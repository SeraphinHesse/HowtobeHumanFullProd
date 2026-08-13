---
description: Author a new phased plan doc into planning/ — the planning agent that helps you scope a new plan in this repo's plan-doc family shape.
argument-hint: <plan name + one-line purpose>
allowed-tools: Read, Write, Edit, Glob
---

Author a new plan: **$ARGUMENTS**. New plans live in `planning/` as
`<Name>PLAN.md` and join the family of phased, agent-executable plans
(`MIGRATION_PLAN.md`, `AgentDispatchPLAN.md`, …). You are
the **planning agent**: help the user scope the plan, then write it — do not
start implementing the plan's contents.

## Read first (token-light)
1. One existing sibling to match structure — `planning/completed plans/AgentDispatchPLAN.md`
   (phased, with a build-order table) or `planning/MIGRATION_PLAN.md`. Mirror
   its shape; don't invent a new format.
2. Root `CLAUDE.md` for the package/layering vocabulary the plan should use.

## Steps
1. **Scope it with the user.** Clarify: the goal/vision, which package(s) it
   touches (engine / game / editor / data), the phases, and the per-phase exit
   criteria. Ask before assuming — a plan is only useful if the phasing is real.
2. **Pick a name**: `planning/<Name>PLAN.md` (PascalCase stem ending `PLAN`).
3. **Write the doc** in the family shape:
   - `# <Title>` then a **Context** (or Vision) section — why this plan exists.
   - Numbered `## N.` sections for architecture / decisions as needed.
   - A **build-order table** with a **Status** column (`not started` / …), one
     row per phase.
   - Per-phase: **Goal**, **Files** (new / modified), **Tests**, **Exit gate**.
   - A closing **Risks / open items** section.

   **Per-phase Tests / Exit gate must be written in the executing role's
   terms.** Phases are executed by subagents (`coder`, `engine-coder`,
   `phase-executor`) or by `/execute-phase`, so a phase's gate is
   `py tools/smoke.py` + `py -m pytest tools/tests/test_<file>.py -q` over that
   phase's files, plus a concrete in-game Quick Test. **Never write "full suite
   green", `py tools/testgate.py check`, `--affected`, or a tier sweep
   (`-m core` / `-m editor` / `-m meta`) into a phase row** — `test_guard.py`
   denies all four from a subagent, so such a gate cannot be run by whoever
   executes the phase. The one full `check` happens ONCE, in the main session,
   at handoff — mention it only as the plan's closing step, never per phase.
   §"Test Suite Policy" in the root `CLAUDE.md` is the authority; link to it
   instead of restating a different rule in the plan doc.
   Keep it token-light and route to subsystem docs rather than pasting
   architecture.
4. **Offer to activate it**: tell the user they can run
   `/setcurrentplan <Name>PLAN.md` (or use the editor's Summon a Drunken Robot
   screen) to make it the active plan. Do not activate without being asked.

## Avoid
- Implementing the plan's work here — this skill only produces the plan doc.
- Writing outside `planning/` (except when the user explicitly asks you to also
  `/setcurrentplan` it).
- A freeform structure — match the sibling plans so `/execute-plan-phases` and
  the editor tooling can consume it.

## Verify
- The new `planning/<Name>PLAN.md` exists, has a phase table with a Status
  column, and reads cleanly. State the path and whether it was activated.

## Final report
- The new plan path; its phases; whether you activated it via `/setcurrentplan`.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
