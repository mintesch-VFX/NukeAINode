"""
nuke_node.py — die eigentliche AI-Gen-Node in Nuke (Group + Knob-UI + Generierung).

MVP-Stufe: ein Modell (Nano Banana), Referenz-Eingänge + @ref-Auflösung, Prompt,
Generate-Button, Live-Status/Timer. Async: Rendern der Eingänge im Main-Thread,
API-Roundtrip im Hintergrund-Thread, UI/Graph-Updates via nuke.executeInMainThread.

Braucht das Nuke-Python (`import nuke`).
"""

import base64
import datetime
import json
import os
import threading
import time
import traceback

import nuke

from . import config, render, video
from . import prompt as prompt_mod
from .backends import get_backend
from .backends.base import DONE, ERROR


_MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "manifest.json")

# Eingänge werden schlicht nummeriert (in1..in4); welche Rolle ein Eingang im
# aktuellen Modell/Mode hat, zeigt der "Inputs"-Hinweistext in der Node.
INPUT_NAMES = ["in1", "in2", "in3", "in4"]
NUM_INPUTS = len(INPUT_NAMES)

LEGAL_TEXT = {
    "green": "\U0001F7E2 cleared for use",
    "yellow": "\U0001F7E1 only with proper contract",
    "red": "\U0001F534 not approved",
}


# ---- Manifest ------------------------------------------------------------------

def load_models():
    with open(_MANIFEST_PATH, encoding="utf-8") as fh:
        return json.load(fh)["models"]


def _model_by_label(label):
    for m in load_models():
        if m["label"] == label:
            return m
    return load_models()[0]


# ---- Node bauen ----------------------------------------------------------------

