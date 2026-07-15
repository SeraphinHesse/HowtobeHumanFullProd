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

from engine.assets import nine_slice  # noqa: E402
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
            for a, b in ((2, 2), (5, 1), (1, 7), (3, 4), (-5, 2), (-1, -1)):
                lo, hi = backend._clamp_pair(a, b, limit)
                self.assertGreaterEqual(lo, 0)
                self.assertGreaterEqual(hi, 0)
                if max(0, a) + max(0, b) > limit:
                    self.assertEqual(lo + hi, limit)  # exactly fills, no overflow

    def test_negative_margin_renders_instead_of_raising(self):
        # Unreachable from committed data (the schema pins minimum 0 and
        # entry_from_dict rejects negatives), but the editor's slice spinboxes
        # feed unsaved draft margins straight in. A negative would otherwise slip
        # through the a+b <= limit fast path and blow up on an out-of-bounds
        # subsurface — rendering must degrade, never raise (E-37).
        for bad in ((-5, 0, 0, 0), (0, -5, 0, 0), (0, 0, -5, 0), (0, 0, 0, -5),
                    (-1, -1, -1, -1), (-5, 2, 3, -4)):
            with self.subTest(margins=bad):
                t = draw_patch(self.src, (20, 20), margins=bad)
                self.assertEqual(t.get_size(), (20, 20))
        # a negative margin floors to 0, so it draws as if that side had none
        self.assertEqual(
            pygame.image.tobytes(draw_patch(self.src, (20, 20), (-5, 2, 3, 4)),
                                 "RGBA"),
            pygame.image.tobytes(draw_patch(self.src, (20, 20), (0, 2, 3, 4)),
                                 "RGBA"))


# A deliberately ASYMMETRIC fixture: a non-square source, four different
# margins, a non-square dest. Every one of the 9 regions gets its own colour, so
# a transposed row/col (src_cols paired with dst_rows) cannot produce the same
# pixels — the square, symmetric 6x6 fixture above is blind to that swap.
ASYM_W, ASYM_H = 10, 8
ASYM_MARGINS = (1, 2, 3, 4)          # left, top, right, bottom
ASYM_DEST = (25, 13)
# source bands: cols 1 | 6 | 3   rows 2 | 2 | 4
# dest   bands: cols 1 | 21 | 3  rows 2 | 7 | 4
ASYM_COLOURS = {
    ("l", "t"): (10, 0, 0), ("m", "t"): (20, 0, 0), ("r", "t"): (30, 0, 0),
    ("l", "m"): (0, 10, 0), ("m", "m"): (0, 20, 0), ("r", "m"): (0, 30, 0),
    ("l", "b"): (0, 0, 10), ("m", "b"): (0, 0, 20), ("r", "b"): (0, 0, 30),
}
ASYM_SRC_COLS = {"l": (0, 1), "m": (1, 6), "r": (7, 3)}
ASYM_SRC_ROWS = {"t": (0, 2), "m": (2, 2), "b": (4, 4)}


def asym_source():
    s = pygame.Surface((ASYM_W, ASYM_H), pygame.SRCALPHA)
    for (cx, cy), colour in ASYM_COLOURS.items():
        x, w = ASYM_SRC_COLS[cx]
        y, h = ASYM_SRC_ROWS[cy]
        s.fill(colour, (x, y, w, h))
    return s


