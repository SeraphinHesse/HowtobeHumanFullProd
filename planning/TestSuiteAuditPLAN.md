<!-- status: NOT STARTED — 0/7 phases -->
<!-- plan-scale: large -->

# TestSuiteAuditPLAN.md — Is the test suite worth what it costs?

Phased, agent-executable plan (same family as `TestRunnerPLAN.md` /
`MIGRATION_PLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/TestSuiteAuditPLAN.md TS-1-TS-6` or
phase-by-phase.

**This plan is allowed to conclude "delete most of it."** It is an audit, not a
defence. The owner has proposed tossing the suite and CI altogether on the
grounds that (a) tests go red from ordinary designer behaviour and (b) when a
test fails it is usually the test that is wrong, not the game. Both claims are
empirically testable, and phases TS-1–TS-3 test them before anything is
deleted or defended. An executing agent that finds the owner is right must say
so plainly and size the deletion.

## 1. Vision

The suite protects the project or it taxes it. Right now nobody knows which,
because the argument has only ever been had in anecdotes. This plan replaces
the anecdotes with numbers, then rebalances the suite around one distinction:

> **An invariant test** asserts something that must be true for the game to
> work at all — data validates against schema, layering holds, the game boots,
> nothing crashes, a pathfinder terminates.
>
> **A value test** asserts a number a designer chose — this enemy has 240 HP,
> this heatmap alpha is 0.35, this roster has 8 entries.

Value tests are the ones that go red when a designer does their job. They are
also the ones with the worst catch-rate, because a wrong number is visible in
the game in seconds while a broken invariant is not. The end state is a suite
that is **mostly invariant tests, deliberately few value tests**, with every
surviving value test justified in writing.

The owner's time is the scarce resource, not correctness. A test that costs
more designer-hours in maintenance than it has ever saved in caught bugs gets
deleted, and the plan says so in those terms.

### The measured starting position (main session, 2026-08-13)

All figures **measured** unless tagged otherwise.

| Quantity | Value | How |
|---|---|---|
| Test files | 133 | `ls tools/tests/*.py \| wc -l` |
| Test functions | 2406 | `grep -c "def test_"` |
| Test LOC | 42,553 | `wc -l tools/tests/*.py` |
| Production LOC (`engine`/`game`/`editor`) | 49,103 | `wc -l` |
| Test-to-production LOC ratio | **0.87 : 1** | derived |
| Assertions pinning a bare numeric literal | **883** | `grep -oE "assert[A-Za-z]*\([^)]*, *[0-9]+...` |
| Test files touching `balancing` | 47 | `grep -rl` |
| …of those, using `TempDataCase` | 24 | `grep -rl` |
| **Test files reading balancing WITHOUT the temp fixture** | **34** | `comm -23` |
| Test-only commits in the last 300 | 22 | `git log` classification |
| …whose message is explicitly "the test was wrong" | ~10 | reading the 22 messages |

Two of these are the whole argument:

- **883 numeric-literal assertions across 2406 tests.** Roughly one test in
  three pins a number. Every one of those is a designer edit away from red.
- **34 test files read balancing data without the temp fixture.** These are the
  ones that break when the owner changes a value in the editor — which is
  exactly the "natural designer behaviour" complaint, and it is not a
  perception problem.

The ~10-of-22 test-only-commit figure is the second complaint, also confirmed:
`Fix test_tile_conditions.py's stale heatmap alpha pin`, `test_ui_min_targets:
read the pinned fixture, not live data/`, `Make the suite green by stating the
premises it was silently assuming`, `Derive the spec-less category in the
selector context-menu test`, and six siblings are all *the test was wrong*.

### What is NOT wrong (do not "fix" these)

- **The CI red on 2026-08-13 was billing, not tests.** Every job on every
  branch failed in 3–4 s with zero steps and this annotation: *"The job was not
  started because recent account payments have failed or your spending limit
  needs to be increased."* The last genuine CI result (`Large Plans`, 12:08)
  was **green**. Any agent executing this plan must not treat that red as
  evidence about the suite. It is evidence about the GitHub bill.
- **The sharding, the concurrency guard, and the ZERO gate** are all sound and
  were each written to fix a specific, documented misreading. Do not undo them
  as part of "simplifying". If sharding goes, it goes because CI goes.

## 2. Architecture decisions

- **D1 — The audit produces a per-file verdict table, committed.**
  `docs/test-audit.md`, one row per test file: category (invariant / value /
  mixed), designer-fragility score from TS-2, catch-rate evidence from TS-3,
  verdict (KEEP / CONVERT / DELETE), and one sentence of justification. This
  file is the deliverable other phases act on. No test is deleted without a row
  naming why.
- **D2 — Fragility is measured by perturbation, not by reading.** TS-2 mutates
  balancing values the way a designer would and counts what goes red. Reading
  a test and guessing whether it is fragile is exactly how the current
  situation was reached.
- **D3 — Catch-rate is measured from git history, not from memory.** A test
  earns its keep by having failed *before* a production fix at least once. TS-3
  mines this; tests with zero historical catches and non-zero maintenance cost
  are DELETE candidates by default.
- **D4 — CONVERT beats DELETE where the invariant survives the number.** A test
  pinning `enemy.hp == 240` usually wants to assert *"hp is a positive number
  the schema accepts and combat consumes"*. Converting keeps the protection and
  drops the fragility. Deletion is for tests where nothing survives.
- **D5 — Value tests that survive move behind a designer-facing gate.** The few
  numbers that genuinely must not drift (BASE_HP = 10, the ×10 combat scale)
  get asserted in ONE place against `data/` as the source of truth, not
  re-pinned in 30 files.
- **D6 — CI's future is a separate decision from the suite's, and it is the
  owner's.** TS-6 prices CI and presents options; it does not unilaterally
  delete the workflow. Billing is now a hard constraint and must be in the
  numbers.

### The live gate result (main session, 2026-08-13, HEAD `7cf468d`)

One full `py tools/testgate.py check` was run. **Measured:**

```
GATE FAIL  4 problem(s)
  NEW FAILURE  test_details_panel.py::TestConditionTintCheckbox::test_unticking_removes_the_key_on_resave
  NEW FAILURE  test_editor_map_mode.py::TestKeybindShortcuts::test_tool_action_switches_tool
  NEW FAILURE  test_editor_panels.py::TestSettingsDialog::test_undo_redo_swap_updates_shortcuts_and_persists
  NEW FAILURE  test_editor_viewport.py::TestPurity::test_editor_does_not_import_game
```

**All four pass in isolation** (verified — re-run individually, 4/4 green).
So on the day the owner proposed deleting the suite, the suite's entire
contribution was four failures, none of which was a game defect. That is not a
rhetorical point; it is the strongest single datum in this document.

`TestPurity::test_editor_does_not_import_game` is the instructive one: it
asserts a **real and valuable** invariant (the layering rule), and it does so in
a **subprocess**, so in-process state pollution cannot explain it. A subprocess
assertion that fails under ~35 concurrent xdist workers and passes alone is
failing on resource contention, not on layering. A good test, made unreliable by
how it is run.

This splits the owner's complaint in two, and the split matters:
- **fragile-by-coupling** — the 883 numeric pins and 34 live-`data/` readers
  (TS-2's territory).
- **fragile-by-execution** — order- and load-dependent flakes that have nothing
  to do with what the test asserts (TS-0's territory, below).

Deleting value tests would not have prevented a single one of today's four
failures. TS-0 exists because of that.

## 3. Build order

**TS-0 first** — it is cheap, it is the live breakage, and until it lands no
other phase can trust a red test to mean anything. Then TS-1 → TS-2 → TS-3 in
order (each consumes the previous one's output). TS-4 and TS-5 may run in
parallel once TS-3 lands, in worktrees. TS-6 is last and ends in a decision for
the owner, not a merge.

---

## TS-0 — Make a red test mean something

**Package:** tools · **Agent:** `coder` · **Scope:** `tools/tests/**`,
`tools/conftest.py`, `tools/ci_shards.py`.

Fix the four live failures **as a class, not as four bugs**. Required, in order:

1. **Reproduce deterministically.** Find the worker count and ordering that
   fails. Record the exact invocation in the report — an unreproducible flake
   fix is a guess.
2. **Distinguish the two mechanisms.** For each of the four, establish whether
   it is (a) in-process state pollution — the `configure_fonts` /
   `configure_palette` / `configure_strings` in-place-mutation leak that root
   `CLAUDE.md` records as *already found four times* — or (b) resource
   contention under parallelism. `TestPurity` is a subprocess test and can only
   be (b); the three keybind/settings/panel tests smell like (a) via a shared
   Qt settings or keybind registry global.
3. **Fix the mechanism.** For (a), restore the global in a fixture the way
   `test_game_boot.py::_restore_font_state_after` already does — that pattern is
   correct and exists; the bug is that it is applied per-incident rather than
   centrally. Prefer ONE conftest-level autouse guard over a fifth hand-rolled
   copy. For (b), bound worker count or serialise subprocess-spawning tests via
   an xdist group marker.
4. **Prove it.** Re-run the affected shards at the failing worker count and show
   green, then at `-n0` (what CI uses) and show green.

**Do not** fix these by weakening the assertions, and **do not** delete
`TestPurity` — it guards a design pillar (R4). The test is right; its execution
environment is wrong.

**Done when:** the four are green under both parallel and `-n0` execution, and
the report names which mechanism each one was. If the count of historical
recurrences of mechanism (a) reaches five, say so explicitly in the report — a
bug found five times is a design problem, and the report should propose the
central fix rather than the fifth patch.

## TS-1 — Classify every test file

**Package:** tools · **Agent:** `scout` then `coder` · **Scope:**
`docs/test-audit.md` (new), read-only elsewhere.

Build the verdict table skeleton. For each of the 133 files record: the tier
marker it carries, the CI shard it lands in (`tools/ci_shards.py`), whether it
uses `TempDataCase`, whether it reads live `data/`, its count of numeric-literal
assertions, and a one-line statement of what it protects.

Category per file:
- **invariant** — would only fail if the game genuinely broke.
- **value** — asserts designer-chosen numbers or roster contents.
- **mixed** — both, and therefore a CONVERT candidate by construction.

**Done when:** `docs/test-audit.md` has 133 rows with categories and no
verdicts yet. Report the invariant/value/mixed split as three numbers.

## TS-2 — Measure designer-fragility by perturbation

**Package:** tools · **Agent:** `coder` · **Scope:** `tools/` throwaway
harness + `docs/test-audit.md`.

Write a scratch harness (NOT committed as a test) that, against a **copy** of
`data/`, applies realistic designer edits one at a time and records which test
files go red. Realistic means what the owner actually does in the editor:

- nudge a balancing scalar ±20% (per domain: buildings, enemies, map, ui, core)
- add a new enemy / building / VFX entry to a roster
- change a map's active flag, repaint a tile, move `camera_start`
- change a UI string, move a UI element, change a screen layout
- add a new agent form spec

For each edit, the fragility score of a test file is how many distinct realistic
edits turn it red. **This is the number that decides most verdicts.**

The harness runs targeted pytest per edit — it is the ONE place in this plan
allowed to run many pytest invocations, and it is a main-session or
worktree-isolated job precisely because of the test-guard rules. Budget it: 15
edits × targeted runs, not 15 full suites.

**Done when:** every row in `docs/test-audit.md` has a fragility score, and the
report names the top 10 most fragile files with the edit that breaks each.
Expected (**inferred**, to be confirmed): the 34 non-`TempDataCase` balancing
files dominate this list.

## TS-3 — Measure catch-rate from history

**Package:** tools · **Agent:** `scout` · **Scope:** read-only +
`docs/test-audit.md`.

For each test file, mine `git log` for evidence it ever caught a real defect:
a commit where the test changed *together with* a production fix in
`engine/`/`game/`/`editor/`, or a commit message naming a failure that the test
found. Contrast with its maintenance cost: how many times the file was edited
for reasons that were purely about the test being wrong.

Produce per file: `catches` (int), `test-was-wrong edits` (int), and the ratio.
Note explicitly that ~10 of the last 22 test-only commits were the latter — the
mining must reproduce or refute that figure across full history.

**Done when:** every row has both counts. The report leads with the **suite-wide
catch-to-maintenance ratio** — the single number that answers "is this worth
it".

## TS-4 — Convert the fragile, delete the worthless

**Package:** tools · **Agent:** `coder` (worktree) · **Scope:**
`tools/tests/**`.

Act on the verdicts. Per D4, prefer CONVERT:
- numeric literal → derive the expected value from `data/` via the same loader
  the game uses, or assert a *property* (positive, within schema bounds,
  monotonic) instead of an identity.
- live `data/` read → `TempDataCase` with a pinned fixture (the existing,
  correct pattern — 24 files already do this).
- roster count pins → derive the roster.

DELETE where TS-3 shows zero catches and TS-2 shows high fragility and nothing
survives conversion. Every deletion is one line in `docs/test-audit.md` and one
line in the surviving module docstring saying what stopped being covered.

**Hard rule:** never weaken a production behaviour to satisfy a stale test, and
never delete a test because it is *currently* failing — that is TS-4's single
biggest failure mode. Failing-now is orthogonal to worth-keeping.

**Done when:** the converted files pass, and the TS-2 harness is re-run over
the converted set to show fragility actually dropped. Report both numbers,
before and after.

## TS-5 — Shrink the surface

**Package:** tools · **Agent:** `coder` (worktree) · **Scope:**
`tools/tests/**`, `tools/ci_shards.py`.

With TS-4's verdicts in hand, address bulk. 42,553 test LOC against 49,103
production LOC is the ratio to attack. Look for:
- near-duplicate tests across files covering one behaviour many times
- editor tests that drive Qt to assert something a pure function could assert
- tests whose only failure mode is "someone renamed a thing"

Re-shard afterwards (`tools/ci_shards.py` + its meta test) so the shard table
still selects every module exactly once.

**Done when:** report states test LOC before/after, test count before/after, and
wall-clock of the full suite before/after — all **measured**.

## TS-6 — Price CI and put the decision to the owner

**Package:** none (a document) · **Agent:** none — **main session** ·
**Scope:** report only.

Billing is now a real constraint: the repo is private, Actions minutes are
metered, and the account has hit its limit. Price the options honestly with
TS-5's post-shrink wall-clock:

1. **Keep CI as-is** — cost in minutes/month at current push+PR rate.
2. **Keep CI, invariant shard only** — run the cheap invariant tests on every
   PR, everything else on demand.
3. **Local-gate only** — delete `.github/workflows/tests.yml`, rely on the
   editor's *Run tests* button and the local gate. Costs nothing, protects
   nothing when the owner forgets.
4. **Public the repo** — Actions minutes are free for public repos. A product
   decision, not a technical one; name it and let the owner reject it.

**Done when:** the owner has the four costed options. **Do not delete the
workflow without an explicit instruction** — that is the decision this whole
plan exists to inform, and it is not an agent's to make.

## 4. Risks / open items

- **R1 — The audit becomes the thing it is auditing.** Six phases of test
  archaeology can easily cost more than the suite has ever cost. Mitigation:
  TS-1–TS-3 are read-and-measure, cheap, and if TS-3's catch-to-maintenance
  ratio is bad enough the owner may skip straight to a large deletion in TS-4
  without the per-file ceremony. **An executing agent should propose that
  shortcut if the number warrants it.**
- **R2 — Perturbation harness false positives.** A test that goes red because
  the harness wrote invalid data is not a fragile test. The harness must write
  only schema-valid edits (use the validating writer).
- **R3 — Catch-rate mining is noisy.** Commit messages are the only signal and
  they are inconsistent. TS-3's numbers are **inferred**, not measured, and the
  report must tag them that way. They are directional, not decisive.
- **R4 — Deleting invariant tests by accident.** The layering, schema, and
  boot tests are what stop the two-package architecture from silently rotting.
  These are KEEP regardless of catch-rate; a test that has never fired may be
  the reason the thing it guards never broke.
- **R5 — Open question for the owner (do not guess):** is the goal *fewer red
  tests* or *less time spent on tests*? They point at different plans — the
  first favours CONVERT, the second favours DELETE. TS-1 must not start until
  this is answered.

## 5. What changed during execution

_(executing agents append here)_
