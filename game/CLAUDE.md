# CLAUDE.md — GAME package

Self-contained guide for `game/` — How To Be Human itself, built on `engine/`.
You reached here from the root router. Requirements: SPEC.md §6 (`G-*`).
Behavior source: the prototype repo
(`../HowToBeHuman/ClaudePrototype/HowToBeHuman`) — what the prototype does is
the required behavior unless SPEC.md says otherwise. **When you change game
architecture/conventions, update THIS doc.**

## File scope you may edit
`game/**` and `data/balancing/*` (lock rules apply — check `_lock` first).
Never import or edit `editor/**`. Engine changes are a cross-package task —
tell the user.

## Layout & domains
- `main.py` — the ONLY entry point (`py game/main.py`): pygame window, engine
  loop, input routing.
- `map/` · `buildings/` · `enemies/` · `core/` · `ui/` — these mirror the
  prototype's five balancing domains, which still scope branches and locks
  (`/start-domain buildings` etc.).

## Host conventions (`main.py`, Phase 2)
- `main(max_frames=None)` is importable so `tools/smoke.py` can drive the
  same code headlessly (G-8); `py game/main.py` runs it windowed.
- Frame order is fixed per E-14: input → `Scene.update(dt)` →
  render submit (grid tiles + `scene.render_items()`) → `flush` → `flip`.
- **Camera input mapping (E-5) lives here**, on pure engine camera state:
  right-click-drag pans (`cs.pan` + `cs.clamp` to map bounds); scroll
  wheel steps through the data-driven `geometry.json` zoom levels, keeping
  the viewport-centre world point fixed via `screen_to_world`/
  `world_to_screen` only (no iso math in the host); Esc quits.
- Window size / fps / caption come from `data/display.json`
  (schema-validated, G-7) — never hardcode them.
- **Active map (Phase 6, D-20/D-21)**: boot loads
  `engine.tilemap.load_active_map(data_dir)` (follows
  `data/maps/active_map.json`) and builds coords with THE MAP's dims
  (`load_coordinate_system(data_dir, map_cols=…, map_rows=…)`). The whole
  static map (tiles with prototype checkerboard parity, base on
  `entities`, deco on `deco` above entities per E-26) comes from
  `engine.tilemap.render_items(doc)` — precomputed once, submitted every
  frame. Invalid map data fails LOUD (D-2); the E-37 log-and-placeholder
  tolerance covers ART only. Since 9D the host builds a `TileMap` +
  `engine.physics.TileOccupancy`, attaches the `BaseBuilding` to its tile, and
  places a demo Defender + Musician via `game.buildings.place_building`
  (the dummy entities are gone). Since 9E the host also builds a `Spawner` and,
  each frame, runs `spawner.update(dt, scene)` → `scene.update(dt)` →
  `game.enemies.resolve_combat(...)`; pressing **`N`** calls
  `spawner.begin_round(++round_num, …)` to spawn a wave (temporary — the real
  round loop is 9F).

## Conventions
- Game classes subclass `GameObject` but keep ALL state in components (engine
  rule) — the editor's inspector and save/load depend on it.
- No pygame calls in gameplay logic; visuals are submitted as RenderItems via
  `SpriteAnimator`. HUD/menus may use the direct HUD layer (G-6).
- Every tunable comes from `data/balancing/` at startup (G-7). If you need a
  new constant, add it to the domain's JSON + schema — never hardcode.
  ×10 combat HP/DMG scale applies; `BASE_HP` stays 10.