def build_node():
    """Legt eine neue AI_Gen-Node (Group) mit Referenz-Eingängen und Knob-UI an."""
    models = load_models()
    # Nur Modelle anzeigen, deren Backend-Key hinterlegt ist (siehe GenAI > Setup).
    avail = [m for m in models if config.has_backend_key(m["backend"])]
    labels = [m["label"] for m in avail] if avail else ["— set API keys: GenAI > Setup —"]

    group = nuke.createNode("Group", inpanel=False)
    try:
        group.setName("GenAI")
    except Exception:
        pass  # Nuke vergibt bei Kollision selbst einen eindeutigen Namen

    # Innenleben: N Eingänge + schwarzer Platzhalter am Output
    group.begin()
    for i in range(NUM_INPUTS):
        inp = nuke.nodes.Input()
        inp.setName(INPUT_NAMES[i])
    placeholder = nuke.nodes.Constant()
    placeholder.setName("placeholder")
    placeholder["color"].setValue([0, 0, 0, 1])
    out = nuke.nodes.Output()
    out.setInput(0, placeholder)
    group.end()

    # UI-Knobs
    group.addKnob(nuke.Tab_Knob("ai_tab", "AI Gen"))

    model_knob = nuke.Enumeration_Knob("model", "Model", labels)
    group.addKnob(model_knob)

    legal_knob = nuke.Text_Knob("legal", "Rights", "")
    group.addKnob(legal_knob)

    # Startwerte NICHT " ": Nuke fixiert die Pulldown-Breite bei Erstellung und
    # vergrößert sie bei setValues() nicht mehr -> breiter Platzhalter, sonst wird
    # z. B. "1080p" auf "10i" abgeschnitten. Die echten Werte setzt _apply_model_params.
    mode_knob = nuke.Enumeration_Knob("mode", "Mode", ["Reference -> Video"])
    mode_knob.setTooltip("Generation mode (model-specific). Changes how the inputs are used.")
    group.addKnob(mode_knob)

    mode_hint = nuke.Text_Knob("mode_hint", "Inputs", "")
    mode_hint.setTooltip("What the connected inputs in1..in4 mean for the current model/mode.")
    group.addKnob(mode_hint)

    group.addKnob(nuke.Text_Knob("div_prompt", ""))  # Trennlinie

    prompt_knob = nuke.Multiline_Eval_String_Knob("prompt", "Prompt", "")
    prompt_knob.setTooltip("Refer to the connected inputs with @in1..@in4 "
                           "(Kling elements: @Element1/@Element2).")
    group.addKnob(prompt_knob)

    # Parameter-Knobs immer anlegen; Werte/Sichtbarkeit richten sich nach dem
    # gewählten Modell (siehe _apply_model_params, auch bei Modellwechsel).
    aspect_knob = nuke.Enumeration_Knob("aspect_ratio", "Aspect Ratio", ["16:9"])
    aspect_knob.setTooltip("Output aspect ratio sent to the model. Match your plate (e.g. 16:9).")
    group.addKnob(aspect_knob)

    res_knob = nuke.Enumeration_Knob("resolution", "Resolution", ["1080p"])
    group.addKnob(res_knob)

    dur_knob = nuke.Enumeration_Knob("duration", "Duration (s)", [" "])
    dur_knob.setTooltip("Video length in seconds.")
    group.addKnob(dur_knob)

    qual_knob = nuke.Enumeration_Knob("quality", "Quality", ["medium"])
    qual_knob.setTooltip("Image quality (GPT). Higher = better but more expensive.")
    group.addKnob(qual_knob)

    cost_knob = nuke.Text_Knob("cost_est", "Est. cost", "")
    cost_knob.setTooltip(
        "Rough estimate for the current settings.\n"
        "Magnific = credits (~€0.0005/credit); fal/OpenAI = approx. USD."
    )
    group.addKnob(cost_knob)

    out_dir_knob = nuke.File_Knob("out_dir", "Output Folder")
    out_dir_knob.setTooltip(
        "Empty = use the installer path setting (or GenAI/UPLOAD + DOWNLOAD next to the .nk).\n"
        "Set = fixed base path; GenAI/UPLOAD + DOWNLOAD are created underneath it."
    )
    group.addKnob(out_dir_knob)

    group.addKnob(nuke.Text_Knob("div_go", ""))  # Trennlinie vor der Aktion

    btn = nuke.PyScript_Knob(
        "generate", "  Generate  ",
        "import ai_gen.nuke_node as N; N.generate(nuke.thisNode())",
    )
    group.addKnob(btn)

    group.addKnob(nuke.Text_Knob("status", "Status", "ready"))

    last_out = nuke.File_Knob("last_output", "Last Result")
    last_out.setTooltip("Path of the most recent generation (informational; editing has no effect).")
    group.addKnob(last_out)

    # ---- History / Extract --------------------------------------------------
    group.addKnob(nuke.Text_Knob("div_hist", "History"))

    gen_sel = nuke.Enumeration_Knob("gen_select", "Generation", [" "])
    gen_sel.setTooltip("Switch between this node's past generations.")
    group.addKnob(gen_sel)

    prev_btn = nuke.PyScript_Knob(
        "gen_prev", "  < Prev  ",
        "import ai_gen.nuke_node as N; N.gen_step(nuke.thisNode(), -1)")
    group.addKnob(prev_btn)
    next_btn = nuke.PyScript_Knob(
        "gen_next", "  Next >  ",
        "import ai_gen.nuke_node as N; N.gen_step(nuke.thisNode(), 1)")
    next_btn.clearFlag(nuke.STARTLINE)  # gleiche Zeile wie Prev
    group.addKnob(next_btn)

    extract_btn = nuke.PyScript_Knob(
        "extract", "  Extract to Read  ",
        "import ai_gen.nuke_node as N; N.extract(nuke.thisNode())")
    extract_btn.setTooltip("Bake the shown generation into a standalone Read node in the comp.")
    group.addKnob(extract_btn)

    restore_btn = nuke.PyScript_Knob(
        "restore_settings", "  Restore Settings  ",
        "import ai_gen.nuke_node as N; N.restore_settings(nuke.thisNode())")
    restore_btn.setTooltip(
        "Load the shown generation's model, mode, prompt and parameters back into the "
        "controls above. Does NOT re-run — press Generate afterwards to reproduce it.")
    group.addKnob(restore_btn)

    hist_store = nuke.String_Knob("history", "history", "")
    hist_store.setVisible(False)  # interner JSON-Speicher der Generierungen
    group.addKnob(hist_store)

    xcnt = nuke.Int_Knob("extract_count", "extract_count")
    xcnt.setVisible(False)  # monotoner Zähler für eindeutige Extract-Namen
    group.addKnob(xcnt)

    _apply_model_params(group, avail[0] if avail else models[0])
    update_legal(group)
    return group


def _apply_model_params(node, model):
    """
    Mode-Dropdown + Parameter-Knobs aufs Modell einstellen (beim Modellwechsel).
    Setzt das Mode-Dropdown auf den Default-Mode, dann die Param-Knobs.
    """
    mode_knob = node.knob("mode")
    modes = model.get("modes") or []
    if mode_knob:
        if len(modes) > 1:
            try:
                mode_knob.setValues([m["label"] for m in modes])
                mode_knob.setValue(model.get("default_mode", modes[0]["label"]))
            except Exception:
                pass
            mode_knob.setVisible(True)
        else:
            mode_knob.setVisible(False)
    _apply_mode_params(node, model)


def _apply_mode_params(node, model):
    """
    Parameter-Knobs (aspect/resolution/duration/quality) auf das aktuelle Mode/Modell
    einstellen. Werte kommen bevorzugt aus dem aktuellen Mode (z. B. Kling: Start/End
    kann 4K, Reference-Video nicht). Ändert das Mode-Dropdown selbst NICHT — daher
    auch beim Mode-Wechsel aufrufbar, ohne den Mode zurückzusetzen.
    """
    _update_mode_hint(node, model)
    specs = [
        ("aspect_ratio", "aspect_ratios", "default_aspect_ratio"),
        ("resolution", "resolutions", "default_resolution"),
        ("duration", "durations", "default_duration"),
        ("quality", "qualities", "default_quality"),
    ]
    for knob_name, values_key, default_key in specs:
        knob = node.knob(knob_name)
        if not knob:
            continue
        values = _mode_get(model, node, values_key)
        if values:
            try:
                is_res = (knob_name == "resolution")
                knob.setValues([_res_label(v) for v in values] if is_res else list(values))
                default = _mode_get(model, node, default_key, values[0])
                if knob_name == "duration":
                    # Standard = so lang wie der Shot (Frame-Range/fps), gerundet.
                    picked = _pick_duration(values, _shot_seconds())
                    if picked is not None:
                        default = picked
                knob.setValue(_res_label(default) if is_res else default)
            except Exception:
                pass
            knob.setVisible(True)
        else:
            knob.setVisible(False)
    _update_cost(node, model)


