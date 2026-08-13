"""TestRunPanel — the editor's test-run popup window (TestRunnerPLAN TR-5).

**NO TEST HERE MAY LAUNCH A REAL TEST RUN.** That is the plan's single largest
hazard (`planning/TestRunnerPLAN.md:268-272`): the thing under test starts
pytest, which inside the suite would take minutes, trip the concurrency guard,
and could recurse. So there is no `subprocess`, no `QProcess`, no
`TestRun(...).run()`, and no worker thread started against a real command
anywhere in this file — every case feeds the panel canned tuples / canned
result objects synchronously, and the in-flight case writes a FAKE lock into an
injected tempdir.
"""
import json
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import QtCase

from PySide6.QtWidgets import QPushButton, QToolBar

from editor.main import MainWindow
from editor.panels.test_run_panel import LOCK_STALE_SECONDS, TestRunPanel
from tools.test_domains import DOMAIN_LABELS
from tools.tests.temp_data import TempDataCase

REPO = Path(__file__).resolve().parents[2]
HOOK = REPO / ".claude" / "hooks" / "test_guard.py"


def _domain_result(domain, state="passed", done=3, total=None, passed=3,
                   failed=0, subfailed=0):
    """A canned TR-3 `DomainResult` as a plain dict — the panel reads results
    through accessors that take an object OR a mapping."""
    return {"domain": domain, "state": state, "done": done, "total": total,
            "passed": passed, "failed": failed, "subfailed": subfailed,
            "skipped": 0, "modules": (), "failures": ()}


def _result(domain=None, verdict="pass", gate_line=None, domains=None):
    """A canned TR-3 `RunResult`. `gate_line` is None for a re-run by
    construction — TR-3 guarantees that, and D2 forbids inventing one."""
    return {"domain": domain, "verdict": verdict,
            "gate_line": None if domain is not None else gate_line,
            "completed": True, "cancelled": False,
            "domains": domains or {}}


