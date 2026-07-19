"""Phase 9D Quick Test: building tier/level math + full-heal (game/buildings).

Walks the Musician (economy) and Defender (defence) lines from tier-0 level-1 to
tier-max, asserting max_hp / yield / damage / upkeep / upgrade_cost / level /
slot_key / at_tier_max against the values in data/balancing/buildings.json at
every step — and that every upgrade() and advance_tier() FULL-HEALS (prototype
update_stats_from_tier sets hp = max_hp on re-apply).
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine.core import Health
from game.buildings import Defender, Musician
from game.buildings.components import TierState
from game.buildings.storm_priest import StormPriest
from game.core.balance import load_balance

BAL = load_balance(FIXTURE_DATA, "buildings")
MUS = BAL["EconomyBuildings"]["Musicians"]["tiers"]
DEF = BAL["DefenceBuildings"]["BasicDefence"]["tiers"]
SP = BAL["DefenceBuildings"]["StormPriest"]["tiers"]


def steps(tiers):
    """The (tier, level_in_tier) sequence a building visits, in order."""
    return [(t, lvl) for t, tier in enumerate(tiers)
            for lvl in range(1, tier["levels"] + 1)]


class TierWalkMixin:
    tiers = None       # per-tier table (from buildings.json)
    sprites = None     # per-tier slot prefixes

    def make(self):
        raise NotImplementedError

    def extra_expected(self, tier, idx):
        """Line-specific expected stats {name: value} (yield vs damage)."""
        return {}

    def extra_actual(self, b):
        raise NotImplementedError

    def test_walk(self):
        b = self.make()
        seq = steps(self.tiers)
        for i, (t, lvl) in enumerate(seq):
            tier = self.tiers[t]
            idx = lvl - 1
            ts = b.get_component(TierState)
            with self.subTest(tier=t, level=lvl):
                self.assertEqual((ts.current_tier, ts.current_level_in_tier),
                                 (t, lvl))
                exp_hp = tier["base_hp"] + idx * tier["hp_per_level"]
                self.assertEqual(b.max_hp(), exp_hp)
                self.assertEqual(b.get_component(Health).max_hp, exp_hp)
                self.assertEqual(b.get_component(Health).hp, exp_hp)  # healthy
                self.assertEqual(
                    b.upgrade_cost(),
                    tier["upgrade_cost_base"] + idx * tier["upgrade_cost_increment"])
                self.assertEqual(
                    b.slot_key(),
                    f"{self.sprites[t]}_t{t + 1}_lvl{lvl}")
                self.assertEqual(b.at_tier_max(), lvl == tier["levels"])
                self.assertEqual(b.has_next_tier(), t + 1 < len(self.tiers))
                for name, val in self.extra_expected(tier, idx).items():
                    self.assertEqual(self.extra_actual(b)[name], val)

            # Transition to the next step; damage first to prove the full-heal.
            if i < len(seq) - 1:
                nt, _ = seq[i + 1]
                b.get_component(Health).damage(7)
                self.assertTrue(b.upgrade() if nt == t else b.advance_tier())
                self.assertEqual(b.get_component(Health).hp, b.max_hp())

        # exhausted: no more upgrades or tiers
        self.assertFalse(b.upgrade())
        self.assertFalse(b.advance_tier())


class TestMusician(TierWalkMixin, unittest.TestCase):
    tiers = MUS
    sprites = ("flute_player", "harp_player", "trio")

    def make(self):
        return Musician(1, 1, BAL)

    def extra_expected(self, tier, idx):
        return {"yield": tier["base_yield"] + idx * tier["yield_per_level"],
                "upkeep": 0}

    def extra_actual(self, b):
        return {"yield": b.yield_amount(), "upkeep": b.upkeep()}


class TestDefender(TierWalkMixin, unittest.TestCase):
    tiers = DEF
    sprites = ("stone_thrower", "slinger", "pistoleer")

    def make(self):
        return Defender(2, 3, BAL)

    def extra_expected(self, tier, idx):
        return {
            "damage": tier["base_dmg"] + idx * tier["dmg_per_level"],
            "upkeep": tier["base_upkeep"] + idx * tier["upkeep_per_level"],
            "range": tier["range_tiles"],
        }

    def extra_actual(self, b):
        return {"damage": b.damage(), "upkeep": b.upkeep(),
                "range": b.range_tiles()}


class TestStormPriest(TierWalkMixin, unittest.TestCase):
    tiers = SP
    sprites = ("storm_priest_i", "storm_priest_ii", "storm_priest_iii")

    def make(self):
        return StormPriest(4, 5, BAL)

    def extra_expected(self, tier, idx):
        return {
            "damage": tier["base_dmg"] + idx * tier["dmg_per_level"],
            "upkeep": tier["base_upkeep"] + idx * tier["upkeep_per_level"],
            "range": tier["range_tiles"],
        }

    def extra_actual(self, b):
        return {"damage": b.damage(), "upkeep": b.upkeep(),
                "range": b.range_tiles()}

    def test_tags_carry_combat_and_lightning_source(self):
        """EXTRA_TAGS fully overrides the base — must re-include ``"combat"``
        or this stops counting as a combatant (building.py:54)."""
        b = self.make()
        self.assertIn("combat", b.tags)
        self.assertIn("lightning_source", b.tags)
        self.assertIn("building", b.tags)


class TestDefenderRangeSensorSync(unittest.TestCase):
    def test_range_sensor_follows_tier(self):
        from engine.core import RangeSensor
        d = Defender(0, 0, BAL)
        # Stone Thrower range 1 -> Slinger range 2 after advancing a tier.
        self.assertEqual(d.get_component(RangeSensor).range_tiles, 1)
        d.advance_tier()
        self.assertEqual(d.get_component(RangeSensor).range_tiles, 2)


if __name__ == "__main__":
    unittest.main()