- Combat-capable buildings advertise capability via components/tags (the
  prototype's `IS_COMBAT` contract) — core sweeps must stay type-agnostic.
- Phase machine + income ordering (snapshot → income → upkeep → painters →
  revive → cleanup) is prototype-exact (G-5); do not reorder without the user.

## Map runtime (`map/`, Phase 9C)
Runtime layer over an `engine.tilemap.TileMapDoc` (never re-parse map JSON):
`tiles.py` (`Tile`, `TileState`, `TileCondition`), `tile_map.py` (`TileMap`),
`pathfinder.py`, `picking.py`. Ports the prototype's `src/map/*` behaviour.
Conventions that differ from the prototype (deliberate, clean-arch):
- **Zones seed from the map file's terrain codes**, not procedural rings —
  `b`→BUILDABLE, `c`→COMBAT, `s`→SPAWNING, `f/l/o`→BACKGROUND, `doc.base`
  tile→BUILT. The map file is the source of truth. Unlock sections + the
  playfield window anchor at the base corner (`base_col/row` .. `dim-1`).
- **Pathfinding weight is content-key driven, not `isinstance(Building)`**:
  each tile resolves to a key in `map.json` `Pathfinding.content_weights`
  (empty tiles from their zone; occupied tiles carry the key set at placement).
  Composition order is PROTOTYPE-EXACT: base → +condition (`path_weights`) →
  +defence-range coverage → ×damage discount, all gated `0 < w < impassable`.
- **Picking goes through `engine.coords` only** (`screen_to_world` + floor) —
  no iso math in `game/`.
- **Balancing** now loads through `game/core/balance.py`
  (`load_balance(data_dir, domain)`, the single validated loader for all five
  domains — 9D); `load_map_balance` is a thin shim over it, kept for the
  re-export + tests. `TileMap(doc, balance)` still takes the dict so tests can
  inject fixtures.
- **Dormant hooks, ported but fed neutral** until their producers land:
  tile conditions (all GRASS → +0, random roll in **10I**), damage-weight
  reduction (`set_round`/`refresh_damage_weight_reductions` present, no building
  damage yet, **10F**), defence-range coverage (`_defence_coverage_fn`=None,
  add value from the *buildings* domain, **10I**), walls (`get_wall_between`→
  None, so `find_path_ignoring_walls` == `find_path`, **10E**), and the four
  building-targeting `find_path_*` variants (goal by occupant `building_type`;
  no occupants yet → all fall back to `find_path`).
- **Occupancy sync is occupant-driven**: `TileMap.sync_occupancy(occupancy)`
  mirrors tiles with a GameObject occupant into `engine.physics.TileOccupancy`
  (BACKGROUND impassability is a weight concern, not occupancy). In 9C nothing
  occupies a tile yet (the base has no GameObject) → it clears everything; 9D
  wires real occupants through this one seam.

## Buildings (`buildings/`, Phase 9D)
`Building(GameObject)` hierarchy; 9D ships the Musician (economy) + Defender
(defence) lines + the untiered `BaseBuilding`. Ports the prototype's
`src/buildings/*`. Rules:
- **All state in components** (E-11): `components.py` holds `TierState`
  (building_type + tier/level cursor), `Nameplate` (rebirth chain), `RoundStats`
  (per-round damage), `Attacker` (defence combat marker), `YieldEconomy`
  (economy marker); plus engine `Health` / `SpriteAnimator` / `RangeSensor`. The
  duck-typed values `game/map` reads — `alive` / `building_type` /
  `damage_dealt_last_round` — are guard-safe `@property`s backed by those
  components (never plain instance attrs); the balancing dict + tier table live
  as `_`-prefixed transients.
- **Derived values are computed methods on the parents**, never stored (prototype
  `update_stats_from_tier`): `max_hp`, `upgrade_cost`, `level`, `yield_amount`
  (economy), `damage`/`upkeep`/`range_tiles`/`attack_speed` (defence). Formulas
  are `base + (level_in_tier-1)*per_level`; **every `upgrade()`/`advance_tier()`
  full-heals** (sets hp = max_hp). Leaves are ≤ ~10 lines: `SUBTREE` path into
  `buildings.json`, `BUILDING_TYPE`, `TIER_SPRITES` prefixes.
- **Values come from `data/balancing/buildings.json`** (the 9A REPLAN tree —
  authoritative; the prototype `.py` defaults drifted). ×10 combat scale is baked
  in; `BaseBuilding` HP is `core.json TheHole.base_hp` = 10 (the NOT-×10
  exception). The base carries **no SpriteAnimator** — its sprite is the static
  map render (`doc.base` slot), so attaching one would double-draw.
- **Attacker + `"combat"` tag replace the prototype `IS_COMBAT` flag** (SPEC G-3)
  so the combat sweep stays type-agnostic. 9D wires the seam (RangeSensor range
  from the tier, an Attacker clock) but NO enemy acquisition/damage — that is 9E.
- **`registry.py` is the factory + placement seam**: `create(building_type,…)`
  (also reconstructs a subclass after `GameObject.from_dict`), and
  `place_building(tilemap, tile, type, love, …)` — buildable-tile +
  affordability gate → sets `tile.occupant/content_key/state` → `scene.spawn` →
  `sync_occupancy` (raises `PlacementError` on a bad tile / too little love).
  `attach_base` wires the `BaseBuilding` onto its pre-seeded tile. Love is passed
  in (no game-state store until 9F); UI batching + per-type unlock gates are
  9F/9G.

## Enemies (`enemies/`, Phase 9E)
`Enemy(GameObject)` walker + `Spawner` + a type-agnostic combat sweep, porting
the prototype's `src/enemies/*` and `game.py` enemy/spawn/combat loops. 9E ships
the **Standard** walker; `Raider`/`SiegeCannon`/`Boss` (+`BossState`) are thin
subclasses present for the spawner's branches but NEVER emitted (`spawner.py`
`ENABLE_RAIDERS`/`ENABLE_SIEGE`/`ENABLE_BOSS = False`; 10F/10G flip them). Rules:
- **All state in components** (E-11): `components.py` holds `PathAgent`
  (navigation + the block-and-attack decision) and `EnemyCombat` (attack stats +
  the attack-a-blocking-building clock); engine `Health`/`Movement`/
  `SpriteAnimator`/`RangeSensor` carry the rest. The duck-typed values the combat
  sweep reads (`alive`/`dmg`) are guard-safe `@property`s.
