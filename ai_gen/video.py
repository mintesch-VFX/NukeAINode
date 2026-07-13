"""
video.py — Video (mp4) in eine PNG-Sequenz transcoden, damit Nuke es zuverlässig
liest. Ruft transcode.py über ein Python mit OpenCV (cv2) auf; Nukes Python hat
kein cv2.

Der cv2-Python wird gesucht in dieser Reihenfolge:
  1) Umgebungsvariable AI_GEN_CV2_PYTHON (falls gesetzt)
  2) 'python' / 'python3' aus dem PATH
  3) übliche Windows-Installationspfade
und dabei jeweils getestet, ob 'import cv2' klappt.
"""

import json
import os
import shutil
import subprocess

from . import config


CV2_PYTHON_ENV = "AI_GEN_CV2_PYTHON"


def _tail_error(text, limit=300):
    """
    Letzte aussagekräftige Zeile aus stderr/stdout ziehen (bei Python-Tracebacks die
    Exception-Zeile). Besser als die ersten N Zeichen, die nur den Traceback-Kopf
    zeigen und den eigentlichen Grund abschneiden.
    """
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    return lines[-1][:limit] if lines else ""

_CANDIDATE_PATHS = [
    r"C:\Program Files\Python310\python.exe",
    r"C:\Program Files\Python311\python.exe",
    r"C:\Program Files\Python312\python.exe",
    r"C:\Program Files\Python313\python.exe",
]


def _candidates():
    seen = []
    env = os.environ.get(CV2_PYTHON_ENV)
    if env:
        seen.append(env)
    for name in ("python", "python3"):
        found = shutil.which(name)
        if found:
            seen.append(found)
    seen.extend(_CANDIDATE_PATHS)
    # Duplikate/leere entfernen, Reihenfolge erhalten
    out = []
    for c in seen:
        if c and c not in out:
            out.append(c)
    return out


def find_cv2_python(modules=("cv2",)):
    """Ersten Python-Interpreter finden, der die genannten Module importieren kann."""
    check = "import " + ",".join(modules)
    for exe in _candidates():
        try:
            if exe.lower().endswith(".exe") and not os.path.isfile(exe):
                continue
            res = subprocess.run([exe, "-c", check], capture_output=True, timeout=30)
            if res.returncode == 0:
                return exe
        except Exception:
            continue
    return None


def encode_and_upload(seq_dir, first, last, fps):
    """
    Guide-Video: PNG-Sequenz -> mp4 -> fal-Upload. Liefert die fal-URL.
    Läuft über ein Python mit cv2 UND fal_client (externes Helfer-Python).
    """
    py = find_cv2_python(("cv2", "fal_client"))
    if not py:
        raise RuntimeError(
            "No Python with OpenCV (cv2) AND fal_client found for guide-video upload. "
            "Install them (pip install opencv-python fal-client) or set env {env}."
            .format(env=CV2_PYTHON_ENV)
        )
    out_mp4 = seq_dir.rstrip("/\\") + ".mp4"
    script = os.path.join(os.path.dirname(__file__), "encode_upload.py")
    env = dict(os.environ)
    env["FAL_KEY"] = config.get_key("FAL_KEY", required=True)
    res = subprocess.run(
        [py, script, seq_dir, str(first), str(last), str(fps), out_mp4],
        capture_output=True, text=True, timeout=1200, env=env,
    )
    lines = [l for l in (res.stdout or "").strip().splitlines() if l.strip().startswith("{")]
    info = json.loads(lines[-1]) if lines else {}
    if res.returncode != 0 or info.get("error"):
        detail = info.get("error") or _tail_error(res.stderr or res.stdout)
        raise RuntimeError("Guide-video encode/upload failed: " + str(detail))
    return info["url"]


def upload_file(path):
    """
    Beliebige lokale Datei zu fal-Storage hochladen und die öffentliche URL liefern.
    Für APIs, die nur echte URLs akzeptieren (z. B. Magnific/Kling), kein base64.
    Läuft über ein Python mit fal_client (externes Helfer-Python).
    """
    py = find_cv2_python(("fal_client",))
    if not py:
        raise RuntimeError(
            "No Python with fal_client found for file upload. "
            "Install it (pip install fal-client) or set env {env}.".format(env=CV2_PYTHON_ENV)
        )
    script = os.path.join(os.path.dirname(__file__), "upload.py")
    env = dict(os.environ)
    env["FAL_KEY"] = config.get_key("FAL_KEY", required=True)
    res = subprocess.run(
        [py, script, path],
        capture_output=True, text=True, timeout=600, env=env,
    )
    lines = [l for l in (res.stdout or "").strip().splitlines() if l.strip().startswith("{")]
    info = json.loads(lines[-1]) if lines else {}
    if res.returncode != 0 or info.get("error"):
        detail = info.get("error") or _tail_error(res.stderr or res.stdout)
        raise RuntimeError("File upload failed: " + str(detail))
    return info["url"]


def mp4_to_sequence(mp4_path, seq_dir):
    """
    Transcodiert mp4_path -> <seq_dir>/frame.####.png.
    Liefert (nuke_file_pattern, first, last, fps).
    Wirft RuntimeError mit klarer Anleitung, wenn kein cv2-Python gefunden wird.
    """
    py = find_cv2_python()
    if not py:
        raise RuntimeError(
            "No Python with OpenCV (cv2) found for video transcode. Install it "
            "(pip install opencv-python) or set the env var {env} to such a python.exe."
            .format(env=CV2_PYTHON_ENV)
        )
    script = os.path.join(os.path.dirname(__file__), "transcode.py")
    res = subprocess.run(
        [py, script, mp4_path, seq_dir],
        capture_output=True, text=True, timeout=600,
    )
    lines = [l for l in (res.stdout or "").strip().splitlines() if l.strip().startswith("{")]
    info = json.loads(lines[-1]) if lines else {}
    if res.returncode != 0 or info.get("error"):
        detail = info.get("error") or _tail_error(res.stderr or res.stdout)
        raise RuntimeError("Video transcode failed: " + str(detail))

    pattern = os.path.join(seq_dir, "frame.####.png").replace("\\", "/")
    return pattern, int(info.get("first", 1)), int(info.get("last", 1)), float(info.get("fps", 24.0))
