"""
ai_gen — Eigenständige Gen-AI-Generierungs-Node für Foundry Nuke.

Manifest-getrieben: Modelle werden in manifest.json beschrieben, die UI baut sich
daraus dynamisch. Backends (fal.ai / Vertex / OpenAI) sind austauschbare Adapter
mit einheitlicher Schnittstelle (siehe backends/base.py).

Die fertige Node läuft eigenständig — ohne Claude, ohne MCP.
"""

__version__ = "0.1.0"
