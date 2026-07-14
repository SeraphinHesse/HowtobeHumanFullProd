---
description: SUSPENDED — the branch+lock protocol is on hold (see root CLAUDE.md). Do not run. Use the editor's Summon a Drunken Robot forms (/dispatch) instead.
argument-hint: <buildings|enemies|map|ui|core>
allowed-tools: Bash(git pull*), Bash(git add*), Bash(git commit*), Bash(git push*), Bash(git switch*), Bash(git branch*), Bash(git status*), Bash(git rev-parse*), Bash(py -c *), Edit, Write, Read
---

> ⚠️ **SUSPENDED.** The branch + lock protocol is on hold for the engine
> migration (root `CLAUDE.md` → "Branch + lock protocol"). Do **not** run this
> command: it is no longer reachable from the editor's spawn dialog, and
> `/dispatch` never writes `.claude/active_domain` or any `_lock`. Spawn work
> from the editor's **Summon a Drunken Robot** launcher ("Add new X…" forms →
> `/dispatch`), or branch per plan phase. This file is kept intact so the
> protocol can be restored unchanged when the migration lands.

Start a scoped work session on the **$1** balancing domain of How To Be Human —
Full Production. Integration branch is `main`. Lock shape is D-11 (an object,
NOT a string). This is one of only two lock writers (`/merge-domain` is the
other — the ONLY unlock).

## Domain → file / branch / doc table

| domain    | balancing JSON                | schema                                   | feature branch    | doc (fallback game/CLAUDE.md) |
|-----------|-------------------------------|------------------------------------------|-------------------|-------------------------------|
| buildings | data/balancing/buildings.json | data/schemas/buildings.schema.json       | featureBuildings  | game/buildings/CLAUDE.md      |
| enemies   | data/balancing/enemies.json   | data/schemas/enemies.schema.json         | featureEnemies    | game/enemies/CLAUDE.md        |
| map       | data/balancing/map.json       | data/schemas/map.schema.json             | featureMap        | game/map/CLAUDE.md            |
| ui        | data/balancing/ui.json        | data/schemas/ui.schema.json              | featureUi         | game/ui/CLAUDE.md             |
| core      | data/balancing/core.json      | data/schemas/core.schema.json            | featureCore       | game/core/CLAUDE.md           |

If `$1` isn't one of these five, STOP and ask.

## Steps

1. **Sync main.** `git switch main` then `git pull`.
2. **Write the lock** (through the validating writer — never hand-edit the JSON;
   the lock is a D-11 object and the file must stay canonical: sorted keys,
   2-space indent, trailing newline). Run from the repo root, substituting the
   domain stem and the CamelCase feature branch name:
   ```
   py -c "from engine import data_io; from datetime import date; d='data/balancing/$1.json'; s='data/schemas/$1.schema.json'; doc=data_io.load_validated(d,s); doc['_lock']={'locked_by':'feature<Domain>','since':date.today().isoformat()}; data_io.write_validated(doc,d,s); print('locked $1')"
   ```
   `feature<Domain>` = the table's feature-branch name (e.g. `featureBuildings`,
   `featureUi`). `write_validated` raises before touching disk if the shape is
   wrong.
3. **Commit + push the lock to main.** `git add data/balancing/$1.json` →
   `git commit -m "lock $1 balancing"` → `git push`. If push is rejected
   (non-fast-forward): `git pull --rebase` then retry — different domain JSONs
   always merge clean.
4. **Branch.** If `feature<Domain>` doesn't exist, create it from main
   (`git switch -c feature<Domain>`); otherwise `git switch feature<Domain>`.
5. **Scope the session.** Write the lowercase domain name (one line, no newline
   games) into `.claude/active_domain` — this arms the PreToolUse scope guard so
   edits outside `game/$1/**` + the domain's balancing/schema (plus shared
   `game/core/**`, and `data/maps/**` for map) are blocked.
6. **Read the domain doc** — `game/$1/CLAUDE.md` if it exists, else the package
   doc `game/CLAUDE.md` (per-domain docs land in Phase 9). Report a short plan
   and wait for instructions.

## Invariant

While `feature<Domain>` exists, that domain's `_lock` stays the object form
(LOCKED). It only returns to `"UNLOCKED"` at merge time (`/merge-domain`). Never
run destructive git on uncommitted work (no `reset --hard`, `clean`,
`checkout -- <file>`, force-push).
