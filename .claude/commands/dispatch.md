---
description: Execute a structured agent-dispatch handoff from the editor — git setup (worktree branch off Development, or current branch), then drive the target add-* skill.
argument-hint: <handoff-file path>
allowed-tools: Read, Edit, Write, Grep, Glob, SlashCommand, Bash(git *), Bash(gh pr create*), Bash(py tools/smoke.py*), Bash(py -m unittest*), Bash(py -c *)
---

Execute the dispatch handoff at **$ARGUMENTS** — a schema-valid JSON payload the
editor wrote when a designer submitted an "Add new X" form. This skill does git
setup + payload translation ONLY; the real work is done by the target `add-*`
skill named in the payload, invoked unmodified. The branch+lock protocol is
SUSPENDED: this skill NEVER writes `.claude/active_domain` and NEVER touches any
`_lock`.

## Read first (token-light)
1. The handoff itself (Step 1) — it names everything else.
2. Only the docs listed in the payload's `context` array. Do not pull in whole
   architecture docs the payload didn't ask for.

## Steps
1. **Read + validate** the handoff. Fail loud, do not guess:
   `py -c "from engine import data_io; data_io.load_validated(r'$ARGUMENTS', r'data/schemas/dispatch_handoff.schema.json')"`
   Then Read it and echo a one-paragraph summary: form id, target skill, values,
   free text, git mode/branch. If validation fails, STOP and report — never
   proceed to git on a malformed payload.
2. **Read the context files** from the payload's `context` array.
3. **Git setup** — from the payload's `git` block:
   - `mode: "current"` → `git status --porcelain`. If dirty, list the dirt and
     continue ONLY if it is unrelated to this task. Work in place.
     **Never switch branches.**
   - `mode: "branch"` → `git fetch origin Development`. If `git.branch` already
     exists (`git rev-parse --verify`), suffix `-2`, `-3`, … until free. Then
     `git worktree add .claude/worktrees/<branch> -b <branch> origin/Development`
     and do ALL subsequent work with **absolute paths inside that worktree** —
     the user's editor has the main tree open; never yank it.
4. **Invoke the target skill** as a real slash command, unmodified:
   `/<skill> <values as one readable line> — free text: <free_text> — structured payload: <handoff path>`
   If the SlashCommand tool is unavailable, Read `.claude/commands/<skill>.md`
   and follow it with exactly that composed `$ARGUMENTS`.
5. **Exit gate** in the working root (the worktree, in branch mode):
   `py tools/smoke.py` and `py -m unittest discover -s tools/tests -t .`. Green
   smoke; no NEW test failures.
6. **Land**:
   - branch mode → commit, push, `gh pr create --base Development` with a body
     carrying the payload summary, what you verified, and a concrete in-game
     Quick Test. Then `git worktree remove <path>` and report the PR URL.
   - current mode → summarize the diff and **WAIT for the user's explicit
     confirmation before committing** (the `/smalltweak` convention). No PR.
7. **Archive** the handoff into `.claude/dispatch/done/` (create the dir if
   needed).

## Avoid
- Writing `.claude/active_domain` or any `_lock` — the protocol is SUSPENDED.
- `git switch` / `git checkout -b` in the main tree; force-push; `reset --hard`;
  `git clean`.
- Committing `build/`, `dist/`, or any `*.exe`.
- Editing anything the target skill's own file scope doesn't cover.
- Re-implementing the target skill. It runs as written.

## Verify
- Smoke + suite from Step 5, run in the working root. State exactly what you
  exercised (worktree vs in place, smoke, suite, any live run).

## Final report
- Handoff file + form/skill; git mode and branch (or "in place on <branch>");
  changed files; verification results; PR URL (branch mode) or the diff summary
  awaiting confirmation (current mode); where the handoff was archived.
