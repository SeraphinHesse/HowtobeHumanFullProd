# CLAUDE.md — game/enemies (Phases 9E + 10F + 10G)

`Enemy(GameObject)` walker + `Spawner` + a type-agnostic combat sweep, porting the
prototype's `src/enemies/*` and `game.py` enemy/spawn/combat loops. You reached
here from `game/CLAUDE.md`. **All four enemy types are LIVE**: Standard + Raider +
SiegeCannon since 10F, `Boss` since 10G (`spawner.py`
`ENABLE_RAIDERS`/`ENABLE_SIEGE`/`ENABLE_BOSS = True`). When you change enemy
conventions, update THIS doc. **Adding an enemy type? Use the `/add-enemy`
skill.**

## Boss (10G)
- **Boss rounds**: every `Boss.round_interval`-th round `_compose` routes to
  `_boss_round` — `[ONE boss] + ALL siege + shuffle(standard + raiders)`, counts
  from `Boss.round_counts[round // interval - 1]` (beyond the 5-row table: the
  three normal per-type formulas incl. start-round guards). NO siege lead/mix
  split on boss rounds. The boss entry's **`tier` argument IS its era**
  (`round // interval - 1`, clamped in `Boss.__init__`; pop-time via
  `Spawner._boss_era`); companions keep the real scale tier.
- **`Boss` hunts buildings**: `on_spawn` paths via
  `find_path_to_nearest_building` (base included) and arms
  `PathAgent.repath_on_kill=True` + `goal_is_base` (whether the path ends on the
  base). Carries the extra `"boss"` scene tag (`Enemy.EXTRA_TAGS`) so
  HUD-bar/shake queries need no host reference. Duck-typed contract for
  `Session.on_enemy_death`: `era` (read property), `death_spawned` (read
  property) + `mark_death_spawned()` — a METHOD, because the E-11
  `GameObject.__setattr__` guard intercepts public property setters.
- **`PathAgent` 10G flags, default-off** (Standard/Raider/Siege byte-identical):
  `goal_is_base=True` — `Movement.arrived` sets `reached_base` only when True;
  a non-base goal arrival `_repath`s instead (kills the phantom-base-hit hazard
  the 10F deferral documented). `repath_on_kill=False` — on unblock (blocker
  died) re-run `find_path_to_nearest_building` from the current tile, reload
  waypoints, re-derive `goal_is_base` (the prototype boss's `_repath`-after-kill
  mapped onto block-and-attack).
- **Death swarm**: `Spawner.spawn_death_swarm(scene, col, row, era)` bursts
  `Boss.death_spawns[era]` standard/raider/siege IMMEDIATELY into the scene at
  the boss tile, at the CURRENT tier (standard+siege scale; raiders never).
  Driven by the Session (stash in `on_enemy_death`, flushed in `post_sim`
  BEFORE the wave-clear check); quick-skip / lives-wipe despawns spawn nothing.
- **No tier scaling on the boss** — `Boss._resolve_stats` reads
  `Boss.stats[era]` verbatim; `dmg_bonus` (the 10G optional kwarg on
  `resolve_combat`, default 0) is the boss-bonus story damage crossing the
  boundary as a plain int, added at fire time in all three firing paths.

## Rules
- **All state in components** (E-11): `components.py` holds `PathAgent`
  (navigation + the block-and-attack decision) and `EnemyCombat` (attack stats +
  the attack-a-blocking-building clock); engine
  `Health`/`Movement`/`SpriteAnimator`/`RangeSensor` carry the rest. The
  duck-typed values the combat sweep reads (`alive`/`dmg`) are guard-safe
  `@property`s.
- **Overhead HP-bar size is a per-type class attr**: `HP_BAR_W`/`HP_BAR_H`
  (walker/raider 14×2, siege 24×2, boss 48×4 — prototype-exact), sitting with
  the other presentation class attrs (`DEFAULT_SLOT`, `REGISTRY_GROUP`). Its
  HEIGHT above the enemy is **not** a class attr: `HP_BAR_PAD` (4px, base class
  only) is just the gap above the sprite's head, and the head is found from the
  sprite as actually DRAWN — since ER-1 that is the footprint fit, not the sheet
  size, so a lift baked in sheet pixels would float (see `game/ui/CLAUDE.md`).
  Read
  duck-typed by `game/ui/effects.py submit_enemy_hp_bars`, which draws the bar
  for EVERY enemy below full HP (boss included) — this package needs no other
  change for it. A new enemy type just declares its own width.
- **`PathAgent` runs BEFORE `Movement`** in the component list so its halt
  decision takes effect the same frame (no drift into a blocked tile). It gates
  locomotion by zeroing `Movement.speed` while blocked and restoring it on unblock
  — the path (`Movement.waypoints`) is NEVER discarded, so no re-path is needed
  when the blocker dies (the route already runs through that now-passable tile). It
  caches the map as `PathAgent._tilemap` — a deliberate environment-reference
  transient, exactly like `Movement._owner`.
