"""``engine.era_math`` tests (Phase ES-1, EnemyScalingReworkPLAN).

Pure Python; no data files, no game vocabulary beyond the neutral type labels
this module's parity sweep needs to name the four count formulas it replaces.

The load-bearing test here is `TestCountParity` — the round-by-round proof that
the per-era ``count_start``/``count_per_round`` seeding of plan §4 reproduces
today's ``//`` formulas exactly, and that it does so ONLY because `count_start`
is a number and not an int (D3').
"""
import unittest

from engine.era_math import (
    count_at_round,
    era_of_round,
    is_boss_round,
    prev_era_reference,
    resolve_era_row,
    round_in_era,
    stats_at_round,
)

RPE = 10  # shipped rounds_per_era


def _era_first_round(era):
    return era * RPE + 1


# --- plan §4 seeding, expressed as code so the sweep can build any era row ---
# (start_round, count_per_round, count_start-at-r0 as an exact expression)
_SEEDS = {
    "standard": (1, lambda e: 2 + e, lambda r0, e: 1 + (r0 - 1) * (2 + e)),
    "raider": (5, lambda e: 1, lambda r0, e: 1 + (r0 - 5)),
    "siege": (14, lambda e: 1, lambda r0, e: 1 + (r0 - 14)),
    "formation": (16, lambda e: 1 / 3, lambda r0, e: 1 + (r0 - 16) / 3),
}


def _seeded_row(kind, era):
    start_round, per_round, start_count = _SEEDS[kind]
    r0 = max(_era_first_round(era), start_round)
    return {
        "count_start": start_count(r0, era),
        "count_per_round": per_round(era),
    }, start_round


def _old_count(kind, round_num):
    """Today's hardcoded spawner formulas, inline (game/enemies/spawner.py)."""
    tier = era_of_round(round_num, RPE)
    if kind == "standard":
        return 1 + (round_num - 1) * (2 + tier)
    if kind == "raider":
        return 1 + (round_num - 5) * 1
    if kind == "siege":
        return 1 + (round_num - 14) // 1
    return 1 + (round_num - 16) // 3


class TestClock(unittest.TestCase):
    def test_boundary_rounds(self):
        for round_num, era, pos in [
            (0, 0, 1),  # D11: the tutorial round is era 0, not era -1
            (1, 0, 1),
            (10, 0, 10),
            (11, 1, 1),
            (20, 1, 10),
            (21, 2, 1),
        ]:
            self.assertEqual(era_of_round(round_num, RPE), era, round_num)
            self.assertEqual(round_in_era(round_num, RPE), pos, round_num)

    def test_boss_rounds_default_clock(self):
        bosses = [r for r in range(0, 31) if is_boss_round(r, RPE, RPE)]
        self.assertEqual(bosses, [10, 20, 30])

    def test_round_zero_is_never_a_boss(self):
        for rounds_per_era in (1, 3, 10):
            for boss_at in range(1, rounds_per_era + 1):
                self.assertFalse(is_boss_round(0, rounds_per_era, boss_at))

    def test_era_of_round_is_also_the_season_formula(self):
        """N1: the ground-art season IS ``era_of_round`` (D7) — no season math
        of its own exists, so this pins the shared function's season reading."""
        self.assertEqual([era_of_round(r, 10) for r in range(1, 11)], [0] * 10)
        self.assertEqual([era_of_round(r, 10) for r in range(11, 21)], [1] * 10)

    def test_non_default_clock(self):
        # rounds_per_era 5, boss on the 3rd round of each era
        self.assertEqual([era_of_round(r, 5) for r in (1, 5, 6, 11)], [0, 0, 1, 2])
        self.assertEqual([round_in_era(r, 5) for r in (1, 5, 6, 11)], [1, 5, 1, 1])
        self.assertEqual(
            [r for r in range(1, 16) if is_boss_round(r, 5, 3)], [3, 8, 13]
        )


