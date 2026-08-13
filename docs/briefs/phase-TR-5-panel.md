# Phase TR-5 — The button and the panel

Source plan: `planning/TestRunnerPLAN.md` §"TR-5 — The button and the panel"
(`planning/TestRunnerPLAN.md:211-235`). Depends on TR-3 (`editor/test_runner.py`)
and TR-4 (`editor/test_report.py`). TR-6 layers on top of this phase's
`editor/main.py` changes.

Package: **editor**. Read `editor/CLAUDE.md` and `editor/panels/CLAUDE.md`
before you touch anything; this brief assumes both.

---

## 1. Behavioral spec

### 1.1 The toolbar button

A **"Run tests"** `QAction` sits on the existing **Agents** toolbar, immediately
after *Summon a Drunken Robot*.

- The Agents toolbar is created at `editor/main.py:333` (`agents_toolbar =
  self.addToolBar("Agents")`); the *Summon a Drunken Robot* action is added at
  `editor/main.py:334-336` and a `addSeparator()` follows at
  `editor/main.py:340`. **Insert the new action between line 336 and line 340**
  — i.e. inside the pre-separator group, so it reads as a sibling of the summon
  button and not of the theme/settings chrome (`editor/main.py:378-386`).
- Copy the action idiom verbatim from `editor/main.py:334-336`: construct
  `QAction(...)`, `agents_toolbar.addAction(...)`, `triggered.connect(...)`.
- The button label is **"Run tests"**. (The summon button's label is fixed by
  `editor/CLAUDE.md` §"Agent dispatch"; nothing constrains this one, but do not
  invent a second name for it anywhere in the code or docs.)

Pressing it:
1. Reads the guard's in-flight lock; if a run is live, shows the warning
   (§1.5) and proceeds only on confirmation.
2. Shows the Tests dock (§1.2) and starts a **full** run (`build_command()`
   with no domain, TR-3).
3. While a run is in flight, the action is **disabled** and a second press is
   impossible. This mirrors `RunControls`' one-tracked-process rule — a second
   `build()` is refused, not queued (`editor/CLAUDE.md` §"Run controls", and
   `editor/main.py:1052-1062` for the enable/disable dance around
   `_on_build_started`/`_on_build_finished`).

### 1.2 The panel

New `TestRunPanel` (`editor/panels/test_run_panel.py`), hosted in a
`QDockWidget("Tests", self)` in the **bottom** dock area, beside the existing
Console dock (`editor/main.py:289-293`). It is hidden at construction and shown
on the first run.

Contents, top to bottom:

**a. A header line** — the run's state (`Idle` / `Running…` / the gate line) and
an **elapsed timer** (`m:ss`), updated by a `QTimer` on a ~500 ms interval.
Never a busy loop: `editor/main.py:81` (`FRAME_INTERVAL_MS`) and
`editor/main.py:318-321` (the debounce `QTimer`) are the house precedents; the
panels doc pins "Frames driven by a `QTimer`, never a busy loop"
(`editor/panels/CLAUDE.md:31-32`). Elapsed is computed from `time.monotonic()`
captured at run start, so a clock change cannot make it run backwards.

**b. One row per domain**, in the order `tools.test_domains` declares them
(TR-1). **Never a hardcoded domain list in this file** — the same doctrine that
killed the editor's `DOMAINS` constant for balancing domains
(`editor/panels/CLAUDE.md:211-217`: "The domain list is DERIVED, never
hardcoded … do not re-introduce a list"). Each row carries:
   - the domain's **display label** (from TR-1's table, not `str.title()` of the
     key);
   - a **count** label: `"<done> passed"`, or `"<done>/<total>"` when TR-3
     supplies a total. **The panel must render correctly when `total is None`**
     — `planning/TestRunnerPLAN.md:277-281` states TR-3 may legitimately have no
     up-front total, and "TR-5 must not depend on a total existing";
   - a **state** label: `pending` / `running` / `passed` / `FAILED`, driven by
     the `state` string TR-3 emits;
   - a **"Re-run"** `QPushButton` carrying `objectName` `rerun:<domain>` — the
     `objectName` convention the panels doc already uses for row buttons and
     prev-era labels (`editor/panels/CLAUDE.md:76-78`, `:135-137`) so a test can
     assert *which* rows are re-runnable without walking the layout by index.
     Disabled while any run is in flight.

