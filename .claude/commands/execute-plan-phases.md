---
description: Execute a range of phases from an implementation-plan document by orchestrating parallel planner/coder/reviewer subagent waves under an umbrella branch. Large plans switch to section mode, adding a tier of section-orchestrators.
argument-hint: <plan-file> <phase-range e.g. 10G-10I> [spec-repo-path] [--large|--flat]
allowed-tools: Agent, SendMessage, Skill, Artifact, Read, Write, Edit, Glob, Grep, AskUserQuestion, Bash(git *), Bash(gh *), Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*)
disable-model-invocation: true
---

Execute plan phases: **$ARGUMENTS** — `<plan-file> <phase-range> [spec-repo-path]
[--large|--flat]`. This is an **orchestrator**; isolation comes from git
worktrees under one umbrella branch.

## Step 0a — Scale detection (before anything else)

Read **line 1** of the plan file. `<!-- plan-scale: large -->` (or an explicit
`--large`) selects **section mode** — jump to §"Section mode" below and run it
INSTEAD of Steps 1-6. Anything else, or `--flat`, runs the flat path exactly as
written below. An explicit flag beats the marker. State the mode you detected in
one line and confirm it before branching; a large plan run flat will overwhelm
this session's context, which is the failure mode section mode exists to fix.

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

   **A denied test run is a REPORT, never a retry.** `test_guard.py` denies with
   exit 2 and a reason; every dispatched agent must be told, verbatim:

   > If `test_guard` denies a test command, do NOT re-issue it, do not vary the
   > flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
   > fingerprints identically), and do not reach for the guard's escape hatch.
   > Report the deny text and the result it quotes back to the orchestrator and
   > stop testing. Retrying is the loop the guard exists to stop.

   Two denies are expected in a parallel wave and must not be fought:
   - *"already ran this exact target and NOTHING has changed"* — the guard
     fingerprints the **main checkout's** diff. Worktrees are gitignored, so a
     coder's own edits may be invisible to it and a legitimate re-run after a
     fix can be denied. Accept the quoted earlier result; if it was a FAIL that
     you believe you have since fixed, say exactly that in your report and let
     the orchestrator verify at the umbrella.
   - *"another test run is already in flight"* — the lock may be shared across
     the wave. Do not wait-loop and do not delete the lock; report and stop.
     Only THIS orchestrator may clear a lock, and only after confirming no run
     is live (the deny prints the path).
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

   **Reconcile §4 too, and downgrade it where needed.** A brief's exit gate is
   executed by a SUBAGENT, so it may contain only `py tools/smoke.py` + named
   `pytest` files. If a brief — or the phase bullet in the plan doc it came
   from — asks for the full suite, `testgate check`, `--affected`, or a tier
   sweep, **the Test Suite Policy wins over the plan doc**: rewrite that §4 to
   the targeted gate before dispatching Wave 2, and note the rewrite in the
   final report. Shipping a brief with a wider gate hands the coder a command
   the hook will deny.
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
   fixes; the coder re-runs its **named-file** gate
   (`py -m pytest tools/tests/test_<file>.py`) — never `--affected`, which the
   hook denies for subagents because its safety pass is the whole core tier.
   **At most TWO fix rounds per phase.** If findings survive round 2, stop the
   ping-pong: record the open findings in the phase's brief and carry them to
   Wave 4 as orchestrator work or a flagged item in the final report. An
   unbounded reviewer↔coder loop is the other way this skill can fail to
   terminate.
5. **Wave 4 — Integrate.** Merge phase branches into the umbrella
   **sequentially in plan order**, resolving conflicts and re-running
   `py tools/testgate.py check --affected` after each merge — legal here because
   this is the MAIN session, mid-task. If it prints `GATE ABORT` (it aborts
   rather than widening) it exits non-zero **without running anything**: that is
   not a test failure and not something to retry — name the affected test files
   yourself and run those once. One **`reviewer`** agent over
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

## Section mode (large plans only — replaces Steps 1-6)

A large plan groups its phases into **sections** (`## 3. Section map`). Each
section gets its own `section-orchestrator` agent, which runs Waves 1-3 over
that section's phases and hands back a capped file. **The point is what YOU
don't read**: this session's context is the bottleneck a large plan overflows.

**The hard context rule.** You read the section map, each section's
**Purpose** / **Publishes** lines, and `docs/handoffs/section-<id>.md`. You do
**NOT** read a `#### Phase` block, a `docs/briefs/*.md`, a phase diff, or a
coder's report — ever. If you need a fact from inside a section, that is a
defect in its handoff: ask the section-orchestrator for it via `SendMessage`,
or record it as an open finding. Reading it yourself refills the context this
mode exists to protect.

