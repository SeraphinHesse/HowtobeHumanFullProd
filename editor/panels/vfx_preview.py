"""VfxPreviewPanel (ESV-4) — live procedural-VFX preview + control levers,
layered on top of the generic `vfx` balancing form (`editor/panels/
balancing.py`), never duplicating it.

**ED-22, one render path.** The preview renders through the engine
`Renderer` into its own offscreen `pygame.Surface`, converted once by
`viewport.surface_to_qimage` and blitted in `paintEvent` — QPainter never
draws a particle, a swatch, or anything else; it only blits the converted
frame (structurally copying `ViewportPanel.__init__`/`_build_store`/
`render_frame`, see `editor/panels/CLAUDE.md`). A second `Renderer` instance
is not a second render path — the ban is on a second QPainter-drawn surface
of game content, and everything drawn here goes out as the same
`HudRect`/`HudLines`/overlay primitives `VfxSystem` submits for the game.

**Not a fourth `ViewportPanel` mode.** ESV-2 owns `viewport.py` concurrently
(anchor handles + drag) — this is a dedicated panel so the two diffs never
touch the same file.

**One staging store.** This panel holds NO copy of `data/balancing/vfx.json`
and never calls `write_validated` itself: every read/write goes through the
live `BalancingPanel` it is handed via `set_balancing_panel` —
`staged_value(path)` / `stage_value(path, value)` — so a lever here and its
twin row in the generic form can never disagree, and Save stays the
balancing panel's one existing button (see `BalancingPanel`'s ESV-4 section).

**Determinism.** `self._rng` is a seeded `random.Random`, RESEEDED to the
same fixed seed on every `_emit()` call — two Emits with the same staged
params produce byte-identical particle batches (the guard that makes
spy-based param tests stable). `self._system` is rebuilt from scratch on
every `_emit()`, which is also how "any lever edit re-emits immediately and
clears the currently-live particles first" (phase-esv-4-vfx-preview.md
§1.4) falls out for free — there is no in-place mutation path, matching the
frozen param dataclasses upstream.

**Family list is data-driven** — the combo is built from the keys actually
present under `procedural` in the loaded doc, not a hardcoded list, so
ESV-3b's `beam`/`crater`/`lightning`/`announce` show up with zero edits
here. A family with no emitter binding (today: `floaters`) shows a
graceful-degrade placeholder (E-37) instead of raising.
"""
import math
import os
import random
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import (
    asset_import, domains, master_sheet_import, registry_ops, selection,
    vfx_params,
)
from editor.asset_import import import_idle_sheet
from editor.panels.balancing import (
    _NoWheelComboBox, _NoWheelDoubleSpinBox, _NoWheelSpinBox,
)
from editor.panels.master_sheet_dialog import MasterSheetDialog
from editor.panels.viewport import surface_to_qimage
from engine import data_io
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import HudLines, HudRect, HudSprite, Renderer, RenderItem
from engine.vfx import VfxSystem

REPO = Path(__file__).resolve().parents[2]
BACKGROUND = (24, 20, 32)
DEFAULT_SEED = 1234
DEFAULT_LOOP_INTERVAL = 1.0
# VA-4 appended "respawn": the payday revive is a fourth spark PRESET, not
# a new family, so it previews through this combo with no new preview path.
_PRESET_KEYS = ("place", "level1", "level2", "tier", "respawn")

# family -> [(label, staged-path-suffix relative to procedural/<family>/)]
# for the curated lever strip (phase-esv-4-vfx-preview.md §1.3's table).
# "{preset}" is substituted with the live preset combo's current value.
_LEVERS = {
    "spark": (("count", "presets/{preset}/count"),
              ("life", "presets/{preset}/life"),
              ("gravity", "gravity")),
    "death_burst": (("count", "count"), ("life", "life"),
                     ("gravity", "gravity")),
    "muzzle": (("count", "count"), ("count_strong", "count_strong"),
               ("life", "life"), ("life_strong", "life_strong"),
               ("smoke_chance", "smoke_chance")),
    "slash": (("life", "life"), ("lines_min", "lines_min"),
              ("lines_max", "lines_max")),
    "gold_highlight": (("life", "life"), ("fade_in", "fade_in"),
                        ("hold", "hold")),
    "splatter": (("alpha", "alpha"), ("radius_px", "radius_px"),
                 ("jitter", "jitter")),
}
# family -> the named-stop ramp key it carries (stop_0/stop_1/stop_2), if any.
_RAMP_KEY = {"spark": "ramp", "death_burst": "colors", "muzzle": "ramp",
             "slash": "colors"}
# family -> flat single-colour keys (no stop indirection).
_FLAT_COLOR_KEYS = {
    "gold_highlight": ("fill_color", "border_color"),
    "splatter": ("color",),
}
# Families this phase binds to an engine emitter (§1.3's table). Anything
# else present under `procedural` (today: `floaters`; tomorrow: ESV-3b's
# beam/crater/lightning/announce) degrades gracefully instead of raising.
_EMIT_FAMILIES = ("spark", "death_burst", "muzzle", "slash", "gold_highlight",
                   "splatter")
# feat-projectile-anchored-flight §3.1: `projectile` is a SUPPORTED preview
# (no "no preview yet" degrade) but is NOT a VfxSystem particle family — a
# projectile is a continuous flying object the game draws itself (like a
# beam), never a `VfxSystem.emit_*` burst — so it is deliberately kept OUT
# of `_EMIT_FAMILIES` and given its own small preview path instead
# (`_submit_projectile_preview`), driven by `render_frame`'s own frame timer.
_PROJECTILE_FAMILY = "projectile"
_CRATER_FAMILY = "crater"
_BEAM_FAMILY = "beam"
# VA-8: `highlights` is ONE `procedural` key holding SEVEN blocks, so it is
# one entry in the family combo with its own sub-combo choosing which
# highlight to preview — the `spark`/`_preset_combo` shape. Like crater/beam
# it is a continuous object the game draws itself, never a VfxSystem burst.
_HIGHLIGHT_FAMILY = "highlights"
#: The tile the highlight preview is drawn on. Middle-ish of the preview grid
#: so the diamond is fully visible at the default camera.
_HIGHLIGHT_TILE = (2, 2)
# vfx-projectile-spritesheets: crater/beam are the SAME shape as projectile —
# continuous/impact objects the game draws itself, not a VfxSystem burst — so
# they join it as SUPPORTED, non-degrading previews with their own small
# `_submit_crater_preview`/`_submit_beam_preview` paths.
_POINT_FX_FAMILIES = (_PROJECTILE_FAMILY, _CRATER_FAMILY, _BEAM_FAMILY,
                      _HIGHLIGHT_FAMILY)
# family -> the ONE fixed vfx_* slot its "Import Spritesheet…" button
# targets. `projectile` has no entry here — it swaps between two slots via
# `_shell_check`, resolved by `_current_import_slot()` instead. Every other
# procedural family (spark/muzzle/slash/hit/death/etc.) binds art per-EVENT
# through the `triggers` table's `sprite_slot` field, not a fixed family
# slot, so it has no button here — out of scope.
_POINT_FX_SLOTS = {_CRATER_FAMILY: "vfx_crater", _BEAM_FAMILY: "vfx_beam"}
#: A manifest `sheet` under this prefix is a MASTER spritesheet (D1) — one PNG
#: many slots cut their own row window out of. Tested against the entry's
#: STORED ref, never re-derived from the slot key (`details.py`'s M4 rule).
MASTER_PREFIX = "master/"

