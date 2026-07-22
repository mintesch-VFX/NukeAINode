"""
install.py — one-time installer for the GenAI node (with a small window).

What it does:
  1) copies `ai_gen/` (next to this file) to  ~/.nuke/ai_gen
  2) adds the menu entry to ~/.nuke/menu.py  (Nodes > GenAI)
  3) asks for your API keys and stores them in  ~/.nuke/ai_gen_keys.json
  4) asks for one example .nk script + the folder where UPLOAD/DOWNLOAD should go,
     and derives the RELATIVE path from it — which then applies to every shot.

Run it (any Python) via install.bat, or:
    python install.py

Then (re)start Nuke -> Nodes > GenAI.
For video you also need a Python with opencv-python, fal-client, imageio-ffmpeg
(see README). Uses only the standard library (tkinter) — no extra package needed.
"""

import json
import os
import shutil
import sys

import tkinter as tk
from tkinter import filedialog, messagebox


KEY_FIELDS = [
    ("MAGNIFIC_API_KEY", "Magnific API Key", "Nano Banana, Kling  ·  magnific.com > API"),
    ("FAL_KEY", "fal Key", "Seedance, Gemini Omni + uploads  ·  fal.ai"),
    ("OPENAI_API_KEY", "OpenAI API Key", "GPT 2  ·  platform.openai.com"),
    ("GOOGLE_API_KEY", "Google AI Studio Key", "optional  ·  aistudio.google.com"),
]

MENU_SNIPPET = '''
# --- GenAI node (auto-added by install.py) ---
try:
    import os as _os
    import nuke
    import ai_gen as _ai_pkg
    import ai_gen.nuke_node as _ai_node
    _ai_node.install_callbacks()
    # Icons-Ordner in den Plugin-Pfad; Icon per DATEINAME (Nuke loest Menue-Icons
    # ueber den Plugin-Pfad auf, absolute Pfade mit Leerzeichen scheitern dabei).
    _ai_icons = _os.path.join(_os.path.dirname(_ai_pkg.__file__), "icons")
    if _os.path.isdir(_ai_icons):
        nuke.pluginAddPath(_ai_icons.replace("\\\\", "/"))
    # Direkt hinter den Standard-Nodes einsortieren (statt ganz unten bei den
    # Drittanbietern). "Other" ist der letzte Standard-Eintrag; Index dynamisch
    # ermitteln, damit es auf jedem Rechner passt (Plugin-Sets sind verschieden).
    _ai_kw = {"icon": "GenAI.png"}
    try:
        _ai_names = [_i.name() for _i in nuke.menu("Nodes").items()]
        if "Other" in _ai_names:
            _ai_kw["index"] = _ai_names.index("Other") + 1
    except Exception:
        pass
    nuke.menu("Nodes").addCommand(
        "GenAI",
        "import ai_gen.nuke_node as N; N.build_node()",
        **_ai_kw
    )
except Exception as _e:
    try:
        nuke.tprint("GenAI menu failed: %r" % _e)
    except Exception:
        pass
# --- /GenAI node ---
'''


def nuke_home():
    return os.path.join(os.path.expanduser("~"), ".nuke")


def keys_file():
    return os.path.join(nuke_home(), "ai_gen_keys.json")


