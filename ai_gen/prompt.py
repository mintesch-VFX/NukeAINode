"""
prompt.py — @-Referenzen im Prompt-Text parsen und auf angeschlossene Eingänge mappen.

Beispiel-Prompt:
    "Mache @ref1 nächtlich, im Stil von @ref2"

@ref1 = erster angeschlossener Eingang, @ref2 = zweiter, usw. (1-basiert, wie im UI).
Das Parsen ist bewusst backend-unabhängig: es liefert die referenzierten Eingangs-
Indizes; das Mapping auf konkrete API-Felder macht das jeweilige Backend.
"""

import re


# @in1, @in2, ... (bevorzugt, passt zu den Eingangs-Namen in1..in4) — auch @ref1
# als Alias. 1-basierte Referenz auf einen angeschlossenen Eingang.
_REF_PATTERN = re.compile(r"@(?:in|ref)(\d+)", re.IGNORECASE)


def find_refs(prompt_text):
    """
    Liefert die im Prompt referenzierten Eingangs-Indizes in Reihenfolge des
    ersten Auftretens, 0-basiert (für Array-Zugriff), ohne Duplikate.

    "@ref1 und @ref3 und nochmal @ref1" -> [0, 2]
    """
    seen = []
    for match in _REF_PATTERN.finditer(prompt_text or ""):
        idx = int(match.group(1)) - 1
        if idx >= 0 and idx not in seen:
            seen.append(idx)
    return seen


_ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth"]


def resolve_for_api(prompt_text):
    """
    Ersetzt @refN im Prompt durch natürliche Bezüge, die Bild-Modelle verstehen:
    @ref1 -> "the first image", @ref2 -> "the second image", ...

    Die Eingänge selbst werden separat als image_urls (in Eingangs-Reihenfolge)
    mitgeschickt; diese Ersetzung macht nur den Prompt-Text lesbar fürs Modell.
    """
    def _repl(match):
        n = int(match.group(1))
        if 1 <= n <= len(_ORDINALS):
            return "the {ord} image".format(ord=_ORDINALS[n - 1])
        return "image {n}".format(n=n)

    return _REF_PATTERN.sub(_repl, prompt_text or "")


def validate(prompt_text, num_inputs):
    """
    Prüft, ob alle @refN im Prompt auf tatsächlich vorhandene Eingänge zeigen.

    Gibt eine Liste menschenlesbarer Fehlermeldungen zurück (leer = alles ok).
    """
    errors = []
    for match in _REF_PATTERN.finditer(prompt_text or ""):
        n = int(match.group(1))
        if n < 1:
            errors.append("@in{n}: Referenzen beginnen bei @in1.".format(n=n))
        elif n > num_inputs:
            errors.append(
                "@in{n} zeigt auf Eingang {n}, es sind aber nur {have} "
                "angeschlossen.".format(n=n, have=num_inputs)
            )
    return errors
