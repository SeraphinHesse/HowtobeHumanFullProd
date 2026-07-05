"""DetailsPanel (ED-40/ED-41) — subcategory picker + asset importer, full
parity with the prototype importer's semantics.

Sits on the right of the shell. Top: the subcategory dropdown (tier for
tiered buildings, the concrete slot otherwise — see editor.selection).
Below: the import editor for the RESOLVED slot: import a sheet PNG (grid
check at the slot's registry frame size, off-grid warning, the PNG is
copied to data/sprites/imported/<slot>.png AT IMPORT TIME — prototype
parity), one RowEditor per sheet row (row 0's animation combo is locked to
"idle": the E-35 rule lives in the UI, not save-time validation), per-row
fps / hidden / loop range×count, entry-level offset X/Y, Save (manifest v2
through engine.data_io's validating writer) and Clear-to-placeholder
(confirm, then entry + PNG removed).

The ANIMATED preview is NOT here: every widget edit emits
draft_changed(slot, entry_dict) and the viewport renders the draft through
the real engine pipeline (ED-22 — one render path; this panel is plain Qt
forms). Imports only the pure half of engine.assets + Pillow; no pygame.
"""
import shutil
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from editor import selection
from engine import data_io
from engine.assets import load_manifest, load_registry

REPO = Path(__file__).resolve().parents[2]


class RowEditor(QGroupBox):
    """Per-sheet-row controls: animation, fps, loop range×count, hide
    toggles (prototype RowEditor parity)."""

    changed = Signal()

    def __init__(self, row_index, num_cols, vocabulary, parent=None):
        title = f"Row {row_index}" + ("  (idle — required)" if row_index == 0 else "")
        super().__init__(title, parent)
        self.row_index = row_index
        self.num_cols = num_cols

        top = QHBoxLayout()
        top.addWidget(QLabel("Animation:"))
        self.anim_combo = QComboBox()
        if row_index == 0:
            self.anim_combo.addItems(["idle"])   # row 0 = idle, unrepresentable otherwise
            self.anim_combo.setEnabled(False)
        else:
            self.anim_combo.addItems(list(vocabulary))
        top.addWidget(self.anim_combo)
        top.addWidget(QLabel("FPS:"))
        self.fps_spin = QSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(8)
        top.addWidget(self.fps_spin)
        top.addStretch(1)

        loop = QHBoxLayout()
        loop.addWidget(QLabel("Loop frames"))
        self.loop_start = QSpinBox()
        self.loop_end = QSpinBox()
        for spin in (self.loop_start, self.loop_end):
            spin.setRange(0, max(0, num_cols - 1))
        self.loop_count = QSpinBox()
        self.loop_count.setRange(1, 99)
        loop.addWidget(self.loop_start)
        loop.addWidget(QLabel("to"))
        loop.addWidget(self.loop_end)
        loop.addWidget(QLabel("×"))
        loop.addWidget(self.loop_count)
        loop.addWidget(QLabel("(count 1 = no loop)"))
        loop.addStretch(1)

        hide = QHBoxLayout()
        hide.addWidget(QLabel("Hide frames:"))
        self.hide_boxes = []
        from PySide6.QtWidgets import QCheckBox
        for col in range(num_cols):
            box = QCheckBox(str(col))
            hide.addWidget(box)
            self.hide_boxes.append(box)
        hide.addStretch(1)

        body = QVBoxLayout(self)
        body.addLayout(top)
        body.addLayout(loop)
        body.addLayout(hide)

        self.anim_combo.currentTextChanged.connect(lambda _t: self.changed.emit())
        self.fps_spin.valueChanged.connect(lambda _v: self.changed.emit())
        for spin in (self.loop_start, self.loop_end, self.loop_count):
            spin.valueChanged.connect(lambda _v: self.changed.emit())
        for box in self.hide_boxes:
            box.toggled.connect(lambda _c: self.changed.emit())

    def set_from(self, row):
        if self.row_index != 0:
            index = self.anim_combo.findText(row.get("animation", "idle"))
            if index >= 0:
                self.anim_combo.setCurrentIndex(index)
        self.fps_spin.setValue(int(row.get("fps", 8)) or 8)
        hidden = set(row.get("hidden", ()))
        for col, box in enumerate(self.hide_boxes):
            box.setChecked(col in hidden)
        self.loop_start.setValue(int(row.get("loop_start", 0)))
        self.loop_end.setValue(int(row.get("loop_end", 0)))
        self.loop_count.setValue(int(row.get("loop_count", 1)))

    def to_dict(self):
        return {
            "animation": self.anim_combo.currentText() or "idle",
            "frames": self.num_cols,
            "fps": self.fps_spin.value(),
            "hidden": [c for c, box in enumerate(self.hide_boxes) if box.isChecked()],
            "loop_start": self.loop_start.value(),
            "loop_end": self.loop_end.value(),
            "loop_count": self.loop_count.value(),
        }


