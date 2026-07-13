"""Phase 10J: per-pixel-alpha primitives — RGBA HudRect/HudText and the
filled-polygon OverlayPolys overlay (engine/render).

Backend blending is checked pixel-for-pixel on a real surface; the renderer
side checks submission validation and world→screen conversion of
submit_overlay_polys (recording backend, no pygame in the renderer).
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.render import backend
from engine.render.hud import HudRect, HudText
from engine.render.item import OverlayPolys


class TestBackendAlpha(unittest.TestCase):
    def setUp(self):
        pygame.init()
        self.target = pygame.Surface((100, 100))
        self.target.fill((0, 0, 0))

    def test_rgba_hud_rect_blends(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 40, 40),
                                           color=(200, 100, 0, 128))])
        r, g, b = self.target.get_at((30, 30))[:3]
        # ~50% of the color over black; allow rounding slack
        self.assertTrue(90 <= r <= 110, r)
        self.assertTrue(40 <= g <= 60, g)
        self.assertEqual(b, 0)

    def test_opaque_rgba_hud_rect_writes_full_color(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 40, 40),
                                           color=(200, 100, 0, 255))])
        self.assertEqual(self.target.get_at((30, 30))[:3], (200, 100, 0))

    def test_rgb_hud_rect_unchanged_path(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 40, 40),
                                           color=(200, 100, 0))])
        self.assertEqual(self.target.get_at((30, 30))[:3], (200, 100, 0))

    def test_rgba_hud_rect_outline_leaves_interior(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 60, 60),
                                           color=(0, 200, 0, 120), width=2)])
        self.assertGreater(self.target.get_at((11, 40))[1], 0)  # border blended
        self.assertEqual(self.target.get_at((40, 40))[:3], (0, 0, 0))  # interior

    def test_polys_opaque_fill(self):
        poly = OverlayPolys(points=((10, 10), (90, 10), (50, 80)),
                            color=(50, 60, 200))
        backend.draw(self.target, [poly])
        self.assertEqual(self.target.get_at((50, 30))[:3], (50, 60, 200))

    def test_polys_alpha_blends(self):
        poly = OverlayPolys(points=((10, 10), (90, 10), (50, 80)),
                            color=(200, 0, 0, 90))
        backend.draw(self.target, [poly])
        r = self.target.get_at((50, 30))[0]
        expected = round(200 * 90 / 255)
        self.assertTrue(abs(r - expected) <= 3, r)
        # outside the triangle untouched
        self.assertEqual(self.target.get_at((5, 90))[:3], (0, 0, 0))

    def test_rgba_hud_text_fades(self):
        full = pygame.Surface((100, 100))
        full.fill((0, 0, 0))
        backend.draw(full, [HudText("XX", pos=(5, 5), font_key="xl",
                                    color=(255, 255, 255))])
        faded = pygame.Surface((100, 100))
        faded.fill((0, 0, 0))
        backend.draw(faded, [HudText("XX", pos=(5, 5), font_key="xl",
                                     color=(255, 255, 255, 60))])
        brightest_full = max(full.get_at((x, y))[0]
                             for x in range(100) for y in range(40))
        brightest_faded = max(faded.get_at((x, y))[0]
                              for x in range(100) for y in range(40))
        self.assertEqual(brightest_full, 255)
        self.assertLess(brightest_faded, 120)
        self.assertGreater(brightest_faded, 0)


class _RecordingBackend:
    def __init__(self):
        self.calls = None

    def __call__(self, target, draw_calls):
        self.calls = list(draw_calls)


class TestRendererPolysSubmission(unittest.TestCase):
    def _renderer(self):
        from engine.coords import Camera, CoordinateSystem, Geometry
        from engine.render.renderer import Renderer

        class _Assets:
            def frame(self, *a, **k):  # pragma: no cover - not used here
                raise AssertionError("no sprites submitted")

        geo = Geometry(tile_w=64, tile_h=32, map_cols=20, map_rows=20,
                       zoom_levels=(0.5, 1.0, 2.0))
        coords = CoordinateSystem(geo, Camera())
        rec = _RecordingBackend()
        return Renderer(coords, _Assets(), backend=rec), coords, rec

    def test_polys_converted_to_screen_space(self):
        renderer, coords, rec = self._renderer()
        world = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0))
        renderer.submit_overlay_polys(world, (10, 20, 30, 40))
        renderer.flush(target=None)
        (call,) = rec.calls
        self.assertIsInstance(call, OverlayPolys)
        self.assertEqual(call.color, (10, 20, 30, 40))
        expected = tuple(coords.world_to_screen(*p) for p in world)
        self.assertEqual(call.points, expected)

    def test_polys_needs_three_points(self):
        renderer, _, _ = self._renderer()
        with self.assertRaises(ValueError):
            renderer.submit_overlay_polys(((0, 0), (1, 1)), (255, 0, 0))

    def test_polys_and_lines_keep_submission_order(self):
        renderer, _, rec = self._renderer()
        renderer.submit_overlay_lines(((0, 0), (1, 1)), (1, 2, 3))
        renderer.submit_overlay_polys(((0, 0), (1, 0), (1, 1)), (4, 5, 6))
        renderer.submit_overlay_lines(((2, 2), (3, 3)), (7, 8, 9))
        renderer.flush(target=None)
        kinds = [type(c).__name__ for c in rec.calls]
        self.assertEqual(kinds, ["OverlayLines", "OverlayPolys", "OverlayLines"])


if __name__ == "__main__":
    unittest.main()
