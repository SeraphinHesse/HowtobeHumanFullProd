"""Phase 9C: per-tile pathfinding weight + state predicates (game/map/tiles.py).

Pins the PROTOTYPE-EXACT weight composition (src/map/tile.py:61-110): base
content weight -> + terrain condition (path_weights) -> + defence-range
coverage -> × damage-reduction discount, each modifier gated to
0 < base < impassable so the base tile (0) and background walls (999) are
exempt. Values are the shipped balancing in data/balancing/map.json.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from game.map import load_map_balance
from game.map.tiles import Tile, TileCondition, TileState

BALANCE = load_map_balance(FIXTURE_DATA)


def tile(state, content_key=None, condition=TileCondition.GRASS):
    return Tile(0, 0, state, content_key=content_key, condition=condition)


class TestBaseWeights(unittest.TestCase):
    def test_zone_weights(self):
        cases = {
            TileState.BUILDABLE: 1,
            TileState.COMBAT: 1,
            TileState.SPAWNING: 1,
        }
        for state, expected in cases.items():
            with self.subTest(state=state):
                self.assertEqual(tile(state).pathfinding_weight(BALANCE), expected)

    def test_background_is_impassable(self):
        self.assertEqual(
            tile(TileState.BACKGROUND).pathfinding_weight(BALANCE), 999)

    def test_occupied_content_weights(self):
        cases = {
            "base_building": 0,
            "economic_building": 1,
            "painter_building": 1,
            "defence_building": 2,
            "aoe_defence_building": 2,
        }
        for key, expected in cases.items():
            with self.subTest(key=key):
                t = tile(TileState.BUILT, content_key=key)
                self.assertEqual(t.pathfinding_weight(BALANCE), expected)


class TestConditionAdd(unittest.TestCase):
    def test_condition_adds_to_combat(self):
        cases = {
            TileCondition.GRASS: 1,      # +0
            TileCondition.FOREST: 2,     # +1
            TileCondition.MOUNTAIN: 3,   # +2
            TileCondition.POND: 10,      # +9
        }
        for cond, expected in cases.items():
            with self.subTest(cond=cond):
                t = tile(TileState.COMBAT, condition=cond)
                self.assertEqual(t.pathfinding_weight(BALANCE), expected)

    def test_condition_never_touches_base_or_background(self):
        base = tile(TileState.BUILT, content_key="base_building",
                    condition=TileCondition.POND)
        self.assertEqual(base.pathfinding_weight(BALANCE), 0)
        bg = tile(TileState.BACKGROUND, condition=TileCondition.POND)
        self.assertEqual(bg.pathfinding_weight(BALANCE), 999)


class TestDefenceRangeAdd(unittest.TestCase):
    def test_coverage_adds_when_flag_set(self):
        t = tile(TileState.COMBAT)
        t.defence_range_covered = True
        # add is 0 by default (9C) → no change; explicit add applies once.
        self.assertEqual(t.pathfinding_weight(BALANCE), 1)
        self.assertEqual(t.pathfinding_weight(BALANCE, defence_range_add=1), 2)

    def test_coverage_exempts_base(self):
        t = tile(TileState.BUILT, content_key="base_building")
        t.defence_range_covered = True
        self.assertEqual(t.pathfinding_weight(BALANCE, defence_range_add=5), 0)


class TestDamageReduction(unittest.TestCase):
    def test_discount_halves_and_clamps_to_one(self):
        combat = tile(TileState.COMBAT)          # base 1
        combat.damage_weight_reduced = True
        # round(1 * 0.5) = 0 -> clamped to 1
        self.assertEqual(combat.pathfinding_weight(BALANCE), 1)

        defence = tile(TileState.BUILT, content_key="defence_building")  # base 2
        defence.damage_weight_reduced = True
        self.assertEqual(defence.pathfinding_weight(BALANCE), 1)  # round(2*0.5)

    def test_applied_after_condition_add(self):
        # defence(2) + mountain(2) = 4, then × 0.5 -> 2
        t = tile(TileState.BUILT, content_key="defence_building",
                 condition=TileCondition.MOUNTAIN)
        t.damage_weight_reduced = True
        self.assertEqual(t.pathfinding_weight(BALANCE), 2)


class TestPredicates(unittest.TestCase):
    def test_is_passable(self):
        self.assertTrue(tile(TileState.COMBAT).is_passable)
        self.assertFalse(tile(TileState.BACKGROUND).is_passable)

    def test_is_unlocked(self):
        self.assertTrue(tile(TileState.BUILDABLE).is_unlocked)
        self.assertTrue(tile(TileState.BUILT).is_unlocked)
        self.assertFalse(tile(TileState.COMBAT).is_unlocked)
        self.assertFalse(tile(TileState.SPAWNING).is_unlocked)

    def test_is_occupied(self):
        self.assertTrue(
            tile(TileState.BUILT, content_key="base_building").is_occupied)
        self.assertFalse(tile(TileState.COMBAT).is_occupied)


if __name__ == "__main__":
    unittest.main()
