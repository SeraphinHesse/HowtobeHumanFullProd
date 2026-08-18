"""PalettePanel (ED-20) — the tilemap editor's brush dock, organised into three
PAINT MODES (user-directed):

- **Gametiles** — the zone tiles (buildable / combat / spawning) PLUS the Hole
  (base). The hole is placed like any other tile (paint = place/move the single
  hole; erase = remove it), but there can only ever be one.
- **Background** — the background tile types shown as "Level 1", "Level 2", … in
  legend order, with a "+ Level" button that adds a brand-new background type
  (Level 4, 5, …) to the open map's legend + the slot registry.
- **Decoration** — a "Type:" selector picks one deco prop TYPE (Rock, Bush, …);
  the brushes below it are that type's interchangeable VARIANTS ("Var 1",
  "Var 2", …), so a specific variant is armed and stored in the map file.
  "+ Variant" adds another variant to the current type; "+ Add Prop" adds a
  brand-new type.
- **Spawnable Background** — ONE brush (plain text, NO sprite: a mark is an
  invisible overlay, not a tile kind) plus a spinbox for the STAGE NUMBER
  the marks it paints carry. Every mark numbered n releases together when the
  run's stage counter reaches n; the underlying forest/cliff/ocean art keeps
  drawing and the game never sees the mark as a legend code.
- **Stage Zones** — the same one-brush-plus-a-number shape again, painted on
  COMBAT tiles: buying a 2×2 that intersects the painted set advances the
  run's stage counter to the highest number among those four tiles, which is
  the ONLY thing that fires the two batches above.
- **Tile Conditions** — the fourth invisible overlay, and the first whose brush
  value is a NAME rather than a number: one brush button per condition name,
  built from `map_file.schema.json`'s own enum via
  `engine.tilemap.condition_codes_from_schema` (adding a fifth condition is a
  schema edit and nothing else — the names are never hardcoded here). A marked
  cell always has that condition and is excluded from the random roll.

A single exclusive brush group spans all mode pages, so exactly one brush
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
    QScrollArea,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor.asset_import import import_idle_sheet
from editor.panels.balancing import _NoWheelComboBox, _NoWheelSpinBox
from engine import data_io, tilemap
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]

TOOLS = ("none", "paint", "erase", "line", "rect", "bucket", "picker")
EYES = ("terrain", "tint", "base", "deco", "camera", "start_area", "tutorial",
        "spawn_reserve", "despawnable_spawn", "stage_zones", "tile_conditions")
MODES = ("gametiles", "background", "decoration", "tutorial", "spawn_reserve",
         "despawnable_spawn", "stage_zones", "tile_conditions")
MODE_LABELS = {
    "gametiles": "Game tiles",
    "background": "Background",
    "decoration": "Decoration",
    "tutorial": "Tutorial",
    "spawn_reserve": "Spawnable Background",
    "despawnable_spawn": "Despawnable Spawn",
    "stage_zones": "Stage Zones",
    "tile_conditions": "Tile Conditions",
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
    camera_armed = Signal(str)   # the camera-startpoint slot (paintable brush)
    # the camera play-area CENTRE slot (paintable brush) — the Camera Start
    # brush's twin, anchoring the camera travel limit rather than the opening view
    camera_limit_center_armed = Signal(str)
    start_area_armed = Signal(str)  # the 2×2 starting-area slot (paintable brush)
    tutorial_flute_armed = Signal(str)  # the "first flute" marker slot
    tutorial_stone_armed = Signal(str)  # the "first stone" marker slot
    tutorial_unlock_armed = Signal(str)  # the tile-buying "tile to unlock" marker slot
    tutorial_stone_2_armed = Signal(str)  # the tile-buying "second stone" marker slot
    spawn_reserve_armed = Signal()      # the spawnable-background brush (no slot)
    reserve_number_changed = Signal(int)  # the stage number marks carry
    despawn_armed = Signal()            # the despawnable-spawn brush (no slot)
    despawn_number_changed = Signal(int)  # the stage number marks carry
    stage_armed = Signal()              # the stage-zone brush (no slot)
    stage_number_changed = Signal(int)  # the stage number marks carry
    tile_condition_armed = Signal(str)  # the condition NAME the brush paints
    eye_toggled = Signal(str, bool)
    grid_toggled = Signal(bool)
    manifest_changed = Signal(str)   # a slot got a fresh import (ED-40 parity)
    mode_changed = Signal(str)       # gametiles / background / decoration
    add_level_requested = Signal()   # + Level (new background type)
    add_prop_requested = Signal()    # + Add Prop (new deco type)
    add_deco_variant_requested = Signal(str)  # + Variant (deco type label)
    background_slot_armed = Signal(str)  # a not-yet-bound background slot clicked
    deco_flip_toggled = Signal(bool)    # mirror-flip toggle for the deco brush

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._registry = load_registry(self._data_dir)
        self._icon_provider = None      # slot -> QImage (viewport-injected)
        self._legend = None
        self._mode = "gametiles"
        # ("code"|"deco"|"base", key) -> QToolButton, spanning all mode pages
        self._brush_buttons = {}
        # condition NAME -> QToolButton (Tile Conditions page). Kept OUT of
        # _brush_buttons for the same reason the three overlay-mark brushes are
        # not in it: that dict drives refresh_icons()/_armed_slot(), both of
        # which need a registry SLOT, and a condition name is not one.
        self._condition_buttons = {}
        # keybind labels (ED settings panel) — set via set_tool_keybinds /
        # set_brush_keybinds; empty until MainWindow supplies the real values
        self._tool_keybinds = {}
        self._brush_keybinds = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        layout = QVBoxLayout(content)
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

        # decoration page: type selector above the variant brushes, then the
        # two add-buttons. Brushes insert at index 1 (after the combo).
        self._deco_type_combo = _NoWheelComboBox(self)
        self._deco_type_combo.currentIndexChanged.connect(
            self._on_deco_type_changed)
        self._pages["decoration"][2].addWidget(self._deco_type_combo)

        self._add_deco_variant_btn = QPushButton("+ Variant", self)
        self._add_deco_variant_btn.setToolTip(
            "Add another sprite variant to the selected decoration type")
        self._add_deco_variant_btn.clicked.connect(
            lambda: self.add_deco_variant_requested.emit(self.deco_type()))
        self._pages["decoration"][2].addWidget(self._add_deco_variant_btn)

        self._add_prop_btn = QPushButton("+ Add Prop", self)
        self._add_prop_btn.setToolTip("Add a brand-new decoration type")
        self._add_prop_btn.clicked.connect(self.add_prop_requested.emit)
        self._pages["decoration"][2].addWidget(self._add_prop_btn)

        self._deco_flip_box = QCheckBox("Mirror Flip", self)
        self._deco_flip_box.setChecked(False)
        self._deco_flip_box.toggled.connect(self.deco_flip_toggled.emit)
        self._pages["decoration"][2].addWidget(self._deco_flip_box)

        # spawnable-background page: ONE plain-text brush (no sprite — the mark
        # is an invisible overlay, like the tutorial markers which also draw as
        # outlines) in the SAME exclusive group as every other brush, with the
        # stage-number spinbox directly under it.
        reserve_layout = self._pages["spawn_reserve"][2]
        self._spawn_reserve_btn = QToolButton(self)
        self._spawn_reserve_btn.setText("Spawn Reserve Mark")
        self._spawn_reserve_btn.setToolTip(
            "Paint invisible spawnable-background marks: every mark numbered n "
            "turns SPAWNING when the run reaches stage n")
        self._spawn_reserve_btn.setCheckable(True)
        self._spawn_reserve_btn.clicked.connect(
            lambda _=False: self.arm_spawn_reserve())
        self._brush_group.addButton(self._spawn_reserve_btn)
        reserve_layout.addWidget(self._spawn_reserve_btn)

        reserve_layout.addWidget(QLabel("Released at stage #"))
        lo, hi = self._reserve_number_bounds()
        self._reserve_spin = _NoWheelSpinBox(self)   # ED-30, never a bare QSpinBox
        self._reserve_spin.setRange(lo, hi)
        self._reserve_spin.setValue(lo)
        self._reserve_spin.valueChanged.connect(self.reserve_number_changed.emit)
        reserve_layout.addWidget(self._reserve_spin)

        # despawnable-spawn page: the exact twin of the page above, over the
        # despawnable_spawn overlay (SPAWNING -> COMBAT at stage n).
        despawn_layout = self._pages["despawnable_spawn"][2]
        self._despawn_btn = QToolButton(self)
        self._despawn_btn.setText("Spawn Despawn Mark")
        self._despawn_btn.setToolTip(
            "Paint invisible despawnable-spawn marks: every mark numbered n "
            "turns from SPAWNING to COMBAT when the run reaches stage n")
        self._despawn_btn.setCheckable(True)
        self._despawn_btn.clicked.connect(
            lambda _=False: self.arm_despawn())
        self._brush_group.addButton(self._despawn_btn)
        despawn_layout.addWidget(self._despawn_btn)

        despawn_layout.addWidget(QLabel("Retired at stage #"))
        lo, hi = self._despawn_number_bounds()
        self._despawn_spin = _NoWheelSpinBox(self)   # ED-30, never a bare QSpinBox
        self._despawn_spin.setRange(lo, hi)
        self._despawn_spin.setValue(lo)
        self._despawn_spin.valueChanged.connect(self.despawn_number_changed.emit)
        despawn_layout.addWidget(self._despawn_spin)

        # stage-zones page: the third page of exactly this shape, over the
        # stage_zones overlay. Painted on COMBAT tiles; buying a 2×2 that
        # intersects the painted set advances the run's stage counter to the
        # HIGHEST number among those four tiles.
        stage_layout = self._pages["stage_zones"][2]
        self._stage_btn = QToolButton(self)
        self._stage_btn.setText("Stage Zone Mark")
        self._stage_btn.setToolTip(
            "Paint invisible stage-zone marks on combat tiles: buying a 2×2 "
            "that intersects them advances the run to the highest stage among "
            "the four bought tiles")
        self._stage_btn.setCheckable(True)
        self._stage_btn.clicked.connect(
            lambda _=False: self.arm_stage())
        self._brush_group.addButton(self._stage_btn)
        stage_layout.addWidget(self._stage_btn)

        stage_layout.addWidget(QLabel("Advances to stage #"))
        lo, hi = self._stage_number_bounds()
        self._stage_spin = _NoWheelSpinBox(self)   # ED-30, never a bare QSpinBox
        self._stage_spin.setRange(lo, hi)
        self._stage_spin.setValue(lo)
        self._stage_spin.valueChanged.connect(self.stage_number_changed.emit)
        stage_layout.addWidget(self._stage_spin)

        # tile-conditions page: the fourth overlay page, but its brush value is
        # a NAME, not a number — so instead of a spinbox it carries ONE
        # plain-text brush per condition, all in the SAME exclusive brush group
        # (the gametiles/background idiom), which is also what makes the
        # eyedropper's return path a plain re-check of the matching button.
        condition_layout = self._pages["tile_conditions"][2]
        for name in self._condition_names():
            btn = QToolButton(self)
            btn.setText(name.title())
            btn.setToolTip(
                f"Paint invisible {name} marks: a marked cell ALWAYS has the "
                f"{name} condition and is excluded from the random condition "
                "roll")
            btn.setCheckable(True)
            btn.clicked.connect(
                lambda _=False, n=name: self.arm_tile_condition(n))
            self._brush_group.addButton(btn)
            self._condition_buttons[name] = btn
            condition_layout.addWidget(btn)

        self._rebuild_deco_types()   # also builds the deco variant brushes
        self._rebuild_gametiles()
        self._rebuild_background()
        self._rebuild_tutorial()

        # -- layer eyes + grid (shared) ---------------------------------------
        layout.addWidget(QLabel("Layers"))
        self._eye_boxes = {}
        for name in EYES:
            box = QCheckBox(
                MODE_LABELS.get(name, name.replace("_", " ").title()), self)
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

    def _deco_types(self):
        """Labels of the deco prop TYPES (the 'Props' group's leaf children),
        in registry order — what the Type: combo offers."""
        try:
            group = self._registry.group("deco", ("Props",))
        except (KeyError, ValueError):
            return []
        return [child.label for child in group.children]

    def _deco_slots(self, type_label=None):
        """Variant slots of ONE deco type (default: the armed type). Every deco
        brush button is a variant of exactly one type."""
        label = self._deco_type_combo.currentText() if type_label is None \
            else type_label
        if not label:
            return []
        try:
            return list(self._registry.group_slots("deco", ("Props", label)))
        except (KeyError, ValueError):
            return []

    def _base_slots(self):
        # scoped to the "Base" group so the sibling "Camera Start" group's slot
        # doesn't leak in as a second Hole button
        try:
            return list(self._registry.group_slots("core", ("Base",)))
        except (KeyError, ValueError):
            return []

    def _camera_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Camera Start",)))
        except (KeyError, ValueError):
            return []

    def _camera_limit_center_slots(self):
        try:
            return list(
                self._registry.group_slots("core", ("Camera Limit Center",)))
        except (KeyError, ValueError):
            return []

    def _start_area_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Start Area",)))
        except (KeyError, ValueError):
            return []

    def _tutorial_flute_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Tutorial Flute",)))
        except (KeyError, ValueError):
            return []

    def _tutorial_stone_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Tutorial Stone",)))
        except (KeyError, ValueError):
            return []

    def _tutorial_unlock_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Tutorial Unlock",)))
        except (KeyError, ValueError):
            return []

    def _tutorial_stone_2_slots(self):
        try:
            return list(self._registry.group_slots("core", ("Tutorial Stone 2",)))
        except (KeyError, ValueError):
            return []

    def _stage_bounds(self, property_key):
        """(minimum, maximum) for one overlay's stage-number spinbox, read
        straight from map_file.schema.json's own item property — invalid input
        is unrepresentable (ED-30) and the bounds have exactly one home. The
        on-disk key is ``stage``, not ``purchase``: the number is a designer
        STAGE, advanced only by buying into a stage zone."""
        schema = data_io.load_json(tilemap.map_schema_path(self._data_dir))
        stage = (schema["properties"][property_key]
                 ["items"]["properties"]["stage"])
        return stage["minimum"], stage["maximum"]

    def _reserve_number_bounds(self):
        """Bounds for the spawnable-background stage spinbox."""
        return self._stage_bounds("spawnable_background")

    def _despawn_number_bounds(self):
        """Bounds for the despawnable-spawn stage spinbox."""
        return self._stage_bounds("despawnable_spawn")

    def _stage_number_bounds(self):
        """Bounds for the stage-zone spinbox."""
        return self._stage_bounds("stage_zones")

    def _condition_names(self):
        """The tile-condition names, in schema order — straight out of
        map_file.schema.json's own enum (the SINGLE source of that vocabulary,
        same "schemas over convention" reason the stage bounds come from the
        schema). Never a hardcoded list: a fifth condition is a schema edit and
        nothing else."""
        schema = data_io.load_json(tilemap.map_schema_path(self._data_dir))
        return list(tilemap.condition_codes_from_schema(schema))

    def _zone_codes(self):
        """Legend codes for the zone (checker) tiles, sorted."""
        if not self._legend:
            return []
        return sorted(c for c, e in self._legend.items() if e["checker"])

    def _background_slot_order(self):
        """The registry's ordering of background slots (forest, ocean, cliff,
        then any '+ Level' additions) — the canonical level order, stable across
        save/reload and appending new levels last (like enemy '+ Variant')."""
        try:
            return list(self._registry.group_slots("map", ("Tiles", "Background")))
        except (KeyError, ValueError):
            return []

    def _background_codes(self):
        """Legend codes for the background (non-checker) tiles, ordered by the
        registry's background-slot order — the order that numbers them 'Level 1',
        'Level 2', …  A new '+ Level' slot is appended in the registry, so its
        code lands last. Codes whose slot isn't in the registry fall back to the
        end, code-sorted, so nothing is ever dropped."""
        if not self._legend:
            return []
        codes = [c for c, e in self._legend.items() if not e["checker"]]
        order = self._background_slot_order()

        def rank(code):
            slot = self._legend[code]["slot"]
            return (order.index(slot), "") if slot in order else (len(order), code)

        return sorted(codes, key=rank)

    def _background_brush_order(self):
        """Ordered list of (key, label) for every Background brush: ALL
        registry background slots, each bound code getting its own
        ("code", code) brush (a slot bound to 2+ codes yields 2+ brushes —
        never drop a bound code) and unbound slots getting a single
        ("bgslot", slot) brush, in registry order; then any ORPHAN legend
        codes whose slot isn't in the registry order at all. Labels number
        continuously as 'Level N'."""
        codes_by_slot = {}
        if self._legend:
            for c, e in self._legend.items():
                if not e["checker"]:
                    codes_by_slot.setdefault(e["slot"], []).append(c)
        for codes in codes_by_slot.values():
            codes.sort()

        order = self._background_slot_order()
        result = []
        for slot in order:
            if slot in codes_by_slot:
                for code in codes_by_slot[slot]:
                    result.append((("code", code), None))
            else:
                result.append((("bgslot", slot), None))

        orphan_codes = sorted(
            code for slot, codes in codes_by_slot.items()
            if slot not in order for code in codes
        )
        for code in orphan_codes:
            result.append((("code", code), None))

        return [(key, f"Level {i + 1}") for i, (key, _) in enumerate(result)]

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
        elif kind == "camera":
            btn.clicked.connect(lambda _=False, v=value: self.arm_camera(v))
        elif kind == "camera_limit_center":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_camera_limit_center(v))
        elif kind == "start_area":
            btn.clicked.connect(lambda _=False, v=value: self.arm_start_area(v))
        elif kind == "tutorial_flute":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_tutorial_flute(v))
        elif kind == "tutorial_stone":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_tutorial_stone(v))
        elif kind == "tutorial_unlock":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_tutorial_unlock(v))
        elif kind == "tutorial_stone_2":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_tutorial_stone_2(v))
        elif kind == "bgslot":
            btn.clicked.connect(
                lambda _=False, v=value: self.arm_background_slot(v))
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

    def _gametiles_brush_order(self):
        """The (key, label) pairs _rebuild_gametiles() builds buttons for, in
        build order — the same order the settings panel's 5 number-key brush
        shortcuts index into (arm_gametiles_brush_by_index), so the mapping
        and the widget order can never drift apart."""
        order = [(("code", code), _title(self._legend[code]["slot"]))
                 for code in self._zone_codes()]
        order += [(("base", slot), "Hole") for slot in self._base_slots()]
        order += [(("camera", slot), "Camera Start")
                  for slot in self._camera_slots()]
        order += [(("camera_limit_center", slot), "Camera Limit Center")
                  for slot in self._camera_limit_center_slots()]
        order += [(("start_area", slot), "Starting Area")
                  for slot in self._start_area_slots()]
        return order

    def _rebuild_gametiles(self):
        _title_w, _page, page_layout = self._pages["gametiles"]
        self._clear_page_brushes("code", page_layout)
        # base + camera + limit-centre + start-area buttons also live here;
        # clear + rebuild too
        for key in [k for k in self._brush_buttons
                    if k[0] in ("base", "camera", "camera_limit_center",
                                "start_area")]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()
        for idx, (key, label) in enumerate(self._gametiles_brush_order()):
            self._add_brush_button(page_layout, key, label, idx)
        self.refresh_icons()
        self._relabel_gametiles_brushes()

    def _rebuild_background(self):
        _title_w, _page, page_layout = self._pages["background"]
        # keep the trailing "+ Level" button; only clear the level brushes —
        # bound "code" background buttons AND unbound "bgslot" buttons.
        for key in [k for k in self._brush_buttons if k[0] == "bgslot"
                    or (k[0] == "code" and self._legend
                        and not self._legend[k[1]]["checker"])]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()
        for i, (key, label) in enumerate(self._background_brush_order()):
            self._add_brush_button(page_layout, key, label, i)
        self.refresh_icons()

    def _rebuild_tutorial(self):
        """Four STATIC single-tile marker brushes (not legend-derived, unlike
        _rebuild_gametiles) — "First Flute" and "First Stone" (round-1/2's
        forced placements), plus the tile-buying topic's "Unlock Tile" and
        "Second Stone" (round-2 follow-up: buy the adjacent tile, then place
        the second stone thrower on its far corner)."""
        _title_w, _page, page_layout = self._pages["tutorial"]
        for key in [k for k in self._brush_buttons
                    if k[0] in ("tutorial_flute", "tutorial_stone",
                                "tutorial_unlock", "tutorial_stone_2")]:
            btn = self._brush_buttons.pop(key)
            self._brush_group.removeButton(btn)
            page_layout.removeWidget(btn)
            btn.deleteLater()
        idx = 0
        for slot in self._tutorial_flute_slots():
            self._add_brush_button(
                page_layout, ("tutorial_flute", slot), "First Flute", idx)
            idx += 1
        for slot in self._tutorial_stone_slots():
            self._add_brush_button(
                page_layout, ("tutorial_stone", slot), "First Stone", idx)
            idx += 1
        for slot in self._tutorial_unlock_slots():
            self._add_brush_button(
                page_layout, ("tutorial_unlock", slot), "Unlock Tile", idx)
            idx += 1
        for slot in self._tutorial_stone_2_slots():
            self._add_brush_button(
                page_layout, ("tutorial_stone_2", slot), "Second Stone", idx)
            idx += 1
        self.refresh_icons()

    def _rebuild_deco_types(self):
        """Repopulate the Type: combo from the registry, keeping the current
        type selected when it survived a reload."""
        previous = self._deco_type_combo.currentText()
        self._deco_type_combo.blockSignals(True)
        self._deco_type_combo.clear()
        self._deco_type_combo.addItems(self._deco_types())
        index = self._deco_type_combo.findText(previous)
        self._deco_type_combo.setCurrentIndex(max(index, 0))
        self._deco_type_combo.blockSignals(False)
        self._rebuild_deco()

    def _on_deco_type_changed(self, _index):
        self._rebuild_deco()
        if self._mode == "decoration":
            self._arm_first_of_mode()

    def _rebuild_deco(self):
        """One brush per VARIANT of the selected type; the brushes sit between
        the Type: combo and the two add-buttons."""
        _title_w, _page, page_layout = self._pages["decoration"]
        self._clear_page_brushes("deco", page_layout)
        slots = self._deco_slots()
        for i, slot in enumerate(slots):
            label = f"Var {i + 1}" if len(slots) > 1 else _title(slot)
            self._add_brush_button(page_layout, ("deco", slot), label, 1 + i)
        self.refresh_icons()

    def deco_type(self):
        """The deco type label the Type: combo currently shows ('' when none)."""
        return self._deco_type_combo.currentText()

    def select_deco_type(self, label):
        """Show one deco type's variants (after a '+ Add Prop' registry write).
        A no-op for an unknown/empty label."""
        index = self._deco_type_combo.findText(label) if label else -1
        if index >= 0:
            self._deco_type_combo.setCurrentIndex(index)

    def toggle_deco_flip(self):
        """Flip the Mirror Flip checkbox's checked state — the keybind's
        entry point (MainWindow can't reach `_deco_flip_box` directly)."""
        self._deco_flip_box.toggle()

    def _deco_type_of(self, slot):
        """The type label owning a deco variant slot ('' when unknown)."""
        for label in self._deco_types():
            if slot in self._deco_slots(label):
                return label
        return ""

    # -- legend (per open map) + icons ---------------------------------------

    def set_legend(self, legend):
        """Rebuild the gametiles zone buttons and the background level buttons
        from the open map's legend."""
        self._legend = legend
        self._rebuild_gametiles()
        self._rebuild_background()
        self._rebuild_tutorial()

    def reload_registry(self):
        """Re-read data/slots.json after a '+ Add Prop' / '+ Variant' / '+ Level'
        registry write so new slots resolve for icons + import."""
        self._registry = load_registry(self._data_dir)
        self._rebuild_gametiles()
        self._rebuild_deco_types()
        self._rebuild_tutorial()

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
            order = self._background_brush_order()
            if order:
                key, _label = order[0]
                if key[0] == "code":
                    self.arm_code(key[1])
                else:
                    self.arm_background_slot(key[1])
        elif self._mode == "tutorial":
            flutes = self._tutorial_flute_slots()
            if flutes:
                self.arm_tutorial_flute(flutes[0])
        elif self._mode == "spawn_reserve":
            self.arm_spawn_reserve()
        elif self._mode == "despawnable_spawn":
            self.arm_despawn()
        elif self._mode == "stage_zones":
            self.arm_stage()
        elif self._mode == "tile_conditions":
            names = list(self._condition_buttons)
            if names:
                self.arm_tile_condition(names[0])
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

    # -- keybind labels + shortcut dispatch (ED settings panel) --------------

    def set_tool_keybinds(self, mapping):
        """mapping: tool name -> single-key string. Relabels every tool
        button with its bound key in parentheses, e.g. 'Paint (B)'."""
        self._tool_keybinds = dict(mapping)
        for name, btn in self._tool_buttons.items():
            key = self._tool_keybinds.get(name, "")
            suffix = f" ({key})" if key else ""
            btn.setText(f"{name.title()}{suffix}")

    def set_brush_keybinds(self, keys):
        """keys: ordered list of up to 5 single-key strings — keys[i] labels
        the (i+1)-th Game-tiles brush button in _gametiles_brush_order().
        Only those first buttons get a "(key)" suffix; background/decoration
        brushes have no number-key shortcut."""
        self._brush_keybinds = list(keys)
        self._relabel_gametiles_brushes()

    def _relabel_gametiles_brushes(self):
        for i, (key, label) in enumerate(self._gametiles_brush_order()):
            btn = self._brush_buttons.get(key)
            if btn is None:
                continue
            bound = self._brush_keybinds[i] if i < len(self._brush_keybinds) else ""
            suffix = f" ({bound})" if bound else ""
            btn.setText(f"{label}{suffix}")

    def arm_gametiles_brush_by_index(self, index):
        """Number-key brush shortcuts (ED settings panel), Game-tiles mode
        only. A minimal map's legend can have fewer than 5 zone/base/camera/
        start_area slots — an out-of-range index is a no-op, not a crash."""
        if self._mode != "gametiles":
            return
        order = self._gametiles_brush_order()
        if not 0 <= index < len(order):
            return
        key, _label = order[index]
        btn = self._brush_buttons.get(key)
        if btn is not None:
            btn.click()

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

    def armed_camera(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "camera" and btn.isChecked():
                return value
        return None

    def armed_camera_limit_center(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "camera_limit_center" and btn.isChecked():
                return value
        return None

    def armed_start_area(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "start_area" and btn.isChecked():
                return value
        return None

    def armed_tutorial_flute(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "tutorial_flute" and btn.isChecked():
                return value
        return None

    def armed_tutorial_stone(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "tutorial_stone" and btn.isChecked():
                return value
        return None

    def armed_tutorial_unlock(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "tutorial_unlock" and btn.isChecked():
                return value
        return None

    def armed_tutorial_stone_2(self):
        for (kind, value), btn in self._brush_buttons.items():
            if kind == "tutorial_stone_2" and btn.isChecked():
                return value
        return None

    def armed_spawn_reserve(self):
        """True while the Spawnable Background brush is armed. Follows the
        armed_tutorial_stone pattern, but the brush has no SLOT to return (a
        mark is an overlay, not a sprite), so the answer is a bool."""
        return self._spawn_reserve_btn.isChecked()

    def reserve_number(self):
        """The stage number newly painted marks carry."""
        return self._reserve_spin.value()

    def set_reserve_number(self, n):
        """Write the spinbox (the viewport's eyedropper return path — mirrors
        code_picked -> arm_code). Out-of-range values clamp in QSpinBox."""
        self._reserve_spin.setValue(int(n))

    def armed_despawn(self):
        """True while the Despawnable Spawn brush is armed — the exact twin of
        armed_spawn_reserve (a bool, not a slot: a mark is an overlay, not a
        sprite)."""
        return self._despawn_btn.isChecked()

    def despawn_number(self):
        """The stage number newly painted despawn marks carry."""
        return self._despawn_spin.value()

    def set_despawn_number(self, n):
        """Write the spinbox (the viewport's eyedropper return path — mirrors
        set_reserve_number). Out-of-range values clamp in QSpinBox."""
        self._despawn_spin.setValue(int(n))

    def armed_stage(self):
        """True while the Stage Zones brush is armed — the exact twin of
        armed_despawn (a bool, not a slot: a mark is an overlay, not a
        sprite)."""
        return self._stage_btn.isChecked()

    def stage_number(self):
        """The stage number newly painted stage-zone marks carry."""
        return self._stage_spin.value()

    def set_stage_number(self, n):
        """Write the spinbox (the viewport's eyedropper return path — mirrors
        set_despawn_number). Out-of-range values clamp in QSpinBox."""
        self._stage_spin.setValue(int(n))

    def armed_tile_condition(self):
        """The condition NAME the armed brush paints, or None. Unlike the three
        overlay-mark brushes (which answer a bool — one brush each), this page
        has one button PER name, so the armed brush carries a value again, like
        armed_code."""
        for name, btn in self._condition_buttons.items():
            if btn.isChecked():
                return name
        return None

    def arm_code(self, code):
        btn = self._brush_buttons.get(("code", code))
        if btn is None:
            return
        btn.setChecked(True)
        self.code_armed.emit(code)

    def arm_deco(self, slot):
        """Arm one deco VARIANT. Only the selected type's variants have buttons,
        so switch the Type: combo to the slot's own type first — callers (the
        picker, '+ Variant', '+ Add Prop') name a slot, not a type."""
        self.select_deco_type(self._deco_type_of(slot))
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

    def arm_camera(self, slot):
        """Arm the Camera Start brush (paint = place/move the single startpoint,
        erase = remove it — viewport._tool_press). camera_armed tells the
        viewport to clear any stale armed code/deco/base."""
        btn = self._brush_buttons.get(("camera", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.camera_armed.emit(slot)

    def arm_camera_limit_center(self, slot):
        """Arm the Camera Limit Center brush (paint = place/move the single
        marker, erase = remove it — viewport._tool_press). Structurally the
        Camera Start brush's twin; the camera never STARTS here, the marker only
        anchors the core-balancing camera travel limit."""
        btn = self._brush_buttons.get(("camera_limit_center", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.camera_limit_center_armed.emit(slot)

    def arm_start_area(self, slot):
        """Arm the Starting Area brush (paint = place/move the single 2×2 area,
        erase = remove it — viewport._tool_press). start_area_armed tells the
        viewport to clear any stale armed code/deco/base/camera."""
        btn = self._brush_buttons.get(("start_area", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.start_area_armed.emit(slot)

    def arm_tutorial_flute(self, slot):
        """Arm the First Flute brush (paint = place/move the single "first
        flute" marker, erase = remove it — viewport._tool_press). Clears any
        other armed brush, INCLUDING the sibling First Stone brush."""
        btn = self._brush_buttons.get(("tutorial_flute", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.tutorial_flute_armed.emit(slot)

    def arm_tutorial_stone(self, slot):
        """Arm the First Stone brush (paint = place/move the single "first
        stone" marker, erase = remove it — viewport._tool_press). Clears any
        other armed brush, INCLUDING the sibling First Flute brush."""
        btn = self._brush_buttons.get(("tutorial_stone", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.tutorial_stone_armed.emit(slot)

    def arm_tutorial_unlock(self, slot):
        """Arm the Unlock Tile brush (paint = place/move the tile-buying
        topic's "tile to unlock" marker, erase = remove it —
        viewport._tool_press). Clears any other armed brush."""
        btn = self._brush_buttons.get(("tutorial_unlock", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.tutorial_unlock_armed.emit(slot)

    def arm_tutorial_stone_2(self, slot):
        """Arm the Second Stone brush (paint = place/move the tile-buying
        topic's second stone-thrower marker, erase = remove it —
        viewport._tool_press). Clears any other armed brush."""
        btn = self._brush_buttons.get(("tutorial_stone_2", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.tutorial_stone_2_armed.emit(slot)

    def arm_spawn_reserve(self):
        """Arm the Spawnable Background brush (paint = mark with the spinbox's
        number, erase = clear the mark). Shares the one exclusive brush group,
        so this disarms EVERY other brush, tutorial markers included."""
        self._spawn_reserve_btn.setChecked(True)
        self.spawn_reserve_armed.emit()

    def arm_despawn(self):
        """Arm the Despawnable Spawn brush (paint = mark with the spinbox's
        number, erase = clear the mark). Shares the one exclusive brush group,
        so this disarms EVERY other brush, the spawn-reserve mark included."""
        self._despawn_btn.setChecked(True)
        self.despawn_armed.emit()

    def arm_stage(self):
        """Arm the Stage Zones brush (paint = mark with the spinbox's number,
        erase = clear the mark). Shares the one exclusive brush group, so this
        disarms EVERY other brush, the other two overlay marks included."""
        self._stage_btn.setChecked(True)
        self.stage_armed.emit()

    def arm_tile_condition(self, name):
        """Arm ONE tile-condition brush (paint = force that condition on the
        cell, erase = clear the mark). Shares the one exclusive brush group, so
        this disarms every other brush including the sibling conditions. Also
        the viewport's eyedropper return path (condition_picked -> here),
        mirroring code_picked -> arm_code; an unknown name is a no-op."""
        btn = self._condition_buttons.get(name)
        if btn is None:
            return
        btn.setChecked(True)
        self.tile_condition_armed.emit(name)

    def arm_background_slot(self, slot):
        """Claim a legend code for a not-yet-bound registry background slot
        (MainWindow._on_background_slot_armed does the actual bind + rearms
        with the real code) — a no-op if this slot has no 'bgslot' button
        (already bound, or not a background slot at all)."""
        btn = self._brush_buttons.get(("bgslot", slot))
        if btn is None:
            return
        btn.setChecked(True)
        self.background_slot_armed.emit(slot)

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
        camera = self.armed_camera()
        if camera is not None:
            return camera
        camera_limit_center = self.armed_camera_limit_center()
        if camera_limit_center is not None:
            return camera_limit_center
        start_area = self.armed_start_area()
        if start_area is not None:
            return start_area
        tutorial_flute = self.armed_tutorial_flute()
        if tutorial_flute is not None:
            return tutorial_flute
        tutorial_stone = self.armed_tutorial_stone()
        if tutorial_stone is not None:
            return tutorial_stone
        tutorial_unlock = self.armed_tutorial_unlock()
        if tutorial_unlock is not None:
            return tutorial_unlock
        tutorial_stone_2 = self.armed_tutorial_stone_2()
        if tutorial_stone_2 is not None:
            return tutorial_stone_2
        code = self.armed_code()
        if code is not None and self._legend is not None:
            return self._legend[code]["slot"]
        return None

    def _on_import_clicked(self):
        slot = self._armed_slot()
        if slot is None:
            QMessageBox.information(
                self, "Import Spritesheet",
                "Arm a tile, background, hole, camera startpoint, starting "
                "area or deco brush first — the import targets whichever one "
                "is currently selected.")
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
