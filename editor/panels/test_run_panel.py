"""The test-run POPUP WINDOW (TestRunnerPLAN TR-5, reconciliation R3).

A pure VIEW. It renders one row per test domain, an elapsed clock, a gate line
and two after-the-run buttons — and it does none of the work: no subprocess, no
stream parsing, no pytest vocabulary, no thread. `editor/test_runner.py` (TR-3)
owns the run and the parse, `editor/test_report.py` (TR-4) owns the report, and
`editor/main.py` owns the worker thread and is the ONLY caller of this panel's
``apply_*`` methods. That split is what lets the whole panel be driven
synchronously from canned tuples in a test — the plan's hardest rule is that
NOTHING in the suite may launch a real test run.

Four things here are load-bearing:

1. **A POPUP WINDOW, NOT A DOCK** (R3). `editor/thats_my_producer.py` is the
   shape copied: a widget parented to the main window so it dies with it, given
   ``Qt.WindowType.Window`` so it floats as its own non-modal window, with the
   shell holding the one reference. The editor stays usable while a run goes.

2. **THE ROW LIST IS DERIVED, NEVER HARDCODED.** Rows come from
   ``tools.test_domains.DOMAIN_LABELS`` in its insertion order (that IS the row
   order — TR-1 keeps no separate ordering table). A domain the panel has no row
   for is APPENDED, never dropped: a stray test module that vanishes from the
   panel looks exactly like success.

3. **``total`` MAY BE ``None``** — a full run has no up-front count, so the
   count label COUNTS UP rather than rendering a fraction it does not have.
   ``done`` is passed+failed+subfailed+skipped (TR-3's ``DomainResult``), so it
   is rendered as "N run", not "N passed".

4. **A PER-AREA RE-RUN IS NOT A GATE** (D2). ``RunResult.gate_line`` is already
   ``None`` for one, and this panel never writes the token ``GATE`` itself — it
   only ever echoes a line TR-3 read out of testgate's own output.

Injection seams, and why each exists (all mirror existing editor precedent):

* ``repo`` — where `.claude/testruns/` lives, so tests never touch the real one.
* ``state_dir`` — the guard's state directory, resolved LAZILY through TR-2's
  ``tools.testguard_ledger.state_dir()``. A test passes a tempdir and writes a
  FAKE ``inflight.json`` into it; that is the only sanctioned way to exercise
  the D5 warning. The panel reads that file and writes NOTHING under there.
* ``detach`` — ``run_controls.start_detached``, so *Open report folder* is
  captured as argv in tests and no explorer opens (`editor/CLAUDE.md`).
* ``copy_fn`` — the clipboard setter, so *Copy agent prompt* is assertable
  without an offscreen clipboard.
* ``confirm`` — ``(title, text) -> bool``, so the in-flight warning never
  ``exec()``s a modal in a test.

ED-22: this is CHROME. Stock widgets only — no ``paintEvent``, no ``QPainter``,
no ``pygame.Surface``, no ``Renderer``. It draws no game content.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor import plans, run_controls, test_report
from tools.test_domains import DOMAIN_LABELS

REPO = Path(__file__).resolve().parents[2]

#: The guard's in-flight lock, inside `testguard_ledger.state_dir()`. Kept as a
#: constant because a test asserts this exact spelling still appears in
#: `.claude/hooks/test_guard.py` — the hook is not importable, so a rename there
#: would otherwise silently turn the warning off forever.
INFLIGHT_FILENAME = "inflight.json"

#: Matches `.claude/hooks/test_guard.py`'s LOCK_STALE_SECONDS. A lock older than
#: this is IGNORED, exactly as the hook ignores it.
LOCK_STALE_SECONDS = 20 * 60

#: Elapsed-clock tick. A QTimer, never a busy loop (editor/panels/CLAUDE.md).
TICK_MS = 500

#: FAILED red — hardcoded, and legible on both the light and the dark chrome
#: theme (editor/CLAUDE.md §Theme, last bullet).
_FAIL_STYLE = "color: #d13438; font-weight: bold;"
_PASS_STYLE = "color: #107c10; font-weight: bold;"
_IDLE_STYLE = ""

_STATE_TEXT = {
    "pending": "pending",
    "running": "running",
    "passed": "passed",
    "failed": "FAILED",
}


def _elapsed_text(seconds):
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


class _DomainRow:
    """One domain's three labels + its Re-run button. Plain holder, no logic."""

    def __init__(self, domain, label, count, state, button):
        self.domain = domain
        self.label = label
        self.count = count
        self.state = state
        self.button = button


