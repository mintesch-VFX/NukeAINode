"""
encode_upload.py — eigenständiges Script: PNG-Sequenz -> mp4 -> fal-Upload.

Wird von einem Python mit OpenCV (cv2) UND fal_client ausgeführt (nicht Nukes
Python). Für Guide-/Referenz-Videos: die in Nuke gerenderte Sequenz wird zu mp4
encodiert und zu fal hochgeladen, damit sie als video_url(s) an die API geht.

    python encode_upload.py <seq_dir> <first> <last> <fps> <out_mp4>

Encodiert bevorzugt als **h264** (yuv420p, faststart) via ffmpeg (imageio-ffmpeg),
weil manche APIs (Kling) MPEG-4/mp4v ablehnen. Fällt auf cv2-mp4v zurück, wenn
ffmpeg nicht verfügbar ist.

Braucht FAL_KEY in der Umgebung (setzt der Aufrufer). Gibt als letzte Zeile JSON:
    {"url": "https://...", "frames": N, "codec": "h264|mp4v"}
"""

import glob
import json
import os
import subprocess
import sys

import cv2
import fal_client


def _encode_h264(files, fps, out_mp4):
    """PNG-Sequenz -> h264-mp4 via ffmpeg (BGR-Frames per stdin). True bei Erfolg."""
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return False
    first = cv2.imread(files[0])
    if first is None:
        return False
    h, w = first.shape[:2]
    cmd = [
        ff, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", "{w}x{h}".format(w=w, h=h), "-r", str(fps), "-i", "-",
        "-an", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out_mp4,
    ]
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for f in files:
            im = cv2.imread(f)
            if im is not None:
                p.stdin.write(im.tobytes())
        p.stdin.close()
        p.wait()
    except Exception:
        return False
    return os.path.isfile(out_mp4) and os.path.getsize(out_mp4) > 1000


def _encode_mp4v(files, fps, out_mp4):
    """Fallback: cv2 mp4v (MPEG-4 Part 2)."""
    first = cv2.imread(files[0])
    h, w = first.shape[:2]
    writer = cv2.VideoWriter(out_mp4, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    for f in files:
        img = cv2.imread(f)
        if img is not None:
            writer.write(img)
    writer.release()


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
    if len(sys.argv) < 6:
        print(json.dumps({"error": "usage: encode_upload.py <seq_dir> <first> <last> <fps> <out_mp4>"}))
        return 2
    seq_dir = sys.argv[1]
    fps = float(sys.argv[4]) or 24.0
    out_mp4 = sys.argv[5]

    files = sorted(glob.glob(os.path.join(seq_dir, "*.png")))
    if not files:
        print(json.dumps({"error": "no frames in " + seq_dir}))
        return 1

    codec = "h264"
    if not _encode_h264(files, fps, out_mp4):
        codec = "mp4v"
        _encode_mp4v(files, fps, out_mp4)

    try:
        url = fal_client.upload_file(out_mp4)
    except Exception as exc:
        print(json.dumps({"error": _fal_error(exc)}))
        return 1
    print(json.dumps({"url": url, "frames": len(files), "codec": codec}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
