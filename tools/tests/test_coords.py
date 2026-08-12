"""Phase 1 acceptance tests for engine/coords (E-1..E-5) and data_io (D-2/D-3).

Pure Python — importing these modules must never pull in pygame
(guarded separately in test_render.py).
"""
import json
import pathlib
import tempfile
import unittest

import jsonschema

from engine import data_io
from engine.coords import Camera, CoordinateSystem, Geometry, load_coordinate_system

REPO = pathlib.Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA
DATA = FIXTURE_DATA


def make_cs(zoom_levels=(0.5, 1.0, 2.0), **camera):
    geo = Geometry(
        tile_w=64, tile_h=32, map_cols=20, map_rows=20, zoom_levels=zoom_levels
    )
    # Pin the test camera to zoom 1 explicitly rather than relying on
    # Camera's dataclass default (now 2.0, the new game/editor default) —
    # these tests assert projection math at a known zoom, independent of
    # whatever the real host's opening zoom happens to be.
    camera.setdefault("zoom", 1.0)
    return CoordinateSystem(geo, Camera(**camera))


class TestGeometryFromData(unittest.TestCase):
    """E-1: geometry loads from data/, validated — never hardcoded."""

    def test_loads_and_matches_prototype_pitch(self):
        cs = load_coordinate_system(DATA)
        self.assertEqual(cs.geometry.tile_w, 64)
        self.assertEqual(cs.geometry.tile_h, 32)
        self.assertEqual(cs.geometry.map_cols, 20)
        self.assertEqual(cs.geometry.map_rows, 20)
        self.assertIn(1.0, cs.geometry.zoom_levels)

    def test_map_dim_overrides(self):
        """Phase 6 (D-20): each map owns its dims; pitch/zoom stay global."""
        cs = load_coordinate_system(DATA, map_cols=7, map_rows=9)
        self.assertEqual(cs.geometry.map_cols, 7)
        self.assertEqual(cs.geometry.map_rows, 9)
        self.assertEqual(cs.geometry.tile_w, 64)  # untouched global truth

    def test_invalid_geometry_fails_loud(self):
        schema_path = DATA / "schemas" / "geometry.schema.json"
        with tempfile.TemporaryDirectory() as tmp:
            bad = pathlib.Path(tmp) / "geometry.json"
            bad.write_text(json.dumps({"tile_w": 64}), encoding="utf-8")
            with self.assertRaises(jsonschema.ValidationError):
                data_io.load_validated(bad, schema_path)


class TestProjection(unittest.TestCase):
    """E-2: world_to_screen = iso projection + camera pan + zoom."""

    def test_known_values_at_origin_camera(self):
        cs = make_cs()
        self.assertEqual(cs.world_to_screen(0, 0), (0.0, 0.0))
        self.assertEqual(cs.world_to_screen(1, 0), (32.0, 16.0))
        self.assertEqual(cs.world_to_screen(0, 1), (-32.0, 16.0))
        self.assertEqual(cs.world_to_screen(1, 1), (0.0, 32.0))

    def test_pan_shifts_screen(self):
        cs = make_cs()
        cs.pan(10, 20)
        cs.pan(10, 20)
        self.assertEqual(cs.world_to_screen(0, 0), (-20.0, -40.0))

    def test_zoom_scales_projection(self):
        cs = make_cs()
        cs.set_zoom(2.0)
        self.assertEqual(cs.world_to_screen(1, 1), (0.0, 64.0))


class TestRoundTrip(unittest.TestCase):
    """E-3: screen_to_world is the exact inverse (< 1e-6 at zoom 1)."""

    POINTS = [(0, 0), (3.25, 7.5), (19.999, 0.001), (-2.5, 4.75), (10.1, 10.9)]
    PANS = [(0, 0), (123.4, -56.7), (-1000.0, 500.25)]

    def test_round_trip_across_zooms_and_pans(self):
        for zoom in (0.5, 1.0, 2.0):
            for pan in self.PANS:
                cs = make_cs(pan_x=pan[0], pan_y=pan[1])
                cs.set_zoom(zoom)
                for wx, wy in self.POINTS:
                    px, py = cs.world_to_screen(wx, wy)
                    rx, ry = cs.screen_to_world(px, py)
                    self.assertLess(
                        abs(rx - wx) + abs(ry - wy),
                        1e-6,
                        msg=f"round-trip failed at zoom={zoom} pan={pan} w=({wx},{wy})",
                    )


class TestDepthKey(unittest.TestCase):
    """E-4: iso depth ordering by world position + layer index."""

    def test_farther_tiles_sort_first(self):
        cs = make_cs()
        self.assertLess(cs.depth_key(2, 3), cs.depth_key(3, 3))
        self.assertLess(cs.depth_key(3, 2), cs.depth_key(3, 3))

    def test_equal_sum_tiebreak_is_deterministic(self):
        cs = make_cs()
        a, b = cs.depth_key(5, 0), cs.depth_key(0, 5)
        self.assertNotEqual(a, b)
        self.assertEqual(sorted([b, a]), sorted([a, b]))

    def test_layer_index_dominates_position(self):
        cs = make_cs()
        self.assertLess(cs.depth_key(19, 19, layer_index=0),
                        cs.depth_key(0, 0, layer_index=1))