def _shot_seconds():
    """Länge des aktuellen Shots in Sekunden aus Frame-Range/fps."""
    try:
        r = nuke.root()
        first = int(r["first_frame"].value())
        last = int(r["last_frame"].value())
        fps = float(r["fps"].value()) or 24.0
        return max(1.0, (last - first + 1) / fps)
    except Exception:
        return None


def _pick_duration(values, shot_sec):
    """
    Aus den erlaubten Duration-Werten (Strings, evtl. inkl. 'auto') den kleinsten
    numerischen Wert >= Shot-Länge wählen (deckt den Shot ab); sonst den längsten.
    """
    if shot_sec is None:
        return None
    nums = []
    for v in values:
        try:
            nums.append((int(v), v))
        except (TypeError, ValueError):
            pass  # 'auto' u. Ä. überspringen
    if not nums:
        return None
    nums.sort()
    for n, v in nums:
        if n >= shot_sec - 0.001:
            return v
    return nums[-1][1]


def _current_mode(model, node):
    """Aktuell gewählten Mode-Eintrag (dict) liefern, sonst None."""
    modes = model.get("modes") or []
    if not modes:
        return None
    label = node["mode"].value() if node.knob("mode") else None
    return next((m for m in modes if m["label"] == label), modes[0])


def _mode_get(model, node, key, default=None):
    """Wert aus dem aktuell gewählten Mode (falls dort gesetzt), sonst aus dem Modell.
    So können Modes z. B. Auflösung/Dauer/Status-Pfad/Flags eigenständig überschreiben."""
    mode = _current_mode(model, node)
    if isinstance(mode, dict) and key in mode:
        return mode[key]
    return model.get(key, default)


def _update_mode_hint(node, model):
    """Kurzen Hinweistext zum aktuellen Mode unter dem Dropdown anzeigen."""
    hint_knob = node.knob("mode_hint")
    if not hint_knob:
        return
    mode = _current_mode(model, node)
    text = (mode.get("hint") if mode else None) or model.get("hint", "")
    if text:
        hint_knob.setValue(text)
        hint_knob.setVisible(True)
    else:
        hint_knob.setValue("")
        hint_knob.setVisible(False)


CR_TO_EUR = 0.0005  # grobe Umrechnung Magnific-Credits -> Euro (plan-abhängig)

# Ziel-Formate für Modelle, die Eingänge aufs Aspect beschneiden müssen (Kling Omni
# lehnt extreme Seitenverhältnisse ab). ~2 MP, unter Klings 2.086-MP-Limit.
_ASPECT_FORMAT = {"16:9": (1920, 1080), "9:16": (1080, 1920), "1:1": (1440, 1440)}

def _res_label(v):
    # Nuke schätzt die Pulldown-Breite zu knapp und schneidet z. B. "1080p" auf
    # "108" ab. Den Wert mit Leerzeichen auf feste Breite auffüllen zwingt den
    # Pulldown breit genug; zentriert wirkt es ausgewogen (statt links "verloren").
    # Nuke schneidet rechts ab -> Breite knapp halten, damit "1080p" nicht clippt.
    # Beim Lesen: strip() entfernt die Füll-Leerzeichen (Werte haben keine internen).
    return v.center(9)


def _estimate_cost(model, node):
    """Kurzer Kosten-Schätztext für die aktuellen Einstellungen (Credits bzw. USD)."""
    cost = model.get("cost")
    if not cost:
        return ""

    def _res():
        k = node.knob("resolution")
        return k.value().strip() if k and k.visible() else None

    unit = cost.get("unit")
    if unit == "cr":
        if "per_image" in cost:
            table = cost["per_image"]
            cr = table.get(_res()) or min(table.values())
            return "≈ {c} cr  (≈ €{e:.2f})".format(c=cr, e=cr * CR_TO_EUR)
        if "per_sec" in cost:
            table = cost["per_sec"]
            ps = table.get(_res()) or max(table.values())
            dk = node.knob("duration")
            try:
                d = int(dk.value()) if dk and dk.visible() else 5
            except (TypeError, ValueError):
                d = 5
            cr = ps * d
            return "≈ {c} cr  (≈ €{e:.2f})  — {d}s".format(
                c=cr, e=cr * CR_TO_EUR, d=d)
    if unit == "usd":
        return cost.get("note", "")
    return ""


def _update_cost(node, model):
    """Kosten-Knob auf die aktuelle Schätzung setzen (leer -> ausblenden)."""
    kb = node.knob("cost_est")
    if not kb:
        return
    txt = _estimate_cost(model, node)
    try:
        kb.setValue(txt)
        kb.setVisible(bool(txt))
    except Exception:
        pass


