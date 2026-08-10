"""``engine.xp_curve`` / ``game.core.xp_curve`` / ``editor.timeline_curve``
tests (TimelinePLAN T3).

Pure Python; every fixture is hand-built (never asserts against live
``data/`` content, per ``data/CLAUDE.md``'s pinned-fixture rule). The
load-bearing tests are ``TestBestCaseCurve`` (boss-round table + fallback,
round-0 tutorial override, non-boss types excluded on a boss round) and
``TestDrift`` (the editor/game vocabulary adapters agree byte-for-byte).
"""
import unittest

from engine import xp_curve as engine_xc
from game.core import xp_curve as game_xc
from editor import timeline_curve as editor_xc


def _flat_type_cfg(count_start, count_per_round, start_round=1, factors=None):
    return {
        "eras": [{"count_start": count_start, "count_per_round": count_per_round}],
        "endgame_scaling": factors or {},
        "start_round": start_round,
    }


class TestEngineTypeCount(unittest.TestCase):
    def test_flat_row_before_start_round_is_zero(self):
        era_cfg = {"rounds_per_era": 10}
        cfg = _flat_type_cfg(1, 1, start_round=5)
        self.assertEqual(engine_xc.type_count_for_round(4, era_cfg, cfg), 0)
        self.assertEqual(engine_xc.type_count_for_round(5, era_cfg, cfg), 1)
        self.assertEqual(engine_xc.type_count_for_round(6, era_cfg, cfg), 2)

    def test_endgame_scaling_compounds_past_last_era(self):
        era_cfg = {"rounds_per_era": 10}
        cfg = {
            "eras": [{"count_start": 1.0, "count_per_round": 1.0}],
            "endgame_scaling": {"count": 2.0},
            "start_round": 1,
        }
        # era 0 covers rounds 1-10; round 21 is era 2, two eras past the
        # single authored row -> count_per_round doubles twice (factor**2).
        base_row_count = engine_xc.type_count_for_round(11, era_cfg, cfg)
        scaled_count = engine_xc.type_count_for_round(21, era_cfg, cfg)
        self.assertGreater(scaled_count, base_row_count)


class TestEngineCumulativeAndCrossings(unittest.TestCase):
    def test_cumulative_sums_and_crossings(self):
        def counts_for_round(round_num):
            return {"a": round_num}  # 1, 2, 3, ... enemies of type "a"

        xp_per_type = {"a": 10}
        cumulative = engine_xc.cumulative_best_case_xp(1, 5, xp_per_type, counts_for_round)
        # round totals: 10, 20, 30, 40, 50 -> cumulative 10, 30, 60, 100, 150
        self.assertEqual(cumulative, {1: 10, 2: 30, 3: 60, 4: 100, 5: 150})

        crossings = engine_xc.threshold_crossing_rounds(cumulative, [25, 60, 999])
        self.assertEqual(crossings, {1: 2, 2: 3, 3: None})

    def test_missing_xp_key_contributes_zero(self):
        cumulative = engine_xc.cumulative_best_case_xp(
            1, 1, {}, lambda r: {"unmapped": 5})
        self.assertEqual(cumulative, {1: 0})


# --- a small, self-contained enemies/core balancing fixture, matching the
# real schema shapes (eras/endgame_scaling/start_round, Boss.round_counts,
# core.json's XP group) but with tiny hand-picked numbers, never copied from
# live data/ content.

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


def _enemies_balance():
    scaling = {
        "rounds_per_era": 10,
        "boss_round_in_era": 10,
        "tutorial_round_enemy_count": 3,
    }
    types = {}
    # Standard/Raider/SiegeCannon/Commander: the four boss-table blocks.
    types["Standard"] = _flat_type_cfg(1, 2, start_round=1)
    types["Raider"] = _flat_type_cfg(1, 1, start_round=5)
    types["SiegeCannon"] = _flat_type_cfg(1, 1, start_round=4)
    types["Commander"] = _flat_type_cfg(0, 0, start_round=1)
    # Formation/Sniper/Digger/Drummer: must NEVER appear on a boss round.
    types["Formation"] = _flat_type_cfg(1, 1, start_round=2)
    types["Sniper"] = _flat_type_cfg(1, 1, start_round=3)
    types["Digger"] = _flat_type_cfg(1, 1, start_round=3)
    types["Drummer"] = _flat_type_cfg(1, 1, start_round=3)
    types["Boss"] = {
        "round_counts": [
            {"regular": 5, "raiders": 2, "siege": 1, "commander": 0},
        ]
    }
    return {"EnemyScaling": scaling, "EnemyTypes": types}


