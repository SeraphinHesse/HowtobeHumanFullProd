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
    find_path_to_nearest_structure,
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


#: every occupant ``building_type`` the game ships (game/buildings/*.py's
#: BUILDING_TYPE constants). The hunt-category matrix below asserts against the
#: WHOLE roster, so a new building type that no category claims is visible.
ALL_BUILDING_TYPES = (
    "defence", "aoe_defence", "storm_priest", "sun_scorcher",   # attack-capable
    "blocker", "wall_builder",                                  # structures
    "economic", "meditator", "painter",                         # economy
    "boost_speed", "boost_damage", "boost_hp",                  # boosts
    "base",                                                     # the hole
)

#: NE-0/D1 — what ``find_path_to_nearest_defence`` hunts since the widening.
ATTACK_TYPES = {"defence", "aoe_defence", "storm_priest", "sun_scorcher"}
#: NE-0/D2 — what ``find_path_to_nearest_structure`` hunts.
STRUCTURE_TYPES = ATTACK_TYPES | {"blocker", "wall_builder"}
#: unchanged, kept here so the matrix covers all three hunt predicates at once.
ECONOMY_TYPES = {"economic", "meditator", "painter"}


def occupy(tm, col, row, building_type):
    """Put a live duck-typed occupant of ``building_type`` on (col, row), the
    way ``game/buildings/registry.py`` does: BUILT state, the matching
    ``<type>_building`` content key, through the ONE ``set_tile_content``
    seam (so the flow-field cache invalidates)."""
    tile = tm.get(col, row)
    tm.set_tile_state(tile, TileState.BUILT)
    tm.set_tile_content(
        tile,
        types.SimpleNamespace(building_type=building_type, alive=True),
        f"{building_type}_building",
    )
    return tile


class TestVariants(unittest.TestCase):
    def test_no_buildings_all_variants_fall_back_to_base(self):
        tm = synth(OPEN_5x5)
        base_path = find_path(tm, 3, 3)
        for fn in (find_path_to_nearest_economic,
                   find_path_to_nearest_defence,
                   find_path_to_nearest_structure,
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


class TestHuntCategories(unittest.TestCase):
    """NE-0 — the two hunt-predicate changes, asserted as a full matrix over
    every ``building_type`` the game ships.

    D1: ``find_path_to_nearest_defence`` widened from the single literal
    ``"defence"`` to every ATTACK-CAPABLE building. D2: the new
    ``find_path_to_nearest_structure`` covers every non-economy, non-boost,
    non-base building. Both ride the existing ``_hunt``/``_goal_tiles``
    helpers, so what is under test here is ONLY the predicate — a match must
    end the path on the occupied tile, a non-match must fall through to the
    base path (``_hunt``'s no-goals branch)."""

    #: (query, the building_type set it must claim)
    QUERIES = (
        (find_path_to_nearest_defence, ATTACK_TYPES),
        (find_path_to_nearest_structure, STRUCTURE_TYPES),
        (find_path_to_nearest_economic, ECONOMY_TYPES),
    )

    def _assert_matrix(self, query, claimed):
        for btype in ALL_BUILDING_TYPES:
            with self.subTest(query=query.__name__, building_type=btype):
                tm = synth(OPEN_5x5)
                occupy(tm, 3, 1, btype)
                path = query(tm, 3, 3)
                if btype in claimed:
                    self.assertEqual(path[0], (3, 3))
                    self.assertEqual(path[-1], (3, 1))
                    self.assertTrue(is_contiguous(path))
                else:
                    # no goal in the set → _hunt falls back to the base path
                    self.assertEqual(path, find_path(tm, 3, 3))
                    self.assertEqual(path[-1], (1, 1))

    def test_defence_hunt_claims_exactly_the_attack_capable_buildings(self):
        """Widened (D1): aoe_defence / storm_priest / sun_scorcher are goals
        now, alongside the original defence. Everything else — economy,
        boosts, blocker, wall_builder, base — still is not."""
        self._assert_matrix(find_path_to_nearest_defence, ATTACK_TYPES)

    def test_structure_hunt_claims_every_non_economy_non_boost_non_base(self):
        """New (D2): blocker + wall_builder + the four attack types; never
        economic / meditator / painter / boost_* / base."""
        self._assert_matrix(find_path_to_nearest_structure, STRUCTURE_TYPES)

    def test_economy_hunt_is_unchanged_by_NE0(self):
        """The third predicate, pinned in the same matrix so a future widening
        of one category cannot silently leak into another."""
        self._assert_matrix(find_path_to_nearest_economic, ECONOMY_TYPES)

    def test_the_three_categories_partition_the_roster_as_documented(self):
        """The prose invariant in ``pathfinder.py``'s comments, as an
        assertion: structure ∪ economy ∪ boosts ∪ base IS the whole roster, and
        attack ⊂ structure."""
        boosts = {"boost_speed", "boost_damage", "boost_hp"}
        self.assertTrue(ATTACK_TYPES < STRUCTURE_TYPES)
        self.assertEqual(
            STRUCTURE_TYPES | ECONOMY_TYPES | boosts | {"base"},
            set(ALL_BUILDING_TYPES))
        self.assertEqual(STRUCTURE_TYPES & ECONOMY_TYPES, set())

    def test_structure_hunt_picks_the_geometrically_nearest_of_two_kinds(self):
        """A blocker and a mortar both qualify — the NEARER one wins, so the
        widened set really is one goal set and not a priority order."""
        tm = synth(["ccccccc"] * 5, base=(0, 0))
        occupy(tm, 4, 2, "blocker")          # 2 tiles from the spawn
        occupy(tm, 1, 2, "aoe_defence")      # 5 tiles from the spawn
        self.assertEqual(find_path_to_nearest_structure(tm, 6, 2)[-1], (4, 2))
        # ... and with only the far mortar standing, it is still a goal.
        tm2 = synth(["ccccccc"] * 5, base=(0, 0))
        occupy(tm2, 1, 2, "aoe_defence")
        self.assertEqual(find_path_to_nearest_structure(tm2, 6, 2)[-1], (1, 2))

    def test_a_dead_attack_building_is_not_a_goal(self):
        """The widened predicate still runs through ``_goal_tiles``' alive
        filter — a dead mortar falls back to the base path."""
        tm = synth(OPEN_5x5)
        tile = occupy(tm, 3, 1, "aoe_defence")
        tile.occupant.alive = False
        for fn in (find_path_to_nearest_defence, find_path_to_nearest_structure):
            with self.subTest(fn=fn.__name__):
                self.assertEqual(fn(tm, 3, 3), find_path(tm, 3, 3))


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
