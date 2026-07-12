"""Flow-field base pathfinding (game/map/pathfinder.py + tile_map.py).

The large-map spawn fix (game/PERF.md): ``find_path`` walks ONE shared
reverse-Dijkstra field seeded at the base instead of running a forward
Dijkstra per enemy. Pinned here: forward-equivalence (same cost/endpoints/
contiguity as a direct ``_dijkstra`` call, exact route where it is unique),
cache reuse (one field build for many queries), and invalidation through
every mutation seam — zone change, content-key write, wall raise, wall
death. Headless, synthetic grids, real balancing (mirrors test_pathfinder).
"""
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
import game.map.pathfinder as pathfinder
from game.map import find_path, load_map_balance
from game.map.pathfinder import _dijkstra
from game.map.tile_map import TileMap, WallEdge, _wall_key
from game.map.tiles import TileCondition, TileState

BALANCE = load_map_balance(REPO / "data")


def synth(terrain_rows, base=(1, 1)):
    """TileMap from raw legend-code rows (b/c/s/f/l/o) — see test_pathfinder."""
    doc = tilemap.TileMapDoc(
        map_id="synth",
        display_name="Synth",
        cols=len(terrain_rows[0]),
        rows=len(terrain_rows),
        legend={},
        terrain=[list(r) for r in terrain_rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"},
        deco=[],
    )
    return TileMap(doc, BALANCE)


def forward(tm, col, row):
    """A direct forward Dijkstra to the base — the pre-flow-field oracle."""
    goal = (tm.base_col, tm.base_row)
    return _dijkstra(tm, col, row, {goal}, ignore_walls=False)


def is_contiguous(path):
    return all(
        abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
        for a, b in zip(path, path[1:])
    )


def path_cost(tm, path):
    """Sum of weights of every tile stepped onto (start contributes 0)."""
    return sum(tm.weight(tm.get(c, r)) for c, r in path[1:])


class TestForwardEquivalence(unittest.TestCase):
    # Mixed weights (mountain +2, pond +9, forest +1) + a wall edge + a
    # background pillar: the field must reproduce forward costs exactly.
    ROWS = [
        "ooooooo",
        "obcccco",
        "occocco",
        "occccso",
        "oscccco",
        "ooooooo",
    ]

    def _mixed_map(self):
        tm = synth(self.ROWS)
        tm.get(2, 1).condition = TileCondition.MOUNTAIN
        tm.get(3, 3).condition = TileCondition.POND
        tm.get(4, 2).condition = TileCondition.FOREST
        tm.get(2, 4).condition = TileCondition.MOUNTAIN
        # A live wall on the edge (2,1)-(2,2), injected before ANY query.
        key = _wall_key(2, 1, 2, 2)
        tm.wall_edges[key] = WallEdge(2, 1, 2, 2, 50, 50, object())
        return tm

    def test_same_cost_endpoints_and_validity_as_forward(self):
        tm = self._mixed_map()
        for start in ((5, 3), (1, 4), (5, 1), (2, 4), (4, 4), (1, 1)):
            with self.subTest(start=start):
                fwd = forward(tm, *start)
                ff = find_path(tm, *start)
                self.assertEqual(bool(ff), bool(fwd))
                if not ff:
                    continue
                self.assertEqual(ff[0], start)
                self.assertEqual(ff[-1], (tm.base_col, tm.base_row))
                self.assertTrue(is_contiguous(ff))
                self.assertEqual(path_cost(tm, ff), path_cost(tm, fwd))

    def test_exact_route_on_a_forced_corridor(self):
        # One row -> a unique route: the field must return it byte-identically.
        tm = synth(["bcccs"], base=(0, 0))
        self.assertEqual(find_path(tm, 4, 0), forward(tm, 4, 0))
        self.assertEqual(find_path(tm, 4, 0),
                         [(4, 0), (3, 0), (2, 0), (1, 0), (0, 0)])

    def test_start_on_base_and_unreachable_start(self):
        tm = synth(["bfs"], base=(0, 0))     # background seals the corridor
        self.assertEqual(find_path(tm, 0, 0), [(0, 0)])
        self.assertEqual(find_path(tm, 2, 0), [])   # fallback seam fires


class TestCacheReuse(unittest.TestCase):
    ROWS = ["bcccc", "ccccc", "ccccs"]

    def _counting(self):
        calls = []
        orig = pathfinder._build_flow_field

        def counted(tm, ignore_walls):
            calls.append(1)
            return orig(tm, ignore_walls)

        return calls, orig, counted

    def test_many_queries_build_the_field_once(self):
        tm = synth(self.ROWS, base=(0, 0))
        calls, orig, counted = self._counting()
        pathfinder._build_flow_field = counted
        try:
            for start in ((4, 2), (2, 1), (4, 0), (0, 2), (4, 2)):
                self.assertTrue(find_path(tm, *start))
        finally:
            pathfinder._build_flow_field = orig
        self.assertEqual(len(calls), 1)

    def test_two_maps_never_share_a_field(self):
        a = synth(["bcs"], base=(0, 0))
        b = synth(["bfs"], base=(0, 0))     # same dims, sealed corridor
        self.assertTrue(find_path(a, 2, 0))
        self.assertEqual(find_path(b, 2, 0), [])
        self.assertTrue(find_path(a, 2, 0))  # a's cache survived b's build


class TestInvalidation(unittest.TestCase):
    def test_zone_change_reroutes(self):
        tm = synth(["bcs"], base=(0, 0))
        self.assertEqual(len(find_path(tm, 2, 0)), 3)      # field cached
        tm.set_tile_state(tm.get(1, 0), TileState.BACKGROUND)
        self.assertEqual(find_path(tm, 2, 0), [])          # sealed -> rebuilt

    def test_content_key_change_reprices(self):
        tm = synth(["bccs", "cccc"], base=(0, 0))
        before = path_cost(tm, find_path(tm, 3, 0))
        tm.set_tile_content(tm.get(1, 0), None, "defence_building")  # 1 -> 2
        after = find_path(tm, 3, 0)
        self.assertEqual(path_cost(tm, after), path_cost(tm, forward(tm, 3, 0)))
        self.assertGreater(path_cost(tm, after), before)

    # The wallable pocket from test_structure: base (0,0), spawn row 2.
    WALL_MAP = ["bbbc", "bbbc", "sssc"]

    def _builder_stub(self):
        return types.SimpleNamespace(wall_hp=lambda: 50,
                                     set_wall_snapshot=lambda snap: None)

    def test_wall_raise_then_wall_death_reroute(self):
        tm = synth(self.WALL_MAP, base=(0, 0))
        self.assertTrue(find_path(tm, 0, 2))               # open -> cached
        tm.place_walls_for_builder(self._builder_stub())
        self.assertEqual(find_path(tm, 0, 2), [])          # enclosed
        # Mid-HP damage keeps the edge alive -> still enclosed (no stale
        # reopening AND no spurious pass-through).
        self.assertFalse(tm.damage_wall(0, 1, 0, 2, 49))
        self.assertEqual(find_path(tm, 0, 2), [])
        # The death transition reopens the step.
        self.assertTrue(tm.damage_wall(0, 1, 0, 2, 1))
        path = find_path(tm, 0, 2)
        self.assertTrue(path)
        self.assertEqual(path[-1], (0, 0))

    def test_remove_walls_for_builder_reopens(self):
        tm = synth(self.WALL_MAP, base=(0, 0))
        builder = self._builder_stub()
        tm.place_walls_for_builder(builder)
        self.assertEqual(find_path(tm, 0, 2), [])
        tm.remove_walls_for_builder(builder)
        self.assertTrue(find_path(tm, 0, 2))


if __name__ == "__main__":
    unittest.main()
