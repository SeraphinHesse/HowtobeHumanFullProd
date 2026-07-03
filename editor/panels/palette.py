"""PalettePanel (ED-20) — the tilemap editor's brush dock: semantic tile
types + deco slots (each iconed with its engine-resolved sprite, grey X if
none), the tool row (paint / erase / line / rect / bucket / picker), the
layer eyes (terrain / zone tint / base / deco) and the grid-lines toggle
(ED-23).

ED-22 interpretation (user-confirmed): the icons are STATIC frames
resolved by the engine's AssetStore and converted via the viewport's
surface_to_qimage — blitting engine-resolved frames is not a second
render path; the only live rendering stays the viewport. Icons come
through an injected provider (slot -> QImage) so this module itself
stays pygame-free.
"""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QLabel,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]

TOOLS = ("paint", "erase", "line", "rect", "bucket", "picker")
EYES = ("terrain", "tint", "base", "deco")


def _title(slot):
    """tile_buildable -> 'Buildable', deco_rock -> 'Rock' (data-driven)."""
    name = slot.split("_", 1)[1] if "_" in slot else slot
    return name.replace("_", " ").title()


class PalettePanel(QWidget):
    tool_changed = Signal(str)
    code_armed = Signal(str)     # a terrain code from the open map's legend
    deco_armed = Signal(str)     # a deco slot key
    eye_toggled = Signal(str, bool)
    grid_toggled = Signal(bool)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._registry = load_registry(self._data_dir)
        self._icon_provider = None      # slot -> QImage (viewport-injected)
        self._legend = None
        self._brush_buttons = {}        # ("code"|"deco", key) -> QToolButton

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        layout.addWidget(QLabel("Tools"))
        self._tool_group = QButtonGroup(self)
        self._tool_group.setExclusive(True)
        self._tool_buttons = {}
        for name in TOOLS:
            btn = QToolButton(self)
            btn.setText(name.title())
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, n=name: self.set_tool(n))
            self._tool_group.addButton(btn)
            self._tool_buttons[name] = btn
            layout.addWidget(btn)
        self._tool = "paint"
        self._tool_buttons["paint"].setChecked(True)

        layout.addWidget(QLabel("Tiles"))
        self._tiles_start = layout.count()
        self._brush_group = QButtonGroup(self)
        self._brush_group.setExclusive(True)

        self._deco_label = QLabel("Deco")
        layout.addWidget(self._deco_label)
        for slot in self._deco_slots():
            self._add_brush_button(("deco", slot), _title(slot),
                                   layout.count())

        layout.addWidget(QLabel("Layers"))
        self._eye_boxes = {}
        for name in EYES:
            box = QCheckBox(name.title(), self)
            box.setChecked(True)
            box.toggled.connect(
                lambda on, n=name: self.eye_toggled.emit(n, on))
            self._eye_boxes[name] = box
            layout.addWidget(box)
        self._grid_box = QCheckBox("Grid lines", self)
        self._grid_box.setChecked(False)
        self._grid_box.toggled.connect(self.grid_toggled.emit)
        layout.addWidget(self._grid_box)
        layout.addStretch(1)

    # -- construction helpers -------------------------------------------------

    def _deco_slots(self):
        for category in self._registry.categories():
            if category.key == "deco":
                return self._registry.group_slots(category.key, ())
        return ()

    def _add_brush_button(self, key, label, index):
        btn = QToolButton(self)
        btn.setText(label)
        btn.setCheckable(True)
        btn.setIconSize(QSize(32, 32))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        kind, value = key
        if kind == "code":
            btn.clicked.connect(lambda _=False, v=value: self.arm_code(v))
        else:
            btn.clicked.connect(lambda _=False, v=value: self.arm_deco(v))
        self._brush_group.addButton(btn)
        self._brush_buttons[key] = btn
        self.layout().insertWidget(index, btn)
        return btn

    # -- legend (per open map) + icons ---------------------------------------

    def set_legend(self, legend):
        """Rebuild the tile-code buttons from the open map's legend —
        zone (checker) kinds first, then background kinds."""
        for key in [k for k in self._brush_buttons if k[0] == "code"]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            btn.deleteLater()
        self._legend = legend
        if legend:
            ordered = sorted(
                legend, key=lambda c: (not legend[c]["checker"], c))
            index = self._tiles_start
            for code in ordered:
                self._add_brush_button(
                    ("code", code), _title(legend[code]["slot"]), index)
                index += 1
        self.refresh_icons()

    def set_icon_provider(self, provider):
        """provider(slot_key) -> QImage of the engine-resolved idle frame."""
        self._icon_provider = provider
        self.refresh_icons()

    def refresh_icons(self):
        if self._icon_provider is None:
            return
        for (kind, value), btn in self._brush_buttons.items():
            slot = self._legend[value]["slot"] if kind == "code" else value
            image = self._icon_provider(slot)
            if image is not None:
                btn.setIcon(QIcon(QPixmap.fromImage(image)))

    # -- state (what the viewport reads through MainWindow wiring) ------------

    def current_tool(self):
        return self._tool

    def set_tool(self, name):
        self._tool = name
        self._tool_buttons[name].setChecked(True)
        self.tool_changed.emit(name)

    def armed_code(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "code" and btn.isChecked():
                return value
        return None

    def armed_deco(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "deco" and btn.isChecked():
                return value
        return None

    def arm_code(self, code):
        btn = self._brush_buttons.get(("code", code))
        if btn is None:
            return
        btn.setChecked(True)
        self.code_armed.emit(code)

    def arm_deco(self, slot):
        btn = self._brush_buttons.get(("deco", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.deco_armed.emit(slot)

    def eye(self, name):
        return self._eye_boxes[name].isChecked()

    def grid_on(self):
        return self._grid_box.isChecked()
