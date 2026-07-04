---
description: Make a small game tweak without the branch+lock protocol. If on a domain feature branch, commits to main instead (never the feature branch).
argument-hint: <what to tweak>
allowed-tools: Bash(git rev-parse*), Bash(git status*), Bash(git diff*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git switch*), Bash(git pull*), Bash(py tools/smoke.py*), Bash(py -m unittest*), Read, Edit, Write
---

Make a small, self-contained tweak: **$ARGUMENTS**. This path deliberately
SKIPS the branch+lock protocol — use it only for changes too small to warrant
locking a domain. It never changes any `_lock`.

## Branch logic

1. `git rev-parse --abbrev-ref HEAD` to see the current branch.
2. If on a domain feature branch (`featureBuildings`, `featureEnemies`,
   `featureMap`, `featureUi`, `featureCore`): do NOT commit the tweak there.
   Make the edits, `git switch main`, commit + push on `main`, then
   `git switch` BACK to the original feature branch.
3. Otherwise commit + push on the current branch.

## Steps

1. Make the edit. If it turns out to be non-trivial — multi-domain, or an
   architectural change — STOP and tell the user to run `/start-domain <domain>`
   instead.
2. Run the exit gate: `py -m unittest discover -s tools/tests -t .` and
   `py tools/smoke.py`. Both must pass.
3. `git status`, summarize, and **wait for explicit confirmation** before
   committing.
4. On confirmation, commit + push per the branch logic above. Report what
   landed and where.

Constraints: no `_lock` changes, ever. Never force-push, never `reset --hard`.
If a balancing JSON is touched, write it through `engine.data_io.write_validated`
(schema-valid, canonical) — never hand-format.
