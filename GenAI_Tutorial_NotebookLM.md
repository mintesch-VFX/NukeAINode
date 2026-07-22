# GenAI for Nuke — Installation & Usage Guide

> **Purpose of this document.** This is a self-contained training source for the
> GenAI node, a native Foundry Nuke tool that generates images and video from inside
> the comp using your own AI API keys. It is written to be fed into NotebookLM (or a
> similar tool) to produce a narrated training video. It contains two parts:
>
> - **Part 1 — Reference Guide:** everything about installing and using the node.
> - **Part 2 — Voice-Over Script:** a scene-by-scene narration you can record a
>   screen capture against, or let NotebookLM turn into a video overview.

---

# Part 1 — Reference Guide

## 1. What the GenAI node is

GenAI is a single node you add inside a Nuke comp. It sends the images or clips you
connect to it to a generative AI model, and loads the result straight back into your
script, already converted to your comp's color space. Everything runs on **your own
API keys**, so you only pay for what you use.

Key ideas:

- **Native and shot-aware.** Results and uploads are written next to your Nuke script
  in a `GenAI` folder, per shot.
- **Color accurate.** The look the model receives matches what you see in the Viewer,
  and the result is brought back into the comp's color space automatically. This works
  across Nuke versions and OCIO configs (ACES 2.0, ACES 1.x, or the legacy Nuke config).
- **Multi-model.** One node, several providers. Only the models whose API key you have
  entered appear in the Model dropdown.

## 2. Before you install — prerequisites

- **Nuke 14, 15, 16, or 17** (Python 3.10+). Tested on Nuke 15.2 and Nuke 17.0.
- **Any Python with Tkinter** to run the installer window (the standard system Python
  is fine — no extra packages needed just to install).
- **API keys** for the providers you want to use (see section 4).
- **For video only:** a second Python interpreter that has `opencv-python`,
  `fal-client`, and `imageio-ffmpeg` installed (see section 7). Image generation does
  not need this.

### Getting Python (if you don't have it)

The installer is a small Python program, so you need Python on your machine. **Nuke's
own built-in Python does not count** — it's internal and not available as a normal
`python` command. Get a standard one:

**Windows**
1. Go to **python.org → Downloads** and click **Download Python 3.x**.
2. Run the installer and — this is the important part — tick **"Add python.exe to
   PATH"** at the bottom, then click **Install Now**.
   *Without that checkbox, neither `python install.py` in a terminal nor `install.bat`
   will work — it's the single most common mistake.*
3. Verify: open a terminal and run `python --version`. If it prints a version, you're set.

**macOS**
- Install from **python.org** as well (that installer includes Tkinter, which the
  installer window needs). Then run `python3 install.py` in Terminal. The `.bat` file
  is Windows-only.

> Use the **python.org** installer, not the Microsoft Store or Homebrew build — those
> sometimes ship without **Tkinter**, and the installer window won't open without it.

## 3. Installation (one time)

1. Copy the whole **`NukeAINode`** folder to your machine.
2. Open a terminal in that folder and run the installer with any Python:
   ```
   python install.py
   ```
3. A small window titled **"GenAI — Installer"** opens. It does four things:
   - copies the `ai_gen` package into your `~/.nuke/` folder,
   - adds the **Nodes → GenAI** menu entry to your `~/.nuke/menu.py`,
   - saves your API keys locally to `~/.nuke/ai_gen_keys.json`,
   - stores a **relative output path** worked out from one example shot (section 6).
4. Enter your **API keys** in the fields (tick "Show keys" to check them).
5. *(Optional but recommended)* Set the **relative path**: pick one example `.nk`
   script and the base folder where its `GenAI` folder should live. The installer
   computes the offset between them so it applies to every shot automatically.
6. Click **Install**, then **restart Nuke**.

After restarting, the node lives under **Nodes → GenAI**.

> Your keys never leave your machine. The file `~/.nuke/ai_gen_keys.json` is personal —
> **do not share it.** You can re-run `install.py` at any time to change keys or paths.

## 4. API keys — what you need and where to get it

You enter these in the installer. **Only models whose key is present show up in the
Model dropdown**, so you can start with just one provider.

| Key | Unlocks | Where to get it |
|-----|---------|-----------------|
| `MAGNIFIC_API_KEY` | Nano Banana (image), Kling 3.0 (video) | magnific.com → account → **API** |
| `FAL_KEY` | Seedance, Gemini Omni, **and all file uploads** | fal.ai → **Keys** (format `id:secret`) |
| `OPENAI_API_KEY` | GPT 2 (image) | platform.openai.com → **API keys** |
| `GOOGLE_API_KEY` | optional, direct Google models | aistudio.google.com → **Get API key** |

