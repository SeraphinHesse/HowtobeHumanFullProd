---
description: Scaffold a new Claude command/skill in .claude/commands/ following this repo's house format (frontmatter + steps + verify + final report).
argument-hint: <skill name + one-line purpose>
allowed-tools: Read, Write, Glob
---

Scaffold a new skill: **$ARGUMENTS**. Skills in this repo live as
`.claude/commands/<name>.md` and are the project's slash commands. Keep the new one
**token-light** — it should point agents at the right subsystem doc rather than
re-explaining architecture. (Scaffolding an AGENT definition in
`.claude/agents/` instead? That's `/add-agent`.)

## Read first
1. An existing sibling that resembles the new skill's shape (`add-building.md` for a
   "add a game thing" workflow; `smalltweak.md` for a git-flow workflow) — match its
   structure, don't invent a new one.

## Steps
1. Pick a **kebab-case name**; the file is `.claude/commands/<name>.md`.
2. Write the **frontmatter** (three keys, same order as siblings):
   - `description:` one sentence, imperative — this is what shows in the skill list.
   - `argument-hint:` `<what the user passes>`.
   - `allowed-tools:` the MINIMAL set. Read/Edit/Write/Grep/Glob for edit workflows;
     add narrowly-scoped `Bash(...)` entries only for the exact commands the skill
     runs (e.g. `Bash(py tools/smoke.py*)`, `Bash(py -m unittest*)`, or specific
     `Bash(git ...)` verbs). Do NOT grant a blanket `Bash`.
3. Write the **body** in the house shape:
   - a one-line restatement using `**$ARGUMENTS**` + any lock/scope caveat;
   - **Read first (token-light)** — name the ONE subsystem doc to load
     (`engine|game|editor/<sub>/CLAUDE.md`) instead of pasting architecture;
   - **Steps** — numbered, smallest-change-first;
   - **Avoid** — the repo-specific foot-guns for this task;
   - **Verify** — the narrowest check (unit test / `py tools/smoke.py` / live run),
     and "state what you verified";
   - **Final report** — changed files + verification + whether a subsystem doc needed
     a durable update.
4. Keep it short. If it's growing past ~60 lines, the detail probably belongs in a
   subsystem CLAUDE.md that the skill links to.

## Verify
- The file parses as valid front-matter markdown (three `---`-fenced keys) and reads
  cleanly. It should appear as `/<name>` after the session reloads skills.

## Final report
- The new file path; its `allowed-tools`; which subsystem doc it routes to.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
