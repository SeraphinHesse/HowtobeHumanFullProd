---
description: Execute a range of phases from an implementation-plan document by orchestrating parallel planner/coder/reviewer subagent waves under an umbrella branch.
argument-hint: <plan-file> <phase-range e.g. 10G-10I> [spec-repo-path]
allowed-tools: Agent, Read, Write, Edit, Glob, Grep, Bash(git *), Bash(gh *), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*)
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
1. **Umbrella.** Branch `phase-<range>-umbrella` off the base branch. Do NOT
   run the suite to confirm it is green — CI gates every PR into `Development`,
   so the base is green by construction. There is no baseline to record: every
   later gate requires **zero failures**.

   **Test-budget rule for every wave below:** every dispatched agent's gate
   is `py tools/smoke.py` + `py -m pytest tools/tests/test_<file>.py -q` over
   the files it touched — nothing wider. A subagent may not run the full suite,
   a tier sweep, or `--affected` (its safety pass is the whole core tier); the
   `test_guard.py` hook denies all three. The **full** suite runs exactly ONCE,
   from THIS main session, on the finished umbrella in Wave 4, right before the
   PR. Never mid-orchestration. §"Test Suite Policy" in the root `CLAUDE.md` is
   the authority.
2. **Wave 1 — PLANNERS** (one **`planner` agent** per phase — launch ALL of them
   in ONE wave, a single message of parallel dispatches). Each reads the router
   `CLAUDE.md` → the relevant package/subsystem docs → current source (+ spec
   repo if given), then writes `docs/briefs/phase-<id>-<slug>.md`.
   **Exploration is capped at ~10 minutes per agent**: the plan, the ONE package
   doc, the files in scope — then write the brief; no codebase sweeps. The brief
   contains exactly:
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
   canonical pattern. The same ~10-minute exploration cap applies: the brief is
   the map — read it and the files in its §3 scope, then implement. Each runs
   the targeted gate (`py tools/smoke.py` +
   `py -m pytest tools/tests/test_<file>.py -q` over the files it touched —
   NOT the full suite, NOT a tier sweep, NOT `--affected`) and commits.
   Coders never push or open PRs.
4. **Wave 3 — REVIEWERS** (one **`reviewer` agent** per phase, parallel). Review the diff against the
   brief (behavior + cited numbers), repo conventions, test quality, scope
   respected. Send findings back to the SAME coder agent via `SendMessage` for
   fixes; coder re-runs the targeted gate (`--affected`).
5. **Wave 4 — Integrate.** Merge phase branches into the umbrella
   **sequentially in plan order**, resolving conflicts and re-running the
   targeted gate (`--affected`) after each merge. One **`reviewer`** agent over
   the umbrella's full diff. Update the plan document's phase table + any
   package CLAUDE.md that changed architecturally. Then run the **one and only
   full gate** of the orchestration: `py tools/testgate.py check` on the
   finished umbrella — zero failures. Push the umbrella; open **ONE** PR to the
   base branch stating each phase's Quick Test. Merge only on the user's
   explicit confirmation.
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
- Running the full suite anywhere except the single Wave-4 umbrella gate.
- Letting any agent's exploration run past ~10 minutes before it produces its
  deliverable.

## Verify
- After each wave: targeted gate (`--affected`) green (0 failures) on every
  phase branch, then on the umbrella after each sequential merge.
- Once, on the finished umbrella before the PR: full `py tools/testgate.py
  check` green. State what you verified.

## Final report
- Per-phase: branch name, brief path, review outcome.
- Test counts, and the failure count — which must be **zero**.
- Umbrella branch + the single PR URL.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
