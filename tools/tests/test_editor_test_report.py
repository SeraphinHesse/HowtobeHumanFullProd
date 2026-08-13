"""TR-4: the test-run report writer (editor/test_report.py).

NO TEST HERE MAY LAUNCH A REAL TEST RUN (TestRunnerPLAN §4, the plan's single
largest hazard): every case drives a CANNED result in the shape TR-3's
``RunResult`` dataclass defines, and writes into a tempdir repo. Nothing shells
out to pytest or testgate, nothing imports ``editor.test_runner``, and nothing
touches the real ``.claude/testruns/`` or ``data/``.
"""
import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from editor import test_report


def _domain(**overrides):
    d = {"label": None, "state": "passed", "done": 3, "total": None,
         "passed": 3, "failed": 0, "subfailed": 0, "skipped": 0,
         "modules": ("test_boss.py",)}
    d.update(overrides)
    return d


def _failure(nodeid, domain="enemies", kind="failed", params="", message=""):
    return {"nodeid": nodeid, "module": nodeid.split("/")[-1].split("::")[0],
            "domain": domain, "kind": kind, "params": params, "message": message}


def _canned(**overrides):
    """A canned RunResult-shaped mapping: a failing full gate run."""
    result = {
        "command": ("py", "tools/testgate.py", "check", "--stream"),
        "stream_command": ("py", "tools/testgate.py", "check", "--stream"),
        "domain": None,
        "verdict": "fail",
        "gate_line": "GATE FAIL  2 problem(s)",
        "completed": True,
        "cancelled": False,
        "returncode": 1,
        "total_ran": 2245,
        "started_at": 1786000862.0,
        "finished_at": 1786001258.0,
        "duration_s": 396.0,
        "domains": {
            "buildings": _domain(done=310, passed=310, modules=("test_boost.py",)),
            "enemies": _domain(state="failed", done=288, passed=286, failed=2,
                               skipped=0),
        },
        "failures": (
            _failure("tools/tests/test_boss.py::TestBossPhases::test_phase_two_hp",
                     message="AssertionError: 240 != 260"),
            _failure("tools/tests/test_enemies.py::TestEnemies::test_speed",
                     message="AssertionError: 1 != 2"),
        ),
        "unknown_modules": (),
        "raw_tail": ("=== short test summary info ===",),
    }
    result.update(overrides)
    return result


class _TmpRepoCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)


class TestBuildReport(unittest.TestCase):
    def test_every_documented_key_is_present(self):
        report = test_report.build_report(_canned())
        for key in ("schema_version", "kind", "domain", "gate_line", "verdict",
                    "passed", "completed", "cancelled", "returncode", "command",
                    "stream_command", "started_at", "finished_at", "duration_s",
                    "totals", "domains", "failures", "unknown_modules",
                    "raw_tail", "report_path"):
            self.assertIn(key, report)
        self.assertEqual(report["kind"], "gate")
        self.assertEqual(report["gate_line"], "GATE FAIL  2 problem(s)")
        self.assertFalse(report["passed"])
        # epoch float -> UTC ISO-Z, never local time.
        self.assertEqual(report["started_at"], "2026-08-06T07:21:02Z")

    def test_failures_sorted_and_domain_counters_verbatim(self):
        report = test_report.build_report(_canned(failures=(
            _failure("tools/tests/test_zeta.py::T::t"),
            _failure("tools/tests/test_alpha.py::T::t"),
        )))
        self.assertEqual([f["nodeid"] for f in report["failures"]],
                         ["tools/tests/test_alpha.py::T::t",
                          "tools/tests/test_zeta.py::T::t"])
        self.assertEqual(report["domains"]["enemies"]["failed"], 2)
        self.assertEqual(report["domains"]["enemies"]["passed"], 286)
        self.assertEqual(report["domains"]["enemies"]["label"], "Enemies")

    def test_totals_sum_the_per_domain_counters(self):
        report = test_report.build_report(_canned())
        self.assertEqual(report["totals"]["done"], 310 + 288)
        self.assertEqual(report["totals"]["failed"], 2)
        self.assertEqual(report["totals"]["ran"], 2245)

    def test_domain_rerun_carries_no_gate_line(self):
        report = test_report.build_report(
            _canned(domain="enemies", gate_line=None, verdict="fail"))
        self.assertEqual(report["kind"], "domain")
        self.assertEqual(report["domain"], "enemies")
        self.assertIsNone(report["gate_line"])

    def test_reads_an_object_as_well_as_a_mapping(self):
        obj = SimpleNamespace(**_canned())
        obj.domains = {k: SimpleNamespace(**v) for k, v in obj.domains.items()}
        obj.failures = tuple(SimpleNamespace(**f) for f in obj.failures)
        self.assertEqual(test_report.build_report(obj),
                         test_report.build_report(_canned()))


