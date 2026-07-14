---
description: Remove every worktree except the main one and delete local branches (plus matching remote branches) that aren't on the keep whitelist; the whitelist can be adjusted per-run.
argument-hint: [+<branch-or-pattern> ...] [-<branch-or-pattern> ...]
allowed-tools: Bash(git worktree*), Bash(git branch*), Bash(git status*), Bash(git push origin --delete*), Read
---

Clean up worktrees and branches: **$ARGUMENTS**. `+name` adds a branch or
pattern to the keep whitelist for this run only; `-name` removes one,
forcing it to be deleted even if it would otherwise match a keep pattern.

## Default whitelist

Kept unless overridden by `-name` above:
- Exact names: `Development`, `main`, `EngineAndEditorComplete`, `Phase-9-Complete`
- Pattern `*umbrella*` — any branch containing "umbrella"
- Pattern `phase-10*` — any branch starting with "phase-10" (case-insensitive)

Edit this list directly in the file for a permanent change instead of
passing `+`/`-` every time.

## Steps

1. `git worktree list` — the first row is the main worktree (repo root);
   never touch it. Every other row is a removal candidate.
2. For each candidate worktree, `git status --short` inside it (`git -C
   <path> status --short`). If it has any output (dirty), **skip it and
   warn the user by name** — do not force-remove.
3. `git worktree remove <path>` for each clean candidate, then
   `git worktree prune`.
4. `git branch -vv` — compute the effective whitelist (defaults above,
   merged with `+`/`-` overrides from `$ARGUMENTS`). For every local
   branch not matching it, `git branch -D <name>`.
5. For each branch just deleted, check whether its `branch -vv` line
   showed a live `[origin/<name>]` tracking ref (not `: gone]`) — if so,
   `git push origin --delete <name>`.
6. Report: worktrees removed (and any skipped for being dirty), branches
   deleted (local-only vs. local+remote), and the final kept branch list.

## Avoid

- Never remove or switch the main/current worktree.
- Never force-remove a dirty worktree — skip and report it instead.
- Never delete a branch whose only checkout is a worktree that was
  skipped for being dirty.
- Before deleting anything, re-check `git worktree list` / `git branch
  -a -vv` right before acting — other agents or sessions may be working
  in this repo concurrently, and a worktree with uncommitted changes is
  active work, not stale state.

## Verify

`git worktree list` and `git branch -a -vv` after running — confirm the
surviving set matches the effective whitelist, plus any worktrees skipped
for being dirty.

## Final report

What was removed vs. kept vs. skipped-as-dirty, tagged
measured/verified/inferred (see `/report`).