def resolve_endpoint(model, node, has_inputs):
    """
    (endpoint, input_map) für den aktuellen Zustand bestimmen.
    Mit Modes: der gewählte Mode. Ohne Modes: mit Input edit_endpoint, sonst endpoint.
    """
    mode = _current_mode(model, node)
    if mode is not None:
        return mode["endpoint"], mode.get("input_map", [])
    if has_inputs and model.get("edit_endpoint"):
        return model["edit_endpoint"], model.get("input_map", [])
    return model["endpoint"], (model.get("input_map", []) if has_inputs else [])


def update_legal(node):
    """Rechts-Ampel im UI auf das aktuell gewählte Modell setzen."""
    try:
        model = _model_by_label(node["model"].value())
        node["legal"].setValue(LEGAL_TEXT.get(model.get("legal"), ""))
    except Exception:
        pass


# ---- Generierung ---------------------------------------------------------------

def generate(node):
    """Generate-Button: Eingänge rendern (Main-Thread), dann Job im Hintergrund."""
    try:
        model = _model_by_label(node["model"].value())
        if not config.has_backend_key(model["backend"]):
            _set_status(node, "Missing {k} — open GenAI > Setup to add your API keys.".format(
                k=config.backend_key_name(model["backend"]) or model["backend"]))
            return
        prompt_text = node["prompt"].value() or ""

        connected = [i for i in range(node.inputs()) if node.input(i) is not None]
        # 1-basierte Slot-Nummern der belegten Eingänge (mit Lücken, z. B. in1+in3 ->
        # [1, 3]) — so ist @inN fest an den physischen Slot N gekoppelt.
        connected_slots = [i + 1 for i in connected]
        errors = prompt_mod.validate(prompt_text, connected_slots)
        if errors:
            _set_status(node, "Prompt error: " + "; ".join(errors))
            return
        if not prompt_text.strip() and not connected:
            _set_status(node, "Enter a prompt or connect an input.")
            return
        if model.get("requires_input") and not connected:
            _set_status(node, "{label} requires a connected input image.".format(label=model["label"]))
            return

        # Rechts-Warnung bei rot geflaggten Modellen (z. B. Kling: behält Trainingsrecht).
        if model.get("legal") == "red":
            warn = ("⚠ {label} is rights-flagged RED (e.g. keeps training rights "
                    "on your input/output).\nGenerate anyway?".format(label=model["label"]))
            if not nuke.ask(warn):
                _set_status(node, "cancelled (rights-flagged model)")
                return

        # Endpoint + Input-Mapping aus dem aktuellen Mode (oder Fallback) auflösen.
        endpoint, input_map = resolve_endpoint(model, node, bool(connected))
        # Welche angeschlossenen Eingänge sind Guide-Videos (input_map ... video:true)?
        video_indices = set(
            i for i in connected
            if i < len(input_map) and input_map[i] and input_map[i].get("video")
        )

        _set_status(node, "rendering inputs ...")
        # Ausgabe-Ort: Node-out_dir (fest) > output_rel (relativ zum Script, aus dem
        # Installer) > output_dir (fester Default) > automatisch aus dem Shot.
        base = node["out_dir"].value() if node.knob("out_dir") else None
        base = base.strip() if base else ""
        output_rel = None
        if not base:
            output_rel = config.get_value("output_rel")
            if not output_rel:
                base = config.get_value("output_dir") or ""
        root, in_dir, outputs_dir = render.genai_dirs(base=(base or None), output_rel=output_rel)

        # Manche Modelle (Kling Omni) verlangen ein Referenz-Video passend zur
        # gewählten Dauer (max 10s) statt der vollen Comp-Range.
        video_range = None
        force_duration = None
        if _mode_get(model, node, "ref_video_matches_duration") and node.knob("duration"):
            try:
                dur = int((node["duration"].value() or "5").strip())
            except (TypeError, ValueError):
                dur = 5
            r = nuke.root()
            vf = int(r["first_frame"].value())
            vfps = float(r["fps"].value()) or 24.0
            vlast = min(vf + int(round(dur * vfps)) - 1, int(r["last_frame"].value()))
            video_range = (vf, vlast)
            # Referenz-Video und Output-Dauer müssen übereinstimmen (Kling maxDelta):
            # ist die Comp kürzer als die gewählte Dauer, Dauer entsprechend kappen.
            ref_secs = (vlast - vf + 1) / vfps
            force_duration = str(max(3, min(dur, int(round(ref_secs)))))

        # Kling Omni: Eingänge aufs Ziel-Seitenverhältnis beschneiden (extreme
        # Aspects werden abgelehnt) — Format aus dem aspect_ratio-Knob.
        input_format = None
        if _mode_get(model, node, "crop_inputs_to_aspect") and node.knob("aspect_ratio"):
            ar = node["aspect_ratio"].value() or "16:9"
            input_format = _ASPECT_FORMAT.get(ar, (1920, 1080))

        inputs = render.render_inputs(node, in_dir, video_indices=video_indices,
                                      video_range=video_range,
                                      max_pixels=_mode_get(model, node, "max_input_pixels"),
                                      input_format=input_format)

        # UI-Parameter einsammeln (nur sichtbare Knobs des aktuellen Modells).
        params = {}
        for pk in ("aspect_ratio", "resolution", "duration", "quality"):
            knob = node.knob(pk)
            if knob and knob.visible():
                val = knob.value()
                if pk == "resolution":
                    val = val.strip()  # Füll-Leerzeichen weg -> exakter API-Wert
                params[pk] = val
        if force_duration is not None:
            params["duration"] = force_duration  # an die Referenz-Video-Länge angeglichen

        api_prompt = prompt_mod.resolve_for_api(prompt_text.strip())

        # Aufgelösten Endpoint/Input-Map in eine Modell-Kopie legen (Backend nutzt sie direkt).
        active = dict(model)
        active["endpoint"] = endpoint
        active["input_map"] = input_map
        active["edit_endpoint"] = None
        # Mode-spezifische Felder in die Modell-Kopie ziehen (Status-Pfad, guide_fps).
        active["status_endpoint"] = _mode_get(model, node, "status_endpoint")
        active["guide_fps"] = _mode_get(model, node, "guide_fps", 24)
        # Konstante API-Felder (z. B. generate_audio=false); Mode darf das Modell überschreiben.
        active["api_static"] = _mode_get(model, node, "api_static")
        # Mode kann eigene api_params vorgeben (z. B. Edit-Endpoint ohne aspect/duration).
        _mode = _current_mode(model, node)
        if _mode is not None and "api_params" in _mode:
            active["api_params"] = _mode["api_params"]

        # Einstellungs-Snapshot für die History (Restore Settings): roher Prompt inkl.
        # @refs, Modell/Mode-Label und die tatsächlich gesendeten Parameter.
        mode_label = None
        _mk = node.knob("mode")
        if _mk and _mk.visible():
            mode_label = _mk.value()
        settings = {
            "model": model["label"],
            "mode": mode_label,
            "prompt": prompt_text,
            "params": dict(params),
        }

        _set_status(node, "sending to {label} ...".format(label=model["label"]))
        worker = threading.Thread(
            target=_worker,
            args=(node, active, api_prompt, inputs, params, outputs_dir, settings),
        )
        worker.daemon = True
        worker.start()
    except Exception as exc:
        _set_status(node, "Error: {e}".format(e=exc))
        nuke.tprint(traceback.format_exc())


