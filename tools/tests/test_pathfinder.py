"""Phase 9C: Dijkstra pathfinder (game/map/pathfinder.py).

Ports the prototype's src/map/pathfinder.py (five find_path* variants,
4-connected, min-heap, impassable skip, wall hook). Exact paths are asserted on
a tiny synthetic grid (heap-order-independent: endpoints + contiguity + cost);
the shipped map exercises a full spawn→base route.
"""
import heapq
import random
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from game.map import (
    find_path,
    find_path_ignoring_walls,
    find_path_to_nearest_building,
    find_path_to_nearest_defence,
    find_path_to_nearest_economic,
    load_map_balance,
)
from game.map.pathfinder import _dijkstra
from game.map.tile_map import TileMap
from game.map.tiles import TileCondition, TileState

MAP = FIXTURE_DATA / "maps" / "first_light.json"
MAP_SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
BALANCE = load_map_balance(FIXTURE_DATA)


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
        tm.set_tile_state(goal, TileState.BUILT)
        goal.content_key = "defence_building"
        goal.occupant = types.SimpleNamespace(building_type="defence", alive=True)
        path = find_path_to_nearest_defence(tm, 3, 3)
        self.assertEqual(path[0], (3, 3))
        self.assertEqual(path[-1], (3, 1))
        self.assertTrue(is_contiguous(path))

    def test_dead_building_is_not_a_goal(self):
        tm = synth(OPEN_5x5)
        goal = tm.get(3, 1)
        tm.set_tile_state(goal, TileState.BUILT)
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


class TestDijkstraReturnsTheRouteItCosted(unittest.TestCase):
    """Regression: ``_dijkstra`` guarded its relax on ``dist`` — the SETTLED
    map — so ``dist.get(node)`` was inf for every not-yet-settled node and EVERY
    relaxation passed, including later, worse ones, each overwriting ``prev``
    with a worse parent. The goal still settled at the correct cost (the heap
    pops in order), but ``_reconstruct`` then walked the clobbered back-pointers
    and returned a different, more expensive route than the one Dijkstra had
    costed. Measured on a pond board: a 23-cost path to a goal it had reached at
    cost 12, doubling back through the water.

    ``_build_flow_field`` always kept a separate tentative-``best`` map (its
    docstring says why); ``_dijkstra`` now does too. This is a real part of the
    boss's "wandering" — every goal-set variant runs through here."""

    @staticmethod
    def _reference_cost(tm, start, goal):
        """A textbook Dijkstra that only ever settles COSTS — no back-pointers,
        so it cannot be wrong in the way the bug was."""
        dist = {}
        heap = [(0, start)]
        while heap:
            cost, node = heapq.heappop(heap)
            if node in dist:
                continue
            dist[node] = cost
            if node == goal:
                return cost
            col, row = node
            for nb in ((col + 1, row), (col - 1, row),
                       (col, row + 1), (col, row - 1)):
                if not (0 <= nb[0] < tm.cols and 0 <= nb[1] < tm.rows):
                    continue
                if nb in dist:
                    continue
                w = tm.weight(tm.get(*nb))
                if w >= tm.impassable_weight:
                    continue
                heapq.heappush(heap, (cost + w, nb))
        return None

    def test_the_returned_path_costs_what_dijkstra_said_it_would(self):
        start, goal = (6, 4), (0, 0)
        for seed in range(40):
            rng = random.Random(seed)
            tm = synth(["ccccccc"] * 5, base=goal)
            for col in range(7):
                for row in range(5):
                    if (col, row) not in (start, goal) and rng.random() < 0.35:
                        tm.get(col, row).condition = TileCondition.POND
            with self.subTest(seed=seed):
                path = _dijkstra(tm, start[0], start[1], {goal},
                                 ignore_walls=False)
                self.assertTrue(path)
                self.assertEqual(path[0], start)
                self.assertEqual(path[-1], goal)
                self.assertTrue(is_contiguous(path))
                self.assertEqual(path_cost(tm, path),
                                 self._reference_cost(tm, start, goal))


class TestWeightProfiles(unittest.TestCase):
    """Chunk 3 — the optional per-caller ``cond_weights`` profile threaded
    through every ``find_path*`` query, and the flow-field cache key it
    extends to ``(ignore_walls, footprint, profile_key)``."""

    def test_a_low_pond_weight_changes_the_chosen_route(self):
        # A pond sits directly on the straight route from the spawn to the
        # base; going around costs 6 (six plain combat tiles) vs going
        # straight through at the default pond weight (9): 1 + (1+9) + 1 =
        # 12 — so the default profile detours around it. At pond=1 the
        # straight route costs 1 + (1+1) + 1 = 4 — cheaper than the detour,
        # so the SAME query now walks straight through it.
        tm = synth(["ccccc", "ccccc", "ccccc"], base=(0, 1))
        tm.get(2, 1).condition = TileCondition.POND
        start = (4, 1)
        default_path = find_path(tm, *start)
        self.assertNotIn((2, 1), default_path)
        cheap_pond = {"forest": 1, "mountain": 2, "pond": 1}
        cheap_path = find_path(tm, *start, cond_weights=cheap_pond)
        self.assertIn((2, 1), cheap_path)
        self.assertTrue(is_contiguous(cheap_path))
        self.assertEqual(cheap_path[0], start)
        self.assertEqual(cheap_path[-1], (0, 1))

    def test_identical_profiles_share_one_flow_field(self):
        """Two DIFFERENT dict objects with the same values must collapse onto
        ONE cached field — never one per caller, let alone one per enemy
        (game/PERF.md)."""
        tm = synth(OPEN_5x5)
        profile_a = {"forest": 1, "mountain": 2, "pond": 9}
        profile_b = dict(profile_a)
        self.assertIsNot(profile_a, profile_b)
        find_path(tm, 3, 3, cond_weights=profile_a)
        find_path(tm, 3, 3, cond_weights=profile_b)
        fields = tm._flow_cache[1]
        matching = [k for k in fields if k[0] is False and k[1] == 1]
        self.assertEqual(len(matching), 1)


if __name__ == "__main__":
    unittest.main()
