---
description: Batch-process the How To Be Human todo list — spawn per-domain worktree agents under an umbrella branch, PR into main.
argument-hint: <small|priority|smallpriority|all>
allowed-tools: Bash(git *), Bash(gh *), Bash(py tools/smoke.py*), Bash(py -m unittest*), Read, Write, Edit, Glob, Grep, Agent
---

Batch-process outstanding todos for How To Be Human — Full Production. Mode
`$ARGUMENTS` selects the slice of work: `small` (quick tweaks only), `priority`
(flagged items), `smallpriority` (both filters), or `all`.

This is an **orchestrator**: isolation comes from git worktrees + an umbrella
branch, so parallel per-domain agents don't collide.

## Read the todo list

Use the `gettodo` skill scoped to this project (`Skill gettodo` with the project
filter) to read the outstanding build items. Bucket each item by domain
(buildings / enemies / map / ui / core): an item belongs to
the domain whose `game/<domain>/**` or `data/balancing/<domain>.json` it touches.
Cross-cutting items (touch `game/core/**` shared host, or multiple domains) go
last, single-threaded. Add any newly discovered follow-ups back with `addtodo`.

## Branch topology

- Umbrella branch `autobatch-<YYYY-MM-DD>` off `main`.
- Each domain agent works in its own **git worktree** on
  `feature<Domain>Batch-<YYYY-MM-DD>` off the umbrella, and PRs into the umbrella.
- Finally, one PR from the umbrella branch into `main`.

## Execution

1. `git switch main` → `git pull`. Create the umbrella branch.
2. For each domain with queued work, spawn a subagent with `isolation:
   "worktree"`, scoped to that domain's files only (give it the domain's
   `DOMAIN_SCOPE` list). **In each subagent's brief, instruct it: if the item
   adds a building / enemy / balancing tunable / engine component / editor
   feature / asset-import category, invoke the matching `/add-*` skill
   (`/add-building`, `/add-enemy`, `/add-balancing-value`, `/add-engine-component`,
   `/add-editor-feature`, `/add-asset-importer`) rather than hand-rolling the
   edits.** Run domains that share `game/core/**` in separate waves
   to avoid host-file conflicts; independent domains may run in parallel.
3. Each agent's exit gate is this repo's: `py -m unittest discover -s tools/tests
   -t .` and `py tools/smoke.py`, both green. Balancing JSON edits go through
   `engine.data_io.write_validated` (canonical, schema-valid).
4. Collect the per-domain PRs into the umbrella, resolve conflicts, run the exit
   gate once more on the umbrella, then open the umbrella → `main` PR. Report all
   PR URLs. Merge only on the user's explicit confirmation.

Constraints: never `reset --hard`, `clean`, or force-push on shared branches;
never commit `build/`, `dist/`, or `*.exe`. If an item is too large or genuinely
spans domains in a way worktrees can't isolate, leave it queued and flag it for a
manual `/execute-phase` session.
