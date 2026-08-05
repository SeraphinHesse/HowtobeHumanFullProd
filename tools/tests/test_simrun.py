"""Debug mode phase 6: the headless balance-sweep runner (``tools/simrun.py``).

Bare-minimum coverage by design (the brief says so explicitly). Exactly the
four checks ``docs/briefs/debug-mode.md`` §6 names, and nothing else:

1. a short run writes a plausible ``rounds.csv``, and ``report.html``
   references no external URL;
2. **the level-1 / level-2 cross-check** — the proof that the ``RoundStats``
   aggregation behind ``dmg_dealt`` is correct;
3. **off-path regression** — a headless boot with no debug flag writes nothing
   to ``logs/``;
4. **determinism** — the same ``--seed`` twice produces a byte-identical
   ``rounds.csv``.

Every artifact goes into a tempdir; nothing touches ``data/`` or the repo's
real ``logs/``.

**What "plausible" is allowed to mean here.** ``simrun`` deliberately plays the
LIVE active map with the LIVE balancing, so a magnitude assertion would be an
assertion against ``data/`` content — the exact thing that put 18 tests
permanently in the red. So the numbers are pinned only where they are
STRUCTURALLY guaranteed no matter how a designer retunes:

* a defended run must deal damage, take damage and kill things (there are
  defenders and there are enemies);
* base income is paid every payday, so ``income_actual`` is positive;
* a run with NO defenders must leak — nothing can stop a walker — so the
  ``none`` baseline is what pins ``leaks``/``lives_lost``, not the defended run;
* everything else is pinned as internal ARITHMETIC (``net == income - upkeep``,
  ``lives_lost <= leaks``, actual <= potential), which no tuning can break.

``upkeep`` is the one column the brief's list names that is NOT asserted
non-zero, and that is a measured fact about the shipped data rather than a gap:
``DefenceBuildings.BasicDefence.tiers[0]`` ships ``base_upkeep: 0``, so the
cheapest defence a policy can buy genuinely bills nothing until tier 2 is
researched. Asserting otherwise would pin a balance value.
"""
import csv
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from game.buildings.registry import BUILDING_CLASSES  # noqa: E402
from game.debug import LEVEL_BASIC, LEVEL_VERBOSE, ROUND_FIELDS  # noqa: E402
from game.debug import events  # noqa: E402
from tools.simrun import run_sim  # noqa: E402

REPO = Path(__file__).resolve().parents[2]

#: Short enough to stay fast, long enough that waves scale and a defended run
#: has something to show. Seed pinned so the run is the same one every time.
ROUNDS, SEED = 6, 1
#: The building types a ``damage`` event's ``attacker`` can name. Exactly the
#: set ``RoundStats.dmg_dealt_this_round`` credits — everything else is an
#: enemy ``ETYPE`` or a null (an uncredited homing shot).
BUILDING_TYPES = frozenset(BUILDING_CLASSES)