**c. A gate line** label, filled on completion of a **full** run only, with the
verdict string TR-3 parsed (`GATE PASS` / `GATE FAIL …`). A **per-area re-run
must never print a gate line** — plan D2 (`planning/TestRunnerPLAN.md:68-73`):
"A re-run of one area is explicitly NOT a gate and the widget must not print
one." For a domain re-run this label shows the neutral shape
`"<label>: <n> passed, <m> failed"` (or stays blank), never anything containing
the token `GATE`.

**d. Two buttons**, both disabled until a run has finished and written a report:
   - **Copy agent prompt** — puts `test_report.agent_prompt(report_path)` (TR-4)
     on the clipboard.
   - **Open report folder** — reveals the report's directory
     (`.claude/testruns/`, plan D7 `planning/TestRunnerPLAN.md:100-101`) in the
     OS file manager.

### 1.3 Live updates

Rows fill in as results arrive, **not** in stream order: pytest runs under
`--dist loadfile` (`pytest.ini`), so files finish out of order and interleave
across workers (`planning/TestRunnerPLAN.md:283-285`). The panel therefore only
ever *applies* the `(domain, done, total, state)` tuples TR-3 hands it and
never infers ordering, position or completeness from the sequence it sees.

A domain TR-3 reports that the panel has no row for (TR-1 domain drift) must be
**surfaced**, not dropped — append a row labelled with the raw key. The plan's
TR-3 tests already demand "output for a file in no known domain (must surface,
not vanish)" (`planning/TestRunnerPLAN.md:179-180`); the panel must not undo
that by silently ignoring an unknown key.

### 1.4 Per-area re-run

`rerun:<domain>` starts a run of that one domain via TR-3's
`build_command(domain)`. It goes through the **same** start path as the full
run (same in-flight check, same worker, same disabling), differing only in:
- no gate line (§1.2c);
- TR-6 will not record it (§3.4);
- rows for other domains keep their previous values rather than resetting to
  `pending`, so a re-run reads as "this area got retested" and not "everything
  else was forgotten".

### 1.5 The in-flight warning (D5 — warn and allow, take no lock)

Plan D5 (`planning/TestRunnerPLAN.md:89-93`): "The panel reads the guard's lock
and shows what is running and when it clears, then lets you start anyway; **it
takes no lock of its own**."

