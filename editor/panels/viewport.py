"""ViewportPanel (ED-2/ED-20/ED-21/ED-22/ED-23) — the engine's render
surface embedded in a PySide6 widget.

Four modes, all drawn by the ONE real engine pipeline (RenderItem ->
Renderer -> pygame.Surface, ED-22): the Phase 3 grey-X ground grid, the
entity preview (ED-21, Phase 5), the TILEMAP EDITOR (ED-20, Phase 6, when a
map node is selected): the open MapSession's doc rendered with layer eyes +
zone tints, ghost previews on the overlay layer, grid lines through the
engine's E-24 overlay primitive, and mouse tools whose cell picking goes
through engine.coords.screen_to_world ONLY (E-3 — no iso math here); and
SCREEN MODE (B4, R3, when a UI-screen leaf is selected): a fixed logical
canvas at data/display.json's resolution (UR-1: that file is the ONE place
the resolution is stated) scaled-to-fit the widget, submitted entirely through
Renderer.submit_hud (HudSprite for skinned widgets, editor.panels.
_screen_primitives' flat-rect fallback for unskinned ones — E-37 degrade,
never a game/ui import). In map mode the LEFT button drives the armed tool
and the RIGHT button pans (entity preview keeps either-button pan); strokes
mutate the session doc live and are pushed as ONE undo command on
release (ED-24). Screen mode mirrors that live-mutate-then-push pattern for
widget drags (set_screen_mode/_screen_press/_screen_release).

SDL dummy drivers are set BEFORE importing pygame: the editor's pygame
surface is always an offscreen render target sized to the widget, never a
real SDL window. The surface is converted to a QImage and painted in
paintEvent — the sanctioned QImage-copy fallback (PLAN §7), >=60fps at
1280x720 (numbers in editor/CLAUDE.md). That literal is a RECORD of the
editor-window size the measurement was taken at, not the logical screen
canvas — the canvas is data/display.json's resolution (see
logical_resolution below). Do not de-literalise it; it would falsify the
measurement.
"""
import math
import os
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from editor import anchor_ops, tilemap_ops, vfx_params
from editor.panels import _screen_primitives
from editor.panels.balancing import _NoWheelComboBox
from editor.sprite_fit import slot_draw_fit
from engine import data_io, tilemap
from engine.assets import entry_from_dict, load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import (
    HudLines,
    HudRect,
    HudSprite,
    HudText,
    Renderer,
    RenderItem,
    fit_factor,
    sprite_anchor_screen,
)

REPO = Path(__file__).resolve().parents[2]
BACKGROUND = (24, 20, 32)

# Editor-only chrome constants (UI cosmetics, not data): zone tints are
# RGBA multipliers (BLEND_RGBA_MULT) applied to ground tiles when the
# zone-tint eye is on, so zones stay tellable apart even in grey-X art.
ZONE_TINTS = {
    "b": (150, 235, 150, 255),   # buildable — green
    "c": (235, 150, 150, 255),   # combat — red
    "s": (200, 160, 235, 255),   # spawning — violet
}
GHOST_TINT = (255, 255, 140, 255)   # armed brush preview under the cursor
GRID_COLOR = (110, 110, 140)
START_AREA_COLOR = (255, 190, 60)        # the placed 2×2 starting-area outline
START_AREA_GHOST_COLOR = (255, 255, 140)  # its armed/drag ghost outline
TUTORIAL_COLOR = (255, 255, 255)          # the placed tutorial marker outline
TUTORIAL_GHOST_COLOR = (200, 200, 200)    # its armed/drag ghost outline
RESERVE_COLOR = (120, 235, 220)           # spawnable-background mark outline
# despawnable-spawn mark outline — deliberately MAGENTA against the reserve's
# cyan so the two invisible overlays are tellable apart at a glance
DESPAWN_COLOR = (245, 110, 210)
# stage-zone mark outline — a third clearly distinct hue (lime green) against
# the reserve's cyan and the despawn's magenta; one cell can legitimately carry
# all three marks, so each number is also drawn at its own y offset
STAGE_COLOR = (150, 255, 90)
# tile-condition mark outlines — ONE hue per condition NAME (the fourth
# overlay's brush value is a name, not a number), each chosen to stay legible
# against the reserve's cyan, the despawn's magenta and the stage's lime, and
# against each other. A name with no entry here falls back to
# CONDITION_DEFAULT_COLOR, so a fifth condition added to the schema still
# draws (E-37) — it just shares the fallback hue until a colour is chosen.
CONDITION_COLORS = {
    "grass": (255, 235, 120),    # pale yellow
    "mountain": (170, 170, 185),  # slate grey
    "pond": (80, 140, 255),      # deep blue (vs the reserve's turquoise)
    "forest": (0, 170, 95),      # deep green (vs the stage's lime)
}
CONDITION_DEFAULT_COLOR = (255, 255, 255)

# ESV-2: anchor handles (entity-preview fallback only) — fixed SCREEN size
# regardless of zoom (the two-sample screen_to_world trick, §2.3c), one
# colour constant per state.
ANCHOR_COLOR = (120, 200, 255)          # authored, unselected
ANCHOR_SELECTED_COLOR = (255, 220, 80)  # the anchor whose row is focused in the panel
ANCHOR_DRAG_COLOR = (255, 90, 90)       # actively being dragged
HANDLE_RADIUS_PX = 6   # half-extent, fixed SCREEN pixels — never scales with zoom
HANDLE_HIT_PX = 10     # hit-test radius, SCREEN pixels, Euclidean

LOGO_PATH = REPO / "editor" / "assets" / "drunken_donuts_logo.png"

# -- screen mode (B4, R3): fixed logical canvas, scaled-to-fit --------------


def logical_resolution(data_dir=None):
    """The logical screen-canvas size, read from ``data/display.json``.

    UR-1: that file is the ONE place in the repo that states the logical
    resolution — nothing here carries a literal fallback, because a fallback
    would be exactly the second source of truth this helper deletes. A missing
    or invalid display.json therefore raises rather than silently drawing at
    the wrong size.

    ``data_dir`` defaults to the repo's ``data/`` (the same root the rest of
    the editor's module-level loads use). The parameter exists so a caller
    with its own data root can ask; making the panel itself per-instance
    data-root aware is UR-3's job, not this helper's.
    """
    root = Path(data_dir) if data_dir is not None else REPO / "data"
    display = data_io.load_validated(
        root / "display.json", root / "schemas" / "display.schema.json")
    return display["window_w"], display["window_h"]


SCREEN_W, SCREEN_H = logical_resolution()
NO_DEFAULTS_COLOR = (235, 90, 90)          # E-37 graceful-degrade placeholder
SELECTION_COLOR = (255, 220, 80)
LETTERBOX_EDGE_COLOR = (90, 95, 105)   # UR-3: muted frame on the canvas edge
HANDLE_COLOR = (255, 255, 255)
HANDLE_PX = 8          # resize-handle hit box, half-width in SCREEN pixels
NUDGE_STEP = 1         # arrow-key nudge, in ONE LOGICAL pixel of the canvas
_CORNERS = ("tl", "tr", "bl", "br")


def surface_to_qimage(surface):
    """Pure conversion: pygame.Surface -> QImage (the sanctioned fallback).

    .copy() detaches the QImage from the tostring() byte buffer so it stays
    valid after this function returns.
    """
    w, h = surface.get_size()
    data = pygame.image.tobytes(surface, "RGB")
    image = QImage(data, w, h, w * 3, QImage.Format.Format_RGB888)
    return image.copy()


