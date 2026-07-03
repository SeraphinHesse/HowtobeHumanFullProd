"""editor.selection — the pure tree-node -> slot resolver (no Qt).

Layout contract (user-confirmed): the tree stops at the deepest group whose
children are all leaf groups (building TYPE); the Details panel picks the
subcategory (tier, or the slot itself); the level bar picks among a tier's
slots. Runs against the real data/slots.json (read-only).
"""
import unittest
from pathlib import Path

from editor.selection import level_slots, resolve_slot, subcategories
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]


class TestResolver(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry(REPO / "data")

    def test_tiered_building_type(self):
        subs = subcategories(self.reg, "buildings", ("Defender",))
        self.assertEqual(subs, ("Stone Thrower", "Slinger", "Pistoleer"))
        levels = level_slots(self.reg, "buildings", ("Defender",), 0)
        self.assertEqual(levels, ("stone_thrower_t1_lvl1",
                                  "stone_thrower_t1_lvl2",
                                  "stone_thrower_t1_lvl3"))
        self.assertEqual(
            resolve_slot(self.reg, "buildings", ("Defender",), 1, 2),
            "slinger_t2_lvl3")

    def test_flat_building_single_slot(self):
        subs = subcategories(self.reg, "buildings", ("Blocker",))
        self.assertEqual(subs, ("blocker",))
        self.assertEqual(level_slots(self.reg, "buildings", ("Blocker",), 0),
                         ("blocker",))
        self.assertEqual(resolve_slot(self.reg, "buildings", ("Blocker",), 0, 0),
                         "blocker")

    def test_direct_slot_list_group(self):
        subs = subcategories(self.reg, "enemies", ("Walker",))
        self.assertEqual(subs, ("enemy", "enemy_t2", "enemy_t3", "enemy_t4"))
        self.assertEqual(resolve_slot(self.reg, "enemies", ("Walker",), 2, 0),
                         "enemy_t3")

    def test_tile_group_with_leaf_children(self):
        subs = subcategories(self.reg, "map", ("Tiles",))
        self.assertEqual(subs, ("Buildable", "Combat", "Spawning", "Background"))
        self.assertEqual(level_slots(self.reg, "map", ("Tiles",), 0),
                         ("tile_buildable", "tile_buildable_b"))
        self.assertEqual(resolve_slot(self.reg, "map", ("Tiles",), 3, 1),
                         "tile_ocean")

    def test_category_root_has_no_slot_context(self):
        self.assertEqual(subcategories(self.reg, "buildings", ()), ())
        self.assertIsNone(resolve_slot(self.reg, "buildings", (), 0, 0))

    def test_out_of_range_indices_resolve_to_none(self):
        self.assertEqual(level_slots(self.reg, "buildings", ("Defender",), 99), ())
        self.assertIsNone(resolve_slot(self.reg, "buildings", ("Defender",), 0, 99))
        self.assertIsNone(resolve_slot(self.reg, "buildings", ("Defender",), -1, 0))


if __name__ == "__main__":
    unittest.main()