class TestRunPanel(QWidget):
    """The run window. Emits intent; renders what it is handed."""

    #: Not a test class — the name only starts with "Test" because the FEATURE
    #: does. Without this pytest tries to collect it and warns on every import.
    __test__ = False

    #: domain key, or None for a full run. Emitted only AFTER the in-flight
    #: check passes — the warning is the panel's business, the thread is the
    #: shell's.
    run_requested = Signal(object)

    def __init__(self, repo=None, state_dir=None, detach=None, copy_fn=None,
                 confirm=None, parent=None):
        super().__init__(parent)
        self._repo = Path(repo) if repo is not None else REPO
        self._state_dir = Path(state_dir) if state_dir is not None else None
        self._detach = detach or run_controls.start_detached
        self._copy_fn = copy_fn or self._clipboard_set
        self._confirm = confirm or self._ask
        self._report_path = None
        self._running = False
        self._started_monotonic = None

        # R3: its own non-modal top-level window, parented to the shell so it
        # dies with it (thats_my_producer.py's shape).
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowTitle("Tests")
        self.resize(560, 420)

        outer = QVBoxLayout(self)

        head = QHBoxLayout()
        self.header_label = QLabel("Idle")
        self.header_label.setObjectName("test_run_header")
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("test_run_elapsed")
        head.addWidget(self.header_label, 1)
        head.addWidget(self.elapsed_label, 0)
        outer.addLayout(head)

        self._rows = {}
        self._grid = QGridLayout()
        outer.addLayout(self._grid)
        # DERIVED, never hardcoded: insertion order IS row order (TR-1).
        for domain, label in DOMAIN_LABELS.items():
            self._add_row(domain, label)

        self.gate_label = QLabel("")
        self.gate_label.setObjectName("test_run_gate")
        self.gate_label.setWordWrap(True)
        outer.addWidget(self.gate_label)

        outer.addStretch(1)

        buttons = QHBoxLayout()
        self.run_all_button = QPushButton("Run all tests")
        self.run_all_button.setObjectName("run_all")
        self.run_all_button.clicked.connect(lambda: self.request_run(None))
        self.copy_button = QPushButton("Copy agent prompt")
        self.copy_button.setObjectName("copy_agent_prompt")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self._on_copy_prompt)
        self.open_button = QPushButton("Open report folder")
        self.open_button.setObjectName("open_report_folder")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._on_open_folder)
        buttons.addWidget(self.run_all_button)
        buttons.addStretch(1)
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.open_button)
        outer.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_MS)
        self._timer.timeout.connect(self._tick)

    # -- rows ---------------------------------------------------------------

    def _add_row(self, domain, label=None):
        row = len(self._rows)
        name = QLabel(label or str(domain))
        count = QLabel("—")
        state = QLabel(_STATE_TEXT["pending"])
        button = QPushButton("Re-run")
        # The objectName convention row buttons already use, so a test can find
        # WHICH row is re-runnable without walking the layout by index.
        button.setObjectName(f"rerun:{domain}")
        button.clicked.connect(lambda _=False, d=domain: self.request_run(d))
        button.setEnabled(not self._running)
        self._grid.addWidget(name, row, 0)
        self._grid.addWidget(count, row, 1)
        self._grid.addWidget(state, row, 2)
        self._grid.addWidget(button, row, 3)
        entry = _DomainRow(domain, name, count, state, button)
        self._rows[domain] = entry
        return entry

    def _row(self, domain):
        """The row for `domain`, APPENDING one for a key TR-1 does not know.

        Domain drift must SURFACE. TR-3 already refuses to let an unmapped test
        module vanish; silently ignoring its key here would undo that.
        """
        entry = self._rows.get(domain)
        if entry is None:
            entry = self._add_row(domain, test_report.label_for(domain))
        return entry

    def row_text(self, domain):
        """`(count, state)` for one row — the tests' read seam."""
        entry = self._rows.get(domain)
        if entry is None:
            return None
        return entry.count.text(), entry.state.text()

    def _set_row(self, domain, done, total, state):
        entry = self._row(domain)
        if total:
            entry.count.setText(f"{done}/{total}")
        else:
            # No up-front total on a full run — COUNT UP, never a fraction.
            # `done` is every finished test, not just the passing ones.
            entry.count.setText(f"{done} run")
        entry.state.setText(_STATE_TEXT.get(state, str(state)))
        entry.state.setStyleSheet(
            _FAIL_STYLE if state == "failed"
            else _PASS_STYLE if state == "passed" else _IDLE_STYLE)

    # -- the result contract: ONE private accessor per field ----------------
    #
    # TR-3 owns `RunResult`. Every assumption about its shape is confined to
    # these four functions so a contract change is a handful of lines.

    @staticmethod
    def _field(obj, name, default=None):
        if obj is None:
            return default
        value = (obj.get(name, default) if isinstance(obj, dict)
                 else getattr(obj, name, default))
        return default if value is None else value

    def _result_domain(self, result):
        """The re-run's domain, or None for a full run (== "this is a gate")."""
        if result is None:
            return None
        return (result.get("domain") if isinstance(result, dict)
                else getattr(result, "domain", None))

    def _result_gate_line(self, result):
        """testgate's verbatim verdict line, or None. NEVER derived here, and
        TR-3 already guarantees None for a re-run (D2)."""
        if self._result_domain(result) is not None:
            return None
        line = (result.get("gate_line") if isinstance(result, dict)
                else getattr(result, "gate_line", None))
        return line or None

    def _result_domains(self, result):
        return self._field(result, "domains", {}) or {}

    # -- view updates (UI thread only) --------------------------------------

    def begin_run(self, domain=None):
        """A run just started. `domain is None` => a full run.

        A per-area re-run leaves every OTHER row untouched, so it reads as
        "this area got retested", not "everything else was forgotten".
        """
        self._running = True
        self._report_path = None
        self._started_monotonic = time.monotonic()
        self.gate_label.setText("")
        self.header_label.setText("Running…")
        self.header_label.setStyleSheet(_IDLE_STYLE)
        targets = list(self._rows) if domain is None else [domain]
        for key in targets:
            entry = self._row(key)
            entry.count.setText("—")
            entry.state.setText(_STATE_TEXT["pending"])
            entry.state.setStyleSheet(_IDLE_STYLE)
        self._set_controls_enabled(False)
        self.elapsed_label.setText("0:00")
        self._timer.start()

    def apply_progress(self, domain, done, total, state):
        """One `(domain, done, total, state)` tuple from TR-3, verbatim.

        Order is never inferred from arrival: `--dist loadfile` interleaves
        files across workers, so tuples arrive out of order by design.
        """
        self._set_row(domain, done, total, state)

    def apply_finished(self, result, report_path=None):
        """The run ended. `report_path` is TR-4's `.json`, or None if none."""
        self._running = False
        self._timer.stop()
        self._tick()
        self._report_path = Path(report_path) if report_path else None

        for key, dom in self._result_domains(result).items():
            self._set_row(key, self._field(dom, "done", 0),
                          (dom.get("total") if isinstance(dom, dict)
                           else getattr(dom, "total", None)),
                          self._field(dom, "state", "pending"))

        gate_line = self._result_gate_line(result)
        if gate_line:
            self.gate_label.setText(gate_line)
        else:
            self.gate_label.setText(self._neutral_summary(result))
        verdict = str(self._field(result, "verdict", "error"))
        self.header_label.setText(self._headline(result, verdict))
        self.header_label.setStyleSheet(
            _PASS_STYLE if verdict == "pass" else _FAIL_STYLE)
        self._set_controls_enabled(True)

    def apply_failed(self, message):
        """The run crashed or never produced a verdict. No report was written."""
        self._running = False
        self._timer.stop()
        self.header_label.setText(f"Run failed: {message}")
        self.header_label.setStyleSheet(_FAIL_STYLE)
        self._set_controls_enabled(True)

    def _headline(self, result, verdict):
        domain = self._result_domain(result)
        if self._field(result, "cancelled", False):
            return "Cancelled — no verdict."
        if domain is not None:
            return f"Re-ran {test_report.label_for(domain)} — not a gate."
        gate_line = self._result_gate_line(result)
        return gate_line or f"Finished — {verdict}."

    def _neutral_summary(self, result):
        """What the gate line's slot says when there is no gate line.

        A re-run gets the neutral "<label>: n passed, m failed" shape and must
        never contain the token GATE (D2).
        """
        domain = self._result_domain(result)
        if domain is None:
            return ""
        dom = self._result_domains(result).get(domain)
        passed = self._field(dom, "passed", 0)
        failed = (self._field(dom, "failed", 0)
                  + self._field(dom, "subfailed", 0))
        return (f"{test_report.label_for(domain)}: {passed} passed, "
                f"{failed} failed (re-run, not a gate)")

    def _set_controls_enabled(self, enabled):
        self.run_all_button.setEnabled(enabled)
        for entry in self._rows.values():
            entry.button.setEnabled(enabled)
        has_report = bool(enabled and self._report_path)
        self.copy_button.setEnabled(has_report)
        self.open_button.setEnabled(has_report)

    def _tick(self):
        if self._started_monotonic is None:
            return
        self.elapsed_label.setText(
            _elapsed_text(time.monotonic() - self._started_monotonic))

    # -- the in-flight lock (D5: warn and ALLOW, take no lock) --------------

    def lock_path(self):
        """The guard's lock file. Resolved through TR-2's `state_dir()` — never
        re-derived, and the hook itself is never imported (`.claude/hooks/` is
        not an importable package)."""
        if self._state_dir is None:
            from tools.testguard_ledger import state_dir
            self._state_dir = Path(state_dir())
        return self._state_dir / INFLIGHT_FILENAME

    def inflight_lock(self):
        """The live lock as a dict, or None. Missing/corrupt/stale => None.

        Mirrors the hook: a lock past LOCK_STALE_SECONDS is ignored, and an
        unreadable one is "nothing running", never an error. This method only
        READS — the panel writes nothing under the guard's state directory.
        """
        try:
            lock = json.loads(self.lock_path().read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(lock, dict) or not lock:
            return None
        try:
            age = time.time() - float(lock.get("started", 0))
        except (TypeError, ValueError):
            return None
        if not 0 <= age < LOCK_STALE_SECONDS:
            return None
        return lock

    def _inflight_text(self, lock):
        started = float(lock.get("started", 0))
        clears = time.strftime("%H:%M:%S",
                               time.localtime(started + LOCK_STALE_SECONDS))
        return (
            "A test run is already in flight:\n\n"
            f"    {lock.get('target', '?')}\n\n"
            f"The guard's block on it clears at {clears}.\n"
            "Two concurrent runs exhaust memory and make both slower, which "
            "then reads as a flaky suite.\n\n"
            "Start a second run anyway?")

    def _ask(self, title, text):
        answer = QMessageBox.question(
            self, title, text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    # -- intent -------------------------------------------------------------

    def request_run(self, domain=None):
        """Ask the shell to start a run. Returns whether it was requested.

        Nothing here may raise out of a Qt slot: every failure degrades to a
        header message (editor/panels/CLAUDE.md, `_on_add_requested`).
        """
        try:
            if self._running:
                return False
            lock = self.inflight_lock()
            if lock and not self._confirm("A test run is already in flight",
                                          self._inflight_text(lock)):
                return False
            self.run_requested.emit(domain)
            return True
        except Exception as exc:  # pragma: no cover - defensive
            self.header_label.setText(f"Could not start the run: {exc}")
            return False

    # -- the two after-the-run buttons --------------------------------------

    def report_dir(self):
        """Where *Open report folder* points: the written report's directory,
        else `.claude/testruns/` under the injected repo."""
        if self._report_path is not None:
            return self._report_path.parent
        return test_report.testruns_dir(self._repo)

    @staticmethod
    def _clipboard_set(text):
        app = QApplication.instance()
        clipboard = app.clipboard() if app is not None else None
        if clipboard is not None:
            clipboard.setText(text)

    def _on_copy_prompt(self):
        if self._report_path is None:
            return
        try:
            self._copy_fn(test_report.agent_prompt(self._report_path,
                                                   repo=self._repo))
        except Exception as exc:
            self.header_label.setText(f"Could not copy the prompt: {exc}")

    def _on_open_folder(self):
        """Reveal the report directory. `plans.reveal_command` is the ONE
        folder-open path in the editor — never re-implemented here (the argv
        split mirrors `spawnclaude.open_planning_folder`)."""
        try:
            argv = plans.reveal_command(self.report_dir())
            self._detach(argv[0], argv[1:], self._repo)
        except Exception as exc:
            self.header_label.setText(f"Could not open the folder: {exc}")
