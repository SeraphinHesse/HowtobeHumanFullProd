"""SheetPickerDialog — "Use Spritesheet…": adopt art already in the game.

Lists every PNG in data/sprites/imported/ (the pure `asset_import.imported_sheets`
model), previews the highlighted one, and returns its `sheet` ref. The caller
points the target slot's manifest entry at that ref — NO bytes are copied, so one
PNG can back many slots. Deleting shared art is the caller's problem to get right
(`asset_import.unreferenced_sheets`).

Filtered by default to sheets that divide cleanly into the TARGET slot's frame
size, because a 64x32 tile sheet offered for a 64x96 building slot is noise, not a
choice. "Show all sizes" escapes the filter: the sheet still imports, it just
re-slices at the target's frame size (with the usual off-grid warning).

Follows the NewMapDialog template (fields + QDialogButtonBox, opened with exec()).
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from editor.asset_import import imported_sheets
from editor.panels.sheet_preview import SheetPreview


class SheetPickerDialog(QDialog):
    """Pick an already-imported sheet for `slot_key`. `chosen()` is the selected
    `ImportedSheet` (None when cancelled)."""

    def __init__(self, data_dir, slot_key, frame_w, frame_h, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Use an imported spritesheet — [{slot_key}]")
        self.resize(720, 520)
        self._slot_key = slot_key
        self._frame_w = frame_w
        self._frame_h = frame_h
        self._sheets = imported_sheets(data_dir)

        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter by name…")
        self._filter.textChanged.connect(self._refill)
        self._all_sizes = QCheckBox(
            f"Show sheets that don't fit the {frame_w}×{frame_h} frame", self)
        self._all_sizes.toggled.connect(self._refill)

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
        layout.addWidget(self._filter)
        layout.addWidget(self._all_sizes)
        layout.addLayout(columns, 1)
        layout.addWidget(self._buttons)

        self._refill()

    # -- model ---------------------------------------------------------------

    def visible_sheets(self):
        """The sheets the current filter + size checkbox let through."""
        needle = self._filter.text().strip().lower()
        show_all = self._all_sizes.isChecked()
        return [
            sheet for sheet in self._sheets
            if (show_all or sheet.fits(self._frame_w, self._frame_h))
            and (not needle or needle in sheet.name.lower())
        ]

    def chosen(self):
        item = self._list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def select_sheet(self, ref):
        """Highlight a sheet by its ref (the test path, and how the dialog opens
        on the slot's current sheet). No-op when it isn't in the visible list."""
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.data(Qt.ItemDataRole.UserRole).ref == ref:
                self._list.setCurrentRow(i)
                return True
        return False

    # -- internals -----------------------------------------------------------

    def _refill(self):
        previous = self.chosen()
        self._list.blockSignals(True)
        self._list.clear()
        for sheet in self.visible_sheets():
            cols, rows = sheet.grid(self._frame_w, self._frame_h)
            label = f"{sheet.name}   {sheet.width}×{sheet.height}"
            if cols and rows:
                label += f"  ({cols}×{rows} frames)"
            if not sheet.users:
                label += "   — unused"
            elif sheet.users != (self._slot_key,):
                label += f"   — used by {len(sheet.users)}"
            item = QListWidgetItem(label, self._list)
            item.setData(Qt.ItemDataRole.UserRole, sheet)
        self._list.blockSignals(False)
        if not (previous is not None and self.select_sheet(previous.ref)):
            self._list.setCurrentRow(0 if self._list.count() else -1)
        self._on_current_changed(self._list.currentItem(), None)

    def _on_current_changed(self, item, _previous):
        sheet = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        self._buttons.button(
            QDialogButtonBox.StandardButton.Ok).setEnabled(sheet is not None)
        if sheet is None:
            self._preview.set_sheet(None, self._frame_w, self._frame_h)
            self._detail.setText("No imported sheet matches this filter.")
            return
        self._preview.set_sheet(sheet.path, self._frame_w, self._frame_h)
        self._detail.setText(self._describe(sheet))

    def _describe(self, sheet):
        cols, rows = sheet.grid(self._frame_w, self._frame_h)
        lines = [f"<b>{sheet.ref}</b>",
                 f"{sheet.width}×{sheet.height} px — "
                 f"{cols}×{rows} frames at {self._frame_w}×{self._frame_h}"]
        if not sheet.fits(self._frame_w, self._frame_h):
            lines.append("⚠ does not divide cleanly into this slot's frame "
                         "size — the remainder is cropped.")
        others = [slot for slot in sheet.users if slot != self._slot_key]
        if others:
            lines.append("Shared with: " + ", ".join(others)
                         + "<br>Linking does not copy the PNG — these slots keep "
                           "using the same file.")
        else:
            lines.append("Not used by any other slot.")
        return "<br>".join(lines)

    def _try_accept(self):
        if self.chosen() is not None:
            self.accept()