class DetailsPanel(QWidget):
    subcategory_changed = Signal(int)
    draft_changed = Signal(str, object)     # (slot_key, entry_dict | None)
    entry_saved = Signal(str)
    entry_cleared = Signal(str)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.registry = load_registry(self._data_dir)
        self.slot_key = None
        self._context = None            # (category_key, group_path)
        self._row_editors = []
        self._loading = False

        self._subcat_combo = QComboBox()
        self._subcat_combo.currentIndexChanged.connect(self._on_subcat_changed)
        self._subcat_combo.hide()

        self._header = QLabel("Select a slot in the tree.")
        self._info = QLabel("")
        self._info.setWordWrap(True)

        self._import_btn = QPushButton("Import Spritesheet…")
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self.save)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.clear_entry)
        buttons = QHBoxLayout()
        for btn in (self._import_btn, self._save_btn, self._clear_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)

        offsets = QHBoxLayout()
        offsets.addWidget(QLabel("Offset  X:"))
        self._offset_x = QSpinBox()
        self._offset_y = QSpinBox()
        for spin in (self._offset_x, self._offset_y):
            spin.setRange(-256, 256)
            spin.valueChanged.connect(lambda _v: self._emit_draft())
        offsets.addWidget(self._offset_x)
        offsets.addWidget(QLabel("Y:"))
        offsets.addWidget(self._offset_y)
        offsets.addWidget(QLabel("(−Y = up)"))
        offsets.addStretch(1)

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows_host)

        layout = QVBoxLayout(self)
        layout.addWidget(self._subcat_combo)
        layout.addWidget(self._header)
        layout.addLayout(buttons)
        layout.addLayout(offsets)
        layout.addWidget(self._info)
        layout.addWidget(scroll, 1)
        self._set_buttons_enabled(False, False, False)

    # -- subcategory dropdown (fed by the shell from the tree selection) ----

    def set_context(self, category_key, group_path):
        """Populate the subcategory dropdown for a tree node; ● marks
        subcategories with at least one assigned slot (ED-11)."""
        self._context = (category_key, tuple(group_path))
        labels = selection.subcategories(self.registry, category_key, group_path)
        assigned = set(load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json").slots())
        combo = self._subcat_combo
        combo.blockSignals(True)
        combo.clear()
        for i, label in enumerate(labels):
            slots = selection.level_slots(self.registry, category_key,
                                          group_path, i)
            marked = any(slot in assigned for slot in slots)
            combo.addItem(("● " + label) if marked else label)
        combo.setCurrentIndex(0 if labels else -1)
        combo.blockSignals(False)
        combo.setVisible(bool(labels))
        if not labels:
            self.set_slot(None)

    def subcategory_index(self):
        return max(0, self._subcat_combo.currentIndex())

    def select_subcategory(self, index):
        """Programmatically pick a subcategory (used after adding a variant so
        the dropdown stays on the same era); emits subcategory_changed when it
        actually moves."""
        if 0 <= index < self._subcat_combo.count():
            self._subcat_combo.setCurrentIndex(index)

    def reload_registry(self):
        """Re-read the registry after a slots.json edit so a freshly added
        variant slot resolves (frame size, animation vocabulary)."""
        self.registry = load_registry(self._data_dir)

    def _on_subcat_changed(self, index):
        if index >= 0:
            self.subcategory_changed.emit(index)

    # -- slot context (the import editor half) -------------------------------

    def set_slot(self, slot_key):
        """Load the import editor for a resolved slot (None disables it)."""
        self.slot_key = slot_key
        self._loading = True
        try:
            self._clear_rows()
            self._offset_x.setValue(0)
            self._offset_y.setValue(0)
            self._info.setText("")
            if slot_key is None:
                self._header.setText("Select a slot in the tree.")
                self._set_buttons_enabled(False, False, False)
                return
            fw, fh = self.registry.frame_size(slot_key)
            self._header.setText(f"[{slot_key}]  {fw}×{fh}/frame")
            entry = self._read_doc()["entries"].get(slot_key)
            if entry:
                self._offset_x.setValue(int(entry.get("offset_x", 0)))
                self._offset_y.setValue(int(entry.get("offset_y", 0)))
            sheet = self._sheet_path(slot_key)
            if sheet.exists():
                self._load_sheet(sheet, entry)
            else:
                self._info.setText("No spritesheet imported — grey-X placeholder.")
                self._set_buttons_enabled(True, False, bool(entry))
        finally:
            self._loading = False

    def import_sheet(self, png_path):
        """Copy a sheet PNG in (AT IMPORT TIME, prototype parity) and build
        the row editors. Returns (cols, rows, clean_grid) or None when the
        image is smaller than one frame. Off-grid sheets warn but import —
        the remainder is cropped, exactly like the prototype."""
        if self.slot_key is None:
            return None
        fw, fh = self.registry.frame_size(self.slot_key)
        with Image.open(png_path) as image:
            w, h = image.size
        cols, rows = w // fw, h // fh
        if cols < 1 or rows < 1:
            self._info.setText(
                f"⚠ image is smaller than one {fw}×{fh} frame — not imported.")
            return None
        destination = self._sheet_path(self.slot_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if Path(png_path).resolve() != destination.resolve():
            shutil.copyfile(png_path, destination)
        entry = self._read_doc()["entries"].get(self.slot_key)
        self._loading = True
        try:
            self._load_sheet(destination, entry)
        finally:
            self._loading = False
        self._emit_draft()
        even = (w % fw == 0) and (h % fh == 0)
        return (cols, rows, even)

    def draft_entry(self):
        """Current UI state as a manifest-v2 entry dict (None: no rows)."""
        if self.slot_key is None or not self._row_editors:
            return None
        return {
            "sheet": f"imported/{self.slot_key}.png",
            "frame_w": self._row_frame_size[0],
            "frame_h": self._row_frame_size[1],
            "offset_x": self._offset_x.value(),
            "offset_y": self._offset_y.value(),
            "rows": [editor.to_dict() for editor in self._row_editors],
        }

    def save(self):
        """Write the draft into the manifest through the validating writer."""
        draft = self.draft_entry()
        if draft is None:
            return
        doc = self._read_doc()
        doc["entries"][self.slot_key] = draft
        self._write_doc(doc)
        self._info.setText("Saved ✓")
        self._set_buttons_enabled(True, True, True)
        self.entry_saved.emit(self.slot_key)

    def clear_entry(self, confirm=True):
        """Clear-to-placeholder: remove the manifest entry AND the imported
        PNG (after a confirm in the UI path)."""
        if self.slot_key is None:
            return
        if confirm:
            answer = QMessageBox.question(
                self, "Clear spritesheet",
                f"Remove the imported spritesheet for '{self.slot_key}'?\n\n"
                "This deletes the imported PNG and its manifest entry; the "
                "slot reverts to the grey-X placeholder.")
            if answer != QMessageBox.StandardButton.Yes:
                return
        slot_key = self.slot_key
        doc = self._read_doc()
        if slot_key in doc["entries"]:
            del doc["entries"][slot_key]
            self._write_doc(doc)
        self._sheet_path(slot_key).unlink(missing_ok=True)
        self._loading = True
        try:
            self._clear_rows()
            self._offset_x.setValue(0)
            self._offset_y.setValue(0)
        finally:
            self._loading = False
        self._info.setText("Cleared — slot reverts to the grey-X placeholder.")
        self._set_buttons_enabled(True, False, False)
        self.entry_cleared.emit(slot_key)

    # -- internals -----------------------------------------------------------

    def _sheet_path(self, slot_key):
        return self._data_dir / "sprites" / "imported" / f"{slot_key}.png"

    def _read_doc(self):
        path = self._data_dir / "sprites" / "asset_manifest.json"
        try:
            doc = data_io.load_json(path)
        except (OSError, ValueError):
            return {"version": 2, "entries": {}}
        if not isinstance(doc, dict) or not isinstance(doc.get("entries"), dict):
            return {"version": 2, "entries": {}}
        return doc

    def _write_doc(self, doc):
        data_io.write_validated(
            doc,
            self._data_dir / "sprites" / "asset_manifest.json",
            self._data_dir / "schemas" / "asset_manifest.schema.json")

    def _load_sheet(self, sheet_path, entry):
        fw, fh = self.registry.frame_size(self.slot_key)
        self._row_frame_size = (fw, fh)
        with Image.open(sheet_path) as image:
            w, h = image.size
        cols, rows = w // fw, h // fh
        if cols < 1 or rows < 1:
            self._info.setText(f"⚠ sheet too small for one {fw}×{fh} frame.")
            self._set_buttons_enabled(True, False, bool(entry))
            return
        if (w % fw) or (h % fh):
            self._info.setText(
                f"⚠ not a clean {fw}×{fh} grid — remainder cropped "
                f"({cols} cols × {rows} rows).")
        else:
            self._info.setText(f"{cols} cols × {rows} rows  ({fw}×{fh}/frame)")
        self._clear_rows()
        vocabulary = self.registry.animations(self.slot_key)
        saved_rows = (entry or {}).get("rows", [])
        for r in range(rows):
            editor = RowEditor(r, cols, vocabulary)
            if r < len(saved_rows):
                editor.set_from(saved_rows[r])
            elif r > 0:
                index = editor.anim_combo.findText(
                    vocabulary[min(r, len(vocabulary) - 1)])
                if index >= 0:
                    editor.anim_combo.setCurrentIndex(index)
            editor.changed.connect(self._emit_draft)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, editor)
            self._row_editors.append(editor)
        self._set_buttons_enabled(True, True, True)

    def _clear_rows(self):
        for editor in self._row_editors:
            self._rows_layout.removeWidget(editor)
            editor.deleteLater()
        self._row_editors = []

    def _set_buttons_enabled(self, import_ok, save_ok, clear_ok):
        self._import_btn.setEnabled(import_ok)
        self._save_btn.setEnabled(save_ok)
        self._clear_btn.setEnabled(clear_ok)

    def _emit_draft(self):
        if self._loading or self.slot_key is None:
            return
        self.draft_changed.emit(self.slot_key, self.draft_entry())

    def _on_import_clicked(self):
        if self.slot_key is None:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose spritesheet PNG", "", "PNG images (*.png)")
        if path:
            self.import_sheet(path)
