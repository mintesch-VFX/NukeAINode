"""
transcode.py — eigenständiges Script: wandelt ein Video (mp4) in eine PNG-Sequenz.

Wird von einem Python mit OpenCV (cv2) ausgeführt — NICHT von Nukes Python (das
hat kein cv2). Bewusst ohne Abhängigkeit zum ai_gen-Paket, damit es standalone läuft.

    python transcode.py <input.mp4> <out_dir>

Schreibt <out_dir>/frame.0001.png ... und gibt als letzte Zeile JSON aus:
    {"first": 1, "last": N, "count": N, "fps": 24.0}

Grund: Nukes mov-Reader indiziert manche h264-mp4s (z. B. von fal/Seedance) falsch
und sieht nur 1 Frame; eine PNG-Sequenz liest Nuke zuverlässig.
"""

import json
import os
import sys

import cv2


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: transcode.py <mp4> <out_dir>"}))
        return 2
    mp4, out_dir = sys.argv[1], sys.argv[2]
    os.makedirs(out_dir, exist_ok=True)

    cap = cv2.VideoCapture(mp4)
    if not cap.isOpened():
        print(json.dumps({"error": "cannot open " + mp4}))
        return 1

    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    count = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        count += 1
        # cv2 liest/schreibt BGR konsistent -> die PNG sieht farblich korrekt aus.
        cv2.imwrite(os.path.join(out_dir, "frame.%04d.png" % count), frame)
    cap.release()

    if count == 0:
        print(json.dumps({"error": "no frames decoded"}))
        return 1
    print(json.dumps({"first": 1, "last": count, "count": count, "fps": fps}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
