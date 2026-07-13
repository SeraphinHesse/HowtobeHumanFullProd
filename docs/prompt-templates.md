# Low-token prompt templates

Reusable task openers for Claude Code sessions on this repo. They point the agent
at the ONE subsystem doc to read and the skill to invoke, so a session doesn't
re-read the whole codebase. Copy a block, fill the `[brackets]`, delete the rest.

The routing chain is always: **root `CLAUDE.md` → the package router → the ONE
subsystem doc → a few source files → narrow edit → narrow verify.** Sub-docs
(`<package>/<subfolder>/CLAUDE.md`) auto-load when the matching files are edited.

---

## Add a building

```txt
Add a new building: [name] ([defence/economy/boost/structure]).
Behavior: [what it does].

Use the /add-building skill. Read game/buildings/CLAUDE.md first; don't scan
enemies/ui/asset folders unless the building touches them.

Acceptance:
- leaf class ≤ ~30 lines (parents compute derived stats), research row added,
  buildings.json + schema mirror + slots.json group in place
- headless tier-max test green, py tools/smoke.py OK, live: build + upgrade works
```

## Add an enemy

```txt
Add a new enemy: [name]. Behavior: [movement/targeting].

Use the /add-enemy skill. Read game/enemies/CLAUDE.md first. If it's a high-count
swarm, also read game/PERF.md (per-spawn pathfinding).

Acceptance:
- thin subclass, spawner branch enabled, scale-tier stats resolved at spawn,
  slots added; scripted-round HP ledger matches the prototype; smoke OK
```

## Add / change a balancing value

```txt
Add a tunable: [domain] — [value].

Use the /add-balancing-value skill. Touch only data/balancing/[domain].json +
data/schemas/[domain].schema.json; the editor form renders it for free.

Acceptance: schema-valid (py tools/smoke.py), respects the domain _lock, ×10 scale
where applicable.
```

## Port a prototype domain/feature (phase 9x/10x)

```txt
Port [feature/domain] from the prototype (../HowToBeHuman/ClaudePrototype/
HowToBeHuman) — prototype behavior is the spec.

Read game/CLAUDE.md "Porting protocol" + the target domain's game/<domain>/
CLAUDE.md. Follow: acceptance checklist -> runnable test -> implement -> iterate
green -> live playtest. Payday ordering is SACROSANCT (don't reorder without me).

Acceptance: per-phase Quick Test from planning/MIGRATION_PLAN.md, live; state
what you verified (smoke vs live round vs static read).
```

## Fix a bug

```txt
Fix: [symptom + repro].

Start in the likely subsystem: [game/<domain> | engine/<sub> | editor]. Read that
one CLAUDE.md, reproduce/explain the cause, make the smallest fix. If it's a
large-map slowdown, read game/PERF.md before touching any hot path (tile-state
writes, occupancy, ground cache).

Acceptance: minimal fix, narrow verification (unit test or live run), no reordering
of payday / no bypass of TileMap.set_tile_state.
```

## Add an editor feature

```txt
Add editor feature: [feature].

Use the /add-editor-feature skill. Read editor/CLAUDE.md + editor/panels/CLAUDE.md.
Hang it off the single selection, one render path (ED-22), writes via
write_validated, add the module to test_editor_viewport.TestPurity.

Acceptance: py editor/main.py exercise (or QT_QPA_PLATFORM=offscreen), JSON
validates, a Play subprocess loads it.
```

## Add an engine component

```txt
Add engine component: [name] holding [state].

Use the /add-engine-component skill. Read engine/core/CLAUDE.md. Declared JSON-safe
fields only, on_added owner seam, keep the module pure (no pygame), add to
TestPurity.

Acceptance: serialization round-trip + behavior test green.
```

## Switch the active plan

```txt
Make [PLAN_NAME] the current plan.

Use the /setcurrentplan skill with planning/[PLAN_NAME]. It mirrors that plan
into the root PLAN.md (line-1 active-plan marker + verbatim body); CLAUDE.md,
agents, and the editor's Summon a Drunken Robot screen all follow it.

Acceptance: root PLAN.md line 1 names the chosen plan; body matches the source.
```

## Create a new plan

```txt
Draft a new phased plan: [name] — [one-line purpose].

Use the /createplan skill (the planning agent). It reads a sibling in planning/
to match the plan-doc family shape (Context -> numbered sections -> phase table
with a Status column -> per-phase Goal/Files/Tests/Exit-gate -> Risks), then
writes planning/[Name]PLAN.md. Optionally /setcurrentplan it afterwards.

Acceptance: planning/[Name]PLAN.md exists with a phased build-order table.
```

---

### General token discipline
- Read at most ~5 source files before proposing a plan; if you need more, say why.
- Don't read `dist/`/`build/` (denied) or asset binaries for a logic task.
- Update a subsystem `CLAUDE.md` only when a durable invariant / file path /
  workflow changed — not for session notes.
