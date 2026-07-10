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
  **both left- and right-click-drag pan** (`cs.pan` + `cs.clamp` to map
  bounds). Left-drag pans only when the press began over the world (not a
  panel/HUD button) and is gated by the same 4px drag threshold that
  separates a click from a drag, so a short left click still selects/places
  a tile while a left-drag moves the camera (`pan_from` tracks this).
  Scroll wheel steps through the data-driven `geometry.json` zoom levels,
  keeping the viewport-centre world point fixed via `screen_to_world`/
  `world_to_screen` only (no iso math in the host); Esc opens pause.
- Window size / fps / caption come from `data/display.json`
  (schema-validated, G-7) — never hardcode them.
- **Tile-state index (perf, THE static-camera large-map fix)**: `TileMap`
  keeps an incremental `_by_state` index (`{TileState: set()}`), so
  `built_tiles()`/`buildable_tiles()`/`spawning_tiles()` are **O(result)**, not
  a full `rows×cols` scan. This is what fixed a 1024² map running at ~2 fps
  *even with a static camera* (and in the editor's Play): the in-round HUD
  (`game/ui/hud.py`) calls those queries several times **per frame** (income
  breakdown + tile counter), which on a 1024² map was ~4 full-map scans ×
  ~1M cells ≈ **630 ms/frame** (measured) — dwarfing all render cost. The
  editor's map *viewport* builds no `TileMap` and has no HUD, so it never paid
  this (it rendered the same map at ~20 fps), which is what isolated the cause.
  **INVARIANT: every tile-state write goes through `TileMap.set_tile_state`**
  (the only place `_by_state` is kept consistent) — `do_unlock`, spawn recede,
  building placement (`game/buildings/registry.py`), and the base seed all route
  through it. `Tile.state` stays a plain `__slots__` attribute so *reads* (the
  pathfinding hot path) pay no property overhead; only writes are routed. A
  consistency unit test (`test_tile_unlock.TestStateIndexConsistency`) pins the
  index == a brute-force scan across seed/unlock/recede.
- **Event-driven full-map scans removed (perf, large-map hitch cleanup)**: two
  routine-play actions used to scan all ~1M tiles on a 1024² map (a multi-hundred-
  ms freeze each), now O(local):
  - **Placement occupancy is incremental** — `place_building`/`attach_base`
    (`game/buildings/registry.py`) call `occupancy.set((col,row), building)` for
    the one tile that changed instead of the full-map `TileMap.sync_occupancy`
    scan. `sync_occupancy` is kept only as a from-scratch full rebuild (not on the
    placement path). Buildings are add-only in the current phases, so a single-tile
    `set` is exact; a remove/sell seam would `occupancy.clear` its tile likewise.
  - **`TileMap._find_2x2` (spawn-recede on unlock) uses an expanding-window
    search** — the nearest matching 2×2 is almost always a few tiles from the
    reference, so it scans a doubling Chebyshev window (`_scan_2x2` inner) and
    accepts only once the window provably contains the global nearest
    (`best_d ≤ (radius−2)²`), with the whole-map window as the terminating
    fallback. Output is byte-identical to the old full scan (same
    nearest-by-squared-distance pick, same first-row-major tie-break, same
    `min_ring`); pinned by `test_tile_unlock.TestFind2x2WindowedMatchesFullScan`
    (40×40 map vs an inlined brute-force oracle) plus the existing exact recede-
    coordinate tests.
- **Next known large-map frontier — per-spawn pathfinding (NOT yet done)**:
  `Enemy.on_spawn` runs a full `find_path` Dijkstra to the base **per enemy**
  (`game/enemies/enemy.py`), which is O(reachable tiles) — the dominant cost when
  hundreds of enemies spawn on a huge map (staggered, so a per-spawn micro-hitch,
  not a sustained fps drop). The intended fix is a single shared reverse-Dijkstra
  "flow field" from the base, recomputed once per wave / map-topology change and
  reused by every enemy, instead of one Dijkstra per spawn. Left for a dedicated
  pass — it touches path-equivalence, the wall hook, and the goal-set variants.
- **Large-map GC (perf)**: a big map builds one `Tile` per cell (a 1024²
  map = ~1M long-lived objects). Left alone, Python's cyclic GC periodically
  walks that whole static grid (an 80–140 ms stall that *scales with map
  size*). After each `build_gameplay`
  the host calls `gc.collect(); gc.freeze()` (helper `freeze_static`) to move
  the tile grid into a permanent generation the collector never re-scans, so a
  collection costs <1 ms at any map size; `teardown_gameplay` calls
  `gc.unfreeze()` first so the old world can be reclaimed. **Gated to windowed
  runs** (`tune_gc = max_frames is None`) — headless tests/smoke re-boot
  `main()` in-process and must not have GC state mutated. `game/map` `Tile`
  carries `__slots__` for the same reason (memory: ~3× smaller per tile).
- **Ground cache (perf, the panning fix)**: the static terrain is no longer
  re-blitted tile-by-tile each frame. The host builds
  `engine.render.ground_cache.GroundCache(cs, assets, bg_color=BACKGROUND)` and,
  in the world/PAUSED render branch, calls `ground_cache.ensure(view_w, view_h,
  <band emitter>)` + `ground_cache.blit(window)` FIRST, then submits base + deco
  (`visible_render_items(..., terrain=False)`) + entities + UI over it. The
  `ensure` callback is the iso-diagonal band emitter
  `lambda dmn,dmx,smn,smx: tilemap.band_render_items(map_doc, dmn,dmx,smn,smx)`
  (NOT `visible_render_items` — the cache repaints thin diagonal scroll strips;
  see engine/CLAUDE.md). In-game terrain never mutates at runtime (unlock/recede
  change runtime zone state, not `map_doc.terrain`; highlights are overlay-layer),
  so no `invalidate()` is needed. The cache SCROLLS on pan and repaints only the
  exposed edge, so panning cost tracks pan speed, not map size — a 1024² map that
  used to drop to ~2 fps while panning (every margin-cross triggered a ~70 ms full
  recomposite) now stays smooth (headless: ~6–14 ms/frame at 1024² zoom 1,
  independent of map size). Details in engine/CLAUDE.md "Ground layer cache".
- **Frame-timing HUD**: windowed runs print `sim/submit/flush/flip` avg ms beside
  the fps line (gated on `tune_gc`, so headless stays silent) — the on-hardware
  measure of where a frame goes.
- **Active map (Phase 6, D-20/D-21)**: boot loads
  `engine.tilemap.load_active_map(data_dir)` (follows
  `data/maps/active_map.json`) and builds coords with THE MAP's dims
  (`load_coordinate_system(data_dir, map_cols=…, map_rows=…)`). The static
  map (tiles with prototype checkerboard parity, base on `entities`, deco on
  `deco` above entities per E-26) is submitted **windowed** each frame:
  `cs.visible_tile_window(view_w, view_h, margin=4)` →
  `engine.tilemap.visible_render_items(map_doc, …)` generates ONLY the tiles
  that can touch the viewport. This is what makes very large maps (up to
  1024×1024) render at full fps — the per-frame cost tracks the visible
  window (worst case ~7k tiles at min zoom), not the map's total tile count.
  (The old full-map `render_items` precompute is gone — it would build/hold
  ~1M RenderItems for a 1024² map.) Invalid map data fails LOUD (D-2); the
  E-37 log-and-placeholder
  tolerance covers ART only. Since 9D the host builds a `TileMap` +
  `engine.physics.TileOccupancy`, attaches the `BaseBuilding` to its tile, and
  places a demo Defender + Musician via `game.buildings.place_building`
  (the dummy entities are gone). Since 9F the host builds a `game.core.Session`
  (owns the phase machine, love, lives, game over) and each frame runs
  `session.pre_sim(dt, scene)` → `scene.update(dt)` →
  `game.enemies.resolve_combat(..., on_base_hit=session.on_base_hit)` →
  `session.post_sim(scene)`; pressing **`SPACE`** in BUILDING calls
  `session.end_turn()` (temporary stand-in for the 9G End Turn button). A minimal
  debug HUD (`submit_debug_hud`) draws love / round / lives / phase via the
  engine HUD pass — NOT the real 9G HUD. The demo buildings stay so combat /
  revive / yield are visible.

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
- **Occupancy is occupant-driven and updated incrementally**: a tile with a
  GameObject occupant is mirrored into `engine.physics.TileOccupancy` (BACKGROUND
  impassability is a weight concern, not occupancy). Placement seams
  (`game/buildings/registry.py`) call `occupancy.set` for the single changed tile;
  `TileMap.sync_occupancy(occupancy)` is the full-grid rebuild variant (not on the
  placement path — see the large-map hitch-cleanup note above).

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
- **9F wires the round loop** around this sweep: `resolve_combat` gained an
  optional `on_base_hit(enemy)` callback — with it, `_resolve_base_arrivals`
  hands the session exactly ONE base arrival per frame then bails (prototype
  `_update_enemy_phase` returns on the first hit), keeping base lives / game over
  / round wipe a `game/core` concern and `game/enemies` free of any core import.
  With no callback (9E tests) it deals raw HP as before. `Spawner.clear()` drops
  the pending wave for a lives-mode round wipe.
- **10A** added `resolve_combat(on_enemy_death=…)`, the callback the session uses
  to count kills + award XP without `game/enemies` importing `game/core`.
  Terrain/wall/death-swarm hooks stay dormant.

## Core / round loop (`core/`, Phase 9F)
The round machine + economy, porting the prototype's `Game._update_gameplay` /
`_begin_enemy_phase` / `_begin_round_end` / `_begin_income_phase`. Four files
beside `balance.py`, all pure logic (no pygame — a `TestPurity` guards it):
- **`phases.py`** — `GamePhase` (BUILDING/ENEMY/ROUND_END/LEVELUP/INCOME driven
  now — LEVELUP since 10A; BOSS_CUTSCENE declared at its prototype ordinal but
  never entered — 10G) and `GameState` (GAMEPLAY/GAME_OVER; menu states 9H).
- **`game_state.py`** — `RunState` dataclass: the single owner of `phase`,
  `state`, `round_num` (starts 1, `++`'d in payday — prototype numbering),
  `love`, `base_lives`, `phase_timer`, run stats. `from_balance(core)` seeds it;
  `add_love`/`spend_love` clamp at ≥0 (prototype clamps every currency write).
- **`payday.py`** — `run_payday(state, tilemap, core)` mirrors
  `_begin_income_phase` **step for step; the ordering is SACROSANCT**. 9F drives:
  snapshot RoundStats (this→last) → base income + duck-typed `yield_amount` sweep
  → duck-typed `upkeep` sweep (clamp 0) → revive sweep (`rebuild()` on non-base,
  base excluded) → round++ → phase=INCOME. Reserved no-op slots (boss-bonus,
  painter, boost, wall-teardown before revive; rebuild-walls) stay in place for
  10C-10G. Do not reorder without the user.
- **`session.py`** — `Session` orchestrates per frame: `end_turn()`
  (BUILDING→ENEMY, `spawner.begin_round(round_num, …)`); `pre_sim(dt, scene)`
  (spawner during ENEMY; ROUND_END/INCOME timers from `core.PhaseLoop`; payday at
  ROUND_END end); `post_sim(scene)` (wave-clear = `spawner.done` + no live enemy →
  ROUND_END; or a `_wipe_pending` lives-breach wipe); `on_base_hit(enemy)`
  (`base_lives--` + round wipe, game over at 0 lives). Everything freezes on
  GAME_OVER (no phase advances) — prototype `_update` has no GAME_OVER branch.
- **Love → interactive placement + real HUD/End-Turn button are 9G**; `Session`
  owns the love store now, ready to feed `place_building`.

> Cross-package note (9F): `engine/render/fonts.py` `get_font` now probes a
> cached SysFont with `get_height()` and rebuilds it if its pygame session was
> torn down (a prior `pygame.quit()` — surfaced by drawing HUD text across the
> repeated in-process `game.main` boots the tests/smoke do). Pure engine
> robustness fix, no API change.

## Shell + menus (`ui/`, Phase 9H)
The top-level application state machine that wraps a run — ports the prototype's
`GameState` shell (`src/core/game.py` dispatch). Split by the ONE-WAY layering
`game.ui → game.core` (`hud.py` already imports `game.core.phases`), so the shell
lives in **`game/ui/shell.py`**, NOT `game/core` (that would be circular):
- **`Shell` is pure** (pygame-free, like all of `game/ui`; a source-scan purity
  test in `test_shell.py` guards it — `game/ui` may import `engine.render.fonts`,
  a sanctioned pygame module, so it imports pygame only *transitively*). It owns
  `state` (`GameState`), the five menu screens (`main_menu`/`settings`/`credits`/
  `add_name`/`pause`, each mirroring the `game_over.py` construct→layout→update→
  hit→submit template + `widgets.Button`), the session-only `SessionSettings`,
  and `settings_caller` (SETTINGS is reused for both entry points — NO
  `SETTINGS_PAUSED` state). It applies pure transitions itself and returns an
  **intent string** only for host-side (pygame/disk) actions: `new_game` /
  `quit_to_menu` / `quit_app` / `set_display_mode` / `add_name_commit`.
- **The host (`main.py`) executes intents + owns the pygame-only concerns** the
  pure shell can't: window (re)creation (`_apply_display_mode` — SCALED keeps the
  logical surface `view_w×view_h` in all three modes so coords/renderer/hit-rects
  never change, E-5), the cutscene raw-surface blit, `engine.audio.play_music`
  (one looping track; windowed runs only), and the `_World` lifecycle
  (`build_gameplay`/`teardown_gameplay` — a fresh `_World` = a fresh run; menus
  hold NO world). The frame loop is three per-`shell.state` switches
  (input / update / render); the 9G in-round click ladder is unchanged but runs
  only in GAMEPLAY. Esc opens PAUSE in gameplay / backs out of menus (was: quit).
- **Cutscene = FULL video** via the 9B `engine.video.VideoSource`
  (`data/video/cutscene.mp4`, length from `ui.json Menu.cutscene_length`);
  graceful-skips to MAIN_MENU when cv2/file absent (headless).
- **ADD_NAME persists** the typed name to `buildings.json`
  `BuildingsGlobal.random_names` via **`game/core/names.py append_random_name`**
  (the one runtime data write; disk I/O stays out of pygame-pure `game/ui`); the
  host also appends to the in-memory `buildings_balance` so it goes live.
- **Headless seam**: `main(autostart=True)` skips the shell straight into
  GAMEPLAY so `tools/smoke.py` + the boot tests still exercise the full
  `_World`/`Session` construction + sim the menu would otherwise defer.
- **Deferred**: main-menu background art + the pause dim overlay (the HUD pass
  has no per-pixel alpha) are host raw-surface concerns, not yet wired; the
  settings audio slider is inert (no audio system beyond music).

## XP / village level-up / research (Phase 10A)
The run's progression layer: enemies and buildings drop XP, XP fills a village
level, and each level opens a modal LEVELUP window whose reward researches the
next building tier (or pays love). Ports the prototype's `_award_xp` /
`_roll_levelup_options` / `_resolve_levelup` + `levelup_window.py`.
- **`game/core/xp.py`** (pure) — `xp_for_etype` (keyed on `Enemy.ETYPE`),
  `award_xp` (arms `levelup_pending`; queues an `xp_events` floater),
  `advance_village_level` (the 50→65→85→110→140 threshold walk; surplus carries
  forward, one level per resolve), and **`scaled_base_income`** — the ONE source
  for payday, the HUD income line and the base-info panel, so they can't drift.
- **`game/core/levelup.py`** (pure) — the option roll + `apply_levelup_option` +
  **`upgrade_gate`**, the FIVE-mode upgrade classifier the panel renders
  (`in_tier` / `tier_upgrade` / `tier_locked` / `tier_hidden` / `max_tier`). A
  tier can no longer be advanced into for free: it must be **researched on a
  level-up** first, and it stays unnamed until its `unlock_min_round`.
- **Three gates stack**, all read live from `buildings.json`: the type unlock
  (`RunState.unlocked_buildings`), the **era gate** `<group>.era_unlock_round`,
  and the per-tier `tiers[idx].unlock_min_round`. Only the SINGLE next locked
  tier (`idx == tiers_unlocked`) is ever offerable. Research is GLOBAL per type.
- **`<group>.era_unlock_round` is the ONE canonical era key.** 10A lifted it off
  the tier dicts (where the prototype read it) onto the group (where 9A had
  migrated a *dead* top-level constant), fixing Sun Scorcher's live gate to 14 —
  the group value had been the never-read 10. The parity map marks
  `SUN_SCORCHER_ERA_UNLOCK_ROUND` DROPPED and the three affected tier-list
  entries carry `drop_keys` (a new `test_balancing_parity` entry form).
- **`game/buildings/research.py`** is the extension seam: `LEAF_CLASSES` +
  a `RESEARCH` table of `ResearchSpec` rows (`starts_unlocked`,
  `starts_with_tier`, `gate_kind`/`gate_path`, `unlock_group`, UI copy). A spec
  never stores a gate VALUE, only where in `buildings.json` to read it.
  **10B–10E add a leaf class + one row and never reopen the roll.** It lives
  there (not `registry.py`) because `registry` imports `game.map.tiles` →
  `game.core.balance`; `game/core/levelup.py` must read the table without
  closing that cycle. `registry` re-exports `LEAF_CLASSES` as
  `BUILDING_CLASSES` and gates `place_building` on `buildable(state, btype)`.
- **Phase machine**: at ROUND_END's expiry a pending level-up enters
  `GamePhase.LEVELUP` **instead of** running payday; `Session.resolve_levelup`
  applies the reward, advances the level, then runs payday (the prototype's
  `run_income=True` path — the cheat `return_phase` path is 10H). `Session.frozen`
  is the host's single "skip the whole sim" flag: no `scene.update`, no combat,
  no animation behind the modal. Payday's base income is now village-scaled.
- **XP award sites**: field kills via a new `resolve_combat(on_enemy_death=…)`
  callback (same layering trick as `on_base_hit` — `game/enemies` still imports
  no `game/core`); base-damage kills gated by `XP.xp_on_base_damage_kill`;
  queued-but-never-spawned enemies paid on a lives wipe (`Spawner.pending()`),
  while live enemies cleared from the field pay nothing (prototype-exact);
  building deaths gated by `XP.xp_from_buildings`, **once per building `id()`
  for the whole run** — a faithful prototype quirk: revive, die again, no
  second payout. `on_enemy_death` also fixes a real bug — `enemies_killed` used
  to count only base breaches, so the game-over screen under-reported kills.
- **UI**: `game/ui/levelup.py` (`LevelupWindow`, the `game_over.py` template; it
  lays out on `open` because hover/hit run before the first `submit`), an XP bar
  + `LVL N` in `hud.py` (gold + pulsing when pending), purple XP floaters via
  `FloaterManager.spawn_xp_events` (drained every frame, not at a phase edge),
  and the gated construct list + five-mode upgrade button in `building_ui.py`.
  The modal sits at the TOP of `main.py`'s click ladder and swallows keys.
- **Known divergences** (both deliberate): the window's backdrop is OPAQUE — the
  HUD pass has no per-pixel alpha, the same limit that deferred 9H's pause dim
  (10J). And the XP bar/floaters drop the prototype's mascot face + `xp_icon`,
  which has no slot in `data/slots.json` (10J).
- **Empty pool is expected before round 10**: only `defence` + `economic` exist,
  both start unlocked at tier 1, their tier-2s are round-gated to 10, and the
  hole is lives-based so the prototype's `+1 Base HP` fallback doesn't apply —
  so early level-ups show three identical `+25 Love` cards, exactly the
  prototype's pad-to-3. The pool fills as 10B–10E land their families.

## Porting protocol (PLAN phase 9+)
Port one domain at a time, prototype as spec: acceptance checklist → runnable
test → implement → iterate until green → live playtest. State what you
verified (smoke test vs live round vs static read).

## Verify before finishing
Headless smoke test (`tools/smoke.py`) after every change; live
`py game/main.py` round for phase/combat/UI behavior. If balance changed:
schema validation passes, lock respected.
