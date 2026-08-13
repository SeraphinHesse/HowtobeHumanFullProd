<!-- active-plan: TestRunnerPLAN.md | set: 2026-08-13 -->
> **Active plan:** TestRunnerPLAN.md (mirror). Source of truth:
> `planning/TestRunnerPLAN.md`. Do **not** edit this file directly — edit the
> source in `planning/` and re-run `/setcurrentplan`, or pick a different
> plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
> screen).

<!-- status: DONE — TR-1–TR-6 all landed on phase-TR-1-TR-6-umbrella -->

# TestRunnerPLAN.md — Run the tests from the editor

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/TestRunnerPLAN.md TR-1-TR-6` or phase-by-phase.

## 1. Vision

A **Run tests** button in the editor toolbar, next to *Summon a Drunken Robot*.
Pressing it runs the exit gate and opens a widget showing one row per area of
the game — Buildings, Enemies, Map, UI, Engine, Editor, Data — each filling in
live as its files complete. When it ends, the widget writes a report an agent
can act on, offers a one-click prompt to paste at one, and a button to open the
report's folder.

The point is to take the gate off Claude's plate. Today the single full run is
the main session's last act before handoff (root `CLAUDE.md`
§"Test Suite Policy"), which means minutes of an agent's wall clock and context
spent on something a human can start and walk away from. After this plan, a
designer can run it themselves, and — because the editor records the result in
the guard's ledger keyed on the working tree — an agent that then reaches for
the gate on an unchanged tree is handed that result instead of running it again.

Two smaller wins fall out. A failure is attributed to an *area of the game*
rather than to a test module nobody outside the suite recognises. And a fix can
be retested against one area in seconds instead of re-running everything.

## 2. Architecture

```
editor (PySide6)                          tools/ (shared, no Qt)
────────────────                          ──────────────────────
main.py  "Run tests" toolbar action       test_domains.py     (new, TR-1)
  └─ TestRunPanel            (new, TR-5)    DOMAINS: file → area
       ├─ one row per domain, live         testguard_ledger.py (new, TR-2)
       ├─ re-run one area                    normalised_target / tree_fingerprint
       ├─ Copy agent prompt                   record_run  ← ONE owner of the key
       └─ Open report folder               testgate.py        (unchanged)
                                           ci_shards.py       (unchanged)
  test_runner.py             (new, TR-3)
    builds the command, streams stdout,  .claude/hooks/
    parses per-file results, emits         test_guard.py  (TR-2: imports the
    progress — pure Python, no Qt                          ledger, drops its
                                                           private copies)
  test_report.py             (new, TR-4)
    writes .claude/testruns/<ts>.json + .md, builds the agent prompt
