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
import os
import random
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import domains, vfx_params
from editor.panels.balancing import _NoWheelDoubleSpinBox, _NoWheelSpinBox
from editor.panels.viewport import surface_to_qimage
from engine import data_io
from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import HudRect, HudSprite, Renderer, RenderItem
from engine.vfx import VfxSystem

REPO = Path(__file__).resolve().parents[2]
BACKGROUND = (24, 20, 32)
DEFAULT_SEED = 1234
DEFAULT_LOOP_INTERVAL = 1.0
_PRESET_KEYS = ("place", "level1", "level2", "tier")

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


class VfxPreviewPanel(QWidget):
    """The preview surface + its controls, in one widget so `editor/main.py`
    can add it to `right_stack` as a single page (index 3+)."""

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

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Family"))
        top_row.addWidget(self._family_combo)
        top_row.addWidget(self._preset_combo)
        top_row.addWidget(self._strong_check)
        top_row.addWidget(self._large_check)
        top_row.addWidget(self._shell_check)
        top_row.addStretch(1)

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

        controls = QVBoxLayout()
        controls.addLayout(top_row)
        controls.addLayout(loop_row)
        controls.addWidget(self._degrade_label)
        controls.addWidget(lever_box)
        controls.addWidget(ramp_box)
        controls.addStretch(1)
        controls_widget = QWidget()
        controls_widget.setLayout(controls)
        controls_widget.setMaximumHeight(220)

        self._surface_widget = _PreviewSurface(self)
        self._surface_widget.setMinimumHeight(200)

        outer = QVBoxLayout(self)
        outer.addWidget(self._surface_widget, 1)
        outer.addWidget(controls_widget)

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
        supported = name in _EMIT_FAMILIES or name == _PROJECTILE_FAMILY
        self._preset_combo.setVisible(name == "spark")
        self._strong_check.setVisible(name == "muzzle")
        self._large_check.setVisible(name == "slash")
        self._shell_check.setVisible(name == _PROJECTILE_FAMILY)
        self._degrade_label.setText(
            "" if supported else f"no preview for {name!r} yet")
        self._degrade_label.setVisible(not supported)
        self._system = None
        self._rebuild_levers()
        self._rebuild_colors()
        if name in _EMIT_FAMILIES:
            self._emit()
        elif name == _PROJECTILE_FAMILY:
            # Not a VfxSystem family (no self._system to rebuild/reseed) —
            # just restart the flight clock, mirroring _emit()'s own
            # self._loop_clock reset for every other family switch.
            self._loop_clock = 0.0

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
        self._renderer.flush(self._surface)
        self._qimage = surface_to_qimage(self._surface)
        self._surface_widget.update()
        self.last_frame_ms = (time.perf_counter() - t0) * 1000.0


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
