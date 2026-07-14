---
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
argument-hint: <buildings|enemies|map|ui|core>
allowed-tools: Bash(git switch*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git pull*), Bash(git branch*), Bash(gh pr*), Bash(py -c *), Edit, Write, Read
---

> ⚠️ **SUSPENDED.** The branch + lock protocol is on hold for the engine
> migration (root `CLAUDE.md` → "Branch + lock protocol"). Do **not** run this
> command: it is no longer reachable from the editor's spawn dialog, and
> `/dispatch` never writes `.claude/active_domain` or any `_lock`. Spawn work
> from the editor's **Summon a Drunken Robot** launcher ("Add new X…" forms →
> `/dispatch`), or branch per plan phase. This file is kept intact so the
> protocol can be restored unchanged when the migration lands.

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