> **Keep `FAL_KEY` set even if you mainly use Magnific models.** It is also used to
> upload your input frames and guide videos to a public URL, which the Magnific-based
> models (Kling, Nano with references) require.

Alternative to the installer: create `~/.nuke/ai_gen_keys.json` by hand:
```json
{
  "MAGNIFIC_API_KEY": "your-magnific-key",
  "FAL_KEY": "id:secret",
  "OPENAI_API_KEY": "sk-..."
}
```
Environment variables of the same name also work and take priority over the file.

## 5. Using the node — step by step

1. **Add the node:** Nodes → GenAI. A `GenAI` node appears with four inputs,
   `in1`–`in4`.
2. **Pick a Model** from the dropdown. A **rights traffic light** shows next to it:
   🟢 cleared for use, 🟡 only with a proper contract, 🔴 not approved. Red-flagged
   models (for example Kling, which keeps training rights) ask for confirmation before
   they run.
3. **Pick a Mode** if the model has several (for example *Image → Video*,
   *Reference → Video*, *Text → Video*). The **Inputs** hint under the dropdown tells
   you what each connected input means for the current model and mode.
4. **Connect your inputs** to `in1`–`in4` as described by the hint (for example
   `in1` = start frame, `in2` = end frame).
5. **Write a prompt.** Refer to connected inputs with **`@in1`–`@in4`** (the alias
   `@ref1` also works). Example: *"Make `@in1` look like a rainy night."* Use **Expand
   editor** for a large prompt window.
6. **Set the parameters** the model exposes: Aspect Ratio, Resolution, Duration,
   Quality. An **Est. cost** line updates as you change them (Magnific in credits,
   fal/OpenAI roughly in USD).
7. **Optionally set an Output Folder.** Leave it empty to use the relative path from
   the installer, or an automatic `GenAI` folder next to your `.nk`.
8. **Press Generate.** The Status field shows progress and a running timer
   (rendering inputs → uploading → generating → transcoding). When it finishes, the
   result is wired into the node in your comp's color space.

## 6. Where files go

Per generation the node uses this folder layout, resolved in this order:

1. the node's own **Output Folder** knob, if you set a fixed path;
2. the **relative offset** stored by the installer;
3. otherwise, automatically, a `GenAI` folder next to the `.nk`.

Result:
```
<shot>/GenAI/UPLOAD/     ← inputs sent to the API
<shot>/GenAI/DOWNLOAD/   ← results downloaded back
<shot>/GenAI/generation_log.txt   ← one line per run (time, model, params, prompt)
```

## 7. Video helper Python (video models only)

Video models need a Python — **not Nuke's** — that has these three packages:
```
pip install opencv-python fal-client imageio-ffmpeg
```
They are used to transcode results into frame sequences and to encode/upload guide and
reference videos (imageio-ffmpeg provides the h264 encoder some models require). The
node finds this Python automatically via your `PATH`, common install locations, or the
environment variable `AI_GEN_CV2_PYTHON` pointing at such a `python.exe`.
**Image-only workflows do not need this.**

## 8. History and reproducing a generation

The node keeps a history of its recent generations:

- **Generation** dropdown plus **< Prev / Next >** to step through past results — each
  one loads back into the node for comparison.
- **Extract to Read** bakes the currently shown generation into a standalone Read node
  in your comp, so you can keep it and carry on.
- **Restore Settings** loads the shown generation's **model, mode, prompt, and
  parameters** back into the controls. It does **not** re-run — press Generate
  afterwards to reproduce or tweak it. (Only generations made from this version onward
  carry restorable settings; the node connections themselves are not restored, but the
  prompt with its `@in1` references tells you what went where.)

## 9. Troubleshooting

| Symptom | Cause / Fix |
|---------|-------------|
| **GenAI is not in the Nodes menu** | Restart Nuke after installing. Check that `~/.nuke/menu.py` contains the GenAI snippet. |
| **A model is missing from the dropdown** | Its API key is not present. Re-run `install.py` and enter the key. |
| **"No Python with OpenCV / fal_client found"** | Install the video helper packages (section 7) or set `AI_GEN_CV2_PYTHON`. |
| **"User is locked. Exhausted balance"** | Your fal account is out of credit. Top up at fal.ai/dashboard/billing. |
| **Colors look off** | The node auto-matches the active Viewer transform; make sure your Viewer is set to the look you want *before* generating. |

## 10. Model overview

