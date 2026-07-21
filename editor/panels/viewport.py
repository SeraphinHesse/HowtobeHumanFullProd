"""ViewportPanel (ED-2/ED-20/ED-21/ED-22/ED-23) — the engine's render
surface embedded in a PySide6 widget.

Four modes, all drawn by the ONE real engine pipeline (RenderItem ->
Renderer -> pygame.Surface, ED-22): the Phase 3 grey-X ground grid, the
entity preview (ED-21, Phase 5), the TILEMAP EDITOR (ED-20, Phase 6, when a
map node is selected): the open MapSession's doc rendered with layer eyes +
zone tints, ghost previews on the overlay layer, grid lines through the
engine's E-24 overlay primitive, and mouse tools whose cell picking goes
through engine.coords.screen_to_world ONLY (E-3 — no iso math here); and
SCREEN MODE (B4, R3, when a UI-screen leaf is selected): a fixed 1280x720
logical canvas scaled-to-fit the widget, submitted entirely through
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
1280x720 (numbers in editor/CLAUDE.md).
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

from editor import tilemap_ops
from editor.panels import _screen_primitives
from editor.panels.balancing import _NoWheelComboBox
from engine import data_io, tilemap
from engine.assets import entry_from_dict, load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import HudLines, HudRect, HudSprite, HudText, Renderer, RenderItem

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

LOGO_PATH = REPO / "editor" / "assets" / "drunken_donuts_logo.png"

# -- screen mode (B4, R3): fixed 1280x720 logical canvas, scaled-to-fit -----
SCREEN_W, SCREEN_H = 1280, 720   # data/display.json's canonical resolution
NO_DEFAULTS_COLOR = (235, 90, 90)          # E-37 graceful-degrade placeholder
SELECTION_COLOR = (255, 220, 80)
HANDLE_COLOR = (255, 255, 255)
HANDLE_PX = 8          # resize-handle hit box, half-width in SCREEN pixels
NUDGE_STEP = 1         # arrow-key nudge, in LOGICAL (1280x720) pixels
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
    widget_selected = Signal(object)      # B4: screen-mode selection (str|None)

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
        self.preview_animation = "idle"
        self._anim_ms = 0.0
        self._anim_last_t = None

        # -- tilemap-editor state (ED-20); all mutations go through the
        # session's undo stack, all cell picking through engine.coords
        self._map_session = None
        self._tool = "none"
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None     # the Hole slot when the Hole brush is armed
        self._armed_camera = None   # the Camera Start slot when that brush is armed
        self._armed_start_area = None  # the Start Area slot when armed
        self._eyes = {"terrain": True, "tint": True, "base": True, "deco": True,
                      "camera": True, "start_area": True}
        self._grid_lines = False
        self._hover_cell = None
        self._stroke = None           # change list accumulating this stroke
        self._stroke_code = None
        self._stroke_last = None
        self._anchor = None           # line/rect anchor cell
        self._base_drag = False
        self._camera_drag = False
        self._start_area_drag = False

        # ED-21 animation dropdown: floating child pinned to the corner so
        # the paint surface keeps filling the whole widget.
        self._anim_combo = _NoWheelComboBox(self)
        self._anim_combo.move(8, 8)
        self._anim_combo.hide()
        self._anim_combo.currentTextChanged.connect(self.set_preview_animation)

        # -- screen mode state (B4, R3): all mutation goes through the open
        # UIScreenSession's undo stack; all rect math in LOGICAL (1280x720)
        # pixels, converted to SCREEN pixels only at submission/hit-test time
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

    # -- entity preview (ED-21) ----------------------------------------------

    def set_preview_slot(self, slot_key):
        """None -> plain grid mode; a slot key -> entity preview mode."""
        if slot_key != self.preview_slot:
            self.preview_slot = slot_key
            self._draft = None
            self._build_store()
            self.preview_animation = "idle"
            self._reset_anim_clock()
        self._refresh_anim_combo()

    def set_preview_animation(self, name):
        if not name or name == self.preview_animation:
            return
        self.preview_animation = name
        self._reset_anim_clock()

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
        self._anchor = None
        self._base_drag = False
        self._start_area_drag = False
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
        1280x720 logical canvas, scaled-to-fit the viewport widget (no
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
        """Uniform scale + letterbox offset fitting the 1280x720 logical
        canvas inside the current widget size (screen mode never zooms)."""
        w, h = max(1, self.width()), max(1, self.height())
        scale = min(w / SCREEN_W, h / SCREEN_H)
        scaled_w, scaled_h = SCREEN_W * scale, SCREEN_H * scale
        return scale, (w - scaled_w) / 2, (h - scaled_h) / 2

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

    def arm_deco(self, slot):
        self._armed_deco = slot
        self._armed_code = None
        self._armed_base = None
        self._armed_camera = None
        self._armed_start_area = None

    def arm_base(self, slot):
        """Arm the Hole brush — a real paintable brush now (paint = place/move
        the single hole, erase = remove it). Clears any armed code/deco."""
        self._armed_base = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_camera = None
        self._armed_start_area = None

    def arm_camera(self, slot):
        """Arm the Camera Start brush (paint = place/move the single startpoint,
        erase = remove it). Mirrors arm_base; clears any other armed brush."""
        self._armed_camera = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_start_area = None

    def arm_start_area(self, slot):
        """Arm the Starting Area brush (paint = place/move the single 2×2 area,
        erase = remove it). Mirrors arm_base; clears any other armed brush."""
        self._armed_start_area = slot
        self._armed_code = None
        self._armed_deco = None
        self._armed_base = None
        self._armed_camera = None

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
        if self._armed_deco is not None:
            if self._tool == "paint":
                self._map_session.push_deco_place(
                    cell[0], cell[1], self._armed_deco)
            elif self._tool == "erase":
                self._map_session.push_deco_remove(cell[0], cell[1])
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
        elif self._stroke is not None:
            self._map_session.push_stroke(self._stroke, "paint stroke")
            self._stroke = None
            self._stroke_last = None
        elif self._anchor is not None:
            if cell is not None:
                op = (tilemap_ops.line if self._tool == "line"
                      else tilemap_ops.rect_fill)
                self._map_session.push_stroke(
                    op(doc, *self._anchor, *cell, self._armed_code), self._tool)
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
                             tint=GHOST_TINT)
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
            self._submit_screen_items(t0)
        else:
            g = self._coords.geometry
            for row in range(g.map_rows):
                for col in range(g.map_cols):
                    self._renderer.submit(RenderItem("ground_tile", (col, row), layer="ground"))
            if self.preview_slot is not None:
                if self._anim_last_t is not None:
                    self._anim_ms += (t0 - self._anim_last_t) * 1000.0
                self._anim_last_t = t0
                self._renderer.submit(RenderItem(
                    self.preview_slot,
                    (g.map_cols // 2, g.map_rows // 2),
                    layer="entities",
                    animation=self.preview_animation,
                    anim_time_ms=int(self._anim_ms),
                ))
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

    # -- screen mode rendering (B4, R3) — ALL through submit_hud (ED-22) -----

    def _submit_screen_items(self, t0):
        scale, ox, oy = self._screen_scale_offset()
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
            return
        if self._screen_anim_last_t is not None:
            self._screen_anim_ms += (t0 - self._screen_anim_last_t) * 1000.0
        self._screen_anim_last_t = t0
        doc = self._screen_session.doc
        self._submit_screen_background(doc, scale, ox, oy)
        for widget_id, spec in defaults.get("widgets", {}).items():
            self._submit_screen_widget(widget_id, spec, doc, scale, ox, oy)
        if self._selected_widget is not None \
                and self._selected_widget in defaults.get("widgets", {}):
            self._submit_screen_selection(self._selected_widget, defaults,
                                          scale, ox, oy)

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
                # "none" tool that didn't start a base/start-area drag →
                # left-drag pans.
                if self._tool == "none" and not self._base_drag \
                        and not self._start_area_drag:
                    self._drag_pos = event.position()
            elif event.button() == Qt.MouseButton.RightButton:
                self._drag_pos = event.position()
            return
        if self.in_screen_mode():
            self._screen_press(event)
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
