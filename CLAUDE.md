# CLAUDE.md — Router

First-read router for agents on **How To Be Human — Full Production**
(isometric tower-defence; you spend *love* to unlock tiles and place
musicians/defenders that protect "the hole" from enemy waves). This file stays
slim: it routes you to ONE package doc. Plan & phase status → `PLAN.md`.
Requirements → `SPEC.md` (referenced as E-*/D-*/G-*/ED-*/T-*).

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