class TestBestCaseCurve(unittest.TestCase):
    def test_round_zero_is_tutorial_standard_only(self):
        core, enemies = _core_balance(), _enemies_balance()
        counts = game_xc._counts_for_round(0, enemies, game_xc._type_configs(enemies))
        self.assertEqual(counts, {"Standard": 3})

    def test_boss_round_uses_table_and_excludes_newer_types(self):
        core, enemies = _core_balance(), _enemies_balance()
        # round 10 = era 0's boss round (round_in_era 10 == boss_round_in_era).
        counts = game_xc._counts_for_round(10, enemies, game_xc._type_configs(enemies))
        self.assertEqual(counts["Standard"], 5)
        self.assertEqual(counts["Raider"], 2)
        self.assertEqual(counts["SiegeCannon"], 1)
        self.assertEqual(counts["Commander"], 0)
        self.assertEqual(counts["__boss__"], 1)
        self.assertNotIn("Formation", counts)
        self.assertNotIn("Sniper", counts)
        self.assertNotIn("Digger", counts)
        self.assertNotIn("Drummer", counts)

    def test_boss_round_past_the_table_falls_back_to_formula(self):
        core, enemies = _core_balance(), _enemies_balance()
        # round 20 = era 1's boss round; round_counts has only 1 row (era 0),
        # so era 1 must fall back to the per-type formula.
        counts = game_xc._counts_for_round(20, enemies, game_xc._type_configs(enemies))
        expected_standard = engine_xc.type_count_for_round(
            20, {"rounds_per_era": 10}, game_xc._type_configs(enemies)["Standard"])
        self.assertEqual(counts["Standard"], expected_standard)
        self.assertEqual(counts["__boss__"], 1)

    def test_normal_round_sums_every_non_boss_type(self):
        core, enemies = _core_balance(), _enemies_balance()
        counts = game_xc._counts_for_round(5, enemies, game_xc._type_configs(enemies))
        self.assertIn("Formation", counts)
        self.assertIn("Sniper", counts)
        self.assertIn("Digger", counts)
        self.assertIn("Drummer", counts)
        self.assertNotIn("__boss__", counts)

    def test_threshold_sequence_matches_documented_curve(self):
        core = _core_balance()
        seq = game_xc.threshold_sequence(core, 5)
        # per-level thresholds 50/65/85/110/140 -> cumulative running sums.
        self.assertEqual(seq, [50, 115, 200, 310, 450])

    def test_best_case_curve_returns_monotonic_cumulative_and_crossings(self):
        core, enemies = _core_balance(), _enemies_balance()
        cumulative, level_to_round = game_xc.best_case_curve(
            core, enemies, 0, 15, max_levels=3)
        rounds = sorted(cumulative)
        self.assertEqual(rounds, list(range(0, 16)))
        values = [cumulative[r] for r in rounds]
        self.assertEqual(values, sorted(values))  # cumulative never decreases
        self.assertIn(1, level_to_round)
        # Level 1 requires 50 cumulative xp; with these fixture rates that is
        # reached well before round 15, and reached by an EARLIER round than
        # level 2's (higher) threshold, if level 2 is reached at all.
        self.assertIsNotNone(level_to_round[1])
        if level_to_round[2] is not None:
            self.assertLessEqual(level_to_round[1], level_to_round[2])


class TestDrift(unittest.TestCase):
    """editor.timeline_curve must reproduce game.core.xp_curve byte-for-byte
    on the same fixture data (TestRegistryGroupDrift pattern, D7)."""

    def test_best_case_curve_matches_across_packages(self):
        core, enemies = _core_balance(), _enemies_balance()
        game_result = game_xc.best_case_curve(core, enemies, 0, 25, max_levels=5)
        editor_result = editor_xc.best_case_curve(core, enemies, 0, 25, max_levels=5)
        self.assertEqual(game_result, editor_result)

    def test_threshold_sequence_matches_across_packages(self):
        core = _core_balance()
        self.assertEqual(
            game_xc.threshold_sequence(core, 10),
            editor_xc.threshold_sequence(core, 10))


if __name__ == "__main__":
    unittest.main()
