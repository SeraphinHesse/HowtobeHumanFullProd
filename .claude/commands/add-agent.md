---
description: Scaffold a new subagent definition in .claude/agents/ following this repo's house format (frontmatter + short system-prompt body + roster registration).
argument-hint: <agent name + one-line role>
allowed-tools: Read, Write, Edit, Glob
---

Scaffold a new agent: **$ARGUMENTS**. Agents live as `.claude/agents/<name>.md`
and are dispatched by name from the orchestrator skills
(`/execute-plan-phases`, `/processtodo`) or directly via the Agent tool. Keep
the body **short** — an agent definition is a role + hard rules, not a
re-explanation of the repo.

## Read first
1. The existing sibling closest to the new agent's role — `scout.md` for
   read-only roles, `coder.md` for implementers, `reviewer.md` for checkers.

## Steps
1. Pick a **kebab-case name**; the file is `.claude/agents/<name>.md`.
2. Write the **frontmatter** (same key order as siblings):
   - `name:` the kebab-case name.
   - `description:` when the ORCHESTRATOR should pick this agent — it's matched
     against tasks, so make it selective ("Use for X; use Y instead when Z").
   - `tools:` the MINIMAL set. Read-only roles never get Edit/Write; add
     `Skill` only if the agent must invoke `/add-*` skills.
   - `model:` `haiku` for mechanical/discovery roles, `sonnet` for
     implementation/review; OMIT the key (inherit) for judgment-heavy roles.
3. Write the **body** as a short system prompt: role in one line → opening
   moves → hard rules → exit gate (only if it edits) → report format.
   Do NOT paste root `CLAUDE.md` or graphify orientation — the SubagentStart
   hook injects both into every agent already.
   **The exit gate is the SUBAGENT row of §"Test Suite Policy", always** — every
   agent in `.claude/agents/` is a subagent, whoever dispatches it. So:
   `py tools/smoke.py` + `py -m pytest tools/tests/test_<file>.py -q` over the
   files it touched, zero failures. Never write the full suite, `testgate
   check`, `--affected`, or a tier sweep into an agent body; `test_guard.py`
   denies all four from a subagent, and a denied command must be reported, not
   retried. Read-only agents (`scout`, `reviewer`) get **no** gate at all — say
   "do not run tests" explicitly.
4. End the body with the two standing rules every agent carries:
   never publish artifacts (report upward; the orchestrator publishes), and
   provenance-tag every claim (**measured** / **verified** / **inferred** —
   see `/report`).
5. **Register it:** add a one-line row to root `CLAUDE.md`'s "Agent roster"
   section.

## Avoid
- Duplicating package docs into the body — name the doc the agent should read.
- Blanket tool grants; giving worker agents push/PR/publish powers.
- Per-package coder clones — specialization belongs in the dispatch prompt +
  package docs unless the package is strict AND self-contained (see
  `engine-coder.md` for the one justified specialist).

## Verify
- The file parses (frontmatter keys present, same order as siblings) and the
  agent appears in the Agent tool's available types in a fresh session. State
  whether you checked live or statically.

## Final report
- New file path; its tools + model; the roster row added to root `CLAUDE.md`.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
