---
description: Use when the task is to add or create a new enemy type. Produces a thin Enemy subclass + spawner branch + scale-tier stats + registry-group slots, following the 10F/10G pattern.
argument-hint: <enemy name + behavior, e.g. "Siege Cannon (ranged, targets buildings)">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*)
---

Add a new enemy: **$ARGUMENTS**. This follows the migration plan's 10F/10G pattern
(enable a spawner branch + a thin subclass; `Raider`/`SiegeCannon`/`Boss` already
exist as zeroed stubs).

## Read first (token-light)
1. `game/enemies/CLAUDE.md` — all-state-in-components, scale-tier stats resolved at
   construction, `REGISTRY_GROUP`-driven variant slots, the spawner wave queue.
2. The closest existing subclass (the zeroed `Raider`/`SiegeCannon`/`Boss` stubs, or
   the `Standard` walker).

## Steps
1. **Subclass** `Enemy(GameObject)` — keep it thin: `ETYPE`, `REGISTRY_GROUP`
   (`"Walker"`/`"Raider"`/`"Siege Cannon"`/`"Boss"`), `DEFAULT_SLOT`,
   `HP_BAR_W`/`HP_BAR_H` (overhead HP-bar px — override only if the sprite is
   bigger than a walker's; the base 14×2 is the default), component
   wiring (`PathAgent` + `EnemyCombat` + engine `Health`/`Movement`/`SpriteAnimator`/
   `RangeSensor`). **All state in components**; the duck-typed `alive`/`dmg` are
   guard-safe `@property`s. `PathAgent` runs BEFORE `Movement` in the component list.
2. **Balancing** — add the type's block to `data/balancing/enemies.json`
   (`EnemyTypes` + any `EnemyScaling` tiers/`era_sizes`/`round_counts`) and mirror it
   in `data/schemas/enemies.schema.json`. ×10 combat scale. Struct-lists
   (scale_tiers, boss eras) keep their shape. Stats are resolved AT SPAWN from type
   base + cumulative scale-tier sum — don't bake per-round numbers into the class.
3. **Spawner branch** — flip the branch flag in `game/enemies/spawner.py`
   (`ENABLE_RAIDERS`/`ENABLE_SIEGE`/`ENABLE_BOSS`) and wire the count/composition per
   the prototype's queue logic. Keep the injectable `rng` for deterministic tests.
4. **Slots** — add the registry group's era subchildren to `data/slots.json` so
   `variant_slot()` can roll a random variant per spawn; grey-X until art imports.
5. If pathfinding/targeting differs (siege targets buildings, boss cutscene), use the
   dormant `find_path_*` variants / reserved payday slots already ported — don't add
   new cross-domain coupling; `game/enemies` imports NO `game/core` (use the
   `on_base_hit`/`on_enemy_death` callback pattern).

## Perf note
`Enemy.on_spawn` runs one `find_path` Dijkstra per enemy — fine at current scale but
the known large-map frontier. If you're adding a high-count swarm, read
`game/PERF.md` first (the shared flow-field fix is the intended direction).

## Verify
- Headless: a scripted round asserts the HP ledger matches hand-computed prototype
  values: `py tools/testgate.py check --affected` (targeted; the single full
  check happens at handoff, per CLAUDE.md Step 2).
- Data: `py tools/smoke.py`.
- Live: `py game/main.py` — reach the round that spawns it; confirm spawn, movement/
  pathing, damage/death, and wave integration.

## Final report
- Changed files; the type + which spawner branch; verification performed; whether
  `game/enemies/CLAUDE.md` needed a durable-rule update.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
