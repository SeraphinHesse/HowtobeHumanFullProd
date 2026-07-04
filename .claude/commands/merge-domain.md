---
description: Merge a finished domain into main — the ONLY place the _lock clears and the feature branch goes away.
argument-hint: <buildings|enemies|map|ui|core>
allowed-tools: Bash(git switch*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git pull*), Bash(git branch*), Bash(gh pr*), Bash(py -c *), Edit, Write, Read
---

Merge the **$1** domain's `feature<Domain>` branch into `main`. **This is the
ONLY place `_lock` clears back to `"UNLOCKED"`.** Integration branch is `main`.

Domain → JSON / schema / feature branch (same table as `/start-domain`):
buildings→featureBuildings, enemies→featureEnemies, map→featureMap,
ui→featureUi, core→featureCore. If `$1` isn't one of the five, STOP and ask.

## Steps

1. `git switch feature<Domain>`.
2. **Unlock** (through the validating writer — keep the file canonical):
   ```
   py -c "from engine import data_io; d='data/balancing/$1.json'; s='data/schemas/$1.schema.json'; doc=data_io.load_validated(d,s); doc['_lock']='UNLOCKED'; data_io.write_validated(doc,d,s); print('unlocked $1')"
   ```
3. `git add data/balancing/$1.json` → `git commit -m "unlock $1 balancing"` →
   `git push`. Unlocking must be the last commit before the branch merges — so
   the domain never sits merged-but-locked.
4. **Merge the PR into main.** Normally the user does this in GitHub. Only on the
   user's explicit confirmation may you run `gh pr merge --merge` for this
   branch's PR.
5. **After the merge:** `git branch -d feature<Domain>`, `git switch main` →
   `git pull`, then clear the session scope — delete `.claude/active_domain`
   (or blank it).

Manual fallback: if the automated unlock step can't run, flip `_lock` to
`"UNLOCKED"` on the feature branch (via `write_validated`, never hand-format) and
commit it before merging the PR — unlocking is always the last step before the
branch goes away. Never force-push, never `reset --hard`.
