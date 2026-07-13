"""
google.py — Backend-Adapter für die Google Gemini-API (Veo-Video, direkt).

Grund: 1080p-Video direkt bei Google (Veo 3.1) ohne fal-Umweg/Aufschlag. Der Key
ist ein AI-Studio-Key (GOOGLE_API_KEY), pay-as-you-go.

Ablauf (async, Long-Running Operation):
  submit -> POST .../models/{model}:predictLongRunning  -> {"name": "operations/..."}
  poll   -> GET  .../v1beta/{operation_name}            -> done + response...video.uri
  dl     -> GET  video.uri  (mit Auth-Header)           -> mp4-Bytes

Auth: Header  x-goog-api-key: <GOOGLE_API_KEY>

Besonderheit ggü. den anderen Backends:
- Das Start-Bild geht als base64 (bytesBase64Encoded) direkt ins Payload (kein Upload).
- Die fertige Video-URI ist nur MIT Auth-Header ladbar -> eigenes download().

Nur Python-Standardbibliothek.
"""

import base64
import json
import mimetypes
import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from .base import Backend, BackendError, Status, PENDING, RUNNING, DONE, ERROR, _ensure_dir
from .. import config


API_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GoogleBackend(Backend):
    name = "google"

    def __init__(self):
        # operation_name schon vom Submit bekannt; poll baut die URL daraus.
        self._jobs = {}

    # ---- öffentliche Schnittstelle ---------------------------------------------

    def submit(self, model_cfg, prompt, inputs, params):
        key = config.get_key("GOOGLE_API_KEY", required=True)
        model = model_cfg.get("google_model") or model_cfg.get("endpoint")

        instance = {"prompt": prompt or ""}
        # Veo image-to-video: erstes angeschlossenes Bild als Startframe (base64).
        start = _first_input(inputs)
        if start:
            instance["image"] = _image_field(start)

        # "allow_adult" gilt für Text→Video UND Bild→Video; "allow_all" lehnt Veo
        # bei Bild→Video ab (HTTP 400) — daher der universell gültige Wert.
        parameters = {"personGeneration": "allow_adult"}
        # Manifest-api_params (UI-Key -> API-Feld) landen im parameters-Objekt.
        api_params = model_cfg.get("api_params", {})
        int_keys = set(model_cfg.get("int_params", []))
        for ui_key, api_field in api_params.items():
            val = (params or {}).get(ui_key)
            if val in (None, ""):
                continue
            if ui_key in int_keys:
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    pass
            parameters[api_field] = val

        payload = {"instances": [instance], "parameters": parameters}
        url = "{base}/models/{model}:predictLongRunning".format(base=API_BASE, model=model)
        data = self._request(url, key, method="POST", body=payload)

        op = data.get("name")
        if not op:
            raise BackendError("Google: keine operation-name in der Antwort: {d}".format(d=data))
        self._jobs[op] = True
        return op

    def poll(self, job_id):
        key = config.get_key("GOOGLE_API_KEY", required=True)
        url = "{base}/{op}".format(base=API_BASE, op=job_id)
        data = self._request(url, key, method="GET")

        if not data.get("done"):
            return Status(RUNNING, progress=None)
        if data.get("error"):
            return Status(ERROR, error="Google: {e}".format(e=data["error"]))
        uri = _dig(data, "response", "generateVideoResponse", "generatedSamples", 0, "video", "uri")
        if not uri:
            raise BackendError("Google: done, aber keine Video-URI: {d}".format(d=str(data)[:500]))
        return Status(DONE, progress=1.0, result_url=uri)

    def download(self, result_url, target_dir, filename=None):
        """Veo-URI ist nur mit Auth-Header ladbar -> eigenes download() mit Key."""
        key = config.get_key("GOOGLE_API_KEY", required=True)
        _ensure_dir(target_dir)
        if not filename:
            filename = "result.mp4"
        target_path = os.path.join(target_dir, filename)
        req = Request(result_url, headers={"x-goog-api-key": key})
        try:
            with urlopen(req, timeout=300) as resp, open(target_path, "wb") as out:
                out.write(resp.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise BackendError("Google DL HTTP {c}: {d}".format(c=exc.code, d=detail[:300]))
        except URLError as exc:
            raise BackendError("Google DL Netzwerkfehler: {r}".format(r=exc.reason))
        return target_path

    # ---- intern ----------------------------------------------------------------

    def _request(self, url, key, method="GET", body=None):
        headers = {"x-goog-api-key": key, "Accept": "application/json"}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = Request(url, data=raw, headers=headers, method=method)
        try:
            with urlopen(req, timeout=120) as resp:
                text = resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise BackendError(
                "Google HTTP {code} bei {url}: {detail}".format(
                    code=exc.code, url=url, detail=detail[:500]
                )
            )
        except URLError as exc:
            raise BackendError("Google Netzwerkfehler: {r}".format(r=exc.reason))
        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise BackendError("Google: ungültiges JSON: {t}".format(t=text[:500]))


# ---- Hilfsfunktionen (rein, ohne State) --------------------------------------

def _first_input(inputs):
    """Kleinster angeschlossener Eingang (Startframe), sonst None."""
    if not inputs:
        return None
    return inputs[min(inputs.keys())]


def _image_field(path):
    """Lokales Bild als {bytesBase64Encoded, mimeType} kodieren."""
    mime = mimetypes.guess_type(path)[0] or "image/png"
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return {"bytesBase64Encoded": b64, "mimeType": mime}


def _dig(data, *keys):
    """Verschachtelten Wert holen; Integer-Keys indizieren Listen. None wenn weg."""
    cur = data
    for k in keys:
        if isinstance(k, int):
            if not isinstance(cur, (list, tuple)) or k >= len(cur):
                return None
            cur = cur[k]
        else:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
    return cur