#: VA-7: the `variant_select.mode` vocabulary, mirrored from
#: `game/vfx_variants.py` because `editor/` may never import `game/` — the
#: same sanctioned duplication `editor/vfx_params.py` already is. A schema
#: test pins the two equal.
RANDOM_MODE = "random"
LEVEL_MODE = "level"
MISC_MODE = "misc"
VARIANT_MODES = (RANDOM_MODE, LEVEL_MODE, MISC_MODE)


class VfxPreviewPanel(QWidget):
    """The preview surface + its controls, in one widget so `editor/main.py`
    can add it to `right_stack` as a single page (index 3+)."""

    #: VA-7: a structural registry edit landed (add/remove/rename/variant), so
    #: the shell should re-read the registry into the selector tree and the
    #: other panels. `DetailsPanel.registry_changed`'s precedent.
    registry_changed = Signal()

    def __init__(self, data_dir=None, seed=DEFAULT_SEED, parent=None):
        super().__init__(parent)
        pygame.init()
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._coords = load_coordinate_system(self._data_dir)
        self._registry = load_registry(self._data_dir)
        self._manifest = load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json")
        self._assets = AssetStore(manifest=self._manifest, registry=self._registry,
                                  sprites_dir=self._data_dir / "sprites")
        self._renderer = Renderer(self._coords, self._assets)
        self._schema = data_io.load_json(domains.schema_path("vfx", self._data_dir))

        self._balancing = None            # set via set_balancing_panel()
        self._families = []               # cached procedural.* keys
        self._family = None
        self._preset = "place"
        self._strong = False
        self._large = False
        self._shell = False   # feat-projectile-anchored-flight §3.1
        self._seed = seed
        self._rng = random.Random(seed)
        self._system = None
        self._loop_clock = 0.0
        self._loop_interval = DEFAULT_LOOP_INTERVAL
        self._last_tick = None
        self._lever_widgets = {}
        self._color_buttons = {}

        self._surface = None
        self._qimage = None
        self.last_frame_ms = 0.0

        self._build_ui()
        self._resize_surface()

    # -- one-time widget construction ---------------------------------------

    def _build_ui(self):
        self._family_combo = QComboBox()
        self._family_combo.currentTextChanged.connect(self._on_family_changed)
        self._preset_combo = QComboBox()
        self._preset_combo.addItems(_PRESET_KEYS)
        self._preset_combo.currentTextChanged.connect(self._on_preset_changed)
        # VA-8: which of `highlights`' seven blocks to preview — the
        # _preset_combo shape, for the one family that is a dict of blocks
        # rather than a single block.
        self._highlight_combo = QComboBox()
        self._highlight_combo.currentTextChanged.connect(
            self._on_highlight_changed)
        self._strong_check = QCheckBox("strong")
        self._strong_check.toggled.connect(self._on_strong_toggled)
        self._large_check = QCheckBox("large")
        self._large_check.toggled.connect(self._on_large_toggled)
        # feat-projectile-anchored-flight §3.1: the stone/shell toggle,
        # mirroring the _strong_check/_large_check precedent — swaps the
        # `projectile` family's preview between the stone (every basic
        # defender) and shell (mortar) params/slot.
        self._shell_check = QCheckBox("shell")
        self._shell_check.toggled.connect(self._on_shell_toggled)
        # vfx-projectile-spritesheets: the working-space import affordance —
        # visible whenever the current family resolves to a fixed vfx_* slot
        # (`_current_import_slot()`), which is projectile/crater/beam only.
        self._import_btn = QPushButton("Import Spritesheet…")
        self._import_btn.clicked.connect(self._on_import_clicked)
        # M5: the master-sheet twin of the button above — same visibility rule
        # (a family with a fixed vfx_* slot), one PNG shared by many slots.
        self._master_btn = QPushButton("Use Master Spritesheet…")
        self._master_btn.setToolTip(
            "Cut this effect's art out of a MASTER spritesheet — one big PNG\n"
            "many characters and effects share. The sheet owns the frame size;\n"
            "this slot claims ONE row in it. Nothing is copied.")
        # Wrapped in a lambda like details.py's Use/Clear buttons: a bare
        # connect would put Qt's clicked(bool checked) into the first argument
        # (the panels-doc footgun that bit map_details' Delete).
        self._master_btn.clicked.connect(lambda: self._on_master_clicked())

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Family"))
        top_row.addWidget(self._family_combo)
        top_row.addWidget(self._preset_combo)
        top_row.addWidget(self._highlight_combo)
        top_row.addWidget(self._strong_check)
        top_row.addWidget(self._large_check)
        top_row.addWidget(self._shell_check)
        top_row.addWidget(self._import_btn)
        top_row.addWidget(self._master_btn)
        top_row.addStretch(1)

        # The row window (M5/D2). ONE spin, not M4's two: a vfx_* slot's entry
        # is a single `idle` row (`asset_import.import_idle_sheet`), so the
        # window is always exactly one row and a second spin could only ever
        # hold the value the first one already implies. ED-30 the other way
        # round — the unrepresentable state here is a window LONGER than one
        # row, and the way to make it unrepresentable is not to offer it.
        self._master_row = QWidget()
        master_layout = QHBoxLayout(self._master_row)
        master_layout.setContentsMargins(0, 0, 0, 0)
        master_layout.addWidget(QLabel("Master sheet row"))
        self._row_spin = _NoWheelSpinBox()
        self._row_spin.setRange(0, 255)   # asset_manifest.schema.json row_start
        self._row_spin.editingFinished.connect(self._on_master_row_changed)
        master_layout.addWidget(self._row_spin)
        self._master_label = QLabel("")
        master_layout.addWidget(self._master_label)
        master_layout.addStretch(1)

        self._loop_check = QCheckBox("Loop")
        self._loop_check.setChecked(True)
        self._interval_spin = _NoWheelDoubleSpinBox()
        self._interval_spin.setRange(0.1, 10.0)
        self._interval_spin.setSingleStep(0.1)
        self._interval_spin.setValue(DEFAULT_LOOP_INTERVAL)
        self._interval_spin.valueChanged.connect(self._on_interval_changed)
        self._emit_btn = QPushButton("Emit")
        self._emit_btn.clicked.connect(lambda: self._emit())

        loop_row = QHBoxLayout()
        loop_row.addWidget(self._loop_check)
        loop_row.addWidget(QLabel("interval (s)"))
        loop_row.addWidget(self._interval_spin)
        loop_row.addWidget(self._emit_btn)
        loop_row.addStretch(1)

        self._degrade_label = QLabel(
            "select the vfx domain to preview an effect")

        self._lever_form = QFormLayout()
        lever_box = QWidget()
        lever_box.setLayout(self._lever_form)

        self._ramp_row = QHBoxLayout()
        ramp_box = QWidget()
        ramp_box.setLayout(self._ramp_row)

        roster_row, binding_row = self._build_roster_ui()

        controls = QVBoxLayout()
        controls.addLayout(roster_row)
        controls.addLayout(binding_row)
        controls.addLayout(top_row)
        controls.addWidget(self._master_row)
        controls.addLayout(loop_row)
        controls.addWidget(self._degrade_label)
        controls.addWidget(lever_box)
        controls.addWidget(ramp_box)
        controls.addStretch(1)
        controls_widget = QWidget()
        controls_widget.setLayout(controls)
        # Two more rows than before VA-7, so the cap rises with them.
        controls_widget.setMaximumHeight(300)

        self._surface_widget = _PreviewSurface(self)
        self._surface_widget.setMinimumHeight(200)

        outer = QVBoxLayout(self)
        outer.addWidget(self._surface_widget, 1)
        outer.addWidget(controls_widget)
        # No family is selected until `refresh_families` runs, so both
        # slot-scoped affordances start hidden rather than flashing.
        self._refresh_import_btn()
        self.refresh_roster()
        self.refresh_events()

    # -- balancing-panel plumbing (§2.3): one staging store, no second writer

    def set_balancing_panel(self, panel):
        """`panel` is the live `BalancingPanel` — this panel never loads,
        stages, or writes `vfx.json` itself, only reads/writes through
        `panel.staged_value`/`panel.stage_value`."""
        self._balancing = panel
        self.refresh_families()

    def on_balancing_value_staged(self, path, value):
        """`BalancingPanel.value_staged` fires for EVERY staged edit in
        every domain (generic-form typing, another domain entirely, or this
        panel's own `stage_value` calls) — filter to the vfx doc and re-read
        levers/re-emit only when it is actually relevant."""
        if self._balancing is None or self._balancing.domain != "vfx":
            return
        if not path.startswith("procedural/"):
            return
        prefix = f"procedural/{self._family}/"
        if self._family is None or not path.startswith(prefix):
            # A different family changed, or the family LIST itself may
            # have (an array/object add under `procedural`) — cheap to just
            # re-check.
            self.refresh_families()
            return
        widget = self._lever_widgets.get(path)
        if widget is not None:
            widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(False)
        button = self._color_buttons.get(path)
        if button is not None and isinstance(value, (list, tuple)):
            self._paint_swatch(button, value)
        self._emit()

    def refresh_families(self):
        """Rebuild the family combo from the keys currently under
        `procedural` — data-driven (§1.3), so ESV-3b's new families appear
        with zero ESV-4 edits."""
        if self._balancing is None or self._balancing.domain != "vfx":
            return
        proc = self._balancing.staged_value("procedural")
        families = sorted(proc.keys())
        if families == self._families and self._family is not None:
            return
        self._families = families
        self._family_combo.blockSignals(True)
        self._family_combo.clear()
        self._family_combo.addItems(families)
        self._family_combo.blockSignals(False)
        if not families:
            return
        target = self._family if self._family in families else families[0]
        self._family_combo.setCurrentText(target)
        self._set_family(target)

    # -- family / preset / variant selection ---------------------------------

    def _on_family_changed(self, name):
        if name:
            self._set_family(name)

    def _set_family(self, name):
        self._family = name
        supported = name in _EMIT_FAMILIES or name in _POINT_FX_FAMILIES
        self._preset_combo.setVisible(name == "spark")
        self._strong_check.setVisible(name == "muzzle")
        self._large_check.setVisible(name == "slash")
        self._shell_check.setVisible(name == _PROJECTILE_FAMILY)
        self._highlight_combo.setVisible(name == _HIGHLIGHT_FAMILY)
        if name == _HIGHLIGHT_FAMILY:
            self._refresh_highlight_combo()
        self._refresh_import_btn()
        self._degrade_label.setText(
            "" if supported else f"no preview for {name!r} yet")
        self._degrade_label.setVisible(not supported)
        self._system = None
        self._rebuild_levers()
        self._rebuild_colors()
        if name in _EMIT_FAMILIES:
            self._emit()
        elif name in _POINT_FX_FAMILIES:
            # Not a VfxSystem family (no self._system to rebuild/reseed) —
            # just restart the flight/loop clock, mirroring _emit()'s own
            # self._loop_clock reset for every other family switch.
            self._loop_clock = 0.0

    def _current_import_slot(self):
        """The fixed ``vfx_*`` slot the current family's Import button
        targets, or ``None`` for a family with no single fixed slot (every
        family but projectile/crater/beam binds art per-event through the
        `triggers` table's `sprite_slot` field instead)."""
        if self._family == _PROJECTILE_FAMILY:
            return "vfx_shell" if self._shell else "vfx_projectile"
        if self._family == _HIGHLIGHT_FAMILY:
            # VA-5 gave each highlight its own vfx_<name> slot, so the family
            # DOES resolve to one fixed slot — it just depends on the
            # sub-combo rather than being a constant.
            return self._highlight_slot()
        fixed = _POINT_FX_SLOTS.get(self._family)
        if fixed is not None:
            return fixed
        # VA-7 follow-up: every OTHER family binds art per-EVENT, so it has no
        # slot of its own — which left an effect added through the roster with
        # a slot and no way to put art on it. The roster's selected Variant is
        # that answer: it is the designer's explicit "this is the art I am
        # working on". A family with a FIXED slot still wins above, so
        # projectile/shell, crater and beam are unchanged.
        return self.current_slot()

    def _refresh_import_btn(self):
        has_slot = self._current_import_slot() is not None
        self._import_btn.setVisible(has_slot)
        self._master_btn.setVisible(has_slot)
        self._refresh_master_row()

    # -- master spritesheets (M5, D1/D2/D3) ---------------------------------

    def _slot_entry(self, slot=None):
        """The current fixed slot's manifest entry, or None. Read fresh from
        disk on every call: this panel holds NO staged copy of the manifest
        (the one-staging-store rule applies to `vfx.json`; the manifest has no
        staging layer here at all — `import_idle_sheet` writes straight
        through, and so does everything below)."""
        slot = slot or self._current_import_slot()
        if slot is None:
            return None
        entry = asset_import.load_manifest_doc(self._data_dir)["entries"].get(slot)
        return entry if isinstance(entry, dict) else None

    def _slot_master_ref(self):
        """The MASTER sheet ref the current slot cuts, or None. Tests the
        entry's STORED `sheet`, never a ref re-derived from the slot key
        (`master_sheet_import.master_ref`'s docstring)."""
        ref = (self._slot_entry() or {}).get("sheet")
        return ref if isinstance(ref, str) and ref.startswith(MASTER_PREFIX) \
            else None

    def _resolve_master_sheet(self, sheet):
        """A `MasterSheet` from the dataclass, its id, or its stored ref —
        `details.py::_resolve_master_sheet`, unchanged."""
        if hasattr(sheet, "ref"):
            return sheet
        key = str(sheet)
        for candidate in master_sheet_import.master_sheets(self._data_dir):
            if key in (candidate.sheet_id, candidate.ref):
                return candidate
        return None

    def _refresh_master_row(self):
        """Show and fill the row spin while the current slot cuts a master
        sheet; hide it otherwise. The spin's ceiling is the sheet's real last
        row, so a window off the bottom of the PNG is unrepresentable."""
        ref = self._slot_master_ref()
        self._master_row.setVisible(ref is not None)
        if ref is None:
            return
        sheet = self._resolve_master_sheet(ref)
        entry = self._slot_entry() or {}
        _cols, rows = sheet.grid() if sheet is not None else (0, 0)
        self._row_spin.blockSignals(True)
        self._row_spin.setRange(0, max(0, rows - 1))
        self._row_spin.setValue(int(entry.get("row_start", 0)))
        self._row_spin.blockSignals(False)
        name = sheet.display_name if sheet is not None else ref
        self._master_label.setText(f"of “{name}” ({ref})")

    def use_master_sheet(self, sheet, row=None):
        """LINK the current family's fixed `vfx_*` slot to a MASTER
        spritesheet, cutting ONE row out of it (M5, D2/D3) — the model half of
        "Use Master Spritesheet…", so no test ever has to `exec()` the modal.

        Takes a `master_sheet_import.MasterSheet`, its id, or its stored ref.
        Copies NO bytes: the entry's `sheet` is the registry entry's STORED
        `file`, verbatim.

        The SHEET owns the grid (D3) — `frame_w`/`frame_h` come off the
        registry entry, NOT `registry.frame_size(slot)`, and **`slots.json` is
        not touched**: a master sheet's grid is not a per-slot override. The
        row shape is `import_idle_sheet`'s exactly (one `idle` row, frames =
        the sheet's columns), because these slots only ever animate `idle`.

        `row` defaults to whatever this slot already claims on this same sheet,
        else 0; `row_start` is OMITTED at 0, so a top-of-sheet link stays
        byte-identical to a pre-window entry (the `slice`/`tint_overlay`
        convention). Returns (cols, sheet_rows), or None when there is no fixed
        slot or the sheet is unknown/missing. Writes immediately — this panel
        has no Save button, exactly like its Import button."""
        slot = self._current_import_slot()
        if slot is None:
            return None
        sheet = self._resolve_master_sheet(sheet)
        if sheet is None or not sheet.path.exists():
            return None
        cols, sheet_rows = sheet.grid()
        if cols < 1 or sheet_rows < 1:
            return None
        if row is None:
            previous = self._slot_entry(slot) or {}
            row = (int(previous.get("row_start", 0))
                   if previous.get("sheet") == sheet.ref else 0)
        row = max(0, min(int(row), sheet_rows - 1))

        entry = {
            "sheet": sheet.ref,
            "frame_w": sheet.frame_w,
            "frame_h": sheet.frame_h,
            "offset_x": 0,
            "offset_y": 0,
            "rows": [{
                "animation": "idle",
                "frames": cols,
                "fps": 8,
                "hidden": [],
                "loop_start": 0,
                "loop_end": 0,
                "loop_count": 1,
            }],
        }
        if row:
            entry["row_start"] = row
        doc = asset_import.load_manifest_doc(self._data_dir)
        doc["entries"][slot] = entry
        asset_import.write_manifest_doc(self._data_dir, doc)
        self.reload_assets()          # ED-42 — no editor restart
        self._refresh_master_row()
        return cols, sheet_rows

    def _on_master_row_changed(self):
        """Re-point the window at another row of the SAME sheet. Rewrites only
        `row_start` on the existing entry — never the whole entry — so any row
        edit made elsewhere (DetailsPanel) survives moving the window."""
        ref = self._slot_master_ref()
        if ref is None:
            return
        slot = self._current_import_slot()
        doc = asset_import.load_manifest_doc(self._data_dir)
        entry = doc["entries"][slot]
        row = self._row_spin.value()
        if int(entry.get("row_start", 0)) == row:
            return
        if row:
            entry["row_start"] = row
        else:
            entry.pop("row_start", None)   # omitted at 0, like every other path
        asset_import.write_manifest_doc(self._data_dir, doc)
        self.reload_assets()

    def _on_master_clicked(self):
        """Open the master-sheet library for this family's fixed slot.
        Construction is split from display (the sheet-picker rule): tests drive
        `use_master_sheet` directly and never `exec()` a modal."""
        if self._current_import_slot() is None:
            return
        dialog = MasterSheetDialog(self._data_dir, parent=self)
        ref = self._slot_master_ref()
        if ref is not None:
            # Open on the sheet this slot already cuts — matched on the STORED
            # ref, never on an id re-derived from it.
            for sheet in dialog.visible_sheets():
                if sheet.ref == ref:
                    dialog.select_sheet(sheet.sheet_id)
                    break
        if dialog.exec() == QDialog.DialogCode.Accepted:
            sheet = dialog.chosen_sheet()
            if sheet is not None:
                self.use_master_sheet(sheet)

    def _on_import_clicked(self):
        """Import a PNG into the current family's fixed slot via the SAME
        Qt-free single-idle-row helper the palette's importer uses
        (`editor.asset_import.import_idle_sheet`), then reload the panel's
        own AssetStore so the preview switches from procedural to sprite
        immediately (ED-42 — no restart)."""
        slot = self._current_import_slot()
        if slot is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Spritesheet", "", "Images (*.png)")
        if not path:
            return
        import_idle_sheet(self._data_dir, self._registry, slot, Path(path))
        self.reload_assets()
        # The slot now owns its own `imported/` PNG, so any master link (and
        # its row window) is gone — `import_idle_sheet` writes a fresh entry.
        self._refresh_master_row()

    def reload_assets(self):
        """Re-read the manifest from disk after an import (ED-42, the
        `viewport.reload_assets` pattern) so a freshly imported spritesheet
        resolves without an editor restart. Camera state lives in
        `self._coords`, untouched."""
        self._manifest = load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json")
        self._assets = AssetStore(manifest=self._manifest, registry=self._registry,
                                  sprites_dir=self._data_dir / "sprites")
        self._renderer = Renderer(self._coords, self._assets)

    def _on_preset_changed(self, name):
        if not name:
            return
        self._preset = name
        self._rebuild_levers()
        self._emit()

    def _on_strong_toggled(self, checked):
        self._strong = bool(checked)
        self._emit()

    def _on_large_toggled(self, checked):
        self._large = bool(checked)
        self._emit()

    def _on_shell_toggled(self, checked):
        self._shell = bool(checked)
        # stone <-> shell swaps which fixed slot the two buttons target, so the
        # row window has to follow: the two slots may cut different sheets.
        self._refresh_master_row()

    def _on_interval_changed(self, value):
        self._loop_interval = float(value)

    # -- schema lookups for the lever spin ranges (D-12) ---------------------

    def _deref(self, node):
        while "$ref" in node:
            ref = node["$ref"]
            node = self._schema["$defs"][ref.removeprefix("#/$defs/")]
        return node

    def _leaf_schema(self, family, suffix):
        node = self._deref(
            self._schema["properties"]["procedural"]["properties"][family])
        segments = suffix.format(preset=self._preset).split("/")
        for seg in segments[:-1]:
            node = self._deref(node["properties"][seg])
        return self._deref(node["properties"][segments[-1]])

    # -- lever strip (curated numeric widgets, imported from balancing.py) --

    def _full_path(self, suffix):
        return f"procedural/{self._family}/{suffix.format(preset=self._preset)}"

    def _rebuild_levers(self):
        while self._lever_form.rowCount():
            self._lever_form.removeRow(0)
        self._lever_widgets = {}
        if self._balancing is None or self._family not in _LEVERS:
            return
        for label, suffix in _LEVERS[self._family]:
            path = self._full_path(suffix)
            try:
                value = self._balancing.staged_value(path)
            except (KeyError, IndexError, TypeError):
                continue
            prop = self._leaf_schema(self._family, suffix)
            widget = self._make_lever_widget(prop, value)
            widget.valueChanged.connect(
                lambda v, p=path: self._on_lever_changed(p, v))
            self._lever_form.addRow(label, widget)
            self._lever_widgets[path] = widget

    def _make_lever_widget(self, prop, value):
        if prop.get("type") == "integer":
            widget = _NoWheelSpinBox()
            widget.setRange(int(prop.get("minimum", -(2**31))),
                            int(prop.get("maximum", 2**31 - 1)))
            widget.setValue(value)
        else:
            widget = _NoWheelDoubleSpinBox()
            widget.setRange(float(prop.get("minimum", -1e9)),
                            float(prop.get("maximum", 1e9)))
            widget.setDecimals(4)
            widget.setSingleStep(0.1)
            widget.setValue(value)
        widget.setToolTip(prop.get("description", ""))
        return widget

    def _on_lever_changed(self, path, value):
        if self._balancing is None:
            return
        self._balancing.stage_value(path, value)
        self._emit()

    # -- colour swatches (§2.4): named-stop ramps + flat colours ------------

    def _rebuild_colors(self):
        while self._ramp_row.count():
            item = self._ramp_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._color_buttons = {}
        if self._balancing is None or self._family is None:
            return
        proc = self._balancing.staged_value("procedural")
        fam = proc.get(self._family)
        if fam is None:
            return
        ramp_key = _RAMP_KEY.get(self._family)
        if ramp_key is not None and ramp_key in fam:
            stops = fam[ramp_key]
            for stop in ("stop_0", "stop_1", "stop_2"):
                if stop in stops:
                    self._add_color_button(
                        stop, f"procedural/{self._family}/{ramp_key}/{stop}",
                        stops[stop])
        for key in _FLAT_COLOR_KEYS.get(self._family, ()):
            if key in fam:
                self._add_color_button(
                    key, f"procedural/{self._family}/{key}", fam[key])

    def _add_color_button(self, label, path, rgb):
        button = QPushButton(label)
        self._paint_swatch(button, rgb)
        button.clicked.connect(
            lambda _c=False, p=path, b=button: self._on_color_clicked(p, b))
        self._ramp_row.addWidget(button)
        self._color_buttons[path] = button

    def _paint_swatch(self, button, rgb):
        r, g, b = rgb[0], rgb[1], rgb[2]
        button.setStyleSheet(f"background-color: rgb({r},{g},{b});")

    def _on_color_clicked(self, path, button):
        current = self._balancing.staged_value(path)
        base = QColor(current[0], current[1], current[2])
        chosen = QColorDialog.getColor(base, self, "Pick a color")
        if not chosen.isValid():
            return
        rgb = [chosen.red(), chosen.green(), chosen.blue()]
        self._balancing.stage_value(path, rgb)
        self._paint_swatch(button, rgb)
        self._emit()

    # -- the ONE emit seam: a test spies on VfxSystem or self._system -------

    def _emit(self):
        """Rebuild a fresh `VfxSystem` from the currently staged params and
        fire exactly one emit for the selected family/variant. A fresh
        system (never mutated in place) is what makes "any lever edit
        clears the currently-live particles first" (§1.4) fall out for
        free. Reseeding to the SAME fixed seed every call is the
        determinism contract (§2.6/§4 test 4)."""
        if self._balancing is None or self._family not in _EMIT_FAMILIES:
            return
        proc = self._balancing.staged_value("procedural")
        if self._family not in proc:
            return
        self._rng.seed(self._seed)
        spark_presets, params = vfx_params.params_from_balance(proc)
        self._system = VfxSystem(params, rng=self._rng)
        g = self._coords.geometry
        col, row = g.map_cols // 2, g.map_rows // 2
        if self._family == "spark":
            preset = spark_presets.get(self._preset, spark_presets.get("place"))
            self._system.emit_burst(preset, col, row)
        elif self._family == "death_burst":
            self._system.emit_shards(col, row)
        elif self._family == "muzzle":
            self._system.emit_muzzle(col, row, strong=self._strong)
        elif self._family == "slash":
            self._system.emit_slash(col, row, large=self._large)
        elif self._family == "gold_highlight":
            self._system.emit_gold(col, row)
        elif self._family == "splatter":
            self._system.add_splatters([(col, row)])
        self._loop_clock = 0.0

    # -- the `projectile` family (§3.1): not a VfxSystem particle emitter ---

    def _submit_projectile_preview(self, dt):
        """A dot/sprite flying repeatedly between two fixed world points,
        driven by `procedural.projectile` (feat-projectile-anchored-flight
        §3.1) — the SAME `editor/vfx_params.py projectile_params` the panel
        already builds for every other family's `VfxParams` construction.
        `_shell_check` swaps stone<->shell params/slot, mirroring the
        `_strong_check`/`_large_check` precedent. Uses `vfx_projectile`/
        `vfx_shell` art when imported, else the dot — the SAME
        `assets.animation_total_ms(slot, "idle") is not None` "has art"
        signal the game reads, so the two can never disagree about
        "imported". No RNG involved (a straight-line flight), so nothing
        here needs reseeding — only the flight clock restarts on a family
        switch (`_set_family`), mirroring `_emit()`'s own reset."""
        if self._balancing is None:
            return
        proc = self._balancing.staged_value("procedural")
        if _PROJECTILE_FAMILY not in proc:
            return
        pr = vfx_params.projectile_params(proc[_PROJECTILE_FAMILY])
        if self._loop_check.isChecked():
            self._loop_clock += dt
        interval = max(self._loop_interval, 0.001)
        progress = (self._loop_clock % interval) / interval

        g = self._coords.geometry
        col, row = g.map_cols // 2, g.map_rows // 2
        start = (col - 1.5, row)
        end = (col + 1.5, row)
        zoom = self._coords.camera.zoom
        sx0, sy0 = self._coords.world_to_screen(*start)
        sx1, sy1 = self._coords.world_to_screen(*end)
        sx = sx0 + (sx1 - sx0) * progress
        sy = sy0 + (sy1 - sy0) * progress
        lift = g.tile_h * zoom * pr.lift_frac

        shell = self._shell
        slot = "vfx_shell" if shell else "vfx_projectile"
        color = pr.shell_color if shell else pr.stone_color
        size = max(2, int((pr.shell_size if shell else pr.stone_size) * zoom))
        dest = (int(sx - size / 2), int(sy - lift - size / 2))
        has_art = self._assets.animation_total_ms(slot, "idle") is not None
        if has_art:
            self._renderer.submit_hud(HudSprite(slot, dest, (size, size)))
        else:
            self._renderer.submit_hud(HudRect(
                (dest[0], dest[1], size, size), color, border_radius=size // 2))

    # -- the `crater`/`beam` families (vfx-projectile-spritesheets): not
    # VfxSystem particle emitters either, same shape as `projectile` above --

    @staticmethod
    def _ring_points(cx, cy, r, segments):
        """A regular polygon's screen points around `(cx, cy)` — a local,
        editor-only reimplementation of `game/ui/effects.py`'s private
        `_polygon_ring` helper (`editor/` may never import `game/ui`, the
        same duplication `editor/vfx_params.py`'s module docstring already
        carries). Used only for the crater's no-art preview outline."""
        segments = max(3, int(segments))
        return tuple(
            (cx + r * math.cos(2 * math.pi * i / segments),
             cy + r * math.sin(2 * math.pi * i / segments))
            for i in range(segments))

    def _submit_crater_preview(self, dt):
        """A designer-imported `vfx_crater` sheet previews as a looping
        sprite at the impact point (`animation="idle"`, sized off the
        manifest's own frame size); with no art, a rough polygon-ring
        outline approximating the procedural `Crater` mark (color/segments
        from `procedural.crater` via `editor/vfx_params.py::crater_params`,
        the same adapter every other family already uses) — a simplified
        stand-in for the real alpha-filled, radius-scaled ring
        `game/ui/effects.py::submit_craters` draws in-game, not a pixel
        match. Loop timing mirrors `_submit_projectile_preview`."""
        if self._balancing is None:
            return
        proc = self._balancing.staged_value("procedural")
        if _CRATER_FAMILY not in proc:
            return
        cp = vfx_params.crater_params(proc[_CRATER_FAMILY])
        if self._loop_check.isChecked():
            self._loop_clock += dt
        g = self._coords.geometry
        col, row = g.map_cols // 2, g.map_rows // 2
        cx, cy = self._coords.world_to_screen(col + 0.5, row + 0.5)
        zoom = self._coords.camera.zoom
        has_art = self._assets.animation_total_ms("vfx_crater", "idle") is not None
        if has_art:
            fw, fh = self._assets.frame_size("vfx_crater")
            size = (max(1, int(fw * zoom)), max(1, int(fh * zoom)))
            dest = (int(cx - size[0] / 2), int(cy - size[1] / 2))
            interval = max(self._loop_interval, 0.001)
            anim_ms = int((self._loop_clock % interval) * 1000.0)
            self._renderer.submit_hud(HudSprite(
                "vfx_crater", dest, size, animation="idle",
                anim_time_ms=anim_ms))
            return
        r = g.tile_h * zoom * 1.5
        points = self._ring_points(cx, cy, r, cp.segments)
        self._renderer.submit_hud(HudLines(points, cp.color, closed=True))

    def _submit_beam_preview(self, dt):
        """A designer-imported `vfx_beam` sheet previews as a looping sprite
        at the target point — the SAME fixed-sprite-at-a-point shape
        `game/ui/effects.py::submit_beams` draws in-game (never a stretched/
        rotated beam texture — `HudSprite` has no rotation support); with no
        art, a plain line from origin to target using `procedural.beam`'s
        first ramp colour. Loop timing mirrors `_submit_projectile_preview`."""
        if self._balancing is None:
            return
        proc = self._balancing.staged_value("procedural")
        if _BEAM_FAMILY not in proc:
            return
        bp = vfx_params.beam_params(proc[_BEAM_FAMILY])
        if self._loop_check.isChecked():
            self._loop_clock += dt
        g = self._coords.geometry
        col, row = g.map_cols // 2, g.map_rows // 2
        ox, oy = self._coords.world_to_screen(col - 1.5, row)
        tx, ty = self._coords.world_to_screen(col + 1.5, row)
        zoom = self._coords.camera.zoom
        has_art = self._assets.animation_total_ms("vfx_beam", "idle") is not None
        if has_art:
            fw, fh = self._assets.frame_size("vfx_beam")
            size = (max(1, int(fw * zoom)), max(1, int(fh * zoom)))
            dest = (int(tx - size[0] / 2), int(ty - size[1] / 2))
            interval = max(self._loop_interval, 0.001)
            anim_ms = int((self._loop_clock % interval) * 1000.0)
            self._renderer.submit_hud(HudSprite(
                "vfx_beam", dest, size, animation="idle",
                anim_time_ms=anim_ms))
            return
        self._renderer.submit_hud(HudLines(
            ((int(ox), int(oy)), (int(tx), int(ty))),
            bp.colors[0], width=bp.width_base))

    # -- surface lifecycle, sized to the surface sub-widget ------------------

    def _resize_surface(self):
        w = max(1, self._surface_widget.width())
        h = max(1, self._surface_widget.height())
        self._surface = pygame.Surface((w, h))
        g = self._coords.geometry
        self._coords.center_on(g.map_cols // 2, g.map_rows // 2, w, h)

    # -- frame drive: main.py's QTimer calls this once per tick, gated on
    # the panel actually being the visible right_stack page --------------

    def render_frame(self):
        self.refresh_families()
        t0 = time.perf_counter()
        self._surface.fill(BACKGROUND)
        g = self._coords.geometry
        for row in range(g.map_rows):
            for col in range(g.map_cols):
                self._renderer.submit(
                    RenderItem("ground_tile", (col, row), layer="ground"))
        dt = (t0 - self._last_tick) if self._last_tick is not None else 0.0
        self._last_tick = t0
        if self._system is not None:
            self._system.update(dt)
            if self._loop_check.isChecked() and self._family in _EMIT_FAMILIES:
                self._loop_clock += dt
                if self._loop_clock >= self._loop_interval:
                    self._emit()
            self._system.submit_splatters(self._renderer, self._coords)
            self._system.submit_gold_highlights(self._renderer)
            self._system.submit_hud(self._renderer, self._coords)
        elif self._family == _PROJECTILE_FAMILY:
            self._submit_projectile_preview(dt)
        elif self._family == _CRATER_FAMILY:
            self._submit_crater_preview(dt)
        elif self._family == _BEAM_FAMILY:
            self._submit_beam_preview(dt)
        elif self._family == _HIGHLIGHT_FAMILY:
            self._submit_highlight_preview(dt)
        self._renderer.flush(self._surface)
        self._qimage = surface_to_qimage(self._surface)
        self._surface_widget.update()
        self.last_frame_ms = (time.perf_counter() - t0) * 1000.0



    # -- the `highlights` family (VA-8) ------------------------------------

    def _refresh_highlight_combo(self):
        """Populate the sub-combo from the staged doc, so a highlight added to
        `procedural.highlights` shows up without an editor change — the same
        data-driven rule `refresh_families` follows for the family combo
        itself."""
        names = sorted(self._staged_highlights())
        current = self._highlight_combo.currentText()
        self._highlight_combo.blockSignals(True)
        self._highlight_combo.clear()
        self._highlight_combo.addItems(names)
        if current in names:
            self._highlight_combo.setCurrentText(current)
        self._highlight_combo.blockSignals(False)

    def _staged_highlights(self):
        if self._balancing is None:
            return {}
        proc = self._balancing.staged_value("procedural") or {}
        return proc.get(_HIGHLIGHT_FAMILY) or {}

    def _on_highlight_changed(self, _name):
        self._refresh_import_btn()
        self._rebuild_levers()
        self._rebuild_colors()

    def current_highlight(self):
        return self._highlight_combo.currentText() or None

    def _highlight_slot(self):
        """The slot the selected highlight actually draws.

        Reads the BOUND `triggers.<name>.sprite_slot` first and only falls
        back to the `vfx_<name>` convention when nothing is bound. Resolving
        by convention alone was a real bug: a designer who bound art to a
        highlight saw the preview keep drawing the procedural diamond, because
        the preview was looking at a different slot than the game was. A
        preview that does not follow the binding is worse than no preview —
        it actively misreports."""
        name = self.current_highlight()
        if not name:
            return None
        bound = None
        if self._balancing is not None and self._balancing.domain == "vfx":
            bound = self._balancing.staged_value(
                f"triggers/{name}/sprite_slot")
        return bound or f"vfx_{name}"

    def _submit_highlight_preview(self, dt):
        """Draw the selected tile highlight exactly as the game draws it: the
        bound `vfx_<name>` sheet when it has art, else the world-space diamond
        in the staged colour/outline/fill.

        The diamond is four world points through `submit_world_fill` — the
        SAME primitive `game/ui/widgets.py::submit_tile_diamond` uses — rather
        than a call into that module, because `editor/` may never import
        `game/`. The polygon is trivial enough that duplicating it costs
        nothing; what matters is that both go through the one depth-sorted
        world-fill path, so the preview cannot drift from the game in the way
        that actually matters (which primitive, at which depth).

        `dt` is accepted for signature parity with the other point-FX preview
        paths; a highlight is a static outline with no clock of its own.
        """
        name = self.current_highlight()
        if not name:
            return
        params = self._staged_highlights().get(name)
        if not params:
            return
        col, row = _HIGHLIGHT_TILE
        slot = self._highlight_slot()
        if slot and self._assets.animation_total_ms(slot, "idle") is not None:
            self._renderer.submit(
                RenderItem(slot, (col, row), animation="idle",
                           anim_time_ms=int(self._loop_clock * 1000)))
            self._loop_clock += dt
            return
        color = tuple(params.get("color") or (255, 255, 255))
        width = int(params.get("border_width", 2))
        alpha = int(params.get("fill_alpha", 0))
        points = [(col, row), (col + 1, row),
                  (col + 1, row + 1), (col, row + 1)]
        self._renderer.submit_world_fill(
            points, world_pos=(col, row),
            color=(color + (alpha,)) if alpha else None,
            border=color, border_width=width)

    # ======================================================================
    # The roster + binding strip (VfxAuthoringPLAN VA-7)
    # ======================================================================
    # Everything above this line tunes an effect that already exists. This
    # section is where the designer changes WHICH effects exist, what art they
    # carry, and how one is chosen at play time.
    #
    # Two contracts hold throughout:
    #
    # * Registry edits (add/remove/rename/variant) write `slots.json`
    #   IMMEDIATELY through `editor/registry_ops.py`, like every other registry
    #   op in the editor — they are structural, not staged values.
    # * Everything else (a binding, a mode, a misc key, the layering bool) is a
    #   BALANCING value and goes through `self._balancing.stage_value`, so this
    #   panel keeps its no-second-writer contract and Save stays the balancing
    #   panel's one button.
    #
    # Every modal has a model half that takes its answer as an argument, so no
    # test ever has to `exec()` a dialog (`main.py`'s `_on_add_button_type`
    # precedent).

    def _build_roster_ui(self):
        """The two rows this phase adds, returned as widgets the caller drops
        into the existing controls column."""
        self._effect_combo = _NoWheelComboBox()
        self._effect_combo.currentIndexChanged.connect(self._on_effect_changed)
        self._variant_combo = _NoWheelComboBox()
        self._variant_combo.currentIndexChanged.connect(self._on_variant_changed)

        self._add_effect_btn = QPushButton("+ Effect")
        self._add_effect_btn.setToolTip(
            "Add a new VFX effect. It starts with one slot and no art;\n"
            "import a spritesheet onto it, then bind it to an event below.")
        self._add_effect_btn.clicked.connect(lambda: self._on_add_effect())
        self._add_variant_btn = QPushButton("+ Variant")
        self._add_variant_btn.setToolTip(
            "Add another interchangeable sheet for this effect. Which one\n"
            "plays is decided by the Pick control below.")
        self._add_variant_btn.clicked.connect(lambda: self._on_add_variant())
        self._rename_btn = QPushButton("Rename…")
        self._rename_btn.clicked.connect(lambda: self._on_rename())
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.clicked.connect(lambda: self._on_remove())

        roster = QHBoxLayout()
        roster.addWidget(QLabel("Effect"))
        roster.addWidget(self._effect_combo)
        roster.addWidget(QLabel("Variant"))
        roster.addWidget(self._variant_combo)
        roster.addWidget(self._add_effect_btn)
        roster.addWidget(self._add_variant_btn)
        roster.addWidget(self._rename_btn)
        roster.addWidget(self._remove_btn)
        roster.addStretch(1)

        self._event_combo = _NoWheelComboBox()
        self._event_combo.currentTextChanged.connect(self._refresh_binding_row)
        self._bind_btn = QPushButton("Bind")
        self._bind_btn.setToolTip(
            "Play the selected effect's art for this event.")
        self._bind_btn.clicked.connect(lambda: self._on_bind())
        self._unbind_btn = QPushButton("Unbind")
        self._unbind_btn.setToolTip(
            "Fall back to this event's procedural effect.")
        self._unbind_btn.clicked.connect(lambda: self._on_unbind())
        self._bound_label = QLabel("")

        self._mode_combo = _NoWheelComboBox()
        self._mode_combo.addItems(VARIANT_MODES)
        self._mode_combo.setToolTip(
            "How a variant is chosen each time this event fires.\n"
            "random: uniformly, per spawn.\n"
            "level: by the source's tier (buildings) or era (enemies);\n"
            "  events that carry no source object use the first variant.\n"
            "misc: by a named value game code registers later.")
        self._mode_combo.currentTextChanged.connect(self._on_mode_changed)
        self._misc_key_edit = QLineEdit()
        self._misc_key_edit.setPlaceholderText("misc key")
        self._misc_key_edit.setToolTip(
            "The name game code registers a provider for\n"
            "(game/vfx_misc.py). Unregistered = the first variant.")
        self._misc_key_edit.editingFinished.connect(self._on_misc_key_edited)
        self._front_check = QCheckBox("draw in front")
        self._front_check.setToolTip(
            "On: this effect draws OVER a building or enemy on its own tile.\n"
            "Off: behind it. Effects still sort by tile position either way —\n"
            "this decides only the tie on the same tile.")
        self._front_check.toggled.connect(self._on_front_toggled)

        binding = QHBoxLayout()
        binding.addWidget(QLabel("Event"))
        binding.addWidget(self._event_combo)
        binding.addWidget(self._bind_btn)
        binding.addWidget(self._unbind_btn)
        binding.addWidget(self._bound_label)
        binding.addWidget(QLabel("Pick"))
        binding.addWidget(self._mode_combo)
        binding.addWidget(self._misc_key_edit)
        binding.addWidget(self._front_check)
        binding.addStretch(1)
        return roster, binding

    # -- reading the roster out of the registry ----------------------------

    def _effect_labels(self):
        """Every VFX effect's label, in registry document order."""
        try:
            return list(selection.subcategories(
                self._registry, "vfx", ("Effects",)))
        except Exception:
            return []

    def _effect_slots(self, label):
        """One effect's interchangeable slots (its variants), in order."""
        labels = self._effect_labels()
        if label not in labels:
            return []
        return list(selection.level_slots(
            self._registry, "vfx", ("Effects",), labels.index(label)))

    def current_effect(self):
        """The selected effect LABEL, or None."""
        return self._effect_combo.currentText() or None

    def current_slot(self):
        """The selected VARIANT's slot key, or None — what Bind, Rename,
        Remove and the import buttons all act on."""
        return self._variant_combo.currentText() or None

    def refresh_roster(self):
        """Rebuild both combos from the live registry, preserving the
        selection where it survived (a rename changes the key, so the effect
        label is the stabler anchor of the two)."""
        wanted_effect = self._effect_combo.currentText()
        wanted_slot = self._variant_combo.currentText()

        labels = self._effect_labels()
        self._effect_combo.blockSignals(True)
        self._effect_combo.clear()
        self._effect_combo.addItems(labels)
        if wanted_effect in labels:
            self._effect_combo.setCurrentText(wanted_effect)
        self._effect_combo.blockSignals(False)

        self._refresh_variants(prefer=wanted_slot)
        self._refresh_binding_row()

    def _refresh_variants(self, prefer=None):
        slots = self._effect_slots(self._effect_combo.currentText())
        self._variant_combo.blockSignals(True)
        self._variant_combo.clear()
        self._variant_combo.addItems(slots)
        if prefer in slots:
            self._variant_combo.setCurrentText(prefer)
        self._variant_combo.blockSignals(False)
        # Removing the last remaining effect would leave the group empty,
        # which `slots.json` cannot represent — so the op refuses and the
        # button says so rather than offering an action that raises.
        self._remove_btn.setEnabled(bool(slots) and len(self._effect_labels()) > 1)
        self._add_variant_btn.setEnabled(bool(slots))
        self._rename_btn.setEnabled(bool(slots))
        self._refresh_import_btn()

    def _on_effect_changed(self, _idx=None):
        self._refresh_variants()

    def _on_variant_changed(self, _idx=None):
        self._refresh_import_btn()
        self._refresh_binding_row()

    # -- the registry ops --------------------------------------------------

    def _reload_registry(self):
        """Re-read `slots.json` after a structural edit, rebuild the asset
        store on top of it, and tell the shell so the selector tree follows."""
        self._registry = load_registry(self._data_dir)
        self.reload_assets()
        self.refresh_roster()
        self.registry_changed.emit()

    def _report(self, message):
        """One place the ops say what happened. A panel with no window (every
        test) simply drops it."""
        window = self.window()
        bar = getattr(window, "statusBar", None)
        if callable(bar):
            try:
                bar().showMessage(message, 6000)
                return
            except Exception:
                pass
        self._degrade_label.setText(message)

    def _on_add_effect(self, name=None):
        """`name=None` opens the naming dialog; passing a name is the test
        seam (`main.py::_on_add_button_type`'s shape)."""
        if name is None:
            name = self._prompt_effect_name()
            if name is None:
                return None
        try:
            label, slot = registry_ops.add_vfx_effect(self._data_dir, name)
        except (KeyError, OSError, ValueError) as exc:
            self._report(f"Could not add effect: {exc}")
            return None
        self._reload_registry()
        self._effect_combo.setCurrentText(label)
        self._refresh_variants(prefer=slot)
        self._report(f"Added effect {label!r} ({slot}) — import art onto it, "
                     f"then bind it to an event.")
        return label, slot

    def _on_add_variant(self):
        label = self.current_effect()
        if not label:
            return None
        try:
            key = registry_ops.add_variant(
                self._data_dir, "vfx", ("Effects",), label)
        except (KeyError, OSError, ValueError) as exc:
            self._report(f"Could not add variant: {exc}")
            return None
        self._reload_registry()
        self._effect_combo.setCurrentText(label)
        self._refresh_variants(prefer=key)
        self._report(f"Added variant {key} — import art onto it.")
        return key

    def _on_rename(self, new_key=None):
        slot = self.current_slot()
        if slot is None:
            return None
        if new_key is None:
            new_key = self._prompt_rename(slot)
            if new_key is None:
                return None
        try:
            rebound, png = registry_ops.rename_slot(
                self._data_dir, slot, new_key)
        except (KeyError, OSError, ValueError) as exc:
            self._report(f"Could not rename: {exc}")
            return None
        self._reload_registry()
        self._refresh_variants(prefer=new_key)
        moved = " (art moved)" if png else ""
        bound = f", rebound {', '.join(rebound)}" if rebound else ""
        self._report(f"Renamed {slot} -> {new_key}{moved}{bound}.")
        return new_key

    def _on_remove(self, confirm=True):
        """`confirm=False` skips the dialog — the test seam.

        NOTE the `clicked.connect(lambda: self._on_remove())` wrapper at the
        button: a bare connect would hand Qt's `clicked(bool)` straight into
        `confirm` and silently skip the confirmation, which is the exact
        footgun the panels doc records biting `map_details`' Delete."""
        slot = self.current_slot()
        if slot is None:
            return False
        bound = registry_ops.trigger_bindings(self._data_dir, slot)
        if bound:
            self._report(f"{slot} is still bound to {', '.join(bound)} — "
                         f"unbind it first.")
            return False
        if confirm:
            answer = QMessageBox.question(
                self, "Remove effect",
                f"Remove {slot}?\n\nIts imported art is deleted too, unless "
                f"another slot links to the same sheet.")
            if answer != QMessageBox.Yes:
                return False
        try:
            removed_group, removed_png = registry_ops.remove_slot(
                self._data_dir, slot)
        except (KeyError, OSError, ValueError) as exc:
            self._report(f"Could not remove: {exc}")
            return False
        self._reload_registry()
        art = " and its art" if removed_png else ""
        self._report(f"Removed {slot}{art}.")
        return True

    # -- the two modals, split from their model halves ---------------------

    def _prompt_effect_name(self):
        """Name dialog with a live slug preview — `main.py`'s
        `_prompt_button_type_name`, verbatim in shape."""
        dialog = QDialog(self)
        dialog.setWindowTitle("New VFX effect")
        form = QFormLayout(dialog)
        name_edit = QLineEdit()
        key_label = QLabel("—")
        form.addRow("Name", name_edit)
        form.addRow("Slot key", key_label)

        def preview(text):
            try:
                key_label.setText(registry_ops.vfx_effect_slot(text))
            except ValueError:
                key_label.setText("—")

        name_edit.textChanged.connect(preview)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        return name_edit.text().strip() or None

    def _prompt_rename(self, slot):
        dialog = QDialog(self)
        dialog.setWindowTitle("Rename slot")
        form = QFormLayout(dialog)
        key_edit = QLineEdit(slot)
        form.addRow("Slot key", key_edit)
        form.addRow(QLabel(
            "The imported art, the manifest entry and every\n"
            "trigger binding follow the new name."))
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec() != QDialog.Accepted:
            return None
        return key_edit.text().strip() or None

    # -- the trigger binding + variant-select controls ---------------------

    def _trigger_events(self):
        """Every event the schema declares, sorted — read from the SCHEMA, not
        from the staged doc, so the list is complete even before a designer
        has touched anything."""
        try:
            return sorted(
                self._schema["properties"]["triggers"]["properties"])
        except (KeyError, TypeError):
            return []

    def current_event(self):
        return self._event_combo.currentText() or None

    def _trigger_value(self, event, *path):
        if self._balancing is None or self._balancing.domain != "vfx":
            return None
        return self._balancing.staged_value("/".join(("triggers", event) + path))

    def _stage_trigger(self, event, path, value):
        if self._balancing is None or self._balancing.domain != "vfx":
            self._report("Select the vfx domain to edit trigger bindings.")
            return False
        self._balancing.stage_value(f"triggers/{event}/{path}", value)
        return True

    def refresh_events(self):
        events = self._trigger_events()
        current = self._event_combo.currentText()
        self._event_combo.blockSignals(True)
        self._event_combo.clear()
        self._event_combo.addItems(events)
        if current in events:
            self._event_combo.setCurrentText(current)
        self._event_combo.blockSignals(False)
        self._refresh_binding_row()

    def _refresh_binding_row(self, _text=None):
        """Push the selected event's stored row into the widgets. Signals are
        blocked throughout: setting a combo would otherwise fire the handler
        that stages a value, so merely LOOKING at an event would dirty the
        document."""
        event = self.current_event()
        enabled = bool(event) and self._balancing is not None \
            and getattr(self._balancing, "domain", None) == "vfx"
        for widget in (self._bind_btn, self._unbind_btn, self._mode_combo,
                       self._misc_key_edit, self._front_check):
            widget.setEnabled(enabled)
        if not enabled:
            self._bound_label.setText("")
            return

        bound = self._trigger_value(event, "sprite_slot") or ""
        self._bound_label.setText(f"→ {bound}" if bound else "→ procedural")
        self._bind_btn.setEnabled(bool(self.current_slot()))
        self._unbind_btn.setEnabled(bool(bound))

        mode = self._trigger_value(event, "variant_select", "mode")
        misc = self._trigger_value(event, "variant_select", "misc_key")
        front = self._trigger_value(event, "draw_in_front")
        for widget in (self._mode_combo, self._misc_key_edit,
                       self._front_check):
            widget.blockSignals(True)
        if mode in VARIANT_MODES:
            self._mode_combo.setCurrentText(mode)
        self._misc_key_edit.setText(misc or "")
        self._misc_key_edit.setVisible(mode == MISC_MODE)
        self._front_check.setChecked(bool(front))
        for widget in (self._mode_combo, self._misc_key_edit,
                       self._front_check):
            widget.blockSignals(False)

    def _on_bind(self):
        event, slot = self.current_event(), self.current_slot()
        if not event or not slot:
            return False
        if not self._stage_trigger(event, "sprite_slot", slot):
            return False
        self._refresh_binding_row()
        self._report(f"{event} → {slot} (Save to keep it).")
        return True

    def _on_unbind(self):
        event = self.current_event()
        if not event:
            return False
        if not self._stage_trigger(event, "sprite_slot", ""):
            return False
        self._refresh_binding_row()
        return True

    def _on_mode_changed(self, mode):
        event = self.current_event()
        if not event or mode not in VARIANT_MODES:
            return
        self._stage_trigger(event, "variant_select/mode", mode)
        self._misc_key_edit.setVisible(mode == MISC_MODE)

    def _on_misc_key_edited(self):
        event = self.current_event()
        if not event:
            return
        self._stage_trigger(event, "variant_select/misc_key",
                            self._misc_key_edit.text().strip())

    def _on_front_toggled(self, checked):
        event = self.current_event()
        if not event:
            return
        self._stage_trigger(event, "draw_in_front", bool(checked))

class _PreviewSurface(QWidget):
    """The engine-`Renderer` paint target. `QPainter` blits the converted
    frame and draws nothing else — the ONE render path (ED-22)."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._panel._resize_surface()

    def paintEvent(self, event):
        if self._panel._qimage is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._panel._qimage)
