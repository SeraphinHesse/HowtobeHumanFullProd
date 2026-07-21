"""Settings dialog (ED chrome + keybinds) — dark mode, the undo/redo key
swap, and every tool/brush keybind, all editable from one place.

Modal: Qt's WindowShortcut context means the 12 MainWindow-level shortcuts
(7 tools + 5 brushes) can't fire while this dialog is the active window, so
typing into a QKeySequenceEdit here never races a live tool switch.

Every change applies live and persists immediately (same UX as the old
toolbar dark-mode checkbox) — there is no Cancel, only Close. A change is
only emitted upward once it passes validation (single bare key, no modifier,
not already bound to another tool/brush); an invalid or colliding capture
reverts the widget to its previous value instead.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QKeySequenceEdit,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from editor.keybinds import BRUSH_SLOTS, TOOL_NAMES


class SettingsDialog(QDialog):
    theme_toggled = Signal(bool)
    undo_redo_swap_changed = Signal(bool)
    tool_keybind_changed = Signal(str, str)     # tool name, new key
    brush_keybind_changed = Signal(int, str)    # 0-based brush index, new key
    deco_flip_keybind_changed = Signal(str)     # new key

    def __init__(self, theme, tool_keybinds, brush_keybinds,
                 undo_redo_swapped, deco_flip_keybind, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")

        # local copies for collision-checking as the user edits — only a
        # validated change is emitted upward
        self._tool_keys = dict(tool_keybinds)
        self._brush_keys = list(brush_keybinds)
        self._swapped = undo_redo_swapped
        self._deco_flip_key = deco_flip_keybind

        layout = QVBoxLayout(self)

        self._dark_box = QCheckBox("Dark mode", self)
        self._dark_box.setChecked(theme == "dark")
        self._dark_box.toggled.connect(self.theme_toggled.emit)
        layout.addWidget(self._dark_box)

        self._swap_btn = QPushButton(self)
        self._swap_btn.clicked.connect(self._on_swap_clicked)
        layout.addWidget(self._swap_btn)
        self._update_swap_label()

        self._error_label = QLabel("", self)
        self._error_label.setStyleSheet("color: #c0392b;")
        layout.addWidget(self._error_label)

        layout.addWidget(QLabel("Tool keybinds"))
        tool_form = QFormLayout()
        self._tool_edits = {}
        for name in TOOL_NAMES:
            edit = QKeySequenceEdit(QKeySequence(self._tool_keys[name]), self)
            edit.setMaximumSequenceLength(1)
            edit.editingFinished.connect(
                lambda n=name: self._on_tool_key_edited(n))
            self._tool_edits[name] = edit
            tool_form.addRow(name.title(), edit)
        layout.addLayout(tool_form)

        layout.addWidget(
            QLabel("Brush keybinds (Game tiles mode, positions 1-5)"))
        brush_form = QFormLayout()
        self._brush_edits = []
        for i in range(len(BRUSH_SLOTS)):
            edit = QKeySequenceEdit(QKeySequence(self._brush_keys[i]), self)
            edit.setMaximumSequenceLength(1)
            edit.editingFinished.connect(
                lambda idx=i: self._on_brush_key_edited(idx))
            self._brush_edits.append(edit)
            brush_form.addRow(f"Brush {i + 1}", edit)
        layout.addLayout(brush_form)

        layout.addWidget(QLabel("Deco tool keybinds"))
        deco_form = QFormLayout()
        self._deco_flip_edit = QKeySequenceEdit(
            QKeySequence(self._deco_flip_key), self)
        self._deco_flip_edit.setMaximumSequenceLength(1)
        self._deco_flip_edit.editingFinished.connect(
            self._on_deco_flip_key_edited)
        deco_form.addRow("Mirror Flip", self._deco_flip_edit)
        layout.addLayout(deco_form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.accept)
        layout.addWidget(buttons)

    # -- undo/redo swap -------------------------------------------------

    def _update_swap_label(self):
        undo_key, redo_key = ("Ctrl+Y", "Ctrl+Z") if self._swapped \
            else ("Ctrl+Z", "Ctrl+Y")
        self._swap_btn.setText(
            f"Swap Undo/Redo — currently Undo={undo_key}, Redo={redo_key}")

    def _on_swap_clicked(self):
        self._swapped = not self._swapped
        self._update_swap_label()
        self.undo_redo_swap_changed.emit(self._swapped)

    # -- keybind capture + validation -------------------------------------

    def _all_bound_keys(self):
        """Every bare key currently bound to a tool, brush or the deco flip
        toggle, for collision checks — undo/redo always carries Ctrl, so it
        never collides with a bare tool/brush/deco-flip key."""
        return (set(self._tool_keys.values()) | set(self._brush_keys)
                | {self._deco_flip_key})

    def _captured_key(self, edit):
        """The bare key text an edit captured, or None if empty/modified.
        QKeySequenceEdit doesn't stop a user from holding a modifier while
        typing — reject anything but a bare key. (Escape clears the field
        instead of being capturable at all; that's a Qt built-in, not a bug
        to "fix" here.)"""
        seq = edit.keySequence()
        if seq.count() != 1:
            return None
        combo = seq[0]
        if combo.keyboardModifiers() != Qt.KeyboardModifier.NoModifier:
            return None
        return QKeySequence(combo.key()).toString()

    def _reject_edit(self, edit, previous, message):
        edit.blockSignals(True)
        edit.setKeySequence(QKeySequence(previous))
        edit.blockSignals(False)
        self._error_label.setText(message)

    def _on_tool_key_edited(self, name):
        edit = self._tool_edits[name]
        previous = self._tool_keys[name]
        key = self._captured_key(edit)
        if key is None:
            self._reject_edit(
                edit, previous,
                "Tool keybinds must be a single key with no modifier.")
            return
        if key != previous and key in self._all_bound_keys():
            self._reject_edit(
                edit, previous,
                f"'{key}' is already bound to another tool/brush.")
            return
        self._error_label.setText("")
        self._tool_keys[name] = key
        self.tool_keybind_changed.emit(name, key)

    def _on_brush_key_edited(self, index):
        edit = self._brush_edits[index]
        previous = self._brush_keys[index]
        key = self._captured_key(edit)
        if key is None:
            self._reject_edit(
                edit, previous,
                "Brush keybinds must be a single key with no modifier.")
            return
        if key != previous and key in self._all_bound_keys():
            self._reject_edit(
                edit, previous,
                f"'{key}' is already bound to another tool/brush.")
            return
        self._error_label.setText("")
        self._brush_keys[index] = key
        self.brush_keybind_changed.emit(index, key)

    def _on_deco_flip_key_edited(self):
        edit = self._deco_flip_edit
        previous = self._deco_flip_key
        key = self._captured_key(edit)
        if key is None:
            self._reject_edit(
                edit, previous,
                "Deco keybinds must be a single key with no modifier.")
            return
        if key != previous and key in self._all_bound_keys():
            self._reject_edit(
                edit, previous,
                f"'{key}' is already bound to another tool/brush.")
            return
        self._error_label.setText("")
        self._deco_flip_key = key
        self.deco_flip_keybind_changed.emit(key)
