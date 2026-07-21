"""TutorialPanel (D3, TU-4) — the right-pane form shown while the "Tutorial"
leaf (selector -> ui -> Tutorial) is selected: a single small document,
reached the selection-driven way (ED-3), sibling of Screens/Theme/Cutscenes.

Edits ``data/tutorial/tutorial.json`` (TU-1): the two message texts
(``messages.economy_intro``/``messages.lives_intro``) and the two behavioral
flags (``skippable``, ``first_loss_costs_life``). ``steps`` (and any other
TU-1-owned key) is loaded into ``self._doc`` and round-tripped byte-identical
-- this panel never reads or renders the step list, so an edit to texts/
flags never perturbs it, and a doc that was never touched saves unchanged.

Edits are STAGED, not written immediately -- the ``balancing.py``/
``game_theme.py`` pattern: every change updates an in-memory doc + a small
dirty dot next to that field (compared against a baseline captured at load/
last-save time); ONE "Save Tutorial Changes" button (enabled only while
dirty) is the sole ``engine.data_io.write_validated`` call site.

Unlike ``game_theme.py``'s ``QLineEdit`` rows, the two message fields are
``QPlainTextEdit`` (the messages run a full sentence/paragraph -- a
``QLineEdit`` would clip them). ``QPlainTextEdit`` has no ``editingFinished``
signal, so this panel commits on focus-out instead (``_MessageEdit``, a thin
subclass overriding ``focusOutEvent``) -- the same "commit on blur" contract,
manually wired. The empty-text guard (ED-30, "invalid text unrepresentable")
applies on that same commit path: an all-whitespace message is never staged
-- the field is restored to its last staged value instead, regardless of
what the schema's ``minLength`` would also catch.

``saved = Signal()`` exists for test observability and symmetry with every
other staged-edit panel, but -- unlike Theme -- nothing in ``MainWindow``
needs to react to it in-process: no engine reconfiguration follows a text/
flag edit. This is intentional; a future phase should not go looking for a
missing consumer.
"""
import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import tutorial_ops

REPO = Path(__file__).resolve().parents[2]

_MESSAGE_KEYS = ("economy_intro", "lives_intro")
_MESSAGE_LABELS = {
    "economy_intro": "Economy intro message",
    "lives_intro": "Lives intro message",
}
_FLAG_KEYS = ("skippable", "first_loss_costs_life")
_FLAG_LABELS = {
    "skippable": "Skippable",
    "first_loss_costs_life": "First loss costs life",
}


class _MessageEdit(QPlainTextEdit):
    """A ``QPlainTextEdit`` with no ``editingFinished`` -- commits to the
    owning panel on focus-out instead, the manual equivalent of
    ``QLineEdit``'s signal used everywhere else in the editor."""

    def __init__(self, key, panel, parent=None):
        super().__init__(parent)
        self._key = key
        self._panel = panel

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._panel._commit_message(self._key)