- **`PathAgent.footprint` (ER-2)** — an `int` field fed from
  `EnemyTypes.<type>.footprint` (G-7; `Enemy.__init__` reads it off the resolved
  `STAT_SUBTREE` block, no code-side default). The unit occupies an N×N block
  whose **anchor is the MIN corner** (the body extends right and down); the whole
  rule set + the helper functions live in `game/map/CLAUDE.md` / `pathfinder.py`
  and are imported, never re-derived. Consequences in this package:
  - `Enemy.on_spawn` threads the footprint into `find_path` /
    `find_path_ignoring_walls`; `_repath` threads it into
    `find_path_to_nearest_building` and re-derives `goal_is_base` with
    `block_covers` (the block COVERS the base — it need not anchor on it).
  - **The blocker scan is block-wide** (`_blocker_ahead`): the first live,
    non-base occupant anywhere in the DESTINATION block stops the unit, scanned
    row-major. The base exemption is per **tile** of the block, so a body that
    covers the hole attacks the other occupant in it, never the BaseBuilding.
  - **The wall scan is face + internal** (`_wall_edge_ahead`): the whole leading
    face first, then the destination block's internal edges; it returns the FIRST
    live edge, so a 2×2 chews through a face one segment at a time.
  - The **spawner filters spawn tiles by clearance** (`_pick_spawn_tile` — the
    ONE choke point all seven composition sites now route through): a footprint-N
    enemy only spawns where its whole N×N block is spawn zone, cached once per
    round per footprint (`_clear_cache`, reset in `begin_round`). No qualifying
    tile → **unfiltered fallback**, so an enemy is never dropped from a wave. The
    filter consumes **zero rng**, and `footprint == 1` takes the byte-identical
    single `rng.choice(spawn_tiles)` draw — which is what keeps the deterministic
    composition fixtures green.
  - The **combat sweep measures from the footprint CENTRE**
    (`anchor + (N−1)/2`): Chebyshev range, Euclidean acquisition, mortar splash
    and predictive lead all use `_enemy_center_world` / `_fp_offset`, so a 2×2 is
    not engaged from an unfair corner and shells are not biased half a tile off
    it. N=1 → offset 0 → numerically identical to before.
    **PERF (load-bearing):** the offset is a per-enemy constant and is resolved
    ONCE PER ENEMY PER FRAME — `resolve_combat` builds `targets =
    [(enemy, off), …]` and passes `off` into `_chebyshev`. Never resolve it
    inside the (defender × enemy) pairwise loop: `get_component` is a linear
    isinstance scan, and doing it per pair cost ~9 ms of a 16.7 ms frame at 50
    defenders × 300 enemies. `_chebyshev` also SKIPS a zero offset rather than
    adding it, keeping the N=1 expression in integer arithmetic (float ops there
    allocate per pair). Both are pinned by `game/PERF.md`.
  - **D5: footprints never enter `TileOccupancy`.** They are a pathfinding
    property only — enemies do not block each other, and two footprint-2 units
    may overlap. That is intended.
  - **Known cosmetic gap (open for ER-4/ER-5)**: ER-1 draws the sprite centred on
    the *anchor tile's* diamond, scaled to `N × tile_w`, so for an even N the
    logical block sits half a tile down-right of where the sprite's centre lands.
    Fixable only in the render layer.
- **Wall-attack is the SAME block-and-attack model (10E, LIVE)**: a live wall on the
  edge being crossed (`get_wall_between(prev_waypoint, next_waypoint)`, checked once
  `index ≥ 1`) blocks FIRST (it sits before the next tile) — `PathAgent` halts and
  records the edge in `_wall_target`; `EnemyCombat` drains it via
  `tilemap.damage_wall(*edge, dmg)` (no `RoundStats` — walls carry no Health). When
  the wall breaks, `get_wall_between → None`, PathAgent unblocks and the enemy
  resumes the SAME path. No `_path_through_walls` flag / pixel-space wall movement is
  ported: only the walls-ignoring path (base enclosed, via `Enemy.on_spawn`'s
  fallback) ever crosses a live wall — a normal `find_path` routes around them. The
  prototype's degenerate nearest-wall fallback (`_try_enter_wall_attack`, fires only
  when even `find_path_ignoring_walls` returns `[]`) is intentionally NOT ported — no
  practical gameplay difference.
- **Locomotion is fractional tile coords**: `move_speed` (tiles/sec) feeds
  `Movement.speed` straight — no ×32 pixel conversion (that was the prototype's
  pixel space); `find_path` output `[(col,row)…]` becomes `[[float(c),float(r)]…]`
  waypoints. Base arrival = `Movement.arrived` → `PathAgent.reached_base`.
