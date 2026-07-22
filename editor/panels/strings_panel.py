"""StringsPanel (Phase C) — the right-pane form shown while the "Strings"
leaf (selector ▸ ui ▸ Strings, third child after "Screens" and "Theme") is
selected: a single global-ish document, reached the selection-driven way
(ED-3), sibling of ``panels/game_theme.py``'s Theme leaf.

Edits ``data/ui/strings.json`` — a FLAT ``{string_id: template}`` map, one
row per id, grouped by source module (the id's dotted prefix — ``hud``,
``widgets``, ``levelup``, ``boss_cutscene``, …) via ``CollapsibleSection``
(``editor.panels.balancing``'s, the ``game_theme.py`` import precedent: never
copied), plus a filter/search box at the top since the set runs to dozens of
rows. Each row shows a read-only placeholder hint (e.g. ``{n}``) beside the
text box so a designer editing a templated string can see what it still
needs to fill — informational only, per ``game.ui.strings.T``'s
``str.format`` contract; a bad edit fails at the GAME's next render/boot the
same way any other data typo would, no save-time validation here.

Edits are STAGED, not written immediately — ``game_theme.py``'s pattern
(``editor/panels/CLAUDE.md`` "Theme panel"), not the screen-session undo
pattern: every change updates an in-memory doc + a dirty dot next to that
row (compared against a baseline captured at load/last-save time); ONE
"Save Strings" button (enabled only while dirty) is the sole
``engine.data_io.write_validated`` call site.

**Save does NOT reconfigure anything in-process.** ``strings.json`` is
game/ui-owned data (``game/ui/strings.py`` — off limits to the editor, the
``editor/`` never imports ``game/**`` layering rule), the exact same "no
separate editor-side consumer" case ``data/CLAUDE.md``'s theme-data section
already documents for ``palette.json`` (``game/ui/widgets`` is game-only
too). The game re-reads ``strings.json`` at its own next boot — see
``editor/panels/CLAUDE.md`` "Strings panel" for the full reasoning."""
import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import strings_ops
from editor.panels.balancing import CollapsibleSection

REPO = Path(__file__).resolve().parents[2]


class StringsPanel(QWidget):
    saved = Signal()   # no consumer today (see module docstring); kept for
                       # symmetry with GameThemePanel.saved and future use.

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._baseline = None
        self._groups = {}       # module prefix -> [string_id, ...] (sorted)
        self._row_editors = {}  # string_id -> QLineEdit
        self._hints = {}        # string_id -> QLabel (placeholder hint)
        self._dots = {}         # string_id -> QLabel (dirty dot)
        self._rows = {}         # string_id -> QWidget (whole row, for filtering)
        self._sections = {}     # module prefix -> CollapsibleSection
        self._dirty = set()     # {string_id, ...}

        self.save_button = QPushButton("Save Strings", self)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.save_button)
        toolbar.addStretch(1)

        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter by id or text…")
        self._filter.textChanged.connect(self._apply_filter)
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:", self))
        filter_row.addWidget(self._filter, 1)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addLayout(filter_row)
        layout.addWidget(self._scroll)

        self.set_strings()

    # -- selection drives content (ED-3) -------------------------------------

    def set_strings(self):
        """(Re)load ``data/ui/strings.json`` fresh from disk and rebuild the
        form — called on entry (the "Strings" leaf's selection handler) and
        by ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid
        strings.json shows a placeholder instead of raising out of a
        constructor/Qt slot — the editor must open on a broken tree. The
        GAME's own boot load (game/main.py) fails loud instead (D-2: this
        is data, not art); that rule is unchanged."""
        try:
            doc = strings_ops.load_strings(self._data_dir)
        except Exception:
            self._doc = None
            self._baseline = None
            self._groups = {}
            self._dirty = set()
            self._show_unavailable()
            return
        self._doc = doc
        self._baseline = copy.deepcopy(doc)
        self._dirty = set()
        self._rebuild_form()

    def _show_unavailable(self):
        self._row_editors = {}
        self._hints = {}
        self._dots = {}
        self._rows = {}
        self._sections = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/ui/strings.json is missing or invalid — nothing to edit "
            "here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)
        self.save_button.setEnabled(False)

    def _rebuild_form(self):
        self._row_editors = {}
        self._hints = {}
        self._dots = {}
        self._rows = {}
        self._sections = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        groups = {}
        for string_id in sorted(self._doc):
            groups.setdefault(string_id.split(".", 1)[0], []).append(string_id)
        self._groups = groups

        for group in sorted(groups):
            section = CollapsibleSection(
                group, f"Strings whose id starts with '{group}.'",
                expanded=True, parent=content)
            form = QFormLayout()
            for string_id in groups[group]:
                row, dot = self._build_row(string_id)
                form.addRow(string_id, row)
                self._dots[string_id] = dot
                self._rows[string_id] = row
            section.content_layout.addLayout(form)
            content_layout.addWidget(section)
            self._sections[group] = section

        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        self.save_button.setEnabled(bool(self._dirty))
        self._apply_filter(self._filter.text())

    # -- row builders ---------------------------------------------------------

    def _build_row(self, string_id):
        editor = QLineEdit(self)
        editor.setText(self._doc[string_id])
        editor.editingFinished.connect(
            lambda k=string_id, e=editor: self._on_text_committed(k, e.text()))
        hint = QLabel(self._placeholder_hint(self._doc[string_id]), self)
        hint.setStyleSheet("color: gray;")
        dot = self._make_dot()
        self._row_editors[string_id] = editor
        self._hints[string_id] = hint

        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(editor, 1)
        row_layout.addWidget(hint)
        row_layout.addWidget(dot)
        return row, dot

    @staticmethod
    def _placeholder_hint(template):
        names = strings_ops.placeholders(template)
        return "  ".join(f"{{{n}}}" for n in names) if names else ""

    def _make_dot(self):
        dot = QLabel("●", self)
        dot.setStyleSheet("color: white;")
        dot.setFixedWidth(12)
        dot.setVisible(False)
        return dot

    # -- staged edits: every change mutates a doc + a dirty dot --------------

    def _on_text_committed(self, string_id, value):
        if value == self._doc[string_id]:
            return
        self._doc[string_id] = value
        self._hints[string_id].setText(self._placeholder_hint(value))
        self._refresh_dirty(string_id)

    def _refresh_dirty(self, string_id):
        if self._doc[string_id] != self._baseline[string_id]:
            self._dirty.add(string_id)
        else:
            self._dirty.discard(string_id)
        dot = self._dots.get(string_id)
        if dot is not None:
            dot.setVisible(string_id in self._dirty)
        self.save_button.setEnabled(bool(self._dirty))

    # -- filter (id or current text, case-insensitive substring) -------------

    def _apply_filter(self, text):
        needle = text.strip().lower()
        for group, ids in self._groups.items():
            visible_ids = [
                sid for sid in ids
                if not needle or needle in sid.lower()
                or needle in self._doc[sid].lower()
            ]
            for sid in ids:
                self._rows[sid].setVisible(sid in visible_ids)
            section = self._sections.get(group)
            if section is not None:
                section.setVisible(bool(visible_ids))

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if not self._dirty:
            return
        strings_ops.write_strings(self._doc, self._data_dir)
        self._baseline = copy.deepcopy(self._doc)
        self._dirty = set()
        for dot in self._dots.values():
            dot.setVisible(False)
        self.save_button.setEnabled(False)
        self.saved.emit()