| Model | Provider | Type | Notes |
|-------|----------|------|-------|
| Nano Banana 2 | Magnific | image | up to 4K, reference images |
| GPT 2 | OpenAI | image | up to 4K |
| Kling 3.0 Pro | Magnific | video (image→video) | native 4K, start/end frames 🔴 |
| Kling 3.0 Omni | Magnific | video (video→video) | motion reference video, up to 1080p 🔴 |
| Seedance 2.0 | fal | video | reference images + guide video |
| Gemini Omni Flash | fal | video | video-to-video edit, 720p |

---

# Part 2 — Voice-Over Script (for a screen-recorded tutorial or NotebookLM video)

> Read the **NARRATION** lines aloud over the matching **ON SCREEN** action. Total
> runtime is roughly three to four minutes at a normal speaking pace. Keep the tone
> calm and instructional.

### Scene 1 — Intro (0:00–0:20)
**ON SCREEN:** A Nuke comp; the presenter adds a GenAI node and connects one image.
**NARRATION:**
"This is GenAI — a node that brings generative AI right into your Nuke comp. You
connect an image or a clip, write a prompt, and the result comes back into your script,
already in the right color space. Everything runs on your own API keys, so you only pay
for what you use. Let's set it up and make our first generation."

### Scene 2 — Getting Python & running the installer (0:20–1:05)
**ON SCREEN:** The python.org download page; the Python installer with the **"Add
python.exe to PATH"** checkbox highlighted; then a terminal in the `NukeAINode` folder
typing `python install.py`; the installer window opens.
**NARRATION:**
"First you need Python — and note that Nuke's own built-in Python doesn't count here.
Grab it from python dot org, and when you run its installer, tick the box that says
'Add python to PATH' at the bottom. That one checkbox saves a lot of headaches — on
Windows and on Mac. With Python installed, open a terminal in the NukeAINode folder and
run: python install dot py. A small window opens. It copies the node into your Nuke
folder, adds the GenAI menu entry, and stores your settings — all locally, on your
machine."

### Scene 3 — Entering API keys (0:55–1:30)
**ON SCREEN:** Filling in the key fields; toggling "Show keys".
**NARRATION:**
"Now enter your API keys. Each model runs on a provider — Magnific, fal, or OpenAI —
and only the models whose key you enter will appear later in the node. One important
tip: keep your fal key set even if you mainly use Magnific models, because fal also
handles uploading your input frames. When you're done, set an example shot for the
output path if you like, click Install, and restart Nuke."

### Scene 4 — Adding the node (1:30–1:55)
**ON SCREEN:** Nodes → GenAI; the node appears with inputs in1 to in4.
**NARRATION:**
"After restarting, you'll find GenAI under the Nodes menu. Drop it into your comp. It
has four inputs, in-one through in-four. A traffic-light next to the model tells you the
usage rights: green is cleared, yellow needs a contract, and red asks for confirmation
before it runs."

### Scene 5 — Choosing model, mode, and inputs (1:55–2:30)
**ON SCREEN:** Selecting a model, then a mode; the Inputs hint updates; connecting
in1 and in2.
**NARRATION:**
"Pick a model, and if it offers several modes — like image-to-video or
reference-to-video — pick one. Watch the Inputs hint: it tells you exactly what each
connected input means for this model. Here, in-one is the start frame and in-two is the
end frame, so we connect those."

### Scene 6 — Prompt and parameters (2:30–3:00)
**ON SCREEN:** Typing a prompt using `@in1`; adjusting Resolution and Duration; the
Est. cost line updating.
**NARRATION:**
"Write your prompt, and refer to a connected input with the at-sign — at-in-one. Then
set the parameters the model offers: aspect ratio, resolution, duration. The estimated
cost updates as you go, so there are no surprises."

### Scene 7 — Generate (3:00–3:30)
**ON SCREEN:** Pressing Generate; Status shows progress and timer; result loads into
the node and Viewer.
**NARRATION:**
"Now press Generate. The status line walks you through it — rendering the inputs,
uploading, generating, and transcoding. When it's done, the result loads straight back
into your comp, matched to your Viewer's look."

### Scene 8 — History and Restore (3:30–4:00)
**ON SCREEN:** Stepping through the Generation dropdown; clicking Restore Settings, then
Extract to Read.
**NARRATION:**
"Every result is kept in the history. Step through them with Prev and Next. If you like
one, Restore Settings brings its model, prompt, and parameters back into the controls,
so you can reproduce it or tweak one thing and run again. And Extract to Read bakes the
result into a standalone Read node, ready to comp. That's GenAI — generative AI, native
to Nuke."

### Closing card (4:00–4:10)
**ON SCREEN:** Text card: "GenAI for Nuke — your keys, your comp, your color."
**NARRATION:**
"Your keys, your comp, your color. Happy generating."
