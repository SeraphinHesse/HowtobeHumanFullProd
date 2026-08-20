"""CreditsPanel — the right-pane form shown while the "Credits" leaf
(selector ▸ ui ▸ Credits, after "Strings") is selected: one ordered row list,
reached the selection-driven way (ED-3), sibling of ``strings_panel.py``'s
Strings leaf.

Edits ``data/ui/credits.json`` — the CREDITS screen's roll. One editor row per
credit row: **role** and **name** boxes, ▲/▼ to reorder, ✕ to delete, plus
"Add Person" / "Add Spacer" at the top. A row with both columns empty is a
SPACER (the game's own rule) and is drawn here as a labelled separator rather
than two empty boxes, so a designer can see the grouping the credits screen
will render — EXCEPT a row the designer just added with "Add Person" and has
not typed into yet, which keeps its boxes (see ``_is_person``).

Edits are STAGED, not written immediately — ``strings_panel.py``'s pattern:
every change updates an in-memory doc, and ONE "Save Credits" button (enabled
only while the doc differs from the baseline captured at load/last-save) is the
sole ``engine.data_io.write_validated`` call site. Dirtiness is whole-document,
not per-row: rows move and disappear here, so a per-row dot would have nothing
stable to compare against.

**Save does NOT reconfigure anything in-process.** ``credits.json`` is
game/ui-owned data (``game/ui/credits.py`` — off limits to the editor, the
``editor/`` never imports ``game/**`` layering rule), the same "no separate
editor-side consumer" case as ``strings.json``/``palette.json``. The game
re-reads it at its own next boot; the editor's screen-mode PREVIEW of the
credits screen re-records through ``tools/export_ui_layouts.py``, which binds
this file the way the game does — so a saved edit shows up there.
"""
import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import credits_ops

REPO = Path(__file__).resolve().parents[2]

_BTN_W = 26


