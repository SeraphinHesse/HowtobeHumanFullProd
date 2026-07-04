---
description: Wrap up the active domain session — run the exit gate, then (on confirmation) commit, push, and open a PR into main. Does NOT unlock.
allowed-tools: Bash(py tools/smoke.py*), Bash(py -m unittest*), Bash(git status*), Bash(git diff*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(gh pr create*), Read
---

Finish the current domain session. The active domain is whatever is written in
`.claude/active_domain` (set by `/start-domain` or `/resume-domain`) — read it
first. This command does **NOT** unlock: the `feature<Domain>` branch still
exists, so the lock stays LOCKED until `/merge-domain`.

## Steps

1. **Run the universal exit gate** (root CLAUDE.md Step 2):
   - `py -m unittest discover -s tools/tests -t .` → all green.
   - `py tools/smoke.py` → OK.
   If either fails, STOP and fix — do not claim done.
2. **Data check.** If balancing values changed, confirm the JSON validates (the
   smoke test already validates every `data/**` file against its schema) and
   that `_lock` is still the object form (you must NOT have unlocked here).
3. **Docs.** If anything architectural changed, confirm the domain's package doc
   was updated (`game/<domain>/CLAUDE.md` if it exists, else `game/CLAUDE.md` /
   the relevant package CLAUDE.md) — not the root router, not another domain's
   doc.
4. `git status` + a short summary of what changed. **Wait for the user's explicit
   confirmation** before committing.
5. On confirmation: `git add` the changed files → `git commit -m "<brief>"` on
   `feature<Domain>` → `git push` → `gh pr create --base main` into `main`.
   Report the PR URL. State a concrete in-game/in-editor Quick Test scenario in
   the PR body (T-5).

Never run destructive git on uncommitted work. Unlocking happens only in
`/merge-domain`.
