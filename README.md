# GenAI — Generative AI node for Foundry Nuke

A native Nuke gizmo that generates images and video through your own API keys,
directly inside the comp. Color accurate (ACES), shot aware, standalone.

---

## 1. Install (one time)

1. Copy the whole `NukeAINode` folder somewhere on your machine.
2. Run the installer with any Python:
   ```
   python install.py
   ```
   A small window opens. It:
   - copies `ai_gen/` into your `~/.nuke/` and adds the **Nodes → GenAI** menu entry,
   - asks for your **API keys**,
   - asks for one **example `.nk` script** and the **base folder** where its GenAI
     folder should go, and works out the *relative* path so it applies to every
     shot automatically (see section 3).
3. Click **Installieren**, then restart Nuke.

Keys and settings are saved locally in `~/.nuke/ai_gen_keys.json` (this file never
leaves your machine — do not share it). Re-run `install.py` anytime to change keys
or paths. That's it — no permanent setup panel lives in Nuke.

---

## 2. API keys

Each model runs on a provider, and you only pay for what you use, on your own key.
You enter them in the installer. **Only models whose key you entered appear in the
Model dropdown.**

### Where to get each key

| Key | Needed for | Get it at |
|-----|------------|-----------|
| `MAGNIFIC_API_KEY` | Nano Banana, Kling (image + 4K video) | magnific.com → account → **API** |
| `FAL_KEY` | Seedance, Gemini Omni, **and file uploads** | fal.ai → **Keys** (format `id:secret`) |
| `OPENAI_API_KEY` | GPT 2 | platform.openai.com → **API keys** |
| `GOOGLE_API_KEY` | optional (direct Google models) | aistudio.google.com → **Get API key** |

> **Note:** `FAL_KEY` is also used to upload your input frames/videos to a public
> URL for the Magnific models (Kling/Nano with references). Keep it set even if you
> mainly use Magnific.

### Manual alternative
Create/edit `~/.nuke/ai_gen_keys.json`:
```json
{
  "MAGNIFIC_API_KEY": "your-magnific-key",
  "FAL_KEY": "id:secret",
  "OPENAI_API_KEY": "sk-...",
  "output_dir": ""
}
```
Environment variables of the same name also work and take priority.

---

## 3. Output folder (relative, set once)

In the installer you point at one example `.nk` and the base folder where its
GenAI folder should go. The installer stores the **relative offset** between them,
so it works for *every* shot without a fixed path.

Example: script `…/PROJECT/SHOTS/SH010/NK/comp.nk` + base `…/PROJECT/SHOTS/SH010/FOOTAGE`
→ offset `../FOOTAGE` (so the GenAI folder is created at `…/PROJECT/SHOTS/SH010/FOOTAGE`).
For any other shot, a `GenAI` folder is created under that base automatically.
Uploaded inputs go to `…/GenAI/UPLOAD`, results to `…/GenAI/DOWNLOAD`, and each run
is logged to `generation_log.txt` next to them.

Resolution order per generation:
1. the node's own **Output Folder** knob (fixed path, if set),
2. the **relative offset** from the installer,
3. otherwise automatic: `GenAI/UPLOAD` + `DOWNLOAD` next to the `.nk`.

Leaving both installer path fields empty keeps option 3 (fully automatic).

---

## 4. Models

| Model | Provider | Type | Notes |
|-------|----------|------|-------|
| Nano Banana 2 | Magnific | image | up to 4K, references |
| GPT 2 | OpenAI | image | up to 4K |
| Kling 3.0 Pro | Magnific | video (i2v) | native 4K, start/end frames |
| Kling 3.0 Omni | Magnific | video (v2v) | motion reference video, up to 1080p |
| Seedance 2.0 | fal | video | references + guide video |
| Gemini Omni Flash | fal | video | video-to-video edit, 720p |

The rights flag (🟢/🟡/🔴) and an estimated cost show for each model. Red-flagged
models (e.g. Kling) ask for confirmation before generating.

---

## 5. Video helper Python (cv2 + fal-client)

Video models need a Python (not Nuke's) that has **`opencv-python`**,
**`fal-client`** and **`imageio-ffmpeg`** installed — used to transcode results to
frames and to encode/upload guide/reference videos (imageio-ffmpeg provides an
h264 encoder that video models like Kling require):
```
pip install opencv-python fal-client imageio-ffmpeg
```
The node auto-detects it (via `PATH`, common install paths, or the env var
`AI_GEN_CV2_PYTHON` pointing at such a `python.exe`). Image-only use does not
need this.

---

## 6. Usage

1. **GenAI Setup…** → enter keys (first time only).
2. Save your `.nk` in the shot's `NK/` folder (for automatic output paths).
3. **Nodes → GenAI**, pick a model, connect inputs to `in1…in4` (the *Inputs* hint
   shows their role per model), write a prompt (`@ref1…@ref4` refer to the inputs;
   **Expand editor** opens a large prompt window).
4. **Generate.** Watch the status; the result loads back into the node in your
   comp's color space. Use **History** to switch between generations and
   **Extract to Read** to bake one into a standalone Read.
