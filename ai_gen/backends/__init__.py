"""
backends — austauschbare Adapter pro Anbieter (fal.ai, Vertex, OpenAI).

Jedes Backend erbt von Backend (base.py) und implementiert submit/poll/download.
Die Node bleibt dadurch modellagnostisch: Modellwechsel = anderes Backend, kein Umbau.
"""

from .base import Backend, BackendError, get_backend

__all__ = ["Backend", "BackendError", "get_backend"]