- **Where the lock is.** `.claude/hooks/test_guard.py:284-285`:
  `def _lock_path(): return _state() / "inflight.json"`. `_state()` is the
  guard's per-worktree state directory, resolved through `git rev-parse
  --git-dir` → `<git-dir>/testguard`, with a `TESTGUARD_STATE_DIR` env override
  and a repo-keyed temp-dir fallback (`.claude/hooks/test_guard.py:56-99`).
- **How the panel gets it.** Through TR-2's `tools/testguard_ledger.state_dir()`
  — never by re-deriving the git-dir path, and never by importing the hook
  (`.claude/hooks/` is not an importable package). Plan D3
  (`planning/TestRunnerPLAN.md:76-80`) makes that module the one owner.
- **What it reads.** The lock JSON's `target` (the command that is running) and
  `started` (epoch seconds); staleness is `started + LOCK_STALE_SECONDS`
  (`.claude/hooks/test_guard.py:108`, 20 min) — the same clock the hook's own
  message quotes (`.claude/hooks/test_guard.py:406-434`). A lock older than that
  is **ignored**, exactly as the hook ignores it. A missing or unparseable lock
  file is "nothing running", never an error (mirror the hook's `_read_json`
  swallow-and-return-`{}` at `.claude/hooks/test_guard.py:288-292`).
- **What it shows.** A `QMessageBox` naming (i) what is running, (ii) the clock
  time the guard's block clears, and (iii) the memory contention — plan D5's
  "The warning names the memory contention so the choice is informed"; root
  `CLAUDE.md` §"Test Suite Policy" states duplicate runs exhaust memory. Yes
  starts the run; No cancels it.
- **What it must NOT do.** Write, delete or touch `inflight.json` or anything
  else under the guard's state directory. Deleting that file is explicitly
  forbidden by root `CLAUDE.md` §"Test Suite Policy"; the editor is not exempt.
  (TR-6 will write to the guard's *ledger*, a different file, and only through
  `record_run`.)

### 1.6 Failure and shutdown behaviour

- A run that **crashes** (the subprocess dies, TR-3 raises) shows the error text
  in the header, re-enables the toolbar action and the re-run buttons, and
  writes no report. Plan D4 (`planning/TestRunnerPLAN.md:82-87`) already fixes
  that a cancelled or crashed run records nothing; the panel must make that
  state visible rather than sitting at "Running…" forever.
- Closing the editor with a run in flight must not crash. See §2.4.
- Nothing in this panel may raise out of a Qt slot. The editor has two written
  precedents that an exception inside a Qt event handler can abort the process
  (`editor/panels/CLAUDE.md:262-264` for the selector's context menu;
  `editor/main.py:1096-1099` for `_on_add_requested`'s `QMessageBox.critical`
  guard). Every callback here degrades to a status message, never a traceback.

---

## 2. Architecture plan

### 2.1 Layering — what lives where

```
editor/main.py                 (Qt shell: action, dock, worker thread, slots)
  └─ editor/panels/test_run_panel.py   (Qt: rows, timer, buttons — NO threads,
                                        NO subprocess, NO parsing)
editor/test_runner.py  (TR-3)  Qt-free: builds the command, runs it, parses
editor/test_report.py  (TR-4)  Qt-free: writes the report, builds the prompt
tools/test_domains.py  (TR-1)  the domain table + labels
tools/testguard_ledger.py (TR-2) state_dir() — the lock's directory
```

Plan D6 (`planning/TestRunnerPLAN.md:95-98`) is the governing rule: **the run
engine is Qt-free and the panel is the only Qt.** So:

- `test_run_panel.py` contains **no** `subprocess`, no stream parsing, no
  `GATE` string construction, and no knowledge of pytest's output format. It
  renders tuples it is given and emits intent signals.
- The thread lives in `editor/main.py`, not in the panel. The panel stays a
  dumb view that a test can drive synchronously by calling its apply-methods —
  which is what makes CRITICAL §4's "canned progress events, never a real run"
  achievable at all.

### 2.2 Panel API (the seam the tests drive)

```python
class TestRunPanel(QWidget):
    run_requested = Signal(object)      # domain key, or None for a full run

    def __init__(self, repo=None, state_dir=None, detach=None,
                 copy_fn=None, confirm=None, parent=None): ...

    # -- view updates, ALL called on the UI thread only --------------------
    def begin_run(self, domain): ...          # domain None => full run
    def apply_progress(self, domain, done, total, state): ...
    def apply_finished(self, result, report_path): ...
    def apply_failed(self, message): ...

    # -- reads --------------------------------------------------------------
    def inflight_lock(self): ...              # dict | None (fresh locks only)
