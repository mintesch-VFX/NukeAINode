"""
render.py — angeschlossene Eingänge intern rendern und die projektbezogenen
GenAI-Ordner anlegen.

Projektstruktur (fest verdrahtet auf die Studio-Konvention):
    <shot>/NK/<script>.nk        <- das Nuke-Script liegt im NK-Unterordner
    <shot>/GenAI/UPLOAD/         <- hochgeladene Eingänge (was an die API geht)
    <shot>/GenAI/DOWNLOAD/       <- heruntergeladene Ergebnisse

Das Shot-Hauptverzeichnis wird aus dem Script-Pfad abgeleitet: liegt das Script in
einem Ordner namens "NK", ist der Shot dessen Eltern-Ordner. So funktioniert es
automatisch für jeden Shot. Über das UI-Feld "Ausgabe-Ordner" lässt sich stattdessen
ein fester Basis-Pfad erzwingen.

Braucht das Nuke-Python (`import nuke`) — läuft nur innerhalb von Nuke.
"""

import datetime
import os

import nuke


# Viewer-Look, der für die API "eingebacken" wird (= was der User im Viewer sieht).
# Primär wird die AKTIVE Viewer-Transform übernommen (siehe _viewer_transform), damit
# es auf jeder Config stimmt: ACES 2.0 (Nuke 16/17), ACES 1.x (Nuke 14/15), Legacy.
# Die folgenden Listen sind nur der Fallback, falls kein Viewer gelesen werden kann;
# der erste in der aktuellen Config vorhandene Eintrag gewinnt.
PREFERRED_DISPLAYS = ["sRGB - Display", "sRGB"]
PREFERRED_VIEWS = [
    "ACES 2.0 - SDR 100 nits (Rec.709)",  # ACES 2.0 (Nuke 16/17)
    "ACES 1.0 - SDR Video",               # ACES 1.x studio-config (Nuke 14/15)
    "sRGB",                                # Legacy/Nuke-Farbmanagement
]
RAW_COLORSPACE = "data"  # "Raw" — Werte ohne weitere Transform durchreichen


def _try_set(node, knob_name, value):
    """Knob nur setzen, wenn der Wert eine gültige Option ist (sonst Default lassen)."""
    knob = node.knob(knob_name)
    if not knob or not value:
        return False
    try:
        options = {v.split("\t")[0] for v in knob.values()}
        if value in options:
            knob.setValue(value)
            return True
    except Exception:
        try:
            knob.setValue(value)
            return True
        except Exception:
            pass
    return False


def _viewer_transform():
    """
    (display, view) aus dem aktiven Viewer lesen — das ist exakt der Look, den der
    User sieht. Nuke schreibt viewerProcess als '<view> (<display>)' (OCIO-Config)
    bzw. nur '<view>' (Legacy). Der View-Name kann selbst Klammern enthalten
    (z. B. "ACES 2.0 - SDR 100 nits (Rec.709)"), daher an der LETZTEN Klammer trennen.
    Liefert (display|None, view|None); bei Fehlern (None, None).
    """
    try:
        v = nuke.activeViewer()
        vn = v.node() if v else None
        vp = vn["viewerProcess"].value() if vn and vn.knob("viewerProcess") else ""
    except Exception:
        vp = ""
    vp = (vp or "").strip()
    if not vp:
        return None, None
    if vp.endswith(")") and "(" in vp:
        i = vp.rfind("(")
        return (vp[i + 1:-1].strip() or None), (vp[:i].strip() or None)
    return None, vp  # Legacy: nur View-Name, Display bleibt Config-Default


def _first_present(knob, prefer):
    """Ersten Wert aus prefer zurückgeben, der eine gültige Option des Knobs ist."""
    if not knob:
        return None
    try:
        options = {v.split("\t")[0] for v in knob.values()}
    except Exception:
        return None
    for p in prefer:
        if p in options:
            return p
    return None


