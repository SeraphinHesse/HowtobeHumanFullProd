# CLAUDE.md — game/enemies (Phases 9E + 10F + 10G + ER-4)

`Enemy(GameObject)` walker + `Spawner` + a type-agnostic combat sweep, porting the
prototype's `src/enemies/*` and `game.py` enemy/spawn/combat loops. You reached
here from `game/CLAUDE.md`. **All five enemy types are LIVE**: Standard + Raider +
SiegeCannon since 10F, `Boss` since 10G, `Formation` since ER-4 (`spawner.py`
`ENABLE_RAIDERS`/`ENABLE_SIEGE`/`ENABLE_BOSS`/`ENABLE_FORMATION = True`). When you
change enemy conventions, update THIS doc. **Adding an enemy type? Use the
`/add-enemy` skill.**

## Boss (10G)
- **Boss rounds**: every `Boss.round_interval`-th round `_compose` routes to
  `_boss_round` — `[ONE boss] + ALL siege + shuffle(standard + raiders)`, counts
  from `Boss.round_counts[round // interval - 1]` (beyond the 5-row table: the
  three normal per-type formulas incl. start-round guards). NO siege lead/mix
  split on boss rounds. The boss entry's **`tier` argument IS its era**
  (`round // interval - 1`, clamped in `Boss.__init__`; pop-time via
  `Spawner._boss_era`); companions keep the real scale tier.
