"""
fal.py — Backend-Adapter für fal.ai (Queue-API).

Nutzt nur die Python-Standardbibliothek (urllib/json/base64), damit die Node auch
im mitgelieferten Nuke-Python ohne pip-Installation läuft.

fal-Queue-Ablauf:
  submit  -> POST https://queue.fal.run/{endpoint}         -> request_id + status/response-URLs
  poll    -> GET  {status_url}                             -> IN_QUEUE / IN_PROGRESS / COMPLETED
  ergebnis-> GET  {response_url}                            -> Modell-Output (z. B. images[].url)

Auth: Header  Authorization: Key <FAL_KEY>
"""

import base64
import json
import mimetypes
import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen, Request

from .base import Backend, BackendError, Status, PENDING, RUNNING, DONE, ERROR
from .. import config


FAL_QUEUE_BASE = "https://queue.fal.run"


class FalBackend(Backend):
    name = "fal"

    def __init__(self):
        # request_id -> {"status_url": ..., "response_url": ...}
        self._jobs = {}

    # ---- öffentliche Schnittstelle ---------------------------------------------

    def submit(self, model_cfg, prompt, inputs, params):
        key = config.get_key("FAL_KEY", required=True)

        # Endpoint kommt bereits aufgelöst rein (aus dem Mode bzw. Fallback).
        endpoint = model_cfg["endpoint"]

        payload = {"prompt": prompt or ""}

        # Nur die vom Manifest deklarierten API-Parameter senden (UI-Key -> API-Feld).
        # Gilt für Text- UND Edit-Endpoint (beide akzeptieren z. B. aspect_ratio).
        api_params = model_cfg.get("api_params", {})
        int_keys = set(model_cfg.get("int_params", []))
        for ui_key, api_field in api_params.items():
            val = (params or {}).get(ui_key)
            if val in (None, ""):
                continue
            if ui_key in int_keys:      # manche Modelle wollen Integer (z. B. duration)
                try:
                    val = int(val)
                except (TypeError, ValueError):
                    pass
            payload[api_field] = val

        # Eingänge per input_map (Index -> API-Feld) einsetzen.
        _apply_inputs(payload, model_cfg.get("input_map", []), inputs, _to_url)

        url = "{base}/{endpoint}".format(base=FAL_QUEUE_BASE, endpoint=endpoint)
        data = self._request(url, key, method="POST", body=payload)

        request_id = data.get("request_id")
        if not request_id:
            raise BackendError("fal: keine request_id in der Antwort: {d}".format(d=data))

        # fal liefert i. d. R. fertige status/response-URLs mit; sonst selbst bauen.
        self._jobs[request_id] = {
            "status_url": data.get("status_url")
            or "{base}/{ep}/requests/{rid}/status".format(
                base=FAL_QUEUE_BASE, ep=endpoint, rid=request_id
            ),
            "response_url": data.get("response_url")
            or "{base}/{ep}/requests/{rid}".format(
                base=FAL_QUEUE_BASE, ep=endpoint, rid=request_id
            ),
        }
        return request_id

    def poll(self, job_id):
        key = config.get_key("FAL_KEY", required=True)
        job = self._jobs.get(job_id)
        if not job:
            raise BackendError("fal: unbekannte job_id {j!r}".format(j=job_id))

        data = self._request(job["status_url"], key, method="GET")
        raw = (data.get("status") or "").upper()

        if raw == "COMPLETED":
            result_url = self._extract_result_url(job, key)
            return Status(DONE, progress=1.0, result_url=result_url)
        if raw == "IN_PROGRESS":
            return Status(RUNNING, progress=_progress_from_logs(data))
        if raw == "IN_QUEUE":
            return Status(PENDING, progress=0.0)
        # Alles andere als Fehler behandeln.
        return Status(ERROR, error="fal-Status: {s!r}".format(s=raw or data))

    # ---- intern ----------------------------------------------------------------

    def _extract_result_url(self, job, key):
        """Fertiges Ergebnis abrufen und die Medien-URL herausziehen."""
        result = self._request(job["response_url"], key, method="GET")
        url = _first_media_url(result)
        if not url:
            raise BackendError("fal: keine Medien-URL im Ergebnis: {r}".format(r=result))
        return url

    def _request(self, url, key, method="GET", body=None):
        headers = {
            "Authorization": "Key {k}".format(k=key),
            "Accept": "application/json",
        }
        raw = None
        if body is not None:
            raw = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = Request(url, data=raw, headers=headers, method=method)
        try:
            with urlopen(req) as resp:
                text = resp.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace") if exc.fp else ""
            raise BackendError(
                "fal HTTP {code} bei {url}: {detail}".format(
                    code=exc.code, url=url, detail=detail[:500]
                )
            )
        except URLError as exc:
            raise BackendError("fal Netzwerkfehler: {r}".format(r=exc.reason))

        if not text:
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise BackendError("fal: ungültiges JSON: {t}".format(t=text[:500]))


# ---- Hilfsfunktionen (rein, ohne State) --------------------------------------

def _apply_inputs(payload, input_map, inputs, to_url):
    """
    Angeschlossene Eingänge ins Payload einsetzen.
    inputs    : {input_index: lokaler_pfad}
    input_map : Liste; Position = Input-Index -> {"field": <api-feld>, "list": bool}
                (leerer/fehlender Eintrag -> dieser Eingang wird ignoriert)
    """
    for idx, path in sorted((inputs or {}).items()):
        if idx >= len(input_map):
            continue
        spec = input_map[idx]
        if not spec or not spec.get("field"):
            continue
        url = to_url(path)
        # "wrap": URL in ein Objekt packen (z. B. Kling elements -> {"frontal_image_url": url}).
        wrap = spec.get("wrap")
        value = {wrap: url} if wrap else url
        if spec.get("list"):
            payload.setdefault(spec["field"], []).append(value)
        else:
            payload[spec["field"]] = value


def _clean_params(params):
    """None/leer aussortieren, damit wir keine leeren Felder an fal schicken."""
    out = {}
    for k, v in (params or {}).items():
        if v is not None and v != "":
            out[k] = v
    return out


def _to_url(path):
    """
    http(s)-URLs unverändert durchreichen; lokale Dateien als Data-URI (base64)
    kodieren. Data-URIs sind der dependency-freie Weg, ohne Upload-Endpoint.
    """
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if path.startswith("data:"):
        return path
    mime = mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        b64 = base64.b64encode(fh.read()).decode("ascii")
    return "data:{mime};base64,{b64}".format(mime=mime, b64=b64)


def _first_media_url(result):
    """
    Aus einer fal-Ergebnisstruktur die erste Medien-URL ziehen.
    Deckt die gängigen Formen ab: images[], image, video, output[].
    """
    if not isinstance(result, dict):
        return None
    for key in ("images", "output", "videos"):
        items = result.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, dict) and first.get("url"):
                return first["url"]
            if isinstance(first, str):
                return first
    for key in ("image", "video"):
        item = result.get(key)
        if isinstance(item, dict) and item.get("url"):
            return item["url"]
    if result.get("url"):
        return result["url"]
    return None


def _progress_from_logs(data):
    """fal liefert selten exakten Fortschritt — falls vorhanden, herausziehen."""
    metrics = data.get("metrics") or {}
    if isinstance(metrics, dict) and isinstance(metrics.get("progress"), (int, float)):
        return float(metrics["progress"])
    return None