def make_ocio_display(input_node, invert=False):
    """
    OCIODisplay-Node, der die Viewer-Transform (View + Display) anwendet.
    invert=False: scene-linear -> Monitor-Look (zum Rausrendern für die API).
    invert=True : Monitor-Look -> scene-linear (zum Reimport in den Comp).

    Version-agnostisch: nimmt bevorzugt die aktive Viewer-Transform; sonst den ersten
    in der Config vorhandenen Eintrag aus PREFERRED_*; sonst bleibt die OCIODisplay-
    Default-Transform der Config stehen. Bake und Un-Bake nutzen dieselbe Logik ->
    der Roundtrip ist immer in sich konsistent.
    """
    ocd = nuke.nodes.OCIODisplay(inputs=[input_node])
    v_disp, v_view = _viewer_transform()
    # Display: aktiver Viewer -> bekannte Defaults; View analog.
    if not _try_set(ocd, "display", v_disp):
        _try_set(ocd, "display", _first_present(ocd.knob("display"), PREFERRED_DISPLAYS))
    if not _try_set(ocd, "view", v_view):
        _try_set(ocd, "view", _first_present(ocd.knob("view"), PREFERRED_VIEWS))
    try:
        ocd["invert"].setValue(bool(invert))
    except Exception:
        pass
    return ocd


GENAI_DIR = "GenAI"
IN_DIR = "UPLOAD"      # hochgeladene Eingänge (was an die API geht)
OUT_DIR = "DOWNLOAD"   # heruntergeladene Ergebnisse


def project_root(base=None):
    """
    Liefert das Basis-Verzeichnis für den GenAI-Ordner.

    base : überschreibt alles (fester Basis-Pfad).
    Sonst: der ORDNER, in dem das Nuke-Script liegt -> GenAI/UPLOAD+DOWNLOAD landen
    direkt neben dem Script (pipeline-unabhängig, keine NK-Annahme).
    Ungespeichertes Script ohne base -> None (Aufrufer meldet das dem User).
    """
    if isinstance(base, str) and base.strip():
        return base.strip()

    script = nuke.root().name()
    if script and script != "Root":
        return os.path.dirname(script)
    return None


def genai_dirs(base=None, output_rel=None):
    """
    Liefert (root, in_dir, out_dir) und legt UPLOAD/DOWNLOAD an.

    Drei Modi (in dieser Reihenfolge):
      1) output_rel gesetzt (aus dem Installer): die Basis liegt RELATIV zum
         aktuellen Script-Ordner (z. B. ".." oder "../../conform"). root = normpath(
         script_dir + output_rel); UPLOAD/DOWNLOAD unter root/GenAI. So passt es für
         jeden Shot, egal wo, ohne festen Pfad.
      2) base gesetzt (fester Basis-Pfad): root = base; UPLOAD/DOWNLOAD unter root/GenAI.
      3) sonst: GenAI/UPLOAD+DOWNLOAD direkt NEBEN dem Script.

    In allen drei Modi entsteht <root>/GenAI/UPLOAD und <root>/GenAI/DOWNLOAD.
    """
    if output_rel:
        script = nuke.root().name()
        if not script or script == "Root":
            raise RuntimeError(
                "Kein Script-Pfad. Bitte das Nuke-Script erst speichern — der "
                "Ausgabe-Ordner wird relativ dazu berechnet."
            )
        root = os.path.normpath(os.path.join(os.path.dirname(script), output_rel))
        in_dir = os.path.join(root, GENAI_DIR, IN_DIR)
        out_dir = os.path.join(root, GENAI_DIR, OUT_DIR)
    else:
        root = project_root(base)
        if not root:
            raise RuntimeError(
                "Kein Projektpfad gefunden. Bitte das Nuke-Script speichern "
                "(in den NK-Ordner) oder im Feld 'Ausgabe-Ordner' einen Basis-Pfad setzen."
            )
        in_dir = os.path.join(root, GENAI_DIR, IN_DIR)
        out_dir = os.path.join(root, GENAI_DIR, OUT_DIR)
    for d in (in_dir, out_dir):
        if not os.path.isdir(d):
            os.makedirs(d)
    return root, in_dir, out_dir