class CreditsPanel(QWidget):
    saved = Signal()   # no consumer today (see module docstring); kept for
                       # symmetry with StringsPanel.saved.

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._baseline = None
        # Rows the designer just added with "Add Person" and has not typed into
        # yet, held by OBJECT IDENTITY (they survive a reorder; the doc holds
        # the only other reference). An empty person and a spacer are the same
        # row in the DATA — both columns blank — so without this a fresh "Add
        # Person" would appear as a spacer, which is what it used to do.
        self._new_person_rows = []

        self.save_button = QPushButton("Save Credits", self)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        self.add_person_button = QPushButton("Add Person", self)
        self.add_person_button.clicked.connect(self._on_add_person)
        self.add_spacer_button = QPushButton("Add Spacer", self)
        self.add_spacer_button.clicked.connect(self._on_add_spacer)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.save_button)
        toolbar.addWidget(self.add_person_button)
        toolbar.addWidget(self.add_spacer_button)
        toolbar.addStretch(1)

        self._status = QLabel("", self)
        self._status.setStyleSheet("color: gray;")

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._status)
        layout.addWidget(self._scroll)

        self.set_credits()

    # -- selection drives content (ED-3) -------------------------------------

    def set_credits(self):
        """(Re)load ``data/ui/credits.json`` fresh from disk and rebuild the
        list — called on entry (the "Credits" leaf's selection handler) and by
        ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid file shows a
        placeholder instead of raising out of a constructor/Qt slot — the
        editor must open on a broken tree. The GAME's own boot load fails loud
        instead (D-2), unchanged."""
        try:
            doc = credits_ops.load_credits(self._data_dir)
        except Exception:
            self._doc = None
            self._baseline = None
            self._show_unavailable()
            return
        self._doc = doc
        self._baseline = copy.deepcopy(doc)
        self._new_person_rows = []
        self._rebuild_list()

    def _show_unavailable(self):
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/ui/credits.json is missing or invalid — nothing to edit "
            "here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)
        self.save_button.setEnabled(False)
        self.add_person_button.setEnabled(False)
        self.add_spacer_button.setEnabled(False)
        self._status.setText("")

    # -- the row list ---------------------------------------------------------

    def _rebuild_list(self):
        """Rebuild every row widget from ``self._doc``.

        Called on load and after any structural edit (add/remove/move) — never
        on a keystroke: the text boxes write straight into the doc on
        ``editingFinished``, so typing never rebuilds the widget you are typing
        in. The list is a couple of dozen rows, so a full rebuild is cheaper
        than tracking widget identity across a reorder."""
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        # Drop pending rows that have since been deleted, so a stale object can
        # never keep a later row person-shaped.
        self._new_person_rows = [
            row for row in self._new_person_rows
            if any(row is existing for existing in self._doc["rows"])]
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        for index in range(len(self._doc["rows"])):
            content_layout.addWidget(self._build_row(index, content))
        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        self._refresh_dirty()

    def _build_row(self, index, parent):
        row = self._doc["rows"][index]
        widget = QWidget(parent)
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)

        if not self._is_person(row):
            # A spacer has nothing to type into — show the gap it renders as,
            # not two empty boxes a designer would read as an unfinished row.
            caption = QLabel("spacer", widget)
            caption.setStyleSheet("color: gray;")
            line = QFrame(widget)
            line.setFrameShape(QFrame.HLine)
            line.setFrameShadow(QFrame.Sunken)
            layout.addWidget(caption)
            layout.addWidget(line, 1)
        else:
            role = QLineEdit(row["role"], widget)
            role.setPlaceholderText("role")
            role.editingFinished.connect(
                lambda i=index, e=role: self._on_text(i, "role", e.text()))
            name = QLineEdit(row["name"], widget)
            name.setPlaceholderText("name")
            name.editingFinished.connect(
                lambda i=index, e=name: self._on_text(i, "name", e.text()))
            layout.addWidget(role, 1)
            layout.addWidget(name, 1)

        up = QPushButton("▲", widget)
        up.setFixedWidth(_BTN_W)
        up.setToolTip("Move up")
        up.setEnabled(index > 0)
        up.clicked.connect(lambda _=False, i=index: self._on_move(i, -1))
        down = QPushButton("▼", widget)
        down.setFixedWidth(_BTN_W)
        down.setToolTip("Move down")
        down.setEnabled(index < len(self._doc["rows"]) - 1)
        down.clicked.connect(lambda _=False, i=index: self._on_move(i, 1))
        remove = QPushButton("✕", widget)
        remove.setFixedWidth(_BTN_W)
        remove.setToolTip("Remove this row")
        remove.clicked.connect(lambda _=False, i=index: self._on_remove(i))
        layout.addWidget(up)
        layout.addWidget(down)
        layout.addWidget(remove)
        return widget

    def _is_person(self, row):
        """Whether this row gets NAME/ROLE boxes rather than a spacer bar.

        A blank row is a spacer to the game, but a blank row the designer just
        created with "Add Person" is a person they have not filled in yet —
        the panel remembers which, so adding someone does not look like adding
        a gap. Saving it blank still writes a spacer, which is what the game
        will draw; the status line says so."""
        return (not credits_ops.is_spacer(row)
                or any(row is pending for pending in self._new_person_rows))

    # -- staged edits ---------------------------------------------------------

    def _on_text(self, index, key, value):
        if self._doc is None or not (0 <= index < len(self._doc["rows"])):
            return
        row = self._doc["rows"][index]
        if row[key] == value:
            return
        was_person = self._is_person(row)
        row[key] = value
        if not credits_ops.is_spacer(row):
            # It has real text now — it is a person on its own merits, so stop
            # tracking it as pending (blanking it later makes it a spacer).
            self._new_person_rows = [
                pending for pending in self._new_person_rows if pending is not row]
        if was_person != self._is_person(row):
            # Emptying both columns turns a person into a spacer (and back) —
            # the row's whole widget shape changes, so rebuild rather than
            # leave a spacer showing text boxes.
            self._rebuild_list()
            return
        self._refresh_dirty()

    def _on_add_person(self):
        if self._doc is None:
            return
        row = credits_ops.new_person()
        self._new_person_rows.append(row)
        credits_ops.insert_row(self._doc, len(self._doc["rows"]), row)
        self._rebuild_list()

    def _on_add_spacer(self):
        if self._doc is None:
            return
        credits_ops.insert_row(self._doc, len(self._doc["rows"]),
                               credits_ops.new_spacer())
        self._rebuild_list()

    def _on_remove(self, index):
        if self._doc is None or not (0 <= index < len(self._doc["rows"])):
            return
        credits_ops.remove_row(self._doc, index)
        self._rebuild_list()

    def _on_move(self, index, delta):
        if self._doc is None:
            return
        credits_ops.move_row(self._doc, index, delta)
        self._rebuild_list()

    def _refresh_dirty(self):
        dirty = self._doc != self._baseline
        self.save_button.setEnabled(dirty)
        self.add_person_button.setEnabled(True)
        self.add_spacer_button.setEnabled(True)
        people = sum(1 for row in self._doc["rows"] if self._is_person(row))
        spacers = len(self._doc["rows"]) - people
        blank = sum(1 for row in self._doc["rows"]
                    if self._is_person(row) and credits_ops.is_spacer(row))
        text = f"{people} credited, {spacers} spacer(s)"
        if blank:
            text += f"  —  {blank} still blank (saves as a spacer)"
        self._status.setText(text + ("  ●  unsaved changes" if dirty else ""))

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if self._doc is None or self._doc == self._baseline:
            return
        credits_ops.write_credits(self._doc, self._data_dir)
        self._baseline = copy.deepcopy(self._doc)
        self._refresh_dirty()
        self.saved.emit()
