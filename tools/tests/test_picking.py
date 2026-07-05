"""Phase 9C: screen→tile picking (game/map/picking.py).

Picking goes through engine.coords only (no bespoke iso math): a tile's world
centre projects to a screen pixel and inverts + floors back to that tile.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine.coords import load_coordinate_system
from engine import tilemap
from game.map import load_map_balance, tile_at_screen, world_to_tile
from game.map.tile_map import TileMap

MAP = REPO / "data" / "maps" / "first_light.json"
MAP_SCHEMA = REPO / "data" / "schemas" / "map_file.schema.json"
BALANCE = load_map_balance(REPO / "data")


def make_env():
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    tm = TileMap(doc, BALANCE)
    coords = load_coordinate_system(REPO / "data", map_cols=doc.cols, map_rows=doc.rows)
    return tm, coords


class TestWorldToTile(unittest.TestCase):
    def test_floor_of_world_coords(self):
        self.assertEqual(world_to_tile(5.5, 7.5), (5, 7))
        self.assertEqual(world_to_tile(0.0, 0.0), (0, 0))
        self.assertEqual(world_to_tile(3.99, 2.01), (3, 2))


class TestTileAtScreen(unittest.TestCase):
    def test_tile_centre_round_trips(self):
        tm, coords = make_env()
        for col, row in ((5, 7), (1, 1), (0, 0), (12, 3), (19, 19)):
            with self.subTest(tile=(col, row)):
                sx, sy = coords.world_to_screen(col + 0.5, row + 0.5)
                picked = tile_at_screen(tm, coords, sx, sy)
                self.assertIsNotNone(picked)
                self.assertEqual((picked.col, picked.row), (col, row))

    def test_off_grid_returns_none(self):
        tm, coords = make_env()
        # A world point well outside the grid → no tile.
        sx, sy = coords.world_to_screen(-5.0, -5.0)
        self.assertIsNone(tile_at_screen(tm, coords, sx, sy))

    def test_survives_pan_and_zoom(self):
        tm, coords = make_env()
        coords.pan(137.0, -84.0)
        if coords.geometry.zoom_levels:
            coords.set_zoom(coords.geometry.zoom_levels[-1])
        sx, sy = coords.world_to_screen(8 + 0.5, 4 + 0.5)
        picked = tile_at_screen(tm, coords, sx, sy)
        self.assertEqual((picked.col, picked.row), (8, 4))


if __name__ == "__main__":
    unittest.main()
