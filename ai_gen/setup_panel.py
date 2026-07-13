"""
setup_panel.py — GenAI-Setup (API-Keys + Standard-Ausgabeordner) und der große
Prompt-Editor. Beides sind PySide-Dialoge; laufen nur in Nuke (Qt vorhanden).

Menü: GenAI > Setup ...   ->  show_setup()
Prompt "Expand"-Button    ->  edit_prompt(node)

Keys/Einstellungen werden über config in ~/.nuke/ai_gen_keys.json gespeichert.
"""

import os

try:
    from PySide6 import QtWidgets, QtCore
except ImportError:  # ältere Nuke-Versionen
    from PySide2 import QtWidgets, QtCore

from . import config


# (Key-Name, Anzeige-Label, Hinweis + Bezugsquelle)
_KEY_FIELDS = [
    ("MAGNIFIC_API_KEY", "Magnific API Key", "Nano Banana, Kling  —  magnific.com → API"),
    ("FAL_KEY", "fal Key", "Seedance, Gemini Omni + Datei-Uploads  —  fal.ai"),
    ("OPENAI_API_KEY", "OpenAI API Key", "GPT 2  —  platform.openai.com"),
    ("GOOGLE_API_KEY", "Google AI Studio Key", "optional (direkt)  —  aistudio.google.com"),
]


def _nuke_main_window():
    for w in QtWidgets.QApplication.topLevelWidgets():
        if w.inherits("QMainWindow"):
            return w
    return None


class SetupDialog(QtWidgets.QDialog):
    """Keys eintragen + Standard-Ausgabeordner festlegen."""

    def __init__(self, parent=None):
        super(SetupDialog, self).__init__(parent)
        self.setWindowTitle("GenAI — Setup")
        self.setMinimumWidth(560)
        self._edits = {}

        layout = QtWidgets.QVBoxLayout(self)

        intro = QtWidgets.QLabel(
            "Trage deine eigenen API-Keys ein. Sie werden lokal in\n"
            "  " + config.keys_file_path() + "\n"
            "gespeichert (nur auf diesem Rechner). Nur Modelle, deren Key hinterlegt "
            "ist, erscheinen später im Model-Dropdown."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setLabelAlignment(QtCore.Qt.AlignRight)
        for name, label, hint in _KEY_FIELDS:
            edit = QtWidgets.QLineEdit()
            edit.setEchoMode(QtWidgets.QLineEdit.Password)
            current = config.get_key(name)
            if current:
                edit.setText(current)
                edit.setPlaceholderText("gesetzt")
            else:
                edit.setPlaceholderText("nicht gesetzt")
            self._edits[name] = edit
            box = QtWidgets.QVBoxLayout()
            box.setSpacing(1)
            box.addWidget(edit)
            hint_lbl = QtWidgets.QLabel(hint)
            hint_lbl.setStyleSheet("color: grey; font-size: 10px;")
            box.addWidget(hint_lbl)
            wrap = QtWidgets.QWidget()
            wrap.setLayout(box)
            form.addRow(label + ":", wrap)
        layout.addLayout(form)

        # Sichtbarkeit der Keys umschalten
        show = QtWidgets.QCheckBox("Keys anzeigen")
        show.toggled.connect(self._toggle_echo)
        layout.addWidget(show)

        # Standard-Ausgabeordner
        layout.addWidget(self._hline())
        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(QtWidgets.QLabel("Standard-Ausgabeordner:"))
        self._outdir = QtWidgets.QLineEdit(config.get_value("output_dir") or "")
        self._outdir.setPlaceholderText("leer = automatisch aus dem Shot (<shot>/GenAI)")
        out_row.addWidget(self._outdir, 1)
        browse = QtWidgets.QPushButton("...")
        browse.setFixedWidth(30)
        browse.clicked.connect(self._browse)
        out_row.addWidget(browse)
        layout.addLayout(out_row)
        note = QtWidgets.QLabel(
            "Leer = pro Shot automatisch (<shot>/GenAI/IN + OUT). Gesetzt = fester "
            "Basis-Pfad; darunter werden GenAI/IN + OUT angelegt. Der Node-eigene "
            "'Output Folder' überschreibt das im Einzelfall."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: grey; font-size: 10px;")
        layout.addWidget(note)

        # Buttons
        layout.addWidget(self._hline())
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ---- intern ---------------------------------------------------------------

    def _hline(self):
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    def _toggle_echo(self, on):
        mode = QtWidgets.QLineEdit.Normal if on else QtWidgets.QLineEdit.Password
        for edit in self._edits.values():
            edit.setEchoMode(mode)

    def _browse(self):
        start = self._outdir.text().strip() or os.path.expanduser("~")
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Standard-Ausgabeordner", start)
        if d:
            self._outdir.setText(d)

    def _save(self):
        values = {}
        for name, edit in self._edits.items():
            values[name] = edit.text().strip()  # leer -> löscht den Eintrag
        values["output_dir"] = self._outdir.text().strip()
        try:
            path = config.save_values(values)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "GenAI", "Speichern fehlgeschlagen:\n%s" % exc)
            return
        QtWidgets.QMessageBox.information(
            self, "GenAI",
            "Gespeichert in:\n%s\n\nNeue GenAI-Nodes zeigen jetzt die passenden Modelle." % path)
        self.accept()


_setup_dialog = None


def show_setup():
    """Setup-Dialog öffnen (modal-frei, damit Nuke bedienbar bleibt)."""
    global _setup_dialog
    _setup_dialog = SetupDialog(_nuke_main_window())
    _setup_dialog.show()
    _setup_dialog.raise_()
    return _setup_dialog


# ---- Großer Prompt-Editor ------------------------------------------------------

class PromptDialog(QtWidgets.QDialog):
    """Frei skalierbares Fenster zum Bearbeiten des Prompts."""

    def __init__(self, node, parent=None):
        super(PromptDialog, self).__init__(parent)
        self._node = node
        self.setWindowTitle("GenAI — Prompt")
        self.resize(640, 420)  # frei an der Ecke vergrößerbar
        layout = QtWidgets.QVBoxLayout(self)
        self._text = QtWidgets.QPlainTextEdit()
        try:
            self._text.setPlainText(node["prompt"].value() or "")
        except Exception:
            pass
        layout.addWidget(self._text, 1)
        btns = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self._apply)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _apply(self):
        try:
            self._node["prompt"].setValue(self._text.toPlainText())
        except Exception:
            pass
        self.accept()


_prompt_dialog = None


def edit_prompt(node):
    """Großen Prompt-Editor für die Node öffnen."""
    global _prompt_dialog
    _prompt_dialog = PromptDialog(node, _nuke_main_window())
    _prompt_dialog.show()
    _prompt_dialog.raise_()
    return _prompt_dialog