def _fit_pixels(src, max_pixels):
    """
    Reformat, das src auf <= max_pixels runterskaliert (Aspect erhalten).
    Liefert die Reformat-Node oder None, wenn nicht nötig/fehlgeschlagen.
    Für Modelle mit Eingangs-Pixel-Limit (z. B. Kling Omni Referenz-Video ~2 MP).
    """
    try:
        fmt = src.format()
        w, h = fmt.width(), fmt.height()
        if w <= 0 or h <= 0 or w * h <= max_pixels:
            return None
        scale = (float(max_pixels) / (w * h)) ** 0.5
        nw = max(2, (int(w * scale) // 2) * 2)
        nh = max(2, (int(h * scale) // 2) * 2)
        rf = nuke.nodes.Reformat(inputs=[src])
        rf["type"].setValue("to box")
        rf["box_width"].setValue(nw)
        rf["box_height"].setValue(nh)
        rf["box_fixed"].setValue(True)
        rf["resize"].setValue("fit")
        rf["black_outside"].setValue(False)
        rf["center"].setValue(True)
        return rf
    except Exception:
        return None


def _reformat_to_format(src, target):
    """
    Reformat 'to box' (fill/crop) auf ein EXAKTES Format -> ändert das Aspect
    (z. B. ultrabreiter Plate 2.67:1 -> 16:9 für Kling Omni, das extreme Aspects
    ablehnt). Beschneidet zentriert. Liefert die Node oder None.
    """
    try:
        tw, th = int(target[0]), int(target[1])
        rf = nuke.nodes.Reformat(inputs=[src])
        rf["type"].setValue("to box")
        rf["box_width"].setValue(tw)
        rf["box_height"].setValue(th)
        rf["box_fixed"].setValue(True)
        rf["resize"].setValue("fill")      # füllt + beschneidet -> exaktes Format
        rf["black_outside"].setValue(False)
        rf["center"].setValue(True)
        return rf
    except Exception:
        return None


def render_inputs(node, in_dir, video_indices=(), video_range=None, max_pixels=None,
                  input_format=None):
    """
    Rendert die angeschlossenen Eingänge (Viewer-Look eingebacken) nach in_dir.
    Liefert {index: value}:
      - Bild-Eingang -> value ist der lokale PNG-Pfad (str)
      - Guide-Video-Eingang (Index in video_indices) -> value ist ein dict
        {"seq_dir", "first", "last", "fps"} (Sequenz über die Comp-Range)

    video_range: optional (first, last) für Guide-Videos statt der vollen Comp-Range
    (z. B. Kling Omni: Referenz-Video muss zur gewählten Dauer passen, max 10s).

    Ein temporärer Write (+ OCIODisplay) wird pro Eingang angelegt, ausgeführt und
    wieder gelöscht — die Node selbst bleibt unangetastet.
    """
    results = {}
    frame = nuke.frame()
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    root = nuke.root()
    first = int(root["first_frame"].value())
    last = int(root["last_frame"].value())
    fps = float(root["fps"].value()) or 24.0
    vfirst, vlast = video_range if video_range else (first, last)

    for i in range(node.inputs()):
        src = node.input(i)
        if src is None:
            continue
        # Eingang ggf. anpassen: input_format = exaktes Format (Aspect-Crop, z. B.
        # Kling Omni braucht 16:9 statt ultrabreit); sonst max_pixels = nur runter-
        # skalieren (Aspect erhalten).
        head, rf = src, None
        if input_format:
            rf = _reformat_to_format(src, input_format)
        elif max_pixels:
            rf = _fit_pixels(src, max_pixels)
        if rf is not None:
            head = rf
        ocd = make_ocio_display(head, invert=False)
        writer = nuke.nodes.Write(inputs=[ocd], channels="rgba")
        try:
            writer["file_type"].setValue("png")
            writer["colorspace"].setValue(RAW_COLORSPACE)  # keine weitere Transform
            if i in video_indices:
                # Guide-Video: ganze Comp-Range als Sequenz rendern.
                seq_dir = os.path.join(in_dir, "{s}_in{n}_seq".format(s=stamp, n=i))
                if not os.path.isdir(seq_dir):
                    os.makedirs(seq_dir)
                writer["file"].setValue(os.path.join(seq_dir, "f.####.png").replace("\\", "/"))
                nuke.execute(writer, vfirst, vlast)
                results[i] = {"seq_dir": seq_dir.replace("\\", "/"), "first": vfirst, "last": vlast, "fps": fps}
            else:
                path = os.path.join(in_dir, "{s}_in{n}.png".format(s=stamp, n=i)).replace("\\", "/")
                writer["file"].setValue(path)
                nuke.execute(writer, frame, frame)
                results[i] = path
        finally:
            nuke.delete(writer)
            nuke.delete(ocd)
            if rf is not None:
                nuke.delete(rf)
    return results