```

Injection points, and why each exists (all follow existing editor precedent):

- **`repo`** — the report directory and the lock live under the repo; every
  editor module is injectable so tests never touch the real tree
  (`editor/panels/CLAUDE.md:46-48`, the `data_dir` rule; `prefs_path` in
  `editor/main.py:94` is the non-`data_dir` instance of the same idea).
- **`state_dir`** — the guard's state directory. Defaults to
  `testguard_ledger.state_dir()`. **A test passes a tempdir and writes a fake
  `inflight.json` into it.** This is the ONLY sanctioned way to test §1.5.
- **`detach`** — defaults to `run_controls.start_detached`, used with
  `plans.reveal_command(<report dir>)` for *Open report folder*. This is a
  straight copy of `spawnclaude.open_planning_folder`
  (`editor/spawnclaude.py:127-138`), including the argv split into
  `program, arguments`; `plans.reveal_command` (`editor/plans.py:71-82`) is the
  ONE folder-open path in the editor and must not be re-implemented here. Tests
  capture the argv and no explorer opens (`editor/CLAUDE.md:252-254`).
- **`copy_fn`** — defaults to `QApplication.clipboard().setText`. Injected so a
  test asserts the prompt text without depending on an offscreen clipboard.
- **`confirm`** — a callable `(title, text) -> bool`, defaulting to a
  `QMessageBox.question`. Injected so the in-flight test never `exec()`s a
  modal. Precedent: `DetailsPanel.clear_entry(confirm=False)` and the selector's
  build/display split, both recorded as the test path in
  `editor/panels/CLAUDE.md:250-252` and `:314-317`.

The panel emits `run_requested(domain)` **after** the in-flight check passes —
i.e. the warning is the panel's business, the thread is the shell's.

### 2.3 The worker thread and signal marshalling

`editor/main.py` gains a small `_TestRunWorker(QObject)`:

```python
class _TestRunWorker(QObject):
    progress = Signal(str, int, object, str)   # domain, done, total|None, state
    finished = Signal(object)                  # TR-3 result object
    failed   = Signal(str)