```

**Flow**: click → warn if a run is already in flight, then launch
`py tools/testgate.py check` in a worker thread → parse the stream, mapping each
finished test file to its domain → rows update live → on completion write the
report, show the gate line, and (full runs only) record the result in the
guard's ledger → *Copy prompt* / *Open folder* / *Re-run this area*.

### Decisions (with rationale)

- **D1 — The domain map is a Python table in `tools/test_domains.py`, with a
  test pinning that every module in `tools/tests/` lands in EXACTLY one
  domain.** Same doctrine as `tools/ci_shards.py`, and chosen for the same
  reason: a table you can import, diff and test beats a convention. There is no
  catch-all domain — a new test file with no entry is a hard error, not a row
  that quietly reads "0 tests". The alternative, deriving the area from the
  filename, breaks silently the first time a file does not fit the pattern, and
  a `data/` JSON file would put build metadata in the game's value store.

- **D2 — The full run shells out to `tools/testgate.py check`; per-area re-runs
  call pytest on that domain's files.** The widget must report the same
  `GATE PASS` / `GATE FAIL` line agents and CI read, including the failure
  shapes testgate learned the hard way (unexpected skips, subtest failures,
  ANSI colour). Re-implementing that parsing in the editor would fork it. A
  re-run of one area is explicitly NOT a gate and the widget must not print one.

- **D3 — One owner of the ledger key: `tools/testguard_ledger.py`.** The gate
  credit in D4 only works if the editor computes byte-identically the same key
  the hook does. Two copies of that logic drift, and the failure is silent in
  the worst direction: the record lands under a key nothing looks up, so the
  feature appears to do nothing. The hook keeps its behaviour and loses its
  private `normalised_target` / `tree_fingerprint`.

- **D4 — A full run from the editor is recorded as a gate run.** Keyed on the
  same working-tree fingerprint, so any edit clears it. It carries a `source`
  field so the guard's message can say the result came from the editor. Only a
  run that COMPLETED and produced a parsed verdict is recorded: a cancelled or
  crashed run records nothing, because a missing record costs one honest re-run
  while a wrong one hides a red suite.

- **D5 — Warn but allow when a run is in flight.** The panel reads the guard's
  lock and shows what is running and when it clears, then lets you start
  anyway; it takes no lock of its own. Deliberately weaker than the agent-side
  rule, because you are a human who can see the machine and an agent is not.
  The warning names the memory contention so the choice is informed.

- **D6 — The run engine is Qt-free (`editor/test_runner.py`), the panel is
  the only Qt.** Keeps the parser testable in the `core` tier instead of the
  slow `editor` tier, and keeps the editor's single-render-path rules (ED-22)
  applying to the widget alone.

- **D7 — Reports live in `.claude/testruns/`, gitignored**, beside
  `.claude/dispatch/`. Same reasoning: agent-facing scratch, never committed.

## 3. Build order

| Phase | What | Package | Depends on | Status |
|---|---|---|---|---|
| TR-1 | Domain map + exactly-one-domain coverage test | tools | — | **done** (`332f3a7`) |
| TR-2 | Extract the ledger key into `tools/testguard_ledger.py` | tools | — | **done** (`84ddc1d`) |
| TR-3 | Qt-free run engine: command build, stream parse, per-domain progress | editor | TR-1 | **done** (`a8d4655`) |
| TR-4 | Report writer + agent prompt | editor | TR-3 | **done** (`9612b04`) |
| TR-5 | Toolbar button + live **popup** + per-area re-run | editor | TR-3, TR-4 | **done** (`7c1562f`) |
| TR-6 | Gate credit: record the editor's full run in the ledger | editor | TR-2, TR-5 | **done** (`b175373`) |

All six landed on `phase-TR-1-TR-6-umbrella`. Orchestrator rulings that amended
this plan during execution are recorded in `docs/briefs/phase-TR-RECONCILE.md`;
the three that changed the design are summarised in §5 below.

---

## TR-1 — Domain map

**Goal.** Every test module in `tools/tests/` belongs to exactly one area of
the game, in a table the editor and anyone else can import.

**Files.**
- new: `tools/test_domains.py` — `DOMAINS: dict[str, tuple[str, ...]]` over
  EIGHT domains: `buildings`, `enemies`, `map`, `ui`, `engine`, `editor`,
  `data`, `tooling`, plus a display label per domain (`DOMAIN_LABELS`, whose
  insertion order is the panel's row order, "Tooling & Agents" last) and
  `domain_for(module) -> str`. The eighth domain holds the ~18 modules that test
  the repo's own scaffolding and developer tooling rather than the game
  (`test_test_guard`, `test_ci_shards`, `test_tiers`, `tools/` script tests…);
  filing them under `data` or `engine` would be a lie in a panel row, and D1
  forbids a catch-all. It is NOT a catch-all: membership is explicit and an
  unmapped module is still a hard error.
- new: `tools/tests/test_test_domains.py`.

**Tests.** Every module in `tools/tests/` is claimed by exactly one domain
(zero is a hard error, two is a hard error — the `ci_shards` rule); every
domain names at least one real, existing file; `domain_for` is exhaustive.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_test_domains.py -q` ·
Quick Test: `py -c "from tools.test_domains import domain_for; print(domain_for('test_boss.py'))"`
prints `enemies`.

---

## TR-2 — One owner of the ledger key

**Goal.** The key that identifies a test run moves out of the hook into a
module the editor can import, with the hook's behaviour unchanged.

**Files.**
- new: `tools/testguard_ledger.py` — `normalised_target`, `tree_fingerprint`,
  `run_key`, `record_run(state_dir, target, outcome, source)`, `state_dir()`.
