"""Footprint clearance pathing (ER-2) — game/map/pathfinder.py + PathAgent.

A size-N unit anchored at (c, r) occupies the N×N block extending RIGHT and DOWN
from that min corner. It may only stand where the whole block is passable and no
wall runs through it, a step must clear the whole leading FACE, entering a block
costs the worst tile under the body, and it has REACHED a goal once its block
COVERS it (not when the anchor sits on it — a 2×2 standing beside the hole is on
the hole). Pinned here: a 2×2 refusing a one-tile gap a 1×1 threads, the N=1
identity (byte-identical to pre-ER-2), the D6 cache invariant (one Dijkstra per
topology change PER footprint, never one per enemy), wall-vs-block rules, the
safe no-path failure mode, the spawner's clearance filter, and a real-map sanity
check. Headless, synthetic grids, real balancing (mirrors test_flow_field).
"""
import copy
import random
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import GameObject, Movement, Transform
import game.map.pathfinder as pathfinder
from game.core.balance import load_balance
from game.enemies.components import PathAgent
from game.enemies.spawner import Spawner
from game.map import load_map_balance
from game.map.pathfinder import (
    _dijkstra,
    _face_blocked,
    _wall_blocks,
    block_covers,
    block_passable,
    block_tiles,
    block_weight,
    face_edges,
    find_path,
    find_path_ignoring_walls,
    find_path_to_nearest_building,
    find_path_to_nearest_defence,
    find_path_to_nearest_economic,
    internal_edges,
)
from game.map.tile_map import TileMap, WallEdge, _wall_key
from game.map.tiles import TileCondition, TileState

BALANCE = load_map_balance(REPO / "data")


def synth(terrain_rows, base=(1, 1)):
    """TileMap from raw legend-code rows (b/c/s/f/l/o) — see test_pathfinder.
    No rng -> every tile stays GRASS, which is what makes costs exactly
    assertable."""
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


def is_contiguous(path):
    return all(
        abs(a[0] - b[0]) + abs(a[1] - b[1]) == 1
        for a, b in zip(path, path[1:])
    )


def path_cost(tm, path, footprint=1):
    """Sum of the cost of every BLOCK entered (the start block contributes 0)."""
    return sum(block_weight(tm, c, r, footprint) for c, r in path[1:])


# -- 1. the headline: a 2x2 refuses a gap a 1x1 takes -----------------------

class TestGapClearance(unittest.TestCase):
    # A background wall down col 2 with a ONE-tile hole at (2, 2).
    ONE_GAP = [
        "ccfcc",
        "ccfcc",
        "ccccc",
        "ccfcc",
        "ccfcc",
    ]
    # The same wall with a TWO-tile hole at (2, 2) + (2, 3).
    TWO_GAP = [
        "ccfcc",
        "ccfcc",
        "ccccc",
        "ccccc",
        "ccfcc",
    ]

    def test_walker_threads_the_one_tile_hole_a_2x2_cannot(self):
        tm = synth(self.ONE_GAP, base=(0, 2))
        walker = find_path(tm, 4, 2)
        self.assertTrue(walker, "a 1x1 must thread the one-tile hole")
        self.assertIn((2, 2), walker)               # it goes through the gap
        self.assertEqual(walker[-1], (0, 2))
        # No 2x2 anchor can ever cover col 2: the hole is one tile tall, so the
        # body would always straddle an impassable tile. Fully sealed.
        self.assertEqual(find_path(tm, 4, 2, footprint=2), [])

    def test_2x2_routes_through_a_two_tile_gap_and_never_straddles_the_wall(self):
        tm = synth(self.TWO_GAP, base=(0, 2))
        path = find_path(tm, 3, 0, footprint=2)
        self.assertTrue(path, "a two-tile gap must admit the 2x2")
        self.assertTrue(is_contiguous(path))
        # Every anchor it stands on is a legal 2x2 placement.
        for c, r in path:
            self.assertTrue(block_passable(tm, c, r, 2, False),
                            f"anchor {(c, r)} straddles the wall")
        self.assertTrue(block_covers(path[-1][0], path[-1][1], 2, 0, 2))


