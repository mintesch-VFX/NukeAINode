"""
config.py — API-Keys laden, ohne sie je im Script/Gizmo zu speichern.

Lesereihenfolge (erste Fundstelle gewinnt):
  1) Umgebungsvariable (z. B. FAL_KEY, OPENAI_API_KEY, GOOGLE_APPLICATION_CREDENTIALS)
  2) User-Config-Datei ~/.nuke/ai_gen_keys.json  (einfachste Variante für Weitergabe)

So kann jeder Empfänger der Node seinen eigenen Key auf eigene Rechnung nutzen.
"""

import json
import os


# Wo die optionale Key-Datei liegt: ~/.nuke/ai_gen_keys.json
KEYS_FILENAME = "ai_gen_keys.json"


def _nuke_home():
    """Pfad zum .nuke-Verzeichnis des Users (plattformunabhängig)."""
    return os.path.join(os.path.expanduser("~"), ".nuke")


def keys_file_path():
    """Vollständiger Pfad zur optionalen Key-Datei."""
    return os.path.join(_nuke_home(), KEYS_FILENAME)


def _load_keys_file():
    """Liest ~/.nuke/ai_gen_keys.json. Fehlt sie oder ist kaputt -> leeres Dict."""
    path = keys_file_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def get_key(name, required=False):
    """
    Liefert den Key `name` (z. B. "FAL_KEY").

    Reihenfolge: Env-Variable > Key-Datei. Nicht gefunden -> None,
    außer required=True, dann MissingKeyError mit klarer Anleitung.
    """
    value = os.environ.get(name)
    if not value:
        value = _load_keys_file().get(name)

    if not value and required:
        raise MissingKeyError(name)
    return value or None


def has_key(name):
    """True, wenn der Key irgendwo hinterlegt ist."""
    return get_key(name) is not None


# ---- Backend -> benötigter Key -------------------------------------------------

BACKEND_KEYS = {
    "fal": "FAL_KEY",
    "openai": "OPENAI_API_KEY",
    "magnific": "MAGNIFIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


def backend_key_name(backend):
    """Name des API-Keys, den ein Backend braucht (oder None)."""
    return BACKEND_KEYS.get(backend)


def has_backend_key(backend):
    """True, wenn der zum Backend gehörende Key hinterlegt ist."""
    name = BACKEND_KEYS.get(backend)
    return bool(name) and has_key(name)


# ---- Werte/Einstellungen in die Key-Datei schreiben (fürs Setup-Panel) ---------

def save_values(values):
    """
    dict in ~/.nuke/ai_gen_keys.json mergen (Datei/Ordner anlegen).
    Nur nicht-leere Werte werden gesetzt; leere/None löschen den Eintrag.
    """
    path = keys_file_path()
    data = _load_keys_file()
    for k, v in (values or {}).items():
        if v is None or v == "":
            data.pop(k, None)
        else:
            data[k] = v
    folder = os.path.dirname(path)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return path


def get_value(name, default=None):
    """
    Wert NUR aus der Key-Datei lesen (ohne Env) — für Einstellungen wie den
    Standard-Ausgabeordner ('output_dir').
    """
    val = _load_keys_file().get(name)
    return val if val not in (None, "") else default


class MissingKeyError(RuntimeError):
    """Wird geworfen, wenn ein zwingend benötigter Key fehlt."""

    def __init__(self, name):
        self.key_name = name
        super().__init__(
            "Kein API-Key '{name}' gefunden.\n"
            "Trage ihn als Umgebungsvariable ein ODER lege ihn in\n"
            "  {path}\n"
            'als {{"{name}": "dein-key-hier"}} ab.'.format(
                name=name, path=keys_file_path()
            )
        )
