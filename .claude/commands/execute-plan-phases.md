---
description: Execute a range of phases from an implementation-plan document by orchestrating parallel planner/coder/reviewer subagent waves under an umbrella branch.
argument-hint: <plan-file> <phase-range e.g. 10G-10I> [spec-repo-path]
allowed-tools: Agent, Read, Write, Edit, Glob, Grep, Bash(git *), Bash(gh *), Bash(py tools/smoke.py*), Bash(py -m unittest*)
disable-model-invocation: true
---

Execute plan phases: **$ARGUMENTS** — `<plan-file> <phase-range> [spec-repo-path]`.
This is an **orchestrator**; isolation comes from git worktrees under one
umbrella branch.

## Step 0 — Preconditions gate (abort with a clear report on any failure)
- The plan file exists and contains every phase in the range (list them).
- Working tree clean; base branch `Development` pulled and up to date.
- If a spec/prototype repo path was given: verify it is readable. It is
  **READ-ONLY** — cite it, never edit it.

## Steps
1. **Umbrella.** Branch `phase-<range>-umbrella` off the base branch. Record the
   suite is GREEN (`py -m unittest discover -s tools/tests -t .` → 0 failures).
   There is no baseline to record: every later gate requires **zero failures**.
2. **Wave 1 — PLANNERS** (one **`planner` agent** per phase, parallel). Each reads the router
   `CLAUDE.md` → the relevant package/subsystem docs → current source (+ spec
   repo if given), then writes `docs/briefs/phase-<id>-<slug>.md` with exactly:
   (1) Behavioral spec w/ citations; (2) Architecture plan; (3) File scope +
   shared-file contract — exact insertion points in files multiple phases touch;
   (4) Exit gate + Quick Test. Orchestrator reconciles §3 across briefs into
   non-overlapping insertion blocks, then commits all briefs to the umbrella.
3. **Wave 2 — CODERS** (one **`coder` agent** per phase — **`engine-coder`**
   when the brief's §3 file scope is `engine/**` — parallel,
   `isolation: "worktree"`, branch
   `phase-<id>-<slug>` off the umbrella). The brief is the contract; §3 is a hard
   file boundary. **If the phase adds a building / enemy / balancing tunable /
   engine component / editor feature / asset-import category, the coder MUST
   invoke the matching `/add-*` skill (`/add-building`, `/add-enemy`,
   `/add-balancing-value`, `/add-engine-component`, `/add-editor-feature`,
   `/add-asset-importer`) instead of hand-rolling the edits** — the skill is the
   canonical pattern. Each runs the exit gate (`py tools/smoke.py` + suite vs
   green) and commits. Coders never push or open PRs.
4. **Wave 3 — REVIEWERS** (one **`reviewer` agent** per phase, parallel). Review the diff against the
   brief (behavior + cited numbers), repo conventions, test quality, scope
   respected. Send findings back to the SAME coder agent via `SendMessage` for
   fixes; coder re-runs the exit gate.
5. **Wave 4 — Integrate.** Merge phase branches into the umbrella
   **sequentially in plan order**, resolving conflicts and re-running the exit
   gate after each merge. One **`reviewer`** agent over the umbrella's full
   diff. Update the plan document's phase table + any package CLAUDE.md that
   changed architecturally. Push the umbrella; open **ONE** PR to the base
   branch stating each phase's Quick Test. Merge only on the user's explicit
   confirmation.
6. **Report (human boundary).** Close via `/report`: the end-of-run summary in
   the shared provenance-tagged format, published as an artifact, plus a
   republish of root `PLAN.md` as the "How To Be Human — Active Plan" artifact
   (the phase table just changed). Workers never publish — only this
   orchestrator does.

## Avoid
- Destructive git on uncommitted work (`reset --hard`, `clean`, force-push).
- Committing `build/`, `dist/`, or any `*.exe`.
- Editing the spec/prototype repo — read-only, always.
- Granting a coder scope outside its brief's §3 file boundary.

## Verify
- After each wave: exit gate green (0 failures) on every phase branch, then on
  the umbrella after each sequential merge. State what you verified.

## Final report
- Per-phase: branch name, brief path, review outcome.
- Test counts, and the failure count — which must be **zero**.
- Umbrella branch + the single PR URL.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