# -- 2. footprint=1 is byte-identical to pre-ER-2 ---------------------------

class TestFootprintOneIdentity(unittest.TestCase):
    # Mixed weights (mountain +2, pond +9, forest +1) + a live wall edge + a
    # background pillar — test_flow_field's forward-equivalence fixture.
    ROWS = [
        "ooooooo",
        "obcccco",
        "occocco",
        "occccso",
        "oscccco",
        "ooooooo",
    ]
    STARTS = ((5, 3), (1, 4), (5, 1), (2, 4), (4, 4), (1, 1))

    def _mixed_map(self):
        tm = synth(self.ROWS)
        tm.get(2, 1).condition = TileCondition.MOUNTAIN
        tm.get(3, 3).condition = TileCondition.POND
        tm.get(4, 2).condition = TileCondition.FOREST
        tm.get(2, 4).condition = TileCondition.MOUNTAIN
        tm.wall_edges[_wall_key(2, 1, 2, 2)] = WallEdge(
            2, 1, 2, 2, 50, 50, object())
        return tm

    def test_default_equals_explicit_footprint_1(self):
        tm = self._mixed_map()
        for start in self.STARTS:
            with self.subTest(start=start):
                self.assertEqual(find_path(tm, *start),
                                 find_path(tm, *start, footprint=1))
                self.assertEqual(
                    find_path_ignoring_walls(tm, *start),
                    find_path_ignoring_walls(tm, *start, footprint=1))
                for fn in (find_path_to_nearest_economic,
                           find_path_to_nearest_defence,
                           find_path_to_nearest_building):
                    self.assertEqual(fn(tm, *start), fn(tm, *start, footprint=1))

    def test_footprint_1_matches_a_direct_forward_dijkstra(self):
        tm = self._mixed_map()
        goal = (tm.base_col, tm.base_row)
        for start in self.STARTS:
            with self.subTest(start=start):
                fwd = _dijkstra(tm, *start, {goal}, ignore_walls=False,
                                footprint=1)
                ff = find_path(tm, *start, footprint=1)
                self.assertEqual(bool(ff), bool(fwd))
                if not ff:
                    continue
                self.assertEqual(ff[0], start)
                self.assertEqual(ff[-1], goal)     # N=1 ANCHORS on the base
                self.assertTrue(is_contiguous(ff))
                self.assertEqual(path_cost(tm, ff), path_cost(tm, fwd))

    def test_the_block_predicates_collapse_to_the_tile_at_n_1(self):
        tm = self._mixed_map()
        self.assertEqual(block_tiles(3, 4, 1), [(3, 4)])
        self.assertEqual(internal_edges(3, 4, 1), [])
        self.assertEqual(face_edges(3, 4, 4, 4, 1), [(3, 4, 4, 4)])
        for c, r in ((1, 1), (3, 3), (0, 0), (2, 2)):
            tile = tm.get(c, r)
            expect = tile is not None and tm.weight(tile) < tm.impassable_weight
            self.assertEqual(block_passable(tm, c, r, 1, False), expect)
            if expect:
                self.assertEqual(block_weight(tm, c, r, 1), tm.weight(tile))


# -- 3. D6: one flow-field build per _path_version bump PER footprint -------

class TestFieldCachePerFootprint(unittest.TestCase):
    ROWS = ["bcccc", "ccccc", "ccccs"]

    def _counting(self):
        calls = []
        orig = pathfinder._build_flow_field

        def counted(tm, ignore_walls, footprint=1):
            calls.append((ignore_walls, footprint))
            return orig(tm, ignore_walls, footprint)

        return calls, orig, counted

    def test_one_build_per_footprint_never_one_per_query(self):
        tm = synth(self.ROWS, base=(0, 0))
        calls, orig, counted = self._counting()
        pathfinder._build_flow_field = counted
        try:
            for start in ((4, 2), (2, 1), (4, 0), (0, 2), (4, 2)):
                find_path(tm, *start)                    # footprint 1
                find_path(tm, *start, footprint=2)       # footprint 2
            self.assertEqual(calls, [(False, 1), (False, 2)])

            # A topology change bumps _path_version -> exactly one rebuild each.
            tm.set_tile_state(tm.get(3, 1), TileState.BACKGROUND)
            for start in ((4, 2), (2, 1), (4, 2)):
                find_path(tm, *start)
                find_path(tm, *start, footprint=2)
            self.assertEqual(calls, [(False, 1), (False, 2),
                                     (False, 1), (False, 2)])
        finally:
            pathfinder._build_flow_field = orig

    def test_cache_is_keyed_on_ignore_walls_and_footprint(self):
        tm = synth(self.ROWS, base=(0, 0))
        find_path(tm, 4, 2)
        find_path(tm, 4, 2, footprint=2)
        find_path_ignoring_walls(tm, 4, 2, footprint=2)
        fields = tm._flow_cache[1]
        self.assertEqual(set(fields), {(False, 1), (False, 2), (True, 2)})


