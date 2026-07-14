# CLAUDE.md — Router

First-read router for agents on **How To Be Human — Full Production**
(isometric tower-defence; you spend *love* to unlock tiles and place
musicians/defenders that protect "the hole" from enemy waves). This file stays
slim: it routes you to ONE package doc. Plan & phase status → `PLAN.md` (the
**active-plan mirror** — see below). Requirements → `SPEC.md` (referenced as
E-*/D-*/G-*/ED-*/T-*).

**Planning:** every plan doc lives in `planning/` (the sources of truth:
`MIGRATION_PLAN.md`, `EngineBuildPLAN.md`, `AgentDispatchPLAN.md`,
`UI_EDITOR_PLAN.md`, …). Root `PLAN.md` is a **generated mirror** of whichever
one is currently active (its line-1 `<!-- active-plan: … -->` marker names the
source). Read `PLAN.md` for the current plan; never hand-edit it — edit the
source in `planning/` and re-run `/setcurrentplan <name>` to re-mirror. Author a
new phased plan with `/createplan`. The editor's **Summon a Drunken Robot**
screen shows the active plan and can switch it too.

## Project identity & status
- **Stack:** Python 3.11+, pygame-ce (game), PySide6 (editor). Deps:
  `pip install -r requirements.txt`.
- **Status:** bootstrap phase — see the phase table in `PLAN.md` before
  assuming anything is runnable. Entry points (once they exist):
  game `py game/main.py`, editor `py editor/main.py`.
- **Behavioral spec for gameplay:** the prototype repo at
  `../HowToBeHuman/ClaudePrototype/HowToBeHuman`. Read it to answer "what
  should this do"; never edit it from here.

## Design pillars (tie-breakers for every decision)
1. **Agent legibility** — small single-purpose files; schemas over convention;
   no editor-only hidden state.
2. **Strict layering** — game logic never touches pygame; `editor/` and
   `game/` never import each other; both consume `engine/` and `data/`.
3. **Editor is the designer interface** — humans never hand-edit `data/`
   JSON; agents may, but only schema-valid writes.

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
| game    | `game/CLAUDE.md`   | `game/**`, `data/balancing/*` (lock rules apply)|
| editor  | `editor/CLAUDE.md` | `editor/**`                                     |
| data    | `data/CLAUDE.md`   | `data/**` (schemas + validated content)         |

If a task truly spans two packages, tell the user — they decide whether you
read both docs. Within `game/`, the prototype's five balancing domains
(buildings / enemies / map / ui / core) still scope locks and branches.

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
the form (`planning/AgentDispatchPLAN.md`). The dialog's old **`/start-domain`
mode is gone** (the lock protocol is suspended); **Small tweak** and **Admin**
are unchanged.

Copy-paste task openers (that themselves point at these skills) live in
[`docs/prompt-templates.md`](docs/prompt-templates.md).

## Data source of truth
`data/` JSON is the ONLY value store (no py+json dual system — do not
reintroduce it). Every file validates against `data/schemas/`. Write through
the validating writer; formatted deterministically (sorted keys, 2-space
indent). ×10 combat HP/DMG scale carries over from the prototype; `BASE_HP`
stays 10 (deliberate exception).

## Step 2 — Universal exit gate
1. Run the smoke test (`tools/smoke.py` once it exists; headless SDL dummy
   drivers) → report exactly what you verified — smoke test, live run, or
   static read only.
2. If data changed: confirm schema validation passes.
3. If anything architectural changed: update **the package CLAUDE.md** — not
   this router, not another package's doc.
4. PRs state a concrete in-game Quick Test scenario. On the user's
   confirmation: commit (brief msg) → push → PR.

## Branch + lock protocol

> ⚠️ **TEMPORARY OVERRIDE (migration in progress) — read first.**
> The branch + lock protocol below is **SUSPENDED** for all Claude agents.
> It is no longer compatible with the engine migration and will be
> redesigned *after* the project is migrated to the new engine setup.
> Until this flag is removed:
> - **Ignore branch lock protocol entirely** — do not run `/start-domain` /
>   `/merge-domain`, do not set/clear `_lock`, do not treat any domain as
>   LOCKED.
> - For each new phase of the engine creation plan (`PLAN.md`) or the
>   `MIGRATION_PLAN.md`, simply **create one new branch for that phase** and
>   work on it.
> - The "never run destructive git on uncommitted work" and "never commit
>   `build/`/`dist/`/`*.exe`" rules below **still apply**.

Ported from the prototype (commands land in `.claude/commands/`, PLAN phase 8):
- `/start-domain <domain>` → lock that domain's `data/balancing/*.json`
  `_lock`, branch `feature<Domain>`.
- `/merge-domain <domain>` is the ONLY place a lock clears.
- **Invariant:** while a `feature<Domain>` branch exists, that domain stays
  LOCKED.
- **Never run destructive git on uncommitted work:** no `git reset --hard`,
  `git clean`, `git checkout -- <file>`, force-push.
- Never commit `build/`, `dist/`, or any `*.exe` (gitignored — keep it that
  way).