class _Panel(QtCase):
    """Builds a panel with every seam injected: no clipboard, no explorer, no
    modal, and the guard's state directory pointed at a tempdir."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.state_dir = self.repo / "state"
        self.state_dir.mkdir()
        self.copied = []
        self.detached = []
        self.asked = []
        self.answer = True
        self.requested = []
        self.panel = self.track(TestRunPanel(
            repo=self.repo, state_dir=self.state_dir,
            detach=lambda program, args, cwd: self.detached.append(
                [program, *args]) or True,
            copy_fn=self.copied.append,
            confirm=self._confirm))
        self.panel.run_requested.connect(self.requested.append)

    def _confirm(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def button(self, name):
        for child in self.panel.findChildren(QPushButton):
            if child.objectName() == name:
                return child
        return None

    def write_lock(self, target="py tools/testgate.py check", age=0.0):
        path = self.state_dir / "inflight.json"
        path.write_text(json.dumps(
            {"target": target, "started": time.time() - age, "pid": 4242}),
            encoding="utf-8")
        return path


class TestRows(_Panel):

    def test_one_row_per_domain_with_the_tables_labels(self):
        for domain, label in DOMAIN_LABELS.items():
            self.assertIsNotNone(self.panel.row_text(domain), domain)
            self.assertIsNotNone(self.button(f"rerun:{domain}"), domain)
        # Eight rows, "Tooling & Agents" last (R1) — insertion order IS row
        # order, so the panel must not sort them.
        self.assertEqual(list(self.panel._rows), list(DOMAIN_LABELS))
        labels = [self.panel._rows[k].label.text() for k in DOMAIN_LABELS]
        self.assertEqual(labels, list(DOMAIN_LABELS.values()))

    def test_progress_updates_only_its_own_row(self):
        before = {k: self.panel.row_text(k) for k in DOMAIN_LABELS}
        self.panel.apply_progress("enemies", 12, 40, "running")
        self.assertEqual(self.panel.row_text("enemies"), ("12/40", "running"))
        for key in DOMAIN_LABELS:
            if key != "enemies":
                self.assertEqual(self.panel.row_text(key), before[key], key)

    def test_total_of_none_renders_a_growing_count(self):
        self.panel.apply_progress("map", 7, None, "running")
        self.assertEqual(self.panel.row_text("map"), ("7 run", "running"))
        self.panel.apply_progress("map", 9, None, "running")
        self.assertEqual(self.panel.row_text("map")[0], "9 run")

    def test_out_of_order_domains_both_land(self):
        # --dist loadfile interleaves files across workers; arrival order
        # carries no meaning and the panel must not infer any.
        self.panel.apply_progress("editor", 4, None, "running")
        self.panel.apply_progress("buildings", 2, None, "passed")
        self.assertEqual(self.panel.row_text("editor")[0], "4 run")
        self.assertEqual(self.panel.row_text("buildings"), ("2 run", "passed"))

    def test_an_unknown_domain_surfaces_as_a_new_row(self):
        self.panel.apply_progress("unknown", 1, None, "failed")
        self.assertEqual(self.panel.row_text("unknown"), ("1 run", "FAILED"))


class TestFinishing(_Panel):

    def _report(self):
        path = self.repo / ".claude" / "testruns" / "20260813-101112.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "kind": "gate", "report_path": None, "domain": None,
            "gate_line": "GATE FAIL 2 failed", "verdict": "fail",
            "passed": False, "cancelled": False, "completed": True,
            "unknown_modules": [], "failures": [
                {"nodeid": "tools/tests/test_boss.py::T::t", "params": "",
                 "kind": "failed", "domain": "enemies", "module": "test_boss.py",
                 "message": "boom"}],
        }), encoding="utf-8")
        return path

    def test_finishing_a_failing_run_enables_the_two_buttons(self):
        self.assertFalse(self.panel.copy_button.isEnabled())
        self.assertFalse(self.panel.open_button.isEnabled())
        path = self._report()
        self.panel.apply_finished(
            _result(gate_line="GATE FAIL 2 failed", verdict="fail",
                    domains={"enemies": _domain_result(
                        "enemies", state="failed", failed=2)}),
            path)
        self.assertTrue(self.panel.copy_button.isEnabled())
        self.assertTrue(self.panel.open_button.isEnabled())
        self.assertIn("GATE FAIL", self.panel.gate_label.text())

    def test_copy_agent_prompt_puts_tr4s_text_on_the_injected_sink(self):
        path = self._report()
        self.panel.apply_finished(_result(gate_line="GATE FAIL 2 failed",
                                          verdict="fail"), path)
        self.panel.copy_button.click()
        self.assertEqual(len(self.copied), 1)
        self.assertIn("GATE FAIL 2 failed", self.copied[0])

    def test_open_report_folder_captures_an_argv_naming_the_directory(self):
        path = self._report()
        self.panel.apply_finished(_result(gate_line="GATE PASS"), path)
        self.panel.open_button.click()
        self.assertEqual(len(self.detached), 1)
        self.assertIn(str(path.parent), self.detached[0][-1])

    def test_a_per_area_rerun_never_prints_a_gate_line(self):
        self.panel.begin_run("ui")
        self.panel.apply_finished(_result(
            domain="ui", verdict="fail",
            domains={"ui": _domain_result("ui", state="failed", passed=5,
                                          failed=1)}))
        self.assertNotIn("GATE", self.panel.gate_label.text())
        self.assertNotIn("GATE", self.panel.header_label.text())
        self.assertIn("5 passed, 1 failed", self.panel.gate_label.text())

    def test_a_crashed_run_re_enables_the_controls(self):
        self.panel.begin_run(None)
        self.assertFalse(self.button("rerun:ui").isEnabled())
        self.panel.apply_failed("OSError: pytest is gone")
        self.assertIn("pytest is gone", self.panel.header_label.text())
        self.assertTrue(self.button("rerun:ui").isEnabled())


class TestIntent(_Panel):

    def test_rerun_button_emits_its_domain_and_run_all_emits_none(self):
        self.button("rerun:data").click()
        self.assertEqual(self.requested, ["data"])
        self.panel.run_all_button.click()
        self.assertEqual(self.requested, ["data", None])


class TestInflightWarning(_Panel):

    def test_a_live_lock_warns_and_still_allows(self):
        path = self.write_lock(target="py tools/testgate.py check")
        before = path.read_bytes()
        self.assertTrue(self.panel.request_run(None))
        self.assertEqual(len(self.asked), 1)
        self.assertIn("tools/testgate.py check", self.asked[0][1])
        self.assertEqual(self.requested, [None])
        # D5: the panel takes NO lock of its own and deletes nothing.
        self.assertEqual(path.read_bytes(), before)

    def test_declining_the_warning_starts_nothing(self):
        path = self.write_lock()
        before = path.read_bytes()
        self.answer = False
        self.assertFalse(self.panel.request_run(None))
        self.assertEqual(self.requested, [])
        self.assertEqual(path.read_bytes(), before)

    def test_stale_missing_and_corrupt_locks_do_not_warn(self):
        self.assertIsNone(self.panel.inflight_lock())      # missing
        self.assertTrue(self.panel.request_run(None))
        self.write_lock(age=LOCK_STALE_SECONDS + 60)       # stale
        self.assertIsNone(self.panel.inflight_lock())
        (self.state_dir / "inflight.json").write_text("{not json",
                                                      encoding="utf-8")
        self.assertIsNone(self.panel.inflight_lock())      # corrupt
        self.assertTrue(self.panel.request_run(None))
        self.assertEqual(self.asked, [])

    def test_the_lock_filename_has_not_drifted_in_the_hook(self):
        # The hook is not importable (`.claude/hooks/` is not a package), so
        # this reads it as TEXT. Cheap, launches nothing, and turns "the
        # warning silently never fires again" into a red test.
        text = HOOK.read_text(encoding="utf-8")
        self.assertIn('"inflight.json"', text)
        self.assertIn(f"LOCK_STALE_SECONDS = {LOCK_STALE_SECONDS // 60} * 60",
                      text)


class TestShellWiring(TempDataCase):
    """One MainWindow-level test. The real start path is STUBBED — no thread is
    ever created and no command is ever built."""

    def test_the_run_tests_button_sits_by_thats_my_prod_and_reaches_the_panel(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        window = self.track(MainWindow(
            data_dir=self.data_dir, prefs_path=Path(tmp.name) / ".prefs.json",
            auto_refresh_layouts=False))

        toolbar = window.test_run_button.parent()
        self.assertIsInstance(toolbar, QToolBar)
        self.assertEqual(toolbar.windowTitle(), "Agents")
        # R3: immediately after "thats my prod", not next to the summon button.
        texts = [b.text() for b in toolbar.findChildren(QPushButton)]
        self.assertEqual(texts[texts.index("thats my prod") + 1], "Run tests")

        # Never trigger the real start path: swap the shell's slot for a spy,
        # and point the panel's lock read at an empty tempdir so the click can
        # never open a modal against the session's real in-flight lock.
        started = []
        window.test_run_panel.run_requested.disconnect()
        window.test_run_panel.run_requested.connect(started.append)
        window.test_run_panel._state_dir = Path(tmp.name)
        window.test_run_button.click()

        self.assertEqual(started, [None])
        self.assertTrue(window.test_run_panel.isVisible())
        self.assertIsNone(window._test_thread)   # nothing was spawned


if __name__ == "__main__":
    unittest.main()
