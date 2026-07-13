"""
Echter End-to-End-Test gegen fal.ai (kostet ein paar Cent, braucht FAL_KEY + Guthaben).
Beweist submit -> poll -> download mit dem MVP-Modell (Nano Banana, Text->Bild).

    python tests/live_fal_test.py
"""

import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai_gen.backends import get_backend
from ai_gen.backends.base import DONE, ERROR

with open(os.path.join(ROOT, "ai_gen", "manifest.json"), encoding="utf-8") as fh:
    model = json.load(fh)["models"][0]  # nano_banana_2

backend = get_backend(model["backend"])
prompt = "a single red apple on a plain white table, soft studio light, photoreal"
params = {"aspect_ratio": "1:1"}

print("Submit an fal:", model["endpoint"])
job_id = backend.submit(model, prompt, input_paths=[], params=params)
print("job_id:", job_id)

deadline = time.time() + 180
last = None
while time.time() < deadline:
    st = backend.poll(job_id)
    if st.status != last:
        print("  status:", st.status, "" if st.progress is None else "progress={:.0%}".format(st.progress))
        last = st.status
    if st.status == DONE:
        out_dir = os.path.join(ROOT, "_test_output")
        path = backend.download(st.result_url, out_dir, filename="nano_banana_test.png")
        size = os.path.getsize(path)
        print("FERTIG. Datei:", path, "(%d Bytes)" % size)
        sys.exit(0 if size > 0 else 1)
    if st.status == ERROR:
        print("FEHLER:", st.error)
        sys.exit(1)
    time.sleep(2)

print("Timeout nach 180s"); sys.exit(1)
