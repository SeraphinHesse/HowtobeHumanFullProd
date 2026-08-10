---
description: Find out why CI is red on this branch/PR and fix it forward — reads the failing run's logs, reproduces the failures locally, fixes, re-verifies, pushes.
argument-hint: "[PR number or run id — inferred from the current branch if omitted]"
allowed-tools: Bash(gh run*), Bash(gh pr*), Bash(git rev-parse*), Bash(git status*), Bash(git log*), Bash(git diff*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(py -m pytest*), Bash(py tools/testgate.py*), Bash(py tools/smoke.py*), Read, Edit, Write, Grep, Glob
---

CI is red on **$ARGUMENTS** (if empty: the PR / run for the current branch).
Diagnose it from the actual run logs and **fix it forward**. Never `git reset`,
`git restore`, `git checkout -- <file>`, or force-push to make a run go away.

## 1. Find the run that is actually red

```bash
git rev-parse --abbrev-ref HEAD
gh pr list --head <branch> --json number,title,url,state
gh pr checks <pr>                     # one line per check
gh run list --branch <branch> --limit 8
```

**Check the SHA before you believe the failure.** A red run is only worth
fixing if it tested the code you have:

```bash
gh run view <id> --json headSha,status,conclusion,createdAt
git rev-parse HEAD
```

- Red run's `headSha` **is** HEAD → real, fix it.
- Red run's `headSha` is an **older commit** on the branch and a newer run is
  green/in-flight → the failure may already be fixed. Say so, wait for the
  current run (`gh run watch <id> --exit-status --interval 20`, backgrounded),
  and do not "fix" tests that already pass.
- Never leave this ambiguous in the report: name the SHA each verdict came from.

## 2. Extract the failures — never dump the raw log

`gh run view <id> --log-failed` on this repo emits the ENTIRE job log (the
steps are unnamed, so `--log-failed` cannot narrow). Pipe it; do not read it:

```bash
gh run view <id> --log-failed 2>&1 | grep -E "Z (FAILED|ERROR|SUBFAILED) " | sed 's/.*Z //'
gh run view <id> --log-failed 2>&1 | grep -E "GATE (PASS|FAIL)|short test summary|Error: Process completed" | sed 's/.*Z //'
```

Group the node IDs by **file** and by **error text** — 25 failures with one
error message are one bug, not 25.

## 3. Classify before you edit

| Signature | It is | First move |
|---|---|---|
| Same assertion across many unrelated test files | ONE behaviour change with wide blast radius | Fix the source/helper, not each test |
| Fails in CI, passes locally | environment or **live-`data/` dependence** | See below |
| `ModuleNotFoundError`, pip/apt step failed, runner cancelled, timeout | infra, not your diff | Fix the workflow or re-run; don't touch tests |
| `UNEXPECTED SKIP` / `SUBFAILED` | a test silently stopped running | Treated as failure by the gate — fix it |

**The live-`data/` trap is the most common cause of "green here, red there".**
Tests must never assert against live `data/` content (CLAUDE.md, Step 2) — a
designer adding one row in the editor can turn a whole suite red. If the
failure traces to a value in `data/**` that a session/headless test happens to
read, the fix is to **pin the fixture** (`TempDataCase`,
`tools/tests/fixtures/data/`) or make the test drive the new state explicitly —
not to delete the data.

## 4. Reproduce locally, narrowly

Obey `## Test Suite Policy` in CLAUDE.md — **the full suite is not a diagnostic
tool.** Run only the files CI named:

```bash
py -m pytest tools/tests/test_<a>.py tools/tests/test_<b>.py -q
```

- Reproduce **before** editing. If it does not reproduce, the difference is
  environment (`QT_QPA_PLATFORM=offscreen`, `SDL_VIDEODRIVER=dummy`,
  Linux vs Windows, live `data/`) — find *that*, don't guess at the test.
- Never launch a second pytest run while one is in flight.

## 5. Fix forward

- Fix the **cause**, once, in the right layer. Prefer the shared helper
  (e.g. a scenario `run_wave()` driver) over N copy-pasted test patches.
- Read the ONE package `CLAUDE.md` for whatever you are about to edit.
- If a new phase/state can strand a headless run, the session must offer a way
  to drain it and the shared test driver must use it — that is a source fix,
  not a per-test fix.
- Do not `snapshot` the baseline to make the gate green. The gate is ZERO.

## 6. Verify, then push

```bash
py -m pytest <the files CI named> -q     # targeted: they must go green
py tools/smoke.py
py tools/testgate.py check               # the ONE full run, at handoff
```

Then commit (brief message) → push → watch:

```bash
gh run watch <new-run-id> --exit-status --interval 20   # background it
```

CI is not fixed until a run whose `headSha` equals the pushed HEAD is green.

## Avoid

- Pasting raw CI log or tracebacks into the report.
- Re-running the full suite mid-task, or twice.
- "Fixing" a failure that a newer commit already fixed.
- Destructive git of any kind — the tree may hold someone else's uncommitted
  work (CLAUDE.md, Branching).
- Disabling, skipping, or xfail-ing a test to get green.

## Final report (one screen)

- The red run + its SHA, and the ONE root cause (not the 25 symptoms).
- What you changed and why that is the cause, not the symptom.
- Gate result as its single line.
- New run id + conclusion, or "watching" if still in flight.
- Tag each claim **measured** / **verified** / **inferred** (`/report`).
