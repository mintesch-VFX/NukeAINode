"""
colorspace.py — den passenden sRGB-Space aus den TATSÄCHLICH vorhandenen
OCIO-Colorspaces eines Nuke-Knobs wählen.

Wird von Read (Ergebnis-Import) und Write (Eingang-Export für die API) gleichermaßen
benutzt, damit beide Seiten dieselbe Kodierung verwenden — sonst geht ein falsch
kodiertes Bild an die API bzw. kommt falsch interpretiert zurück.

fal-Bilder sind display-referred (sRGB, wie am Monitor). In ACES-2.0-Configs
(Nuke Studio / OCIO v2) ist daher der Display-Space "sRGB - Display" die passende,
zur Write-Ausgabe konsistente Wahl. sRGB-Texture und das klassische "sRGB" dienen als
Fallback für Nicht-ACES-Configs.

Braucht das Nuke-Python nicht direkt — es arbeitet nur auf einem übergebenen Knob.
"""

SRGB_PREFS = [
    "sRGB - Display",
    "srgb_display",
    "sRGB Encoded Rec.709 (sRGB)",
    "Utility - sRGB - Texture",
    "Input - Generic - sRGB - Texture",
    "sRGB - Texture",
    "srgb_texture",
    "color_picking",
    "texture_paint",
    "sRGB",  # klassische Nuke-Default-Config (nur als letzter Ausweg)
]


def _options(knob):
    """
    Verfügbare Colorspaces als Liste von (primary_name, {alle Namen/Aliase klein}).
    knob.values() liefert Einträge wie 'primary\\tPfad\\t\\talias1,alias2'.
    """
    result = []
    try:
        raw = list(knob.values())
    except Exception:
        return result
    for entry in raw:
        parts = entry.split("\t")
        primary = parts[0].strip()
        names = {primary.lower()}
        for seg in parts[1:]:
            for alias in seg.split(","):
                alias = alias.strip()
                if alias:
                    names.add(alias.lower())
        result.append((primary, names))
    return result


def apply_srgb(node):
    """
    Setzt den 'colorspace'-Knob der Node (Read oder Write) auf den besten
    vorhandenen sRGB-Space. Liefert den gesetzten Namen oder None.

    Nur Namen aus der echten Options-Liste werden gesetzt — sonst käme beim
    Rendern ein 'Invalid LUT'-Fehler (bloßes "sRGB" existiert z. B. in ACES-2.0
    nicht als gültiger Wert).
    """
    knob = node.knob("colorspace")
    if not knob:
        return None
    options = _options(knob)
    if not options:
        return None
    for want in SRGB_PREFS:
        wl = want.lower()
        for primary, names in options:
            if wl in names:
                try:
                    knob.setValue(primary)
                    return primary
                except Exception:
                    pass
                return None
    return None