class TestAsymmetricGeometry(NineSliceCase):
    """Non-square source, four distinct margins, non-square dest: pins that each
    region lands on the RIGHT axis. Every assertion here would fail if the row
    and column bands were swapped."""

    def setUp(self):
        super().setUp()
        self.src = asym_source()
        self.t = draw_patch(self.src, ASYM_DEST, margins=ASYM_MARGINS)

    def test_every_region_lands_on_its_own_axis(self):
        # one sample well inside each of the 9 destination regions
        samples = {
            ("l", "t"): (0, 0),   ("m", "t"): (12, 1),  ("r", "t"): (23, 0),
            ("l", "m"): (0, 5),   ("m", "m"): (12, 5),  ("r", "m"): (23, 5),
            ("l", "b"): (0, 11),  ("m", "b"): (12, 11), ("r", "b"): (23, 11),
        }
        for region, pos in samples.items():
            self.assertPixel(self.t, pos, ASYM_COLOURS[region])

    def test_band_boundaries_are_exact_on_each_axis(self):
        # left margin is exactly 1px: x=0 is the corner, x=1 is already centre
        self.assertPixel(self.t, (0, 5), ASYM_COLOURS[("l", "m")])
        self.assertPixel(self.t, (1, 5), ASYM_COLOURS[("m", "m")])
        # right margin is exactly 3px: x=21 is centre, x=22 starts the corner
        self.assertPixel(self.t, (21, 5), ASYM_COLOURS[("m", "m")])
        self.assertPixel(self.t, (22, 5), ASYM_COLOURS[("r", "m")])
        # top margin is exactly 2px: y=1 is the corner, y=2 is already centre
        self.assertPixel(self.t, (12, 1), ASYM_COLOURS[("m", "t")])
        self.assertPixel(self.t, (12, 2), ASYM_COLOURS[("m", "m")])
        # bottom margin is exactly 4px: y=8 is centre, y=9 starts the corner
        self.assertPixel(self.t, (12, 8), ASYM_COLOURS[("m", "m")])
        self.assertPixel(self.t, (12, 9), ASYM_COLOURS[("m", "b")])

    def test_asymmetric_corners_are_byte_identical_to_the_source(self):
        # no overflow here, so every corner is dest-size == source-size => a 1:1
        # blit. Compare the whole corner block, not a sample pixel.
        for cx, cy in (("l", "t"), ("r", "t"), ("l", "b"), ("r", "b")):
            sx, w = ASYM_SRC_COLS[cx]
            sy, h = ASYM_SRC_ROWS[cy]
            dx = 0 if cx == "l" else ASYM_DEST[0] - w
            dy = 0 if cy == "t" else ASYM_DEST[1] - h
            src_block = self.src.subsurface(pygame.Rect(sx, sy, w, h))
            dst_block = self.t.subsurface(pygame.Rect(dx, dy, w, h))
            with self.subTest(corner=(cx, cy)):
                self.assertEqual(pygame.image.tobytes(dst_block, "RGBA"),
                                 pygame.image.tobytes(src_block, "RGBA"))


class TestZeroMargins(NineSliceCase):
    def test_zero_margin_axis_stretches_freely(self):
        # No x margins => the horizontal middle band IS the whole source width,
        # so x stretches freely (a pure 1x3 patch) while the 2px top/bottom bands
        # stay fixed. top+bottom must stay < the 6px source height, or the SOURCE
        # middle band is 0 tall and the sprite renders torn in half.
        t = draw_patch(self.src, (30, 12), margins=(0, 2, 0, 2))
        # the middle band is real: opaque all the way across, all the way down
        for y in range(12):
            for x in (0, 15, 29):
                self.assertEqual(t.get_at((x, y))[3], 255, f"transparent at {(x, y)}")
        # y bands hold (src rows 2..3 are the blue centre band), x stretches:
        self.assertPixel(t, (15, 5), BLUE)    # midpoint -> the source's centre
        self.assertPixel(t, (1, 5), GREEN)    # ...its green flanks, stretched
        self.assertPixel(t, (28, 5), GREEN)
        # the top band keeps its 2px height but its corners stretch on x too
        self.assertPixel(t, (15, 0), GREEN)
        self.assertPixel(t, (1, 0), RED)
        self.assertPixel(t, (28, 0), RED)

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


class TestClampPairSharedWithBackend(unittest.TestCase):
    """A8: engine/render/backend.py deleted its local `_clamp_pair` and now
    imports `engine.assets.nine_slice.clamp_pair` — the SAME function object,
    not a reimplementation, so forward compositing and the hit-test inverse
    below can never drift apart."""

    def test_backend_clamp_pair_is_the_shared_pure_function(self):
        self.assertIs(backend._clamp_pair, nine_slice.clamp_pair)


