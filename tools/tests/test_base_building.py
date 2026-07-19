"""Phase 9D: BaseBuilding — the untiered Hole (game/buildings/base_building.py).

BASE_HP stays 10 (core.json TheHole.base_hp — the deliberate NOT-×10 exception),
untiered, not upgradeable, and excluded from the round-end revive sweep. Attaches
as the occupant of the pre-seeded base tile.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.core.balance import load_balance
from game.map.tile_map import BASE_CONTENT_KEY, TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
CORE = load_balance(FIXTURE_DATA, "core")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


class TestBaseBuilding(unittest.TestCase):
    def test_untiered_fixed_hp(self):
        b = BaseBuilding(1, 1, CORE)
        self.assertEqual(b.max_hp(), 10)
        self.assertEqual(b.get_component(Health).max_hp, 10)
        self.assertEqual(b.upgrade_cost(), 0)
        self.assertTrue(b.at_tier_max())
        self.assertFalse(b.has_next_tier())
        self.assertEqual(b.level, 1)
        self.assertEqual(b.building_type, "base")
        self.assertTrue(b.alive)

    def test_never_revives(self):
        b = BaseBuilding(1, 1, CORE)
        b.get_component(Health).damage(100)
        self.assertFalse(b.alive)
        b.rebuild()                 # sweep would revive a normal building
        self.assertFalse(b.alive)   # base stays dead (game over is the loss)

    def test_attaches_to_base_tile(self):
        tm = synth(["bbb", "bbb", "bbb"], base=(1, 1))
        scene, occ = Scene(), TileOccupancy()
        base = BaseBuilding(tm.base_col, tm.base_row, CORE)
        attach_base(tm, base, scene, occ)
        tile = tm.get(1, 1)
        self.assertIs(tile.occupant, base)
        self.assertEqual(tile.content_key, BASE_CONTENT_KEY)  # pre-seeded
        self.assertEqual(occ.get((1, 1)), base)


if __name__ == "__main__":
    unittest.main()
