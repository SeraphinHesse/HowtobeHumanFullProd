"""Phase 1 acceptance tests for the grey-X placeholder (E-33). Headless."""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine.assets.placeholder import placeholder_surface


class TestPlaceholder(unittest.TestCase):
    def test_any_requested_frame_size(self):
        for size in [(64, 32), (64, 96), (48, 48), (7, 130)]:
            self.assertEqual(placeholder_surface(*size).get_size(), size)

    def test_cached_per_size(self):
        self.assertIs(placeholder_surface(64, 32), placeholder_surface(64, 32))
        self.assertIsNot(placeholder_surface(64, 32), placeholder_surface(64, 96))

    def test_visibly_drawn(self):
        s = placeholder_surface(64, 32)
        # X crosses the centre; border covers the corner.
        self.assertGreater(s.get_at((32, 16)).a, 0)
        self.assertGreater(s.get_at((0, 0)).a, 0)


if __name__ == "__main__":
    unittest.main()
