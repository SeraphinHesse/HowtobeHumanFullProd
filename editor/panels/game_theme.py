"""GameThemePanel (UH-6, D5; UH-Font-A) — the right-pane form shown while the
"Theme" leaf (selector ▸ ui ▸ Theme) is selected: a global-ish document,
reached the selection-driven way (ED-3), sibling of the "Screens" branch.

Edits ``data/ui/fonts.json`` (per-key size spinbox, schema-bounded, + bold
checkbox), ``data/ui/palette.json`` (per-key color swatch button ->
``QColorDialog``), and ``data/ui/active_font.json`` (a font-family combo +
"Import Font…" button, UH-Font-A — ORTHOGONAL to the size/bold presets
above: "Default" keeps today's SysFont monospace, any other choice is a
designer-imported ``data/fonts/imported/*.ttf``/``*.otf`` picked from
``data/fonts/font_manifest.json``). Named to avoid colliding with
``editor/theme.py`` (the Qt chrome light/dark theme, untouched by this
phase).

Edits are STAGED, not written immediately — the ``balancing.py`` pattern
(``editor/panels/CLAUDE.md`` Phase 4), not the screen-session undo pattern:
every change updates an in-memory doc + a small dirty dot next to that field
(compared against a baseline captured at load/last-save time); ONE "Save
Theme Changes" button (enabled only while dirty) is the sole
``engine.data_io.write_validated`` call site. Saving emits ``saved`` so
``MainWindow`` can reconfigure ``engine.render.fonts`` in-process and repaint
the viewport (chrome theme, ``editor/theme.py``, untouched).

**"Import Font…" is the one exception to "staged"**: like
``DetailsPanel``'s sprite import, it copies the file + writes the
``font_manifest.json`` entry to disk IMMEDIATELY (through
``editor.font_import.import_font_file``) — only the CHOICE of which font is
*active* is staged, not the act of importing one.
"""
import copy
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import font_import, theme_ops
from editor.panels.balancing import CollapsibleSection, _NoWheelComboBox, _NoWheelSpinBox
from engine import data_io

REPO = Path(__file__).resolve().parents[2]

_DEFAULT_FONT_LABEL = "Default (System Monospace)"
_PREVIEW_TEXT = "The quick brown fox jumps over the lazy dog"


