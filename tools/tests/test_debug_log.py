"""Debug mode phase 1 + 4: the recorder, the round metrics, the reports.

Bare-minimum coverage by design (the brief says so explicitly): the JSONL shape,
the level gate, the round-row arithmetic, the actual-vs-potential income gap,
the CSV/schema pin, the self-contained-HTML pin, and purity.

Headless and pure-Python — a synth ``TileMapDoc`` -> ``TileMap`` fixture plus
real balancing from the pinned fixture data, exactly like ``test_phase_loop``.
Every file this suite writes goes into a tempdir; nothing touches ``data/``.
"""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats, YieldEconomy
from game.core import RunState, load_balance, run_payday
from game.core.xp import scaled_base_income
from game.debug import (
    LEVEL_BASIC, LEVEL_VERBOSE, ROUND_FIELDS, DebugRecorder,
)
from game.debug import events, metrics, report
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows):
    """A synth board with the base attached; returns (tilemap, scene, occ).
    Copied from ``tools/tests/test_phase_loop.py``."""
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def built_pairs(tm):
    """Payday's own ``built`` list: a DEAD building is still ``tile.occupant``
    (payday filters it with the ``alive`` check, it is never absent)."""
    return [(t, t.occupant) for t in tm.built_tiles() if t.occupant is not None]


def payday_with_hooks(rec, state, tm, occ, scene):
    """Drive a real ``run_payday`` with the recorder's three hooks around it.

    Phase 2 wires ``on_payday_story`` between payday steps 3 and 4; here it is
    called before ``run_payday`` instead, which is EXACTLY equivalent for these
    boards: no boss stacks are set, so step 3 pays nothing and the love delta
    the hook measures is 0 either way. ``on_payday_end`` reads only love / lives
    / xp / ``income_events`` — none of which steps 7-12 touch — so calling it
    after the full payday yields the same row as calling it after step 6.
    """
    rec.on_payday_start(state, tm, CORE, built_pairs(tm))
    rec.on_payday_story(state)
    run_payday(state, tm, CORE, occ, scene)
    rec.on_payday_end(state, tm)


def place(tm, scene, occ, state, col, row, btype):
    building, _cost = place_building(tm, tm.get(col, row), btype, 9999, BUILD,
                                     scene, occ, state)
    return building


# ---------------------------------------------------------------------------
class TestJsonlStream(unittest.TestCase):
    """1. The stream is one valid JSON object per line."""

    def test_one_json_object_per_line(self):
        state = RunState.from_balance(CORE, BUILD)
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t")
            rec.bind(state)
            rec.set_frame(7)
            rec.emit(events.RUN_START, level=1, run_id="t", map_id="synth",
                     seed=None, love=state.love, lives=state.base_lives)
            rec.emit(events.WAVE_START, wave_size=4, enemy_tier=1,
                     composition={"standard": 4})
            rec.emit(events.BASE_HIT, etype="standard", waived=False,
                     lives_after=2)
            rec.emit(events.CHEAT, action="add_love", amount=100)
            paths = rec.close(outcome="quit")

            lines = paths["jsonl"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 5)          # 4 emits + run_end
            for line in lines:
                obj = json.loads(line)               # raises on malformed JSON
                self.assertIsInstance(obj, dict)
                for stamp in ("t", "round", "phase", "frame", "wall_ms"):
                    self.assertIn(stamp, obj)
            kinds = [json.loads(ln)["t"] for ln in lines]
            self.assertEqual(kinds[0], events.RUN_START)
            self.assertEqual(kinds[-1], events.RUN_END)
            first = json.loads(lines[0])
            self.assertEqual(first["frame"], 7)
            self.assertEqual(first["round"], state.round_num)
            self.assertEqual(first["phase"], state.phase.name)


