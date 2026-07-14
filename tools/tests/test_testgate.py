"""tools/testgate.py — the four design rules, each pinned by a test.

Fixture-driven: the suite is never actually run. `run_suite` is stubbed with a
synthetic result set, so these are milliseconds and say nothing about the repo's
current state.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import testgate


class GateCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.baseline = Path(tmp.name) / ".test-baseline.json"
        patch = mock.patch.object(testgate, "BASELINE", self.baseline)
        patch.start()
        self.addCleanup(patch.stop)
        sha = mock.patch.object(testgate, "git", lambda *a: "abc123def456")
        sha.start()
        self.addCleanup(sha.stop)

    def write_baseline(self, failures=(), skips=(), sha="abc123def456"):
        self.baseline.write_text(json.dumps({
            "sha": sha, "worktree": False,
            "failures": list(failures), "skips": list(skips),
        }), encoding="utf-8")

    def check(self, results, **kw):
        """Run `check` against a synthetic suite result. Returns (exit, output)."""
        args = mock.Mock(pytest_args=[], affected=False, base_ref="Development",
                         **kw)
        with mock.patch.object(testgate, "run_suite",
                               return_value=(results, 1 if results else 0)):
            with mock.patch("sys.stdout") as out:
                code = testgate.cmd_check(args)
        printed = "\n".join(str(c.args[0]) for c in out.write.call_args_list
                            if c.args and isinstance(c.args[0], str))
        return code, printed


class TestGreenGate(GateCase):
    def test_clean_tree_against_empty_baseline_passes(self):
        self.write_baseline()
        code, out = self.check({})
        self.assertEqual(code, 0)
        self.assertIn("GATE PASS", out)

    def test_a_new_failure_names_exactly_that_test(self):
        self.write_baseline()
        code, out = self.check({"tools/tests/test_boss.py::T::test_x": "FAILED"})
        self.assertEqual(code, 1)
        self.assertIn("GATE FAIL", out)
        self.assertIn("test_boss.py::T::test_x", out)


class TestNodeIdSetSemantics(GateCase):
    """Rule 1: key on the SET of node-ids, not counts. Counts are what drifted."""

    def test_a_known_failure_is_suppressed_not_reported_as_new(self):
        self.write_baseline(failures=["tools/tests/test_a.py::T::test_known"])
        code, out = self.check({"tools/tests/test_a.py::T::test_known": "FAILED"})
        self.assertEqual(code, 0)
        self.assertIn("GATE PASS", out)

    def test_same_COUNT_but_a_different_test_is_still_a_new_failure(self):
        """The exact thing a count-based gate cannot see."""
        self.write_baseline(failures=["tools/tests/test_a.py::T::test_known"])
        code, out = self.check({"tools/tests/test_b.py::T::test_other": "FAILED"})
        self.assertEqual(code, 1)
        self.assertIn("test_b.py::T::test_other", out)

    def test_adding_a_passing_test_does_not_disturb_the_gate(self):
        self.write_baseline(failures=["tools/tests/test_a.py::T::test_known"])
        code, _ = self.check({"tools/tests/test_a.py::T::test_known": "FAILED"})
        self.assertEqual(code, 0)


class TestNewlyFixed(GateCase):
    """Rule 3: report tests that started passing, or the baseline rots."""

    def test_a_repaired_baseline_failure_is_reported(self):
        self.write_baseline(failures=["tools/tests/test_a.py::T::test_known"])
        code, out = self.check({})
        self.assertEqual(code, 0)          # fixing a test is not a gate failure
        self.assertIn("newly FIXED", out)
        self.assertIn("test_a.py::T::test_known", out)

    def test_a_deleted_baselined_test_is_reported_not_crashed(self):
        """A test that no longer exists simply stops failing — same signal."""
        self.write_baseline(failures=["tools/tests/test_gone.py::T::test_x"])
        code, out = self.check({})
        self.assertEqual(code, 0)
        self.assertIn("newly FIXED", out)


class TestUnexpectedSkip(GateCase):
    """Rule 4: an unsanctioned skip is a FAILURE.

    This is the rule that permanently kills the trap TG-2 found: a test class
    that silently skipped inside a worktree, so the gate went green having
    proved nothing.
    """

    def test_an_unexpected_skip_fails_the_gate(self):
        self.write_baseline()
        code, out = self.check(
            {"tools/tests/test_balancing_parity.py::T::test_x": "SKIPPED"})
        self.assertEqual(code, 1)
        self.assertIn("UNEXPECTED SKIP", out)

    def test_a_skip_recorded_in_the_baseline_is_allowed(self):
        self.write_baseline(skips=["tools/tests/test_run_controls.py::T::test_b"])
        code, out = self.check(
            {"tools/tests/test_run_controls.py::T::test_b": "SKIPPED"})
        self.assertEqual(code, 0)
        self.assertIn("GATE PASS", out)


class TestSkipIdentity(unittest.TestCase):
    """A skip is identified by FILE + REASON, never by line number.

    Keying on the line meant that adding an import to the file shifted it, and
    the same sanctioned skip then read as a brand-new unexpected one — the gate
    failed for nothing. That actually happened, on this tool, one commit after
    it was written.
    """

    def parse(self, line):
        results, _ = self._run_with(line)
        return results

    def _run_with(self, line):
        from unittest import mock
        proc = mock.Mock(stdout=line + "\n1 passed\n", stderr="")
        with mock.patch.object(testgate.subprocess, "run", return_value=proc):
            return testgate.run_suite([])

    def test_skip_key_is_file_plus_reason_not_the_line(self):
        at_45 = self.parse(
            "SKIPPED [1] tools/tests/test_a.py:45: a build already exists")
        at_99 = self.parse(
            "SKIPPED [1] tools/tests/test_a.py:99: a build already exists")
        self.assertEqual(list(at_45), list(at_99))
        self.assertEqual(list(at_45), ["tools/tests/test_a.py: a build already exists"])

    def test_a_different_reason_in_the_same_file_is_a_different_skip(self):
        one = self.parse("SKIPPED [1] tools/tests/test_a.py:45: reason one")
        two = self.parse("SKIPPED [1] tools/tests/test_a.py:45: reason two")
        self.assertNotEqual(list(one), list(two))


class TestStaleBaseline(GateCase):
    """Rule 2: a baseline from another commit must say so, not quietly lie."""

    def test_stale_sha_is_announced_on_failure(self):
        self.write_baseline(sha="0000000deadbeef")
        code, out = self.check({"tools/tests/test_a.py::T::test_x": "FAILED"})
        self.assertEqual(code, 1)
        self.assertIn("may be stale", out)


class TestSnapshot(GateCase):
    def test_snapshot_records_failures_skips_and_the_sha(self):
        args = mock.Mock(pytest_args=[])
        results = {"tools/tests/test_a.py::T::test_f": "FAILED",
                   "tools/tests/test_b.py::T::test_s": "SKIPPED"}
        with mock.patch.object(testgate, "run_suite", return_value=(results, 1)):
            with mock.patch("sys.stdout"):
                testgate.cmd_snapshot(args)
        doc = json.loads(self.baseline.read_text(encoding="utf-8"))
        self.assertEqual(doc["failures"], ["tools/tests/test_a.py::T::test_f"])
        self.assertEqual(doc["skips"], ["tools/tests/test_b.py::T::test_s"])
        self.assertEqual(doc["sha"], "abc123def456")
