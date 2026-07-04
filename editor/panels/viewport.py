"""ViewportPanel (ED-2/ED-20/ED-21/ED-22/ED-23) — the engine's render
surface embedded in a PySide6 widget.

Three modes, all drawn by the ONE real engine pipeline (RenderItem ->
Renderer -> pygame.Surface, ED-22): the Phase 3 grey-X ground grid, the
entity preview (ED-21, Phase 5), and — when a map node is selected — the
TILEMAP EDITOR (ED-20, Phase 6): the open MapSession's doc rendered with
layer eyes + zone tints, ghost previews on the overlay layer, grid lines
through the engine's E-24 overlay primitive, and mouse tools whose cell
picking goes through engine.coords.screen_to_world ONLY (E-3 — no iso
math here). In map mode the LEFT button drives the armed tool and the
RIGHT button pans (entity preview keeps either-button pan); strokes
mutate the session doc live and are pushed as ONE undo command on
release (ED-24).

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
from PySide6.QtWidgets import QComboBox, QWidget

from editor import tilemap_ops
from engine import tilemap
from engine.assets import entry_from_dict, load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import Renderer, RenderItem

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

LOGO_PATH = REPO / "editor" / "assets" / "drunken_donuts_logo.png"


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

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        pygame.init()
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._coords = load_coordinate_system(self._data_dir)
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
        self._eyes = {"terrain": True, "tint": True, "base": True, "deco": True}
        self._grid_lines = False
        self._hover_cell = None
        self._stroke = None           # change list accumulating this stroke
        self._stroke_code = None
        self._stroke_last = None
        self._anchor = None           # line/rect anchor cell
        self._base_drag = False

        # ED-21 animation dropdown: floating child pinned to the corner so
        # the paint surface keeps filling the whole widget.
        self._anim_combo = QComboBox(self)
        self._anim_combo.move(8, 8)
        self._anim_combo.hide()
        self._anim_combo.currentTextChanged.connect(self.set_preview_animation)

        self._surface = None
        self._qimage = None
        self._drag_pos = None
        self.last_frame_ms = 0.0
        self._logo_pixmap = QPixmap(str(LOGO_PATH))
        self._resize_surface()

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
        if self.in_map_mode():
            doc = self._map_session.doc
            self._coords = load_coordinate_system(
                self._data_dir, map_cols=doc.cols, map_rows=doc.rows)
            self._anim_combo.hide()
        else:
            self._coords = load_coordinate_system(self._data_dir)
            self._refresh_anim_combo()
        w, h = max(1, self.width()), max(1, self.height())
        if self.in_map_mode():
            self._coords.clamp(w, h)
        else:
            self._center_on_preview(w, h)
        self._renderer = Renderer(self._coords, self._assets)

    def in_map_mode(self):
        return self._map_session is not None and self._map_session.doc is not None

    # palette state (MainWindow wires the PalettePanel signals to these)
    def set_tool(self, name):
        self._tool = name
        self._anchor = None

    def arm_code(self, code):
        self._armed_code = code
        self._armed_deco = None

    def arm_deco(self, slot):
        self._armed_deco = slot
        self._armed_code = None

    def arm_base(self, slot):
        """Arming the base is import-target-only (palette.py) — clear any
        armed code/deco so a stray "paint" click can't use a stale brush."""
        self._armed_code = None
        self._armed_deco = None

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
        if self._eyes["base"] and cell == (doc.base["col"], doc.base["row"]):
            self._base_drag = True   # the single draggable map object;
            return                   # hide the base eye to paint under it
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
                old = tilemap_ops.move_base(doc, *cell)
                self._map_session.push_base_move(old, cell)
            self._base_drag = False
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
        if self._tool == "none":
            return   # no active brush — nothing would actually be placed
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
            self._coords.clamp(w, h)
        else:
            self._center_on_preview(w, h)

    def _center_on_preview(self, w, h):
        """Entity preview mode: park the camera on the preview tile
        (grid/map centre) so the sprite sits centred even when the grid is
        wider than the viewport — clamp alone would anchor it to an edge."""
        g = self._coords.geometry
        self._coords.center_on(g.map_cols // 2, g.map_rows // 2, w, h)

    # -- frame drive: main.py's QTimer calls this once per tick -------------

    def render_frame(self):
        t0 = time.perf_counter()
        self._surface.fill(BACKGROUND)
        if self.in_map_mode():
            self._submit_map_items()
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
        tints), the ghost preview, and grid lines via the E-24 primitive."""
        doc = self._map_session.doc
        for item in tilemap.render_items(
                doc,
                terrain=self._eyes["terrain"],
                base=self._eyes["base"],
                deco=self._eyes["deco"],
                tint_for_code=ZONE_TINTS if self._eyes["tint"] else None):
            self._renderer.submit(item)
        for item in self._ghost_items(doc):
            self._renderer.submit(item)
        if self._grid_lines:
            for r in range(doc.rows + 1):
                self._renderer.submit_overlay_lines(
                    ((0, r), (doc.cols, r)), GRID_COLOR)
            for c in range(doc.cols + 1):
                self._renderer.submit_overlay_lines(
                    ((c, 0), (c, doc.rows)), GRID_COLOR)

    def paintEvent(self, event):
        if self._qimage is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._qimage)
        if not self.in_map_mode() and self.preview_slot is None:
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
                # "none" tool that didn't start a base drag → left-drag pans.
                if self._tool == "none" and not self._base_drag:
                    self._drag_pos = event.position()
            elif event.button() == Qt.MouseButton.RightButton:
                self._drag_pos = event.position()
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
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self._drag_pos = None

    def wheelEvent(self, event):
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