Step 0's preconditions gate still applies (plan exists, tree clean, base pulled,
spec repo read-only), as does the whole test-budget rule in Step 1 — a
section-orchestrator is a SUBAGENT and its row of §"Test Suite Policy" is
unchanged by the fact that it orchestrates.

- **L1 — Umbrella.** Branch `plan-<name>-umbrella` off the base branch. Read
  §3's section table and each section's Purpose/Publishes/Depends-on. Stop
  reading there. Group the sections into **waves**: a wave is the set of
  sections whose dependencies have all landed.
- **L2 — Dispatch a wave.** Cut each section's `section-<id>` branch off the
  umbrella, then dispatch one `section-orchestrator` per section with
  `isolation: "worktree"` — **at most TWO concurrently**; queue the rest of the
  wave behind that cap. Each dispatch carries: section id, plan path, its
  section branch, the umbrella branch, and the **paths of its dependencies'
  handoff files** (never their briefs or diffs). Nested worktrees are verified
  to work, so each section-orchestrator's own phase coders stay parallel and
  isolated beneath it.
- **L3 — Close the wave.** When every section in the wave has returned: merge
  the section branches into the umbrella **in plan order**, resolving conflicts,
  running `py tools/testgate.py check --affected` after each merge (legal here —
  MAIN session, mid-task; a `GATE ABORT` means name the affected test files
  yourself and run those once, it is not a failure and not a retry). Then show
  the user a **digest** of the wave — per section: Landed, Interface deltas,
  Open findings — and **wait for their go** before dispatching wave N+1. This is
  the handoff prompt; it is the point at which a wrong architectural call is
  still cheap to fix.
- **L4 — A section that fails** (aborted, or unresolved findings after its two
  fix rounds) does **not** stop its in-flight siblings: let them finish, merge
  the green ones into the umbrella, then **stop before the next wave** and
  report — the failed section's handoff, what landed, and what the user must
  decide. **No PR.** Killing live siblings only discards tokens already spent.
- **L5 — Close the run.** One `reviewer` over the umbrella's full diff. Update
  any package `CLAUDE.md` that changed architecturally and the plan doc's
  section-map statuses. Then the **one and only full gate**:
  `py tools/testgate.py check` — zero failures. Push the umbrella; open **ONE**
  PR to the base branch quoting each section's Quick Tests. Merge only on the
  user's explicit confirmation. Close via `/report` + the `PLAN.md` artifact
  republish, exactly as Step 6.

## Avoid
- Destructive git on uncommitted work (`reset --hard`, `clean`, force-push).
- Committing `build/`, `dist/`, or any `*.exe`.
- Editing the spec/prototype repo — read-only, always.
- Granting a coder scope outside its brief's §3 file boundary.
- Running the full suite anywhere except the single Wave-4 umbrella gate.
- Passing a brief's or plan doc's wider exit gate through to a coder unchanged —
  downgrade it in Wave 1 instead.
- Letting any agent's exploration run past ~10 minutes before it produces its
  deliverable.
- **Re-issuing any test command that was denied, or that you already ran with
  nothing edited since.** One deny → report it and move on.
- Instructing a subagent to run `--affected` — the hook denies it; the deny then
  invites exactly the retry loop above.
- Unbounded reviewer↔coder fix rounds (cap: two).

Section mode adds:
- **Reading a phase brief, a phase block, or a phase diff from THIS session.**
  It is the one rule the whole mode rests on.
- More than **two** concurrent `section-orchestrator` agents.
- Letting a section-orchestrator push, open a PR, publish an artifact, or run
  the full suite / a tier sweep / `--affected` — it is a subagent.
- Running a large plan flat because the range "looks small". The marker decides.
- Skipping the wave-boundary digest and go-ahead — the user asked to sit there.

## Verify
- After each wave: every phase branch's **named-file** gate green (0 failures) —
  as reported by its coder, not re-run by you — then
  `py tools/testgate.py check --affected` on the umbrella after each sequential
  merge.
- Once, on the finished umbrella before the PR: full `py tools/testgate.py
  check` green. State what you verified. If this single run is denied by an
  in-flight lock left behind by a dead subagent, confirm nothing is running,
  delete the lock file the deny message names, and run it once — do not re-issue
  it blind.

## Final report
- Per-phase: branch name, brief path, review outcome. **In section mode this is
  per-SECTION instead** — section branch, handoff path, phases landed — sourced
  from the handoff files, not from anything you read yourself.
- Test counts, and the failure count — which must be **zero**.
- Umbrella branch + the single PR URL.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
