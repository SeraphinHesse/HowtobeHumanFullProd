# TR-1…TR-6 — Orchestrator reconciliation

**This file OVERRIDES the individual phase briefs.** Read your own brief first
(`docs/briefs/phase-TR-<id>-*.md`), then this. Where they differ, **this wins**.
Every ruling below either answers an open question a planner raised or resolves a
contradiction between two briefs.

Umbrella branch: `phase-TR-1-TR-6-umbrella`. Plan: `planning/TestRunnerPLAN.md`.

---

## R1 — There is an eighth domain: `tooling` (TR-1)

**User ruling.** The plan names seven domains; ~13 modules in `tools/tests/` test
agent scaffolding, not the game (`test_test_guard`, `test_ci_shards`,
`test_tiers`, `test_agent_forms`, `test_fixture_guard`, `test_orient_hook`,
`test_qt_harness`, `test_smoke_pairing`, `test_spawnclaude`, `test_testgate`,
`test_build_script`, `test_data_guard`, plus the new modules TR-1/TR-3/TR-4/TR-5
add). D1 forbids a catch-all, so they get their own domain.

- key `tooling`, display label **"Tooling & Agents"**
- it is the **eighth** row, last in `DOMAIN_LABELS` insertion order
- it is NOT a catch-all: a module with no entry is still a hard error. Membership
  is explicit, like every other domain.
- TR-1 additionally amends `planning/TestRunnerPLAN.md:122-124` to name eight
  domains, so TR-3 and TR-5 inherit the right row list.

## R2 — `tools/testgate.py` gets a `--stream` mode, and TR-3 owns it

**User ruling, and the largest change to the plan.** TR-3 measured that D2 is
mechanically impossible as written: `tools/testgate.py:119-120` runs pytest under
`subprocess.run(capture_output=True)` (nothing is emitted until the run ends) and
`:110` passes `-q` (live output is bare dots, no node-IDs). "Shell out to
testgate" and "rows fill in live" cannot both hold with that file unchanged.

The resolution is a streaming mode on testgate itself — **one** run that is both
live and authoritative. This supersedes the plan's `testgate.py (unchanged)` at
`planning/TestRunnerPLAN.md:40`.

**Scope: TR-3.** Its file scope gains `tools/testgate.py` and
`tools/tests/test_testgate.py`.

Hard constraints on that edit — `testgate.py` is load-bearing for CI, for every
agent's handoff gate, and for the `test_guard` hook:

1. **Strictly additive.** Without `--stream`, `testgate.py` must behave
   byte-identically to today: same flags, same capture, same output, same exit
   codes. The existing `tools/tests/test_testgate.py` cases must pass unmodified
   — if one needs editing to stay green, you have changed the default path and
   the edit is wrong.
2. With `--stream`: run pytest with `-v` instead of `-q`, line-buffered, echoing
   each line to stdout as it arrives, while still accumulating the full output.
3. **The verdict logic is untouched and unforked.** After the stream ends,
   testgate parses exactly as it does now and prints the same authoritative
   `GATE PASS` / `GATE FAIL` line, with the same failure shapes (unexpected
   skips, `SUBFAILED` subtests, ANSI) and the same exit code.
4. Add tests for `--stream` to `tools/tests/test_testgate.py`: lines are emitted
   incrementally, and the final gate line + exit code match the non-stream run
   over the same canned pytest output. **Drive canned output — never a real run.**

**Consequence for TR-3's own module:** `build_command()` returns the testgate
command **with `--stream`**. TR-3's separate `build_stream_command()` is
therefore NOT needed — drop it. Per-area re-runs still call pytest directly and
still produce **no** gate line (D2: a re-run is not a gate).

**Consequence for TR-6:** TR-3's open question 2 is closed. A full editor run
now yields a real testgate `GATE` line, so ledger credit records a verdict
testgate actually pronounced. Options (a) two-pass and (c) editor-computed
verdicts are both rejected. **TR-6 must record only when `gate_line` is present
and testgate-sourced**; if it is `None`, record nothing.

## R3 — The panel is a POPUP WINDOW, not a dock (TR-5)

**User ruling.** TR-5's brief left dock-vs-tabbed open; the answer is neither.

- The panel opens as a **separate popup window**, following the existing pattern
  in `editor/thats_my_producer.py::show_thats_my_producer` — read that file and
  copy its shape (window flags, parenting, lifetime, non-modal behaviour).
- The launch control is a **toolbar button next to "thats my prod"**, i.e.
  immediately after `producer_btn` on `agents_toolbar`
  (`editor/main.py:384-386`), NOT next to *Summon a Drunken Robot* as the plan
  and TR-5's brief say. This supersedes `planning/TestRunnerPLAN.md:220-221` and
  TR-5's §3 toolbar insertion point at `editor/main.py:336-340`.
- Non-modal: the editor stays usable while a run is going.
- Everything else in TR-5's brief stands — one row per domain (now eight), live
  updates, elapsed timer, gate line on completion, *Copy agent prompt*, *Open
  report folder*, the D5 in-flight warning (warn and allow, take no lock).
- Dock-specific parts of TR-5's brief (dock widget, dock area, tabify) do not
  apply. ED-22 and the worker-thread marshalling rules still do.

## R4 — TR-3 owns the `result` contract; TR-4 and TR-5 adapt

TR-4 and TR-5 were both written before TR-3's brief existed and each states an
*assumed* result shape. **TR-3's brief is the contract.** Both confined their
assumptions to a single accessor (TR-4's `_get(obj, name, default)`; TR-5's
one private accessor per field) — that is exactly right; correct those accessors
against TR-3's actual definition and change nothing else.

