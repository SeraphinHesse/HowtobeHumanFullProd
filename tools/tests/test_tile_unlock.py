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


if __name__ == "__main__":
    unittest.main()
