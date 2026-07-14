"""Nine-slice compositing in the render backend (A2, slice 10L-A).

The 9-patch is the ONLY place a HUD skin's geometry happens: corners blit 1:1,
edges stretch on one axis, the centre on both. Everything upstream (manifest ->
Frame -> DrawCall) just carries the margins. Tested against a synthetic
three-colour 6x6 sheet so every region is identifiable by pixel colour.
"""
import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import jsonschema  # noqa: E402
import pygame  # noqa: E402

from engine.assets.manifest import load_manifest  # noqa: E402
from engine.data_io import write_validated  # noqa: E402
from engine.render import backend  # noqa: E402
from engine.render.item import DrawCall  # noqa: E402

pygame.init()

REPO = pathlib.Path(__file__).resolve().parents[2]
SCHEMA = REPO / "data" / "schemas" / "asset_manifest.schema.json"

RED = (255, 0, 0)      # the four 2x2 corners — must never be resampled
GREEN = (0, 255, 0)    # the four edge bands
BLUE = (0, 0, 255)     # the 2x2 centre
MARGINS = (2, 2, 2, 2)


def source_sheet():
    """6x6: all green, a blue 2x2 centre, red 2x2 corners."""
    s = pygame.Surface((6, 6), pygame.SRCALPHA)
    s.fill(GREEN)
    s.fill(BLUE, (2, 2, 2, 2))
    for rect in ((0, 0, 2, 2), (4, 0, 2, 2), (0, 4, 2, 2), (4, 4, 2, 2)):
        s.fill(RED, rect)
    return s


def draw_patch(src, size, margins=MARGINS):
    target = pygame.Surface(size, pygame.SRCALPHA)
    backend.draw(target, [DrawCall(surface=src, dest=(0, 0), size=size,
                                   slice=margins)])
    return target


class NineSliceCase(unittest.TestCase):
    def setUp(self):
        backend._scale_cache.clear()
        self.src = source_sheet()

    def assertPixel(self, target, pos, colour):
        self.assertEqual(target.get_at(pos)[:3], colour, f"at {pos}")


class TestGeometry(NineSliceCase):
    def test_corners_are_not_scaled(self):
        t = draw_patch(self.src, (20, 20))
        for corner in ((0, 0), (19, 0), (0, 19), (19, 19)):
            self.assertPixel(t, corner, RED)
        # ...and the corner is still exactly 2px: one pixel further in is edge
        self.assertPixel(t, (2, 0), GREEN)
        self.assertPixel(t, (0, 2), GREEN)

    def test_edges_and_centre_fill(self):
        t = draw_patch(self.src, (20, 20))
        self.assertPixel(t, (10, 0), GREEN)    # top edge, stretched on x
        self.assertPixel(t, (10, 19), GREEN)   # bottom edge
        self.assertPixel(t, (0, 10), GREEN)    # left edge, stretched on y
        self.assertPixel(t, (19, 10), GREEN)   # right edge
        for pos in ((10, 10), (2, 2), (17, 17)):
            self.assertPixel(t, pos, BLUE)     # centre, stretched both ways


class TestDegenerateClamp(NineSliceCase):
    """Margins bigger than the destination must squeeze, never crash."""

    def test_degenerate_size_clamps_proportionally(self):
        t = draw_patch(self.src, (2, 2))       # 2+2 margins into a 2px axis
        for pos in ((0, 0), (1, 0), (0, 1), (1, 1)):
            self.assertPixel(t, pos, RED)      # corners survive; centre vanishes

    def test_single_pixel_destination(self):
        t = draw_patch(self.src, (1, 1))
        self.assertPixel(t, (0, 0), RED)

    def test_clamp_pair_fills_the_axis_exactly_on_overflow(self):
        self.assertEqual(backend._clamp_pair(2, 2, 6), (2, 2))   # normal: untouched
        self.assertEqual(backend._clamp_pair(0, 0, 6), (0, 0))
        for limit in range(1, 10):
            for a, b in ((2, 2), (5, 1), (1, 7), (3, 4)):
                lo, hi = backend._clamp_pair(a, b, limit)
                self.assertGreaterEqual(lo, 0)
                self.assertGreaterEqual(hi, 0)
                if a + b > limit:
                    self.assertEqual(lo + hi, limit)  # exactly fills, no overflow


