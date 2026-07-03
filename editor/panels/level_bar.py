"""LevelBar — the bottom-panel level picker (Phase 5 selection layout).

A thin radio row ("Level: (•)1 ( )2 ( )3") that picks among one tier's
slots; hidden whenever the active subcategory has no level dimension
(single-slot groups, enemies, UI...). Plain Qt widget; slot resolution
itself lives in editor.selection — this bar only reports an index.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QWidget,
)


class LevelBar(QWidget):
    level_changed = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 2, 8, 2)
        self._layout.addWidget(QLabel("Level:"))
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self.level_changed)
        self._buttons = []
        self._layout.addStretch(1)
        self.hide()

    def set_levels(self, slot_keys, assigned=()):
        """One radio per slot, labelled by position (1-based); ● marks
        assigned slots (ED-11), tooltips carry the actual slot key. A
        single-slot (or empty) list hides the bar; index resets to 0."""
        for button in self._buttons:
            self._group.removeButton(button)
            self._layout.removeWidget(button)
            button.deleteLater()
        self._buttons = []
        for i, slot_key in enumerate(slot_keys):
            label = str(i + 1) + (" ●" if slot_key in assigned else "")
            button = QRadioButton(label)
            button.setToolTip(slot_key)
            self._group.addButton(button, i)
            # keep buttons ahead of the trailing stretch
            self._layout.insertWidget(1 + i, button)
            self._buttons.append(button)
        if self._buttons:
            self._buttons[0].setChecked(True)
        self.setVisible(len(self._buttons) > 1)

    def level(self):
        checked = self._group.checkedId()
        return checked if checked >= 0 else 0
