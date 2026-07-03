"""ViewportPanel (ED-2/ED-22/ED-23) — the engine's render surface embedded in
a PySide6 widget. Phase 3 scope: grey-X ground grid only, no tilemap tools.

SDL dummy drivers are set BEFORE importing pygame: the editor's pygame
surface is always an offscreen render target sized to the widget, never a
real SDL window (mirrors tools/render_demo.py's convention). Everything
drawn goes through the ONE real engine pipeline (RenderItem -> Renderer ->
pygame.Surface, E-22); the surface is then converted to a QImage and painted
in paintEvent — the sanctioned QImage-copy fallback (PLAN §7), accepted
because it measures >=60fps at 1280x720 (numbers in editor/CLAUDE.md).
"""
import os
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget

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
        self._coords = load_coordinate_system(data_dir if data_dir is not None else REPO / "data")
        self._assets = AssetStore(frame_sizes={"ground_tile": (64, 32)})
        self._renderer = Renderer(self._coords, self._assets)
        self._surface = None
        self._qimage = None
        self._drag_pos = None
        self.last_frame_ms = 0.0
        self._resize_surface()

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