class TestRoundTrip(_TmpRepoCase):
    def test_write_then_load_matches_build(self):
        result = _canned()
        path = test_report.write_report(result, repo=self.repo)
        loaded = test_report.load_report(path)
        expected = test_report.build_report(result)
        expected["report_path"] = loaded["report_path"]
        self.assertEqual(loaded, expected)
        self.assertTrue(path.read_text(encoding="utf-8").endswith("\n"))

    def test_two_writes_of_the_same_result_are_byte_identical(self):
        result = _canned()
        first = test_report.write_report(result, repo=self.repo)
        second = test_report.write_report(result, repo=self.repo)
        a = json.loads(first.read_text(encoding="utf-8"))
        b = json.loads(second.read_text(encoding="utf-8"))
        a.pop("report_path"), b.pop("report_path")
        self.assertEqual(a, b)


class TestFailingNodeIds(_TmpRepoCase):
    def test_all_node_ids_survive_with_domain_and_message(self):
        failures = tuple(
            _failure(f"tools/tests/test_boss.py::T::test_{i}",
                     message=f"AssertionError: boom-{i}")
            for i in range(3)
        ) + tuple(
            _failure(f"tools/tests/test_hud_panel.py::T::test_{i}", domain="ui",
                     message=f"AssertionError: bang-{i}")
            for i in range(2))
        path = test_report.write_report(
            _canned(failures=failures), repo=self.repo)
        report = test_report.load_report(path)
        self.assertEqual(len(report["failures"]), 5)
        for record in report["failures"]:
            self.assertIn(record["domain"], ("enemies", "ui"))
            self.assertIn("AssertionError", record["message"])


class TestPathsAndCollision(_TmpRepoCase):
    def test_paths_stem_and_sibling_markdown(self):
        path = test_report.write_report(_canned(), repo=self.repo)
        self.assertEqual(path.parent, self.repo / ".claude" / "testruns")
        self.assertRegex(path.stem, r"^[0-9]{8}-[0-9]{6}(-[0-9]+)?$")
        self.assertTrue(path.with_suffix(".md").exists())

    def test_collision_suffixes_both_files(self):
        first = test_report.write_report(_canned(), repo=self.repo)
        second = test_report.write_report(_canned(), repo=self.repo)
        self.assertNotEqual(first, second)
        self.assertTrue(second.stem.endswith("-2"))
        self.assertTrue(second.with_suffix(".md").exists())
        self.assertTrue(first.with_suffix(".md").exists())


class TestGreenRunStillWrites(_TmpRepoCase):
    def test_pass_writes_both_files_and_a_prompt(self):
        gate = "GATE PASS  2245 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips"
        path = test_report.write_report(
            _canned(verdict="pass", gate_line=gate, failures=(),
                    domains={"enemies": _domain(done=288, passed=288)},
                    raw_tail=()),
            repo=self.repo)
        report = test_report.load_report(path)
        self.assertEqual(report["failures"], [])
        self.assertTrue(report["passed"])
        prompt = test_report.agent_prompt(path, repo=self.repo)
        self.assertIn("PASS", prompt)
        self.assertIn(report["report_path"], prompt)
        self.assertIn("No failures.", path.with_suffix(".md").read_text("utf-8"))