- **`Boss` hunts buildings, hole LAST (BP-2 / D2)**: `on_spawn` paths via
  `find_path_to_nearest_non_base_building` and arms
  `PathAgent.repath_on_kill=True`, then `PathAgent.adopt_goal(path, tm)`. Carries
  the extra `"boss"` scene tag (`Enemy.EXTRA_TAGS`) so HUD-bar/shake queries need
  no host reference. Duck-typed contract for `Session.on_enemy_death`: `era`
  (read property), `death_spawned` (read property) + `mark_death_spawned()` — a
  METHOD, because the E-11 `GameObject.__setattr__` guard intercepts public
  property setters.
  - **The base is NOT in the goal set while anything else stands.** It used to
    be (`find_path_to_nearest_building`'s predicate is `lambda b: True`), and
    `content_weights.base_building` is **0** — cheaper than any real building
    (1–2) — so a weighted search walked the boss straight past its prey and
    parked it on the hole. It destroyed 2 of 8 buildings on a scripted board;
    it now destroys 8 of 8. The fallback to `find_path` when no non-base
    building is alive is the ONE way `goal_is_base` ever flips True.
- **`PathAgent` 10G flags, default-off** (Standard/Raider/Siege byte-identical):
  `goal_is_base=True` — `Movement.arrived` sets `reached_base` only when True;
  a non-base goal arrival `_repath`s instead (kills the phantom-base-hit hazard
  the 10F deferral documented). `repath_on_kill=False` — re-run
  `find_path_to_nearest_non_base_building` from the current tile, reload
  waypoints, re-derive the goal (the prototype boss's `_repath`-after-kill mapped
  onto block-and-attack).
- **`PathAgent.target_col`/`target_row` — the COMMITTED victim (BP-3 / D3)**,
  `-1` = none (walking at the base), which is the default-off sentinel keeping
  the other four types byte-identical. Two rules hang off it:
  - **Choose by DISTANCE, route by COST.** `nearest_non_base_building_tile` picks
    the victim by plain geometric distance — what the player sees — while the
    route to it stays the weighted Dijkstra, so the boss still walks around
    ponds. One weighted search used to do both jobs and the two requirements
    fight: terrain, defence coverage (+1/tile) and the round-11 damage discount
    (×0.5) all bend the cost field, so the "nearest" building could be across the
    map.
  - **The target is watched every frame, not just on the blocked→unblocked
    edge.** `update()` re-paths the moment the target dies — to us OR to a
    defender while we were still walking to it, which on a crowded boss round is
    the common case. It used to march on to the corpse and only notice on
    arrival. Gated on `not blocked`, so while the boss is punching something the
    unblock branch stays the single re-path site.
  - `adopt_goal(path, tm)` is the ONE site deriving `goal_is_base` + the target
    from a fresh path; `on_spawn` and `_repath` both call it so they cannot
    drift. No path at all clears the target — that is what stops the
    dead-target watch from re-pathing every frame forever.
- **`_repath` does not REWIND (BP-4).** It snaps the start to `round(wx)`, but
  the body is somewhere *inside* that tile, not on its centre — so aiming at
  `path[0]` walked the boss BACKWARD to the centre before setting off (measured:
  col 11.000 → 10.705 in the second after a kill). It now starts at `index = 1`
  whenever the path has one: we are already inside `path[0]` and `path[1]` is
  4-adjacent, so heading straight there is always a legal step. A re-path is also
  the one place `_current_condition` genuinely went stale, so `_repath` re-reads
  it from the tile underfoot and resyncs `_last_index`.
- **Death swarm — since ER-3 just ONE instance of the generalised
  `death_spawn`** (below). The boss ships `at_hp_fraction: 0.0` +
  `spawn_hp_fraction: 1.0` + `enabled: true` and its 5 per-era rows moved
  verbatim to `Boss.death_spawn.spawns`, so the 10G burst is byte-identical:
  same counts, same tile, same CURRENT tier (standard+siege scale; raiders
  never), children at full HP. `Boss` itself is now just `_resolve_era` +
  `_resolve_stats` + `on_spawn` + `era` — its `__init__` is gone.
- **No tier scaling on the boss** — `Boss._resolve_stats` reads
  `Boss.stats[era]` verbatim; `dmg_bonus` (the 10G optional kwarg on
  `resolve_combat`, default 0) is the boss-bonus story damage crossing the
  boundary as a plain int, added at fire time in all three firing paths.

## Formation (ER-4)
The 2×2 marching column. **It adds no mechanism** — it is the first consumer of
ER-1 (per-slot frame size), ER-2 (footprint clearance pathing) and ER-3
(`death_spawn`), all three driven purely from `data/balancing/enemies.json`.
- **The subclass is four class attrs + `_resolve_stats`.** No `__init__`, no
  `on_spawn`, no `EXTRA_TAGS`, no component wiring, no break state machine.
- **`_resolve_stats` MUST be overridden — and that is a trap, not a style
  choice.** The base `Enemy._resolve_stats` reads
  `balance["EnemyTypes"]["Standard"]` **literally**; `STAT_SUBTREE` drives the
  balancing-block lookup in `__init__` (and `Spawner._footprint_of`) but **not**
  `_resolve_stats`. An un-overridden subclass silently ships walker stats — a
  bug with no symptom but wrong numbers. Pinned by
  `test_enemies.TestFormation.test_stats_come_from_the_formation_block_not_standard`.
  Formation takes the scale-tier bonuses (like Standard/Siege, unlike Raider).
- **It does NOT override `_resolve_era`**: it is not era-indexed, so it inherits
  row 0 and ships a **single-row** `death_spawn.spawns` array. The clamp
  (`spawns[min(max(era,0), len-1)]`) does the rest.
- **D4 — there is no "break" state; breaking formation IS dying.**
  `at_hp_fraction: 0.5` makes `Enemy.alive` False at half HP, and from there the
  existing ER-3 pipeline runs untouched (`resolve_combat` → `on_enemy_death` →
  `Session` stash → `Spawner.spawn_death_swarm`). The children are regulars at
  `spawn_hp_fraction` (0.8) of their OWN max HP. XP, kill count and splatter all
  fire exactly as for any other death, because it *is* one.
- **Composition: the siege ACCRETION formula, but body-mixed.**
  `_formation_group` emits `base_count + (round − start_round) //
  rounds_per_formation` from `start_round`, mixed into the shuffled body —
  **never `siege_front`**, because a 2×2 at the head of the queue would wall the
  choke point before anything else arrived. It is called **LAST** among the
  composition groups so every earlier group's rng draw sequence stays
  byte-identical (the deterministic-wave fixtures depend on this).
- **Formations never spawn on a boss round — DELIBERATE, do not "fix" it.**
  `_boss_round` composes from `Boss.round_counts`, a `$defs/spawn_counts` table
  **shared with every `death_spawn.spawns` row**. Adding a `"formation"` key to
  that `$def` would force a meaningless formation count into every death-spawn
  row. (It also used to fail the prototype-parity gate — that gate is deleted
  now, so the schema-shape argument is the whole reason and it still stands.) If
  formations on boss rounds are ever wanted, it is a one-line
  `+ self._formation_group(...)` into `_boss_round`'s `rest` — computed from the
  formula, never from the table.
- **Known cosmetic caveat, INHERITED not introduced.** For an EVEN footprint the
  sprite draws 16px (half a tile-height) ABOVE the block's logical centre, with
  zero horizontal error: `Renderer.flush` centres the frame on the *anchor
  tile's* diamond, and the 2×2's centre is at `anchor + (0.5, 0.5)`, which is
  `+16px` in iso screen space at zoom 1. The HP bar rides the sprite so it stays
  consistent; pathing uses the anchor and combat measures from the block centre,
  so **nothing is mis-simulated**. The fix is engine-side (in `Renderer.flush`,
  centre on `wx + (fit_tiles−1)/2` when `fit_tiles > 0` — a provable no-op at
  `fit_tiles` 0 and 1, i.e. every sprite that ships today), plus a re-derived
  `game/ui/effects.py::_sprite_top`. It is a cross-package change against the
  surface ER-1 pixel-pinned, so it wants its own phase.

## Corpse — the death animation body (`corpse.py`, Art/enemies)
The enemy's death path is **byte-identical**: it still despawns the frame it
dies, so combat, XP, wave-clear and the `death_spawn` burst are untouched. To let
a `death` animation actually play, the HOST additionally spawns a cosmetic
`Corpse` at the dead enemy's spot (`main.py` wraps `on_enemy_death`).
- **Purely visual, tagged `"corpse"` (never `"enemy"`)**, carrying only a
  `SpriteAnimator` (the enemy's own `slot_key`/`fit_tiles`/`scale`, animation
  `DEATH_ANIM = "death"`) + a `CorpseFade` clock — no Health/PathAgent/`alive`.
  So it is invisible to EVERY gameplay query (combat targeting,
  `_resolve_base_arrivals`, the wave-clear check, the overhead HP bars all read
  `by_tag("enemy")`/`alive`) and renders/ages through the generic
  `Scene.render_items`/`Scene.update` — the `Crater`/`LightningFX` pattern.
- **Lifetime = the manifest `death` track `total_ms`** (queried host-side via
  `AssetStore.animation_total_ms`, which returns `None` — NOT the idle duration —
  when the sheet has no `death` row, so a sheet without one keeps today's instant
  despawn). `total_ms` already covers loop expansion ⇒ the row plays once. The
  fade clock and the `SpriteAnimator` clock take the same speed-scaled `sim_dt`,
  so play-once timing holds at 1x/1.5x/2x/pause.
- **Only real field deaths get a corpse** — base arrivals, quick-skip, lives-wipe
  and cheat despawns never call `on_enemy_death`, so they spawn nothing (correct:
  the field is cleared silently). Because each spawn-variant sheet is its own slot
  with its own `death` row, playing the enemy's OWN slot yields the right variant
  with no random pick. Pinned by `test_corpse`.

## Rules
- **`death_spawn` — the ONE death-spawn mechanic (ER-3, plan D4)**. Every
  `EnemyTypes/<type>` block carries a **required** `death_spawn`
  (`at_hp_fraction` / `enabled` / `spawn_hp_fraction` / `spawns`); it is
  resolved at CONSTRUCTION into the `DeathSpawn` component (which absorbed
  10G's `BossState`), exactly like `Health.max_hp`.
  - **D4 — "breaking formation IS dying."** `Enemy.alive` is
    `hp > max_hp * at_hp_fraction`, and that is the ONE evaluation site: a unit
    that crosses its threshold is dead in the full existing sense (despawned by
    `resolve_combat`, XP awarded, splatter queued, kill counted). There is **no
    separate "break" state and no second state machine** — a Formation that
    scatters at half health just ships `at_hp_fraction: 0.5`. At the default
    `0.0` this is exactly `not Health.is_dead` (`hp <= 0`), so every pre-ER-3
    type is byte-identical. `Health.is_dead` itself is UNCHANGED (buildings
    still use it; they carry no `DeathSpawn`).
  - **`spawns` is an ARRAY of per-era rows, never a union.** It is resolved
    `spawns[min(max(era, 0), len(spawns) - 1)]` — the Boss carries 5 rows
    (index-aligned with its `stats`), a non-era type carries 1 and always
    clamps to row 0. The "flat map" form is just the 1-row case. **A schema
    `oneOf` here is unimplementable**: `editor/panels/balancing.py` reads
    `prop.get("type")` and a type-less node raises `no widget for schema`,
    crashing the balancing panel for the whole enemies domain. Do not
    reintroduce one.
  - **`enabled: false`** ⇒ dies normally, spawns nothing (the three stock
    non-boss types). Required-not-optional because `data/` is the only value
    store (no code-side `.get()` default) and the editor panel skips schema
    keys absent from the doc — an optional block would be invisible to the
    designer.
  - **Duck-typed contract read by `Session.on_enemy_death`** (game/core imports
    NOTHING from here): `death_spawn_plan` (a plain `{counts,
    spawn_hp_fraction}` dict, or `None` when not enabled), `death_spawned`
    (read property) and **`mark_death_spawned()` — a METHOD**, because the E-11
    `GameObject.__setattr__` guard intercepts public property setters. The
    Session stashes the plan **opaquely** and hands it straight back to
    `Spawner.spawn_death_swarm(scene, col, row, plan)` without indexing into it.
  - **Footgun**: a `spawn_hp_fraction` at or below a child type's own
    `at_hp_fraction` makes the children die on the frame they appear — and
    chain, if that child also has an enabled `death_spawn`. There is
    deliberately NO runtime guard: data is the source of truth and the editor's
    0..1 spinbox bounds are the fence. The schema description says so.
  - **KNOWN LIMITATION — a death on the wave's LAST frame ends the round before
    its children appear.** The Session flushes the burst in `post_sim` before the
    wave-clear check, but `Scene.spawn()` only QUEUES while `by_tag()` reads
    `_objects`, so that check cannot see children burst on the same frame: the
    phase flips to `ROUND_END` and the children land on the next `scene.update`.
    **Pre-existing — 10G's boss swarm does exactly the same** (this is more
    evidence the ER-3 path is byte-identical, not a new bug), and rare for the
    Boss because it dies mid-wave with companions still alive. **It bites much
    harder for anything common** — an ER-4 Formation breaking as the last unit of
    a wave drops its children into an already-ended round. The fix is to teach the
    wave-clear check about pending spawns; ER-3 deliberately did not, being a
    zero-behaviour-change phase.
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
    `find_path_to_nearest_non_base_building`, and `adopt_goal` re-derives
    `goal_is_base` with `block_covers` (the block COVERS the base — it need not
    anchor on it).
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
  - **Known cosmetic gap — ER-4 INHERITED it, deliberately**: ER-1 draws the
    sprite centred on the *anchor tile's* diamond, scaled to `N × tile_w`, so for
    an even N the logical block sits half a tile down-right of where the sprite's
    centre lands (16px vertical, zero horizontal). Fixable only in the render
    layer — see the `## Formation (ER-4)` section above for the exact fix and why
    it wants its own phase.
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
  - **ESV-1 D4 — the spawn point is cosmetic, flight time never moves with it.**
    A defender's optional manifest `muzzle` anchor (`game/anchors.py
    world_offset`) shifts only WHERE `_fire`/`_fire_splash` spawn the
    projectile visually; `ProjectileHoming.launch(target, shooter, scene,
    origin=...)` always computes flight time from the shooter's UNMODIFIED
    `transform.world_pos`, passed in as `origin` — never from the anchored
    spawn point. `origin=None` (every pre-ESV-1 caller) falls back to the
    projectile's own spawn position, today's exact expression. Damage-arrival
    timing is therefore provably invariant under any muzzle value.
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
  applies, prototype-exact); `_repath` additionally re-reads it from the tile
  underfoot, the one place it went stale (BP-4). While unblocked it writes
  `mv.speed = _condition_speed()` every frame — since BP-1
  **`max(real × TileConditions.min_speed_fraction, real − enemy_speed_penalty)`**
  (mountain/forest −0.4 t/s).
  - **The floor is not a nicety — the old `max(0, …)` clamp was a LATCH.** The
    penalty is a flat 0.4 t/s and the boss moves at 0.3–0.45, so eras 0–3
    computed *exactly* 0.0 — and a unit at speed 0 never advances
    `Movement.index`, which is the only thing that refreshes
    `_current_condition`, so it stayed 0 forever. The boss was the one unit in
    the game slower than its own terrain penalty, and it froze solid on the
    first forest tile. Flooring at a fraction of the unit's **own** speed fixes
    it where a multiplicative penalty would have moved everyone's numbers: at
    the shipped `0.5` the four normal types are byte-identical (their
    `real − 0.4` still wins — walker 0.8, raider 2.3, siege 0.6, formation 0.5)
    and only the boss moves, off 0.0 and onto 0.15–0.225. **Anything above
    ~0.55 starts overriding the penalty for Formation too** — the fence is
    `test_boss.TestConditionSpeedFloor`.
  `EnemyCombat._effective_dmg` (`max(1, int(dmg × (1 +
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
- **10G / ER-3** — the same callback carries the death-spawn handshake, now
  **type-agnostic**: the session duck-types `death_spawn_plan` /
  `death_spawned` / `mark_death_spawned()` off ANY enemy and calls
  `Spawner.spawn_death_swarm(scene, col, row, plan)` back. What crosses the
  boundary is an **opaque plan dict**, not `(col, row, era)` — `game/core`
  never indexes into it, which is what keeps the layering structurally
  impossible to violate rather than merely conventional. `resolve_combat(
  dmg_bonus=0)` threads the boss-bonus story damage in as a plain int. Enemy
  construction never leaves this package.

## Perf note that lives here
`Enemy.on_spawn`'s `find_path` (and its `find_path_ignoring_walls` fallback)
now walk the shared base flow field — a wave of hundreds of spawns pays ONE
Dijkstra per map-topology change, not one each, and `spawn_death_swarm`'s
burst rides it for free. Since ER-2 the field caches on
**`(ignore_walls, footprint)`**, so the invariant is one Dijkstra per topology
change **per footprint** — still NEVER one per enemy. Passing a footprint into
`find_path` must therefore stay a plain argument; do not add a per-enemy search.
`Boss.on_spawn`'s `find_path_to_nearest_non_base_building` stays a fresh
Dijkstra, as every goal-set variant does — but note BP-3 makes the boss re-path
**once per kill** rather than once per wave, plus once when a target dies to
someone else. That is still a handful of searches per boss per round (there is
one boss), not one per enemy, so the flow-field invariant holds. If a future
enemy type ever arms `repath_on_kill`, re-measure. Nothing in this package
invalidates the field directly — all mutations route through `TileMap`. Detail →
`game/PERF.md`.

## Verify
Scripted round asserts HP ledger matches hand-computed prototype values:
`py -m unittest discover -s tools/tests -t .`.
