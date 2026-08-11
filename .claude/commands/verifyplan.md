---
description: Verify the active plan (PLAN.md marker + its planning/ source) against the current code via scout agents — report GOOD TO EXECUTE or the stale claims.
argument-hint: [plan filename in planning/ — omit to use the active plan]
allowed-tools: Read, Glob, Grep, Agent, Bash(git log*), Bash(git diff*), Bash(diff *)
disable-model-invocation: true
---

Verify **$ARGUMENTS** (or, with no argument, the active plan named by root
`PLAN.md` line 1) is not stale and is good to execute. **Read-only** — this
skill never edits the plan or the code; it reports. It is user-invoked only
(`disable-model-invocation`) — agents must not trigger it on their own.

## Read first (token-light)
- Root `PLAN.md` line 1 marker → resolve `planning/<name>.md` and read THAT in
  full. If the marker names no active plan, list `planning/*.md` and stop.

## Steps
1. **Mirror integrity.** Diff the `PLAN.md` body (after the banner block)
   against the `planning/` source with `diff --strip-trailing-cr` (CRLF noise
   is expected under OneDrive). If `git status` shows `PLAN.md` modified,
   check `git log -- PLAN.md` before trusting either copy — this repo has had
   OneDrive silently revert plan docs. Report a real mismatch; do not fix it.
2. **Extract checkable claims** from the plan: every `file:line` cite, every
   "X is hardcoded / has no consumers / already exists", every "NEW" artifact
   that must NOT exist yet, the decisions' premises, and the `<!-- status -->`
   line's phase count.
3. **Dispatch scouts** (`scout`, in parallel, one per package
   the plan touches — data / engine / game / editor). Each gets its package's
   claim list and must return, per claim, CONFIRMED or STALE with `file:line`
   evidence. One scout also sweeps the whole repo for the plan's NEW artifact
   names (schema keys, modules, JSON files) to prove no phase silently started.
4. **Synthesize the verdict**: **GOOD TO EXECUTE**, or a numbered stale-claims
   list, each with the exact edit the plan needs. Plan edits go to the
   `planning/` source and then `/setcurrentplan <name>` re-mirrors — never
   into root `PLAN.md`.

## Avoid
- Editing anything (plan, code, data) — findings only.
- `Explore` / `Plan` / `general-purpose` agents — the C2 hook denies them.
- Running the test suite or smoke — staleness is claims-vs-code, not the gate.
- "Fixing" a diverged `PLAN.md` by re-mirroring without checking git history
  first (OneDrive rollback trap).

## Verify
- Every extracted claim has a scout verdict with evidence; none left implicit.
  State the verdict and what each scout actually checked.

## Final report
- The verdict (GOOD TO EXECUTE / stale), counts (N confirmed / M stale), the
  per-stale fix, and mirror-integrity status.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
