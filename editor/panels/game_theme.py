"""GameThemePanel (UH-6, D5) — the right-pane form shown while the "Theme"
leaf (selector ▸ ui ▸ Theme) is selected: a global-ish document, reached the
selection-driven way (ED-3), sibling of the "Screens" branch.

Edits ``data/ui/fonts.json`` (per-key size spinbox, schema-bounded, + bold
checkbox) and ``data/ui/palette.json`` (per-key color swatch button ->
``QColorDialog``). Named to avoid colliding with ``editor/theme.py`` (the Qt
chrome light/dark theme, untouched by this phase).

Edits are STAGED, not written immediately — the ``balancing.py`` pattern
(``editor/panels/CLAUDE.md`` Phase 4), not the screen-session undo pattern:
every change updates an in-memory doc + a small dirty dot next to that field
(compared against a baseline captured at load/last-save time); ONE "Save
Theme Changes" button (enabled only while dirty) is the sole
``engine.data_io.write_validated`` call site. Saving emits ``saved`` so
``MainWindow`` can reconfigure ``engine.render.fonts`` in-process and repaint
the viewport (chrome theme, ``editor/theme.py``, untouched).
"""
import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import theme_ops
from editor.panels.balancing import CollapsibleSection, _NoWheelSpinBox
from engine import data_io

REPO = Path(__file__).resolve().parents[2]