def _write_log(outputs_dir, model, prompt, params, input_summary, output_path):
    """
    Eine Zeile pro Generierung in <shot>/GenAI/generation_log.txt schreiben:
    Zeit, Modell, Parameter, hochgeladene Inputs, Output-Dateiname, Prompt.
    """
    try:
        genai_dir = os.path.dirname(outputs_dir)  # <shot>/GenAI  (OUT liegt darunter)
        log_path = os.path.join(genai_dir, "generation_log.txt")
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        parts = [ts, "model=" + str(model.get("label", "?"))]
        if params:
            parts.append("params=" + ",".join("{k}={v}".format(k=k, v=v) for k, v in params.items()))
        parts.append("inputs=[" + ", ".join(input_summary) + "]")
        parts.append("output=" + os.path.basename(output_path))
        parts.append('prompt="' + (prompt or "").replace("\n", " ").strip() + '"')
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(" | ".join(parts) + "\n")
    except Exception:
        nuke.tprint(traceback.format_exc())


def _worker(node, model, prompt_text, inputs, params, outputs_dir, settings=None):
    """Hintergrund: (Guide-Videos hochladen) -> submit -> poll -> download."""
    try:
        # Input-Beschreibung fürs Log festhalten (vor der Video->URL-Umwandlung).
        input_summary = []
        for i in sorted(inputs.keys()):
            v = inputs[i]
            if isinstance(v, dict):
                input_summary.append("in{i}=guide-video".format(i=i))
            else:
                input_summary.append("in{i}={f}".format(i=i, f=os.path.basename(v)))

        # Guide-Video-Eingänge (Sequenz-dicts) zu mp4 encoden + zu fal hochladen,
        # dann durch die resultierende URL ersetzen.
        for idx in list(inputs.keys()):
            val = inputs[idx]
            if isinstance(val, dict) and val.get("seq_dir"):
                nuke.executeInMainThread(_set_status, args=(node, "uploading guide video ..."))
                # Guide-Video mit der vom Modell erwarteten fps senden (Seedance/Gemini
                # = 24). Die Frames sind die gerenderten Comp-Frames (kein Resampling).
                inputs[idx] = video.encode_and_upload(
                    val["seq_dir"], val["first"], val["last"], model.get("guide_fps", 24)
                )

        backend = get_backend(model["backend"])
        job_id = backend.submit(model, prompt_text, inputs, params)

        start = time.time()
        eta = model.get("eta_sec", 30)
        while True:
            st = backend.poll(job_id)
            elapsed = int(time.time() - start)
            if st.status == DONE:
                ext = model.get("output_ext", "png")
                is_video = model.get("type") == "video"
                filename = "gen_{t}.{ext}".format(t=int(time.time()), ext=ext)
                path = backend.download(st.result_url, outputs_dir, filename=filename)
                _write_log(outputs_dir, model, prompt_text, params, input_summary, path)
                if is_video:
                    # Nukes Reader indiziert fal-mp4s falsch -> in PNG-Sequenz wandeln.
                    nuke.executeInMainThread(_set_status, args=(node, "transcoding video ..."))
                    seq_dir = os.path.splitext(path)[0] + "_frames"
                    pattern, first, last, _fps = video.mp4_to_sequence(path, seq_dir)
                    nuke.executeInMainThread(_on_done, args=(node, pattern, True, first, last, model.get("label"), settings))
                else:
                    nuke.executeInMainThread(_on_done, args=(node, path, False, None, None, model.get("label"), settings))
                return
            if st.status == ERROR:
                nuke.executeInMainThread(_set_status, args=(node, "Error: {e}".format(e=st.error)))
                return
            remaining = eta - elapsed
            if remaining > 0:
                msg = "{s} ... {el}s (~{r}s left)".format(s=st.status, el=elapsed, r=remaining)
            else:
                msg = "{s} ... {el}s (finishing up ...)".format(s=st.status, el=elapsed)
            nuke.executeInMainThread(_set_status, args=(node, msg))
            time.sleep(2)
    except Exception as exc:
        nuke.executeInMainThread(_set_status, args=(node, "Error: {e}".format(e=exc)))
        nuke.tprint(traceback.format_exc())