- **Scale-tier stats resolved at CONSTRUCTION** (prototype `enemy.py:88-108`):
  hp/dmg/speed = type base + cumulative sum of `EnemyScaling.scale_tiers[0..tier)`;
  tier = `(round-1)//scale_every_n_levels`. Values from
  `data/balancing/enemies.json` (×10 combat scale baked in). **Who scales is
  per-type and prototype-exact** (`tier_scaled_stats`): `Standard` AND
  `SiegeCannon` take the cumulative bonuses; **`Raider` deliberately does NOT**
  (it stays 32 HP / 20 DMG forever — a glass cannon that only ever grows in
  COUNT); `Boss` ignores tiers entirely and reads its per-era stat table.
- **Sprite slots are registry-group driven with a random variant per spawn**
  (prototype `_STAGE_SLOT_PREFIX` + `_variant`): each class names its
  `data/slots.json` enemies group via `REGISTRY_GROUP`
  (`"Walker"`/`"Raider"`/`"Siege Cannon"`/`"Boss"`). That group's era subchildren
  are ordered; the enemy's `tier` clamps to an era index and `variant_slot()` picks
  a random slot from that era via the spawner's injected `rng` — so a walker rolls
  between `enemy_stage_1_v1`/`_v2` on spawn, and dropping a new `_v3` slot into the
  era (editor) grows the pool with NO code change. The registry + rng are threaded
  `main.py → Spawner.begin_round → create_enemy`; absent a registry (headless
  stat/logic tests) each class falls back to its `DEFAULT_SLOT`. The Walker/Raider
  eras map to the prototype `*_stage_N` sheets (NOT the procedural `*_t2..t4`);
  Siege/Boss keep their tier/era sheets.
- **`spawner.py` = the wave queue** (prototype `_begin_enemy_phase` /
  `_update_enemy_phase`): `begin_round` composes the standard count
  `base_enemy_count + (round-1)*(enemies_per_round + tier)` with the exact ramp +
  `uniform(0.4, 1.6)` jitter; `update(dt, scene)` pops ONE enemy per timer expiry
  into `scene.spawn`. The round LOOP that calls it + wave-clear detection is 9F; an
  injectable `rng` keeps tests deterministic.
  - **10F composition**: raiders join from `Raider.start_round` at
    `base_count + (round-start)*per_round`; siege from `SiegeCannon.start_round` at
    `base_count + (round-start)//rounds_per_cannon`. Siege splits into a **lead
    group** (`int(queue_lead_count * mix_ratio)`) that HEADS the queue and a
    remainder mixed into the shuffled body — so cannons open the wave and then
    trickle. Queue = `siege_front + shuffle(standard + raiders + siege_mixed)`.
- **Raiders/siege seek the BASE, not their prototype prey (deliberate 10F
  divergence).** The prototype re-paths raiders onto the nearest economy building
  and siege onto the nearest defence building (`_repath`). Here they path to the
  base once at spawn and attack whatever blocks them (the unified
  block-and-attack model), so a raider still eats an economy building standing in
  its lane — it just doesn't hunt one. **10G shipped the re-path machinery for
  the BOSS** (`PathAgent.goal_is_base` + `repath_on_kill`, above) — porting real
  raider/siege prey-hunting is now just arming those flags with
  `find_path_to_nearest_economic` / `_defence` in their `on_spawn`, if ever
  ruled desired.
- **`combat.py` = the type-agnostic sweep** `resolve_combat(scene, tilemap, dt,
  buildings_balance)`, called each frame AFTER `scene.update`: (1) every
  `"combat"`-tagged building keeps its sticky target if alive + in Chebyshev range,
  else acquires the nearest in-range enemy by Euclidean distance, and on cooldown
  fires a `Projectile` — the reset interval clamped to
  `DefenceBuildings.globals.min_attack_speed`; (2) an enemy with
  `PathAgent.reached_base` subtracts its `dmg` from the base's `Health` and
  despawns; (3) dead enemies despawn. This is the FIRST writer of `RoundStats`
  (`dmg_dealt_this_round` on shooters, `dmg_taken_this_round` on targets).
- **Projectiles travel then deal GUARANTEED damage** on arrival if the target is
  still alive (prototype `Projectile`): a shot in flight is wasted only if its
  target dies first — never a collision/accuracy miss. Travel time = `distance /
  DefenceBuildings.globals.projectile_speed_tiles` (new 9E key = 3.75 = prototype
  120 px/s ÷ 32). Projectiles stay LOGICAL GameObjects (no SpriteAnimator);
  since 10J the UI draws them live off the `"projectile"` tag
  (`FloaterManager.submit_projectiles` — stone dot / darker mortar shell), and
  muzzle/slash/blood FX are watcher-driven in `game/ui/effects.py` (an
  `EnemyCombat.cooldown` reset while blocked = an attack landed) — this package
  needed NO change for 10J.