class TestResolveEraRow(unittest.TestCase):
    def _rows(self):
        return [
            {"stats": {"hp": 100, "dmg": 10}, "count_start": 1.5, "batch_size": 2},
            {"stats": {"hp": 200, "dmg": 20}, "count_start": 2.5, "batch_size": 4},
        ]

    def test_in_range_and_clamp(self):
        rows = self._rows()
        self.assertIs(resolve_era_row(rows, 0, None), rows[0])
        self.assertIs(resolve_era_row(rows, 1, None), rows[1])
        # past the end with no factors == a plain clamp (a fresh, equal dict)
        self.assertEqual(resolve_era_row(rows, 7, None), rows[1])

    def test_all_one_factors_equal_plain_clamp(self):
        rows = self._rows()
        factors = {"hp": 1.0, "dmg": 1.0, "count": 1.0, "batch_size": 1.0}
        for era in (2, 5, 9):
            self.assertEqual(resolve_era_row(rows, era, factors), rows[1])

    def test_endgame_factor_compounds_and_never_mutates(self):
        rows = self._rows()
        factors = {"hp": 2.0, "count": 2.0, "batch_size": 1.5}
        row = resolve_era_row(rows, 3, factors)  # N = 3 - 1 = 2
        self.assertEqual(row["stats"]["hp"], 200 * 4)
        self.assertEqual(row["stats"]["dmg"], 20)  # no factor -> unscaled
        self.assertEqual(row["count_start"], 2.5 * 4)
        self.assertEqual(row["batch_size"], 9)  # int leaf floors: 4 * 2.25
        self.assertEqual(rows, self._rows())
        self.assertIsNot(row["stats"], rows[1]["stats"])


class TestStatsAtRound(unittest.TestCase):
    ROW = {
        "stats": {"hp": 100, "dmg": 10, "move_speed": 1.0, "attack_speed": 0.5},
        "per_round": {"hp": 12, "dmg": 1, "move_speed": 0.1},
    }

    def test_first_round_of_era_is_the_authored_row(self):
        self.assertEqual(stats_at_round(self.ROW, 1), self.ROW["stats"])

    def test_flat_additive_growth(self):
        got = stats_at_round(self.ROW, 5)
        self.assertEqual(got["hp"], 100 + 4 * 12)
        self.assertEqual(got["dmg"], 10 + 4)
        self.assertAlmostEqual(got["move_speed"], 1.4)
        self.assertEqual(got["attack_speed"], 0.5)  # no delta key -> flat
        self.assertEqual(self.ROW["stats"]["hp"], 100)


class TestCountAtRound(unittest.TestCase):
    def test_zero_before_start_round(self):
        row = {"count_start": 1, "count_per_round": 1}
        self.assertEqual(count_at_round(row, 13, 11, 14), 0)
        self.assertEqual(count_at_round(row, 14, 11, 14), 1)


class TestCountParity(unittest.TestCase):
    """The D3' fence: per-era seeding == today's formulas, round by round."""

    def _mismatches(self, last_round, floor_count_start):
        bad = []
        for kind in _SEEDS:
            for round_num in range(1, last_round + 1):
                era = era_of_round(round_num, RPE)
                row, start_round = _seeded_row(kind, era)
                if round_num < start_round:
                    continue
                if floor_count_start:
                    row = dict(row, count_start=int(row["count_start"]))
                got = count_at_round(
                    row, round_num, _era_first_round(era), start_round
                )
                if got != _old_count(kind, round_num):
                    bad.append((kind, round_num, got, _old_count(kind, round_num)))
        return bad

    def test_seeded_counts_reproduce_todays_formulas_to_round_40(self):
        self.assertEqual(self._mismatches(40, floor_count_start=False), [])

    def test_int_count_start_would_break_the_formation_from_round_22(self):
        """Teeth check: the sweep above must FAIL under the pre-D3' int shape."""
        bad = self._mismatches(40, floor_count_start=True)
        self.assertTrue(bad)
        self.assertEqual({kind for kind, *_ in bad}, {"formation"})
        self.assertEqual(bad[0][:2], ("formation", 22))

    def test_formation_era_anchors_match_the_plan_table(self):
        anchors = [_seeded_row("formation", e)[0]["count_start"] for e in range(5)]
        for got, want in zip(anchors, [1, 1, 2.667, 6, 9.333]):
            self.assertAlmostEqual(got, want, places=3)


class TestPrevEraReference(unittest.TestCase):
    ROWS = [
        {
            "stats": {"hp": 100, "dmg": 10},
            "per_round": {"hp": 5},
            "count_start": 1.0,
            "count_per_round": 2,
        },
        {
            "stats": {"hp": 300, "dmg": 30},
            "per_round": {"hp": 7},
            "count_start": 21.0,
            "count_per_round": 3,
        },
    ]

    def test_era_zero_has_no_reference(self):
        self.assertIsNone(prev_era_reference(self.ROWS, 0, RPE))

    def test_last_round_of_previous_era(self):
        ref = prev_era_reference(self.ROWS, 1, RPE, start_round=1)
        self.assertEqual(ref["stats"]["hp"], 100 + 9 * 5)  # round 10
        self.assertEqual(ref["stats"]["dmg"], 10)
        self.assertEqual(ref["count_start"], 1 + 9 * 2)  # count on round 10
        self.assertEqual(ref["count_per_round"], 2)
        self.assertEqual(self.ROWS[0]["stats"]["hp"], 100)


if __name__ == "__main__":
    unittest.main()