MAX_HISTORY = 30
_SUPPRESS_CB = {"on": False}   # unterdrückt gen_select-knobChanged bei programmatischem setValue


def _gen_status(prefix, entry):
    """Status-Text mit angehängtem Modell (falls in der History-Entry gespeichert)."""
    m = (entry or {}).get("model")
    return prefix + ("  ·  " + m if m else "")


def _on_done(node, path, is_video=False, first=None, last=None, model_label=None, settings=None):
    """Main-Thread: neue Generierung in die History aufnehmen und anzeigen."""
    entry = _history_add(node, path, bool(is_video), first, last, model_label, settings)
    _show_generation(node, entry)
    try:
        if node.knob("last_output"):
            node["last_output"].setValue(entry["path"])
    except Exception:
        pass
    # No automatic viewer switch: viewer operations over the MCP bridge froze the
    # GUI. The Read is wired up; just view the node.
    _set_status(node, _gen_status("done: " + os.path.basename(path), entry))


def _show_generation(node, entry):
    """Die gegebene Generierung als Read (+ OCIODisplay-invert) in die Node laden.

    Nativ geladen — kein Reformat aufs Plate (der User reformatiert bei Bedarf selbst).
    """
    result_name = node.name() + "_result"
    ocio_name = node.name() + "_toACES"
    reformat_name = node.name() + "_fit"
    posix = entry["path"].replace("\\", "/")
    is_video = entry.get("is_video")

    node.begin()
    try:
        for old in (result_name, ocio_name, reformat_name):
            existing = nuke.toNode(old)
            if existing is not None:
                nuke.delete(existing)
        read = _make_result_read(result_name, posix, is_video, entry.get("first"), entry.get("last"))
        tail = render.make_ocio_display(read, invert=True)
        tail.setName(ocio_name)
        for out in nuke.allNodes("Output"):
            out.setInput(0, tail)
    finally:
        node.end()


def _make_result_read(name, posix, is_video, first, last):
    """Read anlegen (Raw-Colorspace, Video: Range + an Comp-Anfang; Bild: hold)."""
    read = nuke.nodes.Read()
    read.setName(name)
    read["file"].setValue(posix)
    read["colorspace"].setValue(render.RAW_COLORSPACE)  # Raw: Werte wie in der Datei
    if is_video:
        try:
            if first is not None:
                read["first"].setValue(int(first))
            if last is not None:
                read["last"].setValue(int(last))
        except Exception:
            pass
        _offset_to_comp(read)
    else:
        _hold_over_range(read)
    try:
        read["reload"].execute()
    except Exception:
        pass
    return read


# ---- History ------------------------------------------------------------------

def _history_load(node):
    try:
        stored = node["history"].value() if node.knob("history") else ""
        if not stored:
            return []
        # Neu: base64 (siehe _history_save). Fallback für evtl. alten roh-JSON.
        try:
            raw = base64.b64decode(stored.encode("ascii")).decode("utf-8")
        except Exception:
            raw = stored
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _history_save(node, hist):
    try:
        # WICHTIG: base64 statt roher JSON. Nukes String_Knob wertet eckige Klammern
        # [...] als TCL-Ausdruck aus -> roher JSON (beginnt mit "[") wird beim Zurück-
        # lesen zu "Syntax error ..." zerstört und die History geht verloren. base64
        # (A-Za-z0-9+/=) enthält keine TCL-Sonderzeichen und überlebt unverändert.
        enc = base64.b64encode(json.dumps(hist).encode("utf-8")).decode("ascii")
        node["history"].setValue(enc)
    except Exception:
        pass