class TestAgentPrompt(_TmpRepoCase):
    def test_names_relative_posix_path_and_failing_areas(self):
        path = test_report.write_report(_canned(failures=(
            _failure("tools/tests/test_boss.py::T::test_a"),
            _failure("tools/tests/test_boss.py::T::test_b"),
            _failure("tools/tests/test_hud_panel.py::T::test_c", domain="ui"),
        )), repo=self.repo)
        prompt = test_report.agent_prompt(path, repo=self.repo)
        self.assertIn(".claude/testruns/", prompt)
        self.assertNotIn("\\", prompt)
        self.assertIn("Enemies (2 failed)", prompt)
        self.assertIn("UI (1 failed)", prompt)

    def test_node_id_list_is_capped_and_carries_no_message_text(self):
        failures = tuple(
            _failure(f"tools/tests/test_boss.py::T::test_{i}",
                     message="AssertionError: SECRET-TRACEBACK")
            for i in range(11))
        path = test_report.write_report(_canned(failures=failures), repo=self.repo)
        prompt = test_report.agent_prompt(path, repo=self.repo)
        self.assertIn("... and 3 more", prompt)
        self.assertNotIn("SECRET-TRACEBACK", prompt)

    def test_domain_rerun_prompt_has_no_gate_line(self):
        path = test_report.write_report(
            _canned(domain="enemies", gate_line=None,
                    domains={"enemies": _domain(state="failed", failed=2)}),
            repo=self.repo)
        prompt = test_report.agent_prompt(path, repo=self.repo)
        self.assertNotIn("GATE", prompt)
        self.assertIn("NOT a gate", prompt)
        self.assertIn("this is not a gate",
                      path.with_suffix(".md").read_text("utf-8").lower())


class TestCancelledRun(_TmpRepoCase):
    def test_cancelled_still_writes_and_flags_itself(self):
        path = test_report.write_report(
            _canned(verdict="cancelled", cancelled=True, completed=False,
                    gate_line=None, returncode=None),
            repo=self.repo)
        report = test_report.load_report(path)
        self.assertTrue(report["cancelled"])
        self.assertFalse(report["completed"])
        self.assertIsNone(report["gate_line"])
        self.assertFalse(report["passed"])
        self.assertTrue(path.with_suffix(".md").exists())


class TestUnknownModules(_TmpRepoCase):
    def test_unknown_modules_surface_sorted_in_json_and_markdown(self):
        path = test_report.write_report(
            _canned(unknown_modules=("test_zeta.py", "test_brand_new_thing.py")),
            repo=self.repo)
        report = test_report.load_report(path)
        self.assertEqual(report["unknown_modules"],
                         ["test_brand_new_thing.py", "test_zeta.py"])
        text = path.with_suffix(".md").read_text("utf-8")
        self.assertIn("test_brand_new_thing.py", text)
        self.assertIn("no known domain", text)


class TestTr6Seam(unittest.TestCase):
    """TR-6 inserts its ledger call at ONE marked point; pin the marker.

    TR-4 also asserted `testguard_ledger` appeared NOWHERE in the module — that
    was the pin for "the seam is still empty" and TR-6 is precisely the change
    that fills it, so the assertion is gone rather than worked around. What it
    was really protecting (one insertion point, one return) is still pinned
    here, and `TestGateCredit` below pins that the ledger is only ever reached
    through `tools.testguard_ledger`.
    """

    def test_marker_comment_precedes_the_single_return(self):
        source = Path(test_report.__file__).read_text(encoding="utf-8")
        self.assertIn("TR-6 inserts the ledger record here", source)
        self.assertEqual(len(re.findall(r"^    return path$", source, re.M)), 1)