class TestLevelGate(unittest.TestCase):
    """2. Level-2 kinds are dropped at level 1."""

    def _kinds(self, level):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=level, run_id="t")
            rec.emit(events.WAVE_START, wave_size=1, enemy_tier=1)
            rec.emit(events.DAMAGE, attacker="defence", target="standard",
                     dmg=12, target_hp_after=8)
            rec.emit(events.DEFENDER_FIRE, building_type="defence", col=1,
                     row=0, target="standard")
            paths = rec.close()
            text = paths["jsonl"].read_text(encoding="utf-8")
        return [json.loads(ln)["t"] for ln in text.splitlines()]

    def test_level_two_kinds_dropped_at_level_one(self):
        basic = self._kinds(LEVEL_BASIC)
        self.assertIn(events.WAVE_START, basic)
        self.assertNotIn(events.DAMAGE, basic)
        self.assertNotIn(events.DEFENDER_FIRE, basic)

        verbose = self._kinds(LEVEL_VERBOSE)
        self.assertIn(events.DAMAGE, verbose)
        self.assertIn(events.DEFENDER_FIRE, verbose)

    def test_unknown_kind_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t")
            with self.assertRaises(ValueError):
                rec.emit("enmy_death")           # typo guard


class TestRoundSummary(unittest.TestCase):
    """3. Round-row arithmetic against a hand-built RunState + synth tilemap."""

    def test_row_matches_hand_computed_ledger(self):
        tm, scene, occ = build_board(["bbbb", "bbbb"])
        state = RunState.from_balance(CORE, BUILD)
        state.love = 500
        state.unlocked_buildings["aoe_defence"] = True
        eco = place(tm, scene, occ, state, 1, 0, "economic")
        dfn = place(tm, scene, occ, state, 2, 0, "aoe_defence")  # has upkeep
        dfn.get_component(RoundStats).dmg_dealt_this_round = 30
        dfn.get_component(RoundStats).dmg_taken_this_round = 7

        base_income = scaled_base_income(state, CORE)
        exp_income = base_income + eco.yield_amount()
        exp_upkeep = eco.upkeep() + dfn.upkeep()
        self.assertGreater(exp_upkeep, 0)
        love_start = state.love

        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t").bind(state)
            rec.emit(events.WAVE_START, wave_size=3, enemy_tier=2)
            rec.note_spawn(3)
            rec.note_kill()
            rec.note_kill()
            rec.note_base_hit()
            rec.note_lightning(50, 2)
            rec.note_love_spent(10, events.SPEND_PLACE)
            payday_with_hooks(rec, state, tm, occ, scene)
            row = rec.rounds[0]
            rec.close(outcome="quit")

        self.assertEqual(tuple(row), ROUND_FIELDS)   # exact keys, exact order
        self.assertEqual(row["round"], 1)
        self.assertEqual(row["love_start"], love_start)
        self.assertEqual(row["love_end"], state.love)
        self.assertEqual(row["base_income"], base_income)
        self.assertEqual(row["income_actual"], exp_income)
        self.assertEqual(row["income_potential"], exp_income)
        self.assertEqual(row["income_lost_to_damage"], 0)
        self.assertEqual(row["building_income_actual"], eco.yield_amount())
        self.assertEqual(row["upkeep_actual"], exp_upkeep)
        self.assertEqual(row["upkeep_potential"], exp_upkeep)
        self.assertEqual(row["upkeep_unpaid_from_deaths"], 0)
        self.assertEqual(row["net_actual"], exp_income - exp_upkeep)
        self.assertEqual(row["story_income"], 0)
        self.assertEqual(row["painter_income"], 0)
        # Damage: RoundStats only. Lightning is its own source, and a base
        # breach costs a life while applying NO HP damage.
        self.assertEqual(row["dmg_dealt"], 30)
        self.assertEqual(row["dmg_taken_buildings"], 7)
        self.assertEqual(row["dmg_dealt_lightning"], 50)
        self.assertEqual(row["lightning_hits"], 2)
        self.assertEqual(row["lives_lost"], 1)
        self.assertEqual(row["leaks"], 1)
        self.assertEqual(row["lives_end"], state.base_lives)
        self.assertEqual(row["kills"], 2)
        self.assertEqual(row["kidnaps"], 0)
        self.assertEqual(row["enemies_spawned"], 3)
        self.assertEqual(row["wave_size"], 3)
        self.assertEqual(row["enemy_tier"], 2)
        self.assertEqual(row["buildings_built"], 2)       # base excluded
        self.assertEqual(row["buildings_dead_at_payday"], 0)
        self.assertEqual(row["buildings_placed"], 1)
        self.assertEqual(row["love_spent_buildings"], 10)
        self.assertEqual(row["cheated"], 0)
        # Payday really moved love by the ledger the row reports.
        self.assertEqual(state.love, love_start + exp_income - exp_upkeep)

    def test_waived_base_hit_is_a_leak_but_costs_no_life(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t")
            rec.note_base_hit(waived=True)
            rec.note_base_hit()
            self.assertEqual(rec._acc["leaks"], 2)
            self.assertEqual(rec._acc["lives_lost"], 1)
            rec.close()


class TestIncomeLostToDeath(unittest.TestCase):
    """4. The load-bearing one: actual vs potential income when a building dies.

    ``run_payday``'s income sweep AND its upkeep sweep both ``continue`` on
    ``not alive``, so a building destroyed during the wave earns nothing and
    pays no upkeep. Both halves are reported, never fused.
    """

    def test_dead_income_building_splits_actual_from_potential(self):
        tm, scene, occ = build_board(["bbbb", "bbbb"])
        state = RunState.from_balance(CORE, BUILD)
        state.love = 500
        state.unlocked_buildings["aoe_defence"] = True
        alive_eco = place(tm, scene, occ, state, 1, 0, "economic")
        dead_eco = place(tm, scene, occ, state, 2, 0, "economic")
        alive_dfn = place(tm, scene, occ, state, 3, 0, "aoe_defence")
        dead_dfn = place(tm, scene, occ, state, 1, 1, "aoe_defence")
        for b in (dead_eco, dead_dfn):
            b.get_component(Health).hp = 0            # died during the wave
        self.assertFalse(dead_eco.alive)
        self.assertGreater(dead_eco.yield_amount(), 0)
        self.assertGreater(dead_dfn.upkeep(), 0)

        base_income = scaled_base_income(state, CORE)

        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t").bind(state)
            payday_with_hooks(rec, state, tm, occ, scene)
            row = rec.rounds[0]
            rec.close(outcome="quit")

        self.assertEqual(row["buildings_dead_at_payday"], 2)
        self.assertEqual(row["income_actual"],
                         base_income + alive_eco.yield_amount())
        self.assertEqual(row["income_potential"],
                         base_income + alive_eco.yield_amount()
                         + dead_eco.yield_amount())
        self.assertLess(row["income_actual"], row["income_potential"])
        # The gap is EXACTLY the dead income building's undisturbed yield.
        self.assertEqual(row["income_potential"] - row["income_actual"],
                         dead_eco.yield_amount())
        self.assertEqual(row["income_lost_to_damage"],
                         dead_eco.yield_amount())
        # ...and the dead buildings' upkeep was never billed.
        self.assertEqual(row["upkeep_actual"],
                         alive_eco.upkeep() + alive_dfn.upkeep())
        self.assertEqual(row["upkeep_potential"],
                         row["upkeep_actual"] + dead_eco.upkeep()
                         + dead_dfn.upkeep())
        self.assertEqual(row["upkeep_unpaid_from_deaths"],
                         dead_eco.upkeep() + dead_dfn.upkeep())
        self.assertGreater(row["upkeep_unpaid_from_deaths"], 0)
        self.assertEqual(row["net_potential"] - row["net_actual"],
                         row["income_lost_to_damage"]
                         - row["upkeep_unpaid_from_deaths"])

    def test_potential_sweep_never_advances_a_meditator_streak(self):
        """``collect_income`` has side effects; ``yield_amount`` does not.
        Reading the potential ledger must not move gameplay."""
        tm, scene, occ = build_board(["bbbb", "bbbb"])
        state = RunState.from_balance(CORE, BUILD)
        state.unlocked_buildings["meditator"] = True
        med = place(tm, scene, occ, state, 1, 0, "meditator")
        before = med.get_component(YieldEconomy).streak
        ledger = metrics.potential_ledger(state, tm, CORE, built_pairs(tm))
        after = med.get_component(YieldEconomy).streak
        self.assertEqual(before, after)
        self.assertEqual(ledger["building_income_potential"],
                         med.yield_amount())


class TestReports(unittest.TestCase):
    """5 + 6: the CSV header pin and the self-contained-HTML pin."""

    @staticmethod
    def _rows(n=3):
        rows = []
        for i in range(n):
            row = {f: 0 for f in ROUND_FIELDS}
            row.update(round=i + 1, love_start=10 * i, love_end=10 * i + 5,
                       income_actual=8 + i, income_potential=10 + i,
                       income_lost_to_damage=2, base_income=5,
                       upkeep_actual=3, upkeep_potential=4,
                       upkeep_unpaid_from_deaths=1, net_actual=5 + i,
                       net_potential=6 + i, dmg_dealt=40 * i,
                       dmg_dealt_lightning=5 * i, dmg_taken_buildings=7 * i,
                       lives_lost=i % 2, leaks=i % 2, lives_end=3 - i % 2,
                       kills=4 * i, enemies_spawned=4 * i + 1,
                       wave_size=4 * i + 1, enemy_tier=1, village_level=1)
            rows.append(row)
        return rows

    def test_csv_header_is_round_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rounds.csv"
            report.write_rounds_csv(self._rows(), path)
            with open(path, encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader)
                body = list(reader)
        self.assertEqual(tuple(header), ROUND_FIELDS)
        self.assertEqual(len(body), 3)

    def test_html_is_self_contained(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "report.html"
            report.write_html(self._rows(6), path, run_id="t",
                              outcome="game_over")
            text = path.read_text(encoding="utf-8")
        for forbidden in ("http://", "https://", "//cdn"):
            self.assertNotIn(forbidden, text)
        self.assertIn("<svg", text)
        self.assertIn("Actual vs potential income", text)

    def test_close_writes_all_four_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, level=LEVEL_BASIC, run_id="t")
            rec.rounds.extend(self._rows(2))
            rec.breakdowns.extend(
                {"round": r["round"], "dmg_dealt_by_type": {"defence": 40},
                 "dmg_taken_by_type": {"base": 7},
                 "income_actual_by_type": {"economic": 8},
                 "upkeep_actual_by_type": {"defence": 3},
                 "income_potential_by_type": {"economic": 10},
                 "love_spent_by_reason": {"place": 12}}
                for r in rec.rounds)
            written = rec.close(outcome="game_over")
            self.assertEqual(set(written), {"jsonl", "csv", "md", "html"})
            for path in written.values():
                self.assertTrue(path.exists(), path)
            md = written["md"].read_text(encoding="utf-8")
            self.assertIn("actual-vs-potential income gap", md)
            self.assertIn("Damage share by building type", md)
            self.assertIn("Love-spend breakdown", md)
            self.assertIn("Leak rounds", md)
            # Idempotent: a second close() is a no-op returning the same dict.
            self.assertEqual(rec.close(), written)


class TestPurity(unittest.TestCase):
    """7. Hard rule: game.debug imports no pygame — headless-testable."""

    def test_game_debug_does_not_import_pygame(self):
        code = (
            "import sys; "
            "import game.debug; "
            "assert 'pygame' not in sys.modules, 'pygame leaked into game.debug'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
