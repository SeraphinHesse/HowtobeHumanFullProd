"""Phase 9C: Dijkstra pathfinder (game/map/pathfinder.py).

Ports the prototype's src/map/pathfinder.py (five find_path* variants,
4-connected, min-heap, impassable skip, wall hook). Exact paths are asserted on
a tiny synthetic grid (heap-order-independent: endpoints + contiguity + cost);
the shipped map exercises a full spawn→base route.
"""
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from game.map import (
    find_path,
    find_path_ignoring_walls,
    find_path_to_nearest_building,
    find_path_to_nearest_defence,
    find_path_to_nearest_economic,
    load_map_balance,
)
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAP = REPO / "data" / "maps" / "first_light.json"
MAP_SCHEMA = REPO / "data" / "schemas" / "map_file.schema.json"
BALANCE = load_map_balance(REPO / "data")


def synth(terrain_rows, base=(1, 1)):
    """Build a TileMap from raw legend-code rows (b/c/s/f/l/o). TileMap reads
    only cols/rows/base/terrain, so legend/deco can be empty."""
    rows = len(terrain_rows)
    cols = len(terrain_rows[0])
    doc = tilemap.TileMapDoc(
        map_id="synth",
        display_name="Synth",
        cols=cols,
        rows=rows,
        legend={},
        terrain=[list(r) for r in terrain_rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"},
        deco=[],
    )
    return TileMap(doc, BALANCE)


def is_contiguous(path):
    return all(
        abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
        for a, b in zip(path, path[1:])
    )


def path_cost(tm, path):
    """Sum of weights of every tile stepped onto (the start contributes 0,
    matching Dijkstra's cost accounting)."""
    return sum(tm.weight(tm.get(c, r)) for c, r in path[1:])


OPEN_5x5 = [
    "ooooo",
    "occco",
    "occco",
    "occco",
    "ooooo",
]


class TestBasePath(unittest.TestCase):
    def test_shortest_path_to_base(self):
        tm = synth(OPEN_5x5)
        path = find_path(tm, 3, 3)
        self.assertEqual(path[0], (3, 3))
        self.assertEqual(path[-1], (1, 1))
        self.assertEqual(len(path), 5)          # 4 steps
        self.assertTrue(is_contiguous(path))
        self.assertEqual(path_cost(tm, path), 3)  # 3 combat @1 + base @0

    def test_start_on_base(self):
        tm = synth(OPEN_5x5)
        self.assertEqual(find_path(tm, 1, 1), [(1, 1)])

    def test_all_path_tiles_passable(self):
        tm = synth(OPEN_5x5)
        path = find_path(tm, 3, 3)
        self.assertTrue(all(tm.get(c, r).is_passable for c, r in path))


class TestObstacleRouting(unittest.TestCase):
    # Partial wall at col2 rows1-2 (background); row3 stays open.
    PARTIAL = [
        "ooooo",
        "ococo",
        "ococo",
        "occco",
        "ooooo",
    ]
    # Full col2 wall isolates the base column from (3,*).
    SEALED = [
        "ooooo",
        "ococo",
        "ococo",
        "ococo",
        "ooooo",
    ]

    def test_routes_around_background(self):
        tm = synth(self.PARTIAL)
        path = find_path(tm, 3, 3)
        self.assertEqual(path[-1], (1, 1))
        self.assertTrue(all(tm.get(c, r).is_passable for c, r in path))
        self.assertTrue(is_contiguous(path))

    def test_unreachable_returns_empty(self):
        tm = synth(self.SEALED)
        self.assertEqual(find_path(tm, 3, 3), [])


class TestVariants(unittest.TestCase):
    def test_no_buildings_all_variants_fall_back_to_base(self):
        tm = synth(OPEN_5x5)
        base_path = find_path(tm, 3, 3)
        for fn in (find_path_to_nearest_economic,
                   find_path_to_nearest_defence,
                   find_path_to_nearest_building):
            with self.subTest(fn=fn.__name__):
                self.assertEqual(fn(tm, 3, 3), base_path)

    def test_ignoring_walls_matches_base_without_walls(self):
        tm = synth(OPEN_5x5)
        self.assertEqual(find_path_ignoring_walls(tm, 3, 3), find_path(tm, 3, 3))

    def test_targets_nearest_defence_building(self):
        tm = synth(OPEN_5x5)
        goal = tm.get(3, 1)
        goal.state = TileState.BUILT
        goal.content_key = "defence_building"
        goal.occupant = types.SimpleNamespace(building_type="defence", alive=True)
        path = find_path_to_nearest_defence(tm, 3, 3)
        self.assertEqual(path[0], (3, 3))
        self.assertEqual(path[-1], (3, 1))
        self.assertTrue(is_contiguous(path))

    def test_dead_building_is_not_a_goal(self):
        tm = synth(OPEN_5x5)
        goal = tm.get(3, 1)
        goal.state = TileState.BUILT
        goal.content_key = "defence_building"
        goal.occupant = types.SimpleNamespace(building_type="defence", alive=False)
        # dead → falls back to the base path
        self.assertEqual(
            find_path_to_nearest_defence(tm, 3, 3), find_path(tm, 3, 3))


class TestShippedMap(unittest.TestCase):
    def test_spawn_to_base_route(self):
        doc = tilemap.load_map(MAP, MAP_SCHEMA)
        tm = TileMap(doc, BALANCE)
        start = (10, 1)  # a spawn tile
        self.assertEqual(tm.get(*start).state, TileState.SPAWNING)
        path = find_path(tm, *start)
        self.assertTrue(path, "spawn tile should reach the base")
        self.assertEqual(path[0], start)
        self.assertEqual(path[-1], (1, 1))
        self.assertTrue(is_contiguous(path))
        self.assertTrue(all(tm.get(c, r).is_passable for c, r in path))


if __name__ == "__main__":
    unittest.main()