# -- 4. walls vs a block: internal edges, faces, ignore_walls ---------------

class TestWallsAgainstABlock(unittest.TestCase):
    OPEN = [
        "bcccc",
        "ccccc",
        "ccccc",
        "ccccs",
    ]

    def _map_with_wall(self, c1, r1, c2, r2):
        tm = synth(self.OPEN, base=(0, 0))
        tm.wall_edges[_wall_key(c1, r1, c2, r2)] = WallEdge(
            c1, r1, c2, r2, 50, 50, object())
        return tm

    def test_wall_inside_the_body_makes_the_anchor_unusable(self):
        # (1,1)-(2,1) is an INTERNAL edge of the 2x2 anchored at (1,1).
        tm = self._map_with_wall(1, 1, 2, 1)
        self.assertIn((1, 1, 2, 1), internal_edges(1, 1, 2))
        # Both tiles stay individually passable...
        for c, r in ((1, 1), (2, 1)):
            self.assertTrue(block_passable(tm, c, r, 1, False))
        # ...but the 2x2 may not straddle the wall.
        self.assertFalse(block_passable(tm, 1, 1, 2, False))
        # ignore_walls sees straight through it.
        self.assertTrue(block_passable(tm, 1, 1, 2, True))

    def test_one_wall_on_a_two_edge_face_blocks_the_2x2_step(self):
        # Stepping (1,1) -> (2,1) at N=2 sweeps the face {(2,1)-(3,1),
        # (2,2)-(3,2)}. A wall on only the FIRST still blocks the body.
        tm = self._map_with_wall(2, 1, 3, 1)
        self.assertEqual(face_edges(1, 1, 2, 1, 2),
                         [(2, 1, 3, 1), (2, 2, 3, 2)])
        self.assertTrue(_face_blocked(tm, 1, 1, 2, 1, footprint=2))
        # The other edge of that face is clear, so a 1x1 crossing it is fine.
        self.assertFalse(_wall_blocks(tm, 2, 2, 3, 2))
        self.assertFalse(_face_blocked(tm, 2, 2, 3, 2, footprint=1))
        # ...and ignoring walls clears the face for the 2x2 too.
        self.assertTrue(find_path_ignoring_walls(tm, 3, 2, footprint=2))

    def test_the_2x2_routes_around_a_face_wall(self):
        tm = self._map_with_wall(2, 1, 3, 1)
        path = find_path(tm, 3, 2, footprint=2)
        self.assertTrue(path)
        for a, b in zip(path, path[1:]):
            self.assertFalse(_face_blocked(tm, a[0], a[1], b[0], b[1], 2),
                             f"step {a}->{b} crosses a live wall")


# -- 5. the safe failure mode: no path -> stand still, never a base hit -----

