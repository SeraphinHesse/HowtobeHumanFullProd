"""MasterSheetsPanel (MasterSheetColumnsPLAN E5) — the right-pane page shown
while the top-level "Master Sheets" selector item is selected: one place that
lists every REGISTERED master sheet, shows its slicing values and its users,
and can re-import it.

D9 — MASTER SHEETS IS A TOP-LEVEL SELECTOR ITEM, not a leaf hung off a registry
category the way Timeline (``buildings``) or Theme/Strings (``ui``) are. A
master sheet is not a ``data/slots.json`` slot and there is no "master_sheets"
balancing domain, so the selector emits ``master_sheets_selected`` alone —
never ``domain_selected`` (nothing to gate it on) and never ``node_selected``
(the entity-preview machinery must not react to a selection that names no
slot). Selection-driven like every other panel (ED-3): no parallel state store,
``reload_sheets()`` re-reads from disk on entry.

THE LISTING IS REGISTRY-DRIVEN, never a folder glob:
``master_sheet_import.master_sheets(data_dir)`` is consumed unmodified — it
sorts by display name, skips an entry whose PNG vanished (E-37), and already
carries ``users``. **THE REFCOUNT HAS EXACTLY ONE HOME**
(``asset_import.sheet_users``, reached through ``MasterSheet.users``); this
panel never computes a second one.

D10 — AN IN-USE SHEET'S SLICING IS LOCKED IN THE FORM. With one or more linking
slots the frame_w/frame_h/column_width/colours editors are DISABLED and a label
names the slots to Clear first. That is a convenience, not the enforcement: the
enforcement is ``GridInUseError`` inside ``import_master_sheet``, which is why
Re-import stays attemptable at all times and answers a grid change on a linked
sheet with a message naming the slots, before touching the PNG or the registry.

WRITES GO THROUGH ``master_sheet_import`` ONLY (ED-31) — ``write_registry_doc``
for a slicing edit, ``import_master_sheet`` for a re-import. This module never
calls ``data_io.write_validated`` and never writes a PNG itself.

RE-IMPORT KEEPS THE ID, via ``import_master_sheet(..., sheet_id=...)``.
``resolve_sheet_id``'s never-overwrite rule is right for the picker's anonymous
"import a PNG" flow and wrong for this panel's promise: swapping in genuinely
different art under the same display name would mint ``<slug>_2`` and leave
every manifest entry pointed at the stale sheet. Passing the SELECTED sheet's
id verbatim is the deliberate "replace THIS sheet's art" path — see that
parameter's docstring for why it is safe.

CONSTRUCTION IS SPLIT FROM DISPLAY (the ``sheet_picker``/``master_sheet_dialog``
rule): the model is reachable through ``sheets``/``selected_sheet``/
``select_sheet``/``reload_sheets``/``save_selected``/``reimport_selected``, so
no test ever ``exec()``s a modal. ``QFileDialog`` is confined to
``_on_reimport_browse_clicked``; ``set_reimport_source()`` is the same seam
without the modal.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import master_sheet_import
from editor.panels.balancing import _NoWheelSpinBox
from editor.panels.sheet_preview import SheetPreview


class MasterSheetsPanel(QWidget):
    """The Master Sheets right-pane page. ``selected_sheet()`` is the model."""

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = data_dir
        self._sheets = []
        self._reimport_png = None

        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_current_changed)

        self._preview = SheetPreview(interactive=False, parent=self)
        self._detail = QLabel("", self)
        self._detail.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(self._preview)
        right.addWidget(self._detail)
        right.addWidget(self._build_slicing_box())
        right.addWidget(self._build_reimport_box())
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.addWidget(self._list, 1)
        columns.addLayout(right, 1)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Registered master spritesheets:", self))
        layout.addLayout(columns, 1)

        self.reload_sheets()

    # -- construction --------------------------------------------------------

    def _build_slicing_box(self):
        """The direct-edit form: the registry's own slicing values, editable
        only while nothing links to the sheet (D10)."""
        box = QGroupBox("Slicing", self)
        low, high = master_sheet_import.frame_bounds(self._data_dir)
        cw_low, cw_high = master_sheet_import.column_width_bounds(self._data_dir)

        self._frame_w = _NoWheelSpinBox(box)
        self._frame_h = _NoWheelSpinBox(box)
        for spin in (self._frame_w, self._frame_h):
            spin.setRange(low, high)
        self._column_width = _NoWheelSpinBox(box)
        self._column_width.setRange(cw_low, cw_high)
        self._colours = QLineEdit(box)
        self._colours.setPlaceholderText(
            "Comma-separated colour/season names (optional)")

        self._save = QPushButton("Save slicing", box)
        self._save.clicked.connect(self._on_save_clicked)

        self._lock_label = QLabel("", box)
        self._lock_label.setWordWrap(True)

        form = QFormLayout(box)
        form.addRow("Frame width", self._frame_w)
        form.addRow("Frame height", self._frame_h)
        form.addRow("Column width", self._column_width)
        form.addRow("Colours", self._colours)
        form.addRow(self._save)
        form.addRow(self._lock_label)
        return box

    def _build_reimport_box(self):
        """Replace the selected sheet's PNG, keeping its id and every link.
        Stays enabled even while slots link — ``GridInUseError`` decides, not a
        UI lock, so the designer gets the message naming the slots."""
        box = QGroupBox("Re-import this sheet's art", self)
        low, high = master_sheet_import.frame_bounds(self._data_dir)
        cw_low, cw_high = master_sheet_import.column_width_bounds(self._data_dir)

        self._reimport_browse = QPushButton("Choose PNG…", box)
        self._reimport_browse.clicked.connect(self._on_reimport_browse_clicked)
        self._reimport_source = QLabel("No file chosen.", box)
        self._reimport_source.setWordWrap(True)

        self._reimport_frame_w = _NoWheelSpinBox(box)
        self._reimport_frame_h = _NoWheelSpinBox(box)
        for spin in (self._reimport_frame_w, self._reimport_frame_h):
            spin.setRange(low, high)
        self._reimport_column_width = _NoWheelSpinBox(box)
        self._reimport_column_width.setRange(cw_low, cw_high)
        self._reimport_colours = QLineEdit(box)
        self._reimport_colours.setPlaceholderText(
            "Comma-separated colour/season names (optional)")

        self._reimport = QPushButton("Re-import", box)
        self._reimport.clicked.connect(self._on_reimport_clicked)

        chooser = QHBoxLayout()
        chooser.addWidget(self._reimport_browse)
        chooser.addWidget(self._reimport_source, 1)

        form = QFormLayout(box)
        form.addRow(chooser)
        form.addRow("Frame width", self._reimport_frame_w)
        form.addRow("Frame height", self._reimport_frame_h)
        form.addRow("Column width", self._reimport_column_width)
        form.addRow("Colours", self._reimport_colours)
        form.addRow(self._reimport)
        return box

    # -- model ---------------------------------------------------------------

    def sheets(self):
        """Every registered master sheet, in ``master_sheets()`` order."""
        return tuple(self._sheets)

    def selected_sheet(self):
        """The selected ``MasterSheet``, or None when the registry is empty."""
        item = self._list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def select_sheet(self, sheet_id):
        """Highlight a sheet by id. False when it is not listed."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole).sheet_id == sheet_id:
                self._list.setCurrentRow(i)
                return True
        return False

    def detail_text(self):
        """What the detail label currently reports (the test seam)."""
        return self._detail.text()

    def reload_sheets(self):
        """Re-read the registry and refill the list, keeping the selection when
        that sheet still exists (the reload-on-entry convention every other
        selection-driven panel follows)."""
        previous = self.selected_sheet()
        previous_id = None if previous is None else previous.sheet_id
        self._sheets = master_sheet_import.master_sheets(self._data_dir)
        self._list.blockSignals(True)
        self._list.clear()
        for sheet in self._sheets:
            item = QListWidgetItem(self._label(sheet), self._list)
            item.setData(Qt.ItemDataRole.UserRole, sheet)
        self._list.blockSignals(False)
        if not (previous_id is not None and self.select_sheet(previous_id)):
            self._list.setCurrentRow(0 if self._list.count() else -1)
        self._on_current_changed(self._list.currentItem(), None)

    def save_selected(self):
        """Write the slicing form back to the selected sheet's registry entry.
        No PNG is touched. Returns the sheet id, or None when there is nothing
        to write.

        Refuses (returns None) while the sheet has users — defense in depth
        behind the disabled controls, the same D10 rule ``GridInUseError``
        enforces on the re-import path."""
        sheet = self.selected_sheet()
        if sheet is None or sheet.users:
            return None
        columns = master_sheet_import.parse_columns(
            self._colours.text(), self._data_dir)
        doc = master_sheet_import.load_registry_doc(self._data_dir)
        entry = (doc.get("entries") or {}).get(sheet.sheet_id)
        if not isinstance(entry, dict):
            return None
        entry["frame_w"] = self._frame_w.value()
        entry["frame_h"] = self._frame_h.value()
        entry["column_width"] = self._column_width.value()
        # Omit-at-default (the `slice`/`tint_overlay`/`row_start` convention):
        # an unnamed sheet carries no `columns` key at all, which the schema's
        # `minItems: 1` requires anyway.
        if columns:
            entry["columns"] = list(columns)
        else:
            entry.pop("columns", None)
        master_sheet_import.write_registry_doc(self._data_dir, doc)
        self.reload_sheets()
        return sheet.sheet_id

    def reimport_selected(self, png_path, frame_w=None, frame_h=None,
                          column_width=None, columns=None):
        """Replace the selected sheet's PNG, KEEPING ITS ID AND EVERY LINK.
        Omitted slicing arguments default to the sheet's stored values (what
        the seeded form means). Returns the sheet id, or None when nothing is
        selected.

        Goes through ``import_master_sheet(..., sheet_id=sheet.sheet_id)`` —
        the one write path (ED-31) — so D10's ``GridInUseError`` guard runs
        unchanged: a grid change while slots link raises before the PNG copy
        and before the registry write, naming the slots to Clear."""
        sheet = self.selected_sheet()
        if sheet is None:
            return None
        sheet_id = master_sheet_import.import_master_sheet(
            self._data_dir, png_path, sheet.display_name,
            sheet.frame_w if frame_w is None else frame_w,
            sheet.frame_h if frame_h is None else frame_h,
            sheet.column_width if column_width is None else column_width,
            columns=sheet.columns if columns is None else columns,
            sheet_id=sheet.sheet_id)
        self.reload_sheets()
        self.select_sheet(sheet_id)
        return sheet_id

    def reimport_source(self):
        """The PNG queued for re-import, or None."""
        return self._reimport_png

    def set_reimport_source(self, png_path):
        """Queue a PNG for re-import — the non-modal half of
        ``_on_reimport_browse_clicked`` (the test path)."""
        self._reimport_png = None if png_path is None else Path(png_path)
        self._reimport_source.setText(
            "No file chosen." if self._reimport_png is None
            else str(self._reimport_png))
        self._reimport.setEnabled(self._reimport_png is not None)

    # -- internals -----------------------------------------------------------

    def _label(self, sheet):
        cols, rows = sheet.grid()
        label = (f"{sheet.display_name}   {sheet.width}×{sheet.height}"
                 f"  ({cols}×{rows} frames)")
        # An orphan is normal, not an error (§9): it is listed, just marked.
        return label + ("   — unused" if not sheet.users
                        else f"   — used by {len(sheet.users)}")

    def _describe(self, sheet):
        cols, rows = sheet.grid()
        lines = [
            f"<b>{sheet.display_name}</b> ({sheet.sheet_id})",
            f"{sheet.ref} — {sheet.width}×{sheet.height} px",
            f"{cols}×{rows} frames at {sheet.frame_w}×{sheet.frame_h}",
            f"Column width {sheet.column_width} frame(s) — "
            f"{sheet.column_count()} column(s)",
            "Colours: " + (", ".join(sheet.columns) if sheet.columns
                           else "unnamed"),
        ]
        if sheet.users:
            lines.append(f"Used by {len(sheet.users)} slot(s): "
                         + ", ".join(sheet.users))
        else:
            lines.append("Used by 0 slots — not used by any slot yet.")
        return "<br>".join(lines)

    def _on_current_changed(self, item, _previous):
        sheet = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if sheet is None:
            self._preview.set_sheet(None, 1, 1)
            self._detail.setText("No master spritesheet is registered yet.")
            self._lock_label.setText("")
            self._set_slicing_enabled(False)
            self._reimport.setEnabled(False)
            self._reimport_browse.setEnabled(False)
            return
        # The RAW registry entry, whole-sheet: this panel shows the sheet, not
        # one slot's row/column window (three-argument `set_sheet` resets any).
        self._preview.set_sheet(sheet.path, sheet.frame_w, sheet.frame_h)
        self._detail.setText(self._describe(sheet))
        self._seed(sheet)

    def _seed(self, sheet):
        """Fill both forms from the sheet's stored values and apply the D10
        lock to the slicing half."""
        colours = ", ".join(sheet.columns)
        for spin, value in ((self._frame_w, sheet.frame_w),
                            (self._frame_h, sheet.frame_h),
                            (self._column_width, sheet.column_width),
                            (self._reimport_frame_w, sheet.frame_w),
                            (self._reimport_frame_h, sheet.frame_h),
                            (self._reimport_column_width, sheet.column_width)):
            spin.setValue(value)
        self._colours.setText(colours)
        self._reimport_colours.setText(colours)
        self.set_reimport_source(None)
        self._reimport_browse.setEnabled(True)

        self._set_slicing_enabled(not sheet.users)
        if sheet.users:
            names = ", ".join(sheet.users)
            self._lock_label.setText(
                f"Locked: {len(sheet.users)} slot(s) cut windows out of this "
                f"sheet — {names}. Clear them first to change its slicing.")
            for widget in self._slicing_widgets():
                widget.setToolTip(f"Locked by: {names}")
        else:
            self._lock_label.setText(
                "No slot links to this sheet, so its slicing is free to edit.")
            for widget in self._slicing_widgets():
                widget.setToolTip("")

    def _slicing_widgets(self):
        return (self._frame_w, self._frame_h, self._column_width,
                self._colours, self._save)

    def _set_slicing_enabled(self, enabled):
        for widget in self._slicing_widgets():
            widget.setEnabled(enabled)

    def _on_save_clicked(self):
        try:
            self.save_selected()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Save slicing", str(exc))

    def _on_reimport_browse_clicked(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Re-import master spritesheet", "", "Images (*.png)")
        if path:
            self.set_reimport_source(path)

    def _on_reimport_clicked(self):
        if self._reimport_png is None:
            return
        try:
            self.reimport_selected(
                self._reimport_png,
                frame_w=self._reimport_frame_w.value(),
                frame_h=self._reimport_frame_h.value(),
                column_width=self._reimport_column_width.value(),
                columns=master_sheet_import.parse_columns(
                    self._reimport_colours.text(), self._data_dir))
        except (OSError, ValueError) as exc:
            # GridInUseError subclasses ValueError on purpose, for this catch.
            QMessageBox.warning(self, "Re-import master spritesheet", str(exc))
