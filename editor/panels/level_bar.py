"""LevelBar — the bottom-panel level picker (Phase 5 selection layout).

A thin radio row ("Level: (•)1 ( )2 ( )3") that picks among one tier's
slots; hidden whenever the active subcategory has no level dimension
(single-slot groups, UI...). Plain Qt widget; slot resolution itself lives in
editor.selection — this bar only reports an index.

For enemy eras (the shell passes ``can_add=True``) a trailing "+ Variant"
button emits ``add_variant_requested``; the shell appends a variant slot to
that era in slots.json and reselects it. Because the button must reach eras
that currently have only ONE slot, ``can_add`` also forces the bar visible
even for a single-slot list.
"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QWidget,
)


class LevelBar(QWidget):
    level_changed = Signal(int)
    add_variant_requested = Signal()

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
        # sits at the far right, past the stretch; radios insert before it
        self._add_btn = QPushButton("+ Variant")
        self._add_btn.setToolTip(
            "Add another sprite variant to this enemy stage")
        self._add_btn.clicked.connect(self.add_variant_requested)
        self._layout.addWidget(self._add_btn)
        self._add_btn.hide()
        self.hide()

    def set_levels(self, slot_keys, assigned=(), can_add=False):
        """One radio per slot, labelled by position (1-based); ● marks
        assigned slots (ED-11), tooltips carry the actual slot key. A
        single-slot (or empty) list hides the bar UNLESS ``can_add`` (enemy
        eras keep the "+ Variant" button reachable); index resets to 0."""
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
        self._add_btn.setVisible(can_add)
        self.setVisible(len(self._buttons) > 1 or can_add)

    def select_last(self):
        """Check the last level and report it (used after adding a variant so
        the new slot is the one shown, ready for import). No-op on <2 levels."""
        if len(self._buttons) > 1:
            last = len(self._buttons) - 1
            self._buttons[last].setChecked(True)
            self.level_changed.emit(last)

    def level(self):
        checked = self._group.checkedId()
        return checked if checked >= 0 else 0
