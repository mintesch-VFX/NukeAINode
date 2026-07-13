"""
upload.py — eigenständiges Script: eine lokale Datei zu fal-Storage hochladen und
die öffentliche URL zurückgeben.

Wird von einem Python mit fal_client ausgeführt (nicht Nukes Python). Manche APIs
(z. B. Magnific/Kling) akzeptieren nur echte URLs, kein base64 — dieses Script
liefert die URL für ein beliebiges lokales Bild/Video.

    python upload.py <datei>

Braucht FAL_KEY in der Umgebung (setzt der Aufrufer). Gibt als letzte Zeile JSON:
    {"url": "https://..."}
"""

import json
import os
import sys

import fal_client


def _fal_error(exc):
    """
    Menschenlesbaren Grund aus einer fal/httpx-Exception ziehen — inkl. Response-Body,
    denn dort steht der eigentliche Grund (z. B. 'User is locked. Exhausted balance').
    """
    resp = getattr(exc, "response", None)
    if resp is not None:
        detail = None
        try:
            detail = resp.json().get("detail")
        except Exception:
            pass
        try:
            body = resp.text
        except Exception:
            body = ""
        msg = detail or body or str(exc)
        return "fal upload failed (HTTP {c}): {m}".format(c=resp.status_code, m=str(msg)[:300])
    return "fal upload failed: " + str(exc)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: upload.py <datei>"}))
        return 2
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(json.dumps({"error": "file not found: " + path}))
        return 1
    try:
        url = fal_client.upload_file(path)
    except Exception as exc:
        print(json.dumps({"error": _fal_error(exc)}))
        return 1
    print(json.dumps({"url": url}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
