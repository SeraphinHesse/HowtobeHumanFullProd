"""DetailsPanel (ED-40/ED-41) — subcategory picker + asset importer, full
parity with the prototype importer's semantics.

Sits on the right of the shell. Top: the subcategory dropdown (tier for
tiered buildings, the concrete slot otherwise — see editor.selection).
Below: the import editor for the RESOLVED slot: import a sheet PNG (grid
check at the slot's registry frame size, off-grid warning, the PNG is
copied to data/sprites/imported/<slot>.png AT IMPORT TIME — prototype
parity), one RowEditor per sheet row (row 0's animation combo is locked to
"idle": the E-35 rule lives in the UI, not save-time validation), per-row
fps / hidden / loop range×count / static, entry-level offset X/Y, Save
(manifest v2 through engine.data_io's validating writer) and
Clear-to-placeholder (confirm, then entry + unreferenced PNG removed).

**A slot's sheet is NOT derivable from its key.** "Use Spritesheet…" LINKS a
slot to art already in data/sprites/imported/ — the entry's `sheet` points at
another slot's PNG and no bytes are copied, so one file backs many slots (the
engine already resolves `sprites_dir / entry.sheet` verbatim). Always read the
ref off the entry (`self._sheet_ref`), never re-derive `imported/<slot>.png`;
that name is only the FALLBACK for a slot with no entry, and the destination a
fresh file-import re-owns. It is also why Clear refcounts before unlinking
(`asset_import.unreferenced_sheets`) — deleting a shared PNG would blank every
other slot using it.

The ANIMATED preview is NOT here: every widget edit emits
draft_changed(slot, entry_dict) and the viewport renders the draft through
the real engine pipeline (ED-22 — one render path; this panel is plain Qt
forms). SheetPreview shows the raw source PNG (an inspection view of the
importer's own input, not a second renderer of game content — see its module
docstring). Imports only the pure half of engine.assets + Pillow; no pygame.
"""
import shutil
from pathlib import Path

from PIL import Image
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from editor import asset_import, master_sheet_import, registry_ops, selection
from editor.asset_import import pad_to_frame
from editor.panels.balancing import _NoWheelComboBox, _NoWheelSpinBox
from editor.panels.master_sheet_dialog import MasterSheetDialog
from editor.panels.sheet_picker import SheetPickerDialog
from editor.panels.sheet_preview import SheetPreview
from engine.assets import load_manifest, load_registry, master_registry

REPO = Path(__file__).resolve().parents[2]

# The slots.json category whose art the game draws on the `terrain` layer for
# tile conditions — the only one the tint-fallback checkbox applies to. Named
# here rather than imported: `editor/` may never import `game/`.
CONDITION_CATEGORY = "conditions"

#: A manifest `sheet` under this prefix is a MASTER spritesheet (D1) — one PNG
#: many slots cut their own row window out of. Tested against the entry's
#: STORED ref, never re-derived from the slot key.
MASTER_PREFIX = "master/"

MASTER_GRID_TOOLTIP = (
    "The master spritesheet owns this grid (D3) — every slot cutting it must\n"
    "agree on what a row means, so the frame size is inherited, not per-slot.")

COLUMN_WIDTH_TOOLTIP = (
    "The master spritesheet owns this value (D1) — how many frame columns one\n"
    "master column spans is a property of the SHEET, so it is inherited here,\n"
    "not editable per slot.")

#: `column` carries asset_manifest.schema.json's row_start bound EXACTLY
#: (0..255, 0-based) — one spelling of the bound, reused by the spin's static
#: range and by its per-sheet ceiling (ED-30).
COLUMN_RANGE = (0, 255)
#: `column_width` is 1..256 when authored; 0 is only the absent-key in-memory
#: default, never a value written.
COLUMN_WIDTH_RANGE = (1, 256)
#: Display label ⇄ stored enum value. The manifest stores the enum, NEVER the
#: friendly label; `column_mode` names WHO picks the column at render time (D3).
COLUMN_MODES = (("Manual", "manual"),
                ("Season", "season"),
                ("Building colour", "building_color"))
COLUMN_MODE_VALUES = {label: value for label, value in COLUMN_MODES}
COLUMN_MODE_LABELS = {value: label for label, value in COLUMN_MODES}
DEFAULT_COLUMN_MODE = "manual"


