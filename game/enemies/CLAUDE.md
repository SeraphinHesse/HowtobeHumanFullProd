# CLAUDE.md — game/enemies (Phases 9E + 10F)

`Enemy(GameObject)` walker + `Spawner` + a type-agnostic combat sweep, porting the
prototype's `src/enemies/*` and `game.py` enemy/spawn/combat loops. You reached
here from `game/CLAUDE.md`. **Standard + Raider + SiegeCannon are all LIVE since
10F** (`spawner.py` `ENABLE_RAIDERS`/`ENABLE_SIEGE = True`); `Boss` (+`BossState`)
is still a thin subclass wired to a branch that never emits
(`ENABLE_BOSS = False`; 10G flips it). When you change enemy conventions, update
THIS doc. **Adding an enemy type? Use the `/add-enemy` skill.**

## Rules
- **All state in components** (E-11): `components.py` holds `PathAgent`
  (navigation + the block-and-attack decision) and `EnemyCombat` (attack stats +
  the attack-a-blocking-building clock); engine
  `Health`/`Movement`/`SpriteAnimator`/`RangeSensor` carry the rest. The
  duck-typed values the combat sweep reads (`alive`/`dmg`) are guard-safe
  `@property`s.
- **`PathAgent` runs BEFORE `Movement`** in the component list so its halt
  decision takes effect the same frame (no drift into a blocked tile). It gates
  locomotion by zeroing `Movement.speed` while blocked and restoring it on unblock
  — the path (`Movement.waypoints`) is NEVER discarded, so no re-path is needed
  when the blocker dies (the route already runs through that now-passable tile). It
  caches the map as `PathAgent._tilemap` — a deliberate environment-reference
  transient, exactly like `Movement._owner`.
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
  and siege onto the nearest defence building (`_repath`). Here every enemy paths
  to the base once at spawn and attacks whatever blocks it (the unified
  block-and-attack model), so a raider still eats an economy building standing in
  its lane — it just doesn't hunt one. Porting the real thing needs
  re-path-after-kill: `PathAgent.reached_base` is driven purely by
  `Movement.arrived`, so a path ENDING on a targeted building would fire a phantom
  base hit the moment that building dies and the enemy steps onto its tile. The
  goal-set queries are already ported and waiting
  (`find_path_to_nearest_economic` / `_defence` / `_building`) — wire them
  together with a re-path step, not alone.
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
  120 px/s ÷ 32). Logical GameObjects with no sprite in 9E — projectile/muzzle/
  blood art is the 10J FX sweep.
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

## Round-loop / XP callbacks (9F / 10A) — layering trick
`game/enemies` imports NO `game/core`. Cross-boundary needs are optional callbacks:
- **9F** — `resolve_combat` gained `on_base_hit(enemy)`: with it,
  `_resolve_base_arrivals` hands the session exactly ONE base arrival per frame
  then bails (prototype `_update_enemy_phase` returns on the first hit), keeping
  base lives / game over / round wipe a `game/core` concern. With no callback (9E
  tests) it deals raw HP as before. `Spawner.clear()` drops the pending wave for a
  lives-mode round wipe.
- **10A** — `resolve_combat(on_enemy_death=…)`, the callback the session uses to
  count kills + award XP without importing `game/core`. Terrain/wall/death-swarm
  hooks stay dormant.

## Perf frontier that lives here
`Enemy.on_spawn` runs one `find_path` Dijkstra per enemy — the next large-map
frontier (shared flow-field fix, not yet done). Detail → `game/PERF.md`.

## Verify
Scripted round asserts HP ledger matches hand-computed prototype values:
`py -m unittest discover -s tools/tests -t .`.