```

Mechanics, in order:

1. `MainWindow._on_run_tests(domain)` constructs a `QThread` and a
   `_TestRunWorker` holding a TR-3 `TestRun`, `worker.moveToThread(thread)`,
   connects `thread.started -> worker.run`, and `thread.start()`.
2. Inside the worker thread, `TestRun` invokes its plain-Python callbacks
   `on_progress` / `on_finished`. **Those callbacks may do exactly one thing:
   `emit` a signal.** They must never touch a widget, a `QLabel`, the panel, or
   the status bar. Qt widgets are not thread-safe and a cross-thread widget
   write is the classic intermittent-crash bug.
3. The marshalling is **Qt's automatic queued delivery**: `worker.progress` is
   connected to `MainWindow._on_test_progress` with the default
   `AutoConnection`. Because the emitter's thread affinity (the worker thread)
   differs from the receiver's (the GUI thread), Qt queues the emission onto the
   GUI thread's event loop and invokes the slot there. That is the whole
   mechanism — **do not** hand-roll it with `QMetaObject.invokeMethod`, a
   `QTimer.singleShot(0, ...)`, or a mutex-guarded buffer, and **do not** force
   `Qt.DirectConnection` on these connections (that would run the slot on the
   worker thread and reintroduce the cross-thread widget write).
4. `MainWindow._on_test_progress/_on_test_finished/_on_test_failed` run on the
   GUI thread and are the ONLY callers of `TestRunPanel.apply_*`.
5. Guard every `emit` with `shiboken6.isValid(self)` — the same guard
   `RunControls` uses for exactly this hazard (`editor/run_controls.py:25`, and
   `editor/CLAUDE.md` §"Run controls": "Guards with `shiboken6.isValid(self)`
   before emitting").
6. On `finished`/`failed`, the shell quits the thread, `deleteLater()`s the
   worker, clears `self._test_thread = None`, re-enables the toolbar action and
   the panel's re-run buttons.

**Why a thread and not a tracked `QProcess`.** `RunControls` streams Build's
output through a tracked `QProcess` on the GUI thread
(`editor/CLAUDE.md` §"Run controls"), and that would be the cheaper pattern —
but it would put the stream parsing on the Qt side, forking the one parser TR-3
owns (plan D2/D6, `planning/TestRunnerPLAN.md:68-73`, `:95-98`). One parser,
driven from a worker thread, is the deliberate trade. Note for the implementer:
there is **no existing `QThread` anywhere in `editor/`** (verified: no match for
`QThread|threading|invokeMethod|QueuedConnection` under `editor/`), so this is a
new pattern in the package — which is why §3.5 requires the panels doc to record
it.

### 2.4 Shutdown

`MainWindow.closeEvent` (and the test harness's `destroy()`, which really frees
the C++ object — `tools/tests/qt_harness.py:31-44`) must not leave a `QThread`
running. Add: request cancel on the worker, `thread.quit()`, `thread.wait(ms)`
with a bounded timeout. A live `QThread` whose `QObject`s are being deleted is
the same class of bug as the "Signal source has been deleted" crash the run
controls hit with a tracked long-lived `QProcess` (`editor/run_controls.py:7-13`).

### 2.5 ED-22 — how the single-render-path rule applies here

ED-22 bans a **second render path for game content**: the viewport draws through
`engine/render` into an embedded surface, and QPainter never draws tiles
(`editor/panels/CLAUDE.md:10-13`; `editor/CLAUDE.md` §"Hard rules").

`TestRunPanel` is **chrome**, in the same sense the theme is chrome
(`editor/CLAUDE.md` §"Theme": "Chrome only — the viewport keeps drawing through
`engine/render` (ED-22); a theme switch must never reach into how game content is
rendered"). Concretely, ED-22 obliges this phase to:

- build the panel from **stock Qt widgets only** — `QLabel`, `QPushButton`,
  `QGridLayout`/`QVBoxLayout`. No `paintEvent`, no `QPainter`, no `QImage`;
- construct **no** `pygame.Surface`, `AssetStore`, `CoordinateSystem` or
  `Renderer`. The two sanctioned second-`Renderer` cases (`sheet_preview.py`,
  `vfx_preview.py` — `editor/CLAUDE.md` §"VFX preview") exist because they draw
  *game content*; this panel draws none, so it needs neither the exception nor
  the argument for it;
- keep any hardcoded colour (a red FAILED label, a green PASS) legible on
  **both** themes, or read it from the palette — the panel-local-colour rule at
  `editor/CLAUDE.md` §"Theme", last bullet.

---

## 3. File scope + shared-file contract

### 3.1 Files you may touch

| File | New/Mod | What |
|---|---|---|
| `editor/panels/test_run_panel.py` | **new** | The widget (§1.2, §2.2) |
| `editor/main.py` | mod | Toolbar action, Tests dock, `_TestRunWorker`, three slots, `closeEvent` join |
| `tools/tests/test_editor_test_run_panel.py` | **new** | §4 tests, `editor` tier |
| `conftest.py` | mod | ONE line in `TIERS` (§3.3) |
| `tools/tests/test_editor_viewport.py` | mod | ONE token in `TestPurity` (§3.3) |
| `tools/test_domains.py` | mod | ONE entry (§3.3) |
| `editor/panels/CLAUDE.md` | mod | §3.5 |
| `editor/CLAUDE.md` | mod | §3.5 |

Nothing else. In particular: do not touch `editor/test_runner.py`,
`editor/test_report.py`, `tools/testguard_ledger.py`, `tools/testgate.py`,
`.claude/hooks/test_guard.py`, or `tools/ci_shards.py`.

### 3.2 What TR-5 CONSUMES (TR-3 and TR-4)

**`docs/briefs/phase-TR-3-run-engine.md` and `docs/briefs/phase-TR-4-report.md`
do not exist at the time of writing** (verified: no `phase-TR-*` file in
`docs/briefs/`). The contract below is therefore **assumed**, derived from the
plan text, and is the thing to reconcile first if those briefs have since
landed. If they disagree with this section, **the TR-3/TR-4 briefs win** — adapt
the call sites and report the divergence; do not edit those modules.

Assumed from `planning/TestRunnerPLAN.md:163-186` (TR-3):

- `build_command(domain=None) -> list[str]` — the full testgate command when
  `domain is None`, else a pytest command naming only that domain's files.
- `TestRun` — constructed with a command plus `on_progress` and `on_finished`
  callbacks; has a blocking `run()`-style entry point and some form of cancel.
- `on_progress(domain, done, total, state)` — `total` may be `None`
  (`planning/TestRunnerPLAN.md:277-281`); `state` is a short string.
- `on_finished(result)` — `result` carries at minimum the gate line, per-domain
  totals, and the failing node-IDs (implied by TR-4's report contents,
  `planning/TestRunnerPLAN.md:194-197`), plus enough to answer "did this run
  complete and produce a parsed verdict" (plan D4) and "was this a full run".

Assumed from `planning/TestRunnerPLAN.md:188-207` (TR-4):

- `write_report(result) -> Path` — writes `.claude/testruns/<ts>.json` and a
  `.md` beside it; returns one of those paths.
- `agent_prompt(path) -> str`.

**If a needed attribute is absent from TR-3's result**, do NOT add it to
`editor/test_runner.py` and do NOT recompute it in the panel by re-parsing.
Derive what you can from what exists, and report the gap — a second parser in
the panel is the exact drift D2/D6 exist to prevent.

**Panel-side isolation from this uncertainty:** `TestRunPanel.apply_finished`
takes the result object and reads it through **one** private accessor per field
(e.g. `_gate_line(result)`, `_is_full_run(result)`), each defensive against a
missing attribute. That confines every TR-3-shape assumption to a handful of
lines the next phase can correct in one place.

### 3.3 Shared files — exact insertion points

**`conftest.py` — `TIERS`.** A module missing from `TIERS` is a hard error, not
a silent skip (`conftest.py:6-19`). Add, in the `# --- editor:` block
(`conftest.py:52-68`), keeping its alphabetical-ish grouping:

```python
    "test_editor_test_run_panel": "editor",   # TestRunnerPLAN TR-5
```

`tools/ci_shards.py` needs **no** edit — the `editor-rest` shard selects by
marker (`tools/ci_shards.py:70-72`), so a new editor-tier file is picked up for
free, and it must NOT be added to `HEAVY_EDITOR_FILES`
(`tools/ci_shards.py:43-48`).

**`tools/tests/test_editor_viewport.py` — `TestPurity`.** Every new editor
module goes into that import list (`editor/CLAUDE.md` §"Hard rules";
`editor/panels/CLAUDE.md:12-13`). The list is the `code` string at
`tools/tests/test_editor_viewport.py:1492-1528`; add
`editor.panels.test_run_panel` to it (the `editor.panels.vfx_preview` line at
`:1518` is the natural neighbour). `editor.main` is already in that list
(`tools/tests/test_editor_viewport.py:1494`), so the shell change needs nothing
further.

**`tools/test_domains.py` (TR-1) — the domain table.** TR-1's own test asserts
every module in `tools/tests/` is claimed by **exactly one** domain, and that
"zero is a hard error" (`planning/TestRunnerPLAN.md:118-129`). Adding
`tools/tests/test_editor_test_run_panel.py` without an entry therefore turns
TR-1's test red. Add `"test_editor_test_run_panel.py"` to the **`editor`**
domain's tuple, and nowhere else. This is the one edit outside `editor/` this
phase makes; keep it to that single tuple entry.

### 3.4 The TR-6 insertion point (name it, do not build it)

TR-6 records a completed full run in the guard's ledger
(`planning/TestRunnerPLAN.md:239-252`). Its single call site is:

> **`MainWindow._on_test_finished(self, result)` in `editor/main.py`, in the
> body immediately after `report_path = test_report.write_report(result)` and
> before `self.test_run_panel.apply_finished(result, report_path)`.**

TR-5 must leave that method with:
- the write and the apply as two separate statements in that order (no
  `apply_finished(result, write_report(result))` one-liner — TR-6 needs a
  statement boundary between them);
- a `# TR-6: record_run(..., source="editor") goes here` comment on that
  boundary, naming the two conditions TR-6 will gate on (plan D4): the run
  **completed with a parsed verdict**, and it was a **full** run, not a domain
  re-run;
- the "was this a full run" question answerable from `_on_test_finished`'s own
  scope — store the requested domain on the worker/shell at start
  (`self._test_domain`) rather than making TR-6 dig it back out of `result`.

TR-5 itself calls **no** ledger function and imports `tools.testguard_ledger`
**only** for `state_dir()` (§1.5). Writing a ledger record from this phase would
put a gate credit behind a code path TR-6's tests do not yet cover, and plan §4
names a wrong ledger record as the one bug here that costs correctness rather
than time (`planning/TestRunnerPLAN.md:272-276`).