class TestZeroMargins(NineSliceCase):
    def test_zero_margin_axis_stretches_freely(self):
        # no x margins => the horizontal middle band IS the whole source width,
        # so x stretches freely (a pure 1x3 patch); y keeps its 3px bands.
        t = draw_patch(self.src, (30, 12), margins=(0, 3, 0, 3))
        self.assertPixel(t, (15, 1), GREEN)   # midpoint -> source's middle band
        self.assertPixel(t, (0, 1), RED)      # the corner column stretched too
        self.assertPixel(t, (29, 1), RED)

    def test_all_zero_slice_is_a_plain_scale(self):
        size = (20, 20)
        t = draw_patch(self.src, size, margins=(0, 0, 0, 0))
        ref = pygame.transform.scale(self.src, size)
        self.assertEqual(pygame.image.tobytes(t, "RGBA"),
                         pygame.image.tobytes(ref, "RGBA"))
        # ...and it shares the PLAIN scale cache entry, not a 9-patch one
        keys = list(backend._scale_cache[self.src])
        self.assertEqual(keys, [size])


class TestCache(NineSliceCase):
    def counting_scale(self):
        real = pygame.transform.scale
        count = {"n": 0}

        def counting(surface, size):
            count["n"] += 1
            return real(surface, size)

        return real, counting, count

    def test_composite_is_cached_per_surface_size_and_margins(self):
        real, counting, count = self.counting_scale()
        target = pygame.Surface((40, 40), pygame.SRCALPHA)
        call = DrawCall(surface=self.src, dest=(0, 0), size=(20, 20),
                        slice=MARGINS)
        pygame.transform.scale = counting
        try:
            backend.draw(target, [call])
            # 4 edges + the centre are resampled; the 4 corners never are
            self.assertEqual(count["n"], 5)
            backend.draw(target, [call])
            backend.draw(target, [call])
            self.assertEqual(count["n"], 5, "the composite must be memoized")

            by_key = backend._scale_cache[self.src]
            self.assertEqual(list(by_key), [("9p", (20, 20), MARGINS)])

            # the key discriminates on BOTH size and margins
            backend.draw(target, [DrawCall(surface=self.src, dest=(0, 0),
                                           size=(30, 30), slice=MARGINS)])
            self.assertEqual(len(by_key), 2)
            backend.draw(target, [DrawCall(surface=self.src, dest=(0, 0),
                                           size=(20, 20), slice=(1, 1, 1, 1))])
            self.assertEqual(len(by_key), 3)
        finally:
            pygame.transform.scale = real

    def test_plain_scale_key_cannot_collide_with_a_9patch_key(self):
        target = pygame.Surface((40, 40), pygame.SRCALPHA)
        backend.draw(target, [
            DrawCall(surface=self.src, dest=(0, 0), size=(20, 20)),
            DrawCall(surface=self.src, dest=(0, 0), size=(20, 20), slice=MARGINS),
        ])
        by_key = backend._scale_cache[self.src]
        self.assertEqual(sorted(map(str, by_key)),
                         sorted(["(20, 20)", str(("9p", (20, 20), MARGINS))]))


class TestSchemaRoundTrip(unittest.TestCase):
    """The margins survive a real write_validated -> load_manifest round trip
    against the COMMITTED schema (additionalProperties:false — an undeclared
    key would fail here)."""

    def doc(self, slice_value=None):
        entry = {
            "sheet": "imported/btn.png",
            "frame_w": 16,
            "frame_h": 16,
            "offset_x": 0,
            "offset_y": 0,
            "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                      "loop_start": 0, "loop_end": 0, "loop_count": 1}],
        }
        if slice_value is not None:
            entry["slice"] = slice_value
        return {"version": 2, "entries": {"btn": entry}}

    def write(self, doc):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "asset_manifest.json"
        write_validated(doc, path, SCHEMA)
        return path

    def test_slice_survives_a_schema_validated_round_trip(self):
        path = self.write(self.doc([4, 4, 4, 4]))
        self.assertIn('"slice"', path.read_text(encoding="utf-8"))
        entry = load_manifest(path).entry("btn")
        self.assertEqual(entry.slice, (4, 4, 4, 4))

    def test_entry_without_a_slice_still_validates(self):
        entry = load_manifest(self.write(self.doc())).entry("btn")
        self.assertIsNone(entry.slice)

    def test_wrong_length_slice_is_rejected(self):
        with self.assertRaises(jsonschema.ValidationError):
            self.write(self.doc([4, 4, 4]))

    def test_negative_margin_is_rejected(self):
        with self.assertRaises(jsonschema.ValidationError):
            self.write(self.doc([4, -1, 4, 4]))

    def test_committed_manifest_still_validates(self):
        # A2 adds an OPTIONAL property: the shipping manifest (no entry carries
        # a slice) must keep validating untouched.
        manifest = json.loads(
            (REPO / "data" / "sprites" / "asset_manifest.json").read_text(
                encoding="utf-8"))
        jsonschema.validate(manifest, json.loads(SCHEMA.read_text(encoding="utf-8")))


if __name__ == "__main__":
    unittest.main()