class GameThemePanel(QWidget):
    saved = Signal()   # MainWindow reconfigures engine.render.fonts + repaints

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._fonts_doc = None
        self._fonts_baseline = None
        self._palette_doc = None
        self._palette_baseline = None
        self._font_widgets = {}     # key -> (size_spin, bold_check)
        self._font_dots = {}
        self._palette_buttons = {}  # key -> swatch QPushButton
        self._palette_dots = {}
        self._dirty = set()         # {"font:<key>", "palette:<key>"}

        self.save_button = QPushButton("Save Theme Changes", self)
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

        self.set_theme()

    # -- selection drives content (ED-3) -------------------------------------

    def set_theme(self):
        """(Re)load both docs fresh from disk and rebuild the form — called
        on entry (the "Theme" leaf's selection handler) and by ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid
        fonts.json/palette.json shows a placeholder instead of raising out
        of a constructor/Qt slot — the editor must open on a broken tree.
        The GAME's own boot load (game/main.py) fails loud instead (D-2:
        this is data, not art); that rule is unchanged."""
        try:
            fonts_doc = theme_ops.load_fonts(self._data_dir)
            palette_doc = theme_ops.load_palette(self._data_dir)
        except Exception:
            self._fonts_doc = None
            self._palette_doc = None
            self._fonts_baseline = None
            self._palette_baseline = None
            self._dirty = set()
            self._show_unavailable()
            return
        self._fonts_doc = fonts_doc
        self._fonts_baseline = copy.deepcopy(fonts_doc)
        self._palette_doc = palette_doc
        self._palette_baseline = copy.deepcopy(palette_doc)
        self._dirty = set()
        self._rebuild_form()

    def _show_unavailable(self):
        self._font_widgets = {}
        self._font_dots = {}
        self._palette_buttons = {}
        self._palette_dots = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/ui/fonts.json or data/ui/palette.json is missing or "
            "invalid — nothing to edit here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)
        self.save_button.setEnabled(False)

    def _rebuild_form(self):
        self._font_widgets = {}
        self._font_dots = {}
        self._palette_buttons = {}
        self._palette_dots = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)

        fonts_schema = data_io.load_json(theme_ops.fonts_schema_path(self._data_dir))
        size_bounds = fonts_schema["$defs"]["font_spec"]["properties"]["size"]
        lo = int(size_bounds.get("minimum", 4))
        hi = int(size_bounds.get("maximum", 72))

        fonts_section = CollapsibleSection(
            "Fonts",
            "Point size + bold per preset (engine/render/fonts.py's font_key "
            "set). Size changes drawn glyphs only — stored layout rects are "
            "pinned (layout_h) and a very different size can overflow its "
            "widget.",
            expanded=True, parent=content)
        fonts_form = QFormLayout()
        for key in sorted(self._fonts_doc):
            row, size_spin, bold_check, dot = self._build_font_row(key, lo, hi)
            fonts_form.addRow(key, row)
            self._font_widgets[key] = (size_spin, bold_check)
            self._font_dots[key] = dot
        fonts_section.content_layout.addLayout(fonts_form)
        content_layout.addWidget(fonts_section)

        palette_section = CollapsibleSection(
            "Palette",
            "Every named UI color the game draws (game/ui/widgets.py's C_* "
            "block) — press a swatch to change it.",
            expanded=True, parent=content)
        palette_form = QFormLayout()
        for key in sorted(self._palette_doc):
            row, dot = self._build_palette_row(key)
            palette_form.addRow(key, row)
            self._palette_dots[key] = dot
        palette_section.content_layout.addLayout(palette_form)
        content_layout.addWidget(palette_section)

        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        self.save_button.setEnabled(bool(self._dirty))

    # -- row builders ---------------------------------------------------------

    def _build_font_row(self, key, lo, hi):
        spec = self._fonts_doc[key]
        size_spin = _NoWheelSpinBox(self)
        size_spin.setRange(lo, hi)
        size_spin.setValue(spec["size"])
        size_spin.valueChanged.connect(
            lambda v, k=key: self._on_font_size_changed(k, int(v)))
        bold_check = QCheckBox("Bold", self)
        bold_check.setChecked(spec["bold"])
        bold_check.toggled.connect(
            lambda v, k=key: self._on_font_bold_changed(k, bool(v)))
        dot = self._make_dot()
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(size_spin)
        row_layout.addWidget(bold_check)
        row_layout.addWidget(dot)
        return row, size_spin, bold_check, dot

    def _build_palette_row(self, key):
        button = QPushButton(self)
        self._set_swatch(button, self._palette_doc[key])
        button.clicked.connect(
            lambda _checked=False, k=key: self._on_palette_clicked(k))
        self._palette_buttons[key] = button
        dot = self._make_dot()
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.addWidget(button, 1)
        row_layout.addWidget(dot)
        return row, dot

    def _make_dot(self):
        dot = QLabel("●", self)
        dot.setStyleSheet("color: white;")
        dot.setFixedWidth(12)
        dot.setVisible(False)
        return dot

    @staticmethod
    def _set_swatch(button, rgb):
        r, g, b = rgb[0], rgb[1], rgb[2]
        button.setText(f"{r}, {g}, {b}")
        text_color = "white" if (r + g + b) < 380 else "black"
        button.setStyleSheet(
            f"background-color: rgb({r}, {g}, {b}); color: {text_color};")

    # -- staged edits: every change mutates a doc + a dirty dot --------------

    def _on_font_size_changed(self, key, value):
        self._fonts_doc[key]["size"] = value
        self._refresh_font_dirty(key)

    def _on_font_bold_changed(self, key, value):
        self._fonts_doc[key]["bold"] = value
        self._refresh_font_dirty(key)

    def _refresh_font_dirty(self, key):
        dirty_key = f"font:{key}"
        if self._fonts_doc[key] != self._fonts_baseline[key]:
            self._dirty.add(dirty_key)
        else:
            self._dirty.discard(dirty_key)
        dot = self._font_dots.get(key)
        if dot is not None:
            dot.setVisible(dirty_key in self._dirty)
        self.save_button.setEnabled(bool(self._dirty))

    def _on_palette_clicked(self, key):
        current = self._palette_doc[key]
        base = QColor(current[0], current[1], current[2])
        chosen = QColorDialog.getColor(base, self, f"Pick {key}")
        if not chosen.isValid():
            return
        new_value = [chosen.red(), chosen.green(), chosen.blue()]
        if new_value == list(self._palette_doc[key]):
            return
        self._palette_doc[key] = new_value
        self._set_swatch(self._palette_buttons[key], new_value)
        self._refresh_palette_dirty(key)

    def _refresh_palette_dirty(self, key):
        dirty_key = f"palette:{key}"
        if list(self._palette_doc[key]) != list(self._palette_baseline[key]):
            self._dirty.add(dirty_key)
        else:
            self._dirty.discard(dirty_key)
        dot = self._palette_dots.get(key)
        if dot is not None:
            dot.setVisible(dirty_key in self._dirty)
        self.save_button.setEnabled(bool(self._dirty))

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if not self._dirty:
            return
        if any(k.startswith("font:") for k in self._dirty):
            theme_ops.write_fonts(self._fonts_doc, self._data_dir)
            self._fonts_baseline = copy.deepcopy(self._fonts_doc)
        if any(k.startswith("palette:") for k in self._dirty):
            theme_ops.write_palette(self._palette_doc, self._data_dir)
            self._palette_baseline = copy.deepcopy(self._palette_doc)
        self._dirty = set()
        for dot in list(self._font_dots.values()) + list(self._palette_dots.values()):
            dot.setVisible(False)
        self.save_button.setEnabled(False)
        self.saved.emit()
