# CLAUDE.md — Router

First-read router for agents on **How To Be Human — Full Production**
(isometric tower-defence; you spend *love* to unlock tiles and place
musicians/defenders that protect "the hole" from enemy waves). This file stays
slim: it routes you to ONE package doc. Plan & phase status → `PLAN.md` (the
**active-plan mirror** — see below). Requirements → `SPEC.md` (referenced as
E-*/D-*/G-*/ED-*/T-*).

**Planning:** every plan doc lives in `planning/` (the sources of truth:
`UI_EDITOR_PLAN.md`, `EnemyReworkPLAN.md`, …; finished plans move to
`planning/completed plans/`, e.g. `EngineBuildPLAN.md`, `MIGRATION_PLAN.md`).
Root `PLAN.md` is a **generated mirror** of whichever one is currently active
(its line-1 `<!-- active-plan: … -->` marker names the source). Read `PLAN.md`
for the current plan; never hand-edit it — edit the source in `planning/` and
re-run `/setcurrentplan <name>` to re-mirror. Author a new phased plan with
`/createplan`. The editor's **Summon a Drunken Robot** screen shows the active
plan and can switch it too. **Not every task needs a plan** — see Status.

## Project identity & status
- **Stack:** Python 3.11+, pygame-ce (game), PySide6 (editor). Deps:
  `pip install -r requirements.txt`.
- **Status: the migration is COMPLETE.** The game and the editor both run:
  game `py game/main.py`, editor `py editor/main.py`. The bootstrap phases and
  the port from the prototype are finished and their plan is archived
  (`planning/completed plans/MIGRATION_PLAN.md`).
- **What the work is now:** feature reworks, feature expansions, editor
  capability expansion, and asset imports — driven **per task or per plan doc**.
  A small, self-contained change is a task (`/smalltweak`, a form dispatch, or
  just do it); anything phased gets its own doc in `planning/` via `/createplan`
  and becomes the active `PLAN.md` for as long as it runs. There is no single
  master plan any more, and `PLAN.md` may legitimately name no active plan.
- **The prototype is history, not spec.** `../HowToBeHuman/ClaudePrototype/
  HowToBeHuman` is readable for archaeology ("why is this number 240?") and many
  source comments still cite it. It is **no longer the behavioral authority**:
  this repo's `data/` + `SPEC.md` + the package docs are, and gameplay is free to
  diverge from it deliberately. Nothing in the test suite compares against it.
  Never edit it from here.

## Design pillars (tie-breakers for every decision)
1. **Agent legibility** — small single-purpose files; schemas over convention;
   no editor-only hidden state.
2. **Strict layering** — game logic never touches pygame; `editor/` and
   `game/` never import each other; both consume `engine/` and `data/`.
3. **Editor is the designer interface** — humans never hand-edit `data/`
   JSON; agents may, but only schema-valid writes.

## Command and Control Structure (C2) — mandatory agent workflow

**This is the "Command and Control Structure" (C2).** It governs how every task
is approached and is NON-NEGOTIABLE — it overrides the harness's default
plan-mode workflow. It has two halves that carry the same name so a request to
"edit the command and control structure" finds both: this section (the rule) and
`.claude/hooks/command_and_control.py` (the `PreToolUse` hook that hard-enforces
it).

- **Plan mode:**
  1. Explore with **`scout` agents only** — never `Explore`, `Plan`, or
     `general-purpose`.
  2. **The main session (the model the user invoked) writes the plan itself** —
     never a delegated `Plan` agent.
  3. On approval, **spawn the correct execution agent** — `coder`,
     `engine-coder`, or `phase-executor` — opening with the matching **skill**
     from the table below (`/add-building`, `/add-enemy`, …) when the task
     matches a row.
- **Direct mode (no plan mode):**
  1. **`scout`** for exploration.
  2. The main session **writes the plan itself** with the invoked model.
  3. **Spawn the correct execution agent(s)** with the matching skill.
  4. **`reviewer`** reviews the resulting diff.