def load_keys():
    try:
        with open(keys_file(), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def copy_ai_gen():
    """ai_gen next to install.py -> ~/.nuke/ai_gen. Returns destination path."""
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.join(here, "ai_gen")
    if not os.path.isdir(src):
        raise RuntimeError("'ai_gen/' is not next to install.py: " + here)
    home = nuke_home()
    os.makedirs(home, exist_ok=True)
    dst = os.path.join(home, "ai_gen")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dst


def patch_menu():
    """Add the GenAI menu to ~/.nuke/menu.py (only if not already there)."""
    menu = os.path.join(nuke_home(), "menu.py")
    existing = ""
    if os.path.isfile(menu):
        with open(menu, "r", encoding="utf-8") as fh:
            existing = fh.read()
    if "ai_gen.nuke_node" in existing:
        return False
    with open(menu, "a", encoding="utf-8") as fh:
        fh.write("\n" + MENU_SNIPPET)
    return True


def _fwd(p):
    """Auf Forward-Slashes normalisieren + Trailing-Slash weg (kein JSON-Backslash-
    Problem, Nuke-nativ)."""
    return p.replace("\\", "/").rstrip("/")


def compute_output_rel(script_path, out_folder):
    """
    Relative path from the script FOLDER to the BASE folder, in forward slashes.
    The node creates GenAI/UPLOAD + GenAI/DOWNLOAD UNDER that base, so a trailing
    GenAI/UPLOAD/DOWNLOAD in the chosen folder is stripped (avoids doubling).
    Example: <shot>/NK/x.nk + <shot>  ->  ".." (-> <shot>/GenAI/UPLOAD + DOWNLOAD).
    Returns (mode, value): ("rel", "..") or ("abs", ".../base") on different drives.
    """
    script_dir = os.path.dirname(_fwd(script_path))
    out = _fwd(out_folder)
    while os.path.basename(out).lower() in ("genai", "upload", "download", "in", "out"):
        out = os.path.dirname(out)
    try:
        return "rel", _fwd(os.path.relpath(out, script_dir))
    except ValueError:
        return "abs", out


class InstallerApp(object):
    def __init__(self, root):
        self.root = root
        root.title("GenAI — Installer")
        root.resizable(False, False)
        existing = load_keys()
        pad = {"padx": 8, "pady": 3}
        row = 0

        tk.Label(root, text="Install GenAI node", font=("", 12, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(10, 2)); row += 1
        tk.Label(root, text="Copies to  %s  and stores keys + settings there." % nuke_home(),
                 fg="grey").grid(row=row, column=0, columnspan=3, sticky="w", padx=8); row += 1
        tk.Label(root, text="Keys & settings file:  %s" % keys_file(), fg="grey").grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8); row += 1

        # ---- API keys ----
        tk.Label(root, text="API keys", font=("", 10, "bold")).grid(
            row=row, column=0, sticky="w", padx=8, pady=(10, 0)); row += 1
        self.key_entries = {}
        for name, label, hint in KEY_FIELDS:
            tk.Label(root, text=label + ":").grid(row=row, column=0, sticky="e", **pad)
            e = tk.Entry(root, width=50, show="*")
            e.insert(0, existing.get(name, ""))
            e.grid(row=row, column=1, columnspan=2, sticky="w", **pad)
            self.key_entries[name] = e; row += 1
            tk.Label(root, text=hint, fg="grey").grid(
                row=row, column=1, columnspan=2, sticky="w", padx=8); row += 1
        self.show_keys = tk.IntVar(value=0)
        tk.Checkbutton(root, text="Show keys", variable=self.show_keys,
                       command=self._toggle).grid(row=row, column=1, sticky="w", padx=6); row += 1

        # ---- relative path ----
        tk.Label(root, text="Relative path (pipeline conform)", font=("", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(12, 0)); row += 1
        tk.Label(root, text="Example: Nuke script (.nk):").grid(row=row, column=0, sticky="e", **pad)
        self.script_entry = tk.Entry(root, width=50)
        self.script_entry.insert(0, existing.get("_example_script", ""))
        self.script_entry.grid(row=row, column=1, sticky="w", **pad)
        tk.Button(root, text="...", width=3, command=self._browse_script).grid(row=row, column=2, sticky="w"); row += 1
        tk.Label(root, text="Where GenAI/UPLOAD + GenAI/DOWNLOAD should be created:").grid(row=row, column=0, sticky="e", **pad)
        self.out_entry = tk.Entry(root, width=50)
        self.out_entry.insert(0, existing.get("_example_out", ""))
        self.out_entry.grid(row=row, column=1, sticky="w", **pad)
        tk.Button(root, text="...", width=3, command=self._browse_out).grid(row=row, column=2, sticky="w"); row += 1
        self.rel_var = tk.StringVar(value="")
        tk.Label(root, textvariable=self.rel_var, fg="#227722").grid(
            row=row, column=1, columnspan=2, sticky="w", padx=8); row += 1
        tk.Label(root, text="Leave both empty = a GenAI folder next to the .nk  (<script>/GenAI/UPLOAD + DOWNLOAD).",
                 fg="grey").grid(row=row, column=1, columnspan=2, sticky="w", padx=8); row += 1
        for e in (self.script_entry, self.out_entry):
            e.bind("<KeyRelease>", lambda _ev: self._update_rel())
        self._update_rel()

        tk.Button(root, text="Install", width=16, command=self._install).grid(
            row=row, column=1, sticky="w", padx=8, pady=(14, 6)); row += 1
        self.status = tk.Label(root, text="", fg="grey")
        self.status.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 10))

    def _toggle(self):
        show = "" if self.show_keys.get() else "*"
        for e in self.key_entries.values():
            e.config(show=show)

    def _browse_script(self):
        p = filedialog.askopenfilename(title="Example Nuke script", filetypes=[("Nuke", "*.nk"), ("All", "*.*")])
        if p:
            self.script_entry.delete(0, tk.END); self.script_entry.insert(0, p); self._update_rel()

    def _browse_out(self):
        p = filedialog.askdirectory(title="Folder for GenAI/UPLOAD + DOWNLOAD")
        if p:
            self.out_entry.delete(0, tk.END); self.out_entry.insert(0, p); self._update_rel()

    def _update_rel(self):
        s = self.script_entry.get().strip(); o = self.out_entry.get().strip()
        if s and o:
            mode, val = compute_output_rel(s, o)
            if mode == "rel":
                self.rel_var.set("→ relative base: %s   (creates GenAI/UPLOAD + GenAI/DOWNLOAD per shot)" % val)
            else:
                self.rel_var.set("→ fixed base (different drive): %s   (+ GenAI/UPLOAD + DOWNLOAD)" % val)
        else:
            self.rel_var.set("")

    def _install(self):
        try:
            dst = copy_ai_gen()
            patch_menu()
        except Exception as exc:
            messagebox.showerror("GenAI", "Copy failed:\n%s" % exc); return

        data = load_keys()
        for name, e in self.key_entries.items():
            v = e.get().strip()
            if v:
                data[name] = v
            else:
                data.pop(name, None)
        s = self.script_entry.get().strip(); o = self.out_entry.get().strip()
        data.pop("output_rel", None); data.pop("output_dir", None)
        data.pop("_example_script", None); data.pop("_example_out", None)
        if s and o:
            mode, val = compute_output_rel(s, o)
            data["output_rel" if mode == "rel" else "output_dir"] = val
            data["_example_script"] = _fwd(s)
            data["_example_out"] = _fwd(o)
        try:
            os.makedirs(nuke_home(), exist_ok=True)
            with open(keys_file(), "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, ensure_ascii=False)
        except Exception as exc:
            messagebox.showerror("GenAI", "Saving keys failed:\n%s" % exc); return

        messagebox.showinfo(
            "GenAI",
            "Installed.\n\nai_gen  ->  %s\nkeys/settings  ->  %s\n\n"
            "(Re)start Nuke, then: Nodes > GenAI" % (dst, keys_file()))
        self.status.config(text="Done — restart Nuke.", fg="#227722")


def main():
    root = tk.Tk()
    InstallerApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