### 3.5 Docs to update

- **`editor/panels/CLAUDE.md`** — a new section for this panel. It must record:
  (a) the panel is a pure view, all threading lives in `main.py`; (b) the
  derived-not-hardcoded domain row list; (c) the `rerun:<domain>` `objectName`
  convention; (d) the `state_dir`/`detach`/`copy_fn`/`confirm` injection seams
  and *why* each exists (so tests never open a modal, an explorer or a real
  run); (e) that a per-area re-run never prints a gate line.
- **`editor/CLAUDE.md`** — a short bullet under a Testing/Run heading: the
  worker-thread pattern (§2.3), the auto-queued-connection marshalling rule, and
  the hard rule that a worker callback may only `emit`. This is the package's
  **first** `QThread`, so it belongs in the router doc, not only the panels doc.
- Do NOT touch the root `CLAUDE.md` — the §"Test Suite Policy" line about an
  editor run counting as the gate is **TR-6's** edit
  (`planning/TestRunnerPLAN.md:250-251`), and it is not true until TR-6 lands.

---

## 4. Exit gate + Quick Test

### 4.1 The gate (run these, exactly these)

```bash
py tools/smoke.py
py -m pytest tools/tests/test_editor_test_run_panel.py -q
py -m pytest tools/tests/test_editor_viewport.py -q
```

The second `test_editor_viewport.py` run is because this phase edits that file's
`TestPurity` list (§3.3).

**Do not run anything wider.** No full suite, no `py tools/testgate.py check`,
no `--affected`, no `-m editor` / `-m core` / `-m meta` tier sweep. You are a
subagent; root `CLAUDE.md` §"Test Suite Policy" is the only authority on this
and a `PreToolUse` hook (`.claude/hooks/test_guard.py`) **denies** all four from
a subagent — asking for one produces a denied command, not a check. The single
full gate belongs to the main session at handoff. This overrides anything wider
in the plan doc.

The gate is **ZERO** failures. `GATE PASS` on `smoke.py`, green on both pytest
files, or you are not done.

### 4.2 What the new test file must cover — **and the hard rule**

> **CRITICAL: no test in this phase may launch a real test run.**
> `planning/TestRunnerPLAN.md:267-272` names this the single largest hazard of
> the whole plan: "the thing under test launches pytest… would take minutes
> inside the suite, trip the concurrency guard, and could recurse."
> `tools/tests/test_editor_test_run_panel.py` must contain **no**
> `subprocess`, no `QProcess`, no `TestRun(...).run()`, no `pytest` or
> `testgate` in any argv it actually executes, and must never start the worker
> thread against a real command.

Everything is driven by calling the panel's `apply_*` methods directly with
canned tuples on the test's own thread.

Required cases:

1. **It builds.** `TestRunPanel` constructs under the offscreen harness and has
   one row per `tools.test_domains` domain, with the table's display labels.
   Subclass `QtCase` and wrap it: `self.track(TestRunPanel(...))` —
   `tools/tests/qt_harness.py:53-62`; `close()` is not cleanup
   (`editor/CLAUDE.md` §"Testing the editor", rule 1).
2. **Canned progress updates the right rows.** Feed
   `apply_progress("enemies", 12, 40, "running")` and assert the *enemies* row's
   count and state changed and every other row did not.
3. **A `total` of `None` renders.** `apply_progress("map", 7, None, "running")`
   does not raise and shows a growing count
   (`planning/TestRunnerPLAN.md:277-281`).
4. **Out-of-order domains.** Two `apply_progress` calls for different domains,
   second one first — both rows are correct (`--dist loadfile` reordering,
   `planning/TestRunnerPLAN.md:283-285`).
5. **A failing run enables the controls.** `apply_finished(<canned failing
   result>, <tmp report path>)` enables *Copy agent prompt* and *Open report
   folder*, which are disabled before it.
6. **Copy prompt.** With an injected `copy_fn`, clicking *Copy agent prompt*
   passes the string TR-4's `agent_prompt` returns for that path.