class TestUnpathableStandsStill(unittest.TestCase):
    def test_no_legal_2x2_path_yields_empty_from_both_variants(self):
        tm = synth(TestGapClearance.ONE_GAP, base=(0, 2))
        # BACKGROUND is a WEIGHT, not a wall — even ignoring walls cannot pass.
        self.assertEqual(find_path(tm, 4, 2, footprint=2), [])
        self.assertEqual(find_path_ignoring_walls(tm, 4, 2, footprint=2), [])

    def test_empty_waypoints_never_fire_a_phantom_base_hit(self):
        tm = synth(TestGapClearance.ONE_GAP, base=(0, 2))
        path = find_path(tm, 4, 2, footprint=2)
        unit = GameObject(
            name="formation",
            tags=("enemy",),
            transform=Transform(wx=4.0, wy=2.0),
            components=[PathAgent(footprint=2), Movement(speed=1.0)],
        )
        pa = unit.get_component(PathAgent)
        pa._tilemap = tm
        mv = unit.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]   # []
        for _ in range(10):
            unit.update(0.1)
        self.assertEqual(mv.waypoints, [])
        self.assertFalse(mv.arrived)        # Movement early-returns on []
        self.assertFalse(pa.reached_base)   # so no phantom base breach
        self.assertFalse(pa.blocked)


# -- 6. the block-cover goal rule -------------------------------------------

class TestBlockCoversTheGoal(unittest.TestCase):
    OPEN_5x5 = ["ccccc"] * 5
    OPEN_7x7 = ["ccccccc"] * 7

    def _seeds(self, tm, footprint):
        return [(tm.base_col - i, tm.base_row - j)
                for i in range(footprint) for j in range(footprint)]

    def test_2x2_reaches_a_base_it_can_never_anchor_on(self):
        # Base in the far corner: the 2x2 block anchored AT the base runs off
        # the map, so under an "anchor == goal" rule this unit could never
        # arrive. It must instead stop where its BODY covers the hole.
        tm = synth(self.OPEN_5x5, base=(4, 4))
        self.assertFalse(block_passable(tm, 4, 4, 2, False))  # no anchor there

        path = find_path(tm, 0, 0, footprint=2)
        self.assertTrue(path, "a 2x2 must still be able to reach the base")
        last = path[-1]
        self.assertNotEqual(last, (4, 4))                     # not anchored on it
        self.assertTrue(block_covers(last[0], last[1], 2, 4, 4))
        self.assertTrue(block_passable(tm, last[0], last[1], 2, False))

        # At footprint 1 the last anchor IS the base tile, exactly as before.
        self.assertEqual(find_path(tm, 0, 0)[-1], (4, 4))

    def test_every_covering_anchor_is_a_terminal_one_anchor_path(self):
        # INTERIOR base: all four covering anchors are legal placements, so all
        # four are seeds. Each is ALREADY on the hole -> a path of just itself.
        # (A corner base hides this: only one seed is legal there, so a seed
        # that wrongly back-points at another seed cannot show up.)
        tm = synth(self.OPEN_7x7, base=(3, 3))
        for anchor in self._seeds(tm, 2):
            with self.subTest(anchor=anchor):
                self.assertTrue(block_covers(*anchor, 2, 3, 3))
                self.assertEqual(find_path(tm, *anchor, footprint=2), [anchor])
        self.assertEqual(find_path(tm, 3, 3), [(3, 3)])       # N=1 identity

    def test_no_seed_ever_gets_a_back_pointer(self):
        # White-box: the seeds are 4-adjacent to one another for N>1, so the
        # first one popped must NOT be allowed to relax its siblings. If it is,
        # their `dist` still settles to 0 but the bogus `next_step` survives and
        # _field_path walks a unit that already covers the base onward to the
        # lex-min covering anchor.
        tm = synth(self.OPEN_7x7, base=(3, 3))
        dist, next_step = pathfinder._build_flow_field(tm, False, 2)
        for seed in self._seeds(tm, 2):
            with self.subTest(seed=seed):
                self.assertEqual(dist[seed], 0)
                self.assertNotIn(seed, next_step)

    def test_a_2x2_on_the_hole_breaches_even_with_a_tower_beside_it(self):
        # END-TO-END. Base (2,2); a tower at (1,2) sits inside the block of the
        # lex-min covering anchor (1,1). A 2x2 walking in from (4,2) reaches
        # (2,2) — its body COVERS the hole — and must breach there. If the path
        # runs on past the hole toward (1,1), the tower lands in the destination
        # block, PathAgent blocks on it and reached_base never fires: one
        # well-placed tower would neuter every 2x2 for the whole round.
        tm = synth(self.OPEN_5x5, base=(2, 2))
        tower = types.SimpleNamespace(alive=True)
        tm.set_tile_content(tm.get(1, 2), tower, "defence_building")

        path = find_path(tm, 4, 2, footprint=2)
        self.assertTrue(path)
        self.assertTrue(block_covers(path[-1][0], path[-1][1], 2, 2, 2))

        unit = GameObject(
            name="formation",
            tags=("enemy",),
            transform=Transform(wx=4.0, wy=2.0),
            components=[PathAgent(footprint=2), Movement(speed=2.0)],
        )
        pa = unit.get_component(PathAgent)
        pa._tilemap = tm
        pa._real_speed = 2.0
        mv = unit.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        # A real frame step: the per-tick move must stay under Movement's 0.06
        # arrival_threshold or the unit overshoots every waypoint and oscillates.
        for _ in range(300):
            unit.update(1.0 / 60.0)
            if pa.reached_base:
                break
        self.assertIsNone(pa._target, "must not stop to attack the tower")
        self.assertFalse(pa.blocked)
        self.assertTrue(pa.reached_base, "a 2x2 covering the hole must breach")


