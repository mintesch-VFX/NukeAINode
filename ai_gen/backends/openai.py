"""
openai.py — Backend-Adapter für OpenAI GPT Image (gpt-image-1).

Anders als fal ist die OpenAI-Bild-API **synchron**: der Request liefert das Bild
direkt (als base64), es gibt keine Queue/kein Polling. Wir fügen uns trotzdem in die
submit/poll/download-Schnittstelle ein: submit() macht den (blockierenden) Request im
Hintergrund-Thread und legt die Bytes ab, poll() meldet sofort DONE, download()
schreibt die Bytes in die Datei.

Endpoints:
  Text->Bild : POST https://api.openai.com/v1/images/generations  (JSON)
  Bild-Edit  : POST https://api.openai.com/v1/images/edits         (multipart/form-data)

Auth: Header  Authorization: Bearer <OPENAI_API_KEY>
Nur Python-Standardbibliothek.
"""

import base64
import json
import math
import mimetypes
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from .base import Backend, BackendError, Status, DONE, ERROR
from .. import config


API_BASE = "https://api.openai.com/v1"

# gpt-image-2 akzeptiert beliebige Größen, solange Breite/Höhe durch 16 teilbar sind.
# Größe aus UI-Seitenverhältnis + Resolution ableiten.
_RATIOS = {
    "1:1": (1, 1), "16:9": (16, 9), "9:16": (9, 16),
    "4:3": (4, 3), "3:4": (3, 4), "21:9": (21, 9),
}
_BASE_FOR_RES = {"1K": 1024, "2K": 2048, "4K": 3840}
_MIN_PIXELS = 1024 * 1024   # gpt-image-2: Mindest-Pixel-Budget (~1 MP)
_MAX_EDGE = 3840            # gpt-image-2: längste Kante max 3840
# Resolution setzt direkt die Quality-Stufe (User-Wunsch: 1K=low, 2K=mid, 4K=high).
_QUALITY_FOR_RES = {"1K": "low", "2K": "medium", "4K": "high"}


def _round16(n):
    n = int(round(n / 16.0)) * 16
    return max(16, n)


def _size(aspect, resolution):
    """
    WxH-String für gpt-image-2: aspect-korrekt, längere Kante = Resolution-Basis,
    aber innerhalb des Pixel-Budgets [MIN..MAX] und durch 16 teilbar.
    (z. B. 1K/16:9 = 1024x576 wäre unter dem Minimum -> wird hochskaliert.)
    """
    base = _BASE_FOR_RES.get(resolution, 1024)
    rw, rh = _RATIOS.get(aspect, (1, 1))
    if rw >= rh:
        w, h = float(base), float(base) * rh / rw
    else:
        w, h = float(base) * rw / rh, float(base)
    if w * h < _MIN_PIXELS:                        # zu klein -> hochskalieren (Aspect bleibt)
        s = math.sqrt(_MIN_PIXELS / (w * h)); w *= s; h *= s
    longest = max(w, h)
    if longest > _MAX_EDGE:                         # zu groß -> längste Kante kappen
        s = _MAX_EDGE / longest; w *= s; h *= s
    return "{w}x{h}".format(w=_round16(w), h=_round16(h))


