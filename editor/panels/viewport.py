"""ViewportPanel (ED-2/ED-21/ED-22/ED-23) — the engine's render surface
embedded in a PySide6 widget.

Two modes, both drawn by the ONE real engine pipeline (RenderItem ->
Renderer -> pygame.Surface, ED-22): the Phase 3 grey-X ground grid, and —
when a slot is selected — the entity preview (ED-21): that slot rendered at
the map centre, idle by default, with a floating dropdown to play any
authored animation. Unsaved import-panel drafts preview through a manifest
override (never a disk write); `reload_assets()` re-reads the manifest so a
save shows up without an editor restart (ED-42). Missing/corrupt art is the
engine store's problem and renders as the grey X (E-37).

SDL dummy drivers are set BEFORE importing pygame: the editor's pygame
surface is always an offscreen render target sized to the widget, never a
real SDL window. The surface is converted to a QImage and painted in
paintEvent — the sanctioned QImage-copy fallback (PLAN §7), >=60fps at
1280x720 (numbers in editor/CLAUDE.md).
"""
import os
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QComboBox, QWidget

from engine.assets import entry_from_dict, load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.render import Renderer, RenderItem

REPO = Path(__file__).resolve().parents[2]
BACKGROUND = (24, 20, 32)


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
        self._coords.clamp(w, h)

    # -- frame drive: main.py's QTimer calls this once per tick -------------

    def render_frame(self):
        t0 = time.perf_counter()
        self._surface.fill(BACKGROUND)
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

    def paintEvent(self, event):
        if self._qimage is None:
            return
        painter = QPainter(self)
        painter.drawImage(0, 0, self._qimage)

    # -- input (ED-23): drag pan, wheel zoom — engine.coords only -----------
    # ED-23 / game/main.py specify right-click-drag ("same feel"); left-click
    # is also accepted here so panning works on input devices without a
    # right button (e.g. no mouse, trackpad-only). Either button drags.
    _PAN_BUTTONS = Qt.MouseButton.RightButton | Qt.MouseButton.LeftButton

    def mousePressEvent(self, event):
        if event.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.LeftButton):
            self._drag_pos = event.position()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & self._PAN_BUTTONS):
            pos = event.position()
            dx, dy = pos.x() - self._drag_pos.x(), pos.y() - self._drag_pos.y()
            self._drag_pos = pos
            self._coords.pan(-dx, -dy)
            self._coords.clamp(self.width(), self.height())

    def mouseReleaseEvent(self, event):
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
