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

   **Then ask the scale explicitly — never infer it.** A plan is **flat** (the
   default: one orchestrator drives every phase) or **large** (phases are
   grouped into *sections*, and `/execute-plan-phases` gives each section its
   own orchestrator). Large exists because one orchestrator's context fills up
   on phase detail before a big plan is done. Steer with the size cap in Step 3a:
   if the work lands in **fewer than 3 sections**, it is flat — say so and move
   on. Do not offer large for a plan you could execute in one wave. If your
   dispatch handoff already carries a `plan_scale` value (the editor form's
   field), that IS the answer — don't re-ask it.
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

3a. **If the plan is LARGE, write the two-level build order instead** — the
   only structural difference; everything above (Context, decisions, per-phase
   Goal/Files/Tests/Exit gate, Risks) is unchanged.

   - **Stamp line 1**: `<!-- plan-scale: large -->`, then the usual
     `<!-- status: … -->` line, now counting both (`0/4 sections, 0/14 phases`).
     `/execute-plan-phases` reads line 1 to pick its mode.
   - **Size cap — enforce it, don't negotiate it**: **≥3 sections**, and
     **≤5 phases per section**. Fewer than 3 sections → this is a flat plan;
     tell the user and write it flat. A section reaching a 6th phase → split
     it, or move a phase to a neighbour. The cap exists so one section fits one
     section-orchestrator's context by construction.
   - `## 3. Build order` becomes `## 3. Section map`: a table
     `| Section | Title | Phases | Depends on | Status |` (one row per section,
     `S1`/`S2`/… ids), followed by one line naming the **waves** — the groups of
     sections with no dependency between them, which execute concurrently.
   - Then one `### Section S<n> — <title>` block per section, carrying:
     - **Purpose** — two or three lines. No file lists.
     - **Publishes** — the interface contract later sections consume: new schema
       keys, new module entry points, changed signatures. This is the ONLY thing
       a later section may assume about this one before it has run.
     - **Depends on** — section ids, or `—`.
     - the per-phase `| Phase | Scope (package) | Status |` table, scoped to this
       section's phases.
   - The `#### Phase <id>` detail blocks nest under their section, shape
     unchanged. **They are section-orchestrator territory** — the top
     orchestrator reads only the section map and each section's
     Purpose/Publishes, so a fact a later section needs belongs in **Publishes**,
     not buried in a phase block.
4. **Offer to activate it**: tell the user they can run
   `/setcurrentplan <Name>PLAN.md` (or use the editor's Summon a Drunken Robot
   screen) to make it the active plan. Do not activate without being asked.

## Avoid
- Implementing the plan's work here — this skill only produces the plan doc.
- Writing outside `planning/` (except when the user explicitly asks you to also
  `/setcurrentplan` it).
- A freeform structure — match the sibling plans so `/execute-plan-phases` and
  the editor tooling can consume it.
- **Inferring the scale.** Flat vs large is a Step-1 question, not a judgement
  call you make from the phase count.
- **Breaking the size cap to keep a tidy section count** — a 7-phase section
  defeats the entire point of large mode, which is that one section fits one
  orchestrator.
- Stamping `plan-scale: large` on a plan whose sections have no real dependency
  structure. Without waves there is nothing for the section tier to parallelise.

## Verify
- The new `planning/<Name>PLAN.md` exists, has a phase table with a Status
  column, and reads cleanly. State the path and whether it was activated.
- If large: line 1 is `<!-- plan-scale: large -->`, there are ≥3 sections, no
  section holds >5 phases, every section has **Purpose** / **Publishes** /
  **Depends on**, and every phase id in the section map has a matching
  `#### Phase` block. State the section and phase counts.

## Final report
- The new plan path; its scale (flat / large, and for large the section count
  and wave layout); its phases; whether you activated it via `/setcurrentplan`.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
