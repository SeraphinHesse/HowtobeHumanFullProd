"""MasterSheetDialog — "Master spritesheets…": import one big multi-character
PNG, or pick one already in the library (GpuAndMasterSheetsPLAN M3, D1/D3).

Two branches in one dialog, because they are one question ("which master sheet
should this slot cut from?") with two answers:

* **Import new master spritesheet…** — choose a PNG, then give it a display
  name and the frame size, all collected BEFORE anything is written. The frame
  size cannot be deferred to a later screen: D3 makes the registry the OWNER of
  the grid, and a linking slot inherits it. Spin ranges come from
  ``master_sheets.schema.json``'s own ``minimum``/``maximum`` via
  ``master_sheet_import.frame_bounds`` (ED-30 — out-of-range input is
  unrepresentable, and the numbers are never retyped).
* **Use existing…** — the whole registry, each row labelled with its real pixel
  size, its grid AT ITS OWN declared frame size, and its user count, filtered by
  name and previewed read-only.

``chosen()`` is the selected sheet id (the one just imported, after an import),
or ``None``. M3 stops there: nothing constructs this dialog yet — DetailsPanel
grows the button in M4 and VfxPreviewPanel in M5 (D5). The TESTS are what
construct it, which is why CONSTRUCTION IS SPLIT FROM DISPLAY: ``__init__``
builds and fills everything, and the model is reachable through
``visible_sheets`` / ``chosen`` / ``select_sheet`` / ``perform_import``, so no
test ever has to ``exec()`` a modal. Structurally copied from
``editor/panels/sheet_picker.py``.

The dialog NEVER writes data itself — ``master_sheet_import`` owns the one
write path (ED-31). QFileDialog is confined to ``_on_browse_clicked``;
``set_import_source()`` is the same seam without the modal.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
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
)

from editor import master_sheet_import
from editor.panels.balancing import _NoWheelSpinBox
from editor.panels.sheet_preview import SheetPreview

DEFAULT_FRAME = 64


class MasterSheetDialog(QDialog):
    """Pick or import a master spritesheet. ``chosen()`` is the sheet id."""

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Master spritesheets")
        self.resize(760, 560)
        self._data_dir = data_dir
        self._sheets = master_sheet_import.master_sheets(data_dir)
        self._png_path = None

        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter by name…")
        self._filter.textChanged.connect(self._refill)

        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_current_changed)
        self._list.itemDoubleClicked.connect(lambda _item: self._try_accept())

        self._preview = SheetPreview(interactive=False, parent=self)
        self._detail = QLabel("", self)
        self._detail.setWordWrap(True)

        right = QVBoxLayout()
        right.addWidget(self._preview)
        right.addWidget(self._detail)
        right.addStretch(1)

        columns = QHBoxLayout()
        columns.addWidget(self._list, 1)
        columns.addLayout(right, 1)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=self)
        self._buttons.accepted.connect(self._try_accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Use existing master spritesheet:", self))
        layout.addWidget(self._filter)
        layout.addLayout(columns, 1)
        layout.addWidget(self._build_import_box())
        layout.addWidget(self._buttons)

        self._refill()

    def _build_import_box(self):
        box = QGroupBox("Import new master spritesheet…", self)
        low, high = master_sheet_import.frame_bounds(self._data_dir)

        self._browse = QPushButton("Choose PNG…", box)
        self._browse.clicked.connect(self._on_browse_clicked)
        self._source_label = QLabel("No file chosen.", box)
        self._source_label.setWordWrap(True)

        self._name = QLineEdit(box)
        self._name.setPlaceholderText("Display name shown in this list")
        self._name.setMaxLength(80)
        self._name.textChanged.connect(self._sync_import_enabled)

        self._frame_w = _NoWheelSpinBox()
        self._frame_h = _NoWheelSpinBox()
        for spin in (self._frame_w, self._frame_h):
            spin.setParent(box)
            spin.setRange(low, high)
            spin.setValue(min(max(DEFAULT_FRAME, low), high))

        self._import = QPushButton("Import", box)
        self._import.clicked.connect(self._on_import_clicked)

        chooser = QHBoxLayout()
        chooser.addWidget(self._browse)
        chooser.addWidget(self._source_label, 1)

        form = QFormLayout(box)
        form.addRow(chooser)
        form.addRow("Display name", self._name)
        form.addRow("Frame width", self._frame_w)
        form.addRow("Frame height", self._frame_h)
        form.addRow(self._import)
        self._sync_import_enabled()
        return box

    # -- model ---------------------------------------------------------------

    def visible_sheets(self):
        """The registered sheets the current filter lets through — in
        ``master_sheets()`` order (display name, case-insensitive)."""
        needle = self._filter.text().strip().lower()
        return [sheet for sheet in self._sheets
                if not needle
                or needle in sheet.display_name.lower()
                or needle in sheet.sheet_id.lower()]

    def chosen(self):
        """The selected sheet's id, or None when nothing is selected."""
        sheet = self.chosen_sheet()
        return None if sheet is None else sheet.sheet_id

    def chosen_sheet(self):
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def select_sheet(self, sheet_id):
        """Highlight a sheet by id (the test path, and how the dialog lands on
        a sheet it just imported). False when it isn't in the visible list."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole).sheet_id == sheet_id:
                self._list.setCurrentRow(i)
                return True
        return False

    def import_source(self):
        """The PNG queued for import, or None."""
        return self._png_path

    def set_import_source(self, png_path):
        """Queue a PNG for import and seed the display name from its stem.
        The non-modal half of ``_on_browse_clicked`` — the test path."""
        self._png_path = None if png_path is None else Path(png_path)
        self._source_label.setText(
            "No file chosen." if self._png_path is None
            else str(self._png_path))
        if self._png_path is not None and not self._name.text().strip():
            self._name.setText(self._png_path.stem)
        self._sync_import_enabled()

    def perform_import(self):
        """Import the queued PNG with the form's name + frame size, refresh the
        list and select the result. Returns the sheet id, or None when there is
        nothing queued. Re-importing the same bytes reuses the id and leaves the
        PNG untouched (``master_sheet_import.import_master_sheet``)."""
        if self._png_path is None:
            return None
        sheet_id = master_sheet_import.import_master_sheet(
            self._data_dir, self._png_path, self._name.text(),
            self._frame_w.value(), self._frame_h.value())
        self._sheets = master_sheet_import.master_sheets(self._data_dir)
        self._filter.clear()        # a filter that hides the new sheet is noise
        self._refill()
        self.select_sheet(sheet_id)
        return sheet_id

    # -- internals -----------------------------------------------------------

    def _sync_import_enabled(self):
        self._import.setEnabled(self._png_path is not None)

    def _on_browse_clicked(self):
        path, _filter = QFileDialog.getOpenFileName(
            self, "Import master spritesheet", "", "Images (*.png)")
        if path:
            self.set_import_source(path)

    def _on_import_clicked(self):
        try:
            self.perform_import()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import master spritesheet", str(exc))

    def _refill(self):
        previous = self.chosen()
        self._list.blockSignals(True)
        self._list.clear()
        for sheet in self.visible_sheets():
            item = QListWidgetItem(self._label(sheet), self._list)
            item.setData(Qt.ItemDataRole.UserRole, sheet)
        self._list.blockSignals(False)
        if not (previous is not None and self.select_sheet(previous)):
            self._list.setCurrentRow(0 if self._list.count() else -1)
        self._on_current_changed(self._list.currentItem(), None)

    def _label(self, sheet):
        cols, rows = sheet.grid()
        label = (f"{sheet.display_name}   {sheet.width}×{sheet.height}"
                 f"  ({cols}×{rows} frames)")
        # An orphan is normal, not an error (§9): it is listed, just marked.
        return label + ("   — unused" if not sheet.users
                        else f"   — used by {len(sheet.users)}")

    def _on_current_changed(self, item, _previous):
        sheet = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(sheet is not None)
        if sheet is None:
            self._preview.set_sheet(None, 1, 1)
            self._detail.setText("No master spritesheet matches this filter.")
            return
        self._preview.set_sheet(sheet.path, sheet.frame_w, sheet.frame_h)
        self._detail.setText(self._describe(sheet))

    def _describe(self, sheet):
        cols, rows = sheet.grid()
        lines = [f"<b>{sheet.ref}</b>",
                 f"{sheet.width}×{sheet.height} px — {cols}×{rows} frames at "
                 f"{sheet.frame_w}×{sheet.frame_h}"]
        if sheet.users:
            lines.append("Used by: " + ", ".join(sheet.users)
                         + "<br>Linking does not copy the PNG — these slots "
                           "keep cutting the same file.")
        else:
            lines.append("Not used by any slot yet.")
        return "<br>".join(lines)

    def _try_accept(self):
        if self.chosen() is not None:
            self.accept()