# -- 7. PathAgent scans the whole destination block for a blocker -----------

class TestPathAgentBlockScan(unittest.TestCase):
    OPEN = ["bccc", "cccc", "cccc"]

    def _agent(self, tm, footprint, waypoints):
        unit = GameObject(
            name="unit",
            tags=("enemy",),
            transform=Transform(wx=float(waypoints[0][0]),
                                wy=float(waypoints[0][1])),
            components=[PathAgent(footprint=footprint), Movement(speed=0.0)],
        )
        pa = unit.get_component(PathAgent)
        pa._tilemap = tm
        pa._real_speed = 1.0
        unit.get_component(Movement).waypoints = waypoints
        return unit, pa

    def test_building_in_the_blocks_second_column_blocks_a_2x2_only(self):
        tm = synth(self.OPEN, base=(0, 0))
        blocker = types.SimpleNamespace(alive=True)
        # (2,1) is the SECOND column of the 2x2 whose anchor is the waypoint
        # (1,1) — off the 1x1's single-tile scan entirely.
        tm.set_tile_content(tm.get(2, 1), blocker, "defence_building")

        big, pa2 = self._agent(tm, 2, [[1.0, 1.0]])
        big.update(0.1)
        self.assertTrue(pa2.blocked)
        self.assertIs(pa2._target, blocker)

        small, pa1 = self._agent(tm, 1, [[1.0, 1.0]])
        small.update(0.1)
        self.assertFalse(pa1.blocked)
        self.assertIsNone(pa1._target)

    def test_the_base_is_never_a_blocker_for_any_tile_of_the_block(self):
        tm = synth(self.OPEN, base=(0, 0))
        base = types.SimpleNamespace(alive=True)
        tm.get(0, 0).occupant = base
        # The 2x2 anchored at (0,0) COVERS the base tile — it must not stop to
        # attack the hole itself.
        unit, pa = self._agent(tm, 2, [[0.0, 0.0]])
        unit.update(0.1)
        self.assertFalse(pa.blocked)
        self.assertIsNone(pa._target)


# -- 8. spawner clearance filter --------------------------------------------

