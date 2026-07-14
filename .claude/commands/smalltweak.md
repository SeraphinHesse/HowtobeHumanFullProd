---
description: Make a small, self-contained game tweak directly — no plan phase, no dispatch handoff. For anything bigger, use /createplan or a dispatched form.
argument-hint: <what to tweak>
allowed-tools: Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git switch*), Bash(git pull*), Bash(py tools/smoke.py*), Bash(py -m unittest*), Read, Edit, Write
---

Make a small, self-contained tweak: **$ARGUMENTS**. Use this only for changes
too small to warrant a plan phase or a dispatched form.

## Branch logic

1. `git rev-parse --abbrev-ref HEAD` to see the current branch.
2. On `Development` or `main`: create a short-lived branch first (work lands
   via PR, never directly on the base branches).
3. Otherwise commit on the current branch.

## Steps

1. Make the edit. If it turns out to be non-trivial — multi-package, or an
   architectural change — STOP and tell the user to run `/createplan` (or
   dispatch the matching "Add new X" form via the editor) instead.
2. Run the exit gate: `py -m unittest discover -s tools/tests -t .` and
   `py tools/smoke.py`. The suite is GREEN — 0 failures; smoke green.
3. `git status`, summarize, and **wait for explicit confirmation** before
   committing.
4. On confirmation, commit + push per the branch logic above. Report what
   landed and where.

Constraints: never force-push, never `reset --hard`. If a balancing JSON is
touched, write it through `engine.data_io.write_validated` (schema-valid,
canonical) — never hand-format.
