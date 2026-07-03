"""Phase 3 acceptance tests for the Qt viewport spike (ED-2/ED-22/ED-23).

QApplication is a per-process singleton under Qt; QT_QPA_PLATFORM=offscreen
is set before PySide6 is imported so the whole module runs headlessly,
mirroring the SDL dummy-driver convention used for pygame elsewhere in
tools/tests/.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame
from PySide6.QtWidgets import QApplication

from editor.panels.viewport import ViewportPanel, surface_to_qimage

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


class TestSurfaceToQImage(unittest.TestCase):
    """Pure conversion, pixel-exact on a known 2x2-quadrant pattern."""

    def test_pixel_equality(self):
        pygame.init()
        surface = pygame.Surface((4, 4))
        colors = {
            (0, 0): (255, 0, 0),
            (2, 0): (0, 255, 0),
            (0, 2): (0, 0, 255),
            (2, 2): (255, 255, 0),
        }
        for (x, y), color in colors.items():
            surface.fill(color, pygame.Rect(x, y, 2, 2))

        image = surface_to_qimage(surface)
        self.assertEqual((image.width(), image.height()), (4, 4))
        for (x, y), color in colors.items():
            got = image.pixelColor(x, y)
            self.assertEqual((got.red(), got.green(), got.blue()), color)


class TestHeadlessViewportPaint(unittest.TestCase):
    """Full pipeline: grid renders through engine/render and reaches pixels."""

    def test_grid_paints_nonbackground_pixels(self):
        panel = ViewportPanel(data_dir=REPO / "data")
        panel.resize(256, 256)
        panel.render_frame()
        pixmap = panel.grab()
        image = pixmap.toImage()
        background = (24, 20, 32)
        touched = 0
        for x in range(0, image.width(), 8):
            for y in range(0, image.height(), 8):
                c = image.pixelColor(x, y)
                if (c.red(), c.green(), c.blue()) != background:
                    touched += 1
        self.assertGreater(touched, 0)

    def test_resize_recreates_surface_to_match_widget(self):
        panel = ViewportPanel(data_dir=REPO / "data")
        panel.show()
        panel.resize(320, 200)
        _APP.processEvents()
        panel.render_frame()
        self.assertEqual(panel._surface.get_size(), (320, 200))
        panel.resize(150, 400)
        _APP.processEvents()
        panel.render_frame()
        self.assertEqual(panel._surface.get_size(), (150, 400))
        panel.close()


class TestZoomStep(unittest.TestCase):
    """ED-23 wheel zoom moves only through data-driven zoom levels."""

    def test_zoom_step_stays_within_data_driven_levels(self):
        panel = ViewportPanel(data_dir=REPO / "data")
        panel.resize(200, 200)
        levels = sorted(panel._coords.geometry.zoom_levels)
        self.assertIn(panel._coords.camera.zoom, levels)
        panel._step_zoom(1)
        self.assertIn(panel._coords.camera.zoom, levels)
        # stepping past the top level is a no-op, not an error
        for _ in range(len(levels) + 2):
            panel._step_zoom(1)
        self.assertEqual(panel._coords.camera.zoom, levels[-1])


class TestPurity(unittest.TestCase):
    """Hard rule: editor/ never imports game/ (root CLAUDE.md layering rule)."""

    def test_editor_does_not_import_game(self):
        code = (
            "import sys; "
            "import editor.main; "
            "assert not any(m == 'game' or m.startswith('game.') for m in sys.modules), "
            "'editor imported game/'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
