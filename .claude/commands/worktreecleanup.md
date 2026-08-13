---
description: Remove stale worktrees and delete local branches whose commits are already in origin/Development; safety rules protect anything holding unique or unpushed work, and remote branches are never touched without --remote.
argument-hint: [--remote] [--dry-run] [+<branch-or-pattern> ...] [-<branch-or-pattern> ...]
allowed-tools: Bash(git worktree*), Bash(git branch*), Bash(git status*), Bash(git for-each-ref*), Bash(git merge-base*), Bash(git rev-list*), Bash(git log*), Bash(git fetch*), Bash(git push origin --delete*), Bash(gh pr list*), Read
---

Clean up worktrees and branches: **$ARGUMENTS**.

- `+name` — keep this branch/pattern for this run only.
- `-name` — drop a keep-pattern match, forcing deletion. **`-name` cannot
  override a SAFETY RULE below** — only a name/pattern keep.
- `--remote` — also delete the matching branches on `origin`. Off by default.
- `--dry-run` — classify and report, delete nothing.

## The safety rules (absolute — checked before any whitelist)

**A clean working tree does NOT mean a worktree is stale.** This skill once
removed three worktrees the user was actively working in, because its only
check was `git status --short` and all three were committed-and-clean. Clean is
the normal state of active work, not evidence of abandonment.

Never delete a branch that trips ANY of these:

1. **Holds unique commits** — `git merge-base --is-ancestor <b> origin/Development`
   fails. Its work exists nowhere else; deleting it is the one truly
   unrecoverable action here.
2. **Has unpushed commits** — `%(upstream:track)` contains `ahead`. The commits
   live only on this machine.
3. **Is checked out in a worktree** — any worktree, dirty or clean, surviving or
   not.
4. **Has an open PR** — `gh pr list --state open --json headRefName`.
5. **Is the current branch or the main worktree's branch.**
6. **Belongs to someone else** — `git log -1 --format='%an'` is anyone other
   than `SeraphinHesse` / `Seraphin Hesse` / `Claude`. **Authorship, not the
   name, is the real test of whose branch this is**, and it is the only one of
   these rules that catches a teammate who names branches their own way. The
   collaborator name patterns below are a convenience on top; they are not
   sufficient. Known collaborators: **fabiankrg**, **Nox0901** (Joel),
   **Dingle04** (Benji), **varjaxxO169**, **HenniBumBenni** (Hendrik),
   **jakobdahlkar**.

Everything the rules clear is, by definition, fully contained in
`origin/Development` — so deleting it loses no commit, only a name.

## Default keep list (on top of the safety rules)

- `Development`, `main`
- **Collaborators' branches:** `Art/*`, `HendriksStuff`, and case-insensitively
  `joel*`, `benji*`, `fabian*`, `varjax*` — other people's work. Merged or not,
  deleting their refs is confusing, and deleting their remotes would be hostile.
  These patterns are a convenience only: safety rule 6 (authorship) is what
  actually protects a teammate. A real run found `Joel_balancing3`,
  `Lightning_Balancing` and `MapTest` — all teammates' — matching no pattern
  here and surviving purely because they happened to be unmerged.
- **Milestone markers:** `EngineAndEditorComplete`, `Phase-9-Complete`,
  `PrototypeMigrationComplete`, `BeforeScalingRework`
- `Tutorial`
- Pattern `*umbrella*` — orchestration umbrella branches.

Edit this list here for a permanent change rather than passing `+`/`-` each run.

## Steps

1. `git fetch origin` first — every safety rule compares against
   `origin/Development`, and a stale remote ref makes rule 1 lie in the
   dangerous direction (a merged-upstream branch looks unmerged is fine; the
   reverse is not).
2. **Worktrees.** `git worktree list` — the first row is the repo root; never
   touch it. For every other row, `git -C <path> status --short`. Remove ONLY
   worktrees that are both clean AND whose branch the safety rules clear for
   deletion. **A clean worktree on a protected branch stays** — it is active
   work someone has open. Then `git worktree prune`.
   - Removal deletes gitignored files (`graphify-out/`, caches, `.venv`,
     `settings.local.json`) even though git reports the tree clean. Say so.
   - On Windows/OneDrive a removal can fail with `Permission denied` partway.
     Re-check with `git worktree list` and report it rather than retrying.
3. **Classify every local branch** into keep-with-reason vs delete, and
   **print both lists with counts before deleting anything.** The reason string
   (`UNMERGED` / `UNPUSHED` / `in-worktree` / `open-PR` / `keep-name`) is what
   makes this auditable.
4. **Delete the cleared local branches.** Prefer `git branch -d`; if it refuses,
   the branch was not really merged — that is rule 1 catching a classification
   bug, so STOP and report rather than reaching for `-D`.
5. **Remote branches: only with `--remote`.** Without the flag, list the stale
   remote refs as a suggestion and delete nothing. With it, classify
   `git branch -r` under the SAME safety rules — re-derived from the remote
   refs, never inherited from step 4, since the local refs are gone by then —
   and `git push origin --delete` only what clears all six. Print the authors
   alongside the delete list; a name you don't recognise is rule 6 doing its
   job. Also skip any ref that fails `git rev-parse --verify` (the enumeration
   can yield phantom tokens such as a bare `origin`).
6. Report per the Final report section.

## Avoid

- Removing or switching the main/current worktree.
- Force-removing a dirty worktree, or `git branch -D` on anything rule 1 flags.
- Treating "clean working tree" as "abandoned" — see the safety rules.
- Deleting a remote branch without `--remote`, and any remote delete at all for
  a collaborator's branch.
- Acting on a classification computed before the last `git fetch`, or before a
  re-check of `git worktree list` — other agents and the user work in this repo
  concurrently.

## Verify

`git worktree list` and `git branch -vv` afterwards: every surviving branch is
either on the keep list or protected by a safety rule, and every worktree that
existed with unique or unpushed work still exists.

## Recovery (if this skill deletes something it should not have)

A branch deleted while fully merged loses nothing — recreate it at the same
commit. A removed worktree comes back with
`git worktree add <path> <branch>`, restoring every tracked file; only
gitignored local files are gone for good. `git reflog` still holds the tip of a
branch deleted by mistake.

## Final report

Worktrees removed / kept / skipped-as-dirty; branches deleted (local vs
local+remote) with the total count; the keep list with each branch's protecting
reason. Tag claims measured/verified/inferred (see `/report`).
