"""PalettePanel (ED-20) — the tilemap editor's brush dock, organised into three
PAINT MODES (user-directed):

- **Gametiles** — the zone tiles (buildable / combat / spawning) PLUS the Hole
  (base). The hole is placed like any other tile (paint = place/move the single
  hole; erase = remove it), but there can only ever be one.
- **Background** — the background tile types shown as "Level 1", "Level 2", … in
  legend order, with a "+ Level" button that adds a brand-new background type
  (Level 4, 5, …) to the open map's legend + the slot registry.
- **Decoration** — the deco props, with an "+ Add Prop" button that adds a new
  prop slot to the registry.

A single exclusive brush group spans all three mode pages, so exactly one brush
is armed at a time. The tool row (none/paint/erase/line/rect/bucket/picker), the
layer eyes, the grid toggle, and "Import Spritesheet…" are shared across modes.

ED-22 interpretation (user-confirmed): the icons are STATIC frames resolved by
the engine's AssetStore and converted via the viewport's surface_to_qimage —
blitting engine-resolved frames is not a second render path; the only live
rendering stays the viewport. Icons come through an injected provider
(slot -> QImage) so this module itself stays pygame-free.
"""
from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor.asset_import import import_idle_sheet
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]

TOOLS = ("none", "paint", "erase", "line", "rect", "bucket", "picker")
EYES = ("terrain", "tint", "base", "deco")
MODES = ("gametiles", "background", "decoration")
MODE_LABELS = {
    "gametiles": "Game tiles",
    "background": "Background",
    "decoration": "Decoration",
}


def _title(slot):
    """tile_buildable -> 'Buildable', deco_rock -> 'Rock' (data-driven)."""
    name = slot.split("_", 1)[1] if "_" in slot else slot
    return name.replace("_", " ").title()


