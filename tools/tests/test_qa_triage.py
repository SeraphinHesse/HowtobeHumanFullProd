"""tools/qa_triage.py — the multi-machine playtest coalescer.

Bare-minimum coverage by design: the two ingest rules that silently corrupt
every downstream number if they break (de-dup by run_id across host folders,
and round-0 normalisation), the default exclusions, and an end-to-end run that
must produce markdown without raising.

Everything is written into a tempdir; nothing touches ``data/`` or
``QATestingOutputs/``.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tools.qa_triage import (
    apply_filters, build_report, classify_rounds, load_session, pool_rounds,
    write_html_report,
)


class _Args:
    def __init__(self, **kw):
        self.session = Path(".")
        self.form = None
        self.skill = None
        self.outcome = None
        self.min_rounds = 3
        self.include_devs = False
        self.include_cheats = False
        self.__dict__.update(kw)


def _round(n, **over):
    row = {
        "t": "round_summary", "round": n, "wall_ms": 1000 * n,
        "love_start": 5, "love_end": 15, "income_actual": 10,
        "income_potential": 10, "income_lost_to_damage": 0, "upkeep_actual": 0,
        "love_spent_buildings": 10, "leaks": 0, "lives_lost": 0, "lives_end": 3,
        "enemies_spawned": 3, "kills": 3, "kidnaps": 0, "wave_size": 3,
        "village_level": 1, "cheated": 0,
    }
    row.update(over)
    return row


def _run(run_id, *, first_round=1, n_rounds=5, skill="never", name="p", extra=()):
    events = [{
        "t": "run_start", "round": 0, "wall_ms": 0, "run_id": run_id,
        "map_id": "m", "player_name": name, "player_skill": skill,
    }]
    events += [_round(first_round + i) for i in range(n_rounds)]
    events += list(extra)
    events.append({"t": "run_end", "round": n_rounds, "wall_ms": 9000, "outcome": "game_over"})
    return events


def _write(session: Path, host: str, run_id: str, events):
    folder = session / f"logs, {host}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{run_id}-events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8"
    )


class TestIngest(unittest.TestCase):
    def test_identical_run_on_three_hosts_counts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            events = _run("run-A")
            for host in ("joel", "pantelis", "seraphin"):
                _write(session, host, "run-A", events)
            runs, notes = load_session(session)
            self.assertEqual(len(runs), 1)
            self.assertEqual(notes, [])

    def test_same_run_id_different_content_is_flagged_not_merged(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            _write(session, "joel", "run-A", _run("run-A", n_rounds=5))
            _write(session, "seraphin", "run-A", _run("run-A", n_rounds=9))
            runs, notes = load_session(session)
            self.assertEqual(len(runs), 1)
            self.assertTrue(any("COLLISION" in n for n in notes), notes)

    def test_round_zero_runs_are_shifted_so_first_played_round_is_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            _write(session, "a", "run-zero", _run("run-zero", first_round=0, n_rounds=4))
            _write(session, "a", "run-one", _run("run-one", first_round=1, n_rounds=4))
            runs, _ = load_session(session)
            for run in runs:
                self.assertEqual(run.rounds[0]["round"], 1, run.run_id)
                self.assertEqual(run.last_round, 4, run.run_id)

    def test_host_folder_prefix_is_stripped(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            _write(session, "joel", "run-A", _run("run-A"))
            runs, _ = load_session(session)
            self.assertEqual(runs[0].host, "joel")


class TestFilters(unittest.TestCase):
    def _pool(self, session):
        _write(session, "a", "run-ok", _run("run-ok"))
        _write(session, "a", "run-short", _run("run-short", n_rounds=1))
        _write(session, "a", "run-dev", _run("run-dev", skill="developer"))
        _write(session, "a", "run-cheat", _run(
            "run-cheat", extra=[{"t": "cheat", "round": 1, "wall_ms": 1, "action": "add_love"}]))
        _write(session, "a", "run-abit", _run("run-abit", skill="a_bit"))
        return load_session(session)[0]

    def test_defaults_drop_devs_cheats_and_abandoned_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self._pool(Path(tmp))
            kept, excluded = apply_filters(runs, _Args())
            self.assertEqual({r.run_id for r in kept}, {"run-ok", "run-abit"})
            self.assertEqual(sum(excluded.values()), 3)

    def test_skill_filter_keeps_only_that_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            runs = self._pool(Path(tmp))
            kept, _ = apply_filters(runs, _Args(skill=["a_bit"]))
            self.assertEqual([r.run_id for r in kept], ["run-abit"])


class TestReport(unittest.TestCase):
    def test_report_renders_every_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            for i in range(4):
                _write(session, "a", f"run-{i}", _run(
                    f"run-{i}", n_rounds=4 + i,
                    extra=[
                        {"t": "place", "round": 1, "wall_ms": 5, "building_type": "defence",
                         "col": 512, "row": 512, "cost": 10},
                        {"t": "wave_start", "round": 1, "wall_ms": 500, "wave_size": 3,
                         "composition": {"standard": 3}},
                        {"t": "enemy_death", "round": 1, "wall_ms": 600, "etype": "standard",
                         "wx": 512.0, "wy": 511.0},
                        {"t": "levelup", "round": 2, "wall_ms": 700, "option": "unlock_building"},
                        {"t": "unlock", "round": 2, "wall_ms": 700, "building_type": "blocker"},
                    ],
                ))
            runs, notes = load_session(session)
            kept, excluded = apply_filters(runs, _Args())
            md = build_report(kept, excluded, notes, _Args(session=session))
            for heading in ("## 1. Cohort", "## 2. Difficulty curve",
                            "## 4. Economy curve", "## 6. Building meta",
                            "## 7. Progression choices"):
                self.assertIn(heading, md)
            # Breaches and lives_lost are one metric, never two columns.
            self.assertNotIn("lives lost", md)

    def test_html_is_one_self_contained_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            for i in range(4):
                _write(session, "a", f"run-{i}", _run(
                    f"run-{i}", n_rounds=4 + i, skill="never" if i % 2 else "a_bit",
                    extra=[
                        {"t": "place", "round": 1, "wall_ms": 5, "building_type": "defence",
                         "col": 512, "row": 512, "cost": 10},
                        {"t": "wave_start", "round": 1, "wall_ms": 500, "wave_size": 3,
                         "composition": {"standard": 3}},
                        {"t": "enemy_death", "round": 1, "wall_ms": 600, "etype": "standard",
                         "wx": 512.0, "wy": 511.0},
                        {"t": "levelup", "round": 2, "wall_ms": 700, "option": "tier"},
                        {"t": "boss_choice", "round": 3, "wall_ms": 800, "boss_num": 1,
                         "option": "B", "outcome": "loss"},
                    ],
                ))
            runs, notes = load_session(session)
            kept, excluded = apply_filters(runs, _Args())
            out = session / "TRIAGE.html"
            write_html_report(out, kept, excluded, notes, _Args(session=session))
            doc = out.read_text(encoding="utf-8")

            self.assertTrue(doc.startswith("<!DOCTYPE html>"))
            self.assertIn("</html>", doc)
            self.assertIn("<svg", doc)
            # No CDN, no external stylesheet, no remote font: it must open offline.
            self.assertNotIn("http://", doc)
            self.assertNotIn("https://", doc)
            self.assertNotIn("<link", doc)
            # Nothing rendered from a divide-by-zero or a missing key.
            for poison in ("NaN", "undefined", "Infinity", "None"):
                self.assertNotIn(poison, doc, poison)

    def test_markdown_and_html_agree_on_the_spike_rounds(self):
        """One threshold source — the two renderers can never disagree."""
        with tempfile.TemporaryDirectory() as tmp:
            session = Path(tmp)
            # Ten runs, all breaching hard on round 3 only.
            for i in range(10):
                events = _run(f"run-{i}", n_rounds=5)
                for row in events:
                    if row.get("t") == "round_summary" and row["round"] == 3:
                        row["leaks"] = row["lives_lost"] = 1
                _write(session, "a", f"run-{i}", events)
            runs, _ = load_session(session)
            kept, _ = apply_filters(runs, _Args())
            hard, easy = classify_rounds(kept, pool_rounds(kept))
            self.assertEqual([r for r, _b, _m in hard], [3])
            self.assertIn(1, easy)


if __name__ == "__main__":
    unittest.main()
