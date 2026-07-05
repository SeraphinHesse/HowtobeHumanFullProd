"""editor.selection — the pure tree-node -> slot resolver (no Qt).

Layout contract (user-confirmed): the tree stops at the deepest group whose
children are all leaf groups (building TYPE); the Details panel picks the
subcategory (tier, or the slot itself); the level bar picks among a tier's
slots. Runs against the real data/slots.json (read-only).
"""
import unittest
from pathlib import Path

from editor.selection import (
    level_slots,
    resolve_slot,
    subcategories,
    variant_target,
)
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

    def test_walker_era_subgroups_with_variants(self):
        # Walker is a leaf-children group (like Tiles): era subgroups, each
        # holding its sprite variants. Subcategories are the eras; the level
        # index selects a variant within an era (random-per-spawn in game).
        subs = subcategories(self.reg, "enemies", ("Walker",))
        self.assertEqual(subs, ("Era 1", "Era 2", "Era 3", "Era 4"))
        self.assertEqual(level_slots(self.reg, "enemies", ("Walker",), 0),
                         ("enemy_stage_1_v1", "enemy_stage_1_v2"))
        self.assertEqual(resolve_slot(self.reg, "enemies", ("Walker",), 0, 1),
                         "enemy_stage_1_v2")
        self.assertEqual(resolve_slot(self.reg, "enemies", ("Walker",), 3, 0),
                         "enemy_stage_4_v1")

    def test_tile_group_with_leaf_children(self):
        subs = subcategories(self.reg, "map", ("Tiles",))
        self.assertEqual(subs, ("Buildable", "Combat", "Spawning", "Background"))
        self.assertEqual(level_slots(self.reg, "map", ("Tiles",), 0),
                         ("tile_buildable", "tile_buildable_b"))
        self.assertEqual(resolve_slot(self.reg, "map", ("Tiles",), 3, 1),
                         "tile_ocean")

    def test_variant_target_names_the_era_child(self):
        # an enemy era subgroup is a valid "+ variant" target: its child label
        self.assertEqual(
            variant_target(self.reg, "enemies", ("Walker",), 1), "Era 2")
        self.assertEqual(
            variant_target(self.reg, "enemies", ("Siege Cannon",), 3), "Era 4")

    def test_variant_target_none_for_flat_and_stale(self):
        # a flat single-slot group (no children) has nothing to extend
        self.assertIsNone(variant_target(self.reg, "buildings", ("Blocker",), 0))
        # out-of-range subcategory index
        self.assertIsNone(variant_target(self.reg, "enemies", ("Walker",), 9))
        # a category root the tree recursed through
        self.assertIsNone(variant_target(self.reg, "enemies", (), 0))

    def test_category_root_has_no_slot_context(self):
        self.assertEqual(subcategories(self.reg, "buildings", ()), ())
        self.assertIsNone(resolve_slot(self.reg, "buildings", (), 0, 0))

    def test_out_of_range_indices_resolve_to_none(self):
        self.assertEqual(level_slots(self.reg, "buildings", ("Defender",), 99), ())
        self.assertIsNone(resolve_slot(self.reg, "buildings", ("Defender",), 0, 99))
        self.assertIsNone(resolve_slot(self.reg, "buildings", ("Defender",), -1, 0))


if __name__ == "__main__":
    unittest.main()