class TestDestToSource(unittest.TestCase):
    """`nine_slice.dest_to_source` — the exact piecewise inverse of
    `_nine_patch`'s band layout (A8). Source 6x6, dest 20x20, margins
    (2,2,2,2) throughout, matching TestGeometry's fixture above."""

    SRC = (6, 6)
    DEST = (20, 20)
    MARGINS = (2, 2, 2, 2)

    def test_dest_to_source_corners_map_1_to_1_leading_end(self):
        for pos in ((0, 0), (1, 1), (2, 2)):
            self.assertEqual(
                nine_slice.dest_to_source(pos, self.DEST, self.SRC, self.MARGINS),
                pos)

    def test_dest_to_source_corners_map_1_to_1_trailing_end(self):
        cases = {(19, 19): (5, 5), (18, 18): (4, 4), (17, 17): (3, 3)}
        for pos, expected in cases.items():
            self.assertEqual(
                nine_slice.dest_to_source(pos, self.DEST, self.SRC, self.MARGINS),
                expected)

    def test_dest_to_source_centre_scales_by_band_width_ratio(self):
        # centre band: source [2,4), dest [2,18); 2 + (10-2)*2//16 = 3
        self.assertEqual(
            nine_slice.dest_to_source((10, 10), self.DEST, self.SRC, self.MARGINS),
            (3, 3))

    def test_dest_to_source_degenerate_margins_clamp_without_raising(self):
        # margins (5,5,5,5) into a 6px source and a 2px dest — must not raise
        for pos in ((0, 0), (1, 1), (1, 0), (0, 1)):
            sx, sy = nine_slice.dest_to_source(pos, (2, 2), (6, 6), (5, 5, 5, 5))
            self.assertTrue(0 <= sx < 6)
            self.assertTrue(0 <= sy < 6)

    def test_dest_to_source_none_margins_are_plain_scale(self):
        self.assertEqual(
            nine_slice.dest_to_source((10, 10), self.DEST, self.SRC, None),
            (3, 3))   # 10*6//20 == 3

    def test_dest_to_source_zero_margins_are_plain_scale(self):
        self.assertEqual(
            nine_slice.dest_to_source((10, 10), self.DEST, self.SRC, (0, 0, 0, 0)),
            (3, 3))

    def test_dest_to_source_out_of_bounds_clamps(self):
        # the function itself never checks dest bounds (pure, no crash) —
        # it just keeps computing; the RESULT still lands somewhere sane.
        sx, sy = nine_slice.dest_to_source((-1, 5), self.DEST, self.SRC,
                                           self.MARGINS)
        # negative rel_x: left-corner branch, 1:1 (sx == rel_x, unclamped);
        # rel_y=5 lands in the centre row band: 2 + (5-2)*2//16 == 2
        self.assertEqual((sx, sy), (-1, 2))
        sx, sy = nine_slice.dest_to_source((25, 25), self.DEST, self.SRC,
                                           self.MARGINS)
        # 25 >= dw - dr (18) -> trailing-corner branch: sw - (dw - rel) = 6-(20-25)=11
        self.assertEqual((sx, sy), (11, 11))


class TestDestToSourceGeometry(NineSliceCase):
    """Composite cross-check: render the synthetic 3-colour sheet through the
    REAL `backend._nine_patch`, then verify `dest_to_source` maps a grid of
    interior points on each band back to a source pixel of the SAME colour
    the composite actually drew there (±1px tolerance at band seams, since
    edges/centre are resampled)."""

    def assert_matches_composite(self, target, dx, dy, margins):
        sx, sy = nine_slice.dest_to_source((dx, dy), (20, 20), (6, 6), margins)
        expected = target.get_at((dx, dy))[:3]
        actual = self.src.get_at((sx, sy))[:3]
        self.assertEqual(actual, expected,
                         f"dest {(dx, dy)} -> source {(sx, sy)}")

    def test_interior_points_on_each_band_agree_with_the_composite(self):
        target = draw_patch(self.src, (20, 20))   # margins=MARGINS default
        # (5,5) centre, (1,10) left edge, (10,1) top edge, (18,10) right edge,
        # (10,18) bottom edge, and all four corners well inside their 2px box
        for dx, dy in ((5, 5), (1, 10), (10, 1), (18, 10), (10, 18),
                       (0, 0), (19, 0), (0, 19), (19, 19)):
            with self.subTest(pos=(dx, dy)):
                self.assert_matches_composite(target, dx, dy, MARGINS)


