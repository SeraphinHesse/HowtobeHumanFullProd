"""Phase 9D: buildings keep ALL state in components (engine E-11 guard).

A Building is a GameObject subclass, so it may not hold public instance state;
the duck-typed values the map layer reads (alive / building_type /
damage_dealt_last_round) are guard-safe properties backed by components, and
to_dict round-trips through those components.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine.core import Health
from game.buildings import Defender, Musician
from game.core.balance import load_balance

BAL = load_balance(REPO / "data", "buildings")


class TestStateInComponents(unittest.TestCase):
    def test_public_attribute_assignment_rejected(self):
        m = Musician(1, 1, BAL)
        with self.assertRaises(AttributeError):
            m.gold = 5  # gameplay state must live in a component (E-11)

    def test_duck_typed_contract(self):
        d = Defender(2, 3, BAL)
        self.assertTrue(d.alive)
        self.assertEqual(d.building_type, "defence")
        self.assertEqual(d.damage_dealt_last_round, 0)
        self.assertEqual((d.col, d.row), (2, 3))

    def test_alive_derives_from_health(self):
        d = Defender(0, 0, BAL)
        d.get_component(Health).damage(10 ** 6)
        self.assertFalse(d.alive)

    def test_damage_dealt_reads_roundstats(self):
        from game.buildings.components import RoundStats
        d = Defender(0, 0, BAL)
        d.get_component(RoundStats).dmg_dealt_last_round = 42
        self.assertEqual(d.damage_dealt_last_round, 42)

    def test_state_serializes_through_components(self):
        d = Defender(0, 0, BAL)
        types_present = {c["type"] for c in d.to_dict()["components"]}
        self.assertIn("TierState", types_present)
        self.assertIn("Health", types_present)
        self.assertIn("Attacker", types_present)


if __name__ == "__main__":
    unittest.main()
