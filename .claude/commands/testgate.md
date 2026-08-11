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
and skips the entire editor tier. If the selection is uncertain for any reason
(a `conftest.py`/`pytest.ini` change, a stale graph), it silently falls back to
running everything: a gate that under-selects is worse than a slow one.

Use `--affected` while iterating. Run the **full** `check` once before you hand
work back.

## Tiers
```
py -m pytest -m core        # engine + game + data. Fast.
py -m pytest -m editor      # the PySide6 suites. Slow.
py -m pytest -m meta        # the agent scaffolding.
```
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
