---
description: Commit the current work, push the branch, and open a PR into Development in one step (runs the exit gate first).
argument-hint: [optional commit/PR subject — inferred from the diff if omitted]
allowed-tools: Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git log*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(gh pr create*), Bash(gh pr view*), Bash(py tools/smoke.py*), Bash(py -m unittest*), Read
---

Wrap up the working tree: **commit the current work, push the branch, and open
a PR in one step** — subject: **$ARGUMENTS** (infer from the diff if empty).
This is the closing move of a session, not a work skill: it makes NO code
edits and never touches any `_lock`.

## Preconditions (abort with a clear report on any failure)

1. `git rev-parse --abbrev-ref HEAD` — refuse to run on `Development` or
   `main`; work belongs on a phase/feature branch (branch first if needed).
2. `git status` — there must be something to commit OR unpushed commits;
   otherwise say so and stop.
3. Review `git diff` — never blind-commit: no `build/`, `dist/`, `*.exe`, no
   stray scratch files; if a plan doc (`MIGRATION_PLAN.md`/`PLAN.md`) should
   reflect this work and doesn't, flag it before committing.

## Steps

1. Run the exit gate: `py tools/smoke.py` and
   `py -m unittest discover -s tools/tests -t .` — no NEW failures vs the
   session's baseline (Development carries known pre-existing failures; diff
   the failure list, don't demand a green board).
2. Show `git status` + a one-line summary, then **wait for explicit
   confirmation** before committing (skip the wait only if the user already
   confirmed in the invoking message).
3. Commit (brief message; group unrelated changes into separate commits) and
   `git push -u origin <branch>`.
4. `gh pr create --base Development` — body states a concrete in-game Quick
   Test scenario plus what was verified (smoke / suite vs baseline / live run).
5. If a PR already exists for the branch (`gh pr view`), just push — don't
   open a duplicate.

## Avoid

- Committing on `Development`/`main`, force-push, `reset --hard`, amending
  pushed commits.
- Committing `build/`, `dist/`, any `*.exe`, or editor prefs.
- Opening a PR with failing NEW tests "to fix later".

## Verify

- Exit gate ran (state the result), push succeeded, `gh pr view` shows the PR.

## Final report

- Branch, commits landed, exit-gate result, PR URL.