7. **Open report folder.** With an injected `detach`, clicking it captures an
   argv naming the report's directory. No explorer opens
   (`editor/CLAUDE.md:252-254`).
8. **A per-area re-run prints no gate line.** After a domain re-run finishes,
   the gate label contains no `GATE` token (plan D2).
9. **`rerun:<domain>` emits `run_requested` with that domain**, and
   `run_requested(None)` for the full-run entry point.
10. **The in-flight warning — with a FAKE lock file.** Construct the panel with
    `state_dir=<tempdir>`; write a JSON `inflight.json` into it by hand with
    `started = time.time()` and a `target` string. Assert: the injected
    `confirm` was called, its text names the target; returning `True` still
    emits `run_requested` (warn **and allow**, D5); returning `False` emits
    nothing. **Assert the lock file is byte-identical afterwards** — the panel
    takes no lock and deletes nothing (§1.5).
11. **A stale lock is ignored.** Same fake file with
    `started = time.time() - 21*60` (past `LOCK_STALE_SECONDS`,
    `.claude/hooks/test_guard.py:108`) → no warning, run proceeds. A missing
    file and a corrupt file likewise → no warning, no exception.
12. **The lock filename has not drifted.** Read `.claude/hooks/test_guard.py`
    as text and assert the panel's lock-filename constant appears in it (the
    hook's `_lock_path` at `:284-285`). Cheap, no run, and it turns a silent
    "the warning never fires again" into a red test.
13. **The shell wires up.** One `MainWindow`-level test (tracked, offscreen,
    `data_dir=<temp copy>`, `auto_refresh_layouts=False`,
    `prefs_path=<temp>` — the injection set at `editor/main.py:91-94` and
    `editor/CLAUDE.md` §"Screen mode" UH-2 bullet): the "Run tests" action
    exists on the Agents toolbar, and triggering it with a **stubbed** start
    method records the request without spawning a thread. Never trigger the
    real start path.

Keep the test file to the bare minimum that pins these behaviours — no coverage
padding.

### 4.3 Quick Test (in-game / in-editor; the orchestrator or the user runs this,
not you)

1. `py editor/main.py`.
2. The Agents toolbar shows **Run tests** immediately right of *Summon a Drunken
   Robot*.
3. Press it. The Tests dock appears; rows for Buildings, Enemies, Map, UI,
   Engine, Editor, Data are listed; the elapsed timer ticks.
4. Rows fill in live as areas complete — the fast ones resolve well before the
   editor row (`planning/TestRunnerPLAN.md:286-288`).
5. On completion the gate line appears and matches what `tools/testgate.py`
   prints.
6. Press **Open report folder** — `.claude/testruns/` opens and contains a
   fresh `<ts>.json` + `<ts>.md`.
7. Press **Copy agent prompt** and paste it somewhere — it names the report path
   and the failing areas.
8. Press one row's **Re-run**: only that area re-runs, in seconds, and **no gate
   line is printed** for it.
9. While a Claude session is mid-test-run, press **Run tests**: the warning
   names what is running and when it clears; *Yes* starts anyway, *No* does not.
   Afterwards, the agent's run is unaffected — the editor took no lock.

---

## Open questions for the orchestrator

1. **TR-3/TR-4 briefs are absent.** §3.2's contract is inferred from the plan
   text. If TR-3 lands with a different `TestRun` shape (e.g. it owns its own
   thread, or exposes an iterator rather than callbacks), §2.3's worker collapses
   to something smaller — reconcile before dispatching this phase.
2. **`tools/test_domains.py` is edited by this phase** (one tuple entry, §3.3).
   The plan's TR-5 file list does not mention it, but TR-1's exactly-one-domain
   test makes it mandatory. Same for `conftest.py`'s `TIERS`. Confirm those two
   one-line edits are in scope rather than TR-1's problem.
3. **Dock vs. tab.** This brief puts the Tests panel in its own bottom
   `QDockWidget` beside the Console. Tabifying it with the Console instead is a
   one-line change; nobody has stated a preference.