- **Three firing paths, dispatched by capability component (10B), never by
  class** — the sweep still selects combatants by the `"combat"` tag, then
  `_update_defender` branches: a building with `BeamAttacker` runs `_update_beam`
  (instant hitscan, **highest-HP** targeting, per-tick damage ramp reset on any
  target change, and a `target_death_cooldown` re-acquire pause after a kill,
  ticking at its own `BEAM_MIN_TICK=0.02` floor — below the shared 0.2); a
  building with `SplashAttacker` fires an arcing `ProjectileAOE` to a FIXED
  ground point via predictive lead (`_predict_lead` reads the enemy's next
  `Movement` waypoint + speed), splashing full damage to every enemy within
  `splash_radius()` on impact (no falloff/target cap) and spawning a cosmetic
  `Crater`; otherwise the plain homing `Projectile`. `AOE_TRAVEL_TIME` (0.55s)
  and `CRATER_LIFE` (1.0s) are prototype-hardcoded cosmetic/timing constants, not
  balancing. The beam line + crater marker draw in `game/ui/effects.py`
  (`submit_beams`/`submit_craters`, reading `BeamAttacker._target` + `"crater"`
  scene objects) — alpha-limited by the HUD pass (10J polish).

- **10I tile-condition modifiers** (keyed on the tile the enemy last ARRIVED
  at): `PathAgent` tracks `_current_condition` (GRASS at spawn) — refreshed
  when `Movement.index` advances, reading `waypoints[index-1]`, gated
  `index >= 2` because waypoint 0 IS the spawn tile (whose condition never
  applies, prototype-exact). While unblocked it writes
  `mv.speed = _condition_speed()` every frame — `max(0, real −
  enemy_speed_penalty)` (mountain/forest −0.4 t/s; the `max(0)` clamp is
  prototype-exact). `EnemyCombat._effective_dmg` (`max(1, int(dmg × (1 +
  enemy_dmg_bonus)))`) is applied at BOTH attack sites — blocking building AND
  edge wall — but NEVER base hits (lives mode costs one life flat). POND has
  no enemy stat modifier (only its +9 path weight). The modifiers dict is read
  duck-typed off `PathAgent._tilemap.balance` (guarded — headless stubs stay
  neutral) through `game.map.tiles.CONDITION_MODIFIER_KEY`. The combat sweep's
  two targeting sites use `targeting_range_tiles()` (effective mountain +1
  for basic/beam, RAW for the mortar — a prototype-inherited inconsistency,
  see `game/buildings/CLAUDE.md`) via a guarded `getattr` fallback to
  `range_tiles()`, keeping the raw/effective split (coverage + RANGE
  overlay = raw).

## Round-loop / XP callbacks (9F / 10A) — layering trick
`game/enemies` imports NO `game/core`. Cross-boundary needs are optional callbacks:
- **9F** — `resolve_combat` gained `on_base_hit(enemy)`: with it,
  `_resolve_base_arrivals` hands the session exactly ONE base arrival per frame
  then bails (prototype `_update_enemy_phase` returns on the first hit), keeping
  base lives / game over / round wipe a `game/core` concern. With no callback (9E
  tests) it deals raw HP as before. `Spawner.clear()` drops the pending wave for a
  lives-mode round wipe.
- **10A** — `resolve_combat(on_enemy_death=…)`, the callback the session uses to
  count kills + award XP without importing `game/core`.
- **10G** — the same callback carries the boss death-swarm handshake (the
  session duck-types `era`/`death_spawned`/`mark_death_spawned` and calls
  `Spawner.spawn_death_swarm` back); `resolve_combat(dmg_bonus=0)` threads the
  boss-bonus story damage in as a plain int. Enemy construction never leaves
  this package.

## Perf note that lives here
`Enemy.on_spawn`'s `find_path` (and its `find_path_ignoring_walls` fallback)
now walk the shared base flow field — a wave of hundreds of spawns pays ONE
Dijkstra per map-topology change, not one each, and `spawn_death_swarm`'s
burst rides it for free. Since ER-2 the field caches on
**`(ignore_walls, footprint)`**, so the invariant is one Dijkstra per topology
change **per footprint** — still NEVER one per enemy. Passing a footprint into
`find_path` must therefore stay a plain argument; do not add a per-enemy search.
`Boss.on_spawn`'s `find_path_to_nearest_building`
stays a fresh Dijkstra (~one per wave). Nothing in this package invalidates
the field directly — all mutations route through `TileMap`. Detail →
`game/PERF.md`.

## Verify
Scripted round asserts HP ledger matches hand-computed prototype values:
`py -m unittest discover -s tools/tests -t .`.
