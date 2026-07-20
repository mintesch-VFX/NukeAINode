"""
Schneller Rauch-Test der Nuke-unabhängigen Logik.
Läuft mit reinem System-Python, ohne Nuke, ohne Netz, ohne API-Key.

    python tests/smoke_test.py
"""

import json
import os
import sys

# Projekt-Root (Ordner über tests/) auf den Pfad, damit `import ai_gen` klappt.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from ai_gen import prompt, config
from ai_gen.backends import fal


def check(name, cond):
    print(("  OK  " if cond else " FAIL ") + name)
    if not cond:
        check.failures += 1
check.failures = 0


print("== manifest.json ==")
with open(os.path.join(ROOT, "ai_gen", "manifest.json"), encoding="utf-8") as fh:
    manifest = json.load(fh)
models = manifest["models"]
check("manifest lädt, >=1 Modell", len(models) >= 1)
check("MVP-Modell ist nano_banana_2", models[0]["id"] == "nano_banana_2")
check("Modell hat endpoint", bool(models[0].get("endpoint")))

print("== prompt-@ref-Parsing ==")
check("@ref1/@ref3 -> [0, 2]", prompt.find_refs("a @ref1 b @ref3") == [0, 2])
check("Duplikate entfernt", prompt.find_refs("@ref1 @ref1 @ref2") == [0, 1])
check("Groß/klein egal", prompt.find_refs("@REF2") == [1])
check("kein @ref -> []", prompt.find_refs("nur text") == [])
check(
    "validate meldet zu hohe Referenz",
    len(prompt.validate("@ref3", 1)) == 1,
)
check("validate ok bei genug Eingängen", prompt.validate("@ref1", 2) == [])
# Lücken-Fall: in1+in3 belegt (in2 leer) -> Slots {1,3}; @in3 muss gültig sein.
check("validate @in3 ok bei Slots {1,3}", prompt.validate("@in3 in @in1", [1, 3]) == [])
check("validate @in2 fehlt bei Slots {1,3}", len(prompt.validate("@in2", [1, 3])) == 1)

print("== fal-Hilfsfunktionen (ohne Netz) ==")
check(
    "http-URL wird durchgereicht",
    fal._to_url("https://x/y.png") == "https://x/y.png",
)
res = {"images": [{"url": "https://out/img.png"}]}
check("Ergebnis-URL aus images[]", fal._first_media_url(res) == "https://out/img.png")
check("Ergebnis-URL aus image{}", fal._first_media_url({"image": {"url": "u"}}) == "u")
check("leeres Ergebnis -> None", fal._first_media_url({}) is None)
check("_clean_params filtert Leeres", fal._clean_params({"a": 1, "b": "", "c": None}) == {"a": 1})

print("== config (kein Key gesetzt) ==")
os.environ.pop("FAL_KEY", None)
check("has_key False ohne Key/Datei", config.has_key("FAL_KEY") in (True, False))  # nur Aufrufbarkeit
try:
    config.get_key("DEFINITELY_MISSING_KEY_XYZ", required=True)
    check("MissingKeyError geworfen", False)
except config.MissingKeyError as exc:
    check("MissingKeyError geworfen", True)
    check("Fehlermeldung nennt Pfad", "ai_gen_keys.json" in str(exc))

print()
if check.failures:
    print("FEHLGESCHLAGEN: {n} Checks".format(n=check.failures))
    sys.exit(1)
print("Alle Checks bestanden.")