- modified: `.claude/hooks/test_guard.py` — imports the above, deletes its
  private copies; `post()` calls `record_run`.
- modified: `tools/tests/test_test_guard.py` — a test that the hook and a
  direct `run_key` call agree on the same key for the same command.

**Tests.** The existing guard tests stay green unchanged (they drive the hook
as a subprocess, so they pin the behaviour, not the layout); new: hook and
module agree on the key; `record_run` writes a file the hook's repeat guard
then reads back.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_test_guard.py -q` ·
Quick Test: run any targeted pytest twice in a row in a Claude session — the
second is still denied, with the first one's result quoted.

---

## TR-3 — The run engine

**Goal.** A Qt-free object that launches a run, streams its output, and reports
per-domain progress and results as they arrive.

**Files.**
- new: `editor/test_runner.py` — `build_command(domain=None)`,
  `parse_line(line)`, `TestRun` with callbacks for `on_progress(domain, done,
  total, state)` and `on_finished(result)`; strips ANSI, counts passes,
  failures, subtest failures and unexpected skips per file, maps file → domain
  via TR-1.
- new: `tools/tests/test_editor_test_runner.py`.

**Tests.** Parsing is driven from **canned pytest/testgate output fixtures** —
these tests must never launch a real run (see Risks). Cover: a green run, a run
with a failure, a subtest failure, an unexpected skip, an ANSI-coloured stream,
and output for a file in no known domain (must surface, not vanish).

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_editor_test_runner.py -q` ·
Quick Test: `py -c "from editor.test_runner import build_command; print(build_command()); print(build_command('enemies'))"`
prints the testgate command and a pytest command naming only enemy test files.

---

## TR-4 — Report + agent prompt

**Goal.** A finished run leaves behind something an agent can act on without
being told anything else.

**Files.**
- new: `editor/test_report.py` — `write_report(result) -> Path` producing
  `.claude/testruns/<ts>.json` (gate line, per-domain totals, failing node-IDs,
  tracebacks) and a `.md` beside it; `agent_prompt(path) -> str`.
- new: `tools/tests/test_editor_test_report.py`.
- modified: `.gitignore` — add `.claude/testruns/`.

**Tests.** The report round-trips (write then read gives the same failures);
the JSON carries every failing node-ID; the prompt names the report path and
the failing areas; a green run still writes a report.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_editor_test_report.py -q` ·
Quick Test: write a report from a canned failing result and confirm the `.md`
opens readably and the prompt pastes into a Claude session as a usable task.

---

## TR-5 — The button and the panel

**Goal.** The feature, visible: toolbar button, live rows, per-area re-run,
Copy prompt, Open folder.

**Files.**
- new: `editor/panels/test_run_panel.py` — the widget; one row per domain with
  count, state and a re-run control; elapsed timer; gate line on completion;
  *Copy agent prompt* and *Open report folder*; the in-flight warning (D5).
- modified: `editor/main.py` — the toolbar action beside *Summon a Drunken
  Robot*; the worker thread that drives `TestRun` and marshals its callbacks
  onto the UI thread.
- new: `tools/tests/test_editor_test_run_panel.py` (`editor` tier).
- modified: `editor/CLAUDE.md` and `editor/panels/CLAUDE.md` if the panel adds
  a pattern those docs do not already cover.

**Tests.** The panel builds; feeding it canned progress events updates the
right rows; a failing run enables the copy and open controls; the in-flight
warning appears when a lock file is present and the run still starts on
confirm. Add the module to `TestPurity`. Again: **no real run in a test.**

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_editor_test_run_panel.py -q` ·
Quick Test: open the editor, press **Run tests**, watch the rows fill in live,
let it finish, press *Open report folder* and confirm the report is there.

---

## TR-6 — Gate credit

**Goal.** A green full run from the editor spares an agent from running it
again on the same tree.

**Files.**
- modified: `editor/test_report.py` or `editor/main.py` — on a COMPLETED full
  run only, call `record_run(..., source="editor")`.
- modified: `.claude/hooks/test_guard.py` — the repeat-deny message names the
  source, so an agent reads "this passed 340s ago, from the editor" rather
  than being told it ran something it has no memory of.