class ViewportPanel(QWidget):
    cursor_world = Signal(float, float)   # ED-23 readout (both modes)
    code_picked = Signal(str)             # picker tool → palette re-arm
    reserve_number_picked = Signal(int)   # picker on a mark → palette spinbox
    despawn_number_picked = Signal(int)   # picker on a despawn mark → spinbox
    stage_number_picked = Signal(int)     # picker on a stage-zone mark → spinbox
    condition_picked = Signal(str)        # picker on a condition mark → brush
    widget_selected = Signal(object)      # B4: screen-mode selection (str|None)
    anchor_selected = Signal(object)          # ESV-2: name|None -> AnchorsPanel
    anchor_dragged = Signal(str, int, int)    # ESV-2: live drag -> spinboxes
    anchor_drag_finished = Signal(str, int, int)  # ESV-2: ONE write per gesture

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)  # B4: arrow-key nudge
        pygame.init()
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._coords = self._load_coords()
        self._registry = load_registry(self._data_dir)
        self._disk_manifest = load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json")
        self._draft = None            # (slot_key, ManifestEntry) or None
        self._manifest = None         # effective manifest (disk + draft)
        self._build_store()

        self.preview_slot = None
        # Memoized (fit_tiles, scale) for preview_slot — resolved eagerly by
        # _resolve_draw_fit() on slot change / registry reload, never per
        # frame (slot_draw_fit re-reads two JSON files). See _preview_draw_fit.
        self._draw_fit = (0.0, 1.0)
        self.preview_animation = "idle"
        self._anim_ms = 0.0
        self._anim_last_t = None

        # ESV-2: anchor handles — a VIEW of the panel's authoritative
        # mapping plus a live drag delta; the viewport never reads/writes
        # the manifest for anchors itself (§2.2).
        self._anchors = {}            # {name: (x, y)}
        self._anchor_selected = None  # name | None
        self._anchor_drag = None      # (name, orig_x, orig_y) while dragging

        # -- tilemap-editor state (ED-20); all mutations go through the
        # session's undo stack, all cell picking through engine.coords
        self._map_session = None
        self._tool = "none"
        self._armed_code = None
        self._armed_deco = None
        self._deco_flip_armed = False  # mirror-flip toggle for the deco brush
        self._armed_base = None     # the Hole slot when the Hole brush is armed
        self._armed_camera = None   # the Camera Start slot when that brush is armed
        self._armed_start_area = None  # the Start Area slot when armed
        self._armed_tutorial_flute = None  # the First Flute slot when armed
        self._armed_tutorial_stone = None  # the First Stone slot when armed
        # the Spawnable Background brush: True when armed (it has no slot —
        # a mark is an invisible overlay, not a sprite)
        self._armed_spawn_reserve = None
        self._reserve_number = 1      # stage number newly painted marks carry
        # the Despawnable Spawn brush: True when armed (same shape — a mark is
        # an invisible overlay, not a sprite)
        self._armed_despawn = None
        self._despawn_number = 1   # stage number newly painted marks carry
        # the Stage Zones brush: True when armed (same shape again)
        self._armed_stage = None
        self._stage_number = 1     # stage number newly painted marks carry
        # the Tile Conditions brush: the armed condition NAME when armed (the
        # same shape again, except the brush carries a value — one button per
        # condition, so the value is the name, never a number)
        self._armed_condition = None
        self._eyes = {"terrain": True, "tint": True, "base": True, "deco": True,
                      "camera": True, "start_area": True, "tutorial": True,
                      "spawn_reserve": True, "despawnable_spawn": True,
                      "stage_zones": True, "tile_conditions": True}
        self._grid_lines = False
        self._hover_cell = None
        self._stroke = None           # change list accumulating this stroke
        self._stroke_code = None
        self._stroke_last = None
        # spawn-reserve stroke accumulator + the value it writes (None = erase)
        self._reserve_stroke = None
        self._reserve_stroke_value = None
        # despawn stroke accumulator + the value it writes (None = erase)
        self._despawn_stroke = None
        self._despawn_stroke_value = None
        # stage-zone stroke accumulator + the value it writes (None = erase)
        self._stage_stroke = None
        self._stage_stroke_value = None
        # tile-condition stroke accumulator + the condition NAME it writes
        # (None = erase)
        self._condition_stroke = None
        self._condition_stroke_value = None
        self._anchor = None           # line/rect anchor cell
        self._base_drag = False
        self._camera_drag = False
        self._start_area_drag = False
        self._tutorial_flute_drag = False
        self._tutorial_stone_drag = False

        # ED-21 animation dropdown: floating child pinned to the corner so
        # the paint surface keeps filling the whole widget.
        self._anim_combo = _NoWheelComboBox(self)
        self._anim_combo.move(8, 8)
        self._anim_combo.hide()
        self._anim_combo.currentTextChanged.connect(self.set_preview_animation)

        # -- screen mode state (B4, R3): all mutation goes through the open
        # UIScreenSession's undo stack; all rect math in LOGICAL canvas
        # (SCREEN_W x SCREEN_H) pixels, converted to SCREEN pixels only at
        # submission/hit-test time
        self._screen_session = None
        self._screen_defaults = {}    # {screen_id: {widgets, mock_note}} or {}
        self._selected_widget = None
        self._selected_field_mode = None   # None | "move" | "resize"
        self._resize_corner = None         # "tl"|"tr"|"bl"|"br" while resizing
        self._drag_start = None            # SCREEN-pixel QPointF at press
        self._drag_orig_rect = None        # effective LOGICAL rect at press
        self._drag_orig_override_rect = None  # doc override at press, or None
        self._screen_state = "idle"        # state-dropdown value (button rows)
        self._screen_anim_ms = 0.0
        self._screen_anim_last_t = None
        # UR-3: the logical SCREEN_W x SCREEN_H canvas the screen preview is
        # rendered into before it is scaled up once (see `_screen_canvas`).
        self._screen_canvas_surface = None
        # Button-state dropdown (idle/hover/pressed/disabled), same floating-
        # child pattern as the entity-preview animation combo above.
        self._state_combo = _NoWheelComboBox(self)
        self._state_combo.move(8, 8)
        self._state_combo.hide()
        self._state_combo.currentTextChanged.connect(self.set_screen_state)

        self._surface = None
        self._qimage = None
        self._drag_pos = None
        self.last_frame_ms = 0.0
        self._logo_pixmap = QPixmap(str(LOGO_PATH))
        # feat-projectile-anchored-flight §3.2 PERF: data/balancing/vfx.json
        # is a THIRD JSON file the entity-preview muzzle-projectile draw
        # needs (on top of the two slot_draw_fit already reads) — resolved
        # ONCE here, never inside render_frame/_anchor_draw_params/
        # _hit_anchor_handle/_anchor_move (the slot_draw_fit PERF lesson:
        # re-reading JSON per frame/per drag-move measured 125-145ms/frame).
        # Unlike _draw_fit this does not depend on preview_slot at all, so
        # there is nothing to re-resolve on a slot switch — only
        # reload_registry() re-reads it, mirroring _resolve_draw_fit's call
        # site for "a designer edited data/ and reloaded".
        self._projectile_params = self._load_projectile_params()
        self._resize_surface()

    # -- coords lifecycle: zoom is a balancing tunable (core:Camera) --------

    def _load_coords(self, map_cols=None, map_rows=None):
        """load_coordinate_system with the balancing-core `Camera` group's
        zoom_levels/default_zoom applied as the override (the editor may not
        import `game/`, so it reads data/balancing/core.json directly through
        data_io.load_validated — the same pattern balancing.py's set_domain
        uses — rather than game.core.balance.load_balance), plus any map-dims
        override (D-20, unchanged)."""
        core_balance = data_io.load_validated(
            self._data_dir / "balancing" / "core.json",
            self._data_dir / "schemas" / "core.schema.json")
        return load_coordinate_system(
            self._data_dir, map_cols=map_cols, map_rows=map_rows,
            zoom_levels=core_balance["Camera"]["zoom_levels"],
            default_zoom=core_balance["Camera"]["default_zoom"])

    # -- asset store lifecycle (rebuild = the only cache invalidation) ------

    def _build_store(self):
        manifest = self._disk_manifest
        if self._draft is not None:
            manifest = manifest.override(*self._draft)
        self._manifest = manifest
        self._assets = AssetStore(manifest=manifest, registry=self._registry,
                                  sprites_dir=self._data_dir / "sprites")
        self._renderer = Renderer(self._coords, self._assets)

    def reload_assets(self):
        """ED-42: re-read the manifest from disk (after an import-panel
        save) and drop any draft. Camera state lives in self._coords and is
        untouched — pan/zoom survive."""
        self._disk_manifest = load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json")
        self._draft = None
        self._build_store()
        self._refresh_anim_combo()

    def reload_registry(self):
        """Re-read data/slots.json (a variant slot was added) so the new slot
        resolves for preview + import; the store is rebuilt, camera untouched."""
        self._registry = load_registry(self._data_dir)
        self._build_store()
        self._resolve_draw_fit()   # slots.json changed -> the fit may have too
        self._projectile_params = self._load_projectile_params()

    def _load_projectile_params(self):
        """The memoized `procedural.projectile` read (feat-projectile-
        anchored-flight §3.2 PERF) — `data_io.load_validated` against the
        vfx schema, then the SAME `editor/vfx_params.py projectile_params`
        the VFX preview panel already builds."""
        doc = data_io.load_validated(
            self._data_dir / "balancing" / "vfx.json",
            self._data_dir / "schemas" / "vfx.schema.json")
        return vfx_params.projectile_params(doc["procedural"]["projectile"])

    # -- entity preview (ED-21) ----------------------------------------------

    def set_preview_slot(self, slot_key):
        """None -> plain grid mode; a slot key -> entity preview mode."""
        if slot_key != self.preview_slot:
            self.preview_slot = slot_key
            self._draft = None
            self._build_store()
            self._resolve_draw_fit()   # memoized; see _preview_draw_fit
            self.preview_animation = "idle"
            self._reset_anim_clock()
            # ESV-2: a stale slot's handles/drag must not survive a switch
            # (the same rule that clears self._draft just above).
            self._anchors = {}
            self._anchor_selected = None
            self._anchor_drag = None
        self._refresh_anim_combo()

    def set_preview_animation(self, name):
        if not name or name == self.preview_animation:
            return
        self.preview_animation = name
        self._reset_anim_clock()

    def set_anchors(self, mapping):
        """The panel's authoritative {name: (x, y)} mapping for the
        currently previewed slot — the viewport never reads the manifest
        for anchors itself (§2.2)."""
        self._anchors = dict(mapping or {})

    def set_selected_anchor(self, name):
        """External sync (the panel's own row focus) — mirrors
        set_selected_widget (§2.2)."""
        self._anchor_selected = name

    def assigned_slots(self):
        """Slot keys with an entry in the effective (draft-aware) manifest —
        the shell uses this for ● markers on the level bar."""
        return self._manifest.slots()

    def preview_animations(self):
        """Animations authored for the previewed slot (draft-aware); ()
        when there is no entry — the preview is then the grey X."""
        if self.preview_slot is None:
            return ()
        entry = self._manifest.entry(self.preview_slot)
        return tuple(entry.animations) if entry is not None else ()

    def set_preview_draft(self, slot_key, entry_dict):
        """Live unsaved-edit preview: override one slot with the import
        panel's draft (in memory only). An unusable draft (e.g. every frame
        hidden) falls back to the on-disk state instead of raising."""
        if entry_dict is None:
            self._draft = None
        else:
            try:
                self._draft = (slot_key, entry_from_dict(slot_key, entry_dict))
            except ValueError:
                self._draft = None
        self._build_store()
        self._refresh_anim_combo()

    def _reset_anim_clock(self):
        self._anim_ms = 0.0
        self._anim_last_t = None

    # -- tilemap editor mode (ED-20) -----------------------------------------

    def set_map_mode(self, session):
        """A MapSession with an open doc → tilemap mode (coords rebuilt to
        the map's own dims, D-20); None → back to entity preview
        (geometry.json dims). Camera re-clamps on every mode entry."""
        self._map_session = session if (
            session is not None and session.doc is not None) else None
        self._hover_cell = None
        self._stroke = None
        self._reserve_stroke = None
        self._despawn_stroke = None
        self._stage_stroke = None
        self._condition_stroke = None
        self._anchor = None
        self._base_drag = False
        self._start_area_drag = False
        self._tutorial_flute_drag = False
        self._tutorial_stone_drag = False
        if self.in_map_mode():
            doc = self._map_session.doc
            self._coords = self._load_coords(map_cols=doc.cols, map_rows=doc.rows)
            self._anim_combo.hide()
        else:
            self._coords = self._load_coords()
            self._refresh_anim_combo()
        w, h = max(1, self.width()), max(1, self.height())
        if self.in_map_mode():
            self._center_on_camera_start(w, h)
        else:
            self._center_on_preview(w, h)
        self._renderer = Renderer(self._coords, self._assets)

    def in_map_mode(self):
        return self._map_session is not None and self._map_session.doc is not None

    # -- screen mode (B4, R3) -------------------------------------------------

    def set_screen_mode(self, session, defaults=None):
        """A UIScreenSession with an open doc → screen mode: a FIXED
        SCREEN_W x SCREEN_H logical canvas (data/display.json's resolution),
        scaled-to-fit the viewport widget (no
        viewport-driven zoom like map mode — the whole canvas is always
        visible at one computed scale, like the entity preview's parked
        camera). None → leaves screen mode.

        `defaults` is the loaded data/ui/screen_defaults.json dict, keyed by
        screen_id -> {widgets, mock_note} (building_panel additionally
        carries a `views` mapping of view_id -> {widgets, mock_note} — UH-2;
        `_current_screen_defaults` resolves the session's active view, if
        any, to the same shape). Missing/empty is HARD REQUIRED to degrade
        gracefully (pre-B3, or a broken dev machine): render_frame never
        raises over it — see _submit_screen_items's placeholder path.
        """
        self._screen_session = session if (
            session is not None and session.doc is not None) else None
        self._screen_defaults = defaults if defaults is not None else {}
        self._selected_widget = None
        self._selected_field_mode = None
        self._resize_corner = None
        self._drag_start = None
        self._drag_orig_rect = None
        self._drag_orig_override_rect = None
        self._screen_state = "idle"
        self._reset_screen_anim_clock()
        if self.in_screen_mode():
            self._anim_combo.hide()
            self._refresh_state_combo()
            self._state_combo.show()
        else:
            self._state_combo.hide()
        self._resize_surface()

    def in_screen_mode(self):
        return self._screen_session is not None and self._screen_session.doc is not None

    def refresh_screen_defaults(self, defaults):
        """"Refresh Layouts" finished (B3's exporter ran): re-render with the
        freshly re-read data/ui/screen_defaults.json — no mode change."""
        self._screen_defaults = defaults or {}

    def set_selected_widget(self, widget_id):
        """External (screen_details widget-list click) → sync the viewport's
        own selection, without re-emitting widget_selected (screen_details
        already knows)."""
        self._selected_widget = widget_id
        self._selected_field_mode = None
        self._drag_start = None

    def set_screen_state(self, name):
        """The floating state combo (idle/hover/pressed/disabled) — drives
        the animation ROW passed to every skinned widget's HudSprite."""
        if not name or name == self._screen_state:
            return
        self._screen_state = name

    def _reset_screen_anim_clock(self):
        self._screen_anim_ms = 0.0
        self._screen_anim_last_t = None

    def _refresh_state_combo(self):
        """Populated from the registry's "ui" category vocabulary (data-
        driven, not a hardcoded literal list) — every ui slot shares the same
        idle/hover/pressed/disabled rows (data/CLAUDE.md 'ui animation
        vocabulary')."""
        try:
            animations = self._registry.category("ui").animations
        except KeyError:
            animations = ("idle",)
        combo = self._state_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(animations))
        if self._screen_state not in animations:
            self._screen_state = animations[0] if animations else "idle"
        combo.setCurrentText(self._screen_state)
        combo.blockSignals(False)

    def _current_screen_defaults(self):
        """The open screen's own {widgets, mock_note} sub-dict, or None when
        absent (no defaults file, or this screen isn't in it yet) — the ONE
        place every screen-mode code path checks for graceful degrade.

        UH-2: if the entry carries a `views` mapping and the session's
        active `view` names one, resolve to that view's own {widgets,
        mock_note} sub-dict (the same shape) instead — this single change
        IS the widget-list/render/hit-test filtering, since every caller
        already funnels through this function. A screen with no `views`
        (every screen but building_panel) or a session with no active view
        (view=None) behaves exactly as before."""
        if self._screen_session is None:
            return None
        entry = self._screen_defaults.get(self._screen_session.screen_id)
        if entry is None:
            return None
        views = entry.get("views")
        view = self._screen_session.view
        if views and view in views:
            return views[view]
        return entry

    def _screen_scale_offset(self):
        """Uniform scale + letterbox offset fitting the SCREEN_W x SCREEN_H
        logical canvas inside the current widget size (screen mode never
        zooms).

        UR-3: a fitted scale of 1.0 or more is snapped DOWN to a whole number
        (1x, 2x, 3x). The preview is pixel art blitted through one
        `transform.scale` (`_render_screen_frame`), and a fractional upscale
        duplicates some source pixels and not others — the game's own SCALED
        upscale is an exact integer multiple, so this is what a player sees.
        Below 1.0 the fractional downscale stays exactly as before (there is
        no honest integer answer there, and 1x would overflow the widget).
        The offsets are floored to whole pixels for the same reason the snap
        lives HERE and not at the blit: hit-testing, dragging and the blit all
        read this one triple, so they cannot disagree."""
        w, h = max(1, self.width()), max(1, self.height())
        scale = min(w / SCREEN_W, h / SCREEN_H)
        if scale >= 1.0:
            scale = float(math.floor(scale))
        scaled_w, scaled_h = SCREEN_W * scale, SCREEN_H * scale
        return (scale,
                float(math.floor((w - scaled_w) / 2)),
                float(math.floor((h - scaled_h) / 2)))

    def _to_screen_rect(self, rect, scale, ox, oy):
        x, y, w, h = rect
        return (ox + x * scale, oy + y * scale, w * scale, h * scale)

    def _effective_rect(self, widget_id, defaults):
        """The widget's CURRENT logical rect: the doc's override if one
        exists, else the default's own rect. Always a fresh list (never an
        alias into `defaults` or the doc)."""
        base = defaults["widgets"][widget_id]["rect"]
        override = self._screen_session.doc.get("widgets", {}).get(widget_id, {})
        return list(override.get("rect", base))

    # -- screen-mode hit testing (E-3 spirit: only through the one scale) ----

    def _hit_widget(self, pos, defaults):
        """Topmost widget rect under `pos` (SCREEN pixels) — reverse
        submission order, since a later HUD submission draws over an
        earlier one. Invisible widgets (visible=False override) can't be
        hit."""
        scale, ox, oy = self._screen_scale_offset()
        doc = self._screen_session.doc
        for widget_id in reversed(list(defaults.get("widgets", {}))):
            if doc.get("widgets", {}).get(widget_id, {}).get("visible") is False:
                continue
            sx, sy, sw, sh = self._to_screen_rect(
                self._effective_rect(widget_id, defaults), scale, ox, oy)
            if sx <= pos.x() <= sx + sw and sy <= pos.y() <= sy + sh:
                return widget_id
        return None

    def _hit_resize_handle(self, pos, defaults):
        """One of the 4 corner handles of the CURRENTLY selected widget, or
        None — handles only exist once something is already selected."""
        if self._selected_widget is None:
            return None
        scale, ox, oy = self._screen_scale_offset()
        sx, sy, sw, sh = self._to_screen_rect(
            self._effective_rect(self._selected_widget, defaults), scale, ox, oy)
        corners = dict(zip(_CORNERS,
                          ((sx, sy), (sx + sw, sy), (sx, sy + sh), (sx + sw, sy + sh))))
        for corner, (cx, cy) in corners.items():
            if abs(pos.x() - cx) <= HANDLE_PX and abs(pos.y() - cy) <= HANDLE_PX:
                return corner
        return None

    def _resized_rect(self, orig_rect, corner, dx, dy):
        """Dragging a corner keeps the OPPOSITE corner anchored; width/height
        floor at 1 logical pixel (never a degenerate/negative rect)."""
        x, y, w, h = orig_rect
        x1, y1, x2, y2 = x, y, x + w, y + h
        if corner in ("tl", "bl"):
            x1 = x + dx
        else:
            x2 = x + w + dx
        if corner in ("tl", "tr"):
            y1 = y + dy
        else:
            y2 = y + h + dy
        return [round(min(x1, x2)), round(min(y1, y2)),
                max(1, round(abs(x2 - x1))), max(1, round(abs(y2 - y1)))]

    # -- screen-mode interaction (ED-23) --------------------------------------

    def _screen_press(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        defaults = self._current_screen_defaults()
        if not defaults:
            return   # E-37: no defaults, no interaction
        pos = event.position()
        self.setFocus(Qt.FocusReason.MouseFocusReason)   # arrow nudge needs it
        handle = self._hit_resize_handle(pos, defaults)
        if handle is not None:
            self._begin_drag(self._selected_widget, "resize", pos, defaults,
                             corner=handle)
            return
        widget_id = self._hit_widget(pos, defaults)
        if widget_id != self._selected_widget:
            self._selected_widget = widget_id
            self.widget_selected.emit(widget_id)
        if widget_id is not None:
            self._begin_drag(widget_id, "move", pos, defaults)
        else:
            self._selected_field_mode = None
            self._drag_start = None

    def _begin_drag(self, widget_id, mode, pos, defaults, corner=None):
        self._selected_widget = widget_id
        self._selected_field_mode = mode
        self._resize_corner = corner
        self._drag_start = pos
        self._drag_orig_rect = self._effective_rect(widget_id, defaults)
        override = self._screen_session.doc.get("widgets", {}).get(widget_id, {})
        self._drag_orig_override_rect = (
            list(override["rect"]) if "rect" in override else None)

    def _screen_move(self, event):
        if self._drag_start is None or self._selected_widget is None:
            return
        defaults = self._current_screen_defaults()
        if not defaults:
            return
        scale, _ox, _oy = self._screen_scale_offset()
        pos = event.position()
        dx = (pos.x() - self._drag_start.x()) / scale
        dy = (pos.y() - self._drag_start.y()) / scale
        if self._selected_field_mode == "resize":
            new_rect = self._resized_rect(
                self._drag_orig_rect, self._resize_corner, dx, dy)
        else:
            x, y, w, h = self._drag_orig_rect
            new_rect = [round(x + dx), round(y + dy), w, h]
        doc = self._screen_session.doc
        doc.setdefault("widgets", {}).setdefault(
            self._selected_widget, {})["rect"] = new_rect

    def _screen_release(self, event):
        widget_id, mode = self._selected_widget, self._selected_field_mode
        dragging = self._drag_start is not None and widget_id is not None
        self._drag_start = None
        if not dragging:
            return
        defaults = self._current_screen_defaults()
        if not defaults:
            return
        new_rect = self._effective_rect(widget_id, defaults)
        old_rect = self._drag_orig_override_rect
        if mode == "resize":
            self._screen_session.push_resize(widget_id, old_rect, new_rect)
        else:
            self._screen_session.push_move(widget_id, old_rect, new_rect)

    def _nudge_selected(self, ddx, ddy):
        """Arrow-key nudge (1 logical px/press): a discrete edit, pushed
        directly (no live-drag preview needed) — QUndoStack.push() calls
        redo() itself, which is what actually mutates the doc."""
        defaults = self._current_screen_defaults()
        widget_id = self._selected_widget
        if not defaults or widget_id is None:
            return
        override = self._screen_session.doc.get("widgets", {}).get(widget_id, {})
        old_rect = list(override["rect"]) if "rect" in override else None
        x, y, w, h = self._effective_rect(widget_id, defaults)
        new_rect = [x + ddx * NUDGE_STEP, y + ddy * NUDGE_STEP, w, h]
        self._screen_session.push_move(widget_id, old_rect, new_rect)

    # -- palette state (MainWindow wires the PalettePanel signals to these)
    def set_tool(self, name):
        self._tool = name
        self._anchor = None

    def arm_code(self, code):
        self._armed_code = code
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_deco(self, slot):
        self._armed_deco = slot
        self._armed_code = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_base(self, slot):
        """Arm the Hole brush — a real paintable brush now (paint = place/move
        the single hole, erase = remove it). Clears any armed code/deco."""
        self._armed_base = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_camera(self, slot):
        """Arm the Camera Start brush (paint = place/move the single startpoint,
        erase = remove it). Mirrors arm_base; clears any other armed brush."""
        self._armed_camera = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_start_area(self, slot):
        """Arm the Starting Area brush (paint = place/move the single 2×2 area,
        erase = remove it). Mirrors arm_base; clears any other armed brush."""
        self._armed_start_area = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_tutorial_flute(self, slot):
        """Arm the First Flute brush (paint = place/move the single "first
        flute" marker, erase = remove it). Mirrors arm_base; clears any other
        armed brush, including the sibling First Stone brush."""
        self._armed_tutorial_flute = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_tutorial_stone(self, slot):
        """Arm the First Stone brush (paint = place/move the single "first
        stone" marker, erase = remove it). Mirrors arm_base; clears any other
        armed brush, including the sibling First Flute brush."""
        self._armed_tutorial_stone = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def arm_spawn_reserve(self):
        """Arm the Spawnable Background brush (paint = mark the cell with the
        current stage number, erase = clear the mark). Mirrors arm_base,
        but the brush has NO slot — a mark is an invisible overlay, never a
        sprite; clears every other armed brush."""
        self._armed_spawn_reserve = True
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_despawn = None
        self._armed_stage = None
        self._armed_condition = None

    def set_reserve_number(self, n):
        """The stage number newly painted marks carry (palette spinbox)."""
        self._reserve_number = int(n)

    def arm_despawn(self):
        """Arm the Despawnable Spawn brush (paint = mark the cell with the
        current stage number, erase = clear the mark). The exact twin of
        arm_spawn_reserve — no slot, clears every other armed brush."""
        self._armed_despawn = True
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_stage = None
        self._armed_condition = None

    def set_despawn_number(self, n):
        """The stage number newly painted despawn marks carry (palette
        spinbox)."""
        self._despawn_number = int(n)

    def arm_stage(self):
        """Arm the Stage Zones brush (paint = mark the cell with the current
        stage number, erase = clear the mark). The exact twin of arm_despawn —
        no slot, clears every other armed brush."""
        self._armed_stage = True
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_condition = None

    def set_stage_number(self, n):
        """The stage number newly painted stage-zone marks carry (palette
        spinbox)."""
        self._stage_number = int(n)

    def arm_tile_condition(self, name):
        """Arm ONE tile-condition brush (paint = force that condition on the
        cell, erase = clear the mark). The fourth overlay brush, and the only
        one that carries a VALUE rather than a bool: the palette has one button
        per condition NAME, so arming names the condition. Clears every other
        armed brush."""
        self._armed_condition = name
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None
        self._armed_tutorial_flute = None
        self._armed_tutorial_stone = None
        self._armed_spawn_reserve = None
        self._armed_despawn = None
        self._armed_stage = None

    def set_deco_flip(self, on):
        """Mirror-flip toggle for the armed deco brush — an orthogonal
        placement modifier, not tied to which prop is armed, so it persists
        across type/variant switches until the user toggles it off."""
        self._deco_flip_armed = bool(on)

    def set_eye(self, name, on):
        self._eyes[name] = on

    def set_grid_lines(self, on):
        self._grid_lines = on

    def slot_qimage(self, slot_key):
        """Engine-resolved idle frame as a QImage — the palette's icon
        provider (static blit of an engine frame; ED-22-clean)."""
        frame = self._assets.frame(slot_key, "idle", 0)
        return surface_to_qimage(frame.surface)

    # -- tools: cell picking via engine.coords ONLY (E-3) ---------------------

    def _cell_at(self, pos):
        wx, wy = self._coords.screen_to_world(pos.x(), pos.y())
        col, row = math.floor(wx), math.floor(wy)
        doc = self._map_session.doc
        if 0 <= col < doc.cols and 0 <= row < doc.rows:
            return col, row
        return None

    def _tool_press(self, pos):
        cell = self._cell_at(pos)
        if cell is None:
            return
        doc = self._map_session.doc
        self._hover_cell = cell
        if self._armed_base is not None:
            # the Hole is placed like a tile (but only one exists)
            if self._tool == "paint":
                self._map_session.push_base_place(cell[0], cell[1])
            elif self._tool == "erase":
                self._map_session.push_base_remove()
            return
        if self._armed_camera is not None:
            # the camera startpoint is placed like the Hole (single object)
            if self._tool == "paint":
                self._map_session.push_camera_place(cell[0], cell[1])
            elif self._tool == "erase":
                self._map_session.push_camera_remove()
            return
        if self._armed_start_area is not None:
            # the 2×2 starting area is placed like the Hole (single object);
            # the clicked cell becomes its MIN corner (session clamps to fit)
            if self._tool == "paint":
                self._map_session.push_start_area_place(cell[0], cell[1])
            elif self._tool == "erase":
                self._map_session.push_start_area_remove()
            return
        if self._armed_tutorial_flute is not None:
            # the "first flute" marker is placed like the Hole (single
            # object, single tile, no clamp)
            if self._tool == "paint":
                self._map_session.push_tutorial_flute_place(cell[0], cell[1])
            elif self._tool == "erase":
                self._map_session.push_tutorial_flute_remove()
            return
        if self._armed_tutorial_stone is not None:
            # the "first stone" marker is placed like the Hole (single
            # object, single tile, no clamp)
            if self._tool == "paint":
                self._map_session.push_tutorial_stone_place(cell[0], cell[1])
            elif self._tool == "erase":
                self._map_session.push_tutorial_stone_remove()
            return
        if self._eyes["base"] and doc.base is not None \
                and cell == (doc.base["col"], doc.base["row"]):
            self._base_drag = True   # the single draggable map object;
            return                   # hide the base eye to paint under it
        if self._eyes["camera"] and doc.camera_start is not None \
                and cell == (doc.camera_start["col"], doc.camera_start["row"]):
            self._camera_drag = True   # draggable like the base;
            return                     # hide the camera eye to paint under it
        if self._eyes["start_area"] and doc.start_area is not None \
                and doc.start_area["col"] <= cell[0] <= doc.start_area["col"] + 1 \
                and doc.start_area["row"] <= cell[1] <= doc.start_area["row"] + 1:
            self._start_area_drag = True   # any of its 4 cells grabs it;
            return                         # hide the eye to paint under it
        if self._eyes["tutorial"] and doc.tutorial_flute is not None \
                and cell == (doc.tutorial_flute["col"], doc.tutorial_flute["row"]):
            self._tutorial_flute_drag = True   # single tile, no brush armed;
            return                             # hide the eye to paint under it
        if self._eyes["tutorial"] and doc.tutorial_stone is not None \
                and cell == (doc.tutorial_stone["col"], doc.tutorial_stone["row"]):
            self._tutorial_stone_drag = True   # single tile, no brush armed;
            return                             # hide the eye to paint under it
        if self._armed_deco is not None:
            if self._tool == "paint":
                self._map_session.push_deco_place(
                    cell[0], cell[1], self._armed_deco,
                    flip=self._deco_flip_armed)
            elif self._tool == "erase":
                self._map_session.push_deco_remove(cell[0], cell[1])
            return
        if self._armed_spawn_reserve is not None:
            # the spawn reserve is an INVISIBLE OVERLAY, not a legend code —
            # it gets its own ops over doc.spawnable_background, and must be
            # handled BEFORE the terrain-code branches below.
            if self._tool == "picker":
                picked = tilemap_ops.pick_reserve(doc, *cell)
                if picked is not None:
                    self.reserve_number_picked.emit(picked)
            elif self._tool in ("paint", "erase"):
                value = self._reserve_number if self._tool == "paint" else None
                self._reserve_stroke_value = value
                self._reserve_stroke = tilemap_ops.set_reserve(doc, *cell, value)
                self._stroke_last = cell
            elif self._tool in ("line", "rect"):
                self._anchor = cell
            elif self._tool == "bucket":
                self._map_session.push_reserve_stroke(
                    tilemap_ops.reserve_bucket(doc, *cell, self._reserve_number),
                    "spawn reserve bucket fill")
            return
        if self._armed_despawn is not None:
            # the despawn mark is an INVISIBLE OVERLAY too — its own ops over
            # doc.despawnable_spawn, likewise BEFORE the terrain-code branches.
            if self._tool == "picker":
                picked = tilemap_ops.pick_despawn(doc, *cell)
                if picked is not None:
                    self.despawn_number_picked.emit(picked)
            elif self._tool in ("paint", "erase"):
                value = self._despawn_number if self._tool == "paint" else None
                self._despawn_stroke_value = value
                self._despawn_stroke = tilemap_ops.set_despawn(doc, *cell, value)
                self._stroke_last = cell
            elif self._tool in ("line", "rect"):
                self._anchor = cell
            elif self._tool == "bucket":
                self._map_session.push_despawn_stroke(
                    tilemap_ops.despawn_bucket(doc, *cell, self._despawn_number),
                    "spawn despawn bucket fill")
            return
        if self._armed_stage is not None:
            # the stage-zone mark is an INVISIBLE OVERLAY too — its own ops
            # over doc.stage_zones, likewise BEFORE the terrain-code branches.
            if self._tool == "picker":
                picked = tilemap_ops.pick_stage(doc, *cell)
                if picked is not None:
                    self.stage_number_picked.emit(picked)
            elif self._tool in ("paint", "erase"):
                value = self._stage_number if self._tool == "paint" else None
                self._stage_stroke_value = value
                self._stage_stroke = tilemap_ops.set_stage(doc, *cell, value)
                self._stroke_last = cell
            elif self._tool in ("line", "rect"):
                self._anchor = cell
            elif self._tool == "bucket":
                self._map_session.push_stage_stroke(
                    tilemap_ops.stage_bucket(doc, *cell, self._stage_number),
                    "stage zone bucket fill")
            return
        if self._armed_condition is not None:
            # the tile-condition mark is an INVISIBLE OVERLAY too — its own ops
            # over doc.tile_conditions, likewise BEFORE the terrain-code
            # branches. The only difference from the three above: the painted
            # value is the armed condition NAME, not a spinbox number.
            if self._tool == "picker":
                picked = tilemap_ops.pick_condition(doc, *cell)
                if picked is not None:
                    self.condition_picked.emit(picked)
            elif self._tool in ("paint", "erase"):
                value = self._armed_condition if self._tool == "paint" else None
                self._condition_stroke_value = value
                self._condition_stroke = tilemap_ops.set_condition(
                    doc, *cell, value)
                self._stroke_last = cell
            elif self._tool in ("line", "rect"):
                self._anchor = cell
            elif self._tool == "bucket":
                self._map_session.push_condition_stroke(
                    tilemap_ops.condition_bucket(
                        doc, *cell, self._armed_condition),
                    "tile condition bucket fill")
            return
        if self._tool == "picker":
            code = tilemap_ops.pick(doc, *cell)
            if code is not None:
                self.code_picked.emit(code)
            return
        if self._tool == "erase":
            self._stroke_code = tilemap.default_fill_code(doc.legend)
            self._stroke = tilemap_ops.paint(doc, *cell, self._stroke_code)
            self._stroke_last = cell
            return
        if self._armed_code is None:
            return
        if self._tool == "paint":
            self._stroke_code = self._armed_code
            self._stroke = tilemap_ops.paint(doc, *cell, self._stroke_code)
            self._stroke_last = cell
        elif self._tool in ("line", "rect"):
            self._anchor = cell
        elif self._tool == "bucket":
            self._map_session.push_stroke(
                tilemap_ops.bucket_fill(doc, *cell, self._armed_code),
                "bucket fill")

    def _tool_move(self, pos):
        cell = self._cell_at(pos)
        self._hover_cell = cell
        if self._reserve_stroke is not None and cell is not None \
                and cell != self._stroke_last:
            # same Bresenham interpolation as the terrain stroke below
            self._reserve_stroke.extend(tilemap_ops.reserve_line(
                self._map_session.doc, *self._stroke_last, *cell,
                self._reserve_stroke_value))
            self._stroke_last = cell
            return
        if self._despawn_stroke is not None and cell is not None \
                and cell != self._stroke_last:
            # same Bresenham interpolation as the reserve stroke above
            self._despawn_stroke.extend(tilemap_ops.despawn_line(
                self._map_session.doc, *self._stroke_last, *cell,
                self._despawn_stroke_value))
            self._stroke_last = cell
            return
        if self._stage_stroke is not None and cell is not None \
                and cell != self._stroke_last:
            # same Bresenham interpolation as the despawn stroke above
            self._stage_stroke.extend(tilemap_ops.stage_line(
                self._map_session.doc, *self._stroke_last, *cell,
                self._stage_stroke_value))
            self._stroke_last = cell
            return
        if self._condition_stroke is not None and cell is not None \
                and cell != self._stroke_last:
            # same Bresenham interpolation as the stage stroke above
            self._condition_stroke.extend(tilemap_ops.condition_line(
                self._map_session.doc, *self._stroke_last, *cell,
                self._condition_stroke_value))
            self._stroke_last = cell
            return
        if self._stroke is not None and cell is not None \
                and cell != self._stroke_last:
            # Bresenham-interpolate between events so fast drags don't gap
            self._stroke.extend(tilemap_ops.line(
                self._map_session.doc, *self._stroke_last, *cell,
                self._stroke_code))
            self._stroke_last = cell

    def _tool_release(self, pos):
        cell = self._cell_at(pos)
        doc = self._map_session.doc
        if self._base_drag:
            if cell is not None:
                self._map_session.push_base_place(cell[0], cell[1])
            self._base_drag = False
        elif self._camera_drag:
            if cell is not None:
                self._map_session.push_camera_place(cell[0], cell[1])
            self._camera_drag = False
        elif self._start_area_drag:
            if cell is not None:
                # release cell becomes the new MIN corner (session clamps)
                self._map_session.push_start_area_place(cell[0], cell[1])
            self._start_area_drag = False
        elif self._tutorial_flute_drag:
            if cell is not None:
                self._map_session.push_tutorial_flute_place(cell[0], cell[1])
            self._tutorial_flute_drag = False
        elif self._tutorial_stone_drag:
            if cell is not None:
                self._map_session.push_tutorial_stone_place(cell[0], cell[1])
            self._tutorial_stone_drag = False
        elif self._reserve_stroke is not None:
            self._map_session.push_reserve_stroke(
                self._reserve_stroke, "spawn reserve stroke")
            self._reserve_stroke = None
            self._stroke_last = None
        elif self._despawn_stroke is not None:
            self._map_session.push_despawn_stroke(
                self._despawn_stroke, "spawn despawn stroke")
            self._despawn_stroke = None
            self._stroke_last = None
        elif self._stage_stroke is not None:
            self._map_session.push_stage_stroke(
                self._stage_stroke, "stage zone stroke")
            self._stage_stroke = None
            self._stroke_last = None
        elif self._condition_stroke is not None:
            self._map_session.push_condition_stroke(
                self._condition_stroke, "tile condition stroke")
            self._condition_stroke = None
            self._stroke_last = None
        elif self._stroke is not None:
            self._map_session.push_stroke(self._stroke, "paint stroke")
            self._stroke = None
            self._stroke_last = None
        elif self._anchor is not None:
            if cell is not None:
                if self._armed_spawn_reserve is not None:
                    op = (tilemap_ops.reserve_line if self._tool == "line"
                          else tilemap_ops.reserve_rect)
                    self._map_session.push_reserve_stroke(
                        op(doc, *self._anchor, *cell, self._reserve_number),
                        f"spawn reserve {self._tool}")
                elif self._armed_despawn is not None:
                    op = (tilemap_ops.despawn_line if self._tool == "line"
                          else tilemap_ops.despawn_rect)
                    self._map_session.push_despawn_stroke(
                        op(doc, *self._anchor, *cell, self._despawn_number),
                        f"spawn despawn {self._tool}")
                elif self._armed_stage is not None:
                    op = (tilemap_ops.stage_line if self._tool == "line"
                          else tilemap_ops.stage_rect)
                    self._map_session.push_stage_stroke(
                        op(doc, *self._anchor, *cell, self._stage_number),
                        f"stage zone {self._tool}")
                elif self._armed_condition is not None:
                    op = (tilemap_ops.condition_line if self._tool == "line"
                          else tilemap_ops.condition_rect)
                    self._map_session.push_condition_stroke(
                        op(doc, *self._anchor, *cell, self._armed_condition),
                        f"tile condition {self._tool}")
                else:
                    op = (tilemap_ops.line if self._tool == "line"
                          else tilemap_ops.rect_fill)
                    self._map_session.push_stroke(
                        op(doc, *self._anchor, *cell, self._armed_code),
                        self._tool)
            self._anchor = None

    def _ghost_items(self, doc):
        """Armed brush preview under the cursor (ED-20 ghost) — tinted
        engine sprites on the overlay layer, snapped to the grid."""
        cell = self._hover_cell
        if cell is None:
            return
        if self._base_drag:
            yield RenderItem(doc.base["slot"], cell, layer="overlay",
                             tint=GHOST_TINT)
            return
        if self._camera_drag:
            yield RenderItem(doc.camera_start["slot"], cell, layer="overlay",
                             tint=GHOST_TINT)
            return
        if self._start_area_drag or self._armed_start_area is not None:
            return   # its ghost is an OUTLINE, drawn by _submit_map_items
        if (self._tutorial_flute_drag or self._tutorial_stone_drag
                or self._armed_tutorial_flute is not None
                or self._armed_tutorial_stone is not None):
            return   # its ghost is an OUTLINE, drawn by _submit_map_items
        if self._armed_spawn_reserve is not None:
            return   # its ghost is the OUTLINE drawn by the reserve overlay
        if self._armed_despawn is not None:
            return   # its ghost is the OUTLINE drawn by the despawn overlay
        if self._armed_stage is not None:
            return   # its ghost is the OUTLINE drawn by the stage-zone overlay
        if self._armed_condition is not None:
            return   # its ghost is the OUTLINE drawn by the condition overlay
        if self._tool == "none":
            return   # no active brush — nothing would actually be placed
        if self._armed_base is not None:
            if self._tool == "paint":
                yield RenderItem(self._armed_base, cell, layer="overlay",
                                 tint=GHOST_TINT)
            return
        if self._armed_camera is not None:
            if self._tool == "paint":
                yield RenderItem(self._armed_camera, cell, layer="overlay",
                                 tint=GHOST_TINT)
            return
        if self._armed_deco is not None:
            yield RenderItem(self._armed_deco, cell, layer="overlay",
                             tint=GHOST_TINT, flip=self._deco_flip_armed)
            return
        if self._armed_code is None and self._tool != "erase":
            return
        if self._tool == "picker":
            return
        code = (tilemap.default_fill_code(doc.legend)
                if self._tool == "erase" else self._armed_code)
        if self._anchor is not None and self._tool in ("line", "rect"):
            cells_fn = (tilemap_ops.line_cells if self._tool == "line"
                        else tilemap_ops.rect_cells)
            cells = cells_fn(*self._anchor, *cell)
        else:
            cells = [cell]
        for c, r in cells:
            if 0 <= c < doc.cols and 0 <= r < doc.rows:
                yield RenderItem(tilemap.slot_for_code(doc.legend, code, c, r),
                                 (c, r), layer="overlay", tint=GHOST_TINT)

    def _refresh_anim_combo(self):
        animations = self.preview_animations()
        combo = self._anim_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(list(animations))
        if self.preview_animation not in animations:
            self.preview_animation = animations[0] if animations else "idle"
            self._reset_anim_clock()
        if animations:
            combo.setCurrentText(self.preview_animation)
        combo.blockSignals(False)
        combo.setVisible(bool(animations))

    # -- anchor handles (ESV-2): entity-preview fallback only, ED-22 clean --
    # A VIEW of the panel's mapping (self._anchors) plus a live drag delta;
    # never reads or writes the manifest here (that's anchor_ops + the panel).

    def _preview_draw_fit(self):
        """(fit_tiles, scale) the current `preview_slot` draws at — the ONE
        value both the preview `RenderItem` and `_anchor_draw_params` read
        (fix-editor-preview-footprint §2.3): they must never compute this
        independently, or the handle and the sprite can desync again exactly
        like the bug this fix closes.

        Returns the MEMOIZED pair. `slot_draw_fit` re-reads and re-validates
        slots.json + enemies.json from disk, which is far too expensive to do
        per call: this is read once per rendered frame, once per anchor
        hit-test, and once per mouse-move while a handle is being dragged.
        Resolving it eagerly instead (`_resolve_draw_fit`, on slot change and
        on registry reload — the only two things that can change the answer)
        keeps handle-dragging interactive."""
        return self._draw_fit

    def _resolve_draw_fit(self):
        """Recompute the memoized `_draw_fit`. `(0.0, 1.0)` (the RenderItem
        defaults) when there is no preview slot, or the slot is not (yet)
        declared in the registry — E-37, never raise."""
        if self.preview_slot is None:
            self._draw_fit = (0.0, 1.0)
            return
        try:
            category_key = self._registry.category_of(self.preview_slot).key
        except KeyError:
            self._draw_fit = (0.0, 1.0)
            return
        self._draw_fit = slot_draw_fit(
            self._data_dir, category_key, self.preview_slot)

    def _anchor_draw_params(self):
        """(origin, s, zoom) for the current preview slot's frame anchor,
        origin COMPOSED with the entry's offset_x/offset_y (§1.2 — the
        renderer already nudges the art by this, so the handle must move
        with it or it stops sitting on the sprite) — None when there is
        nothing to anchor a handle to. `s` is the editor's OWN drawn scale:
        fit_factor computed from the exact fit_tiles/scale the preview's
        RenderItem carries — `_preview_draw_fit()`, the SAME call the
        preview submission below reads, so they cannot drift apart.

        fix-anchor-origin-parity: `origin` resolves through the SAME shared
        `engine.render.sprite_anchor_screen` the game's `game.anchors.
        anchor_world_point` calls (`anchor_xy=(0, 0)` -> the sprite's drawn
        CENTRE) — never hand-rolled here, so the handle and the game's
        anchor resolution cannot drift apart again."""
        if self.preview_slot is None:
            return None
        g = self._coords.geometry
        wx, wy = g.map_cols // 2, g.map_rows // 2
        frame_w, _frame_h = self._assets.frame_size(self.preview_slot)
        zoom = self._coords.camera.zoom
        fit_tiles, scale = self._preview_draw_fit()
        s = fit_factor(frame_w, g.tile_w, fit_tiles) * scale
        ox, oy = self._assets.offset(self.preview_slot)
        origin = sprite_anchor_screen(
            self._coords, wx, wy, frame_w, fit_tiles, scale, (ox, oy), (0.0, 0.0))
        return origin, s, zoom

    def _hit_anchor_handle(self, pos):
        """Topmost handle within HANDLE_HIT_PX SCREEN pixels of `pos`
        (Euclidean), reverse submission order — the same rule _hit_widget
        uses in screen mode (§1.5)."""
        params = self._anchor_draw_params()
        if params is None:
            return None
        origin, s, zoom = params
        for name in reversed(list(self._anchors)):
            ax, ay = self._anchors[name]
            sx, sy = anchor_ops.screen_point(origin, ax, ay, s, zoom)
            if math.hypot(pos.x() - sx, pos.y() - sy) <= HANDLE_HIT_PX:
                return name
        return None

    def _anchor_press(self, pos):
        """LEFT-press hit test: on a handle, starts a drag AND selects it
        (emits to the panel), so the caller can suppress the pan it would
        otherwise start (§1.5). Returns True when a handle was grabbed."""
        name = self._hit_anchor_handle(pos)
        if name is None:
            return False
        self._anchor_selected = name
        self.anchor_selected.emit(name)
        self._anchor_drag = (name, *self._anchors[name])
        return True

    def _anchor_move(self, pos):
        if self._anchor_drag is None:
            return
        params = self._anchor_draw_params()
        if params is None:
            return
        name = self._anchor_drag[0]
        origin, s, zoom = params
        ax, ay = anchor_ops.frame_px(origin, pos.x(), pos.y(), s, zoom)
        ax = max(-4096, min(4096, ax))
        ay = max(-4096, min(4096, ay))
        self._anchors[name] = (ax, ay)
        self.anchor_dragged.emit(name, ax, ay)

    def _anchor_release(self):
        """Commit ONE write per gesture (§1.5) — only when the value
        actually moved; a click that produced no change only selected."""
        if self._anchor_drag is None:
            return
        name, orig_x, orig_y = self._anchor_drag
        self._anchor_drag = None
        x, y = self._anchors.get(name, (orig_x, orig_y))
        if (x, y) != (orig_x, orig_y):
            self.anchor_drag_finished.emit(name, x, y)

    def _submit_muzzle_projectile(self):
        """feat-projectile-anchored-flight §3.2: when the previewed slot's
        `muzzle` anchor is authored, draw the projectile AT that handle's
        real screen point/size — dragging the handle then shows exactly
        where the shot leaves the barrel. Resolves the handle point through
        `_anchor_draw_params()`/`anchor_ops.screen_point`, the SAME call
        `_submit_anchor_handles` itself uses — never a second computation.
        Uses `vfx_projectile` art when imported, else the stone dot — the
        SAME `assets.animation_total_ms(slot, "idle") is not None` "has
        art" signal the game reads, so the two can never disagree about
        "imported". Called BEFORE `_submit_anchor_handles()` (§ caller
        order) so the crosshair stays on top of the dot."""
        if "muzzle" not in self._anchors:
            return
        params = self._anchor_draw_params()
        if params is None:
            return
        origin, s, zoom = params
        ax, ay = self._anchors["muzzle"]
        sx, sy = anchor_ops.screen_point(origin, ax, ay, s, zoom)
        pr = self._projectile_params
        size = max(2, int(pr.stone_size * zoom))
        dest = (int(sx - size / 2), int(sy - size / 2))
        has_art = (self._assets.animation_total_ms("vfx_projectile", "idle")
                  is not None)
        if has_art:
            self._renderer.submit_hud(
                HudSprite("vfx_projectile", dest, (size, size)))
        else:
            self._renderer.submit_hud(HudRect(
                (dest[0], dest[1], size, size), pr.stone_color,
                border_radius=size // 2))

    def _submit_anchor_handles(self):
        params = self._anchor_draw_params()
        if params is None:
            return
        origin, s, zoom = params
        for name, (ax, ay) in self._anchors.items():
            sx, sy = anchor_ops.screen_point(origin, ax, ay, s, zoom)
            if self._anchor_drag is not None and self._anchor_drag[0] == name:
                color = ANCHOR_DRAG_COLOR
            elif self._anchor_selected == name:
                color = ANCHOR_SELECTED_COLOR
            else:
                color = ANCHOR_COLOR
            self._submit_anchor_marker(sx, sy, color)
            self._renderer.submit_hud(HudText(
                name, (sx + HANDLE_RADIUS_PX + 4, sy - 6), "sm", color))

    def _submit_anchor_marker(self, sx, sy, color):
        """A fixed-SCREEN-size closed outline + crosshair, submitted in
        WORLD points (§2.3c — the two-sample screen_to_world trick, ESV-1's
        proven pattern; never hand-derive the per-axis deltas)."""
        cs = self._coords
        wx0, wy0 = cs.screen_to_world(sx, sy)
        wx1, wy1 = cs.screen_to_world(sx + HANDLE_RADIUS_PX, sy + HANDLE_RADIUS_PX)
        dwx, dwy = wx1 - wx0, wy1 - wy0
        self._renderer.submit_overlay_lines(
            ((wx0 - dwx, wy0 - dwy), (wx0 + dwx, wy0 - dwy),
             (wx0 + dwx, wy0 + dwy), (wx0 - dwx, wy0 + dwy)),
            color, width=2, closed=True)
        self._renderer.submit_overlay_lines(
            ((wx0 - dwx, wy0), (wx0 + dwx, wy0)), color, width=2)
        self._renderer.submit_overlay_lines(
            ((wx0, wy0 - dwy), (wx0, wy0 + dwy)), color, width=2)

    # -- surface lifecycle, sized to the widget -----------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_surface()

    def _resize_surface(self):
        w, h = max(1, self.width()), max(1, self.height())
        self._surface = pygame.Surface((w, h))
        if self.in_map_mode():
            self._center_on_camera_start(w, h)
        elif not self.in_screen_mode():
            # screen mode needs no camera — its scale/offset is recomputed
            # fresh every render_frame from the widget's CURRENT size
            self._center_on_preview(w, h)

    def _center_on_preview(self, w, h):
        """Entity preview mode: park the camera on the preview tile
        (grid/map centre) so the sprite sits centred even when the grid is
        wider than the viewport — clamp alone would anchor it to an edge."""
        g = self._coords.geometry
        self._coords.center_on(g.map_cols // 2, g.map_rows // 2, w, h)

    def _center_on_camera_start(self, w, h):
        """Tilemap mode: open (and re-frame on resize) centred on the map's
        own camera-startpoint — the same view `game/main.py:frame_camera()`
        opens on — falling back to `clamp` (centres if the map fits, else
        anchors) when no startpoint has been painted yet."""
        cam = self._map_session.doc.camera_start
        if cam is not None:
            self._coords.center_on(cam["col"], cam["row"], w, h)
        else:
            self._coords.clamp(w, h)

    # -- frame drive: main.py's QTimer calls this once per tick -------------

    def render_frame(self):
        t0 = time.perf_counter()
        self._surface.fill(BACKGROUND)
        if self.in_map_mode():
            self._submit_map_items()
        elif self.in_screen_mode():
            self._render_screen_frame(t0)
        else:
            g = self._coords.geometry
            for row in range(g.map_rows):
                for col in range(g.map_cols):
                    self._renderer.submit(RenderItem("ground_tile", (col, row), layer="ground"))
            if self.preview_slot is not None:
                if self._anim_last_t is not None:
                    self._anim_ms += (t0 - self._anim_last_t) * 1000.0
                self._anim_last_t = t0
                fit_tiles, scale = self._preview_draw_fit()
                self._renderer.submit(RenderItem(
                    self.preview_slot,
                    (g.map_cols // 2, g.map_rows // 2),
                    layer="entities",
                    animation=self.preview_animation,
                    anim_time_ms=int(self._anim_ms),
                    fit_tiles=fit_tiles,
                    scale=scale,
                ))
                self._submit_muzzle_projectile()
                self._submit_anchor_handles()
        self._renderer.flush(self._surface)
        self._qimage = surface_to_qimage(self._surface)
        self.update()
        self.last_frame_ms = (time.perf_counter() - t0) * 1000.0

    def _submit_map_items(self):
        """ED-20: the open doc through engine.tilemap (layer eyes + zone
        tints), the ghost preview, and grid lines via the E-24 primitive.
        Windowed culling (same as game/main.py) keeps large maps interactive:
        only the on-screen tile range is generated/submitted."""
        doc = self._map_session.doc
        w, h = self.width(), self.height()
        cmin, cmax, rmin, rmax = self._coords.visible_tile_window(w, h, margin=4)
        for item in tilemap.visible_render_items(
                doc, cmin, cmax, rmin, rmax,
                terrain=self._eyes["terrain"],
                base=self._eyes["base"],
                deco=self._eyes["deco"],
                camera=self._eyes["camera"],
                tint_for_code=ZONE_TINTS if self._eyes["tint"] else None):
            self._renderer.submit(item)
        for item in self._ghost_items(doc):
            self._renderer.submit(item)
        self._submit_start_area_outline(doc)
        self._submit_tutorial_outline(doc)
        self._submit_spawn_reserve(doc, cmin, cmax, rmin, rmax)
        self._submit_despawn(doc, cmin, cmax, rmin, rmax)
        self._submit_stage_zones(doc, cmin, cmax, rmin, rmax)
        self._submit_tile_conditions(doc, cmin, cmax, rmin, rmax)
        if self._grid_lines:
            # bound the grid to the visible window too (a 1024-line full grid
            # would swamp the overlay pass)
            c0, c1 = max(0, cmin), min(doc.cols, cmax)
            r0, r1 = max(0, rmin), min(doc.rows, rmax)
            for r in range(r0, r1 + 1):
                self._renderer.submit_overlay_lines(
                    ((c0, r), (c1, r)), GRID_COLOR)
            for c in range(c0, c1 + 1):
                self._renderer.submit_overlay_lines(
                    ((c, r0), (c, r1)), GRID_COLOR)

    def _submit_start_area_outline(self, doc):
        """The 2×2 starting area draws as a closed OUTLINE through the E-24
        overlay primitive (never a sprite — ED-22-clean, same as grid lines):
        the placed marker when its eye is on, plus a ghost outline at the
        (clamped) hover cell while its brush is armed with the paint tool or
        during a drag."""
        def outline(col, row, color):
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 2, row), (col + 2, row + 2), (col, row + 2)),
                color, width=2, closed=True)

        if self._eyes["start_area"] and doc.start_area is not None \
                and not self._start_area_drag:
            outline(doc.start_area["col"], doc.start_area["row"],
                    START_AREA_COLOR)
        ghosting = (self._start_area_drag
                    or (self._armed_start_area is not None
                        and self._tool == "paint"))
        if ghosting and self._hover_cell is not None:
            col = max(0, min(self._hover_cell[0], doc.cols - 2))
            row = max(0, min(self._hover_cell[1], doc.rows - 2))
            outline(col, row, START_AREA_GHOST_COLOR)

    def _submit_tutorial_outline(self, doc):
        """The tutorial markers ("first flute" / "first stone") each draw as a
        single-tile closed OUTLINE through the E-24 overlay primitive (never
        a sprite — mirrors _submit_start_area_outline), with a labeled
        HudText caption above it (the screen-mode selection caption idiom,
        _submit_screen_selection): the placed marker when the tutorial eye
        is on, plus a ghost outline+caption at the (clamped) hover cell while
        its brush is armed with the paint tool or during a drag."""
        def outline(col, row, color):
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)),
                color, width=2, closed=True)

        def caption(col, row, label, color):
            sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)
            self._renderer.submit_hud(
                HudText(label, (sx, sy - 14), "sm", color, align="center"))

        for marker, label, dragging, armed in (
                (doc.tutorial_flute, "First Flute",
                 self._tutorial_flute_drag, self._armed_tutorial_flute),
                (doc.tutorial_stone, "First Stone",
                 self._tutorial_stone_drag, self._armed_tutorial_stone)):
            if self._eyes["tutorial"] and marker is not None and not dragging:
                outline(marker["col"], marker["row"], TUTORIAL_COLOR)
                caption(marker["col"], marker["row"], label, TUTORIAL_COLOR)
            ghosting = dragging or (armed is not None and self._tool == "paint")
            if ghosting and self._hover_cell is not None:
                col = max(0, min(self._hover_cell[0], doc.cols - 1))
                row = max(0, min(self._hover_cell[1], doc.rows - 1))
                outline(col, row, TUTORIAL_GHOST_COLOR)
                caption(col, row, label, TUTORIAL_GHOST_COLOR)

    def _submit_spawn_reserve(self, doc, cmin, cmax, rmin, rmax):
        """The spawnable-background marks: per mark a single-tile closed
        diamond OUTLINE through the E-24 overlay primitive plus a `HudText`
        of its STAGE NUMBER at the tile centre — never a sprite, never
        QPainter (the _submit_tutorial_outline idiom). The marks are
        editor-only chrome: the game draws nothing for them.

        WINDOW-CULLED against the caller's visible tile window: a map may
        carry hundreds of marks, and drawing them all would put a full-map
        overlay pass back into a renderer that windows everything else.
        Iterates the MARKS (a dict of painted cells) and filters, rather
        than the window — the marks are almost always the smaller set."""
        if not self._eyes["spawn_reserve"]:
            return
        for (col, row), number in doc.spawnable_background.items():
            if not (cmin <= col <= cmax and rmin <= row <= rmax):
                continue
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)),
                RESERVE_COLOR, width=2, closed=True)
            sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)
            self._renderer.submit_hud(HudText(
                str(number), (sx, sy - 6), "sm", RESERVE_COLOR, align="center"))

    def _submit_despawn(self, doc, cmin, cmax, rmin, rmax):
        """The despawnable-spawn marks: the exact twin of
        _submit_spawn_reserve — a single-tile closed diamond OUTLINE through
        the E-24 overlay primitive plus a `HudText` of its STAGE NUMBER,
        in DESPAWN_COLOR (magenta) so it can never be mistaken for a
        spawn-reserve mark (cyan). Editor-only chrome; the game draws nothing.

        WINDOW-CULLED against the caller's visible tile window for the same
        reason the reserve overlay is."""
        if not self._eyes["despawnable_spawn"]:
            return
        for (col, row), number in doc.despawnable_spawn.items():
            if not (cmin <= col <= cmax and rmin <= row <= rmax):
                continue
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)),
                DESPAWN_COLOR, width=2, closed=True)
            sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)
            self._renderer.submit_hud(HudText(
                str(number), (sx, sy + 4), "sm", DESPAWN_COLOR, align="center"))

    def _submit_stage_zones(self, doc, cmin, cmax, rmin, rmax):
        """The stage-zone marks: the third twin of _submit_spawn_reserve — a
        single-tile closed diamond OUTLINE through the E-24 overlay primitive
        plus a `HudText` of its STAGE NUMBER, in STAGE_COLOR (lime) so it can
        never be mistaken for a reserve (cyan) or despawn (magenta) mark. Its
        number sits BELOW both of theirs (reserve above the centre, despawn
        just below it, stage lower still) so a cell carrying all three marks
        stays readable. Editor-only chrome; the game draws nothing.

        WINDOW-CULLED against the caller's visible tile window for the same
        reason the other two overlays are."""
        if not self._eyes["stage_zones"]:
            return
        for (col, row), number in doc.stage_zones.items():
            if not (cmin <= col <= cmax and rmin <= row <= rmax):
                continue
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)),
                STAGE_COLOR, width=2, closed=True)
            sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)
            self._renderer.submit_hud(HudText(
                str(number), (sx, sy + 14), "sm", STAGE_COLOR, align="center"))

    def _submit_tile_conditions(self, doc, cmin, cmax, rmin, rmax):
        """The tile-condition marks: the FOURTH twin of _submit_spawn_reserve —
        a single-tile closed diamond OUTLINE through the E-24 overlay primitive
        plus a `HudText` label, one hue per condition NAME (CONDITION_COLORS)
        so the four are tellable apart from each other and from the reserve
        (cyan) / despawn (magenta) / stage (lime) marks. Its label sits BELOW
        all three of their numbers (reserve sy-6, despawn sy+4, stage sy+14,
        condition sy+24) so a cell carrying all four marks stays readable.
        Editor-only chrome; the game draws nothing for the mark itself.

        WINDOW-CULLED against the caller's visible tile window for the same
        reason the other three overlays are."""
        if not self._eyes["tile_conditions"]:
            return
        for (col, row), name in doc.tile_conditions.items():
            if not (cmin <= col <= cmax and rmin <= row <= rmax):
                continue
            color = CONDITION_COLORS.get(name, CONDITION_DEFAULT_COLOR)
            self._renderer.submit_overlay_lines(
                ((col, row), (col + 1, row), (col + 1, row + 1), (col, row + 1)),
                color, width=2, closed=True)
            sx, sy = self._coords.world_to_screen(col + 0.5, row + 0.5)
            self._renderer.submit_hud(HudText(
                name.upper(), (sx, sy + 24), "sm", color, align="center"))

    # -- screen mode rendering (B4, R3) — ALL through submit_hud (ED-22) -----

    def _screen_canvas(self):
        """The reusable logical canvas, always exactly the CURRENT
        SCREEN_W x SCREEN_H (re-allocated if `data/display.json` changed the
        resolution under us — never a literal size)."""
        size = (SCREEN_W, SCREEN_H)
        if self._screen_canvas_surface is None \
                or self._screen_canvas_surface.get_size() != size:
            self._screen_canvas_surface = pygame.Surface(size)
        return self._screen_canvas_surface

    def _render_screen_frame(self, t0):
        """UR-3: render the screen at its LOGICAL size, then scale the
        finished surface once — the same pipeline shape `game/main.py` gets
        from `pygame.SCALED`.

        Scaling the geometry instead (what this did before) left `HudText` at
        its absolute font-preset pixel size while every box around it grew or
        shrank, so the editor's label/box ratio was wrong by exactly 1/scale
        and a designer comparing the two would re-tune fonts that are already
        right. `HudText` carries no scale field, so the only parity-true fix
        is to scale the whole rendered surface.

        Editor chrome (selection outline, handles, caption, the E-37
        placeholder, the letterbox edge) is deliberately NOT scaled: it is
        submitted afterwards in SCREEN pixels and flushed by `render_frame`'s
        own flush — two flushes, one Renderer (ED-22), because `flush` clears
        the queue."""
        scale, ox, oy = self._screen_scale_offset()
        canvas = self._screen_canvas()
        canvas.fill(BACKGROUND)
        self._submit_screen_items(t0, 1.0, 0.0, 0.0)
        self._renderer.flush(canvas)
        scaled = pygame.transform.scale(
            canvas, (round(SCREEN_W * scale), round(SCREEN_H * scale)))
        self._surface.blit(scaled, (int(ox), int(oy)))
        self._submit_screen_chrome(scale, ox, oy)

    def _submit_screen_items(self, t0, scale, ox, oy):
        """The screen's CONTENT (background + widgets). Called with the
        identity triple (1.0, 0, 0) because it draws into the logical canvas;
        the `(scale, ox, oy)` parameters stay so `_to_screen_rect` remains the
        one placement rule shared with hit-testing."""
        defaults = self._current_screen_defaults()
        if not defaults:
            return          # E-37 placeholder is chrome — see below
        if self._screen_anim_last_t is not None:
            self._screen_anim_ms += (t0 - self._screen_anim_last_t) * 1000.0
        self._screen_anim_last_t = t0
        doc = self._screen_session.doc
        self._submit_screen_background(doc, scale, ox, oy)
        for widget_id, spec in defaults.get("widgets", {}).items():
            self._submit_screen_widget(widget_id, spec, doc, scale, ox, oy)

    def _submit_screen_chrome(self, scale, ox, oy):
        """Editor-only overlay, in SCREEN pixels at a fixed size: the canvas
        edge, the selection outline/handles/caption, and the E-37 message."""
        defaults = self._current_screen_defaults()
        if not defaults:
            # E-37: no data/ui/screen_defaults.json yet (pre-B3, or a broken
            # dev machine) — a placeholder message, no raise, every widget
            # interaction upstream of here already checks the same defaults.
            cx = ox + (SCREEN_W * scale) / 2
            cy = oy + (SCREEN_H * scale) / 2
            self._renderer.submit_hud(HudText(
                "no layout defaults yet — click Refresh Layouts",
                (cx, cy), "lg", NO_DEFAULTS_COLOR, align="center"))
        self._submit_screen_letterbox(scale, ox, oy)
        if defaults and self._selected_widget is not None \
                and self._selected_widget in defaults.get("widgets", {}):
            self._submit_screen_selection(self._selected_widget, defaults,
                                          scale, ox, oy)

    def _submit_screen_letterbox(self, scale, ox, oy):
        """A muted 1px frame on the drawn canvas edge, so the letterbox bars
        are visibly outside it — at 640x360 in a wide dock those bars are
        large, and a dark screen background otherwise reads as 'the canvas is
        the whole panel'."""
        w, h = SCREEN_W * scale, SCREEN_H * scale
        self._renderer.submit_hud(HudLines(
            ((ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h)),
            LETTERBOX_EDGE_COLOR, width=1, closed=True))

    def _submit_screen_background(self, doc, scale, ox, oy):
        """Background comes ONLY from the open doc's own override — the
        committed screen_defaults.schema.json carries layout (rect/kind/
        label) only, no default background/styling (B1's landed shape)."""
        background = doc.get("background")
        if not background:
            return
        dest = self._to_screen_rect((0, 0, SCREEN_W, SCREEN_H), scale, ox, oy)
        if "slot" in background:
            self._renderer.submit_hud(HudSprite(
                background["slot"], (dest[0], dest[1]), (dest[2], dest[3])))
        elif "color" in background:
            self._renderer.submit_hud(HudRect(dest, tuple(background["color"])))

    def _submit_screen_widget(self, widget_id, spec, doc, scale, ox, oy):
        override = doc.get("widgets", {}).get(widget_id, {})
        if override.get("visible") is False:
            return
        rect = override.get("rect", spec["rect"])
        kind = spec["kind"]
        label = override.get("label", spec["label"])
        dest = self._to_screen_rect(rect, scale, ox, oy)
        style = doc.get("defaults", {})
        skin = override.get("skin")
        if skin is None:
            if kind == "button":
                skin = style.get("button_skin")
            elif kind == "panel":
                skin = style.get("panel_skin")
        font_key = override.get("font", style.get("font", "md"))
        text_color = override.get("text_color", style.get("text_color"))
        if skin:
            # D6/UH-6: tint from the widget's own `tint` key — `color` on a
            # skinned widget is INERT in the game (skinning.py's
            # button_kwargs docstring), so tinting from it here was an
            # editor lie (the editor showed a color the game ignored).
            tint = tuple(override["tint"]) if "tint" in override else None
            self._renderer.submit_hud(HudSprite(
                skin, (dest[0], dest[1]), (dest[2], dest[3]), tint,
                animation=self._screen_state,
                anim_time_ms=int(self._screen_anim_ms)))
            label_item = _screen_primitives.centered_label_item(
                dest, label, font_key,
                tuple(text_color) if text_color is not None else (255, 255, 255))
            if label_item is not None:
                self._renderer.submit_hud(label_item)
        else:
            fill = tuple(override["color"]) if "color" in override else None
            for item in _screen_primitives.fallback_hud_items(
                    dest, kind, label, font_key=font_key,
                    text_color=text_color, fill=fill):
                self._renderer.submit_hud(item)

    def _submit_screen_selection(self, widget_id, defaults, scale, ox, oy):
        x, y, w, h = self._to_screen_rect(
            self._effective_rect(widget_id, defaults), scale, ox, oy)
        self._renderer.submit_hud(HudLines(
            ((x, y), (x + w, y), (x + w, y + h), (x, y + h)),
            SELECTION_COLOR, width=2, closed=True))
        half = HANDLE_PX / 2
        for cx, cy in ((x, y), (x + w, y), (x, y + h), (x + w, y + h)):
            self._renderer.submit_hud(HudRect(
                (cx - half, cy - half, HANDLE_PX, HANDLE_PX), HANDLE_COLOR))
        # UH-4: a small caption above the outline naming the selected widget
        # (display name, falls back to the code id — D4, `widget_display_name`
        # is the ONE resolution rule shared with the widget list). Clamped to
        # the canvas top (`oy`) so a widget at y=0 still shows a caption.
        name = _screen_primitives.widget_display_name(
            widget_id, defaults.get("widgets", {}).get(widget_id))
        caption_y = max(oy, y - 14)
        self._renderer.submit_hud(HudText(
            name, (x, caption_y), "sm", SELECTION_COLOR))

    def paintEvent(self, event):
        if self._qimage is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._qimage)
        if not self.in_map_mode() and not self.in_screen_mode() \
                and self.preview_slot is None:
            self._paint_empty_state(painter)

    def _paint_empty_state(self, painter):
        """Nothing selected in the tree: a large centred brand logo with
        pixel-font title/subtitle underneath, instead of a bare grey grid."""
        if self._logo_pixmap.isNull():
            return
        w, h = self.width(), self.height()
        logo = self._logo_pixmap.scaledToHeight(
            min(h // 2, 220), Qt.TransformationMode.SmoothTransformation)
        logo_x = (w - logo.width()) // 2
        logo_y = (h - logo.height()) // 2 - 40
        painter.drawPixmap(logo_x, logo_y, logo)

        title_font = QFont("Consolas", 22, QFont.Weight.Bold)
        title_font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        subtitle_font = QFont("Consolas", 13, QFont.Weight.Bold)
        subtitle_font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)

        title_y = logo_y + logo.height() + 36
        painter.setFont(title_font)
        painter.setPen(Qt.GlobalColor.white)
        painter.drawText(0, title_y, w, 32, Qt.AlignmentFlag.AlignHCenter,
                          "drunken robot editor")

        painter.setFont(subtitle_font)
        painter.drawText(0, title_y + 30, w, 24, Qt.AlignmentFlag.AlignHCenter,
                          "drunken donuts")

    # -- input (ED-23): drag pan, wheel zoom — engine.coords only -----------
    # Entity preview: EITHER button pans (left is an editor-only addition
    # for devices without a right button). Tilemap mode: LEFT drives the
    # armed tool and RIGHT pans (ED-23 / game "same feel") — EXCEPT under the
    # "none" tool (inspect mode), where a left-drag that didn't grab the base
    # pans too, so you can move the camera without a brush armed.
    _PAN_BUTTONS = Qt.MouseButton.RightButton | Qt.MouseButton.LeftButton

    def mousePressEvent(self, event):
        if self.in_map_mode():
            if event.button() == Qt.MouseButton.LeftButton:
                self._tool_press(event.position())
                # "none" tool that didn't start a base/start-area/tutorial
                # drag → left-drag pans.
                if self._tool == "none" and not self._base_drag \
                        and not self._start_area_drag \
                        and not self._tutorial_flute_drag \
                        and not self._tutorial_stone_drag:
                    self._drag_pos = event.position()
            elif event.button() == Qt.MouseButton.RightButton:
                self._drag_pos = event.position()
            return
        if self.in_screen_mode():
            self._screen_press(event)
            return
        # ESV-2: a LEFT-press on a handle grabs it (drag + select) and
        # suppresses the pan below; RIGHT never grabs a handle (§1.5).
        if event.button() == Qt.MouseButton.LeftButton \
                and self._anchor_press(event.position()):
            return
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self._drag_pos = event.position()

    def mouseMoveEvent(self, event):
        pos = event.position()
        wx, wy = self._coords.screen_to_world(pos.x(), pos.y())
        self.cursor_world.emit(wx, wy)   # ED-23 world-coordinate readout
        if self.in_map_mode():
            # _drag_pos is set only for a pan gesture (RIGHT always, or a
            # LEFT-drag under the "none" tool); a live brush stroke leaves it
            # None and falls through to the tool.
            if self._drag_pos is not None and \
                    (event.buttons() & self._PAN_BUTTONS):
                dx, dy = pos.x() - self._drag_pos.x(), pos.y() - self._drag_pos.y()
                self._drag_pos = pos
                self._coords.pan(-dx, -dy)
                self._coords.clamp(self.width(), self.height())
            else:
                self._tool_move(pos)
            return
        if self.in_screen_mode():
            self._screen_move(event)
            return
        if self._anchor_drag is not None:
            self._anchor_move(pos)
            return
        if self._drag_pos is not None and (event.buttons() & self._PAN_BUTTONS):
            dx, dy = pos.x() - self._drag_pos.x(), pos.y() - self._drag_pos.y()
            self._drag_pos = pos
            self._coords.pan(-dx, -dy)
            self._coords.clamp(self.width(), self.height())

    def mouseReleaseEvent(self, event):
        if self.in_map_mode():
            if event.button() == Qt.MouseButton.LeftButton:
                self._tool_release(event.position())
                self._drag_pos = None   # ends a "none"-tool left-drag pan
            elif event.button() == Qt.MouseButton.RightButton:
                self._drag_pos = None
            return
        if self.in_screen_mode():
            self._screen_release(event)
            return
        if event.button() == Qt.MouseButton.LeftButton and self._anchor_drag is not None:
            self._anchor_release()
            return
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self._drag_pos = None

    _NUDGE_KEYS = {
        Qt.Key.Key_Left: (-1, 0), Qt.Key.Key_Right: (1, 0),
        Qt.Key.Key_Up: (0, -1), Qt.Key.Key_Down: (0, 1),
    }

    def keyPressEvent(self, event):
        if self.in_screen_mode() and self._selected_widget is not None:
            delta = self._NUDGE_KEYS.get(Qt.Key(event.key()))
            if delta is not None:
                self._nudge_selected(*delta)
                return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        if self.in_screen_mode():
            return   # fixed scale-to-fit — no viewport-driven zoom (brief §1c)
        self._step_zoom(1 if event.angleDelta().y() > 0 else -1)

    def _step_zoom(self, direction):
        """Step through geometry.json's zoom levels, keeping the viewport
        centre's world point fixed (same feel as game/main.py's step_zoom;
        coords authority only, E-5)."""
        cs = self._coords
        levels = sorted(cs.geometry.zoom_levels)
        i = levels.index(cs.camera.zoom) + direction
        if not 0 <= i < len(levels):
            return
        view_w, view_h = self.width(), self.height()
        cx, cy = view_w / 2, view_h / 2
        anchor = cs.screen_to_world(cx, cy)
        cs.set_zoom(levels[i])
        px, py = cs.world_to_screen(*anchor)
        cs.pan(px - cx, py - cy)
        cs.clamp(view_w, view_h)