def _rebuild_gen_select(node, hist, index):
    knob = node.knob("gen_select")
    if not knob:
        return
    labels = [e.get("label", str(i + 1)) for i, e in enumerate(hist)] or [" "]
    _SUPPRESS_CB["on"] = True
    try:
        knob.setValues(labels)
        if 0 <= index < len(labels):
            knob.setValue(labels[index])
    except Exception:
        pass
    finally:
        _SUPPRESS_CB["on"] = False


def _current_index(node, hist):
    knob = node.knob("gen_select")
    if not knob or not hist:
        return len(hist) - 1
    try:
        return max(0, min(int(knob.getValue()), len(hist) - 1))
    except Exception:
        return len(hist) - 1


def _history_add(node, path, is_video, first, last, model_label=None, settings=None):
    hist = _history_load(node)
    num = (hist[-1].get("num", len(hist)) + 1) if hist else 1
    label = "#{n}  {t}".format(n=num, t=datetime.datetime.now().strftime("%H:%M:%S"))
    entry = {"path": path.replace("\\", "/"), "is_video": bool(is_video),
             "first": first, "last": last, "num": num, "label": label,
             "model": model_label, "settings": settings}
    hist.append(entry)
    hist = hist[-MAX_HISTORY:]
    _history_save(node, hist)
    _rebuild_gen_select(node, hist, len(hist) - 1)
    return entry


def gen_step(node, delta):
    """Prev/Next: eine Generierung in der History weiterschalten und anzeigen."""
    hist = _history_load(node)
    if not hist:
        _set_status(node, "no generations yet")
        return
    i = max(0, min(_current_index(node, hist) + delta, len(hist) - 1))
    knob = node.knob("gen_select")
    if knob:
        _SUPPRESS_CB["on"] = True
        try:
            knob.setValue(hist[i]["label"])
        except Exception:
            pass
        finally:
            _SUPPRESS_CB["on"] = False
    _show_generation(node, hist[i])
    _set_status(node, _gen_status("showing " + hist[i]["label"], hist[i]))


def extract(node):
    """Aktuell gezeigte Generierung als eigenständigen Read (+OCIODisplay) im Comp."""
    hist = _history_load(node)
    if not hist:
        _set_status(node, "nothing to extract")
        return
    entry = hist[_current_index(node, hist)]
    base = node.name() + "_extract"
    nx, ny = int(node.xpos()), int(node.ypos())

    # Eindeutige Nummer über einen monotonen Zähler-Knob (toNode ist im
    # Button-/Group-Kontext unzuverlässig und findet Root-Nodes nicht).
    cnt_knob = node.knob("extract_count")
    k = (int(cnt_knob.value()) + 1) if cnt_knob else 1
    if cnt_knob:
        cnt_knob.setValue(k)
    read_name = "{b}{i}".format(b=base, i=k)

    # WICHTIG: Der Button läuft im Group-Kontext -> ohne `with nuke.root()` landen
    # die Nodes INNERHALB der Group (unsichtbar im Comp).
    with nuke.root():
        read = _make_result_read(read_name, entry["path"].replace("\\", "/"),
                                 entry.get("is_video"), entry.get("first"), entry.get("last"))
        ocd = render.make_ocio_display(read, invert=True)
        ocd.setName(read_name + "_toACES")
        try:
            read["tile_color"].setValue(0x228822ff)  # grün, damit gut sichtbar
            read.setXYpos(nx + 200, ny + 120)
            ocd.setXYpos(nx + 200, ny + 190)
        except Exception:
            pass
    _set_status(node, "extracted {lbl} -> {name}".format(lbl=entry["label"], name=read.fullName()))


def _set_enum(node, knob_name, value):
    """
    Enumeration/Text-Knob auf 'value' setzen, tolerant gegenüber den Auffüll-
    Leerzeichen der Resolution (Werte im Dropdown sind zentriert, z. B. "  1080p ").
    Findet die Option, deren getrimmte Form == value ist, und setzt deren Rohtext.
    """
    knob = node.knob(knob_name)
    if not knob or value is None:
        return
    target = str(value).strip()
    try:
        options = list(knob.values())
    except Exception:
        options = None
    try:
        if options:
            for opt in options:
                raw = opt.split("\t")[0]
                if raw.strip() == target:
                    knob.setValue(raw)
                    return
        knob.setValue(value)
    except Exception:
        pass