class TestSpawnerClearance(unittest.TestCase):
    THIN_BAND = ["bccc", "cccc", "ssss"]            # spawn band 1 tile thick
    THICK_BAND = ["bccc", "cccc", "ssss", "ssss"]   # 2 tiles thick

    def _balance(self, siege_footprint=1):
        bal = copy.deepcopy(load_balance(REPO / "data", "enemies"))
        bal["EnemyTypes"]["SiegeCannon"]["footprint"] = siege_footprint
        return bal

    def _spawner(self, rows, bal, seed=7):
        tm = synth(rows, base=(0, 0))
        sp = Spawner()
        sp._balance = bal
        sp._rng = random.Random(seed)
        return sp, tm.spawning_tiles()

    def test_footprint_1_is_the_unfiltered_single_draw(self):
        sp, tiles = self._spawner(self.THICK_BAND, self._balance(1))
        mirror = random.Random(7)
        picked = sp._pick_spawn_tile(tiles, "siege")
        self.assertIs(picked, mirror.choice(tiles))     # same tile...
        self.assertEqual(sp._rng.random(), mirror.random())  # ...same stream
        self.assertEqual(sp._clear_cache, {})           # filter never ran

    def test_footprint_2_only_picks_fully_clear_anchors(self):
        sp, tiles = self._spawner(self.THICK_BAND, self._balance(2))
        zone = {(t.col, t.row) for t in tiles}
        for _ in range(30):
            t = sp._pick_spawn_tile(tiles, "siege")
            for b in block_tiles(t.col, t.row, 2):
                self.assertIn(b, zone, "spawned a 2x2 outside the spawn zone")
        # Only the top spawn row can host a 2x2 (the bottom row's block would
        # run off the map). ``spawning_tiles()`` is set-derived, so compare the
        # SET — the filter preserves whatever order it was handed.
        self.assertEqual({(t.col, t.row) for t in sp._clear_cache[2]},
                         {(0, 2), (1, 2), (2, 2)})

    def test_thin_band_falls_back_and_never_drops_the_enemy(self):
        sp, tiles = self._spawner(self.THIN_BAND, self._balance(2))
        self.assertEqual(sp._clear_spawn_tiles(tiles, 2), [])  # nothing qualifies
        for _ in range(10):
            t = sp._pick_spawn_tile(tiles, "siege")
            self.assertIn(t, tiles)          # unfiltered fallback, no crash

    def test_the_clearance_filter_consumes_no_rng(self):
        sp, tiles = self._spawner(self.THICK_BAND, self._balance(2))
        mirror = random.Random(7)
        sp._clear_spawn_tiles(tiles, 2)      # the filter alone
        self.assertEqual(sp._rng.random(), mirror.random())

    def test_begin_round_stays_deterministic_under_a_seeded_rng(self):
        bal = self._balance(1)
        tm = synth(self.THICK_BAND, base=(0, 0))
        queues = []
        for _ in range(2):
            sp = Spawner()
            sp.begin_round(3, tm, bal, rng=random.Random(11))
            queues.append([(t.col, t.row, e) for t, e, _ in sp._queue])
        self.assertEqual(queues[0], queues[1])
        self.assertTrue(queues[0])

    def test_begin_round_resets_the_clear_cache(self):
        bal = self._balance(2)
        tm = synth(self.THICK_BAND, base=(0, 0))
        sp = Spawner()
        sp.begin_round(3, tm, bal, rng=random.Random(11))
        sp._clear_cache[2] = ["stale"]
        sp.begin_round(4, tm, bal, rng=random.Random(11))
        self.assertNotIn("stale", sp._clear_cache.get(2, []))


# -- 9. real-map sanity: the shipped map must admit a 2x2 -------------------

class TestShippedMapAdmitsA2x2(unittest.TestCase):
    def test_a_footprint_2_unit_reaches_the_base_from_a_real_spawn_tile(self):
        doc = tilemap.load_active_map(REPO / "data")
        tm = TileMap(doc, BALANCE)
        spawn = tm.spawning_tiles()
        self.assertTrue(spawn, "the shipped map has no spawn tiles")

        clear = [t for t in spawn if block_passable(tm, t.col, t.row, 2, False)]
        self.assertTrue(
            clear,
            "no spawn tile on the shipped map can host a 2x2 body — ER-4's "
            "Formation could never spawn")

        reached = [t for t in clear if find_path(tm, t.col, t.row, footprint=2)]
        self.assertTrue(
            reached,
            "no 2x2-clear spawn tile on the shipped map can reach the base — "
            "the map cannot support 2x2 units at all")

        path = find_path(tm, reached[0].col, reached[0].row, footprint=2)
        self.assertTrue(is_contiguous(path))
        self.assertTrue(block_covers(path[-1][0], path[-1][1], 2,
                                     tm.base_col, tm.base_row))
        for c, r in path:
            self.assertTrue(block_passable(tm, c, r, 2, False))


if __name__ == "__main__":
    unittest.main()