class TestDestToSourceDegenerateBand(NineSliceCase):
    """A8 carry-over fix (HIGH, interrupted review): margins that clamp to
    fill the SOURCE dimension exactly (`sl + sr == sw`) while the DEST still
    has a centre band on that axis (`dw > sw`) leave `_nine_patch` painting
    NOTHING there -- the source centre band is 0px wide, so the `min(sw_i,
    sh_i, dw_i, dh_i) <= 0` skip in `_nine_patch` drops that band across
    every row. `dest_to_source` must report a miss for a `rel_xy` in that
    band, not resolve to the source's boundary pixel `sl` -- that pixel is a
    REAL, painted, opaque pixel elsewhere on the sheet (the first column of
    the right band, since `sl == sw - sr` here), so reading it instead of
    signalling a miss is exactly the bug: `hit_opaque` would return True over
    on-screen transparency."""

    # left + right == 6 == src_w -> horizontal centre band vanishes in the
    # SOURCE; dl, dr stay unclamped (3+3==6 <= dw=20) so the DEST still has a
    # 14px centre band (columns [3, 17)) with nothing to paint into it.
    MARGINS = (3, 2, 3, 2)
    DEST = (20, 20)
    SRC = (6, 6)
    VANISHED_COLUMNS = (3, 5, 10, 15, 16)   # inside dest [3, 17)

    def test_composite_leaves_the_vanished_band_transparent(self):
        t = draw_patch(self.src, self.DEST, margins=self.MARGINS)
        for x in self.VANISHED_COLUMNS:
            for y in (0, 5, 10, 19):
                self.assertEqual(t.get_at((x, y))[3], 0,
                                 f"expected transparent at {(x, y)}")
        # sanity: the surrounding corner/edge columns ARE painted
        for x in (0, 2, 17, 19):
            self.assertEqual(t.get_at((x, 5))[3], 255,
                             f"expected painted at {(x, 5)}")

    def test_dest_to_source_signals_a_miss_in_the_vanished_band(self):
        for x in self.VANISHED_COLUMNS:
            sx, sy = nine_slice.dest_to_source((x, 5), self.DEST, self.SRC,
                                               self.MARGINS)
            self.assertFalse(0 <= sx < self.SRC[0],
                             f"sx={sx} should be out of [0, {self.SRC[0]})")

    def test_naive_boundary_pixel_would_have_read_opaque(self):
        # Documents WHY the miss signal is needed: sl (== sw - sr == 3) is
        # the first column of the RIGHT band -- a real, opaque, BLUE pixel
        # -- not "no content". Resolving a vanished-band rel_xy to sx == sl
        # (the pre-fix behaviour) would read this pixel and return True.
        sl = 3
        self.assertEqual(self.src.get_at((sl, 2))[3], 255)

    def test_vertical_axis_degenerates_the_same_way(self):
        # top + bottom == 6 == src_h this time; dest still has a vertical
        # centre band since dh=20 > 6.
        margins = (2, 3, 2, 3)
        dest = (20, 20)
        t = draw_patch(self.src, dest, margins=margins)
        for y in (3, 5, 10, 15, 16):
            self.assertEqual(t.get_at((5, y))[3], 0,
                             f"expected transparent at {(5, y)}")
            sx, sy = nine_slice.dest_to_source((5, y), dest, self.SRC, margins)
            self.assertFalse(0 <= sy < self.SRC[1],
                             f"sy={sy} should be out of [0, {self.SRC[1]})")


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