- modified: `CLAUDE.md` §"Test Suite Policy" — one line: a full run from the
  editor IS the handoff gate for that tree.
- modified: `tools/tests/test_test_guard.py`.

**Tests.** A recorded editor run denies an agent's subsequent
`py tools/testgate.py check` on the same tree and quotes the result; editing
anything clears it; a cancelled run records nothing; the deny message names the
source.

**Exit gate.** `py tools/smoke.py` ·
`py -m pytest tools/tests/test_test_guard.py -q` ·
Quick Test: run the full suite from the editor, then ask a Claude session to
run the gate — it should be handed your result instead of running.

---

## 4. Risks / open items

- **A test that runs the suite.** The single largest hazard here: the thing
  under test launches pytest. Every phase's tests drive canned output, never a
  real run. A test that shells out to testgate would take minutes inside the
  suite, trip the concurrency guard, and could recurse. If a phase cannot be
  tested without a real run, the phase is wrong.
- **A wrong ledger record is worse than none.** D4 hides a real gate run from
  an agent. It is keyed on the tree fingerprint so any edit clears it, and only
  a completed, parsed run is recorded — but this is the one place where a bug
  costs correctness rather than time. TR-6's tests are the guard on it.
- **Live progress needs a total per domain before the run starts.** pytest
  reports counts as it goes, not up front. Either collect first
  (`--collect-only`, an extra pass of a few seconds) or show a count that grows
  rather than a fraction. TR-3 decides; TR-5 must not depend on a total
  existing.
- **`--dist loadfile` reorders output.** Files finish out of order and
  interleave across workers. The parser must key on the node-ID in each line,
  never on position in the stream.
- **The editor tier is most of the wall clock.** The panel will spend most of a
  full run on one row. Consider ordering rows so the fast ones resolve first,
  and showing which shard-heavy files are still going.
- **Open: does the button need a "skip the editor tier" escape?** Deliberately
  not in scope — a partial run that looks like a gate is the failure mode this
  repo has already had once. Revisit only if the full run proves too slow to
  use.

Test policy for every phase above is root `CLAUDE.md` §"Test Suite Policy" and
nothing else. The single full `py tools/testgate.py check` happens ONCE, in the
main session, at handoff — never inside a phase.

---

## 5. What changed during execution

Three design decisions were taken by the user mid-run, plus two corrections.
Full detail and rationale: `docs/briefs/phase-TR-RECONCILE.md`.

- **`tools/testgate.py` is no longer "unchanged" (R2).** TR-3 measured that D2
  was mechanically impossible as written: testgate runs pytest under
  `subprocess.run(capture_output=True)` (`:119-120`) and with `-q` (`:110`), so
  it emits nothing until the run ends and its live output carries no node-IDs —
  "shell out to testgate" and "rows fill in live" could not both hold. testgate
  gained a **strictly additive `--stream` mode**: with the flag it runs pytest
  `-v`, line-buffered, echoing as it goes; without it, behaviour is byte-
  identical to before. The verdict logic is shared, not forked, so the streamed
  run still prints the same authoritative `GATE` line. This is also what makes
  TR-6 honest — without it there would be no real gate line on an editor run.
- **There are EIGHT domains, not seven (R1).** ~18 modules test the repo's own
  scaffolding rather than the game, and D1 forbids a catch-all, so they get an
  explicit `tooling` domain labelled **"Tooling & Agents"**, last in row order.
- **The panel is a POPUP WINDOW, not a dock (R3)**, following
  `editor/thats_my_producer.py`, and its button sits next to *thats my prod* on
  the Agents toolbar — not next to *Summon a Drunken Robot* as §TR-5 said.
- **`Failure.kind` has three values, not four (R9)** — `failed | subfailed |
  unexpected_skip`. An `ERROR` test buckets as `failed`, mirroring testgate.
- **TR-6 additionally captures the tree fingerprint at run START and FINISH and
  records nothing if they differ (R5.1).** Not in the original plan; it follows
  from "a wrong ledger record is worse than none". `GATE ABORT` is likewise not
  credited — an abort means testgate refused to run, so crediting it would
  suppress the real gate.
