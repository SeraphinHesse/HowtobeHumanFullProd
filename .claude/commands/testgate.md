---
description: Run the exit gate and report it in one line. Replaces "run the suite and figure out what was already broken".
argument-hint: "[--affected] — narrow to the blast radius of your diff"
allowed-tools: Bash(py tools/testgate.py*), Bash(py tools/smoke.py*), Read
---

Run the exit gate: **$ARGUMENTS**

```
py tools/smoke.py
py tools/testgate.py check
```

**Only the MAIN SESSION, at handoff, runs that second line** — the role table in
§"Test Suite Policy" (root `CLAUDE.md`) is the authority, and a `PreToolUse`
hook denies it from a subagent. A subagent invoking this command runs
`py tools/smoke.py` plus the specific test files it touched, and nothing else.

Read the last line. That is the whole gate:

```
GATE PASS  2245 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips
```

```
GATE FAIL  1 problem(s)
  NEW FAILURE   tools/tests/test_boss.py::TestBoss::test_dead_goal_repaths
```

## Rules
- **The gate is ZERO.** The suite is green (TestGatePLAN TG-2). There is no
  baseline to measure and no "pre-existing failure" to tolerate. If a test is
  red, you broke it — fix it, don't explain it away.
- **Do not re-run the suite to find out what was already broken.** That is the
  waste this tool exists to delete. `check` already knows.
- **Never paste raw gate output into a report.** Collapsing ~3.3k tokens of
  tracebacks into one line is the point; pasting the tracebacks back in undoes it.
- **An UNEXPECTED SKIP fails the gate.** A test that quietly stops running is
  indistinguishable from one that passes. If you meant to skip it, `snapshot` it
  with a reason.

## `--affected` (fast path for coders)
```
py tools/testgate.py check --affected
```
Diffs against `Development`, asks Graphify for the blast radius of what you
changed, and runs only those test modules — always union'd with the `core` tier
as cheap insurance. A change confined to `engine/tilemap.py` selects 23 modules
and skips the entire editor tier.

**If it cannot narrow, it ABORTS — it does not widen.** A `conftest.py` /
`pytest.ini` / `qt_harness` change, or no matching test module, prints
`GATE ABORT` and exits non-zero *having run nothing*, telling you to name the
files yourself. So the `GATE INFO` line is trustworthy: if it ran, it narrowed.
(This doc used to say the opposite — "it silently falls back to running
everything: a gate that under-selects is worse than a slow one" — while the root
`CLAUDE.md` said to kill it when that happened. Same tool, opposite advice, and
the tool now does neither: it refuses. Do not reintroduce a silent widening.)

**`--affected` is a MAIN-SESSION mid-task tool, not a subagent one**: its
core-tier safety pass is hundreds of tests. Subagents name their files instead.
Run the **full** `check` once, from the main session, before handing work back.

## Tiers
```
py -m pytest -m core        # engine + game + data. Fast.
py -m pytest -m editor      # the PySide6 suites. Slow.
py -m pytest -m meta        # the agent scaffolding.
```
These are TIER SWEEPS — main session only (the hook denies them from a
subagent), and usually the wrong reach: name the test file you touched.
CI runs the WHOLE suite — no tier is excluded. (There used to be a `migration`
tier holding the prototype-parity gate; the migration is complete and it is
deleted.)

## `snapshot` — only when you are deliberately tolerating a red test
```
py tools/testgate.py snapshot
```
Writes `.test-baseline.json` (node-ID sets, stamped with the git SHA). A
non-empty baseline means someone has decided to live with a failing test; it has
to be written down in a file, not remembered. Do not run this to make a red
gate go green.