- **`PathAgent` runs BEFORE `Movement`** in the component list so its halt
  decision takes effect the same frame (no drift into a blocked tile). It gates
  locomotion by zeroing `Movement.speed` while blocked and restoring it on
  unblock — the path (`Movement.waypoints`) is NEVER discarded, so no re-path is
  needed when the blocker dies (the route already runs through that now-passable
  tile). It caches the map as `PathAgent._tilemap` — a deliberate
  environment-reference transient, exactly like `Movement._owner`.
- **Locomotion is fractional tile coords**: `move_speed` (tiles/sec) feeds
  `Movement.speed` straight — no ×32 pixel conversion (that was the prototype's
  pixel space); `find_path` output `[(col,row)…]` becomes `[[float(c),float(r)]…]`
  waypoints. Base arrival = `Movement.arrived` → `PathAgent.reached_base`.
- **Scale-tier stats resolved at CONSTRUCTION** (prototype `enemy.py:88-108`):
  hp/dmg/speed = type base + cumulative sum of `EnemyScaling.scale_tiers[0..tier)`;
  tier = `(round-1)//scale_every_n_levels`. Values from
  `data/balancing/enemies.json` (×10 combat scale baked in).
- **Sprite slots are registry-group driven with a random variant per spawn**
  (prototype `_STAGE_SLOT_PREFIX` + `_variant`): each class names its
  `data/slots.json` enemies group via `REGISTRY_GROUP` (`"Walker"`/`"Raider"`/
  `"Siege Cannon"`/`"Boss"`). That group's era subchildren are ordered; the
  enemy's `tier` clamps to an era index and `variant_slot()` picks a random
  slot from that era via the spawner's injected `rng` — so a walker rolls
  between `enemy_stage_1_v1`/`_v2` on spawn, and dropping a new `_v3` slot into
  the era (editor) grows the pool with NO code change. The registry + rng are
  threaded `main.py → Spawner.begin_round → create_enemy`; absent a registry
  (headless stat/logic tests) each class falls back to its `DEFAULT_SLOT`. The
  Walker/Raider eras map to the prototype `*_stage_N` sheets (NOT the
  procedural `*_t2..t4`); Siege/Boss keep their tier/era sheets.
- **`spawner.py` = the wave queue** (prototype `_begin_enemy_phase` /
  `_update_enemy_phase`): `begin_round` composes the standard count
  `base_enemy_count + (round-1)*(enemies_per_round + tier)` with the exact ramp +
  `uniform(0.4, 1.6)` jitter; `update(dt, scene)` pops ONE enemy per timer expiry
  into `scene.spawn`. The round LOOP that calls it + wave-clear detection is 9F;
  an injectable `rng` keeps tests deterministic.
- **`combat.py` = the type-agnostic sweep** `resolve_combat(scene, tilemap, dt,
  buildings_balance)`, called each frame AFTER `scene.update`: (1) every
  `"combat"`-tagged building keeps its sticky target if alive + in Chebyshev
  range, else acquires the nearest in-range enemy by Euclidean distance, and on
  cooldown fires a `Projectile` — the reset interval clamped to
  `DefenceBuildings.globals.min_attack_speed`; (2) an enemy with
  `PathAgent.reached_base` subtracts its `dmg` from the base's `Health` and
  despawns; (3) dead enemies despawn. This is the FIRST writer of `RoundStats`
  (`dmg_dealt_this_round` on shooters, `dmg_taken_this_round` on targets).
- **Projectiles travel then deal GUARANTEED damage** on arrival if the target is
  still alive (prototype `Projectile`): a shot in flight is wasted only if its
  target dies first — never a collision/accuracy miss. Travel time = `distance /
  DefenceBuildings.globals.projectile_speed_tiles` (new 9E key = 3.75 = prototype
  120 px/s ÷ 32). Logical GameObjects with no sprite in 9E — projectile/muzzle/
  blood art is the 10J FX sweep.
- **Deferred to 9F+**: base lives-mode / game-over / round wipe, the round loop
  and love economy, XP-per-kill + floaters (10A). Terrain/wall/death-swarm hooks
  stay dormant.

## Porting protocol (PLAN phase 9+)
Port one domain at a time, prototype as spec: acceptance checklist → runnable
test → implement → iterate until green → live playtest. State what you
verified (smoke test vs live round vs static read).

## Verify before finishing
Headless smoke test (`tools/smoke.py`) after every change; live
`py game/main.py` round for phase/combat/UI behavior. If balance changed:
schema validation passes, lock respected.