class TutorialPanel(QWidget):
    saved = Signal()   # no in-process MainWindow consumer (see docstring)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._baseline = None
        self._dirty = set()   # {"messages.economy_intro", "skippable", ...}
        self._message_edits = {}   # key -> _MessageEdit
        self._flag_checks = {}     # key -> QCheckBox
        self._dots = {}            # dirty-key -> QLabel

        self.save_button = QPushButton("Save Tutorial Changes", self)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.save_button)
        toolbar.addStretch(1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._scroll)

        self.set_tutorial()

    # -- selection drives content (ED-3) -------------------------------------

    def set_tutorial(self):
        """(Re)load ``data/tutorial/tutorial.json`` fresh from disk and
        rebuild the form -- called on entry (the "Tutorial" leaf's selection
        handler) and by ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid
        tutorial.json shows a placeholder instead of raising out of a
        constructor/Qt slot -- the editor must open on a broken tree. The
        GAME's own boot load fails loud instead (D-2: this is data, not
        art); that rule is unchanged."""
        try:
            doc = tutorial_ops.load_tutorial(self._data_dir)
        except Exception:
            self._doc = None
            self._baseline = None
            self._dirty = set()
            self._show_unavailable()
            return
        self._doc = doc
        self._baseline = copy.deepcopy(doc)
        self._dirty = set()
        self._rebuild_form()

    def _show_unavailable(self):
        self._message_edits = {}
        self._flag_checks = {}
        self._dots = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/tutorial/tutorial.json is missing or invalid -- nothing "
            "to edit here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)
        self.save_button.setEnabled(False)

    def _rebuild_form(self):
        self._message_edits = {}
        self._flag_checks = {}
        self._dots = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        form = QFormLayout(content)

        for key in _MESSAGE_KEYS:
            row, edit, dot = self._build_message_row(key, content)
            form.addRow(_MESSAGE_LABELS[key], row)
            self._message_edits[key] = edit
            self._dots[f"messages.{key}"] = dot

        for key in _FLAG_KEYS:
            row, check, dot = self._build_flag_row(key, content)
            form.addRow(_FLAG_LABELS[key], row)
            self._flag_checks[key] = check
            self._dots[key] = dot

        self._scroll.setWidget(content)
        self.save_button.setEnabled(bool(self._dirty))

    # -- row builders ---------------------------------------------------------

    def _build_message_row(self, key, parent):
        edit = _MessageEdit(key, self, parent)
        edit.setPlainText(self._doc["messages"][key])
        edit.setMaximumHeight(90)
        dot = self._make_dot()
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(edit, 1)
        row_layout.addWidget(dot)
        return row, edit, dot

    def _build_flag_row(self, key, parent):
        check = QCheckBox(parent)
        check.setChecked(bool(self._doc[key]))
        check.toggled.connect(lambda v, k=key: self._on_flag_toggled(k, bool(v)))
        dot = self._make_dot()
        row = QWidget(parent)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(check)
        row_layout.addWidget(dot)
        return row, check, dot

    def _make_dot(self):
        dot = QLabel("●", self)
        dot.setStyleSheet("color: white;")
        dot.setFixedWidth(12)
        dot.setVisible(False)
        return dot

    # -- staged edits: every change mutates the doc + a dirty dot -------------

    def _commit_message(self, key):
        """Focus-out commit path for a message field (see class docstring).
        Empty-text guard (ED-30): an all-whitespace message is never
        staged -- restore the field to its last staged value instead."""
        if self._doc is None:
            return
        edit = self._message_edits[key]
        text = edit.toPlainText()
        if not text.strip():
            edit.setPlainText(self._doc["messages"][key])
            return
        if text == self._doc["messages"][key]:
            return
        self._doc["messages"][key] = text
        self._refresh_dirty(f"messages.{key}")

    def _on_flag_toggled(self, key, value):
        if self._doc is None:
            return
        self._doc[key] = value
        self._refresh_dirty(key)

    def _refresh_dirty(self, dirty_key):
        if dirty_key.startswith("messages."):
            msg_key = dirty_key.split(".", 1)[1]
            current = self._doc["messages"][msg_key]
            baseline = self._baseline["messages"][msg_key]
        else:
            current = self._doc[dirty_key]
            baseline = self._baseline[dirty_key]
        if current != baseline:
            self._dirty.add(dirty_key)
        else:
            self._dirty.discard(dirty_key)
        dot = self._dots.get(dirty_key)
        if dot is not None:
            dot.setVisible(dirty_key in self._dirty)
        self.save_button.setEnabled(bool(self._dirty))

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if not self._dirty:
            return
        tutorial_ops.write_tutorial(self._doc, self._data_dir)
        self._baseline = copy.deepcopy(self._doc)
        self._dirty = set()
        for dot in self._dots.values():
            dot.setVisible(False)
        self.save_button.setEnabled(False)
        self.saved.emit()
