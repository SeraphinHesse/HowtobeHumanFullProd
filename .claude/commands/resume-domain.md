---
description: Resume an already-started domain session — pull, switch to the feature branch, re-scope. Does NOT touch the lock.
argument-hint: <buildings|enemies|map|ui|core>
allowed-tools: Bash(git pull*), Bash(git switch*), Bash(git status*), Bash(git rev-parse*), Edit, Write, Read
---

Resume work on the **$1** domain. The lock was already written by
`/start-domain`, so this command **does NOT touch `_lock`** and does NOT create
a branch — it only re-syncs and re-scopes the session.

Domain → feature branch: buildings→featureBuildings · enemies→featureEnemies ·
map→featureMap · ui→featureUi · core→featureCore. If `$1` isn't one of the five,
STOP and ask.

## Steps

1. `git switch main` then `git pull`.
2. `git switch feature<Domain>`. If that branch does NOT exist, STOP and tell the
   user to run `/start-domain $1` first (the lock hasn't been taken yet).
3. Write the lowercase domain name into `.claude/active_domain` (re-arms the
   PreToolUse scope guard).
4. Read the domain doc — `game/$1/CLAUDE.md` if it exists, else `game/CLAUDE.md`.
   Report a short plan and wait.

Invariant unchanged: `/merge-domain` is the only unlock. No destructive git on
uncommitted work.