class PalettePanel(QWidget):
    tool_changed = Signal(str)
    code_armed = Signal(str)     # a terrain code from the open map's legend
    deco_armed = Signal(str)     # a deco slot key
    base_armed = Signal(str)     # the base/hole slot (now a paintable brush)
    eye_toggled = Signal(str, bool)
    grid_toggled = Signal(bool)
    manifest_changed = Signal(str)   # a slot got a fresh import (ED-40 parity)
    mode_changed = Signal(str)       # gametiles / background / decoration
    add_level_requested = Signal()   # + Level (new background type)
    add_prop_requested = Signal()    # + Add Prop (new deco slot)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._registry = load_registry(self._data_dir)
        self._icon_provider = None      # slot -> QImage (viewport-injected)
        self._legend = None
        self._mode = "gametiles"
        # ("code"|"deco"|"base", key) -> QToolButton, spanning all mode pages
        self._brush_buttons = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        # -- mode selector ----------------------------------------------------
        layout.addWidget(QLabel("Mode"))
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_buttons = {}
        for name in MODES:
            btn = QToolButton(self)
            btn.setText(MODE_LABELS[name])
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, n=name: self.set_mode(n))
            self._mode_group.addButton(btn)
            self._mode_buttons[name] = btn
            layout.addWidget(btn)
        self._mode_buttons["gametiles"].setChecked(True)

        # -- tools (shared) ---------------------------------------------------
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
        self._tool = "none"
        self._tool_buttons["none"].setChecked(True)

        self._import_btn = QPushButton("Import Spritesheet…", self)
        self._import_btn.clicked.connect(self._on_import_clicked)
        layout.addWidget(self._import_btn)

        # -- brush pages (one per mode); one exclusive group spans them --------
        self._brush_group = QButtonGroup(self)
        self._brush_group.setExclusive(True)
        self._pages = {}
        for name in MODES:
            title = QLabel(MODE_LABELS[name])
            page = QWidget(self)
            page_layout = QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.setSpacing(2)
            layout.addWidget(title)
            layout.addWidget(page)
            self._pages[name] = (title, page, page_layout)

        self._add_level_btn = QPushButton("+ Level", self)
        self._add_level_btn.clicked.connect(self.add_level_requested.emit)
        self._pages["background"][2].addWidget(self._add_level_btn)

        self._add_prop_btn = QPushButton("+ Add Prop", self)
        self._add_prop_btn.clicked.connect(self.add_prop_requested.emit)
        self._pages["decoration"][2].addWidget(self._add_prop_btn)

        self._rebuild_gametiles()
        self._rebuild_background()
        self._rebuild_deco()

        # -- layer eyes + grid (shared) ---------------------------------------
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

        self._apply_mode_visibility()

    # -- registry-driven slot lists ------------------------------------------

    def _deco_slots(self):
        for category in self._registry.categories():
            if category.key == "deco":
                return self._registry.group_slots(category.key, ())
        return ()

    def _base_slots(self):
        for category in self._registry.categories():
            if category.key == "core":
                return self._registry.group_slots(category.key, ())
        return ()

    def _zone_codes(self):
        """Legend codes for the zone (checker) tiles, sorted."""
        if not self._legend:
            return []
        return sorted(c for c, e in self._legend.items() if e["checker"])

    def _background_codes(self):
        """Legend codes for the background (non-checker) tiles, sorted — the
        order that numbers them 'Level 1', 'Level 2', …"""
        if not self._legend:
            return []
        return sorted(c for c, e in self._legend.items() if not e["checker"])

    # -- brush-button construction -------------------------------------------

    def _add_brush_button(self, page_layout, key, label, insert_at):
        kind, value = key
        btn = QToolButton(self)
        btn.setText(label)
        btn.setCheckable(True)
        btn.setIconSize(QSize(32, 32))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        if kind == "code":
            btn.clicked.connect(lambda _=False, v=value: self.arm_code(v))
        elif kind == "deco":
            btn.clicked.connect(lambda _=False, v=value: self.arm_deco(v))
        else:
            btn.clicked.connect(lambda _=False, v=value: self.arm_base(v))
        self._brush_group.addButton(btn)
        self._brush_buttons[key] = btn
        page_layout.insertWidget(insert_at, btn)
        return btn

    def _clear_page_brushes(self, kind, page_layout):
        for key in [k for k in self._brush_buttons if k[0] == kind]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()

    def _rebuild_gametiles(self):
        _title_w, _page, page_layout = self._pages["gametiles"]
        self._clear_page_brushes("code", page_layout)
        # base buttons also live here; clear + rebuild them too
        for key in [k for k in self._brush_buttons if k[0] == "base"]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()
        idx = 0
        for code in self._zone_codes():
            self._add_brush_button(page_layout, ("code", code),
                                   _title(self._legend[code]["slot"]), idx)
            idx += 1
        for slot in self._base_slots():
            self._add_brush_button(page_layout, ("base", slot), "Hole", idx)
            idx += 1
        self.refresh_icons()

    def _rebuild_background(self):
        _title_w, _page, page_layout = self._pages["background"]
        # keep the trailing "+ Level" button; only clear the level brushes
        for key in [k for k in self._brush_buttons if k[0] == "code"
                    and self._legend and not self._legend[k[1]]["checker"]]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()
        for i, code in enumerate(self._background_codes()):
            self._add_brush_button(
                page_layout, ("code", code), f"Level {i + 1}", i)
        self.refresh_icons()

    def _rebuild_deco(self):
        _title_w, _page, page_layout = self._pages["decoration"]
        self._clear_page_brushes("deco", page_layout)
        for i, slot in enumerate(self._deco_slots()):
            self._add_brush_button(page_layout, ("deco", slot), _title(slot), i)
        self.refresh_icons()

    # -- legend (per open map) + icons ---------------------------------------

    def set_legend(self, legend):
        """Rebuild the gametiles zone buttons and the background level buttons
        from the open map's legend."""
        self._legend = legend
        self._rebuild_gametiles()
        self._rebuild_background()

    def reload_registry(self):
        """Re-read data/slots.json after a '+ Add Prop' / '+ Level' registry
        write so new slots resolve for icons + import."""
        self._registry = load_registry(self._data_dir)
        self._rebuild_gametiles()
        self._rebuild_deco()

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

    # -- mode ----------------------------------------------------------------

    def current_mode(self):
        return self._mode

    def set_mode(self, name):
        self._mode = name
        self._mode_buttons[name].setChecked(True)
        self._apply_mode_visibility()
        self.mode_changed.emit(name)
        self._arm_first_of_mode()

    def _apply_mode_visibility(self):
        for name, (title, page, _layout) in self._pages.items():
            visible = name == self._mode
            title.setVisible(visible)
            page.setVisible(visible)

    def _arm_first_of_mode(self):
        """Arm the first brush of the newly shown mode so a paint click can't
        use a brush hidden on another page."""
        if self._mode == "gametiles":
            codes = self._zone_codes()
            if codes:
                self.arm_code(codes[0])
            else:
                bases = self._base_slots()
                if bases:
                    self.arm_base(bases[0])
        elif self._mode == "background":
            codes = self._background_codes()
            if codes:
                self.arm_code(codes[0])
        else:
            decos = self._deco_slots()
            if decos:
                self.arm_deco(decos[0])

    # -- tool + armed-brush state (read by the viewport via MainWindow) ------

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

    def armed_base(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "base" and btn.isChecked():
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

    def arm_base(self, slot):
        """Arm the Hole brush. Unlike the old import-only base button, this is a
        real paintable brush now (paint = place/move the single hole, erase =
        remove it — viewport._tool_press). base_armed still tells the viewport to
        clear any stale armed code/deco."""
        btn = self._brush_buttons.get(("base", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.base_armed.emit(slot)

    def eye(self, name):
        return self._eye_boxes[name].isChecked()

    def grid_on(self):
        return self._grid_box.isChecked()

    # -- import (ED-40 parity, targets the armed brush) ----------------------

    def _armed_slot(self):
        """The slot the currently armed brush points at, or None."""
        deco = self.armed_deco()
        if deco is not None:
            return deco
        base = self.armed_base()
        if base is not None:
            return base
        code = self.armed_code()
        if code is not None and self._legend is not None:
            return self._legend[code]["slot"]
        return None

    def _on_import_clicked(self):
        slot = self._armed_slot()
        if slot is None:
            QMessageBox.information(
                self, "Import Spritesheet",
                "Arm a tile, background, hole or deco brush first — the import "
                "targets whichever one is currently selected.")
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "Choose spritesheet PNG", "", "PNG images (*.png)")
        if not path:
            return
        try:
            import_idle_sheet(self._data_dir, self._registry, slot, path)
        except ValueError as exc:
            QMessageBox.warning(self, "Import Spritesheet", str(exc))
            return
        self.refresh_icons()
        self.manifest_changed.emit(slot)
