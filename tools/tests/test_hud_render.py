"""Phase 9B: engine.render.fonts cache/TextMetrics + backend HUD dispatch.

The real HUD primitive dataclasses (HudRect/HudText/HudLines) are the
parallel 9B half in engine/render/hud.py. To keep this test independent of
that merge, it defines structurally-identical local stand-ins and patches
them onto the backend module (which reads those names for its isinstance
dispatch). Post-merge the backend imports the real classes; this test still
exercises the same drawing code against equivalent shapes.
"""
import os
import unittest
from dataclasses import dataclass

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.render import backend, fonts
from engine.render.fonts import TextMetrics


@dataclass(frozen=True)
class HudRect:
    rect: tuple
    color: tuple
    border_radius: int = 0
    width: int = 0


@dataclass(frozen=True)
class HudText:
    text: str
    pos: tuple
    font_key: str
    color: tuple
    align: str = "left"
    family: str = None  # UH-Font-B: the stand-in tracks the real dataclass


@dataclass(frozen=True)
class HudLines:
    points: tuple
    color: tuple
    width: int = 1
    closed: bool = False


class TestFontCache(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def test_get_font_returns_font_and_caches(self):
        f1 = fonts.get_font("md")
        f2 = fonts.get_font("md")
        self.assertIsInstance(f1, pygame.font.Font)
        self.assertIs(f1, f2)  # cached, same object

    def test_all_declared_keys_resolve(self):
        for key in ("sm", "md", "lg", "xl", "xxl", "hud_phase", "hud_lvl"):
            self.assertIsInstance(fonts.get_font(key), pygame.font.Font)

    def test_unknown_key_falls_back(self):
        # falls back to 'md' rather than raising
        self.assertIs(fonts.get_font("does_not_exist"), fonts.get_font("md"))

    def test_text_metrics_positive_dims(self):
        w, h = TextMetrics().size("love 128", "hud_phase")
        self.assertGreater(w, 0)
        self.assertGreater(h, 0)

    def test_text_metrics_wider_for_longer_string(self):
        m = TextMetrics()
        short_w, _ = m.size("x", "md")
        long_w, _ = m.size("xxxxxxxxxx", "md")
        self.assertGreater(long_w, short_w)


class TestBackendHudDispatch(unittest.TestCase):
    def setUp(self):
        pygame.init()
        # Patch the names the backend uses for isinstance dispatch.
        self._orig = (backend.HudRect, backend.HudText, backend.HudLines)
        backend.HudRect, backend.HudText, backend.HudLines = HudRect, HudText, HudLines
        self.addCleanup(self._restore)
        self.target = pygame.Surface((200, 100))
        self.target.fill((0, 0, 0))

    def _restore(self):
        backend.HudRect, backend.HudText, backend.HudLines = self._orig

    def test_hud_rect_filled(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 50, 30), color=(200, 40, 40))])
        self.assertEqual(self.target.get_at((30, 25))[:3], (200, 40, 40))

    def test_hud_rect_outline_leaves_interior(self):
        backend.draw(self.target, [HudRect(rect=(10, 10, 60, 40),
                                           color=(0, 180, 0), width=2)])
        # border pixel painted, interior stays background
        self.assertEqual(self.target.get_at((10, 30))[:3], (0, 180, 0))
        self.assertEqual(self.target.get_at((40, 30))[:3], (0, 0, 0))

    def test_hud_lines_endpoint_painted(self):
        backend.draw(self.target, [HudLines(points=((5, 5), (150, 5)),
                                            color=(50, 90, 255), width=1)])
        self.assertEqual(self.target.get_at((150, 5))[:3], (50, 90, 255))

    def test_hud_text_left_draws_pixels(self):
        backend.draw(self.target, [HudText("HELLO", pos=(5, 5), font_key="xl",
                                           color=(255, 255, 255))])
        changed = sum(
            1 for x in range(0, 200) for y in range(0, 40)
            if self.target.get_at((x, y))[:3] != (0, 0, 0)
        )
        self.assertGreater(changed, 0)

    def test_hud_text_aligns_do_not_crash(self):
        for align in ("left", "center", "right"):
            backend.draw(self.target, [HudText("love 128", pos=(100, 10),
                                               font_key="md", color=(255, 210, 120),
                                               align=align)])

    def test_mixed_batch_no_crash(self):
        batch = [
            HudRect(rect=(0, 0, 200, 20), color=(30, 30, 40)),
            HudText("phase", pos=(4, 2), font_key="hud_phase", color=(220, 220, 220)),
            HudLines(points=((0, 22), (200, 22)), color=(80, 80, 80)),
        ]
        backend.draw(self.target, batch)  # must not raise


if __name__ == "__main__":
    unittest.main()