Because coders run in dependency order (see R6), TR-3's `editor/test_runner.py`
is **already on disk** when TR-4 and TR-5 start. Read it. Do not guess.

Same rule for TR-1's API: `DOMAINS`, `DOMAIN_LABELS`, `domain_for`,
`modules_for` will exist when TR-3 starts — read the real signatures. TR-3's
open question 3 (does `domain_for` raise or return `None`?) is answered by the
file, not by assumption; keep the `"unknown"` bucket for unmapped modules either
way, since it must surface rather than vanish.

## R5 — TR-6 rulings (all its open questions, answered)

1. **Approved, and it is required:** capture `tree_fingerprint()` at run start
   AND at finish; if they differ, **record nothing**. This is not in the plan;
   it follows from "a wrong ledger record is worse than none"
   (`planning/TestRunnerPLAN.md:273-276`). A tree edited mid-run makes both
   candidate keys wrong.
2. **Call site: `editor/test_report.py`** (not `editor/main.py`), for core-tier
   testability per D6. Confirmed.
3. **`source` tokens: `"agent"` for hook-recorded runs, `"editor"` for editor
   runs.** TR-2 defaults to `"agent"`; TR-6 keys its message wording off
   `"editor"`. `record.get("source")` for back-compat with pre-TR-6 records.
4. **Yes, record `GATE FAIL` too** — any completed, parsed verdict is recorded.
   The repeat guard already routes failures to "fix the code first"
   (`.claude/hooks/test_guard.py:463-464`).
5. **Approved:** TR-6 may append the "cancelled records nothing" and "per-area
   re-run records nothing" cases to `tools/tests/test_editor_test_report.py`.
   Append only — do not restructure TR-4's tests.
6. **No speculative credit for non-canonical spellings** (`python tools/...`,
   backslash paths). Confirmed as briefed.
7. The root `CLAUDE.md` §"Test Suite Policy" line stays **TR-6's** job, as the
   plan says. One line, prose, after the "runs exactly ONCE" bullet
   (`CLAUDE.md:49-51`).

## R6 — Execution is SEQUENTIAL, in dependency order

Coders run one at a time in this order — **not** concurrently:

    TR-1 ─┐
          ├─ TR-3 ── TR-4 ── TR-5 ── TR-6
    TR-2 ─┘

Every phase branches off the umbrella and merges back before the next starts, so
each coder sees its dependencies' real code on disk. The append-only insertion
points the planners negotiated for the shared files therefore hold without
worktree isolation:

| Shared file | Phases | Rule |
|---|---|---|
| `tools/tests/conftest.py` (`TIERS`) | TR-1, TR-3, TR-4, TR-5 | one line per new test module; append. A module missing from `TIERS` is a HARD ERROR (`conftest.py:19`), not a skip. |
| `tools/tests/test_editor_viewport.py` (`TestPurity`) | TR-3, TR-4, TR-5 | one line per new **editor** module; append to the list at `:1492-1528`. `editor.main` is already there. |
| `tools/test_domains.py` | TR-1 creates; TR-3/TR-4/TR-5 append | every new test module needs an entry or TR-1's exactly-one-domain test fails. New test modules for this feature go in `tooling`. |
| `.claude/hooks/test_guard.py` | TR-2, TR-6 | TR-2 extracts the key logic; TR-6 rewords the deny message. |
| `tools/tests/test_test_guard.py` | TR-2, TR-6 | append. |
| `editor/test_report.py` | TR-4 creates; TR-6 adds the `record_run` call | TR-4 leaves a marker comment before its single `return path`. |
| `editor/main.py` | TR-5 | TR-6 no longer touches it (R5.2 moves the call site to `test_report.py`). |
| `tools/testgate.py` | TR-3 only | see R2. |

## R7 — Test budget (binding on every coder)

Root `CLAUDE.md` §"Test Suite Policy" is the authority and **overrides the plan
doc and your brief**. As a subagent your gate is:

    py tools/smoke.py
    py -m pytest tools/tests/test_<file>.py -q     # only files you touched

**Never** the full suite, **never** `py tools/testgate.py check`, **never**
`--affected`, **never** a tier sweep (`-m core` / `-m editor` / `-m meta`). The
`test_guard.py` hook denies all four from a subagent.

**A denied test run is a REPORT, never a retry.** Do not re-issue it, do not vary
the flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
fingerprints identically), and do not reach for the guard's escape hatch. Report
the deny text and the result it quotes, and stop testing. Two denies are expected
and must not be fought:

- *"already ran this exact target and NOTHING has changed"* — accept the quoted
  earlier result. If it was a FAIL you believe you have since fixed, say exactly
  that in your report and let the orchestrator verify at the umbrella.
- *"another test run is already in flight"* — do not wait-loop, do not delete the
  lock. Report and stop.

Watch the trap TR-2 and TR-6 both found: **any bash command containing the bare
token `pytest`, `testgate` or `unittest` is classified as a test run** by
`.claude/hooks/test_guard.py:123` — even `cat pytest.ini`. Route Quick-Test
probes through a scratchpad script whose command line contains none of those
words.

**No test may launch a real test run.** This is the plan's single largest hazard
(`planning/TestRunnerPLAN.md:268-272`). Every phase drives canned
pytest/testgate output or canned result objects. If a phase seems to need a real
run to be tested, the phase is wrong — stop and report.

## R8 — Not your job

- Do not push, do not open a PR, do not merge. The orchestrator does that.
- Do not run the full gate. It runs ONCE, from the main session, on the finished
  umbrella.
- Do not edit `planning/TestRunnerPLAN.md` except where R1 explicitly assigns it
  to TR-1.
- Do not edit another phase's files. Your brief's §3, as amended here, is a hard
  boundary.