- **Two or more implementation agents running AT THE SAME TIME must each get
  `isolation: "worktree"`.** A file-scope fence written in a dispatch prompt is
  honour-based prose; a worktree is enforced. Concurrent agents sharing one
  checkout have already produced one incident (a `git restore` that reverted a
  parallel agent's uncommitted work — see Branching). Sequential dispatches into
  one tree are fine.

Agent roles and the skill table are defined once below (**Agent roster** and the
skills table) — this section does not duplicate them. `planner` is exempt: it is
reached only via the explicit `/createplan` flow, not general exploration.

The `PreToolUse` hook **hard-denies** `Explore` / `Plan` / `general-purpose`
Agent dispatches and redirects to the above. Set `WORKFLOW_HOOK_OFF=1` to bypass
it temporarily.

## Step 0 — Orient with the code graph (Graphify)

Before grepping for "where does X live", ask the graph. It is a real traversable
graph of every symbol in `engine/`, `game/`, `editor/`, `tools/` (~5k nodes /
~10k edges), built locally from tree-sitter ASTs — no LLM, no embeddings. Use it
to *locate* code and see call/import fan-out; then read the actual files. It
does not replace the package docs below.

```bash
graphify explain "place_building()"    # a symbol's neighbours, in/out edges
graphify path "BaseBuilding" "TileMap" # how two symbols connect
graphify affected "BaseBuilding"       # blast radius before you change a thing
graphify query "how is balancing json loaded?" --budget 800
graphify update .                      # rebuild after you add/move/delete code
```

Rules:
- **The graph rebuilds itself on every commit.** A `post-commit` / `post-checkout`
  git hook (`graphify hook install`) re-extracts *only the changed files* in a
  detached process, so `git commit` never blocks. You normally never run
  `graphify update` by hand. It logs to `~/.cache/graphify-rebuild.log` — check
  there if the graph looks stale. `GRAPHIFY_SKIP_HOOK=1 git commit …` skips it.
  The hook self-skips during rebase/merge/cherry-pick.
- **`graphify-out/` is generated and gitignored** — never hand-edit it, never
  commit it. If it is missing or stale, rebuild:
  `graphify extract . --code-only && graphify cluster-only . --no-label`.
- **Keep `GRAPHIFY_VIZ_NODE_LIMIT` above the node count** (set to 8000 at user
  scope; we are at ~5k). The viz caps at 5000 by default, and a rebuild that
  cannot regenerate `graph.html` *deletes* it rather than leaving it stale.
- **`--code-only` is deliberate.** Semantic extraction of `docs/`, `SPEC.md` etc.
  needs an LLM API key (`ANTHROPIC_API_KEY`/`GEMINI_API_KEY`); we don't set one,
  so the graph is code-only and community names are `Community N` placeholders.
  Node/edge data is unaffected — only the labels are cosmetic.
- The graph is a **map, not the source of truth.** `data/` JSON + the package
  docs still win; edges tagged `INFERRED` are guesses, `EXTRACTED` are literal.
- Install (once, per machine — `.git/hooks/` is not committed, so a fresh clone
  has no auto-rebuild until you run step 2):
  1. `uv tool install git+https://github.com/Graphify-Labs/graphify.git`
  2. `graphify hook install` — then build the first graph with the two commands
     in the rebuild bullet above.

## Step 1 — Classify the task, then read ONE package doc

| Package | Read this doc      | May edit (file scope)                          |
|---------|--------------------|------------------------------------------------|
| engine  | `engine/CLAUDE.md` | `engine/**`, `tools/` tests for engine          |
| game    | `game/CLAUDE.md`   | `game/**`, `data/balancing/*`                   |
| editor  | `editor/CLAUDE.md` | `editor/**`                                     |
| data    | `data/CLAUDE.md`   | `data/**` (schemas + validated content)         |

If a task truly spans two packages, tell the user — they decide whether you
read both docs. Within `game/`, the prototype's five balancing domains
(buildings / enemies / map / ui / core) still scope file ownership and
branch naming.

Each package doc is a **router** to per-subsystem docs
(`<package>/<subfolder>/CLAUDE.md`) that auto-load when you edit inside that
folder — read the ONE that matches your task, not the whole package.

### If your task matches one of these, INVOKE the skill — don't hand-roll it

These skills encode the full pattern (files to touch, order, verify gate) for
their task. When a request matches a row, **invoke the skill** rather than
editing by hand; it is the source of truth and keeps changes consistent. This
applies to dispatched subagents too — if a phase/brief hands you one of these
tasks, open with the skill.

| When the task is…                                  | Invoke            |
|----------------------------------------------------|-------------------|
| Add / create a building type                       | `/add-building`   |
| Add / create an enemy type                         | `/add-enemy`      |
| Add / change a balancing tunable                   | `/add-balancing-value` |
| Add an engine Component                             | `/add-engine-component` |
| Add an editor feature/panel                        | `/add-editor-feature` |
| Wire a new renderable category into asset import   | `/add-asset-importer` |
| Scaffold a new command/skill                       | `/add-skill`      |
| Add a new slot-registry category / balancing domain | `/add-category`  |
| Add a new "Add new X" FORM type (the meta-form)     | `/add-form-spec` |
| Replace a sprite/visual for an existing thing       | `/replace-visual` |

Most of these are **also forms** in the editor — the roster is
`data/agent_forms/*.json`, and that directory (not this table) is the source of
truth for what the launcher offers. `/add-skill` is skill-only; `/createplan` is
form-and-picker. Using a form: **Summon a Drunken
Robot** → *Add new X…* → fill the fields + the free-text box → Dispatch. The
editor writes a schema-validated handoff and opens a terminal on
`/dispatch <handoff>`, which runs the same skill unmodified, on a new branch off
`Development` (ending in a PR) or in place on the current branch — your choice in
the form (`planning/completed plans/AgentDispatchPLAN.md`). **Small tweak** and **Admin** are
unchanged.

Copy-paste task openers (that themselves point at these skills) live in
[`docs/prompt-templates.md`](docs/prompt-templates.md).

## Agent roster (`.claude/agents/`)

Orchestrator skills dispatch these **by name**; agents report upward with
provenance-tagged claims (see `/report`), and only orchestrators publish
artifacts. Scaffold a new one with `/add-agent`.

| Agent | Role |
|---|---|
| `scout` | Graphify-first discovery; returns `file:line` + the one pattern to copy (haiku, read-only) |
| `coder` | Generic implementer for game/editor/data tasks; opens with the matching skill above |
| `engine-coder` | Engine specialist, scoped to `engine/**` + engine tests; layering invariants baked in |
| `planner` | Phased plan docs + phase briefs in the house shape; never implements |
| `reviewer` | Read-only diff review against brief + design pillars; ranked findings |
| `phase-executor` | Unattended single-phase execution from a brief; never re-plans |

## Data source of truth
`data/` JSON is the ONLY value store (no py+json dual system — do not
reintroduce it). Every file validates against `data/schemas/`. Write through
the validating writer; formatted deterministically (sorted keys, 2-space
indent). ×10 combat HP/DMG scale carries over from the prototype; `BASE_HP`
stays 10 (deliberate exception).

## Step 2 — Universal exit gate

```bash
py tools/smoke.py          # data validation + 5-frame headless boot
py tools/testgate.py check # the suite. Read the ONE line it prints.
```

**The gate is ZERO.** `GATE PASS` or you are not done. There is no baseline to
measure and no "pre-existing failure" to tolerate — if a test is red, you broke
it. (It was not always so: the suite used to carry 18 permanent failures and the
gate was a *diff* against a number that lived in prose and had drifted three
ways. `planning/TestGatePLAN.md` records how that was fixed.)

- **Never re-run the suite to find out what was already broken.** That waste is
  exactly what `/testgate` deletes.
- While iterating, `py tools/testgate.py check --affected` runs only the blast
  radius of your diff (Graphify) ∪ the `core` tier. Run the **full** check once
  before handing work back.
- **Do NOT run the full suite for verification unless explicitly asked or you
  are handing work back.** `--affected` is the default; the full `check` runs
  exactly once, at the end — never as a mid-task sanity run, never twice.
- **A red test clearly outside your diff's blast radius: note it in your report
  and stop** — do not burn the session investigating it. The gate is still ZERO
  (it must be resolved before handoff), but the first move is to surface it to
  the user, not to silently dig.
- Tiers: `py -m pytest -m core` (fast, ~800) · `-m editor` (Qt, slow) ·
  `-m meta` (agent scaffolding). **CI runs the whole suite** — there is no
  excluded tier. (The old `migration` tier compared `data/` against the
  prototype checkout; it is deleted along with the migration.)
- **An unexpected skip is a failure.** A test that quietly stops running is
  indistinguishable from one that passes. **So is a failing subtest** — the gate
  reads pytest's `SUBFAILED` lines, which it once ignored while printing PASS.
- Never paste raw gate output into a report — collapsing it to one line is the
  whole point.

Then:
1. Report exactly what you verified, tagging each claim **measured** (command +
   number) / **verified** (read or ran it) / **inferred** (flagged as such) —
   the `/report` taxonomy.
2. If data changed: confirm schema validation passes.
3. If anything architectural changed: update **the package CLAUDE.md** — not
   this router, not another package's doc.
4. PRs state a concrete in-game Quick Test scenario. On the user's
   confirmation: commit (brief msg) → push → PR. CI (`.github/workflows/
   tests.yml`) gates every PR into `Development`.

**Tests must never write into `data/`.** Copy it to a tempdir (`TempDataCase`).
A session fixture hashes `data/` before and after the suite and fails the run if
it changed — the suite used to corrupt the repo silently, and now it cannot.
**Never assert against live `data/` content**: pin the fixture. Tests that
assumed "this slot has no art" or "this map is active" is what put 18 tests
permanently in the red.

## Branching

The old branch+lock protocol is **REMOVED** (its successor is a future,
separate design — nothing enforces domain locks today).
- One branch per phase/feature off `Development`; land via PR.
- **Never run destructive git on uncommitted work:** no `git reset --hard`,
  `git clean`, `git checkout -- <file>`, **`git restore`**, `git stash`,
  force-push. `git restore` is the modern spelling of `git checkout -- <file>`
  and was missing from this list until an agent used it to "clean up" its own
  mistake and silently reverted a *parallel* agent's uncommitted work, then
  reported the resulting 177 failures as someone else's pre-existing bug.
  **HEAD is not a safe restore point** — the tree routinely holds uncommitted
  work from other agents or the user. Undo by editing FORWARD.
- Never commit `build/`, `dist/`, or any `*.exe` (gitignored — keep it that
  way).
