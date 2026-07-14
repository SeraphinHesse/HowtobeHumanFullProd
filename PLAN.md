# PLAN.md — no active plan

> **There is no active plan right now, and that is a valid state.** This file is
> a generated mirror: when a plan is active, line 1 carries an
> `<!-- active-plan: … -->` marker and the rest is that plan's body, verbatim.
> It carries no marker today, so the editor's **Summon a Drunken Robot** screen
> shows "— none set" and agents should read this page instead of hunting for
> phases that no longer exist.

## Where the project is

**The migration is COMPLETE.** The port from the prototype landed; the game
(`py game/main.py`) and the editor (`py editor/main.py`) both run, `data/` is
the only value store, and nothing in the test suite compares against
`../HowToBeHuman` any more. That plan is archived at
`planning/completed plans/MIGRATION_PLAN.md` — read it as history, never as
instructions.

## How work is chosen now

The project is in a **feature-rework / feature-expansion / editor-capability /
asset-import** phase, and work arrives one of two ways:

- **Per task.** A small, self-contained change — a tweak, a new building or
  enemy, a balancing value, a sprite import. Use the matching skill from the
  root `CLAUDE.md` table (`/add-building`, `/add-enemy`, `/replace-visual`,
  `/smalltweak`, …) or the editor's *Add new X…* forms. No plan doc, no phases.
- **Per plan doc.** Anything that needs phases gets its own doc in `planning/`
  via `/createplan`, and becomes the active plan (`/setcurrentplan <name>`) for
  as long as it runs — at which point this file mirrors it.

There is no master plan any more, and nothing should be invented to fill this
page. Balancing values are free: the prototype-parity gate is gone, so a number
that differs from the prototype is a design decision, not a regression.

## Plans in `planning/`

Sources of truth; none currently active. `BossPathfindingPLAN.md` and
`EnemyReworkPLAN.md` are unfinished and each now opens with a banner voiding the
parity obligations the migration used to impose. `UI_EDITOR_PLAN.md` is
unfinished and unaffected. `TestGatePLAN.md` is already EXECUTED, kept for the
record (root `CLAUDE.md` cites it).

Activate a plan with `/setcurrentplan <name>` (or the editor's Summon a Drunken
Robot screen), which regenerates this file as its mirror. Finished plans move to
`planning/completed plans/`.

**Never hand-edit this file** — edit the source in `planning/` and re-mirror.