class OpenAIBackend(Backend):
    name = "openai"

    def __init__(self):
        self._results = {}  # job_id -> image bytes

    def submit(self, model_cfg, prompt, inputs, params):
        key = config.get_key("OPENAI_API_KEY", required=True)
        params = params or {}
        resolution = params.get("resolution", "1K")
        size = _size(params.get("aspect_ratio", "1:1"), resolution)
        # Quality aus der Resolution ableiten (1K=low, 2K=mid, 4K=high).
        quality = params.get("quality") or _QUALITY_FOR_RES.get(resolution, "auto")
        model_id = model_cfg.get("openai_model", "gpt-image-1")

        # GPT Image bearbeitet ein einzelnes Bild -> den ersten angeschlossenen
        # Eingang (kleinster Index, i. d. R. "Start") nehmen.
        start = None
        if inputs:
            start = inputs[min(inputs.keys())]
        if start:
            data = self._edit(key, model_id, prompt, start, size, quality)
        else:
            data = self._generate(key, model_id, prompt, size, quality)

        job_id = "openai-" + uuid.uuid4().hex
        self._results[job_id] = data
        return job_id

    def poll(self, job_id):
        if job_id in self._results:
            return Status(DONE, progress=1.0, result_url="mem://" + job_id)
        return Status(ERROR, error="OpenAI: unbekannte job_id {j!r}".format(j=job_id))

    def download(self, result_url, target_dir, filename=None):
        job_id = result_url.split("://", 1)[1]
        data = self._results.pop(job_id, None)
        if data is None:
            raise BackendError("OpenAI: kein Ergebnis für {j!r}".format(j=job_id))
        if not os.path.isdir(target_dir):
            os.makedirs(target_dir)
        if not filename:
            filename = "result.png"
        path = os.path.join(target_dir, filename)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    # ---- Requests -------------------------------------------------------------

    def _generate(self, key, model_id, prompt, size, quality=None):
        body = {"model": model_id, "prompt": prompt or "", "n": 1}
        if size and size != "auto":
            body["size"] = size
        if quality and quality != "auto":
            body["quality"] = quality
        raw = json.dumps(body).encode("utf-8")
        headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
        resp = self._send(API_BASE + "/images/generations", raw, headers)
        return _first_image_bytes(resp)

    def _edit(self, key, model_id, prompt, image_path, size, quality=None):
        fields = {"model": model_id, "prompt": prompt or "", "n": "1"}
        if size and size != "auto":
            fields["size"] = size
        if quality and quality != "auto":
            fields["quality"] = quality
        files = {"image": image_path}
        body, content_type = _encode_multipart(fields, files)
        headers = {"Authorization": "Bearer " + key, "Content-Type": content_type}
        resp = self._send(API_BASE + "/images/edits", body, headers)
        return _first_image_bytes(resp)

    def _send(self, url, raw, headers):
        req = Request(url, data=raw, headers=headers, method="POST")
        try:
            with urlopen(req, timeout=300) as r:
                text = r.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise BackendError("OpenAI HTTP {c}: {d}".format(c=exc.code, d=detail[:500]))
        except URLError as exc:
            raise BackendError("OpenAI Netzwerkfehler: {r}".format(r=exc.reason))
        try:
            return json.loads(text)
        except ValueError:
            raise BackendError("OpenAI: ungültiges JSON: {t}".format(t=text[:300]))


def _first_image_bytes(resp):
    """Aus der OpenAI-Antwort das erste Bild (base64) als Bytes ziehen."""
    data = (resp or {}).get("data")
    if isinstance(data, list) and data:
        b64 = data[0].get("b64_json")
        if b64:
            return base64.b64decode(b64)
    raise BackendError("OpenAI: kein Bild in der Antwort: {r}".format(r=str(resp)[:300]))


def _encode_multipart(fields, files):
    """Einfaches multipart/form-data (nur Stdlib) für den Edit-Endpoint."""
    boundary = "----aigen" + uuid.uuid4().hex
    crlf = b"\r\n"
    parts = []
    for name, value in fields.items():
        parts.append(b"--" + boundary.encode())
        parts.append(('Content-Disposition: form-data; name="%s"' % name).encode())
        parts.append(b"")
        parts.append(str(value).encode("utf-8"))
    for name, path in files.items():
        fname = os.path.basename(path)
        mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            content = fh.read()
        parts.append(b"--" + boundary.encode())
        parts.append(
            ('Content-Disposition: form-data; name="%s"; filename="%s"' % (name, fname)).encode()
        )
        parts.append(("Content-Type: %s" % mime).encode())
        parts.append(b"")
        parts.append(content)
    parts.append(b"--" + boundary.encode() + b"--")
    parts.append(b"")
    body = crlf.join(parts)
    return body, "multipart/form-data; boundary=" + boundary
