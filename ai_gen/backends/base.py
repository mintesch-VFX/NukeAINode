"""
base.py — gemeinsame Schnittstelle aller Backends.

Jedes Backend implementiert dieselben drei Schritte, damit die Node modellagnostisch
bleibt:

    submit(model_cfg, prompt, input_paths, params) -> job_id
    poll(job_id)                                   -> Status(status, progress, result_url, error)
    download(result_url, ziel_ordner)              -> lokaler_pfad

submit/poll/download laufen später im Hintergrund-Thread der Node; hier ist bewusst
keine Nuke-/UI-Abhängigkeit drin, damit die Backends pur und testbar bleiben.
"""

import os
from urllib.request import urlopen, Request


# Backend-Status-Konstanten
PENDING = "pending"
RUNNING = "running"
DONE = "done"
ERROR = "error"


class Status(object):
    """Ergebnis eines poll()-Aufrufs."""

    def __init__(self, status, progress=None, result_url=None, error=None):
        self.status = status          # einer von PENDING/RUNNING/DONE/ERROR
        self.progress = progress      # 0.0..1.0 oder None, wenn Anbieter nichts liefert
        self.result_url = result_url  # gesetzt, wenn status == DONE
        self.error = error            # Fehlertext, wenn status == ERROR

    @property
    def is_final(self):
        return self.status in (DONE, ERROR)

    def __repr__(self):
        return "Status({s!r}, progress={p}, result_url={u!r})".format(
            s=self.status, p=self.progress, u=self.result_url
        )


class Backend(object):
    """Basisklasse für alle Anbieter-Adapter."""

    name = "base"

    def submit(self, model_cfg, prompt, input_paths, params):
        """
        Job an den Anbieter schicken. Liefert eine job_id (String), mit der poll()
        später den Fortschritt abfragt.

        model_cfg    : dict aus manifest.json (das ausgewählte Modell)
        prompt       : Prompt-Text (bereits mit aufgelösten @refs, falls nötig)
        input_paths  : Liste lokaler Datei-/URL-Pfade der Eingänge (Reihenfolge = @ref1..N)
        params       : dict der UI-Parameter (aspect_ratio, resolution, ...)
        """
        raise NotImplementedError

    def poll(self, job_id):
        """Aktuellen Status eines Jobs abfragen. Liefert Status()."""
        raise NotImplementedError

    def download(self, result_url, target_dir, filename=None):
        """
        Ergebnis von result_url in target_dir speichern. Liefert den lokalen Pfad.
        Standard-Implementierung reicht für die meisten Anbieter (direkte URL).
        """
        _ensure_dir(target_dir)
        if not filename:
            filename = os.path.basename(result_url.split("?")[0]) or "result.out"
        target_path = os.path.join(target_dir, filename)
        req = Request(result_url, headers={"User-Agent": "nuke-ai-gen/0.1"})
        with urlopen(req) as resp, open(target_path, "wb") as out:
            out.write(resp.read())
        return target_path


class BackendError(RuntimeError):
    """Fehler bei der Anbieter-Kommunikation (HTTP, Auth, ungültige Antwort)."""


def _ensure_dir(path):
    if path and not os.path.isdir(path):
        os.makedirs(path)


# ---- Registry: id (aus manifest "backend") -> Backend-Instanz -------------------

_REGISTRY = {}


def get_backend(name):
    """
    Backend-Instanz nach Name aus dem Manifest ("fal", "vertex", "openai").
    Import erfolgt lazy, damit ein fehlendes Backend nicht die ganze Node blockiert.
    """
    if name in _REGISTRY:
        return _REGISTRY[name]

    if name == "fal":
        from .fal import FalBackend
        instance = FalBackend()
    elif name == "openai":
        from .openai import OpenAIBackend
        instance = OpenAIBackend()
    elif name == "magnific":
        from .magnific import MagnificBackend
        instance = MagnificBackend()
    elif name == "google":
        from .google import GoogleBackend
        instance = GoogleBackend()
    else:
        raise BackendError("Unbekanntes Backend: {n!r}".format(n=name))

    _REGISTRY[name] = instance
    return instance
