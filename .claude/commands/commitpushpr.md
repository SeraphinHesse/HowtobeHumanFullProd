---
description: Commit the current work, push the branch, and open a PR into Development in one step.
argument-hint: [optional commit/PR subject — inferred from the diff if omitted]
allowed-tools: Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git log*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(gh pr create*), Bash(gh pr view*), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Read
disable-model-invocation: true
---

Wrap up the working tree: **commit the current work, push the branch, and open
a PR in one step** — subject: **$ARGUMENTS** (infer from the diff if empty).
This is the closing move of a session, not a work skill: it makes NO code
edits.

It does **not** run the exit gate itself. Per §"Test Suite Policy" in the root
`CLAUDE.md`, the main session runs exactly ONE `py tools/testgate.py check`, at
handoff — and this skill IS the handoff, so that run belongs to the session
*before* invoking it. Report whatever was actually verified (smoke, the single
full `GATE PASS` line, targeted files, live run, or "static read only"); never
imply a check you did not run. **There is no baseline and no tolerated failure**
— the gate is ZERO, so "green vs baseline" is not a thing to report.

If the session has NOT run the gate yet, say so in step 1 and let the user
decide: run it once now, or ship the PR stating exactly what was verified. Never
run it twice, and never run it from inside a dispatched agent.

## Preconditions (abort with a clear report on any failure)

1. `git rev-parse --abbrev-ref HEAD` — refuse to run on `Development` or
   `main`; work belongs on a phase/feature branch (branch first if needed).
2. `git status` — there must be something to commit OR unpushed commits;
   otherwise say so and stop.
3. Review `git diff` — never blind-commit: no `build/`, `dist/`, `*.exe`, no
   stray scratch files; if a plan doc (`MIGRATION_PLAN.md`/`PLAN.md`) should
   reflect this work and doesn't, flag it before committing.

## Steps

1. Show `git status` + a one-line summary, then **wait for explicit
   confirmation** before committing (skip the wait only if the user already
   confirmed in the invoking message).
2. Commit (brief message; group unrelated changes into separate commits) and
   `git push -u origin <branch>`.
3. `gh pr create --base Development` — body states a concrete in-game Quick
   Test scenario plus what the session verified.
4. If a PR already exists for the branch (`gh pr view`), just push — don't
   open a duplicate.

## Avoid

- Committing on `Development`/`main`, force-push, `reset --hard`, amending
  pushed commits.
- Committing `build/`, `dist/`, any `*.exe`, or editor prefs.
- Claiming verification that did not happen — if nothing was run, say so in the
  PR body.
- A second full `testgate check` when the session already ran one; and any full
  run at all if this skill was invoked from inside a dispatched agent (the
  `test_guard.py` hook denies it).

## Verify

- Push succeeded, `gh pr view` shows the PR.

## Final report

- Branch, commits landed, what was verified this session, PR URL.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