class RowEditor(QGroupBox):
    """Per-sheet-row controls: animation, fps, loop range×count, hide
    toggles (prototype RowEditor parity), plus STATIC mode.

    Static ("don't animate — just show this one frame") is a DERIVED view of the
    manifest's existing `hidden` array, never a stored flag: hiding every column
    but one already yields a still sprite, because `playback_order` drops hidden
    frames AFTER loop expansion (engine/assets/manifest.py). So there is no new
    schema key, no editor-only hidden state, and a static row a designer built by
    hand with the old checkboxes re-opens as static.

    The two frame widgets are kept independent on purpose — the hide checkboxes
    hold their own state while static is on, so unticking Static restores what you
    had rather than a derived approximation of it.
    """

    changed = Signal()

    def __init__(self, row_index, num_cols, vocabulary, parent=None):
        title = f"Row {row_index}" + ("  (idle — required)" if row_index == 0 else "")
        super().__init__(title, parent)
        self.row_index = row_index
        self.num_cols = num_cols

        top = QHBoxLayout()
        top.addWidget(QLabel("Animation:"))
        self.anim_combo = _NoWheelComboBox()
        if row_index == 0:
            self.anim_combo.addItems(["idle"])   # row 0 = idle, unrepresentable otherwise
            self.anim_combo.setEnabled(False)
        else:
            self.anim_combo.addItems(list(vocabulary))
        top.addWidget(self.anim_combo)
        top.addWidget(QLabel("FPS:"))
        self.fps_spin = _NoWheelSpinBox()
        self.fps_spin.setRange(1, 60)
        self.fps_spin.setValue(6)
        top.addWidget(self.fps_spin)
        self.static_check = QCheckBox("Static — don't animate")
        self.static_check.setToolTip(
            "Show one frame and never play this animation.\n"
            "Saved as: every other frame hidden.")
        top.addWidget(self.static_check)
        top.addStretch(1)

        self.loop_row = QWidget()
        loop = QHBoxLayout(self.loop_row)
        loop.setContentsMargins(0, 0, 0, 0)
        loop.addWidget(QLabel("Loop frames"))
        self.loop_start = _NoWheelSpinBox()
        self.loop_end = _NoWheelSpinBox()
        for spin in (self.loop_start, self.loop_end):
            spin.setRange(0, max(0, num_cols - 1))
        self.loop_count = _NoWheelSpinBox()
        self.loop_count.setRange(1, 99)
        loop.addWidget(self.loop_start)
        loop.addWidget(QLabel("to"))
        loop.addWidget(self.loop_end)
        loop.addWidget(QLabel("×"))
        loop.addWidget(self.loop_count)
        loop.addWidget(QLabel("(count 1 = no loop)"))
        loop.addStretch(1)

        self.hide_row = QWidget()
        hide = QHBoxLayout(self.hide_row)
        hide.setContentsMargins(0, 0, 0, 0)
        hide.addWidget(QLabel("Hide frames:"))
        self.hide_boxes = []
        for col in range(num_cols):
            box = QCheckBox(str(col))
            hide.addWidget(box)
            self.hide_boxes.append(box)
        hide.addStretch(1)

        # Shown INSTEAD of the hide row while static: one widget, one meaning —
        # "hide all but this" as an exclusive pick, not N checkboxes to count out.
        self.pick_row = QWidget()
        pick = QHBoxLayout(self.pick_row)
        pick.setContentsMargins(0, 0, 0, 0)
        pick.addWidget(QLabel("Show frame:"))
        self.frame_group = QButtonGroup(self)
        self.frame_radios = []
        for col in range(num_cols):
            radio = QRadioButton(str(col))
            self.frame_group.addButton(radio, col)
            pick.addWidget(radio)
            self.frame_radios.append(radio)
        if self.frame_radios:
            self.frame_radios[0].setChecked(True)
        pick.addStretch(1)
        self.pick_row.setVisible(False)

        body = QVBoxLayout(self)
        body.addLayout(top)
        body.addWidget(self.loop_row)
        body.addWidget(self.hide_row)
        body.addWidget(self.pick_row)

        self.anim_combo.currentTextChanged.connect(lambda _t: self.changed.emit())
        self.fps_spin.valueChanged.connect(lambda _v: self.changed.emit())
        for spin in (self.loop_start, self.loop_end, self.loop_count):
            spin.valueChanged.connect(lambda _v: self.changed.emit())
        for box in self.hide_boxes:
            box.toggled.connect(lambda _c: self.changed.emit())
        self.frame_group.idToggled.connect(self._on_frame_picked)
        self.static_check.toggled.connect(self._on_static_toggled)

    # -- static mode ---------------------------------------------------------

    def is_static(self):
        return self.static_check.isChecked()

    def static_frame(self):
        """The one visible column while static, else None (nothing to outline)."""
        if not self.is_static():
            return None
        checked = self.frame_group.checkedId()
        return checked if checked >= 0 else 0

    def set_static_frame(self, col):
        """Pick the visible frame — the preview's click target in static mode."""
        if 0 <= col < len(self.frame_radios):
            self.frame_radios[col].setChecked(True)

    def toggle_hidden(self, col):
        """Flip one column's hide box — the preview's click target otherwise."""
        if 0 <= col < len(self.hide_boxes):
            box = self.hide_boxes[col]
            box.setChecked(not box.isChecked())

    def effective_hidden(self):
        """The `hidden` array this row SAVES — the single source for both to_dict
        and the preview's dimming, so the two can never disagree."""
        if self.is_static():
            keep = self.static_frame()
            return [col for col in range(self.num_cols) if col != keep]
        return [c for c, box in enumerate(self.hide_boxes) if box.isChecked()]

    def _apply_static_mode(self):
        static = self.is_static()
        self.hide_row.setVisible(not static)
        self.pick_row.setVisible(static)
        # A loop over a one-visible-frame row is harmless (hidden frames drop
        # after expansion) but meaningless — say so by greying it out rather than
        # rewriting the designer's numbers behind their back.
        self.loop_row.setEnabled(not static)

    def _on_static_toggled(self, checked):
        if checked:
            # Default to the first frame that is currently VISIBLE — the most
            # likely one the designer means, and never a frame they just hid.
            visible = [c for c, box in enumerate(self.hide_boxes)
                       if not box.isChecked()]
            self.set_static_frame(visible[0] if visible else 0)
        self._apply_static_mode()
        self.changed.emit()

    def _on_frame_picked(self, _id, checked):
        if checked and self.is_static():
            self.changed.emit()

    # -- manifest round-trip --------------------------------------------------

    def set_from(self, row):
        if self.row_index != 0:
            index = self.anim_combo.findText(row.get("animation", "idle"))
            if index >= 0:
                self.anim_combo.setCurrentIndex(index)
        self.fps_spin.setValue(int(row.get("fps", 6)) or 6)
        hidden = {c for c in row.get("hidden", ()) if 0 <= c < self.num_cols}
        for col, box in enumerate(self.hide_boxes):
            box.setChecked(col in hidden)
        self.loop_start.setValue(int(row.get("loop_start", 0)))
        self.loop_end.setValue(int(row.get("loop_end", 0)))
        self.loop_count.setValue(int(row.get("loop_count", 1)))
        # Derive static: exactly one column left visible out of more than one.
        # A genuinely 1-frame row is NOT static — it has no animation to disable,
        # and auto-ticking the box on every tile sheet would be noise.
        visible = [c for c in range(self.num_cols) if c not in hidden]
        static = self.num_cols > 1 and len(visible) == 1
        self.static_check.setChecked(static)
        if static:
            self.set_static_frame(visible[0])
        self._apply_static_mode()

    def to_dict(self):
        return {
            "animation": self.anim_combo.currentText() or "idle",
            "frames": self.num_cols,
            "fps": self.fps_spin.value(),
            "hidden": self.effective_hidden(),
            "loop_start": self.loop_start.value(),
            "loop_end": self.loop_end.value(),
            "loop_count": self.loop_count.value(),
        }


