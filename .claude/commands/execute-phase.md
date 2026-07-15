---
description: Execute ONE phase from a plan document interactively — plan mode first, then user questions, then implementation — and always update that plan doc's phase status.
argument-hint: <plan-doc> <phase-id e.g. 10J>
allowed-tools: Read, Write, Edit, Glob, Grep, Agent, AskUserQuestion, EnterPlanMode, ExitPlanMode, Bash(git *), Bash(gh *), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*), Bash(py game/main.py*)
---

Execute one plan phase: **$ARGUMENTS** — `<plan-doc> <phase-id>`. Interactive
single-phase mode (for parallel batch ranges use `/execute-plan-phases`;
unattended background execution of one phase is the `phase-executor` agent's
job). The plan doc is the status ledger: this skill NEVER finishes without
writing the phase's outcome back into it.

## Step 0 — Preconditions gate (abort with a clear report on any failure)
- The plan doc exists and contains the phase — quote its bullet/section verbatim.
- Working tree clean; base branch `Development` pulled and up to date.
- If the plan doc names a spec/prototype repo (e.g. `planning/MIGRATION_PLAN.md`
  → `planning/planning resources/MIGRATION_AGENT_READ_FIRST.md` + the prototype repo): it is
  **READ-ONLY** — cite it, never edit it.

## Read first (token-light)
1. Root `CLAUDE.md` router → the ONE package doc matching the phase's scope
   (if the phase truly spans packages, that becomes a Step-2 user question).
2. For `planning/MIGRATION_PLAN.md` phases: `planning/planning resources/MIGRATION_AGENT_READ_FIRST.md`.

## Steps
1. **Plan mode.** Enter plan mode. Audit what the phase needs vs what already
   exists (current repo AND spec repo, with `file:line` citations — delegate
   wide discovery to `scout` agents rather than grepping inline), then draft
   the implementation plan: work items, file scope, exit gate, a concrete
   in-game Quick Test.
2. **Questions.** Before finalizing, surface every genuine user decision via
   AskUserQuestion — package-spanning scope, deferrals/divergences, asset or
   data choices. Never assume answers to these.
3. **Approval.** ExitPlanMode. On approval: branch `phase-<id>-<slug>` off
   `Development`. The suite is GREEN on `Development`; there is no baseline to
   record.
4. **Implement** the approved plan in small commits. While iterating, verify
   with `py tools/testgate.py check --affected` — never the full suite mid-task.
5. **Exit gate:** `py tools/smoke.py` green; ONE full `py tools/testgate.py
   check` — **0 failures** (the single full-suite run of the phase, since this
   skill hands the work back); run the Quick Test live. Report exactly what was
   verified.
6. **Plan-doc status (ALWAYS).** Edit the phase's entry in the plan doc:
   `*(LANDED)*` on completion, with any deferrals/accepted divergences as
   sub-bullets (mirror 10F's style in `planning/MIGRATION_PLAN.md`). If the phase was
   aborted or partially landed, write that instead — the doc must state
   reality either way. This edit is part of the phase's diff.
7. **Report + PR.** Final report via `/report` (a phase completion is a human
   boundary — also republish root `PLAN.md` as the "How To Be Human — Active
   Plan" artifact after the status write-back), then commit → push → PR to
   `Development` stating the Quick Test — only on the user's explicit
   confirmation.

## Avoid
- Skipping the plan-doc status update — it is the point of this skill.
- Destructive git on uncommitted work (`reset --hard`, `clean`, force-push).
- Committing `build/`, `dist/`, or any `*.exe`.
- Editing the spec/prototype repo.
- Silently absorbing scope beyond the phase's bullet — extra scope is a
  Step-2 question, not a decision.

## Verify
- Exit gate of Step 5, plus: the plan doc's phase entry now reflects the
  outcome. State what you verified (smoke / suite green / live run).

## Final report
- Branch name, changed files, verification results, plan-doc status line as
  written, PR URL (if opened), any package CLAUDE.md that needed a durable
  update.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
