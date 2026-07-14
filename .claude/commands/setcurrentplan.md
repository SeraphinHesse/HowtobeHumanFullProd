---
description: Set the active plan — mirror a plan doc from planning/ into the root PLAN.md so CLAUDE.md, agents, and the editor all point at it.
argument-hint: <plan filename in planning/, e.g. MIGRATION_PLAN.md>
allowed-tools: Read, Write, Glob, Bash(date +%Y-%m-%d)
model: haiku
---

Set the active plan to **$ARGUMENTS**. `planning/` holds the plan sources of
truth; root `PLAN.md` is a **generated mirror** of whichever one is active —
never hand-edited. This skill regenerates that mirror.

## Read first (token-light)
- The current root `PLAN.md` line 1 marker (`<!-- active-plan: … -->`) — that
  is what you are replacing. Do not read the whole plan bodies.

## Steps
1. **Resolve the target.** Treat `$ARGUMENTS` as a filename under `planning/`.
   `Glob planning/*.md`; match case-insensitively, and accept the bare stem
   (e.g. `MIGRATION_PLAN`) or the full name (`MIGRATION_PLAN.md`). If it does
   not match exactly one file, **list the available plans and abort** — do not
   guess.
2. **Read** the resolved `planning/<name>.md` in full (this is the body to
   mirror). Never mirror `PLAN.md` into itself.
3. **Stamp the date**: `date +%Y-%m-%d`.
4. **Write** root `PLAN.md` = a banner block, then the verbatim body:
   ```
   <!-- active-plan: <name>.md | set: <date> -->
   > **Active plan:** <name>.md (mirror). Source of truth:
   > `planning/<name>.md`. Do **not** edit this file directly — edit the
   > source in `planning/` and re-run `/setcurrentplan`, or pick a different
   > plan (`/setcurrentplan <name>`, or the editor's Summon a Drunken Robot
   > screen).

   <verbatim body of planning/<name>.md>
   ```
   Line 1 MUST be the `<!-- active-plan: … -->` marker (the editor and agents
   parse it). Copy the body byte-for-byte — do not summarize or reflow it.

## Avoid
- Editing files under `planning/` — this skill only writes root `PLAN.md`.
- Dropping or reformatting any of the source body; the mirror must match.
- Inventing a plan name; on ambiguity, list and stop.

## Verify
- Root `PLAN.md` line 1 names the chosen plan, and its body length matches the
  source (`planning/<name>.md`). State which plan is now active.

## Final report
- The plan now active, the marker line written, and a reminder that edits go to
  the `planning/` source (re-run this skill to re-mirror).
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
