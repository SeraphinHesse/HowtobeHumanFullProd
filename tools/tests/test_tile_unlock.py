"""Phase 9C: 2×2 chunk unlock + spawn-zone recede (game/map/tile_map.py).

Ports and pins the prototype's src/map/tile_map.py:298-438 on the shipped
starter map (data/maps/first_light.json, prototype-exact layout). Unlock cost =
BASE + (col_sec + row_sec) * MOD with the live map.json values (5 / 2);
adjacency requires a chunk COMBAT tile edge-adjacent to an unlocked tile; a
successful unlock recedes the spawn band exactly one 2×2 section outward.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from game.map import load_map_balance
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAP = REPO / "data" / "maps" / "first_light.json"
MAP_SCHEMA = REPO / "data" / "schemas" / "map_file.schema.json"
BALANCE = load_map_balance(REPO / "data")


def make_tilemap():
    doc = tilemap.load_map(MAP, MAP_SCHEMA)
    return TileMap(doc, BALANCE)


def states(tm, coords):
    return [tm.get(c, r).state for c, r in coords]


class TestSeeding(unittest.TestCase):
    def test_zones_seed_from_terrain_codes(self):
        tm = make_tilemap()
        self.assertEqual(tm.get(1, 1).state, TileState.BUILT)      # base
        self.assertEqual(tm.get(2, 1).state, TileState.BUILDABLE)  # 'b'
        self.assertEqual(tm.get(3, 1).state, TileState.COMBAT)     # 'c'
        self.assertEqual(tm.get(10, 1).state, TileState.SPAWNING)  # 's'
        self.assertEqual(tm.get(0, 1).state, TileState.BACKGROUND)  # 'o'
        self.assertEqual(tm.get(1, 1).content_key, "base_building")


class TestUnlockCost(unittest.TestCase):
    def test_cost_scales_with_section_distance(self):
        tm = make_tilemap()
        # section (col_sec, row_sec) anchored at the base (1,1): 5 + (sc+sr)*2
        cases = {
            (1, 1): 5,   # section (0,0)
            (3, 1): 7,   # section (1,0)
            (1, 3): 7,   # section (0,1)
            (3, 3): 9,   # section (1,1)
            (7, 7): 5 + (3 + 3) * 2,  # section (3,3) -> 17
        }
        for (c, r), expected in cases.items():
            with self.subTest(tile=(c, r)):
                self.assertEqual(tm.unlock_cost(tm.get(c, r)), expected)


class TestAdjacency(unittest.TestCase):
    def test_adjacent_chunk_unlockable(self):
        tm = make_tilemap()
        # section (1,0) COMBAT tiles touch the buildable pocket at (2,1).
        self.assertTrue(tm.can_unlock(tm.get(3, 1)))

    def test_far_chunk_locked(self):
        tm = make_tilemap()
        # section (3,3): combat tiles surrounded by combat, no unlocked neighbour.
        self.assertFalse(tm.can_unlock(tm.get(7, 7)))

    def test_already_buildable_chunk_does_not_unlock(self):
        tm = make_tilemap()
        # section (0,0) is the buildable pocket — no COMBAT tiles to convert.
        self.assertFalse(tm.do_unlock(tm.get(2, 2)))


class TestUnlockAndRecede(unittest.TestCase):
    def test_unlock_section_1_0_and_recede(self):
        tm = make_tilemap()
        ok = tm.do_unlock(tm.get(3, 1))
        self.assertTrue(ok)

        # 1. The chunk's four COMBAT tiles become BUILDABLE.
        unlocked = [(3, 1), (4, 1), (3, 2), (4, 2)]
        self.assertTrue(
            all(s == TileState.BUILDABLE for s in states(tm, unlocked)),
            states(tm, unlocked))

        # 2. Nearest SPAWNING 2×2 (cols10-11, rows1-2) recedes to COMBAT.
        receded_spawn = [(10, 1), (11, 1), (10, 2), (11, 2)]
        self.assertTrue(
            all(s == TileState.COMBAT for s in states(tm, receded_spawn)),
            states(tm, receded_spawn))

        # 3. Nearest in-playfield BACKGROUND 2×2 behind it (cols14-15, rows1-2)
        #    becomes SPAWNING.
        new_spawn = [(14, 1), (15, 1), (14, 2), (15, 2)]
        self.assertTrue(
            all(s == TileState.SPAWNING for s in states(tm, new_spawn)),
            states(tm, new_spawn))

    def test_recede_conserves_nothing_outside_the_three_blocks(self):
        # A tile far from the action is untouched by the recede.
        tm = make_tilemap()
        before = tm.get(1, 12).state  # deep spawn band, unrelated
        tm.do_unlock(tm.get(3, 1))
        self.assertEqual(tm.get(1, 12).state, before)


class TestStateIndexConsistency(unittest.TestCase):
    """The `_by_state` index (perf: O(result) state queries — it removed the
    per-frame full-map HUD scans that dropped large maps to ~2 fps) must always
    agree with a brute-force scan of `all_tiles()`, through every state change."""

    def _assert_consistent(self, tm):
        for state in TileState:
            indexed = {(t.col, t.row) for t in tm._by_state[state]}
            scanned = {(t.col, t.row) for t in tm.all_tiles()
                       if t.state == state}
            self.assertEqual(indexed, scanned, f"index desync for {state.name}")

    def test_query_methods_match_scan_at_seed(self):
        tm = make_tilemap()
        self._assert_consistent(tm)
        # the three queries return exactly the indexed sets
        self.assertEqual({(t.col, t.row) for t in tm.built_tiles()},
                         {(t.col, t.row) for t in tm.all_tiles()
                          if t.state == TileState.BUILT})
        self.assertEqual({(t.col, t.row) for t in tm.spawning_tiles()},
                         {(t.col, t.row) for t in tm.all_tiles()
                          if t.state == TileState.SPAWNING})

    def test_index_survives_unlock_and_recede(self):
        tm = make_tilemap()
        tm.do_unlock(tm.get(3, 1))  # converts + recedes across all three states
        self._assert_consistent(tm)

    def test_set_tile_state_moves_between_buckets(self):
        tm = make_tilemap()
        t = tm.get(2, 1)  # BUILDABLE at seed
        self.assertIn(t, tm._by_state[TileState.BUILDABLE])
        tm.set_tile_state(t, TileState.BUILT)
        self.assertIn(t, tm._by_state[TileState.BUILT])
        self.assertNotIn(t, tm._by_state[TileState.BUILDABLE])
        self.assertEqual(t.state, TileState.BUILT)
        # a no-op state write leaves the index untouched
        tm.set_tile_state(t, TileState.BUILT)
        self._assert_consistent(tm)


class TestFind2x2WindowedMatchesFullScan(unittest.TestCase):
    """`_find_2x2` uses an expanding-window search (perf: O(local), not a full
    ~1M-anchor scan per unlock on a large map). It must return the SAME block a
    brute-force whole-map scan would — same nearest-by-squared-distance pick,
    same first-row-major tie-break, same `min_ring` handling."""

    @staticmethod
    def _build_big(cols, rows, base=(1, 1)):
        # A large synth map (mostly background 'o' so predicates find sparse
        # matches far from the reference — the case the window must expand for),
        # exercised without any real art (TileMap reads dims/base/terrain only).
        terrain = [["o"] * cols for _ in range(rows)]
        doc = tilemap.TileMapDoc(
            map_id="synth", display_name="Synth", cols=cols, rows=rows,
            legend={}, terrain=terrain,
            base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
        return TileMap(doc, BALANCE)

    @staticmethod
    def _full_scan(tm, predicate, ref_col, ref_row, min_ring=None):
        """The pre-optimisation whole-map scan, inlined here as the oracle."""
        best, best_d = None, float("inf")
        for r in range(tm.rows - 1):
            for c in range(tm.cols - 1):
                block = [tm.get(c, r), tm.get(c + 1, r),
                         tm.get(c, r + 1), tm.get(c + 1, r + 1)]
                if any(t is None or not predicate(t) for t in block):
                    continue
                cc, rr = c + 0.5, r + 0.5
                if min_ring is not None and max(cc, rr) < min_ring:
                    continue
                d = (cc - ref_col) ** 2 + (rr - ref_row) ** 2
                if d < best_d:
                    best_d, best = d, block
        return best

    @staticmethod
    def _coords(block):
        return None if block is None else [(t.col, t.row) for t in block]

    def _paint_block(self, tm, anchor_c, anchor_r, state):
        for dc in range(2):
            for dr in range(2):
                tm.set_tile_state(tm.get(anchor_c + dc, anchor_r + dr), state)

    def test_matches_full_scan_across_refs_and_min_ring(self):
        tm = self._build_big(40, 40)
        # A few sparse SPAWNING 2×2 blocks scattered across the map, including
        # near-far and equal-distance candidates around a couple of references.
        for ac, ar in [(4, 4), (30, 6), (6, 30), (34, 34), (18, 18), (20, 18)]:
            self._paint_block(tm, ac, ar, TileState.SPAWNING)
        pred = lambda t: t.state == TileState.SPAWNING
        cases = [
            (5, 5, None), (19, 18, None), (33, 33, None), (19, 5, None),
            (2, 2, None), (19, 18, 10), (5, 5, 25), (18, 19, 20),
        ]
        for ref_c, ref_r, ring in cases:
            with self.subTest(ref=(ref_c, ref_r), min_ring=ring):
                got = tm._find_2x2(pred, ref_c, ref_r, min_ring=ring)
                want = self._full_scan(tm, pred, ref_c, ref_r, min_ring=ring)
                self.assertEqual(self._coords(got), self._coords(want))

    def test_matches_full_scan_when_no_block_qualifies(self):
        tm = self._build_big(40, 40)  # no SPAWNING blocks painted
        pred = lambda t: t.state == TileState.SPAWNING
        self.assertIsNone(tm._find_2x2(pred, 20, 20))

    def test_equal_distance_picks_row_major_first(self):
        # Two qualifying blocks equidistant from the reference: the full scan
        # (and so the window search) must pick the row-major-earlier one.
        tm = self._build_big(40, 40)
        # Anchors 8 and 23 on row 20 have centres 8.5 / 23.5 — both exactly 7.5
        # from ref col 16 (8 + 23 = 31 = 2*16 - 1), so a true distance tie.
        self._paint_block(tm, 8, 20, TileState.SPAWNING)   # earlier in row-major
        self._paint_block(tm, 23, 20, TileState.SPAWNING)  # same row, later col
        pred = lambda t: t.state == TileState.SPAWNING
        got = tm._find_2x2(pred, 16, 20)
        want = self._full_scan(tm, pred, 16, 20)
        self.assertEqual(self._coords(got), self._coords(want))
        self.assertEqual(got[0].col, 8)  # the row-major-earlier block wins


if __name__ == "__main__":
    unittest.main()
