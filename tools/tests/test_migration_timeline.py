"""``tools/migrate_timeline_from_unlock_min_round.py`` tests (TimelinePLAN
T6). Pure Python — hand-built fixture balancing dicts (never asserts
against live ``data/`` content, per ``data/CLAUDE.md``'s pinned-fixture
rule), so a future retune of real `unlock_min_round` values can't redden
this test for reasons unrelated to the migration logic itself.
"""
import unittest

from tools.migrate_timeline_from_unlock_min_round import compute_migration


def _tier(unlock_min_round, name="Tier"):
    return {"unlock_min_round": unlock_min_round, "name": name}


def _group(building_type, rounds, names=None):
    names = names or [f"{building_type} T{i}" for i in range(len(rounds))]
    return {
        "building_type": building_type,
        "card_slots": [f"{building_type}_t{i}_lvl1" for i in range(len(rounds))],
        "tiers": [_tier(r, n) for r, n in zip(rounds, names)],
    }


def _buildings_balance():
    return {
        "DefenceBuildings": {
            "BasicDefence": _group("defence", [0, 10, 30]),
            "AOEDefence": _group("aoe_defence", [0, 20, 30]),
        },
        "StructureBuildings": {
            "Blocker": _group("blocker", [5, 20, 30]),
        },
    }


def _core_balance():
    return {
        "XP": {
            "village_xp_base_threshold": 50,
            "village_xp_threshold_inc": 15,
            "village_xp_threshold_inc_growth": 5,
            "xp_per_standard_enemy": 1,
            "xp_per_raider": 1,
            "xp_per_siege_enemy": 5,
            "xp_per_boss": 150,
        }
    }


def _flat_type(count_start, count_per_round, start_round=1):
    return {
        "eras": [{"count_start": count_start, "count_per_round": count_per_round}],
        "endgame_scaling": {},
        "start_round": start_round,
    }


def _enemies_balance():
    return {
        "EnemyScaling": {
            "rounds_per_era": 10,
            "boss_round_in_era": 10,
            "tutorial_round_enemy_count": 1,
        },
        "EnemyTypes": {
            "Standard": _flat_type(2, 3, start_round=1),
            "Raider": _flat_type(0, 0, start_round=1000),
            "SiegeCannon": _flat_type(0, 0, start_round=1000),
            "Formation": _flat_type(0, 0, start_round=1000),
            "Commander": _flat_type(0, 0, start_round=1000),
            "Sniper": _flat_type(0, 0, start_round=1000),
            "Digger": _flat_type(0, 0, start_round=1000),
            "Drummer": _flat_type(0, 0, start_round=1000),
            "Boss": {"round_counts": []},
        },
    }


class TestComputeMigration(unittest.TestCase):
    def setUp(self):
        self.doc, self.diff_rows = compute_migration(
            _buildings_balance(), _core_balance(), _enemies_balance(),
            round_max=200, max_levels=60)

    def test_every_tier_is_placed_exactly_once(self):
        placed = set()
        for level in self.doc["Timeline"]["levels"]:
            for slot in level["offer_slots"]:
                assignment = slot["assignment"]
                self.assertIsNotNone(assignment)
                key = (assignment["building_type"], assignment["tier_index"])
                self.assertNotIn(key, placed)  # no duplicates
                placed.add(key)
        self.assertEqual(len(placed), 9)  # 3 groups x 3 tiers

    def test_output_validates_uniqueness(self):
        from editor import timeline_ops
        timeline_ops.validate_uniqueness(self.doc)  # must not raise

    def test_bucketing_preserves_relative_order_of_unlock_min_round(self):
        """The load-bearing property: nothing bucketed to an EARLIER
        village_level may have had a LARGER unlock_min_round than something
        bucketed later — the migration must never invert the designer's
        existing round-based ordering."""
        by_round = sorted(self.diff_rows, key=lambda row: row[4])  # old_round
        levels_in_round_order = [row[5] for row in by_round]  # village_level
        self.assertEqual(levels_in_round_order, sorted(levels_in_round_order))

    def test_kind_is_unlock_only_for_tier_index_zero(self):
        for level in self.doc["Timeline"]["levels"]:
            for slot in level["offer_slots"]:
                assignment = slot["assignment"]
                expected_kind = "unlock" if assignment["tier_index"] == 0 else "tier"
                self.assertEqual(assignment["kind"], expected_kind)

    def test_equal_round_gates_land_on_the_same_village_level(self):
        by_round_gate = {}
        for row in self.diff_rows:
            by_round_gate.setdefault(row[4], set()).add(row[5])
        for round_gate, village_levels in by_round_gate.items():
            self.assertEqual(
                len(village_levels), 1,
                f"round {round_gate} split across levels {village_levels}")


if __name__ == "__main__":
    unittest.main()