class TestCamera(unittest.TestCase):
    """E-5: pan / clamp / zoom levels — pure state, no input handling."""

    def test_zoom_restricted_to_data_levels(self):
        cs = make_cs()
        cs.set_zoom(0.5)
        self.assertEqual(cs.camera.zoom, 0.5)
        with self.assertRaises(ValueError):
            cs.set_zoom(3.0)

    def test_clamp_to_map_bounds(self):
        # 20x20 map, 64x32 pitch → iso bounds x:[-640, 640], y:[0, 640] at zoom 1
        cs = make_cs()
        cs.pan(-100000, -100000)
        cs.clamp(800, 600)
        self.assertEqual((cs.camera.pan_x, cs.camera.pan_y), (-640.0, 0.0))
        cs.pan(200000, 200000)
        cs.clamp(800, 600)
        self.assertEqual((cs.camera.pan_x, cs.camera.pan_y), (-160.0, 40.0))

    def test_clamp_centers_when_map_smaller_than_viewport(self):
        cs = make_cs()
        cs.clamp(2000, 2000)
        self.assertEqual((cs.camera.pan_x, cs.camera.pan_y), (-1000.0, -680.0))

    def test_center_on_puts_target_at_viewport_centre(self):
        # map centre (10,10) overflows a narrow viewport → clamp alone would
        # anchor it to an edge; center_on parks it at the middle instead.
        cs = make_cs()
        cs.center_on(10, 10, 590, 500)
        sx, sy = cs.world_to_screen(10, 10)
        self.assertAlmostEqual(sx, 295.0)
        self.assertAlmostEqual(sy, 250.0)

    def test_mutators_keep_pan_integer(self):
        # Integer-pan invariant (JitteryMapFix): a fractional pan makes the
        # ground cache and the per-item sprite path quantize it at different
        # sub-pixel phases (layers desync while panning). Every mutator must
        # leave pan whole, even from fractional inputs / centring division.
        cs = make_cs(pan_x=0.25, pan_y=-0.75)  # direct construction may be float
        cs.pan(10.4, -3.3)
        self.assertEqual(cs.camera.pan_x, round(cs.camera.pan_x))
        self.assertEqual(cs.camera.pan_y, round(cs.camera.pan_y))
        cs.clamp(801, 601)          # odd viewport → centring halves would fracture
        self.assertEqual(cs.camera.pan_x, round(cs.camera.pan_x))
        self.assertEqual(cs.camera.pan_y, round(cs.camera.pan_y))
        cs.center_on(3.5, 7.25, 801, 601)
        self.assertEqual(cs.camera.pan_x, round(cs.camera.pan_x))
        self.assertEqual(cs.camera.pan_y, round(cs.camera.pan_y))

    def test_center_on_still_clamps_off_map_target(self):
        # a target past the map edge is re-clamped onto the map (never off it)
        cs = make_cs()
        cs.center_on(0, 0, 800, 600)
        min_x, min_y, max_x, max_y = cs.map_pixel_bounds()
        self.assertGreaterEqual(cs.camera.pan_x, min_x)
        self.assertLessEqual(cs.camera.pan_x, max_x - 800)
        self.assertGreaterEqual(cs.camera.pan_y, min_y)


class TestVisibleTileWindow(unittest.TestCase):
    """E-5: the on-screen tile range for windowed culling — the AABB of the
    four screen-corner inversions, optionally padded by a whole-tile margin."""

    def test_window_is_corner_aabb(self):
        # pan 0, zoom 1: corners invert to wx∈[0,25], wy∈[-10,15] for 640x480.
        cs = make_cs()
        self.assertEqual(cs.visible_tile_window(640, 480), (0, 25, -10, 15))

    def test_margin_pads_all_sides(self):
        cs = make_cs()
        self.assertEqual(
            cs.visible_tile_window(640, 480, margin=4), (-4, 29, -14, 19))

    def test_covers_every_on_screen_tile(self):
        # exhaustive: any tile whose diamond origin projects inside the viewport
        # must fall inside the (margin-0) window.
        cs = make_cs(pan_x=-200, pan_y=-50)
        cmin, cmax, rmin, rmax = cs.visible_tile_window(640, 480)
        for row in range(-50, 70):
            for col in range(-50, 70):
                sx, sy = cs.world_to_screen(col, row)
                if 0 <= sx < 640 and 0 <= sy < 480:
                    self.assertTrue(
                        cmin <= col <= cmax and rmin <= row <= rmax,
                        f"tile ({col},{row}) at ({sx},{sy}) not in window")


class TestDataIO(unittest.TestCase):
    """D-3: deterministic formatting. D-2: writes validate."""

    def test_dumps_deterministic(self):
        out = data_io.dumps_deterministic({"b": 1, "a": [1, 2]})
        self.assertTrue(out.endswith("\n"))
        self.assertLess(out.index('"a"'), out.index('"b"'))
        self.assertIn('  "a"', out)  # 2-space indent
        self.assertEqual(json.loads(out), {"a": [1, 2], "b": 1})

    def test_write_validated_rejects_invalid(self):
        schema_path = DATA / "schemas" / "geometry.schema.json"
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "geometry.json"
            with self.assertRaises(jsonschema.ValidationError):
                data_io.write_validated({"tile_w": 64}, target, schema_path)
            self.assertFalse(target.exists())

    def test_write_validated_round_trips(self):
        schema_path = DATA / "schemas" / "geometry.schema.json"
        good = {
            "map_cols": 4, "map_rows": 3, "tile_h": 16, "tile_w": 32,
            "zoom_levels": [1.0],
        }
        with tempfile.TemporaryDirectory() as tmp:
            target = pathlib.Path(tmp) / "geometry.json"
            data_io.write_validated(good, target, schema_path)
            self.assertEqual(data_io.load_validated(target, schema_path), good)


if __name__ == "__main__":
    unittest.main()