class DetailsPanel(QWidget):
    subcategory_changed = Signal(int)
    draft_changed = Signal(str, object)     # (slot_key, entry_dict | None)
    entry_saved = Signal(str)
    entry_cleared = Signal(str)
    registry_changed = Signal(str)          # slots.json was written (frame size)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.registry = load_registry(self._data_dir)
        self.slot_key = None
        self._context = None            # (category_key, group_path)
        self._row_editors = []
        self._loading = False
        #: The sheet THIS slot's entry points at — may be another slot's PNG.
        self._sheet_ref = None
        self._row_frame_size = (1, 1)   # set for real by _load_sheet
        #: The ROW WINDOW into a master sheet (M4/D2): `_row_start` is the sheet
        #: row this entry's rows[0] cuts from, `_row_count` how many rows the
        #: window spans (None = to the bottom of the sheet). 0/None for every
        #: non-master sheet, which is what keeps those entries byte-identical.
        self._row_start = 0
        self._row_count = None
        self._sheet_rows = 0            # rows the CURRENT sheet really has
        #: The master sheet's own frame size while one is linked (D3) — the
        #: registry's per-slot size does not apply then.
        self._master_grid = None
        #: The COLUMN WINDOW into a master sheet — the row window's horizontal
        #: twin. `_column` is the 0-based master column this entry cuts,
        #: `_column_mode` declares WHO picks it at render time (D3), and
        #: `_column_width` is how many frame-columns one master column spans,
        #: INHERITED from the sheet's registry entry (D1 — the sheet owns it).
        #: 0/"manual"/0 for every non-master sheet, which is what keeps those
        #: entries byte-identical.
        self._column = 0
        self._column_mode = DEFAULT_COLUMN_MODE
        self._column_width = 0
        self._sheet_cols = 0            # frame-columns the CURRENT sheet has

        self._subcat_combo = _NoWheelComboBox()
        self._subcat_combo.currentIndexChanged.connect(self._on_subcat_changed)
        self._subcat_combo.hide()

        self._header = QLabel("Select a slot in the tree.")

        # Per-slot display name (editor-only). A slot key is the only label the
        # UI screen editor's skin pickers have, and `ui_panel_v2` vs
        # `ui_panel_v3` tells a designer nothing — so naming a variant here is
        # what makes it pickable over there. Committed on editingFinished (the
        # Frame W/H rule): typing a name does not write once per keystroke.
        self._name_row = QWidget()
        name_layout = QHBoxLayout(self._name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(QLabel("Name"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("(unnamed — shown as the slot key)")
        self._name_edit.setToolTip(
            "What this variant is called wherever the editor lists slots\n"
            "(the UI screen editor's Skin pickers, most of all). Editor-only —\n"
            "the game never reads it. Clear the field to go back to the key.")
        self._name_edit.editingFinished.connect(self._on_display_name_changed)
        name_layout.addWidget(self._name_edit, 1)
        self._info = QLabel("")
        self._info.setWordWrap(True)

        self._import_btn = QPushButton("Import Spritesheet…")
        self._import_btn.clicked.connect(self._on_import_clicked)
        self._use_btn = QPushButton("Use Spritesheet…")
        self._use_btn.setToolTip(
            "Point this slot at a spritesheet already imported in the game.\n"
            "Links to the same PNG — nothing is copied.")
        # clicked(bool checked) would land in a kwarg default — always wrap
        # (the panels-doc footgun that bit map_details' Delete).
        self._use_btn.clicked.connect(lambda: self._on_use_clicked())
        self._master_btn = QPushButton("Use Master Spritesheet…")
        self._master_btn.setToolTip(
            "Cut this slot's rows out of a MASTER spritesheet — one big PNG\n"
            "many characters share. The sheet owns the frame size; this slot\n"
            "claims a row window in it. Nothing is copied.")
        # Wrapped, like _use_btn/_clear_btn: a bare connect would put Qt's
        # clicked(bool checked) into the first argument (the panels-doc footgun).
        self._master_btn.clicked.connect(lambda: self._on_master_clicked())
        self._save_btn = QPushButton("Save")
        self._save_btn.clicked.connect(self.save)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(lambda: self.clear_entry())
        buttons = QHBoxLayout()
        for btn in (self._import_btn, self._use_btn, self._master_btn,
                    self._save_btn, self._clear_btn):
            buttons.addWidget(btn)
        buttons.addStretch(1)

        offsets = QHBoxLayout()
        offsets.addWidget(QLabel("Offset  X:"))
        self._offset_x = _NoWheelSpinBox()
        self._offset_y = _NoWheelSpinBox()
        for spin in (self._offset_x, self._offset_y):
            spin.setRange(-256, 256)
            spin.valueChanged.connect(lambda _v: self._emit_draft())
        offsets.addWidget(self._offset_x)
        offsets.addWidget(QLabel("Y:"))
        offsets.addWidget(self._offset_y)
        offsets.addWidget(QLabel("(−Y = up)"))
        offsets.addStretch(1)

        # Nine-slice margins (ui category only): corners fixed, edges stretched
        # by the HUD backend. Omitted from the entry when all four are 0.
        self._slice_row = QWidget()
        slice_layout = QHBoxLayout(self._slice_row)
        slice_layout.setContentsMargins(0, 0, 0, 0)
        self._slice_l = _NoWheelSpinBox()
        self._slice_t = _NoWheelSpinBox()
        self._slice_r = _NoWheelSpinBox()
        self._slice_b = _NoWheelSpinBox()
        self._slice_spins = (self._slice_l, self._slice_t,
                             self._slice_r, self._slice_b)   # order = manifest order
        slice_layout.addWidget(QLabel("Nine-slice  L:"))
        slice_layout.addWidget(self._slice_l)
        for label, spin in zip(("T:", "R:", "B:"), self._slice_spins[1:]):
            slice_layout.addWidget(QLabel(label))
            slice_layout.addWidget(spin)
        for spin in self._slice_spins:
            spin.setRange(0, 1024)
            spin.valueChanged.connect(lambda _v: self._emit_draft())
        slice_layout.addStretch(1)

        # Condition-tint fallback (conditions category only). The game draws a
        # flat colour diamond on every non-grass tile; that is a FALLBACK for a
        # condition with no art, so a slot with no sheet forces it on (checkbox
        # checked + disabled — there is no entry to write it to anyway). Once a
        # sheet is imported the designer chooses; unchecked omits the manifest
        # key entirely, so an untinted entry stays byte-identical.
        self._tint_row = QWidget()
        tint_layout = QHBoxLayout(self._tint_row)
        tint_layout.setContentsMargins(0, 0, 0, 0)
        self._tint_check = QCheckBox("Show condition tint under this art")
        self._tint_check.toggled.connect(lambda _v: self._emit_draft())
        tint_layout.addWidget(self._tint_check)
        tint_layout.addStretch(1)

        # Per-slot frame size (ER-5). Frame size is a CATEGORY property; this is
        # the per-slot override, and the ONE thing about a slot the editor could
        # not express. Committed on editingFinished, not valueChanged, so typing
        # "128" does not write three times on the way there.
        frames = QHBoxLayout()
        frames.addWidget(QLabel("Frame  W:"))
        self._frame_w = _NoWheelSpinBox()
        self._frame_h = _NoWheelSpinBox()
        for spin in (self._frame_w, self._frame_h):
            spin.setRange(1, 1024)          # slots.schema.json bounds (ED-30)
            spin.editingFinished.connect(self._on_frame_size_changed)
        frames.addWidget(self._frame_w)
        frames.addWidget(QLabel("H:"))
        frames.addWidget(self._frame_h)
        frames.addWidget(QLabel("(how the sheet is SLICED)"))
        frames.addStretch(1)

        # The master-sheet ROW WINDOW (D2/D4), built exactly like the Frame W/H
        # row above and shown only while the slot's sheet IS a master sheet.
        # `a > b` is unrepresentable (ED-30): the second spin's minimum tracks
        # the first as it moves, rather than a save-time error.
        self._master_row = QWidget()
        master_layout = QHBoxLayout(self._master_row)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.addWidget(QLabel("Using rows"))
        self._row_from = _NoWheelSpinBox()
        self._row_to = _NoWheelSpinBox()
        for spin in (self._row_from, self._row_to):
            spin.setRange(0, 255)       # asset_manifest.schema.json row_start
            spin.editingFinished.connect(self._on_row_window_changed)
        self._row_from.valueChanged.connect(self._row_to.setMinimum)
        master_layout.addWidget(self._row_from)
        master_layout.addWidget(QLabel("til"))
        master_layout.addWidget(self._row_to)
        master_layout.addWidget(QLabel("(rows of the master spritesheet)"))
        master_layout.addStretch(1)

        # The master-sheet COLUMN WINDOW (D1/D3) — the row window's horizontal
        # twin: same shape, same `_master_applies()` visibility gate, and the
        # same "writes nothing until Save" rule. The WIDTH is inherited from
        # the sheet, so it gets the Frame W/H treatment (a disabled spin with a
        # tooltip, not a bare QLabel) — tab order and styling stay uniform.
        self._column_row = QWidget()
        column_layout = QHBoxLayout(self._column_row)
        column_layout.setContentsMargins(0, 0, 0, 0)
        column_layout.addWidget(QLabel("Column"))
        self._column_spin = _NoWheelSpinBox()
        self._column_spin.setRange(*COLUMN_RANGE)   # per-sheet ceiling below
        self._column_spin.editingFinished.connect(self._on_column_changed)
        column_layout.addWidget(self._column_spin)
        column_layout.addWidget(QLabel("mode"))
        self._column_mode_combo = _NoWheelComboBox()
        self._column_mode_combo.addItems([label for label, _ in COLUMN_MODES])
        # Wrapped like every other connect in this panel: currentIndexChanged
        # hands the new index to the first argument (the panels-doc footgun).
        self._column_mode_combo.currentIndexChanged.connect(
            lambda _i: self._on_column_changed())
        column_layout.addWidget(self._column_mode_combo)
        column_layout.addWidget(QLabel("width:"))
        self._column_width_display = _NoWheelSpinBox()
        self._column_width_display.setRange(*COLUMN_WIDTH_RANGE)
        self._column_width_display.setEnabled(False)   # inherited, never edited
        self._column_width_display.setToolTip(COLUMN_WIDTH_TOOLTIP)
        column_layout.addWidget(self._column_width_display)
        column_layout.addWidget(QLabel("(columns of the master spritesheet)"))
        column_layout.addStretch(1)

        self._preview = SheetPreview(interactive=True)
        self._preview.frame_clicked.connect(self._on_frame_clicked)

        self._rows_host = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._rows_host)

        layout = QVBoxLayout(self)
        layout.addWidget(self._subcat_combo)
        layout.addWidget(self._header)
        layout.addWidget(self._name_row)
        layout.addLayout(buttons)
        layout.addWidget(self._preview)
        layout.addLayout(offsets)
        layout.addWidget(self._slice_row)
        layout.addWidget(self._tint_row)
        layout.addLayout(frames)
        layout.addWidget(self._master_row)
        layout.addWidget(self._column_row)
        layout.addWidget(self._info)
        layout.addWidget(scroll, 1)
        self._set_buttons_enabled(False, False, False)
        self._name_row.setVisible(False)
        self._slice_row.setVisible(False)
        self._tint_row.setVisible(False)
        self._master_row.setVisible(False)
        self._column_row.setVisible(False)

    # -- subcategory dropdown (fed by the shell from the tree selection) ----

    def set_context(self, category_key, group_path):
        """Populate the subcategory dropdown for a tree node; ● marks
        subcategories with at least one assigned slot (ED-11)."""
        self._context = (category_key, tuple(group_path))
        self._slice_row.setVisible(self._slice_applies())
        self._tint_row.setVisible(self._tint_applies())
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

    def select_subcategory_label(self, label):
        """Pick a subcategory by its LABEL (used after adding a deco type,
        whose index isn't known to the caller). Tolerates the ● assigned
        prefix; a no-op when the label isn't in the dropdown."""
        for i in range(self._subcat_combo.count()):
            if self._subcat_combo.itemText(i).removeprefix("● ") == label:
                self._subcat_combo.setCurrentIndex(i)
                return

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
            for spin in self._slice_spins:
                spin.setValue(0)
            self._info.setText("")
            self._reset_row_window()
            self._name_edit.setText(
                "" if slot_key is None else self.registry.display_name(slot_key))
            self._name_row.setVisible(slot_key is not None)
            if slot_key is None:
                self._sheet_ref = None
                self._header.setText("Select a slot in the tree.")
                self._set_buttons_enabled(False, False, False)
                self._refresh_tint_state()
                self._refresh_master_state()
                self._refresh_preview()
                return
            fw, fh = self.registry.frame_size(slot_key)
            self._header.setText(self._header_text(slot_key, fw, fh))
            # Populated even with no sheet imported: declaring the frame size
            # BEFORE the import is the point — it is what the importer slices
            # (and pads) against.
            self._frame_w.setValue(fw)
            self._frame_h.setValue(fh)
            for spin, cap in zip(self._slice_spins, (fw, fh, fw, fh)):
                spin.setRange(0, cap)
            entry = self._read_doc()["entries"].get(slot_key)
            if entry:
                self._offset_x.setValue(int(entry.get("offset_x", 0)))
                self._offset_y.setValue(int(entry.get("offset_y", 0)))
                margins = entry.get("slice") or ()
                if len(margins) == 4:
                    for spin, value in zip(self._slice_spins, margins):
                        spin.setValue(int(value))
            # The entry's OWN ref wins; imported/<slot>.png is only the fallback
            # for a slot that has never been imported (a linked slot's sheet is
            # some other slot's file).
            self._sheet_ref = ((entry or {}).get("sheet")
                               or asset_import.sheet_ref(slot_key))
            if entry and self._master_applies():
                # A master-linked entry carries the sheet's INHERITED grid (D3)
                # and its own row window; both come off the entry rather than
                # the registry, which does not own either.
                self._master_grid = (int(entry["frame_w"]),
                                     int(entry["frame_h"]))
                self._row_start = int(entry.get("row_start", 0))
                self._row_count = len(entry.get("rows") or ()) or None
                self._column = int(entry.get("column", 0))
                self._column_mode = entry.get("column_mode",
                                              DEFAULT_COLUMN_MODE)
                # An entry SAVED BEFORE columns shipped has no `column_width`
                # key (in-memory default 0), which would leave the spin with a
                # 0..0 ceiling. Fall back to the registry — the sheet owns the
                # value anyway, so re-reading it is the correct answer, not a
                # guess.
                self._column_width = (int(entry.get("column_width", 0))
                                      or self._column_width_from_registry(
                                          self._sheet_ref))
            sheet = self._sheet_file(self._sheet_ref)
            if sheet.exists():
                self._load_sheet(sheet, entry)
            else:
                self._info.setText("No spritesheet imported — grey-X placeholder.")
                self._set_buttons_enabled(True, False, bool(entry))
                self._refresh_master_state()
                self._refresh_preview()
            self._refresh_tint_state(entry)
        finally:
            self._loading = False

    def import_sheet(self, png_path):
        """Copy a sheet PNG in (AT IMPORT TIME, prototype parity) and build
        the row editors. Returns (cols, rows, clean_grid), or None when no slot
        is selected. Art smaller than one frame is padded onto a transparent
        frame-sized canvas and centred (ED-40), never rejected. Off-grid sheets
        warn but import — the remainder is cropped, exactly like the prototype.

        A fresh file import RE-OWNS the slot's own imported/<slot>.png, even if
        the slot was previously linked to someone else's sheet."""
        if self.slot_key is None:
            return None
        fw, fh = self.registry.frame_size(self.slot_key)
        with Image.open(png_path) as image:
            src_w, src_h = image.size
            padded, was_padded = pad_to_frame(image, fw, fh)
            w, h = padded.size
        cols, rows = w // fw, h // fh
        destination = self._sheet_path(self.slot_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if was_padded:
            padded.save(destination)
        elif Path(png_path).resolve() != destination.resolve():
            shutil.copyfile(png_path, destination)
        self._sheet_ref = asset_import.sheet_ref(self.slot_key)
        self._reset_row_window()      # its own PNG starts at row 0 by definition
        entry = self._read_doc()["entries"].get(self.slot_key)
        self._loading = True
        try:
            self._load_sheet(destination, entry)
            self._refresh_tint_state(entry)
        finally:
            self._loading = False
        even = (w % fw == 0) and (h % fh == 0)
        if was_padded:
            note = (f"padded {src_w}×{src_h} → {w}×{h} "
                    f"(centred in the {fw}×{fh} frame)")
            # An off-grid pad still crops a remainder — keep _load_sheet's ⚠
            # rather than replacing it with the neutral padding note.
            warning = "" if even else self._info.text()
            self._info.setText(f"{warning} — {note}" if warning else note)
        self._emit_draft()
        return (cols, rows, even)

    def use_sheet(self, sheet):
        """LINK this slot to a sheet already in data/sprites/imported/ — the
        "Use Spritesheet…" path. Takes an `asset_import.ImportedSheet` or a bare
        "imported/x.png" ref. Copies NO bytes: the entry just points at that file,
        so the source slot and this one render from one PNG.

        Same shape as import_sheet — (cols, rows, clean_grid), or None when there
        is no slot or the sheet is missing. The sheet re-slices at THIS slot's
        registry frame size (a cross-size link keeps _load_sheet's off-grid ⚠, so
        it degrades visibly rather than silently), and the row settings are seeded
        from whichever entry already describes this sheet — linking the art brings
        its fps/hidden/loop/offsets with it. Nothing is written until Save."""
        if self.slot_key is None:
            return None
        ref = getattr(sheet, "ref", None) or str(sheet)
        path = self._sheet_file(ref)
        if not path.exists():
            return None
        doc = self._read_doc()
        entries = doc["entries"]
        # Prefer this slot's OWN entry when it already uses this sheet (re-picking
        # the same sheet must not throw away the tuning done on it); otherwise
        # inherit the source's rows.
        own = entries.get(self.slot_key)
        seed = own if (own or {}).get("sheet") == ref else next(
            (entry for entry in entries.values() if entry.get("sheet") == ref),
            None)
        fw, fh = self.registry.frame_size(self.slot_key)
        with Image.open(path) as image:
            w, h = image.size
        self._sheet_ref = ref
        self._reset_row_window()   # the picker only offers whole imported/ PNGs
        self._loading = True
        try:
            self._load_sheet(path, seed)
            self._offset_x.setValue(int((seed or {}).get("offset_x", 0)))
            self._offset_y.setValue(int((seed or {}).get("offset_y", 0)))
            self._refresh_tint_state(seed)
        finally:
            self._loading = False
        self._emit_draft()
        return (w // fw, h // fh, (w % fw == 0) and (h % fh == 0))

    def use_master_sheet(self, sheet, row_start=None, row_count=None):
        """LINK this slot to a MASTER spritesheet and claim a row window in it
        (M4, D2/D3) — the "Use Master Spritesheet…" path.

        Takes a `master_sheet_import.MasterSheet`, or its id / stored ref (both
        resolved through the registry). Copies NO bytes, exactly like
        `use_sheet`: the entry points at the registry entry's STORED `file`,
        verbatim — never a re-derived ``master/<id>.png`` (see
        `master_sheet_import.master_ref`'s docstring).

        The sheet OWNS the grid (D3): `frame_w`/`frame_h` are inherited into
        `_row_frame_size` (and so into the saved entry), and the Frame W/H
        spinboxes go read-only. **This deliberately bypasses
        `_on_frame_size_changed`** — that method writes a per-slot
        `slots.json` override and re-saves, and a master sheet's grid is NOT a
        per-slot override. `slots.json` must not be touched here.

        `row_start`/`row_count` default to whatever this slot's existing entry
        already claims on this sheet, else the whole sheet. Same shape as
        `use_sheet` — (cols, rows-in-window, clean_grid), or None when there is
        no slot or the sheet is missing. Nothing is written until Save."""
        if self.slot_key is None:
            return None
        sheet = self._resolve_master_sheet(sheet)
        if sheet is None or not sheet.path.exists():
            return None
        entry = self._read_doc()["entries"].get(self.slot_key)
        seed = entry if (entry or {}).get("sheet") == sheet.ref else None
        self._sheet_ref = sheet.ref
        self._master_grid = (sheet.frame_w, sheet.frame_h)
        # The sheet owns `column_width` (D1) exactly as it owns the grid (D3):
        # adopt it from the REGISTRY, and seed the column/mode the same way the
        # row window is seeded from an existing entry on this sheet.
        self._column_width = self._column_width_from_registry(sheet.ref)
        self._column = int((seed or {}).get("column", 0))
        self._column_mode = (seed or {}).get("column_mode", DEFAULT_COLUMN_MODE)
        self._row_start = (int(seed.get("row_start", 0)) if seed is not None
                           and row_start is None else int(row_start or 0))
        self._row_count = (len(seed.get("rows") or ()) or None
                           if seed is not None and row_count is None
                           else row_count)
        self._loading = True
        try:
            self._load_sheet(sheet.path, seed)
            self._offset_x.setValue(int((seed or {}).get("offset_x", 0)))
            self._offset_y.setValue(int((seed or {}).get("offset_y", 0)))
            self._refresh_tint_state(seed)
        finally:
            self._loading = False
        self._emit_draft()
        fw, fh = sheet.frame_w, sheet.frame_h
        return (sheet.width // fw, len(self._row_editors),
                (sheet.width % fw == 0) and (sheet.height % fh == 0))

    def _resolve_master_sheet(self, sheet):
        """A `MasterSheet` from the dataclass, its id, or its stored ref."""
        if hasattr(sheet, "ref"):
            return sheet
        key = str(sheet)
        for candidate in master_sheet_import.master_sheets(self._data_dir):
            if key in (candidate.sheet_id, candidate.ref):
                return candidate
        return None

    def draft_entry(self):
        """Current UI state as a manifest-v2 entry dict (None: no rows)."""
        if self.slot_key is None or not self._row_editors:
            return None
        entry = {
            "sheet": self._sheet_ref or asset_import.sheet_ref(self.slot_key),
            "frame_w": self._row_frame_size[0],
            "frame_h": self._row_frame_size[1],
            "offset_x": self._offset_x.value(),
            "offset_y": self._offset_y.value(),
            "rows": [editor.to_dict() for editor in self._row_editors],
        }
        margins = self._slice_margins()
        if margins is not None:
            entry["slice"] = margins
        # ESV-2: anchors are authored by AnchorsPanel, not this panel — carry
        # an existing entry's `anchors` value through verbatim (the same
        # shape as the `slice` branch above), or Save would silently erase
        # them (the regression this line pins, ESV-2 brief §1.7).
        existing = self._read_doc()["entries"].get(self.slot_key)
        if existing and "anchors" in existing:
            entry["anchors"] = existing["anchors"]
        # M4: the row window. Optional like `slice`/`tint_overlay` — OMITTED at
        # 0, so every non-master entry stays byte-identical. And the `anchors`
        # argument in reverse: a path that does NOT author a window (the sheet
        # is not a master sheet, so the row is not even shown) must carry an
        # existing one through rather than silently erasing it.
        if self._master_applies():
            if self._row_start:
                entry["row_start"] = self._row_start
        elif existing and existing.get("row_start"):
            entry["row_start"] = existing["row_start"]
        # The COLUMN window, under that same two-branch rule: authored while a
        # master sheet is linked (each key omitted at its default — 0 /
        # "manual" / 0, so a pre-column entry stays byte-identical), and
        # otherwise PRESERVED from `existing`, because a path that never shows
        # the column row must not erase a column somebody saved.
        if self._master_applies():
            if self._column:
                entry["column"] = self._column
            if self._column_mode != DEFAULT_COLUMN_MODE:
                entry["column_mode"] = self._column_mode
            if self._column_width:
                entry["column_width"] = self._column_width
        elif existing:
            for key in ("column", "column_mode", "column_width"):
                if existing.get(key):
                    entry[key] = existing[key]
        if self._tint_applies() and self._tint_check.isChecked():
            # Optional like `slice`: False omits the key, so an entry that
            # doesn't want the tint is byte-identical to a pre-feature one, and
            # unticking + re-saving removes it (save() replaces the whole entry).
            entry["tint_overlay"] = True
        return entry

    def _slice_margins(self):
        """[l, t, r, b] for a ui slot with at least one non-zero margin;
        None otherwise. `slice` is optional in the manifest — an unsliced
        entry must never grow the key (and re-saving with all-zero margins
        removes it, since save() replaces the whole entry)."""
        if not self._slice_applies():
            return None
        values = [spin.value() for spin in self._slice_spins]
        return values if any(values) else None

    def _slice_applies(self):
        """Nine-slice is a HUD-only feature -> the ui category only."""
        return self._context is not None and self._context[0] == "ui"

    def _tint_applies(self):
        """The tint fallback only means anything for tile-condition art."""
        return (self._context is not None
                and self._context[0] == CONDITION_CATEGORY)

    def _master_applies(self):
        """The row window is offered for MASTER sheets only (D4) — a plain
        per-slot sheet starts at row 0 by definition. Unlike `_slice_applies`/
        `_tint_applies` this tests the current SHEET REF, not the category:
        any category may cut a master sheet."""
        return bool(self._sheet_ref) and self._sheet_ref.startswith(MASTER_PREFIX)

    def _effective_frame_size(self):
        """The grid the current sheet is CUT at. A master sheet owns its grid
        and the linking slot inherits it (D3), so the registry's per-slot size
        (and any slots.json override) does not apply while one is linked."""
        if self._master_applies() and self._master_grid:
            return self._master_grid
        return self.registry.frame_size(self.slot_key)

    def _reset_row_window(self):
        """Back to "the whole sheet, from row 0 and column 0" — every
        non-master path. A column only ever means something on a master sheet
        (D2), exactly like the row window."""
        self._row_start = 0
        self._row_count = None
        self._sheet_rows = 0
        self._master_grid = None
        self._column = 0
        self._column_mode = DEFAULT_COLUMN_MODE
        self._column_width = 0
        self._sheet_cols = 0

    def _refresh_master_state(self):
        """Show/fill the row window, and lock Frame W/H while a master sheet is
        linked (D3 — the registry owns that grid, so the per-slot override the
        spins author would be a lie)."""
        master = self._master_applies()
        self._master_row.setVisible(master)
        self._column_row.setVisible(master)
        self._refresh_column_state()
        for spin in (self._frame_w, self._frame_h):
            spin.setEnabled(not master)
            spin.setToolTip(MASTER_GRID_TOOLTIP if master else "")
        if not master or self._sheet_rows < 1:
            return
        last = self._sheet_rows - 1
        count = max(1, self._row_count or 1)
        for spin in (self._row_from, self._row_to):
            spin.blockSignals(True)
        self._row_from.setRange(0, last)
        self._row_from.setValue(self._row_start)
        # `a > b` unrepresentable (ED-30): the minimum tracks the first spin.
        self._row_to.setRange(self._row_start, last)
        self._row_to.setValue(min(last, self._row_start + count - 1))
        for spin in (self._row_from, self._row_to):
            spin.blockSignals(False)
        fw, fh = self._row_frame_size
        self._frame_w.setValue(fw)
        self._frame_h.setValue(fh)

    def _refresh_column_state(self):
        """Fill the column row from state, with the spin's CEILING pinned to
        the sheet's real last master column (`sheet_cols // column_width - 1`).
        An off-sheet column is therefore UNREPRESENTABLE (ED-30) rather than a
        save-time error — the horizontal twin of `_row_to`'s minimum tracking
        `_row_from`. Nothing to fill until a master sheet with a known width is
        loaded (a pre-column entry falls back to the registry in `set_slot`)."""
        if (not self._master_applies() or self._sheet_cols < 1
                or self._column_width < 1):
            return
        width = max(1, self._column_width)
        ceiling = min(COLUMN_RANGE[1], max(0, (self._sheet_cols // width) - 1))
        # Clamp the STATE too, not just the widget: draft_entry() reads
        # `_column`, and a column past the sheet must never reach the manifest.
        self._column = min(max(0, self._column), ceiling)
        self._column_spin.blockSignals(True)
        self._column_spin.setRange(COLUMN_RANGE[0], ceiling)
        self._column_spin.setValue(self._column)
        self._column_spin.blockSignals(False)
        self._column_mode_combo.blockSignals(True)
        self._column_mode_combo.setCurrentText(COLUMN_MODE_LABELS.get(
            self._column_mode, COLUMN_MODE_LABELS[DEFAULT_COLUMN_MODE]))
        self._column_mode_combo.blockSignals(False)
        self._column_width_display.setValue(width)

    def _effective_column(self):
        """The master column the PREVIEW cuts. The STORED column always wins
        here: a non-manual `column_mode` names who overrides it at RENDER time
        (the season stepper, a building's colour), and the editor has no such
        live value — the schema's own "falls back to the stored column when the
        caller supplies none" rule."""
        return max(0, self._column) if self._master_applies() else 0

    def _column_width_from_registry(self, ref):
        """The linked sheet's `column_width` off the master registry, or 0.

        Read through `engine.assets.master_registry` rather than off a
        `MasterSheet` attribute: the registry is the one owner of this value
        (D1), and this panel has no business reaching into the import module's
        dataclass for it."""
        return master_registry.column_width_for(
            master_sheet_import.load_registry_doc(self._data_dir), ref)

    def _on_row_window_changed(self):
        """Re-cut the slot at the new window and rebuild exactly that many
        RowEditors. Unlike `_on_frame_size_changed` this writes NOTHING — the
        window is entry state, saved with Save like every other row edit."""
        if self._loading or self.slot_key is None or not self._master_applies():
            return
        start = self._row_from.value()
        end = max(start, self._row_to.value())
        if (start, end - start + 1) == (self._row_start, self._row_count):
            return
        self._row_start, self._row_count = start, end - start + 1
        sheet = self._sheet_file(self._sheet_ref)
        if not sheet.exists():
            return
        entry = self._read_doc()["entries"].get(self.slot_key)
        self._loading = True
        try:
            self._load_sheet(sheet, entry)
        finally:
            self._loading = False
        self._emit_draft()

    def _on_column_changed(self):
        """Re-cut the PREVIEW at the new column/mode. Like
        `_on_row_window_changed` — and pointedly unlike
        `_on_frame_size_changed` — this writes NOTHING: the column is entry
        state, saved by Save with every other row edit, and `slots.json` is
        never touched from here.

        It does not rebuild the RowEditors either. The row window changes WHICH
        ROWS EXIST (hence its `_load_sheet` call); the column window only
        changes which horizontal SLICE of those same rows is shown, so
        `_refresh_preview()` alone is the whole update."""
        if self._loading or self.slot_key is None or not self._master_applies():
            return
        column = self._column_spin.value()
        mode = COLUMN_MODE_VALUES.get(self._column_mode_combo.currentText(),
                                      DEFAULT_COLUMN_MODE)
        if (column, mode) == (self._column, self._column_mode):
            return
        self._column, self._column_mode = column, mode
        self._refresh_preview()
        self._emit_draft()

    def _refresh_tint_state(self, entry=None):
        """Sync the tint checkbox to whether this slot HAS art.

        No art (no row editors) ⇒ the game draws no sprite for the condition, so
        the flat colour diamond is the ONLY thing that renders it: the box is
        forced checked and disabled. The gate is the LIVE row editors, not the
        on-disk entry, so a freshly imported sheet is editable before its first
        Save. With art present the state comes from `entry` — and a fresh import
        (no entry yet) defaults to OFF, i.e. the sprite replaces the tint."""
        has_art = bool(self._row_editors)
        self._tint_check.setChecked(
            bool((entry or {}).get("tint_overlay", False)) if has_art else True)
        self._tint_check.setEnabled(has_art)

    def _header_text(self, slot_key, fw, fh):
        """The header line: the slot's display name (when it has one) before
        the key and its slicing size. One formatter, so the three call sites
        that re-render the header after a write cannot drift apart."""
        name = self.registry.display_name(slot_key)
        prefix = f"{name}  " if name else ""
        return f"{prefix}[{slot_key}]  {fw}×{fh}/frame"

    def _on_display_name_changed(self):
        """Commit this slot's display name to slots.json.

        One file, unlike `_on_frame_size_changed`: the name is editor metadata,
        so no manifest entry has to be re-cut and nothing on disk can disagree
        with it. Every panel that caches a registry still has to re-read one
        (`registry_changed` -> the shell's `_reload_registries`), because the
        UI screen editor's skin combos are built from it."""
        if self._loading or self.slot_key is None:
            return
        name = self._name_edit.text().strip()
        if name == self.registry.display_name(self.slot_key):
            return                                   # nothing to do
        registry_ops.set_slot_display_name(self._data_dir, self.slot_key, name)
        self._name_edit.setText(name)                # normalise the whitespace
        fw, fh = self.registry.frame_size(self.slot_key)
        self._header.setText(self._header_text(self.slot_key, fw, fh))
        self.registry_changed.emit(self.slot_key)    # shell reloads every registry
        self.reload_registry()

    def _on_frame_size_changed(self):
        """Commit a per-slot frame-size override, and RE-SLICE against it.

        The two-file part is not optional. `AssetStore.frame_size` resolves
        manifest entry > registry, so a slot that already has an entry carries its
        own frame_w/frame_h and would keep rendering at the OLD size no matter what
        slots.json says. So: write the registry override, reload every cached
        registry, then re-cut the sheet at the new size and persist the refreshed
        entry. Leaving the two disagreeing on disk is the failure mode this method
        exists to prevent.

        Row count follows the new slicing (a taller frame yields fewer rows);
        `_load_sheet` already warns on an unclean grid.
        """
        if self._loading or self.slot_key is None:
            return
        fw, fh = self._frame_w.value(), self._frame_h.value()
        if (fw, fh) == self.registry.frame_size(self.slot_key):
            return                                   # nothing to do
        registry_ops.set_slot_frame_size(self._data_dir, self.slot_key, fw, fh)
        self.registry_changed.emit(self.slot_key)    # shell reloads every registry
        self.reload_registry()

        self._header.setText(self._header_text(self.slot_key, fw, fh))
        entry = self._read_doc()["entries"].get(self.slot_key)
        sheet = self._sheet_file(self._sheet_ref) if self._sheet_ref else None
        if entry is None or sheet is None or not sheet.exists():
            self._emit_draft()
            return
        self._loading = True
        try:
            self._load_sheet(sheet, entry)           # re-cut at the new frame size
        finally:
            self._loading = False
        self.save()                                  # entry + registry agree again

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
        """Clear-to-placeholder: remove the manifest entry, then delete the PNGs
        it leaves UNREFERENCED (after a confirm in the UI path).

        The PNG is only unlinked when no remaining entry points at it — a sheet
        shared with other slots survives clearing any one of them, and is
        collected when the last user goes. Both candidates are checked: the sheet
        this entry actually used (which may be another slot's file) and the slot's
        own imported/<slot>.png (art imported but never saved has no entry to read
        a ref from)."""
        if self.slot_key is None:
            return
        slot_key = self.slot_key
        doc = self._read_doc()
        entry = doc["entries"].get(slot_key)
        ref = (entry or {}).get("sheet") or asset_import.sheet_ref(slot_key)
        others = [slot for slot in asset_import.sheet_users(doc, ref)
                  if slot != slot_key]
        if confirm:
            shared = (
                f"\n\n{len(others)} other slot(s) use this spritesheet "
                f"({', '.join(others)}) — the PNG is kept for them."
                if others else
                "\n\nThis deletes the imported PNG and its manifest entry; the "
                "slot reverts to the grey-X placeholder.")
            answer = QMessageBox.question(
                self, "Clear spritesheet",
                f"Remove the imported spritesheet for '{slot_key}'?" + shared)
            if answer != QMessageBox.StandardButton.Yes:
                return
        if slot_key in doc["entries"]:
            del doc["entries"][slot_key]
            self._write_doc(doc)
        for orphan in asset_import.unreferenced_sheets(
                doc, [ref, asset_import.sheet_ref(slot_key)]):
            # A MASTER sheet is never collected, even at zero users: it is
            # committed library content with its own registry entry, and
            # "orphans are legal — that is how you get the art back"
            # (master_sheet_import's module docstring, §9). Unlinking it would
            # also strand the registry entry pointing at a vanished PNG. The
            # refcount above still protects a master sheet with users, which is
            # what M4 §3.6 asks for; this line extends it to zero users.
            if orphan.startswith(MASTER_PREFIX):
                continue
            self._sheet_file(orphan).unlink(missing_ok=True)
        self._sheet_ref = asset_import.sheet_ref(slot_key)
        self._reset_row_window()
        self._loading = True
        try:
            self._clear_rows()
            self._offset_x.setValue(0)
            self._offset_y.setValue(0)
            for spin in self._slice_spins:
                spin.setValue(0)
            self._refresh_tint_state()   # no art again ⇒ tint forced back on
        finally:
            self._loading = False
        self._info.setText("Cleared — slot reverts to the grey-X placeholder.")
        self._set_buttons_enabled(True, False, False)
        self._refresh_master_state()
        self._refresh_preview()
        self.entry_cleared.emit(slot_key)

    # -- internals -----------------------------------------------------------

    def _sheet_path(self, slot_key):
        """Where a slot's OWN art lives — the fresh-import destination and the
        no-entry fallback. NOT "the slot's sheet": read `_sheet_ref` for that."""
        return self._sheet_file(asset_import.sheet_ref(slot_key))

    def _sheet_file(self, ref):
        """Resolve an "imported/x.png" manifest ref to a real path — the same
        sprites_dir-relative resolution the engine's AssetStore does."""
        return self._data_dir / "sprites" / ref

    def _read_doc(self):
        return asset_import.load_manifest_doc(self._data_dir)

    def _write_doc(self, doc):
        asset_import.write_manifest_doc(self._data_dir, doc)

    def _load_sheet(self, sheet_path, entry):
        fw, fh = self._effective_frame_size()
        self._row_frame_size = (fw, fh)
        self._header.setText(self._header_text(self.slot_key, fw, fh))
        with Image.open(sheet_path) as image:
            w, h = image.size
        cols, sheet_rows = w // fw, h // fh
        self._sheet_rows = sheet_rows
        self._sheet_cols = cols     # the column spin's ceiling is derived here
        if cols < 1 or sheet_rows < 1:
            self._info.setText(f"⚠ sheet too small for one {fw}×{fh} frame.")
            self._set_buttons_enabled(True, False, bool(entry))
            self._refresh_master_state()
            return
        # ONE RowEditor per row IN THE WINDOW (the whole sheet unless a master
        # sheet narrowed it). Row 0 of the WINDOW stays idle-locked, so E-35
        # remains unrepresentable in the UI rather than a save-time error.
        start = min(self._row_start if self._master_applies() else 0,
                    sheet_rows - 1)
        available = sheet_rows - start
        count = (available if self._row_count is None
                 else max(1, min(self._row_count, available)))
        self._row_start, self._row_count, rows = start, count, count
        # A ROW IS AS WIDE AS ITS MASTER COLUMN, NOT AS THE WHOLE SHEET.
        # `cols` is the sheet's full frame-column count and stays that way —
        # `_sheet_cols` above derives the column spin's ceiling from it. But a
        # column-sliced entry only owns `column_width` of those columns (D1),
        # so the RowEditors (and the `frames` count they save) must stop at the
        # column boundary. Deriving them from `cols` instead is what wrote a
        # 68-frame idle row against a 17-frame-wide column: the animation
        # walked straight out of its colour into the next one and, past the
        # last column, off the sheet into the grey X.
        row_cols = (min(self._column_width, cols)
                    if self._master_applies() and self._column_width > 0
                    else cols)
        if (w % fw) or (h % fh):
            self._info.setText(
                f"⚠ not a clean {fw}×{fh} grid — remainder cropped "
                f"({cols} cols × {rows} rows).")
        elif row_cols != cols:
            self._info.setText(
                f"{cols} cols × {rows} rows  ({fw}×{fh}/frame) — "
                f"{row_cols}/column")
        else:
            self._info.setText(f"{cols} cols × {rows} rows  ({fw}×{fh}/frame)")
        self._clear_rows()
        vocabulary = self.registry.animations(self.slot_key)
        saved_rows = (entry or {}).get("rows", [])
        for r in range(rows):
            editor = RowEditor(r, row_cols, vocabulary)
            if r < len(saved_rows):
                editor.set_from(saved_rows[r])
            elif r > 0:
                index = editor.anim_combo.findText(
                    vocabulary[min(r, len(vocabulary) - 1)])
                if index >= 0:
                    editor.anim_combo.setCurrentIndex(index)
            editor.changed.connect(self._on_row_changed)
            self._rows_layout.insertWidget(self._rows_layout.count() - 1, editor)
            self._row_editors.append(editor)
        self._set_buttons_enabled(True, True, True)
        self._refresh_master_state()
        self._refresh_preview()

    def _clear_rows(self):
        for editor in self._row_editors:
            self._rows_layout.removeWidget(editor)
            editor.deleteLater()
        self._row_editors = []

    def _set_buttons_enabled(self, import_ok, save_ok, clear_ok):
        self._import_btn.setEnabled(import_ok)
        # "Use" and "Use Master" are available exactly when "Import" is — all
        # three just need a slot.
        self._use_btn.setEnabled(import_ok)
        self._master_btn.setEnabled(import_ok)
        self._save_btn.setEnabled(save_ok)
        self._clear_btn.setEnabled(clear_ok)

    # -- sheet preview --------------------------------------------------------

    def _refresh_preview(self):
        """Repaint the sheet view from the row editors. `effective_hidden` is the
        SAME call to_dict saves, so what you see dimmed is what gets written."""
        if self.slot_key is None or self._sheet_ref is None or not self._row_editors:
            self._preview.set_sheet(None, 1, 1)
            self._preview.set_rows(())
            return
        fw, fh = self._row_frame_size
        # The window narrows the PICTURE too, and it speaks entry-relative rows
        # on the way back out — so `_on_frame_clicked` needs no offset.
        # ...and the COLUMN narrows it horizontally, on the same terms. This is
        # the ONE place the column window reaches the preview, mirroring the
        # row window. Off a master sheet the two arguments are the widget's own
        # defaults, so the call is byte-identical to the row-only shape — which
        # is what RESETS a column window left over from a previous slot.
        master_column = self._master_applies() and self._column_width > 0
        self._preview.set_sheet(self._sheet_file(self._sheet_ref), fw, fh,
                                row_start=self._row_start,
                                row_count=len(self._row_editors),
                                col_start=(self._effective_column()
                                           * self._column_width
                                           if master_column else 0),
                                col_count=(self._column_width
                                           if master_column else None))
        self._preview.set_rows([
            {"hidden": editor.effective_hidden(),
             "static_frame": editor.static_frame()}
            for editor in self._row_editors
        ])

    def _on_row_changed(self):
        self._refresh_preview()
        self._emit_draft()

    def _on_frame_clicked(self, row, col):
        """A click on the sheet lands on that frame's RowEditor: in static mode it
        PICKS the frame, otherwise it toggles hidden. Both go through the row's own
        widgets, so the checkboxes below never fall out of sync with the picture."""
        if not (0 <= row < len(self._row_editors)):
            return
        editor = self._row_editors[row]
        if editor.is_static():
            editor.set_static_frame(col)
        else:
            editor.toggle_hidden(col)

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

    def _on_use_clicked(self):
        if self.slot_key is None:
            return
        fw, fh = self.registry.frame_size(self.slot_key)
        dialog = SheetPickerDialog(self._data_dir, self.slot_key, fw, fh,
                                   parent=self)
        if self._sheet_ref:
            dialog.select_sheet(self._sheet_ref)     # open on the current sheet
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sheet = dialog.chosen()
            if sheet is not None:
                self.use_sheet(sheet)

    def _on_master_clicked(self):
        """Open the master-sheet library. Construction is split from display
        (the sheet-picker rule), so tests drive `use_master_sheet` directly and
        never exec() a modal."""
        if self.slot_key is None:
            return
        dialog = MasterSheetDialog(self._data_dir, parent=self)
        if self._master_applies():
            # Open on the sheet this slot already cuts — matched on the STORED
            # ref, never on an id re-derived from it.
            for sheet in dialog.visible_sheets():
                if sheet.ref == self._sheet_ref:
                    dialog.select_sheet(sheet.sheet_id)
                    break
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sheet = dialog.chosen_sheet()
            if sheet is not None:
                self.use_master_sheet(sheet)