class GameThemePanel(QWidget):
    saved = Signal()   # MainWindow reconfigures engine.render.fonts + repaints

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._fonts_doc = None
        self._fonts_baseline = None
        self._palette_doc = None
        self._palette_baseline = None
        self._font_manifest_doc = None      # data/fonts/font_manifest.json
        self._active_font_doc = None        # data/ui/active_font.json
        self._active_font_baseline = None
        self._font_widgets = {}     # key -> (size_spin, bold_check)
        self._font_dots = {}
        self._palette_buttons = {}  # key -> swatch QPushButton
        self._palette_dots = {}
        self._font_family_combo = None
        self._active_font_dot = None
        self._preview_labels = {}   # font_key -> QLabel
        self._loaded_font_families = {}  # font_id -> Qt family name (cache)
        self._dirty = set()         # {"font:<key>", "palette:<key>", "active_font"}

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
        """(Re)load every doc fresh from disk and rebuild the form — called
        on entry (the "Theme" leaf's selection handler) and by ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid
        fonts.json/palette.json/font_manifest.json/active_font.json shows a
        placeholder instead of raising out of a constructor/Qt slot — the
        editor must open on a broken tree. The GAME's own boot load
        (game/main.py) fails loud instead (D-2: this is data, not art);
        that rule is unchanged."""
        try:
            fonts_doc = theme_ops.load_fonts(self._data_dir)
            palette_doc = theme_ops.load_palette(self._data_dir)
            font_manifest_doc = theme_ops.load_font_manifest(self._data_dir)
            active_font_doc = theme_ops.load_active_font(self._data_dir)
        except Exception:
            self._fonts_doc = None
            self._palette_doc = None
            self._fonts_baseline = None
            self._palette_baseline = None
            self._font_manifest_doc = None
            self._active_font_doc = None
            self._active_font_baseline = None
            self._loaded_font_families = {}
            self._dirty = set()
            self._show_unavailable()
            return
        self._fonts_doc = fonts_doc
        self._fonts_baseline = copy.deepcopy(fonts_doc)
        self._palette_doc = palette_doc
        self._palette_baseline = copy.deepcopy(palette_doc)
        self._font_manifest_doc = font_manifest_doc
        self._active_font_doc = active_font_doc
        self._active_font_baseline = copy.deepcopy(active_font_doc)
        self._loaded_font_families = {}
        self._dirty = set()
        self._rebuild_form()

    def _show_unavailable(self):
        self._font_widgets = {}
        self._font_dots = {}
        self._palette_buttons = {}
        self._palette_dots = {}
        self._font_family_combo = None
        self._active_font_dot = None
        self._preview_labels = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        placeholder = QLabel(
            "data/ui/fonts.json, data/ui/palette.json, "
            "data/fonts/font_manifest.json or data/ui/active_font.json is "
            "missing or invalid — nothing to edit here.", self)
        placeholder.setWordWrap(True)
        self._scroll.setWidget(placeholder)
        self.save_button.setEnabled(False)

    def _rebuild_form(self):
        self._font_widgets = {}
        self._font_dots = {}
        self._palette_buttons = {}
        self._palette_dots = {}
        self._font_family_combo = None
        self._active_font_dot = None
        self._preview_labels = {}
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

        font_family_section = CollapsibleSection(
            "Font Family",
            "The game-wide custom font (UH-Font-A), ORTHOGONAL to the size/"
            "bold presets above — 'Default' keeps today's system monospace. "
            "Import a .ttf/.otf, pick it below, then Save to make it active.",
            expanded=True, parent=content)
        font_family_section.content_layout.addWidget(
            self._build_font_family_section())
        content_layout.addWidget(font_family_section)

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

    # -- Font Family (UH-Font-A): import + active-font combo + preview -------

    def _build_font_family_section(self):
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        picker_row = QWidget(container)
        picker_layout = QHBoxLayout(picker_row)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        import_button = QPushButton("Import Font…", picker_row)
        import_button.clicked.connect(self._on_import_font_clicked)
        combo = _NoWheelComboBox(picker_row)
        self._font_family_combo = combo
        self._populate_font_combo()
        combo.currentIndexChanged.connect(self._on_font_family_changed)
        dot = self._make_dot()
        self._active_font_dot = dot
        picker_layout.addWidget(import_button)
        picker_layout.addWidget(combo, 1)
        picker_layout.addWidget(dot)
        layout.addWidget(picker_row)

        preview_form = QFormLayout()
        for key in sorted(self._fonts_doc):
            label = QLabel(_PREVIEW_TEXT, container)
            label.setWordWrap(True)
            self._preview_labels[key] = label
            preview_form.addRow(key, label)
        layout.addLayout(preview_form)

        self._refresh_preview()
        return container

    def _populate_font_combo(self):
        combo = self._font_family_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(_DEFAULT_FONT_LABEL, "default")
        for font_id, entry in sorted(
                self._font_manifest_doc["entries"].items(),
                key=lambda kv: kv[1]["display_name"].lower()):
            combo.addItem(entry["display_name"], font_id)
        current = self._active_font_doc["font_id"]
        index = combo.findData(current)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def _on_import_font_clicked(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import Font", "", "Fonts (*.ttf *.otf)")
        if not path:
            return
        try:
            font_id = font_import.import_font_file(self._data_dir, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import Font", str(exc))
            return
        self._font_manifest_doc = theme_ops.load_font_manifest(self._data_dir)
        self._populate_font_combo()
        index = self._font_family_combo.findData(font_id)
        if index >= 0:
            self._font_family_combo.setCurrentIndex(index)

    def _on_font_family_changed(self, _index):
        font_id = self._font_family_combo.currentData()
        if font_id is None:
            return
        self._active_font_doc["font_id"] = font_id
        self._refresh_active_font_dirty()
        self._refresh_preview()

    def _refresh_active_font_dirty(self):
        dirty_key = "active_font"
        if self._active_font_doc["font_id"] != self._active_font_baseline["font_id"]:
            self._dirty.add(dirty_key)
        else:
            self._dirty.discard(dirty_key)
        if self._active_font_dot is not None:
            self._active_font_dot.setVisible(dirty_key in self._dirty)
        self.save_button.setEnabled(bool(self._dirty))

    def _family_for_font_id(self, font_id):
        """Qt family name for the CURRENTLY SELECTED combo choice — 'None'
        (Qt's own default) for 'default', loading the .ttf/.otf into
        QFontDatabase (cached per font_id) otherwise.

        **Registered from BYTES, never a path** (the exact argument
        ``engine.render.fonts.configure_fonts`` makes for its own side):
        ``QFontDatabase.addApplicationFont(<path>)`` itself is harmless, but
        the first time Qt's font engine actually loads a glyph from that
        family it opens the file and holds it for as long as the family
        stays registered — on Windows that is a hard lock, so a preview
        render would leave the editor sitting on the designer's font file
        and would break every ``TempDataCase`` teardown that rmtree's a
        copied ``data/``. ``addApplicationFontFromData`` copies into memory
        up front and never touches the path again."""
        if font_id == "default":
            return None
        if font_id in self._loaded_font_families:
            return self._loaded_font_families[font_id]
        entry = self._font_manifest_doc["entries"].get(font_id)
        if entry is None:
            return None
        path = self._data_dir / "fonts" / entry["file"]
        try:
            data = Path(path).read_bytes()
        except OSError:
            self._loaded_font_families[font_id] = None
            return None
        font_db_id = QFontDatabase.addApplicationFontFromData(data)
        families = QFontDatabase.applicationFontFamilies(font_db_id)
        family = families[0] if families else None
        self._loaded_font_families[font_id] = family
        return family

    def _refresh_preview(self):
        if not self._preview_labels or self._active_font_doc is None:
            return
        family = self._family_for_font_id(self._active_font_doc["font_id"])
        for key, label in self._preview_labels.items():
            spec = self._fonts_doc[key]
            font = QFont(family) if family else QFont()
            font.setPointSize(spec["size"])
            font.setBold(spec["bold"])
            label.setFont(font)

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
        self._refresh_preview()   # UH-Font-A: size/bold edits move the preview too

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
        if "active_font" in self._dirty:
            theme_ops.write_active_font(self._active_font_doc, self._data_dir)
            self._active_font_baseline = copy.deepcopy(self._active_font_doc)
        self._dirty = set()
        for dot in (list(self._font_dots.values())
                    + list(self._palette_dots.values())
                    + ([self._active_font_dot] if self._active_font_dot else [])):
            dot.setVisible(False)
        self.save_button.setEnabled(False)
        self.saved.emit()