def _rows(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _events(path):
    return [json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()]


#: Module-level memo. A sim run is SECONDS, not milliseconds, and both classes
#: below read the same level-1 run — re-running it per class would double the
#: module's cost for no extra coverage.
_TMP = tempfile.TemporaryDirectory()
_RUNS = {}


def _run(level, name):
    if name not in _RUNS:
        _RUNS[name] = run_sim(ROUNDS, "greedy_defence", SEED, level=level,
                              out_dir=Path(_TMP.name) / name)
    return _RUNS[name]


def tearDownModule():
    _RUNS.clear()
    _TMP.cleanup()


class SimRunCase(unittest.TestCase):
    """One tempdir + one defended level-1 run, shared by the checks that only
    read it."""

    @classmethod
    def setUpClass(cls):
        cls.out = Path(_TMP.name)
        cls.recorder = _run(LEVEL_BASIC, "basic")


# ---------------------------------------------------------------------------
class TestRoundsCsv(SimRunCase):
    """1. The CSV is a real, plausible per-round table and the HTML is
    self-contained."""

    def test_csv_header_and_row_count(self):
        rows = _rows(self.recorder.paths["csv"])
        self.assertEqual(tuple(rows[0]), ROUND_FIELDS)
        self.assertEqual(len(rows), len(self.recorder.rounds))
        self.assertGreaterEqual(len(rows), 2)
        self.assertEqual([int(r["round"]) for r in rows],
                         list(range(1, len(rows) + 1)))

    def test_numbers_are_plausible(self):
        rows = self.recorder.rounds
        total = lambda k: sum(r[k] for r in rows)  # noqa: E731
        # Structural: love is held, base income is paid, defenders shoot,
        # enemies hit back, and things die.
        self.assertGreater(rows[-1]["love_end"], 0)
        self.assertGreater(total("income_actual"), 0)
        self.assertGreater(total("base_income"), 0)
        self.assertGreater(total("dmg_dealt"), 0)
        self.assertGreater(total("dmg_taken_buildings"), 0)
        self.assertGreater(total("kills"), 0)
        self.assertGreater(total("enemies_spawned"), 0)
        self.assertGreater(total("buildings_placed"), 0)
        self.assertGreater(total("love_spent_buildings"), 0)
        # Arithmetic no retune can break.
        for row in rows:
            self.assertEqual(row["net_actual"],
                             row["income_actual"] - row["upkeep_actual"])
            self.assertEqual(row["net_potential"],
                             row["income_potential"] - row["upkeep_potential"])
            self.assertGreaterEqual(row["income_potential"],
                                    row["income_actual"])
            self.assertGreaterEqual(row["upkeep_potential"],
                                    row["upkeep_actual"])
            self.assertGreaterEqual(row["upkeep_actual"], 0)
            self.assertLessEqual(row["lives_lost"], row["leaks"])
            self.assertEqual(row["cheated"], 0)   # nothing here cheats

    def test_leaks_are_recorded_when_nothing_defends(self):
        """``leaks``/``lives_lost`` pinned on the DO-NOTHING baseline, where a
        breach is structural: with no defence placed, nothing on the map can
        stop a walker reaching the hole."""
        rec = run_sim(3, "none", SEED, level=LEVEL_BASIC,
                      out_dir=self.out / "none")
        rows = rec.rounds
        self.assertTrue(rows)
        self.assertGreater(sum(r["leaks"] for r in rows), 0)
        self.assertGreater(sum(r["lives_lost"] for r in rows), 0)
        self.assertLess(rows[-1]["lives_end"], rows[0]["lives_end"] + 1)

    def test_html_is_self_contained(self):
        text = self.recorder.paths["html"].read_text(encoding="utf-8")
        for forbidden in ("http://", "https://", "//cdn"):
            self.assertNotIn(forbidden, text)
        self.assertIn("<svg", text)

    def test_all_four_artifacts_land_in_the_out_dir(self):
        for kind in ("jsonl", "csv", "md", "html"):
            path = self.recorder.paths[kind]
            self.assertTrue(path.exists(), path)
            self.assertEqual(path.parent, self.out / "basic")
            self.assertTrue(path.name.startswith(f"sim-greedy_defence-{SEED}"))


# ---------------------------------------------------------------------------
class TestLevelOneTwoCrossCheck(SimRunCase):
    """2. THE load-bearing one: replay the SAME seed at level 2 and prove that
    the summed per-hit ``damage`` events equal the round row's ``dmg_dealt``,
    which is computed the completely different way — off ``RoundStats`` at
    payday, with no instrumentation in the combat sweep at all.

    Only events with a non-null BUILDING attacker are summed: that is exactly
    the set ``RoundStats.dmg_dealt_this_round`` credits, which is why an
    uncredited shot emits a null attacker instead of guessing one. Lightning is
    excluded by construction — it has no shooter, emits no ``damage`` event,
    and is reported separately as ``dmg_dealt_lightning``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.verbose = _run(LEVEL_VERBOSE, "verbose")

    def test_level_two_does_not_move_the_game(self):
        """The premise the cross-check rests on: level 2 only OBSERVES. Same
        seed, same rows — if this fails, the comparison below is meaningless."""
        self.assertEqual(self.recorder.rounds, self.verbose.rounds)

    def test_damage_events_sum_to_the_round_row(self):
        dealt, taken = Counter(), Counter()
        for rec in _events(self.verbose.paths["jsonl"]):
            if rec["t"] != events.DAMAGE:
                continue
            attacker = rec.get("attacker")
            if attacker in BUILDING_TYPES:
                dealt[rec["round"]] += rec["dmg"]
            else:
                taken[rec["round"]] += rec["dmg"]

        self.assertTrue(dealt, "no building-credited damage events at level 2")
        for row in self.verbose.rounds:
            n = row["round"]
            self.assertEqual(dealt[n], row["dmg_dealt"],
                             f"round {n}: summed damage events != dmg_dealt")
            self.assertEqual(taken[n], row["dmg_taken_buildings"],
                             f"round {n}: summed damage events != dmg_taken")
        # Lightning is reported separately and never as a `damage` event.
        self.assertEqual(sum(r["dmg_dealt_lightning"]
                             for r in self.verbose.rounds), 0)

    def test_level_one_records_no_level_two_kinds(self):
        kinds = {rec["t"] for rec in _events(self.recorder.paths["jsonl"])}
        self.assertNotIn(events.DAMAGE, kinds)
        self.assertNotIn(events.DEFENDER_FIRE, kinds)
        verbose_kinds = {rec["t"]
                         for rec in _events(self.verbose.paths["jsonl"])}
        self.assertIn(events.DAMAGE, verbose_kinds)
        self.assertIn(events.DEFENDER_FIRE, verbose_kinds)


# ---------------------------------------------------------------------------
class TestDeterminism(unittest.TestCase):
    """4. The same seed replays byte-for-byte — otherwise a diff between two
    balance revisions is unreadable noise."""

    def test_same_seed_twice_is_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            first = run_sim(4, "greedy_defence", 3, out_dir=tmp / "a")
            second = run_sim(4, "greedy_defence", 3, out_dir=tmp / "b")
            self.assertEqual(first.paths["csv"].read_bytes(),
                             second.paths["csv"].read_bytes())
            self.assertEqual(first.rounds, second.rounds)


# ---------------------------------------------------------------------------
class TestOffPathRegression(unittest.TestCase):
    """3. The guardrail the whole feature rests on: with no debug flag, a
    headless boot writes NOTHING. Compares the repo's real ``logs/`` listing
    across the boot (rather than pointing the game at a tempdir) because
    ``main(debug_log=None)`` never constructs a recorder at all, so the real
    directory is precisely where a leak would show up."""

    def test_headless_boot_without_debug_writes_no_logs(self):
        from game.main import main as game_main

        logs = REPO / "logs"
        before = sorted(p.name for p in logs.iterdir()) if logs.is_dir() else None
        frames = game_main(max_frames=120, autostart=True)
        after = sorted(p.name for p in logs.iterdir()) if logs.is_dir() else None
        self.assertEqual(frames, 120)
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