def restore_settings(node):
    """
    History-Button: Modell, Mode, Prompt und Parameter der aktuell gezeigten
    Generierung zurück in die Bedienelemente laden (führt NICHT neu aus).

    Reihenfolge ist entscheidend: erst Modell (baut Mode-/Parameter-Dropdowns neu
    auf), dann Mode (setzt die Options-Listen des Modes), dann die gespeicherten
    Parameter (überschreiben die Defaults), zuletzt der Prompt. Die Rebuilds werden
    explizit aufgerufen, statt sich auf Callback-Nebenwirkungen zu verlassen.
    """
    hist = _history_load(node)
    if not hist:
        _set_status(node, "no generations yet")
        return
    entry = hist[_current_index(node, hist)]
    settings = entry.get("settings")
    if not settings:
        _set_status(node, "this generation has no saved settings (older entry) — nothing to restore")
        return

    model = _model_by_label(settings.get("model"))
    if model.get("label") != settings.get("model"):
        _set_status(node, "cannot restore: model '{m}' is no longer in the manifest".format(
            m=settings.get("model")))
        return
    if not config.has_backend_key(model.get("backend", "")):
        _set_status(node, "cannot restore: model '{m}' is unavailable (missing API key — GenAI > Setup)".format(
            m=settings.get("model")))
        return

    # Modell setzen + Mode-/Parameter-Dropdowns auf dieses Modell aufbauen.
    _set_enum(node, "model", settings["model"])
    update_legal(node)
    _apply_model_params(node, model)

    # Gespeicherten Mode wählen und dessen Parameter-Optionslisten aufbauen.
    if settings.get("mode") and node.knob("mode"):
        _set_enum(node, "mode", settings["mode"])
    _apply_mode_params(node, model)

    # Gespeicherte Parameterwerte über die Mode-Defaults legen.
    for pk, val in (settings.get("params") or {}).items():
        _set_enum(node, pk, val)

    # Prompt zuletzt (kein Callback, keine Nebenwirkung).
    if node.knob("prompt") is not None:
        try:
            node["prompt"].setValue(settings.get("prompt", ""))
        except Exception:
            pass

    _update_cost(node, model)
    _set_status(node, "restored settings from {lbl} — press Generate to reproduce".format(
        lbl=entry.get("label", "generation")))


def _reformat_to(read, plate_fmt, name, mode="fill"):
    """
    Reformat hinter den Read hängen, das auf das Plate-Format zurückrechnet.
    mode: fill (füllt, winziger Beschnitt) | fit (Letterbox, kein Beschnitt) |
          distort (exakt füllend, leichter Stretch).
    """
    resize = {"fill": "fill", "fit": "fit", "distort": "distort"}.get(mode, "fill")
    rf = nuke.nodes.Reformat(inputs=[read])
    rf.setName(name)
    try:
        rf["type"].setValue("to box")
        rf["box_width"].setValue(plate_fmt.width())
        rf["box_height"].setValue(plate_fmt.height())
        rf["box_fixed"].setValue(True)
        rf["box_pixel_aspect"].setValue(plate_fmt.pixelAspect())
        rf["resize"].setValue(resize)
        rf["black_outside"].setValue(False)
        rf["center"].setValue(True)
    except Exception:
        nuke.tprint(traceback.format_exc())
    return rf


def _hold_over_range(read):
    """Standbild an jedem Frame zeigen (before/after = hold)."""
    for kn, val in (("before", "hold"), ("after", "hold")):
        try:
            read[kn].setValue(val)
        except Exception:
            pass


def _offset_to_comp(read):
    """
    Video so verschieben, dass sein erstes Bild am Comp-Anfang liegt — sonst läge
    es (Range 1..N) außerhalb der Comp-Range und der Viewer zeigt schwarz.
    """
    try:
        first = int(nuke.root()["first_frame"].value())
        read["frame_mode"].setValue("start at")
        read["frame"].setValue(str(first))
    except Exception:
        nuke.tprint(traceback.format_exc())


def _show_in_viewer(node):
    """Aktiven Viewer auf die Node schalten, damit das Ergebnis sofort sichtbar ist."""
    try:
        v = nuke.activeViewer()
        if v is not None:
            v.node().setInput(0, node)
        else:
            nuke.connectViewer(0, node)
    except Exception:
        pass


def _set_status(node, text):
    try:
        node["status"].setValue(text)
    except Exception:
        pass


# ---- Rechts-Ampel live aktualisieren, wenn das Modell gewechselt wird ----------

def _on_knob_changed():
    try:
        node = nuke.thisNode()
        kn = nuke.thisKnob().name()
        if kn == "model" and node.knob("legal"):
            model = _model_by_label(node["model"].value())
            update_legal(node)
            _apply_model_params(node, model)
        elif kn == "mode":
            # Mode-Wechsel: Hint + Param-Knobs (Auflösung/Dauer je Mode) neu setzen,
            # ohne den Mode selbst zurückzusetzen.
            _apply_mode_params(node, _model_by_label(node["model"].value()))
        elif kn in ("resolution", "duration") and node.knob("cost_est"):
            _update_cost(node, _model_by_label(node["model"].value()))
        elif kn == "gen_select" and not _SUPPRESS_CB["on"] and node.knob("history"):
            hist = _history_load(node)
            if hist:
                entry = hist[_current_index(node, hist)]
                _show_generation(node, entry)
                _set_status(node, _gen_status("showing " + entry.get("label", ""), entry))
    except Exception:
        pass


def install_callbacks():
    """Einmal registrieren: Ampel folgt der Modell-Auswahl."""
    nuke.addKnobChanged(_on_knob_changed, nodeClass="Group")