class TestGateCredit(_TmpRepoCase):
    """TR-6: which runs are credited in the guard's ledger, and which are not.

    NOTHING here launches a test run, and nothing here writes into the LIVE
    guard state dir: every call passes `state=` a tempdir. A test that wrote a
    real record would suppress a real session's handoff gate — the exact
    wrong-record failure this phase exists to prevent.
    """

    FP = "a" * 64          # the tree as it was when the run started
    OTHER_FP = "b" * 64    # ...and after somebody edited it mid-run

    def setUp(self):
        super().setUp()
        self.state = self.repo / "testguard"

    def credit(self, report, started=None, finished=None):
        return test_report.record_gate_credit(
            report, self.FP if started is None else started,
            state=self.state,
            finished_fingerprint=self.FP if finished is None else finished)

    def records(self):
        return sorted(self.state.glob("run-*.json")) if self.state.exists() else []

    def test_a_completed_full_run_with_a_verdict_is_credited(self):
        from tools.testguard_ledger import normalised_target, run_key

        report = test_report.build_report(
            _canned(verdict="pass", gate_line="GATE PASS  2251 passed",
                    failures=(), returncode=0))
        self.assertTrue(self.credit(report))

        target = normalised_target(test_report.GATE_COMMAND)
        path = self.state / f"run-{run_key(target, self.FP)}.json"
        self.assertTrue(path.exists(), "credited under a key nothing looks up")
        record = json.loads(path.read_text("utf-8"))
        self.assertEqual(record["source"], "editor")
        self.assertEqual(record["target"], target)
        self.assertEqual(record["outcome"], "GATE PASS  2251 passed")

    def test_a_failing_gate_is_credited_too(self):
        """A FAIL record is useful: the guard hands the failure back and says
        fix the code. Only *pass* is not a precondition."""
        self.assertTrue(self.credit(test_report.build_report(_canned())))
        self.assertEqual(len(self.records()), 1)

    def test_nothing_is_credited_when_it_must_not_be(self):
        cases = {
            "per-area re-run": _canned(domain="enemies", gate_line=None),
            "cancelled": _canned(cancelled=True, completed=False,
                                 gate_line=None),
            "did not complete": _canned(completed=False, gate_line=None),
            "no verdict line": _canned(gate_line=None),
            "GATE ABORT": _canned(gate_line="GATE ABORT  cannot narrow"),
        }
        for name, result in cases.items():
            with self.subTest(case=name):
                report = test_report.build_report(result)
                self.assertFalse(self.credit(report))
                self.assertIsNotNone(
                    test_report.credit_refusal(report, self.FP, self.FP))
        self.assertEqual(self.records(), [])

    def test_a_tree_edited_mid_run_is_not_credited(self):
        """Both candidate keys would be wrong: the start key credits a tree
        that is gone, the end key credits a tree that was never tested."""
        report = test_report.build_report(_canned())
        self.assertFalse(self.credit(report, finished=self.OTHER_FP))
        self.assertEqual(self.records(), [])

    def test_an_unfingerprinted_run_is_not_credited(self):
        """No start fingerprint (git unavailable, or a caller that never
        captured one) means the tree cannot be proven unchanged -> no credit."""
        report = test_report.build_report(_canned())
        self.assertFalse(test_report.record_gate_credit(
            report, None, state=self.state, finished_fingerprint=self.FP))
        self.assertEqual(self.records(), [])

    def test_write_report_forwards_the_start_fingerprint_and_nothing_else(self):
        """The seam, driven end to end with the ledger stubbed out — so this
        test proves the wiring without going anywhere near real guard state."""
        seen = []
        original = test_report.record_gate_credit
        self.addCleanup(setattr, test_report, "record_gate_credit", original)
        test_report.record_gate_credit = lambda report, fp: seen.append(
            (report["kind"], fp)) or True

        test_report.write_report(_canned(), repo=self.repo,
                                 started_fingerprint=self.FP)
        test_report.write_report(_canned(), repo=self.repo)
        self.assertEqual(seen, [("gate", self.FP), ("gate", None)])


if __name__ == "__main__":
    unittest.main()
