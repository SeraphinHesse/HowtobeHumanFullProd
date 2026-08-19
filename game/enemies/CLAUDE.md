# CLAUDE.md — game/enemies (Phases 9E + 10F + 10G + ER-4 + NE-1 + NE-2 + NE-3)

`Enemy(GameObject)` walker + `Spawner` + a type-agnostic combat sweep, porting the
prototype's `src/enemies/*` and `game.py` enemy/spawn/combat loops. You reached
here from `game/CLAUDE.md`. **All five enemy types are LIVE**: Standard + Raider +
SiegeCannon since 10F, `Boss` since 10G, `Formation` since ER-4 (`spawner.py`
`ENABLE_RAIDERS`/`ENABLE_SIEGE`/`ENABLE_BOSS`/`ENABLE_FORMATION = True`); the
sixth, `Commander`, exists since BR-2 with `ENABLE_COMMANDER = True` but ships
**dormant** — see its section below. The seventh, **`Sniper`, is LIVE since NE-1**
(`ENABLE_SNIPER = True`, `start_round: 26`) and is the first type that fights at
RANGE — see "Ranged stand-off" below. The eighth, **`Digger`, is LIVE since
NE-2** (`ENABLE_DIGGER = True`, from `start_round: 35`) and is the one type
that adds a genuinely new state machine — see its section below. The ninth,
**`Drummer`, is LIVE since NE-3** (`ENABLE_DRUMMER = True`, from round 25) and
brings the game's FIRST buff/aura mechanism with it — read its section before
adding any status effect. When you
change enemy conventions, update THIS doc. **Adding an enemy type? Use the
`/add-enemy` skill.**

## The era clock (ES-1..ES-5) — read this before any scaling question
Difficulty is ONE global clock, not the two that used to be bolted together.
`EnemyScaling.rounds_per_era` (10) and `boss_round_in_era` (10) live in
`data/balancing/enemies.json`; `scale_every_n_levels`, `scale_tiers` and
`Boss.round_interval` are **deleted**. Every formula is
`engine/era_math.py` — no era arithmetic is written out anywhere in this
package (D7).
- **D1 — clock.** `era = (round − 1) // rounds_per_era`, `round_in_era =
  (round − 1) % rounds_per_era + 1`, boss round iff `round_in_era ==
  boss_round_in_era`. Round 0 is era 0 by definition and is never a boss round
  (D11, clamped inside `era_math`, so no caller carries the guard).
  `Spawner.enemy_tier` survives only as a read-only alias of `enemy_era`.
- **D2 — per-era stats are fresh MANUAL values.** Each type carries
  `eras: [{stats:{hp,dmg,move_speed,attack_speed,attack_range_tiles},
  per_round:{hp,dmg,move_speed}, count_start, count_per_round}]`. A row IS the
  answer — there are no cumulative bonuses to add. In-era growth is the flat
  additive `stats + (round_in_era − 1) × per_round`; `attack_speed` and
  `attack_range_tiles` change BETWEEN eras only.
- **D3/D3′ — counts are data.** `floor(count_start + (round − r0) ×
  count_per_round)` with `r0 = max(era's first round, the type's global
  `start_round`)`. `count_per_round` is fractional-capable (⅓ is the old
  Formation accretion) and **`count_start` is a NUMBER, not an int** — see
  `data/CLAUDE.md`. `base_count`/`per_round`/`rounds_per_cannon`/
  `rounds_per_formation` are gone.
- **D4 — batch spawning**: `EnemyScaling.eras[era].batch_size` enemies leave
  the queue per timer expiry (see the spawner bullet in Rules).
- **D5 — past the last authored era**: the row clamps AND the type's own
  `endgame_scaling: {hp, dmg, move_speed, count}` (plus
  `EnemyScaling.endgame_scaling: {batch_size, spawn_interval}`) compound as
  `value × factor ** N`. All factors ship 1.0, so today this is exactly a
  clamp — and the old "past tier 5 stats freeze while counts climb forever"
  cliff is gone.
  - **A `0.0` factor is NOT a clamp — it is a kill switch, and this has
    shipped broken before.** `factor ** N` for `N ≥ 1` makes `0.0` zero the
    stat outright the moment the round crosses past the authored table, not
    "stop growing it." A 2026-08-10 balancing edit set `move_speed` (and
    several `hp`/`dmg`/`count` factors) to `0.0` on most live enemy types,
    which meant every enemy spawning from round 51 onward (round 51 = the
    first round whose era, 5, falls past the 5-row authored table at
    `rounds_per_era=10`) got `Movement(speed=0.0)` and froze on its spawn
    tile forever — no exception, since `resolve_era_row`/`engine/era_math.py`
    compute a perfectly well-typed zero. Fixed by restoring every factor to
    `1.0` and adding `exclusiveMinimum: 0` to all three `*_endgame_scaling`
    schema defs (`boss_endgame_scaling`/`pacing_endgame_scaling`/
    `type_endgame_scaling` in `data/schemas/enemies.schema.json`) so `0.0`
    can no longer be saved for a compounding factor. If a design ever truly
    wants "stat hits zero past round 50," it must clamp the base stat to 0
    directly in the last authored era row, not lean on this multiplier.
- **D10 — `hunts` and `condition_path_weights` are PER-TYPE, NOT per-era**, and
  so are `kidnapping`, `death_spawn`, `registry_group`, `start_round`,
  `mix_ratio`, `queue_lead_count`. The
  restructure moved only the numbers that scale with the round. A Raider hunts
  economic buildings in era 0 and in era 9 — nothing in the "Prey hunting"
  section below is era-indexed or was touched by this rework. Promoting them
  into era rows later would be additive; do not pre-build it.
  - **`footprint`/`sprite_scale` ARE per-era, on every type, and have no flat
    home left.** They were on this list until BR-1 carved out the Boss; the
    per-era-footprint change then moved every era-shaped type's pair into its
    own `eras[]` rows (`$defs/type_era_row`) and DELETED the type-root keys.
    A body's size is a number that scales with the round after all — the
    Formation grows 2→2→3→3→4 across eras 0–4. **`endgame_scaling` carries no
    factor for either**, so past the last authored era a size clamps; only
    the Boss's `endgame_boss_scaling` can grow one.
- Editor support: era arrays are `minItems 1` with no `maxItems`, so the
  balancing panel's ER-5 `+ Row`/`− Row` buttons work on them, and every era ≥ 1
  field shows a greyed previous-era reference (D9, `editor/panels/CLAUDE.md`).

## Boss (10G)
- **Boss rounds**: on a round the era clock calls a boss round
  (`era_math.is_boss_round`, D1 — `Boss.round_interval` is deleted) `_compose`
  routes to `_boss_round` — `[ONE boss] + ALL siege + shuffle(standard +
  raiders + commanders)`, counts from `Boss.round_counts[era]`, **falling back
  past the 5-row table to the ordinary per-type `_count_of` counts**.
  - **BR-4 swapped that fallback for the endgame-scaled era-4 row; BR-5
    REVERTED exactly that branch (user decision) and kept everything else BR-4
    shipped.** So a round-60 boss round is 295/46/37 companions again, not the
    era-4 table's 700/215/61 — the escort follows the ordinary per-type curve
    while the BOSS ITSELF still grows through `endgame_boss_scaling` (stats,
    fit, shake, `second_phase.spawns`). If the "a round-60 boss round is
    lighter than a round-50 one" cliff is ever to be closed, close it in the
    per-type era rows or by re-swapping THIS ONE branch — deliberately, not by
    accident. Measured: rounds 0–60 of the real `Spawner` (12,659 queue
    entries, trailing rng state included) are byte-identical to BR-3.
  - **`round_counts[era]["commander"]` IS wired since BR-5** (it was authored
    in BR-1 and consumed by nothing until then). Composed **LAST**, after the
    standard and raider picks, so the shipped all-zero counts draw no rng and
    every deterministic wave fixture holds — the same rule
    `_formation_group`/`_commander_group` follow.
  NO
  siege lead/mix split on boss rounds. The boss entry's **`era` constructor
  argument IS the global era** (the old `tier` channel, renamed at its source) (`era_math.era_of_round`, clamped in `Boss._resolve_era`;
  pop-time via `Spawner._boss_era`); companions carry the same era.
- **`Boss` hunts buildings, hole LAST (BP-2 / D2)**: `EnemyTypes.Boss.hunts ==
  "any_non_base"` routes it through the generic `Enemy.on_spawn` (Chunk 4 —
  `Boss.on_spawn` itself is DELETED, see "Prey hunting" below) via
  `find_path_to_nearest_non_base_building`, arming
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
  `death_spawn`** (below), and since BR-3 the boss's block is renamed
  **`second_phase`** and staged (see the next section). The boss ships
  `at_hp_fraction: 0.0` + `spawn_hp_fraction: 1.0` + `enabled: true` and its 5
  per-era rows moved
  verbatim to `Boss.second_phase.spawns`, so the counts/tile/era are
  unchanged: same counts, same tile, same CURRENT era (each child resolves its
  own era row), children at full HP. `Boss` itself is now just `_resolve_era` +
  `_resolve_stats` + `era` — its `__init__` is gone (9E-era), and its
  `on_spawn` override is gone too (Chunk 4 — collapsed into the generic
  `Enemy.on_spawn`, see "Prey hunting" below).
- **The boss keeps its OWN 5-row `stats[]` table** — it is the ONE type that
  does not carry `eras[]` (reshaping it into `eras[]` is still
  `planning/BossReworkPLAN.md`'s job). `Boss._stat_row(block, era)` is the ONE
  resolver for it since BR-4 (`_resolve_stats`, `resolve_fit` and `shake` all go
  through it, so they can never disagree about which era they are);
- **EVERY boss variable is PER-ERA (BR-1).** `footprint`, `sprite_scale` and
  `shake: {interval, strength}` were single GLOBAL keys on `EnemyTypes.Boss`
  shared by all five bosses; they now live in each `stats[]` row and the
  global keys are DELETED. `shake` is still the Boss's alone; `footprint`/
  `sprite_scale` are no longer — the per-era-footprint change did the same
  move for all nine era-shaped types, into their `eras[]` rows (D10 above).
  What stays boss-specific is only WHERE its pair lives (`stats[]`, since it
  has no `eras[]`) and that `endgame_boss_scaling` can grow it past the table.
  - **`Enemy.resolve_fit(block, era)` is the ONE seam** deciding *where* a
    type's `(footprint, sprite_scale)` lives. A `classmethod`, because
    `spawner._footprint_of` needs the footprint to pick a spawn tile BEFORE
    the enemy exists — so `__init__` and the clearance filter can never read
    different values. **Both sides of it are per-era now**: the base resolves
    the type's own `eras[era]` row through `era_math.resolve_era_row` (with
    `cls.endgame_factors(block)`, which is `None` for everything but the
    Boss, so it plainly clamps); `Boss` overrides it to read its clamped
    `stats[era]` row (`Boss._stat_row`), because it carries no `eras[]`.
    The base used to return two flat type-root keys, which no longer exist.
    `_pick_spawn_tile` passes `_boss_era` for a boss and `_era` for
    everything else.
  - **The shake is read off the LIVE boss**, not re-derived from the round
    number: `Boss.shake` is a duck-typed property (a dict COPY) beside
    `era`/`death_spawned`, and `game/main.py`'s camera-shake driver takes it
    from the first alive object it already finds via `by_tag("boss")`.
  - **FIXED in BR-5** (it was a known BR-1 follow-up): `editor/sprite_fit.py`'s
    `slot_draw_fit` read `EnemyTypes/<type>/footprint`/`sprite_scale` FLAT, so
    for the Boss it raised `KeyError` — swallowed by a bare `except Exception`
    — and every `boss_era_*` preview silently drew at the `(0.0, 1.0)` render
    defaults for four phases. It now resolves the `stats[]` row whose index is
    the slot's position among its top group's era child groups, and the
    tolerance net wraps the two data LOADS only. It does NOT import
    `Enemy.resolve_fit`: `editor/` may never import `game/` (D5), which is why
    `registry_group` exists as data in the first place. See
    `editor/panels/CLAUDE.md`.
- **ENDGAME BOSS SCALING (BR-4) — `EnemyTypes.Boss.endgame_boss_scaling`.**
  Past the last authored era the boss no longer repeats verbatim: the last row
  is grown by `value × factor ** N`, `N = era − (len(stats) − 1)`. **ONE block
  covers all THREE of the boss's per-era arrays** (D1) — `stats[]`,
  `round_counts[]` and `second_phase.spawns[]`.
  - **It is `engine.era_math.resolve_era_row`, not a boss-only helper** — the
    same ES-4 function every other type's `eras[]` rows go through. Consequence
    that drives the SHAPE OF THE DATA: the resolver matches a factor to a leaf
    **by leaf name**, so the block's keys are the leaf names those rows carry —
    `hp`/`dmg`/`move_speed`/`attack_speed`/`attack_range_tiles`/`footprint`/
    `sprite_scale`, `interval`/`strength` (the two `shake` leaves — NOT
    `shake_interval`, which would silently never match), and
    `regular`/`raiders`/`siege`/**`commander`** for the count rows. A missing
    name is 1.0, so a key omitted here scales silently not at all.
    **`second_phase.staging` is the ONE per-era boss array deliberately kept
    OUT of this path** (BR-5): it is resolved with `endgame_factors=None`, a
    plain clamp. Its leaves are fractions and a per-child delay — no factor
    name collides with them today, so routing them through would be a silent
    no-op, and the first designer to add one would drive `at_hp_fraction` past
    1.0, which fires the phase the instant the boss spawns.
  - **All factors ship 1.0, which is EXACTLY the old clamp** — `_scale_leaf`
    floors only leaves that were ints in the authored row, so an int floors back
    to itself and a float is untouched. Measured: rounds 0-59 of the real
    `Spawner` and the boss's resolved stats/fit/shake/second-phase counts at
    eras 0-8 are byte-identical to BR-3. **Round 60 is the ONE deliberate
    change** (see the boss-round bullet above): 295/46/37 companions → the era-4
    table's 700/215/61.
  - **`Boss._resolve_era` no longer clamps** — it returns the GLOBAL era, and
    `Boss.era` with it. It has to: the clamp is what tells `resolve_era_row` how
    far past the table we are, and clamping in the caller would freeze every
    era-5+ boss at exactly the cliff this removes. `DeathSpawn.era` therefore
    now holds the global era for a boss too; nothing in `game/` reads it but
    `Boss.era`.
  - **`Enemy.endgame_factors(block)` is the seam** (a classmethod beside
    `resolve_fit`): `None` for every type but the Boss, which returns its
    `endgame_boss_scaling`. It is why `Enemy.__init__`'s single
    `resolve_era_row(ds["spawns"], …)` call serves both the boss's 5 scaled
    rows and every other type's single always-clamping one.
  - **`round_counts[era]["commander"]` is WIRED since BR-5** — see the
    boss-round bullet above. The `commander` factor here only ever reaches
    `second_phase.spawns` now, because BR-5 also took `round_counts` off the
    past-the-table path.
- `dmg_bonus` (the 10G optional kwarg on
  `resolve_combat`, default 0) is the boss-bonus story damage crossing the
  boundary as a plain int, added at fire time in all three firing paths.

## The boss's SECOND PHASE (BR-3) — the staged death
`EnemyTypes.Boss.death_spawn` is renamed **`second_phase`** (`$defs/
second_phase`, a standalone copy of `$defs/death_spawn` plus two keys — never
an `allOf`/`oneOf`, same balancing-panel reason as everywhere else) and gains
`delayed_spawns` (bool) + `spawn_delay` (seconds PER CHILD, not a phase
total). **Only the Boss** — every other type still carries `death_spawn`, and
`Enemy.DEATH_SPAWN_KEY` (a class attr, `"death_spawn"`; `Boss` overrides it to
`"second_phase"`) is the ONE place that difference lives. The resolved fields
are identical either way, which is why this is a key and not an `__init__`
override.
- **`delayed_spawns: false` is byte-identical to the one-frame burst.** The
  new `DeathSpawn` fields all default to the historical behaviour, so a block
  without them (every non-boss type) resolves to exactly today's component.
- **`delayed_spawns: true`**: crossing `at_hp_fraction` does NOT kill the boss.
  It freezes (`Movement.speed = 0` + the new `PathAgent.frozen`, the
  `carrying` precedent — `EnemyCombat` reads the same flag, because a boss
  frozen mid-swing keeps whatever `blocked` state it stopped in), goes
  untargetable, plays `endphase`, trickles one child per `spawn_delay` at its
  own tile, then dies through the **normal** path (XP, kill count, splatter,
  `Corpse`).
- **Two properties carry the whole thing, and both are the SINGLE evaluation
  site of their question:**
  - `Enemy.alive` returns True for an enabled+delayed unit until
    `phase_complete`. That one line is what keeps combat, `_resolve_base_
    arrivals` and the wave-clear check all correct with **no change to any of
    them** — `Session.post_sim` needed nothing at all.
  - `Enemy.targetable` (new, duck-typed — everything reads it as
    `getattr(obj, "targetable", True)`) is derived straight from HP, NOT from
    `phase_started`, so it flips on the SAME frame the crossing blow lands and
    the boss can never eat one extra volley. Readers: `combat.py`'s one
    `enemies = [...]` filter (which removes it from every defender's
    `in_range` at once — homing, splash and beam alike), `ProjectileHoming.
    _impact` + `ProjectileArc._impact` (a shot in flight is wasted, D2),
    `_update_beam`'s sticky-target check, `game/core/lightning.py` (the storm
    is a damage source too), and BOTH bars in `game/ui/effects.py`
    (`submit_enemy_hp_bars` and `submit_boss_bars`).
- **The machine is split by capability, not arbitrarily.** State lives in
  `DeathSpawn` (`delayed`, `spawn_delay`, `phase_started`, `phase_complete`,
  `phase_timer`, `pending` — all declared JSON-safe, E-11); the LOGIC is
  `Enemy.advance_second_phase(dt)`, which returns the etypes due this frame and
  **never touches the scene**; the SPAWNER (`Spawner._advance_second_phases`,
  called FIRST in `update` — before the `if not self._queue: return`, because a
  boss stages long after its wave queue has drained) turns them into enemies
  through `_spawn_child`, the one per-child path `spawn_death_swarm` also uses
  now. `dt` is the host's speed-scaled `sim_dt`, so the cadence holds at
  1.5×/2× — the `Corpse` fade-clock rule.
- **The phase claims `death_spawned` at its START**, so the eventual normal
  death cannot ALSO stash a `death_spawn_plan` with the Session and double-burst.
- **The `endphase` / `death` rows are NOT in the manifest, and adding
  placeholder ones would be WRONG (measured, BR-5).** A manifest row's index
  IS its sheet row (`engine/assets/manifest.py`: `Track.row = row_idx`; there
  is no explicit row key), and every `boss_era_*` sheet is exactly as many
  rows tall as it declares (era 0: 384×288 = 3 rows of 96; eras 1–4 are
  single-row). Appending an `endphase` row therefore resolves to sheet row 3,
  which `engine/assets/store.py` logs as "outside its sheet" and replaces with
  the **grey-X placeholder** — for the entire second phase. Leaving the rows
  absent IS D4's graceful fallback and is strictly better art:
  `Manifest.current_frame` falls back to the IDLE row for a missing animation,
  and `animation_total_ms` returns `None` for a missing `death` row, which is
  the existing no-corpse behaviour. Real rows land with real art, via
  `/replace-visual`.
- **Camera shake keeps firing on a frozen boss (BR-3 finding, NOT fixed).**
  `game/main.py`'s driver keys off `by_tag("boss")` + `alive`, and `alive` is
  True for the whole second phase — so a frozen, untargetable boss still
  shakes the screen. It may well be intended drama; it is a one-line change at
  the driver if it is not. Flagged for the user, deliberately untouched.
- **Known limitation, now much more visible (NOT fixed here).** The wave-clear
  check cannot see children spawned on the round's last frame (see Rules
  below). A boss frozen for several seconds makes that window wider; BR-3
  deliberately did not expand scope into it. Flagged for the user.
- **PER-ERA since BR-5 — `second_phase.staging[]`.**
  `at_hp_fraction`/`spawn_hp_fraction`/`delayed_spawns`/`spawn_delay` were
  single GLOBAL values on the `second_phase` block; they now live in a 5-row
  `staging` array index-aligned with `stats[]`/`round_counts[]`/`spawns[]`
  (`$defs/second_phase_row`, `minItems`/`maxItems` 5 like the boss's other
  pinned arrays). `spawns[]` did NOT move.
  - **They are their own array, not extra keys on a `spawns[]` row** — D7:
    those rows are `$defs/spawn_counts`, SHARED with every other type's
    `death_spawn.spawns`, so a boss-only threshold key there would land on all
    14 committed rows.
  - **`Enemy.resolve_phase_row(ds, era)` is the ONE seam**, the exact shape of
    `resolve_fit`: base returns the flat `death_spawn` block (a Formation
    breaks at half health in era 0 and in era 9), `Boss` overrides it to
    `resolve_era_row(ds["staging"], era, None)` — no endgame factors, on
    purpose (see the endgame section above).
  - **D5's tuning, the ONE gameplay change in BR-5**: era 0 ships
    `at_hp_fraction 0.5` + `spawn_hp_fraction 0.5`; eras 1–4 keep `0.0`/`1.0`.
    Era 0's `spawns` row ships `commander: 1` (added after BR-5, with the
    user's approval), so the era-0 boss stages into a real two-phase fight:
    at 50% HP it freezes, turns untargetable, plays `endphase`, releases ONE
    Commander at its own tile, then dies. Shipping the thresholds *without*
    that count is what makes the boss effectively 700 HP instead of 1400 —
    the two are a pair, so never tune one to zero alone.

## Commander (BR-2) — LIVE code, DORMANT data
The boss's officer. **Nothing spawns it today** and that is the phase's whole
invariant: BR-3 wires it to the boss's second phase.
- **The subclass is four class attrs plus an HP-bar width** — `ETYPE
  "commander"`, `REGISTRY_GROUP "Commander"`, `DEFAULT_SLOT
  "commander_stage_1"`, `STAT_SUBTREE ("Commander",)`, `HP_BAR_W/H = 24, 2`
  (siege-sized). No `__init__`, no `on_spawn`, **no `_resolve_stats`**, no
  `_resolve_era`, no `EXTRA_TAGS` — so no `"boss"` scene tag and therefore no
  camera shake and no boss HUD bar, both of which key off that tag.
- **It is a NORMAL era type** (D8): the base `STAT_SUBTREE`-driven resolver
  reads its own `EnemyTypes.Commander.eras` rows — including its `footprint` /
  `sprite_scale`, which sit in those rows like every other era-shaped type's
  (they were flat at the block root until the per-era-footprint change).
  `Boss._resolve_stats` is still the ONE surviving stat override in the
  module. Do not add one here.
- **It hunts buildings like the Boss with no boss-specific code**: `hunts:
  "any_non_base"` is all it takes — the generic `Enemy.on_spawn` runs the
  goal-set query, arms `PathAgent.repath_on_kill` and calls `adopt_goal`
  (so `goal_is_base` is False while any non-base building stands). Same
  collapse that deleted `Boss.on_spawn` in Chunk 4.
- **Dormancy is DATA, in two independent places**, and both must stay 0 for
  BR-2 to hold: every `eras[]` row's `count_start`/`count_per_round`
  (so `Spawner._commander_group` emits nothing and draws no rng), and every
  `$defs/spawn_counts` row's `commander` (BR-1 added the key at 0 to all 14).
  Every schedule key exists, so switching it on is a data edit alone.
- **`_commander_group` is called LAST in `_compose`, after
  `_formation_group`** — the same rule the Formation follows: an earlier call
  site shifts every other group's rng draw sequence and moves the
  deterministic wave fixtures. Measured: rounds 0–60 composed on the real
  `Spawner` are byte-identical to BR-1 (12,659 queue entries).
- **`SWARM_TYPES` gained `("commander", "commander")` in BR-3, appended
  LAST.** Until then a non-zero `commander` count in ANY `spawn_counts` row
  silently spawned nothing (BR-2 shipped the type but not its spawn wiring).
  The table now lives in `enemy.py`, not `spawner.py` — BR-3's second phase
  lays out its child queue from the SAME order and `enemy.py` cannot import
  the spawner (the dependency runs the other way); `spawner._SWARM_TYPES` is
  kept as an alias. Appending LAST is the same rng rule the composition groups
  follow, and it is **measured**: a 55-child era-4 burst and the rounds-0..60
  queues (12,659 entries) are both byte-identical to BR-2, trailing rng state
  included.
- No manifest rows: its four `data/slots.json` era slots
  (`commander_stage_1..4`) ship art-less, which is the normal grey-X
  placeholder state (a slot with no `asset_manifest.json` entry is legal and
  common). Real art lands via `/replace-visual`.

## Ranged stand-off (NE-1) — `PathAgent.stand_off_range` / `in_range`
**Until NE-1 every enemy in the game was a melee unit.** `attack_range_tiles`
and `RangeSensor` exist on all of them and are read by the DEFENDER range gate
(`combat.py`) only — *nothing* consulted them for an enemy's own attack, so
every type walked until something physically blocked it and then punched that.
The Sniper is the first exception, and it is built out of one flag pair, not a
second combat system.
- **`PathAgent.stand_off_range: int = 0` and `PathAgent.in_range: bool =
  False`, both default-off** — the `goal_is_base`/`repath_on_kill` precedent
  exactly. At `stand_off_range == 0` the check short-circuits on its first
  comparison, so **every other type's `update()` is byte-identical** (pinned by
  `test_enemies.TestStandOffIsOffForEveryOtherType`, which also asserts the
  melee block-and-attack path still sets `blocked` and never `in_range`).
- **`in_range` is the RANGED TWIN OF `blocked`.** `EnemyCombat.update()`'s gate
  widened from `pa.blocked` to `pa.blocked or pa.in_range` — that `or` is the
  entire combat change. The cooldown tick, the condition-modified damage, the
  `RoundStats` credit, the debug hook and the kidnap arming are the same lines
  they always were. **Do not add a second attack path**; if a ranged mechanic
  cannot be expressed as "halt, then run the existing clock", it wants its own
  component, not a fork of this one.
- **The check runs EVERY frame, BEFORE the wall/blocker scan**, against the
  COMMITTED target (BP-3's `target_col`/`target_row`) — so a stand-off unit
  halts on geometry and **normally never reaches `blocked` at all**. Distance
  is `components.block_distance`, a block-to-block Chebyshev (per-axis clamp,
  then max) — the same "nearest tile of the block, not its centre" rule
  `combat.py`'s `_chebyshev` uses, so a footprint-N body measures the way the
  rest of the game measures.
- **Crossing into range CLEARS `blocked`/`_target`/`_wall_target`.** From that
  point the victim is resolved from the committed target, so a stale melee
  engagement would otherwise have the unit shooting whatever last blocked it
  instead of its actual prey. Leaving range (only ever via `_repath`) clears
  `in_range` and restores the walk animation; `mv.speed` comes back through the
  normal `_condition_speed()` write at the bottom of `update()`.
- **`PathAgent.committed_target(tm)` is the ONE resolver for "who am I
  shooting".** `_target_alive` is now one line over it — the block-wide,
  dead-occupant-safe scan is written once. `EnemyCombat` calls it only when
  `_target is None and in_range` (the blocker scan never ran), and the existing
  `target is None or not alive` guard below covers a corpse, so a ranged unit
  can no more hit a dead building than a melee one can.
- **Re-targeting needed NO new code.** The BP-3 dead-target watch is gated on
  `not blocked`, and a stand-off unit is never blocked — so the frame its
  victim dies it re-paths through the ordinary `_repath`. Verified, not
  assumed: `TestSniper.test_retargets_when_its_victim_dies`.
- **`begin_kidnap` clears `in_range` beside `blocked`** (`kidnap.py`). No
  shipped type is both a kidnapper and a stand-off unit (Sniper is
  `kidnapping: false`), but the two flags feed one gate and must be cleared
  together or a carrier would keep firing all the way home.
- **The balancing leaf lives ONLY on blocks that have the mechanic**, reached
  through `Enemy.resolve_stand_off_range(block)` — a classmethod seam of the
  exact shape as `resolve_fit`/`resolve_phase_row`/`endgame_factors`, returning
  `0` for every class and overridden only by `Sniper`. That `0` is not a G-7
  code-side default for an authored value; it is the statement "this type has
  no stand-off", which is what lets the six other `EnemyTypes` blocks stay free
  of a `stand_off_range: 0` they would never use.

## Sniper (NE-1)
The ranged stand-off type. **Four class attrs plus the one seam override** — no
`__init__`, no `on_spawn`, no `_resolve_stats` (the base `STAT_SUBTREE`
resolver reads its own `EnemyTypes.Sniper.eras` rows), no `_resolve_era`, no
`EXTRA_TAGS`, no `resolve_fit`.
- **It hunts `"defence"`, which NE-0 WIDENED** to every attack-capable building
  (`_ATTACK_BUILDING_TYPES` — defence, aoe_defence, storm_priest,
  sun_scorcher), so it stands off from mortars and Storm Priests too, not just
  plain Defenders. That widening is a prerequisite, not an implementation
  detail: with the old single-literal predicate the Sniper would walk past
  three quarters of the player's guns.
- **`stand_off_range` is FLAT at the type root, like `kidnapping`/`hunts`
  (D10)** — standing off at 2 tiles is the type's identity, not a number that
  scales with the round. (It was written here as "like `footprint`"; that
  comparison is dead — `footprint` went per-era for every type.) Keep it at or below `attack_range_tiles` or the unit
  halts outside its own reach; there is deliberately no runtime guard (the
  editor bounds are the fence), same policy as `death_spawn`'s
  `spawn_hp_fraction` footgun.
- **Seed stats are a STARTING POINT, fully retunable in the editor with no code
  change.** Era 0 ships `hp 150 / dmg 140 / move_speed 0.85 / attack_speed 2.6
  / attack_range_tiles 2`, `stand_off_range 2`, `start_round 26` — the
  qualitative brief (high damage, long range, slow attack, low HP, below-average
  speed) grounded against SiegeCannon era 0 (280/100/1.0/1.9/range 2). Eras 1–4
  follow the SiegeCannon growth-curve shape; `attack_speed` and
  `attack_range_tiles` stay flat between eras, as they do for every other type.
- **Composition: body-mixed, LAST in `_compose`, never on a boss round.**
  `_sniper_group` is called after `_commander_group` for the standing rng
  reason (an earlier call site shifts every other group's draw sequence and
  moves the deterministic wave fixtures). It draws nothing below round 26, so
  every wave under that round is byte-identical to BR-5; from 26 on it is a
  real, deliberate wave change. It does not lead the queue — a sniper at the
  head of the wave would out-range the player's defences before anything
  arrived to draw fire — and it is absent from boss rounds for the same
  `$defs/spawn_counts`-is-shared reason the Formation is (see that section).
- **No projectile visual in v1**: the hit applies instantly on cooldown, the
  same tick model as a melee swing minus the adjacency requirement. A
  muzzle-flash/arrow pass is a follow-up `/replace-visual`, and building an
  enemy projectile-travel system was explicitly out of NE-1's scope.
- Its five `data/slots.json` era slots (`sniper_stage_1..5`) ship art-less —
  the normal grey-X placeholder state, exactly like the Commander's.

## Digger (NE-2) — the burrow / claim / emerge machine
The one type that is a genuine NEW state machine rather than data over the
existing one. `ETYPE "digger"`, `REGISTRY_GROUP "Digger"`, `STAT_SUBTREE
("Digger",)`, `hunts: "structure"` (NE-0's category, whose first consumer this
is), `kidnapping: false`, footprint 1, `start_round: 35` (data-authoritative —
`data/balancing/enemies.json` currently ships 15; retune freely),
`spawner.ENABLE_DIGGER = True`. **Five times reworked for player feedback
(digger-hop-rework)** — Passes 1–4's summary is kept below for the historical
record, but **Pass 5 (the most recent) is a GROUND-UP REWRITE of the entire
underground movement mechanic, done at the user's explicit request** ("scrap
everything we know about the movement... redo it all") — nothing in Passes
1–4's knight hop, parity lattice, or readjustment fallback survives it. Read
the machine description below for what actually ships today; the history is
context for why it looks the way it does, not a description of current
behavior.

**Pass 1** made it walk visibly at most ONCE (spawn's approach to its first
claimed structure) — the old behaviour (emerge, strike, immediately re-path,
walk visibly to the next building) was the original bug: the player never saw
it coming and the walk-away beat read as broken, not menacing. **Pass 2**
replaced every underground relocation with a fixed-shape knight hop and
closed three gaps (never giving up permanently, hunting only "structure"
buildings, a WallBuilder perimeter sealing off the one overground walk).
**Pass 3** made a strike require landing EXACTLY on the target's tile (no
more "within some radius" snap) and added a short readjustment-dig fallback
for offsets the fixed hop shape's parity could never reach. **Pass 4** made
target *selection* prefer a hop-reachable building over the merely-nearest
one, so the Pass 3 readjustment stayed a rare fallback instead of the
routine first move. **Pass 5** throws all of that out: there is no more hop
shape, no more parity lattice, no more readjustment fallback, no more
multi-leg travel animation. A submerge now dives straight from the current
tile to a chosen destination tile, and the Digger simply reappears there —
invisible and untargetable the whole time — when the dig timer runs out.

- **`PathAgent.no_melee` (default OFF — every existing type byte-identical) is
  a DURABLE RULE, not a Digger detail, and unaffected by any of this.** When
  set, `update()` skips the halt-and-attack scan WHOLESALE: no
  `_wall_edge_ahead`, no `_blocker_ahead`, `blocked` never latches,
  `_target`/`_wall_target` stay `None`, and `EnemyCombat` (which ticks only
  while blocked) therefore never runs. **Routing is untouched** — the unit
  still walks the ordinary weighted path, around or through buildings exactly
  as before; it just never physically STOPS for one. It exists because a
  Digger has no attack outside digging: a halt on an incidental blocker would
  be a **permanent 0-damage soft-lock**, not a slow fight, because the thing it
  stopped for can never die. Any future type with no melee attack wants this
  flag, and any type WITH one must not have it.
- **`BurrowAgent` (`components.py`, beside `PathAgent`/`EnemyCombat`) is the
  machine**, and carrying one is what MAKES a unit a burrower — the claim scan
  identifies rivals by "has a `BurrowAgent`", never by class or `ETYPE`, so a
  second burrower would share the claim pool for free. Declared JSON-safe state
  only (E-11): `state` (plain strings `BURROW_WALKING`/`_SUBMERGED`/`_EMERGE`),
  `dig_range_tiles` (now BOTH the overground trigger distance and the
  underground targeting scan radius, both MANHATTAN — see below), `dig_speed`,
  `dig_timer`, `dig_duration`, `start_wx`/`start_wy` (this dig's entry tile —
  also the VFX telegraph anchor, `game/ui/CLAUDE.md`'s Digger telegraph
  section), `dest_col`/`dest_row` (this dig's destination tile),
  `emerge_cooldown`/`cooldown_remaining`, `min_target_distance_tiles`.
  - **WALKING — overground movement, on foot, visible. Spawn's initial
    approach AND every later "walk to a distant target" leg alike — unlike
    every earlier pass this is NOT spawn-only any more.** Whenever nothing is
    close enough to dig at, the Digger walks again (`retarget`, below). Each
    tick it measures MANHATTAN distance (not Chebyshev — user decision,
    "following the manhattan pattern") from its tile to the currently-claimed
    far target's BLOCK (`distance_to_target`/`block_tiles`, the same reason
    `_target_alive` scans the block: `target_col/_row` is the goal ANCHOR, not
    necessarily the body); once that's `<= dig_range_tiles`, it re-scans the
    local neighbourhood rather than blindly diving on that one target
    (`_arrived_in_range`, below) — something else may now be the preferred,
    FARTHER pick from this exact spot.
  - **SUBMERGED — a straight dive to `dest_col`/`dest_row`, nothing else (user
    decision: "the digger can only submerge and emerge").** No travel
    animation of any kind: the body simply vanishes from the tile it dove
    from and reappears exactly at the destination when `dig_timer` runs out
    (`_emerge`, below) — there is no intermediate lerp, no hop shape, no
    parity constraint to satisfy. `dig_duration` is the actual Manhattan tile
    distance between entry and destination over `dig_speed` — a real
    duration proportional to how far this specific dig actually goes, unlike
    every earlier pass's fixed hop-shape length.
    `Digger.targetable` reads this state, so combat, projectiles, the storm
    and both HP bars drop it at once (the duck-typed contract BR-3 built for
    the boss). **The Digger's own `SpriteAnimator` is also hidden entirely**
    (`visible = False`) rather than merely held on its dig pose — the
    dirt-pile decal and the two telegraph arrows are the only things that
    mark the spot.
    - **`_submerge` never dives from a tile a (possibly unrelated) LIVE
      building already occupies** — the route to the real target is a
      traversable weight, not impassable, and `no_melee` never halts for a
      blocker, so the walk can legitimately cross another building's tile
      first. Gated on the occupant being **ALIVE**, not merely "an occupant
      exists" (a live-playtest fix carried over from Pass 3): a just-struck
      building's CORPSE stays on its own tile as `tile.occupant` until
      payday revives it (`game/buildings/CLAUDE.md`'s kidnapping section),
      and an un-gated check would relocate the Digger off its own kill site
      on every subsequent dive, which used to read as "the hole keeps
      moving" even though the Digger was always diving from wherever it
      actually stood.
  - **EMERGE — a genuine STANDING state, not a one-frame pass-through.**
    Entered by the dig clock expiring: snap onto `dest_col`/`dest_row`,
    become visible, and strike whatever alive, non-base building (if any)
    occupies that EXACT tile (`_occupant_at` + `_strike`, the unchanged
    eruption mechanic). **This single occupancy check does the job three
    separate mechanisms (D5's mid-dig interrupt, the exact-tile-match rule,
    the readjustment strike) used to split across in earlier passes**: a
    real committed target that's still alive when the dig completes gets
    struck; a target that died to something else while the Digger was
    underground simply has no occupant left on its tile by the time the
    Digger arrives, so nothing happens — no separate mid-dig interrupt logic
    is needed at all. A repositioning dig (below) always picked a tile that
    was verified empty when chosen, so it never strikes anything either. The
    Digger's commitment (`PathAgent.target_col/_row`) is always cleared here,
    win or lose — the NEXT decision starts with a completely fresh scan.
    Either way `cooldown_remaining` is armed to `emerge_cooldown` and the
    Digger does **nothing else — no walking, no re-targeting** — until it
    drains: this is the "stand there for a duration" beat, and it fires
    after EVERY dig, strike or not, so the player always gets a visible
    surfacing, never a silent disappear-and-reappear. Once the stand drains,
    `retarget` runs.
  - **The eruption hit is `EnemyCombat.update()`'s single-target damage
    application verbatim** — `_effective_dmg(pa)` (so the 10I terrain bonus
    still applies) → `Health.damage` → the `RoundStats.dmg_taken_this_round`
    credit → `_damage_hook` at exactly that credit line. No kidnap arming
    (Diggers ship `kidnapping: false`).
- **`retarget` (`components.py`) is the ONE decision point — spawn's first
  move and every later one alike.** No more "spawn-only" special case: this
  single method covers the whole cycle.
  1. **Look around.** `_commit_local` (via `_farthest_in_range`) scans for
     the FARTHEST unclaimed structure within `dig_range_tiles` Manhattan
     tiles of the current tile — **"high range beats close range" (user
     decision: "Diggers always focus buildings that are in high range rather
     than close range... they should fall back to close range... if no
     building is in high range")** — and, if found, commits
     (`PathAgent.target_col/_row` = it) and submerges straight onto it.
  2. **Nothing in local range, but an unclaimed structure exists somewhere
     on the map** → `_start_walk` runs real pathfinding
     (`find_path_to_nearest_structure`, claim-exclusion + the
     `min_target_distance_tiles` walk-preference threaded through) to the
     nearest one and starts walking. **No route to it at all (or only the
     base fallback)** → `_reposition` instead: submerge onto the nearest
     tile with no building occupant (skipping the current tile — a genuine
     move, not a no-op) and resurface there, no strike, purely to reset
     pathfinding from a new position (user decision: "if the digger cannot
     walk into range of his target building, because [other] buildings
     block the path, the digger submerges and emerges on a free tile to
     restart the pathfinding"). This REPLACES Pass 2's walls-ignoring
     fallback outright — a blocked walk of ANY kind (not just a wall) now
     triggers a reposition, never a second wall-tunneling pathfind attempt.
  3. **No unclaimed structure anywhere at all** → the same two steps
     (1)/(2), widened to boost and economy buildings
     (`find_path_to_nearest_boost_or_economic_building`, over
     `_BOOST_ECONOMY_BUILDING_TYPES` — the three `boost_*` types unioned with
     the pre-existing `_ECONOMY_BUILDING_TYPES`) — user decision: "if there
     are 0 structure buildings on the map left for the Digger to focus he
     focuses boost and economy buildings instead".
  4. **Nothing at all, anywhere, in either category** → `_stand_down`.
  - **`_arrived_in_range`** is what fires once a walked-toward far target
    finally comes within Manhattan `dig_range_tiles` — it does NOT blindly
    commit to that one target; it re-runs the SAME local scan (current
    category, then widened) from the arrival tile, so a different, farther
    building discovered only on arrival can win instead, per the same
    "high range beats close range" rule. Nothing qualifying after all (rare
    — the sole candidate died or got claimed by a rival the instant this
    Digger arrived) falls through to a fresh `retarget` call.
  - **`_stand_down`**: visible, idle, harmless, no waypoints,
    `PathAgent.target_col = target_row = -1`, `goal_is_base` forced back OFF
    (a stale `True` would fire a phantom base breach on the next reported
    arrival — the `begin_kidnap` finding), state forced to `BURROW_WALKING`.
    **Not a terminal state**: it arms `cooldown_remaining = emerge_cooldown`,
    and `_tick_walking`'s own `target_col < 0` branch ticks that timer down
    and re-runs `retarget` once it drains — reusing the exact same
    stand-duration cadence as the post-dig stand. A rival's claim freeing
    up, or the player placing a new building, is noticed on the Digger's
    very next re-check rather than never. Diggers still never fall back to
    attacking the hole.
- **`emerge_cooldown` (balancing) / `cooldown_remaining` (runtime) — the
  stand duration, doing double duty as the periodic-recheck cadence while
  stood down too.** Counted from the moment the Digger comes up (a strike, a
  no-strike dig, or a reposition all arm it) to the moment `retarget` is
  allowed to run again. `0.0` is a no-op (a hand-built headless Digger with
  no balancing behind it stays byte-identical); the shipped
  `EnemyTypes.Digger.emerge_cooldown` is `2.5` seconds, a flat type-root leaf
  (D10 — a starting value, tune in the editor).
- **`Digger.targetable` is overridden off the SUBMERGED state** — the exact
  duck-typed contract BR-3 built for the boss's second phase, so combat
  targeting, in-flight projectiles, the lightning storm and BOTH HP bars drop a
  burrowed Digger with **no per-site change anywhere**.
- **`repath_on_kill` stays OFF for the Digger, and that is why
  `Digger.on_spawn` overrides the generic one.** `PathAgent._repath` would
  re-run `_HUNT_QUERIES["structure"]` with no claim exclusion, and would
  silently accept the query's empty-goal-set fallback to the hole.
  `BurrowAgent.retarget` is the ONE pathfinding-based re-targeting path — and,
  since Pass 5, it runs on EVERY decision, not just at spawn.
- **`Enemy.nav_components(block)` is the seam** placing `BurrowAgent` between
  `PathAgent` and `Movement`: after the agent's walk/halt decision for the
  frame, before the locomotion that would act on it. `()` for every other type.
  Same shape as `resolve_fit`/`resolve_phase_row` — the component ORDER is the
  invariant, so it stays at ONE construction site. Threads `dig_range_tiles`,
  `dig_speed`, `emerge_cooldown`, `min_target_distance_tiles` — Pass 5 dropped
  the two knight-hop leaves (`dig_hop_long_tiles`/`_short_tiles`) from both
  this call site and the schema; they no longer exist anywhere.
- **`Digger._resolve_stats` substitutes the flat `dig_speed` for the era row's
  `move_speed`** — the brief's "one speed value for both phases", made provable
  in code rather than trusted to two authored numbers staying equal. The era
  rows still carry `move_speed` (`$defs/type_era_row` requires it and the
  balancing panel renders it); for this type alone it is INERT, and the schema
  description says so.

### The exclusive claim
**A claim is nothing but another Digger's `PathAgent.target_col/_row`** — there
is no registry, and nothing to leak. `BurrowAgent.claimed_tiles` scans
`scene.by_tag("enemy")` for other live burrowers and passes their committed
tiles as `exclude` into whichever query is asking — `_start_walk`'s real
pathfinding, or the SAME `_goal_tiles` predicate `_commit_local`/
`_arrived_in_range` scan directly (no pathfinding, straight-line only). A
claim lasts from the moment the Digger commits to a building until it
EMERGES (whether or not the dig struck anything) — `_emerge` unconditionally
clears `PathAgent.target_col/_row`, so every decision after a dig starts with
a completely fresh scan. This is a real behavior change from every earlier
pass's "stay committed across multiple hops toward the same target" rule:
since a single dig now always resolves (strike or miss) in one step, there is
no longer a multi-step chase to stay committed through.
- **No target after exclusion, anywhere, in either category ⇒ STAND DOWN** —
  see `_stand_down` above; it periodically re-checks rather than parking
  forever.
- **Blocked paths reposition instead of tunneling through walls (Pass 5 — a
  deliberate behavior change from Pass 2).** Pass 2 gave the Digger's ONE
  overground walk an `ignore_walls=True` fallback pathfind attempt, tried
  only once the normal wall-respecting route came back empty/base-only.
  Pass 5 removes that fallback entirely: `_start_walk`'s single pathfind
  attempt stays wall-respecting, and ANY failure (a wall, a fully-enclosed
  area, anything) triggers `_reposition` instead — submerge onto the nearest
  free tile and resurface there to try again from a new position (see
  `retarget` step 2 above). `find_path_to_nearest_structure`/`find_path_to_
  nearest_non_base_building` (`game/map/pathfinder.py`) still carry their
  `ignore_walls` parameter (harmless, unused by the Digger now — see that
  doc's pathfinder section) since other callers may still want it; the new
  `find_path_to_nearest_boost_or_economic_building` was added WITHOUT one,
  since nothing calls it with walls ignored either.
- **`Enemy._scene` — the transient seam** (parallel to `_tilemap`,
  underscore-prefixed and non-authoritative per E-11). A `GameObject` is never
  handed the scene (`Scene.update` calls `on_spawn()` with no arguments) and a
  `Component` cannot reach it either, which is why `CorpseFade._scene` and
  `Kidnap._scene` are both wired externally by their one transition site. The
  Digger needs the scene for two things `_tilemap` cannot answer — who else is
  a live Digger, and where to put the dirt pile — so it is cached ONCE on the
  whole `Enemy` hierarchy rather than threaded through four call signatures.
  **`Spawner._attach_scene(enemy, scene)` sets it at BOTH of the spawner's
  construction sites** (the wave pop in `update` and `_spawn_child`),
  immediately before `scene.spawn`, so it is already there when `on_spawn()`
  takes the first claim. A named helper rather than two inline assignments so
  the sites cannot drift — and because NE-3's Drummer needs the identical seam
  and must share it, not clone it. A hand-built headless
  enemy leaves it `None`, which every reader treats as "no scene, no rivals" —
  single-Digger behaviour, never a crash.

### The dirt pile (`dirt_pile.py`)
`DirtPile`/`DirtPileFade`/`spawn_dirt_pile` — the exact shape of `corpse.py`,
in **its own module** rather than as a sibling there: a `Corpse` is *the dead
enemy's own sprite playing its own death row* and is constructed FROM an enemy;
a dirt pile is a fixed world decal with one shared slot (`vfx_dirt_pile`) and no
relationship to the unit that made it. Same pattern, different subject, and the
design pillar is small single-purpose files. Tagged **`"dirt_pile"`, never
`"enemy"`**, with no `alive`/Health/PathAgent, so it is invisible to every
gameplay query exactly as a `Corpse` is. Its lifetime is **the dig duration**
(passed in by `BurrowAgent`, not read from a manifest track), so the mound is on
the board for precisely as long as the Digger is under it — and the fade clock
takes the same speed-scaled `sim_dt`, so that holds at 1×/1.5×/2×. **Real art
since `tools/gen_dirt_pile_sheet.py`** — a one-shot generator that crops
`base_hole` (the map's own "hole" — the thing the whole game protects) to its
opaque content via `Surface.get_bounding_rect`, scales it up, and centres it on
a fresh 64×64 `vfx`-category canvas; re-runnable and idempotent, the
`tools/gen_wall_sheets.py` shape applied to a DERIVED sprite instead of a drawn
one. Repaint `data/sprites/imported/vfx_dirt_pile.png` freely — the script is
only how it was seeded.

### Digger balancing (`EnemyTypes.Digger`)
A NORMAL era-shaped type — its own `eras[]` rows through the base
`STAT_SUBTREE` resolver, `footprint`/`sprite_scale` among them (1 and 1.0 in
every row; they were flat at the root until the per-era-footprint change).
Five things are specific to it, all flagged as STARTING VALUES in their schema
descriptions:
- **`dig_speed`** (flat, tiles/sec) — burrowed AND overground speed.
- **`dig_range_tiles`** (flat, default 3, MANHATTAN not Chebyshev) — double
  duty since Pass 5: the overground submerge-trigger distance to a
  currently-claimed far target, AND the underground local-scan radius every
  decision re-runs (`retarget`/`_arrived_in_range`) — the Digger always
  prefers the FARTHEST unclaimed candidate within this radius over a closer
  one. Raising it makes the Digger both harder to stop (untargetable for
  longer, since duration scales with actual dig distance) and able to reach
  farther without walking.
- **`min_target_distance_tiles`** (flat, default 3, Chebyshev) — unrelated to
  `dig_range_tiles`'s Manhattan scan: this is `_start_walk`'s own preference
  for which distant structure/boost/economy building to WALK toward, once
  nothing is in local range at all. Falls back to the plain nearest when
  nothing on the board clears it.
- **`emerge_cooldown`** (flat, seconds, default 2.5) — the minimum time it
  stands on the surface after ANY dig (a strike, a no-strike dig, or a
  reposition alike) before its next move — see the `BurrowAgent` bullet
  above. It ALSO paces the periodic re-check while stood down with nothing
  claimed. `0` restores the pre-cooldown behaviour exactly (the very next
  tick decides immediately).
- **`stats.dmg` per era IS the eruption hit**, not a per-swing melee value —
  `data/balancing/enemies.json` currently ships 900/9400/9000/9700/9500
  against `hp` 900/200/300/400/550; retune freely.
  `attack_speed`/`attack_range_tiles` are decorative for this type (it never
  uses the cooldown-gated melee path at all), and `stats.move_speed` is inert.
- Counts start at `start_round: 35` (era 3) and trickle: 1 at round 35, +1 per
  5 rounds. `_digger_group` is called **LAST** in `_compose`, after
  `_commander_group` — the same newest-last rng rule the Formation and the
  Commander follow — and mixed into the shuffled body, never queue-leading.
- **Diggers never spawn on a boss round**, the same deliberate rule (and the
  same `$defs/spawn_counts` reason) the Formation section spells out: adding a
  `digger` key to `Boss.round_counts` would force one into all 14 shared
  death-spawn rows. One `+ self._digger_group(...)` into `_boss_round`'s `rest`
  if it is ever wanted. Pinned by
  `test_enemies.TestDigger.test_no_diggers_on_a_boss_round`.

## Drummer (NE-3) — the FIRST buff/aura mechanism in the game
A support unit that marches at the hole like a walker (`hunts: "base"`, so the
generic `Enemy.on_spawn` takes the original byte-identical branch) and hits for
almost nothing. Everything it does is the aura. **Read this before adding any
status effect, buff, debuff or aura to anything** — the per-source model below
is the pattern, and a second one would be a second state machine for the same
question.

- **The subclass is four class attrs plus ONE extra component.** `ETYPE
  "drummer"`, `REGISTRY_GROUP "Drummer"`, `DEFAULT_SLOT "drummer_stage_1"`,
  `STAT_SUBTREE ("Drummer",)`. No `__init__`, no `on_spawn`, no
  `_resolve_stats` (the Commander's D8 rule holds: the base `STAT_SUBTREE`
  resolver reads its own `EnemyTypes.Drummer.eras` rows; the Boss's is still
  the ONE override in the module), no `_resolve_era`, no `EXTRA_TAGS`, default
  14×2 HP bar. `sprite_scale` 1.15 is the "slightly taller" cosmetic ask and is
  pure data.
- **`Enemy.extra_components(block)` is the seam for "this type needs a
  mechanism nothing else has"** — a classmethod beside `resolve_fit` /
  `resolve_phase_row` / `endgame_factors`, returning components appended after
  the shared list. Base returns `()`, so every stock type is byte-identical.
  It exists so a subclass never has to reimplement `__init__` (and re-derive
  the era/stat/fit resolution it would have to copy to do that) just to add
  one component. It is called BEFORE `GameObject.__init__` has run, so it must
  read only the resolved balancing block, never instance state.
- **Two components, split by capability — the `DeathSpawn`/`advance_second_
  phase` rule again.** `BuffState` is the passive LEDGER and owns every
  consequence; `DrummerAura` is the SCANNER and owns nothing.
  - **`BuffState` is on EVERY enemy type's component list** (second, right
    after `Health`), the `Kidnap` "declared field, usually inert" shape: empty
    it costs one dict-truthiness test per frame. It is second on purpose — a
    contribution that expires this frame is undone before `PathAgent` reads
    the buffed move speed and `EnemyCombat` reads the buffed damage/clock in
    the same frame. **Nothing pins any type's component list or count**
    (checked: `test_core.py`'s `len(go2.components)` is a generic GameObject,
    not an enemy), which is what made adding it to all seven types safe.
  - **`DrummerAura` lives only on Drummer instances** and does one thing per
    frame: scan `scene.by_tag("enemy")` and re-apply THIS drummer's
    contribution to everything within Chebyshev `support_range`. It keeps no
    list of who it has buffed, so it can die at any moment without leaking a
    buff. It never buffs itself. Cost is `drummers × enemies` tile tests per
    frame; drummers are 1–4 per wave by design.
- **The ledger is keyed by SOURCE, and that one decision buys both D6 and
  D7.** `BuffState.sources` maps the buffing `GameObject.id` (a uuid hex —
  which is what keeps the whole thing JSON-safe, E-11) to
  `{"hp": int, "dmg": float, "move_speed": float, "attack_speed": float,
  "decay": float}`. `hp` is an ABSOLUTE amount; the other three are FRACTIONS.
  - **Stacking is additive** (D7): `total(key)` sums every live contribution,
    so two Drummers are exactly twice one. Each grant is sized off
    `base_max_hp` (`Health.max_hp` minus every live hp grant), **never off the
    already-buffed max** — that is the difference between additive and
    compounding, and it is why `hp` is stored as an amount and not a fraction.
  - **Decay is per source and needs no "left the radius" event** (D7):
    `apply` re-pins that ONE source's `decay` to `BUFF_DECAY_SECONDS` (4.0, a
    module constant — the `CARRY_OFFSET_TILES` precedent, deliberately NOT a
    balancing leaf) every frame it is sustained. "Four seconds after leaving"
    is simply the fourth second after the last frame anything re-pinned it.
  - **The clock lives on `BuffState`, not on the aura** — load-bearing: a
    Drummer that DIES stops re-pinning, and its buff then fades on the same 4s
    clock with no component of its own left to run. Put the timer on the
    source and a killed Drummer's buff would either hang forever or vanish
    instantly.
  - **The same ledger carries DEBUFFS since BU-3 3.3** — see "Slows are
    `BuffState` too" below (D19). A slow is one NEGATIVE `move_speed`
    contribution keyed by a plain slot string instead of a `GameObject.id`,
    carrying its own explicit `decay` instead of `BUFF_DECAY_SECONDS`.
    Everything in this section applies to it unchanged, and nothing on the
    aura path had to learn about it — which is exactly why D19 chose to widen
    this ledger rather than build a parallel status-effect mechanism.
- **`_grant_hp(delta)` is the ONE place `Health` is touched**, both
  directions, which is what makes grant and un-grant provably symmetric (D6):
  a positive delta raises `max_hp` AND `hp` by the same amount (a real heal,
  not headroom); a negative one shrinks `max_hp` and clamps `hp` **only if it
  is now above the new max** (a unit already damaged below it keeps what it
  has). Re-applying an UNCHANGED amount touches `Health` not at all — that is
  what stops a parked Drummer from healing a wounded unit to full every frame.
- **The other three stats are READ-SITE multipliers, never written into the
  component field.** `buff_total(owner, key)` is the guarded front door (0.0
  for a building/stub/no-contributions owner). Three sites, one per stat, and
  each is the *only* place its stat is resolved:
  - `EnemyCombat.buffed_dmg` — read by `Enemy.dmg` (base hits + the combat
    sweep's telemetry) AND by `_effective_dmg` (blocking-building and wall
    attacks, which layer the tile-condition bonus **on top** of it, so the two
    compound). One property, so an aura can never reach one and miss the other.
  - `EnemyCombat.buffed_attack_speed` — the leaf is an INTERVAL, so a bonus
    **divides**: `attack_speed / (1 + bonus)`. +10% means 10% more swings, not
    10% slower. Both `self.cooldown = …` resets read it.
  - `PathAgent._condition_speed()` — scales `_real_speed` **before** the
    terrain penalty and the `min_speed_fraction` floor. This has to be the
    site: writing a bonus into `Movement.speed` directly is overwritten by
    this method on the very next walking frame.
- **`Enemy._scene` — the scene transient, set by `Spawner._attach_scene`.**
  `Scene` hands objects no reference to itself (`on_spawn()` takes no
  argument), so a component that must QUERY the world needs the host that
  builds the enemy to give it one. An underscore transient exactly like
  `PathAgent._tilemap` / `Kidnap._scene` (legal past the E-11 setattr seal),
  set at BOTH spawner construction sites — the wave pop and `_spawn_child`, so
  a death-spawn or second-phase child is as world-aware as a queued one. An
  enemy built outside the spawner simply has no `_scene`, and every consumer
  treats that as inert. **This is also the seam NE-2's Digger claim wants** —
  do not invent a second one.
- **Composition**: `_drummer_group` is called LAST in `_compose`, after
  `_commander_group` — the same rng rule every newer group follows (an earlier
  call site moves every deterministic wave fixture). Body-mixed, never
  queue-leading: a support unit ahead of the units it supports buffs nothing.
  Zero before round 25, so rounds 0–24 are byte-identical to BR-5. **Drummers
  never spawn on a boss round**, exactly like Formations and for exactly the
  same reason (`Boss.round_counts` is `$defs/spawn_counts`, shared with every
  `death_spawn.spawns` row); it is a one-line `+ self._drummer_group(...)`
  into `_boss_round`'s `rest` if that is ever wanted.
- **OPEN ITEM, flagged not resolved — `attack_speed_increase` and
  `support_range_increase`.** The design's prose says the Drummer buffs
  "dmg/hp/movement speed"; its own variable list also names those two. NE-3
  implemented the more specific list, so the data shape is future-proof:
  `attack_speed_increase` IS wired and live (0.10), and
  **`support_range_increase` is a deliberately INERT leaf at 0 — nothing reads
  it and there is no era-growth mechanic behind it.** Do not "finish" either
  one on your own initiative; the scope question is the user's to answer.
  Pinned by `test_enemies.TestDrummer.test_support_range_increase_is_inert_
  as_shipped`, which goes red the moment someone wires it up.

## Slows are `BuffState` too (BossUpgradeTimelinePLAN BU-3 3.3, D19)
The game's first DEBUFF rides the Drummer's own ledger rather than a parallel
mechanism — read the Drummer section above first; everything it says about
per-source keying, additive stacking and per-source decay applies unchanged.
- **`apply_slow(owner, source, slow_fraction, duration)`** (`components.py`,
  beside `buff_total`) is THE way anything slows an enemy. It writes a
  NEGATIVE `move_speed` contribution through `BuffState.apply` — a slow IS a
  buff with the sign flipped, which is why no new read site was needed:
  `PathAgent._condition_speed` was already the one place `move_speed` is
  resolved. `slow_fraction` is taken as a MAGNITUDE and negated inside, so no
  caller can accidentally speed an enemy up through this door; `duration`
  re-pins that source's decay clock on every application, the same "the Nth
  second after the last frame anything re-pinned it" rule the aura uses.
  Returns False (never raises) for an owner with no `BuffState`.
- **`source` is a plain SLOT STRING here, not a `GameObject.id`** —
  `"boss_upgrade:mortar_slow"` / `"boss_upgrade:stormpriest_slow"`, the two
  module constants `game/enemies/combat.py` and `game/core/lightning.py` own.
  **One key per UPGRADE, never per firing building**: N mortars shelling one
  enemy must read as one slow, or a bombardment stacks into a full stop. The
  upgrade's own repeat PICKS still stack additively (D4), inside the fraction
  the caller computes.
- **`buff_signs(owner, key)` is the READ side the HUD indicators gate on**, and
  it is `buff_total`'s deliberate opposite: it returns `(has_positive,
  has_negative)` by walking the individual `BuffState.sources` contributions,
  **never by taking the sign of their sum**. A netted total can only ever carry
  ONE sign, so an enemy inside a Drummer's aura AND under a mortar slow would
  show only whichever effect won the subtraction (and nothing at all on an
  exact cancel) — but that is a real, legible state and the gold buff arrow and
  the red debuff arrow are meant to show TOGETHER for it (D20 follow-up,
  `game/ui/CLAUDE.md`). `buff_total` stays THE read path for a buffed STAT's
  value; `buff_signs` is only for "is something pushing this stat up / down".
  Same `(False, False)`/no-`BuffState` guard, keyed on the STAT and never on
  who applied it — anything that ever slows an enemy lights the indicator for
  free.
- **`MIN_SPEED_MULTIPLIER` (0.1) is the floor on that multiplier**, and it is
  load-bearing for exactly the reason BP-1's own terrain floor is: a unit at
  speed 0 never advances `Movement.index`, which is the only thing that
  refreshes `_current_condition`, so it LATCHES at 0 forever. Additive
  stacking can drive the sum past -1.0; the clamp in `_condition_speed` is
  what makes that a very slow unit rather than a frozen one. Provably a no-op
  for every positive bonus and for any negative sum above -0.9.
- **The mortar's hook (#3 `mortar_slow`) lives in `combat.py`.**
  `resolve_combat` grew the standard BU-3 optional trailing pair
  (`run_state=None, boss_upgrades_balance=None` — see
  `game/core/boss_upgrades.py`'s threading-pattern section) and threads it to
  `_fire_splash` ONLY. `_mortar_slow_spec` resolves
  `(source, fraction, duration)` at FIRE time — that is where the FIRING
  building is in hand, and D16's snapshot check
  (`id(defender) in RunState.mortar_slow_snapshot_ids`) is about the firing
  building, not the shell — and stashes it on the shell's `ProjectileArc._slow`
  (the `_on_damage`/`_assets` transient pattern, E-11). `_impact` applies it to
  every enemy the splash damages, at the same site the damage lands. A shell
  already in flight when the upgrade is picked carries `None`. This package
  still imports `game.core` LAZILY, inside `_mortar_slow_spec`'s body.
- **`game/core` does NOT import this** for its own slow (#7
  `stormpriest_slow`): `apply_slow` reaches `game/core/lightning.py` through a
  host-installed `set_slow_hook` seam, because `game/core` imports nothing
  from `game/enemies` and that rule is not relaxed for a status effect. See
  `game/core/CLAUDE.md`.

## Two more boss-upgrade hooks live here (BU-3 3.4 + 3.5)
The threading contract is stated ONCE, in `game/core/boss_upgrades.py`'s
module docstring ("THE BU-3 HOOK THREADING PATTERN") — read it there. Both
hooks below use its standard `hook_stacks` reader and its lazy
`game.core.boss_upgrades` import; what is worth writing down here is the two
places this package's shape forced a variation.
- **#8 `thorns` (`components.py`) is the ONE BU-3 hook that CANNOT take the
  pair as a parameter, so it takes it as a SEAM.** Its hook site is
  `EnemyCombat.update()`, which `Scene.update`'s generic component sweep calls
  with `dt` alone — the identical constraint that already forced
  `set_damage_hook`/`set_wall_damage_hook` into this module, for the identical
  reason (that sweep runs BEFORE `resolve_combat`, so `resolve_combat`'s own
  parameters physically cannot reach it). Hence a module-level
  `_boss_upgrade_pair` + **`set_boss_upgrade_pair(run_state,
  boss_upgrades_balance)`**, installed once per run by `game/main.py`'s
  `build_gameplay()` (spelled off the Session, like every other hook site) and
  CLEARED by `teardown_gameplay()` so a dead run's ledger can never leak into
  the next one. Unset by default ⇒ every headless test is byte-identical.
  `_apply_thorns(attacker, dmg)` is called from BOTH damage branches (D13:
  buildings AND edge walls), at the site each branch already spends the
  victim's HP, off the SAME `dmg` — a wall carries no `Health`, so its reflect
  is measured from the blow, not from the wall's remaining HP. Reflected
  damage lands on the ATTACKER's own `Health`; `int()` truncation, no floor.
- **#11 `condition_dmg_bonus` (`combat.py`) is resolved at IMPACT, not at
  fire time** — the opposite of #3 `mortar_slow` above, and for a stated
  reason: #3 asks about the FIRING building (D16's snapshot), while #11 asks
  about the TARGET enemy's own tile (D15: any non-Grass condition), which
  changes as the enemy walks and differs per enemy inside one splash. So the
  pair rides UNRESOLVED on `ProjectileHoming`/`ProjectileArc` transients
  (the `_slow`/`_on_damage` shape) and `_condition_bonus_dmg` runs at each
  damage site. **"Exactly once per hit" is provable by the call graph, not by
  a guard**: this module finalises damage at exactly three DISJOINT sites —
  `ProjectileHoming._impact`, `ProjectileArc._impact` (once per enemy in the
  radius) and `_update_beam` — and `_fire`/`_fire_splash` apply no damage at
  all, they only load a projectile. There is no shared downstream applier for
  the multiplier to run through twice. Each site multiplies once, immediately
  before its single `Health.damage`, and reuses the returned value for the
  `RoundStats` credit and the `on_damage` telemetry so all three report the
  number actually dealt. `on_non_grass_condition(enemy)` (`components.py`,
  beside `_condition_mods`) is the ONE definition of "is this enemy on
  non-Grass", reading `PathAgent._current_condition` — the same value
  `_condition_speed`/`_effective_dmg` already treat as the enemy's current
  tile. Lightning is a separate damage source with its own hook (#7) and is
  deliberately NOT covered.

## Prey hunting + per-type terrain weights (Chunk 3 + Chunk 4)
Two independent per-type balancing knobs, both threaded through `PathAgent`
transients set once by `Enemy.__init__` (E-11: a dict/str resolved from
balancing is not itself component-declared JSON state unless it needs to
survive save/load — `hunt` IS declared since it's a plain string the editor's
inspector can show; `_cond_weights` is a transient because a dict is not
JSON-safe).

- **`EnemyTypes.<type>.hunts`** (required enum `"base" | "economic" |
  "defence" | "structure" | "any_non_base"`) drives `PathAgent.hunt` (declared
  field, default `"base"`). **A hunt is nothing but a PREDICATE over the
  occupant's `building_type`** fed through the one shared
  `_hunt()`/`_goal_tiles()` body in `game/map/pathfinder.py` — adding a
  category is a new module-level set + a new `find_path_to_nearest_*` wrapper +
  a `_HUNT_QUERIES` row + the schema enum, never new pathfinding machinery.
  The four category sets, all in `pathfinder.py`:
  - `_ECONOMY_BUILDING_TYPES` = `{economic, meditator, painter}`.
  - **`_ATTACK_BUILDING_TYPES` = `{defence, aoe_defence, storm_priest,
    sun_scorcher}` — NE-0 WIDENED `"defence"` from the single literal
    `building_type == "defence"`.** It is a deliberate, user-approved BALANCE
    change to an existing type, not a refactor: `SiegeCannon` already ships
    `hunts: "defence"`, so from NE-0 it also paths to mortars, Storm Priests
    and Sun Scorchers, starting at its unchanged `start_round: 14`.
  - **`_STRUCTURE_BUILDING_TYPES` = `{blocker, wall_builder, defence,
    aoe_defence, storm_priest, sun_scorcher}` — the NE-0 `"structure"`
    category**, i.e. every non-economy, non-boost, non-base building.
    Blockers/wall builders are the common case but it is deliberately not
    limited to them. Spelled out literally rather than derived from the attack
    set: the two answer different questions, so a future attack-capable
    building must be added to BOTH on purpose. Landed in NE-0 with **no
    consumer** — the Digger (NE-2) is the first type to carry it — so that a
    mistake in the predicate shows up against `SiegeCannon`'s existing test
    coverage first.
  - `"any_non_base"` stays `building_type != "base"` (no set — the boss's
    `_non_base_goals`).
  The roster partitions exactly: structure ∪ economy ∪ the three `boost_*` ∪
  `base` IS every `BUILDING_TYPE` the game ships, and attack ⊂ structure —
  asserted, not just documented, by `test_pathfinder.TestHuntCategories`,
  which runs each predicate against the WHOLE building-type roster so a new
  type no category claims is visible.
  `Enemy.on_spawn` is generic over the hunt string:
  - `"base"` (Standard, Formation) keeps the ORIGINAL walk-to-the-hole
    behaviour byte-for-byte — `find_path` with the `find_path_ignoring_walls`
    fallback, `repath_on_kill` never armed, `goal_is_base` stays at its
    default `True`. This is what keeps every pre-Chunk-4 fixture green.
  - Any other value runs the matching goal-set query
    (`game/map/pathfinder.py`'s `find_path_to_nearest_economic` /
    `_defence` / `_structure` / `_non_base_building`, dispatched through a module-level
    `_HUNT_QUERIES` dict in `components.py` — the ONE place the
    hunt-string → query mapping lives, imported by both `enemy.py` and
    `components.py`'s own `PathAgent._repath`, so the two can never
    disagree about what a given `hunt` means), with the SAME
    `find_path_ignoring_walls` fallback the Boss always used, arms
    `PathAgent.repath_on_kill = True`, and calls `pa.adopt_goal(path,
    tilemap)` — the one site deriving `goal_is_base`/`target_col`/
    `target_row` from the fresh path (10G, unchanged).
  - **`Boss.on_spawn` is DELETED** — `EnemyTypes.Boss.hunts ==
    "any_non_base"` is exactly the dispatch it used to hardcode, so once
    every type could carry its own hunt string there was nothing
    boss-specific left in it. `Boss` is now `_resolve_era` + `_resolve_stats`
    + `era` only. Fenced by `tools/tests/test_boss.py` (unchanged — the
    generic path reproduces its behaviour exactly).
  - Seeded values (NE-0 added no `hunts` value to any type, it only changed
    what `"defence"` MEANS and added a then-unused category; **NE-1's
    `Sniper` is the first NEW consumer of the widened `"defence"`; NE-2 is
    what armed `"structure"`, on the new `Digger`** — which does NOT route
    through the generic `Enemy.on_spawn` branch below, because it needs the
    claim exclusion; see the Digger section above):
    `Standard`/`Formation`/`Drummer` `"base"`, `Raider` `"economic"`,
    `SiegeCannon`/`Sniper` `"defence"`, `Boss`/`Commander` `"any_non_base"`,
    `Digger` `"structure"`.
- **`EnemyTypes.<type>.condition_path_weights`** (required `{forest, mountain,
  pond}`, same bounds as `map.json`'s `Pathfinding.content_weights`) is this
  type's OWN terrain path-cost profile, threaded as `PathAgent._cond_weights`
  (a transient dict, copied — never aliased — off the resolved balancing
  block) into EVERY `find_path*` call this package makes (`Enemy.on_spawn`,
  `PathAgent._repath`, `kidnap.py`'s `begin_kidnap`). **It DUPLICATES
  `map.json`'s `TileConditions.path_weights` and will not track future
  changes to it** — there is deliberately no nullable "inherit" sentinel,
  because `editor/panels/balancing.py` reads `prop.get("type")` and a
  type-less schema node crashes the balancing panel for the whole domain
  (the same reason `death_spawn.spawns` is an array, never a union — see
  Rules below). Seeded to the map's current values (forest 1 / mountain 2 /
  pond 9) for every type, so this ships **behaviourally neutral**: every
  enemy still costs exactly what it did before this profile seam existed.
  Retuning one type's `pond` weight (e.g. to make raiders swim) changes
  ONLY that type's routing.
  - `Tile.pathfinding_weight`/`TileMap.weight`/every `game/map/pathfinder.py`
    query take an optional trailing `cond_weights` (`None` = "use the map's
    own `TileConditions.path_weights`", today's behaviour byte-for-byte).
    The flow-field cache key gains a third component, `profile_key` — see
    `game/map/CLAUDE.md`'s perf section for the full mechanism and the
    "still shares one field" measurement.
- **`kidnap.py`'s `find_path_to_nearest_spawn` call takes the carrier's own
  profile too** (`pa._cond_weights`) — the carrier still routes home by its
  own terrain preferences even mid-carry.
- **Already generic, needed NO change (verified, not re-derived)**:
  `PathAgent.update`'s `goal_is_base`-false-on-arrival branch (re-paths
  instead of breaching, line ~137 of `components.py`), the dead-target watch
  (`repath_on_kill and not blocked and not _target_alive`, line ~149), and
  `begin_kidnap`'s clearing of `goal_is_base`/`target_col`/`target_row`/
  `repath_on_kill` (`kidnap.py`) — none of these read or care WHICH hunt
  produced the path they're watching, only whether one is active. Raiders
  are kidnappers (`kidnapping: true`), so a killed economy building the
  raider is still walking toward gets hoisted home via the SAME
  `begin_kidnap` transition every other kidnap uses — never re-pathed from,
  because the carrier is inert (`PathAgent.carrying`) the instant the
  transition fires.

## Round 0 — the tutorial's forced composition (TU-9)
`round_num == 0` is the tutorial's own scripted round (game/CLAUDE.md's "The
tutorial is round 0" section owns the full cross-package picture); this
package's only piece is `Spawner._compose`'s round-0 early branch, checked
**FIRST**: round 0 always composes exactly
`EnemyScaling.tutorial_round_enemy_count` `"standard"` walkers, ignoring every
other composition rule (raiders/siege/formation/boss all emit zero). It is a
**composition** rule, not a clock rule — since ES-1 the clock itself is safe at
round 0 by contract (D11): `era_math.era_of_round(0, …) == 0` and
`era_math.is_boss_round(0, …)` is False for EVERY configuration, so no caller
here re-derives the old `0 % round_interval == 0` / `(0 − 1) // n` guards. Real
enemy scaling begins at round 1 unshifted — composing round 0 then round 1
on one `Spawner` yields byte-identical output to composing round 1 fresh
(pinned by `test_enemies.py`'s `TestSpawnComposition` round-zero tests).

## Formation (ER-4)
The marching column, and **the one type whose body actually GROWS**:
`footprint` is `2, 2, 3, 3, 4` across eras 0–4 (per-era for every type now —
D10 above). It shipped a flat `1` for the whole of ER-4 despite this section,
its schema description and its own docstring all calling it 2×2; the per-era
change is what finally made the data agree with the design.

**It adds no mechanism** — it is the first consumer of
ER-1 (per-slot frame size), ER-2 (footprint clearance pathing) and ER-3
(`death_spawn`), all three driven purely from `data/balancing/enemies.json`.
- **A 3×3/4×4 body leans much harder on two existing behaviours**, neither of
  which changed. `_pick_spawn_tile` only spawns it where its whole N×N block
  is spawn zone and falls back to an UNFILTERED pick when no tile qualifies —
  on a map with a thin spawn band an era-4 Formation will take that fallback,
  which is the designed "never drop an enemy from a wave" outcome, not a bug.
  And its art is a 64×32 per-slot frame auto-fit to `footprint*tile_w` and
  never upscaled, so a 4×4 draws at its sheet size until real art lands.
- **The subclass is four class attrs, nothing else.** No `__init__`, no
  `on_spawn`, no `_resolve_stats`, no `EXTRA_TAGS`, no component wiring, no
  break state machine.
- **The `_resolve_stats` OVERRIDE TRAP IS GONE (ES-2).** It used to be
  mandatory: the base `Enemy._resolve_stats` read
  `balance["EnemyTypes"]["Standard"]` **literally**, so an un-overridden
  subclass silently shipped walker stats — a bug with no symptom but wrong
  numbers. The base implementation is now **`STAT_SUBTREE`-driven** like every
  other lookup, and Raider/SiegeCannon/Formation carry **no override at all**
  (only the Boss still does, for its own `stats[]` table). The regression test
  (`test_enemies.TestFormation.test_stats_come_from_the_formation_block_not_standard`)
  stays — it now proves the GENERIC path resolves the right block.
- **It does NOT override `_resolve_era`**: it is not era-indexed, so it inherits
  row 0 and ships a **single-row** `death_spawn.spawns` array. The clamp
  (`spawns[min(max(era,0), len-1)]`) does the rest.
- **D4 — there is no "break" state; breaking formation IS dying.**
  `at_hp_fraction: 0.5` makes `Enemy.alive` False at half HP, and from there the
  existing ER-3 pipeline runs untouched (`resolve_combat` → `on_enemy_death` →
  `Session` stash → `Spawner.spawn_death_swarm`). The children are regulars at
  `spawn_hp_fraction` (0.8) of their OWN max HP. XP, kill count and splatter all
  fire exactly as for any other death, because it *is* one.
- **Composition: fractional accretion, body-mixed.**
  `_formation_group` emits `era_math.count_at_round` over the Formation's own
  era row from `start_round` — the era row's `count_per_round` is **⅓**, which
  is exactly the old `// rounds_per_formation` accretion (D3′ is why
  `count_start` may be fractional: `2.666666666666667` in era 2). Mixed into
  the shuffled body —
  **never `siege_front`**, because a 2×2 at the head of the queue would wall the
  choke point before anything else arrived. It is called **LAST** among the
  composition groups so every earlier group's rng draw sequence stays
  byte-identical (the deterministic-wave fixtures depend on this).
- **Formations never spawn on a boss round — DELIBERATE, do not "fix" it.**
  `_boss_round` composes from `Boss.round_counts`, a `$defs/spawn_counts` table
  **shared with every `death_spawn.spawns` row**. Adding a `"formation"` key to
  that `$def` would force a meaningless formation count into every death-spawn
  row. **AMENDED (BR-1/D3, user decision): that argument no longer holds
  absolutely** — `commander` WAS added to the shared `$def` (all 14 rows carry
  it, at 0), deliberately overriding this note, because the boss's swarm and
  its round table both wanted the same count vocabulary. The cost was paid and
  is visible in the file; it is a judgement call per key, not a ban. It still
  stands for `formation` specifically: nothing wants a formation count in a
  death-spawn row, and D7 keeps BOSS-ONLY keys (the BR-5 staging rows) out of
  this `$def` entirely. (It also used to fail the prototype-parity gate — that gate is deleted
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

## Kidnapping (`kidnap.py`, Art/enemies)
A kidnap-capable enemy's killing blow on a building is **terminal for the
CARRIER, ordinary for the BUILDING**: the carrier stops being a combatant (no
death VFX, no death animation, no drained health bar) and hoists a *copy* of the
building's sprite home, while the building itself is left standing on its tile
as a plain dead building — **it revives at payday exactly like any other kill**
(user decision; `game/core/CLAUDE.md`). It used to be terminal for both, with
the tile freed for good. Per-type toggle: `EnemyTypes.<type>.kidnapping` (bool,
required, `/add-balancing-value` shape) — **Standard `true`, Raider `true`,
SiegeCannon `false`, Formation `false`, Boss `false`** (Boss keeps its 10G
building-grinding rampage; Formation keeps marching). **A kidnapper walking
home HOLDS THE ROUND OPEN** — confirmed user decision; see the wave-clear
condition below.

- **The retag trick, reused wholesale from `Corpse`'s precedent.** On the
  transition (`begin_kidnap`) the owner's tags flip `("enemy", …) ->
  ("kidnapper",)`. `GameObject.tags` sits in `_ENGINE_ATTRS`
  (`engine/core/gameobject.py`), so the write is legal past the E-11 seal. One
  move makes the carrier invisible to **every** gameplay query that reads
  `by_tag("enemy")` at once — the combat sweep's target list, the beam's
  sticky target, `_resolve_base_arrivals`, `game/core/lightning.py`, the
  overhead HP bars (`game/ui/effects.py submit_enemy_hp_bars`) and the heatmap
  traffic tracker — with **no per-site "if kidnapping" filter anywhere**.
  Consequence to accept: a *damaged* kidnapper shows no HP bar at all (moot in
  practice — its `Health` is never touched, since combat can no longer see it);
  it is also never counted by the heatmap tracker.
- **`Kidnap` (`components.py`) is a component like any other** — `enabled`
  (resolved at construction from balancing), `pending` (armed by
  `EnemyCombat.update()`'s building branch the instant its killing blow leaves
  the target not-alive — guard-safe, **never touches the scene**), `active`
  (carrying), `frozen` (pin the sprite clock at 0 when the sheet has no
  `kidnap` row — `SpriteAnimator.update` always advances its own clock
  regardless, so `Kidnap.update`'s per-frame re-pin is what actually locks the
  frame), plus the carried building's own `slot_key`/`fit_tiles`/`scale`/
  `column` — `column` (fix-kidnap-carried-building-colour) is the player's
  master-sheet swatch pick (MasterSheetColumnsPLAN B1), carried along on the
  SAME `-1` "no driver" sentinel `SpriteAnimator.column` uses, so a
  colour-capable building's carried sprite keeps the colour it was placed in
  rather than silently reverting to the manifest's default column. It
  goes **LAST** in `Enemy.__init__`'s component list — after `Movement` (sees
  arrival the same frame) and `SpriteAnimator` (its clock re-pin wins).
  `Kidnap.render_items` yields ONE extra `RenderItem` for the carried sprite,
  `column=` included; `Scene.render_items` picks it up generically alongside
  the carrier's own `SpriteAnimator` item — no new GameObject, no engine change.
- **`begin_kidnap(scene, tilemap, enemy, building)` (`kidnap.py`) is the ONE
  transition site**, called from the combat sweep's kidnap pass
  (`combat.py::_resolve_kidnaps`, placed AFTER the defender loop and BEFORE
  `_resolve_base_arrivals`). It COPIES the victim's `SpriteAnimator` fields
  onto `Kidnap` and touches the building in no other way. It used to also blank
  the building's own `slot_key` to vanish it the same frame — that was both
  redundant (the victim is dead by definition here, and `BuildingSprite` draws
  nothing while its owner is dead) and, once the building started reviving,
  actively wrong: the blank key survives `rebuild()` and leaves the revived
  building invisible forever. `pa.goal_is_base = False` here is
  **load-bearing**: a stale `True` would fire a phantom base breach the moment
  the carrier reaches the spawn tile. It also clears `pa._target`/`pa._wall_target`/`pa.target_col`/
  `pa.target_row` and `pa.repath_on_kill`, loads
  `find_path_to_nearest_spawn(tilemap, col, row, footprint)` into `Movement`
  at `mv.speed = pa._real_speed` (the BP-4 no-rewind `index = 1 if len >= 2
  else 0` rule, same as `PathAgent._repath`), and retags LAST. No path (no
  spawn tile / unreachable) ⇒ despawn on the spot.
- **`PathAgent.carrying`** — a carrier is inert: `update()` returns
  immediately at the top when it is set. No blocker scan, no wall scan, no
  re-path, no condition-speed write; `Movement` (a separate component) keeps
  driving the waypoints `begin_kidnap` loaded, on the speed it set.
- **The carried-sprite offset is pure iso arithmetic, no engine change.**
  `world_to_screen` is `ix = (wx-wy)*half_w`, `iy = (wx+wy)*half_h`, and
  `depth_key = (layer, wx+wy, wy)` (`engine/coords/system.py`), so a world
  offset of `(-d, +d)` (`CARRY_OFFSET_TILES = 0.25`, a cosmetic module
  constant — the `AOE_TRAVEL_TIME`/`CRATER_LIFE` precedent, not balancing):
  moves the sprite exactly `2·d·half_w` px LEFT on screen with zero vertical
  change; leaves the depth (`wx+wy`) identical and raises `wy`, so the carried
  building sorts AFTER the carrier and draws IN FRONT of it. `d = 0.25` → 16px
  left at zoom 1.
- **The host seam (`game/main.py`) is the `spawn_corpse` pattern again**:
  `resolve_combat(..., on_kidnap=…)` fires `session.on_kidnap` (XP + kill count
  only — no gore, no death-spawn stash, nothing done to the victim) then, since
  `game/enemies` must not import `engine.assets`, asks
  `assets.animation_total_ms(slot, KIDNAP_ANIM)` and hands the answer to
  `set_kidnap_pose` — a sheet with a `kidnap` row plays it; one without freezes
  on idle frame 0.
- **Wave-clear**: `Session.post_sim` now also requires `not
  scene.by_tag("kidnapper")` and `not scene.queued_by_tag("kidnapper")` — see
  `game/core/CLAUDE.md`. Every "clear the field" cheat/quick-skip path
  (`quick_skip_combat`, `cheat_skip_round`, `cheat_goto_round`, `_wipe_round`)
  despawns `by_tag("kidnapper")` alongside `by_tag("enemy")`, or the round
  could never end under an abandoned carrier.
- **Consequences of the victim staying on the board**, all of them "same as any
  other death" by design: a kidnapped booster DOES run payday's slot-7
  flat-boost rollback, a kidnapped `wall_builder`'s perimeter comes down at
  slot 8 and back at slot 10, the tile stays BUILT (not re-placeable) for the
  rest of the round, and the building pays its one-time `xp_from_buildings` XP
  from `_award_building_deaths` — which `Session.post_sim` now also runs on the
  round-ending frame, so a wave ended early by a base breach can no longer
  swallow it (`game/core/CLAUDE.md`).

## Telemetry seams in `components.py` (debug-mode-telemetry)
Two module-level hooks, **`None` by default and installed by the HOST only at
debug level >= 2** (`game/main.py` sets them around `scene.update()` and clears
them straight after, so nothing can leak into the next caller). Both are
OBSERVATION only — with either unset, `EnemyCombat.update()` is byte-identical
to before they existed (one `is not None` check). They exist because
`EnemyCombat.update(dt)` runs inside `Scene.update`'s generic component sweep,
which the host calls BEFORE `resolve_combat` — so `resolve_combat`'s own
`on_damage=` parameter physically cannot reach these two call sites. The
precedent is `game/ui/widgets.py`'s `set_skin_hit_test`.
- **`set_damage_hook(fn)`** — the enemy-attacks-a-blocking-building site,
  fired at exactly the `RoundStats` credit line, with the SAME
  `(attacker_kind, target_kind, dmg, target_hp_after)` shape
  `resolve_combat(on_damage=…)` uses.
- **`set_wall_damage_hook(fn)`** — the edge-WALL attack branch of the same
  method (10E). It needs its own hook, not the one above: a wall is a
  map-owned `WallEdge` with no `Health`, no `RoundStats` and no
  `building_type`, and it spans an EDGE rather than sitting on a tile — so
  the shape is `(attacker_kind, (c1, r1, c2, r2), dmg, hp_after, broke)`,
  with `hp_after` read back through the public `TileMap.get_wall_between`
  (a broken edge is deleted, so it reports 0). Wall damage is credited to
  nothing and therefore appears in NO per-round telemetry column — it is
  event-stream-only, deliberately.

## Crowd spacing (feature) — Standard/Walker and Raider
When 2+ SAME-TYPE enemies genuinely share a tile (not just briefly crossing
paths), they ease into small evenly-spread positions instead of drawing
stacked on top of each other. **Grouping is strictly per-type**: a Raider and
a Standard sharing a tile never share a slot layout, even though both may be
crowding independently at once — each type reads its own
`data/balancing/enemies.json` `CrowdSpacing.<Type>` block (`Standard`/
`Raider` today), so a designer can tune (or cap) one type's crowding without
touching the other's. This is a REAL position offset — it is written into
the same `Transform.wx/wy` combat and range-gating read, a deliberate user
decision: `combat.py`'s range gate rounds to a tile so it is unaffected at
any offset under half a tile, but the Euclidean nearest-target tiebreak and
the mortar splash-radius check both read the CONTINUOUS position, so they
are measurably (if very slightly) affected by design, not by oversight.
- **Why a naive per-frame nudge doesn't work.** `engine/core/movement.py`'s
  `Movement.update()` reads `transform.wx/wy` as *this frame's* starting
  point and writes the stepped result back into the same field — it has no
  separate "true path position" input. Writing a crowd offset into
  `transform.wx/wy` directly would make next frame's `Movement.update()`
  treat last frame's offset as the real path position, permanently dragging
  the route off-centre and fighting the waypoint-arrival threshold (0.06
  tiles — smaller than a typical crowd offset).
- **`CrowdSpacing` (`game/enemies/crowd_spacing.py`) is declared state
  only, and carries NO per-type identity of its own** — `base_wx`/`base_wy`
  (the clean, un-offset path position; `-1.0` is the "not yet seeded"
  sentinel, the `PathAgent.target_col/_row` -1 precedent),
  `dwell_time`/`dwell_tile_col`/`dwell_tile_row` (how long this enemy has
  continuously held its current rounded tile), `offset_dx`/`offset_dy` (the
  current EASED visual offset). Every type carrying it uses the identical
  bare constructor; `_crowd_group_key(enemy)` derives which
  `CrowdSpacing.<Type>` balancing block an enemy reads from its OWN class —
  it reuses `Enemy.STAT_SUBTREE` (already the `EnemyTypes.<Type>` lookup
  path every type's stats resolve through) rather than a second, parallel
  type -> key table that could drift from it. The component carries **no
  `update()`** — the logic is two pure functions, the `DeathSpawn` state +
  `Enemy.advance_second_phase` + `Spawner._advance_second_phases` split
  applied here, because grouping every crowd-spacing enemy by tile is
  naturally ONE O(N) pass over the whole enemy list, not something each
  enemy's own `Component.update()` should redo independently (an O(N²) cost
  the `DrummerAura` "drummers × enemies" precedent can absorb at 1-4
  drummers but Standard/Walker, the single most common type running into
  the hundreds, cannot).
- **Standard/Walker and Raider carry the component; every other type
  doesn't.** `Enemy.extra_components` (the base classmethod) returns
  `(CrowdSpacing(),)` iff `cls.ETYPE in ("standard", "raider")`, else `()` —
  zero changes needed to any other subclass, since every other type's
  `ETYPE` differs (including `Tutorial`, whose own `ETYPE = "tutorial"`
  excludes it automatically even though it otherwise reuses the Walker's
  slots). This is also how "a type without the mechanism sharing the tile
  is ignored by the grouping" is satisfied for free: the grouping pass only
  ever looks for a `CrowdSpacing` component.
- **Host wiring (`game/main.py`), bracketing `world.scene.update(sim_dt)`**:
  `restore_crowd_positions(scene)` runs BEFORE it (undoes last frame's
  offset so `Movement` steps from the clean position), `apply_crowd_spacing
  (scene, sim_dt, enemies_balance["CrowdSpacing"])` runs AFTER it and BEFORE
  `resolve_combat` — so combat sees the final offset position for the frame,
  matching the "real offset" decision above. `enemies_balance["CrowdSpacing"]`
  is the WHOLE per-type dict (`{"Standard": {...}, "Raider": {...}}`), not one
  flat block. `apply_crowd_spacing` buckets every `CrowdSpacing`-bearing
  enemy by `(round(wx), round(wy), _crowd_group_key(enemy))` in one pass —
  the type key in the bucket is what keeps a Raider and a Standard on the
  same tile from ever landing in the same group — updates each one's dwell
  timer, and — for any group with 2+ enemies whose OWN `dwell_time` has
  crossed that TYPE's `dwell_threshold_seconds` — sorts them by `.id` (the
  `BuffState.sources` stable-key precedent) and assigns each a slot in
  `ANCHOR_TABLE[min(count, that type's own max_slots)]`. An enemy that
  hasn't dwelled long enough yet, or is alone in its group, targets `(0, 0)`
  — this is what filters "too far ahead to actually stay on 1 tile" with no
  separate check: a fast-passing enemy simply leaves the tile before its own
  dwell timer crosses the threshold.
- **`ANCHOR_TABLE`** (module constant, the `CARRY_OFFSET_TILES` cosmetic
  precedent — not balancing data, and SHARED across every type: only the
  magnitude/cap differ per type, not the layout shape) holds one row per
  occupant count (2-6), each a list of `(fx, fy)` direction fractions of
  a type's own `max_offset_tiles`, in world space chosen to read as clean
  horizontal/vertical spacing ON SCREEN under the iso projection. **No entry
  exceeds ±1.0 per axis — this is load-bearing**: every
  `CrowdSpacing.<Type>.max_offset_tiles` schema maximum (0.4) relies on it
  to guarantee an offset enemy can never round into a neighboring tile (a
  tile owns `wx`/`wy` in `[c-0.5, c+0.5)`). A `(max_slots + 1)`th occupant in
  one group (by sorted `.id`) reuses the table's last slot rather than
  growing past that type's cap — Standard ships `max_slots: 6`, Raider ships
  `max_slots: 5` (feature request: raiders crowd a little less densely than
  walkers before extras start stacking). `max_slots` is itself schema-bounded
  2-6, since `ANCHOR_TABLE` defines no layout wider than 6.
- **Overhead UI needs no changes.** `game/ui/effects.py`'s
  `submit_enemy_hp_bars`/`submit_buff_arrows` already read the enemy's live
  `transform.wx/wy` via `world_to_screen` every frame with no caching, so
  both follow the offset automatically.
- **Formation / multi-tile-footprint seam — documented, NOT implemented.**
  A `Formation` (or any footprint>1 body) is ONE GameObject occupying an
  N×N block, not several enemies (see the Formation section above; D5:
  footprints deliberately never enter `TileOccupancy` and are allowed to
  overlap). Extending crowd spacing to multi-tile bodies is a DIFFERENT
  problem — detecting overlapping *blocks*, not shared tiles, and offsetting
  a whole block's anchor point with the offset magnitude scaled by how much
  the blocks overlap (a fixed small offset that looks right on a 1-tile
  walker would be invisible on a 4×4 era-4 Formation, and naively scaling it
  to the body's own footprint risks the same neighboring-tile push the
  safety bound above prevents for 1-tile bodies). This wants its own design
  pass reusing `dwell_threshold_seconds`/`offset_ease_seconds`; flagged here
  so a future task starts from this note instead of rediscovering the
  constraint.

## Rules
- **`death_spawn` — the ONE death-spawn mechanic (ER-3, plan D4)**. Every
  `EnemyTypes/<type>` block carries a **required** `death_spawn` — **except the
  Boss, whose block is `second_phase` since BR-3** (same four keys plus
  `delayed_spawns`/`spawn_delay`; `Enemy.DEATH_SPAWN_KEY` is the one seam)
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
- **`REGISTRY_GROUP` now has a data-side twin, `data/balancing/enemies.json`'s
  `EnemyTypes/<Type>.registry_group` (fix-editor-preview-footprint)** —
  added so `editor/sprite_fit.py` can resolve a preview slot's real
  `(footprint, sprite_scale)` render fit without the editor importing this
  package (D5: `editor/` may never import `game/`). **This class constant
  was deliberately NOT refactored to read `data/` in that fix** — it stays
  the runtime source of truth here, and the two are pinned equal by
  `tools/tests/test_enemies.py`'s `TestRegistryGroupDrift` (walks every
  `Enemy` subclass, compares `REGISTRY_GROUP` against the `EnemyTypes` block
  its `STAT_SUBTREE` names). A future enemy type that lets the two drift
  turns that test red instead of silently breaking the editor's Formation-
  style preview for it — keep both in sync by hand until/unless a later
  phase collapses them into one source.
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
- **`PathAgent.footprint` (ER-2)** — an `int` field fed from the type's own
  `eras[era].footprint` (the Boss's `stats[era].footprint`) via the ONE
  `Enemy.resolve_fit` seam (G-7 — no code-side default anywhere). It is
  resolved ONCE at construction, so a unit keeps the size of the era it
  spawned in for its whole life. The unit occupies an N×N block
  whose **anchor is the MIN corner** (the body extends right and down); the whole
  rule set + the helper functions live in `game/map/CLAUDE.md` / `pathfinder.py`
  and are imported, never re-derived. Consequences in this package:
  - `Enemy.on_spawn` threads the footprint (and, since Chunk 3, the unit's own
    `PathAgent._cond_weights`) into `find_path` / `find_path_ignoring_walls`
    or its dispatched hunt query; `_repath` threads both into whichever query
    `_HUNT_QUERIES[self.hunt]` resolves to, and `adopt_goal` re-derives
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
  - **The combat sweep's range GATE measures to the footprint's NEAREST TILE,
    not its centre** (`_chebyshev`) — everything else (Euclidean acquisition
    tiebreak, mortar splash measurement, predictive lead) still measures from
    the block CENTRE (`anchor + (N−1)/2`, `_enemy_center_world` / `_fp_offset`).
    These are deliberately different: a centre-only range gate meant every tile
    OUTSIDE a 2×2 block sat at Chebyshev ≥ 1.5 from the centre, so a range-1
    defender standing adjacent to a boss could never target it — while the
    boss's own block-and-attack scan (`components.py` `_blocker_ahead`, a
    block-wide occupancy check) hit that same defender fine. `_chebyshev` now
    clamps the defender's tile to the block's span (`[anchor, anchor + 2·off]`
    per axis) before taking Chebyshev, so any tile touching the block is in
    range. Acquisition/splash/lead keep the centre — a defender should still
    prefer the nearest BODY when choosing between two candidates, and a shell
    should still land mid-block — so only the range gate changed. N=1 → offset
    0 → numerically identical to before for all four call sites.
    **PERF (load-bearing):** the offset is a per-enemy constant and is resolved
    ONCE PER ENEMY PER FRAME — `resolve_combat` builds `targets =
    [(enemy, off), …]` and passes `off` into `_chebyshev`. Never resolve it
    inside the (defender × enemy) pairwise loop: `get_component` is a linear
    isinstance scan, and doing it per pair cost ~9 ms of a 16.7 ms frame at 50
    defenders × 300 enemies. `_chebyshev` also SKIPS a zero offset rather than
    running the block-clamp with a zero span, keeping the N=1 expression in
    integer arithmetic (float ops there allocate per pair). Both are pinned by
    `game/PERF.md`.
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
- **Per-era stats resolved at CONSTRUCTION** (ES-2; the cumulative
  `tier_scaled_stats` sum is DELETED): the module-level `era_stats(type_block,
  era, position_in_era, endgame_factors)` runs
  `era_math.resolve_era_row` → `era_math.stats_at_round` and returns the
  constructor's `(hp, dmg, move_speed, attack_speed, attack_range_tiles)`
  tuple. Values from `data/balancing/enemies.json` (×10 combat scale baked in).
  **Who scales is now DATA, not code**: `Standard`/`SiegeCannon`/`Formation`
  ship rising era rows; **the Raider ships five IDENTICAL era rows with zero
  deltas** — "the raider deliberately does not scale" is preserved exactly, but
  as five flat rows a designer can retune, not as a Python exception (a glass
  cannon that only ever grows in COUNT, until someone decides otherwise).
  `Boss` still reads its own per-era `stats[]` table.
- **Sprite slots are registry-group driven with a random variant per spawn**
  (prototype `_STAGE_SLOT_PREFIX` + `_variant`): each class names its
  `data/slots.json` enemies group via `REGISTRY_GROUP`
  (`"Walker"`/`"Raider"`/`"Siege Cannon"`/`"Boss"`). That group's era subchildren
  are ordered; the enemy's `era` clamps to an era index and `variant_slot()` picks
  a random slot from that era via the spawner's injected `rng` — so a walker rolls
  between `enemy_stage_1_v1`/`_v2` on spawn, and dropping a new `_v3` slot into the
  era (editor) grows the pool with NO code change. The registry + rng are threaded
  `main.py → Spawner.begin_round → create_enemy`; absent a registry (headless
  stat/logic tests) each class falls back to its `DEFAULT_SLOT`. The Walker/Raider
  eras map to the prototype `*_stage_N` sheets (NOT the procedural `*_t2..t4`);
  Siege/Boss keep their era sheets.
- **`spawner.py` = the wave queue** (prototype `_begin_enemy_phase` /
  `_update_enemy_phase`): `begin_round` resolves the era + its
  `EnemyScaling.eras` row, then every per-type count comes from
  `_count_of` → `era_math.count_at_round` over that type's own era row (the
  four hardcoded per-type formulas are DELETED), with the ramp +
  `uniform(0.4, 1.6)` jitter; `update(dt, scene)` releases ONE BATCH per timer
  expiry into `scene.spawn`. The round LOOP that calls it + wave-clear detection is
  9F; an injectable `rng` keeps tests deterministic.
  - **ES-3/D4 — batch spawning.** `EnemyScaling.eras[era]` owns BOTH the pacing
    (`spawn_interval`) and `batch_size` (seeded 1..5 for eras 0-4), resolved once
    in `begin_round`. One timer expiry pops up to `batch_size` queue entries, each
    spawning exactly as a single pop did — one `create_enemy` + one `scene.spawn`,
    in queue order — so the rng draw sequence WITHIN a batch is unchanged and the
    boss simply leads its batch. Ramp-on: the next timer is the new queue head's
    delay. Ramp-off: ONE re-rolled jitter per BATCH (not per enemy). **The knob
    moves spawn EVENTS, never the round TOTAL**, and `batch_size == 1` is
    byte-identical to the pre-ES-3 one-per-expiry loop — that is the fence for the
    deterministic wave fixtures.
  - **10F composition**: raiders join from `Raider.start_round`, siege from
    `SiegeCannon.start_round` — both now through the SAME
    `era_math.count_at_round`, whose `count_per_round` reproduces the old
    `per_round` slope and `// rounds_per_cannon` accretion exactly (D3/D6;
    ES-2 swept every round from each type's `start_round` to 60 against the old
    expressions and found zero mismatches). Siege splits into a **lead
    group** (`int(queue_lead_count * mix_ratio)`) that HEADS the queue and a
    remainder mixed into the shuffled body — so cannons open the wave and then
    trickle. Queue = `siege_front + shuffle(standard + raiders + siege_mixed)`.
- **Raiders/siege now HUNT their prototype prey (Chunk 3/4 — this bullet used to
  say the opposite; it was true for 10F and is FALSE today).** Every
  `EnemyTypes/<type>` block carries a required `hunts` enum (`"base"` |
  `"economic"` | `"defence"` | `"any_non_base"`) — `Standard`/`Formation` are
  `"base"` (byte-identical to 10F: walk straight at the hole, attack whatever
  blocks en route), `Raider` is `"economic"` (Flute Player/Meditator/Painter),
  `SiegeCannon` is `"defence"`, `Boss` is `"any_non_base"` (unchanged from
  10G). See the "Prey hunting" section below for the full mechanism — the
  machinery 10G shipped boss-only (`PathAgent.goal_is_base` +
  `repath_on_kill`, `adopt_goal`) is now generic across every type.
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
    A defender's optional manifest `muzzle` anchor shifts only WHERE
    `_fire`/`_fire_splash` spawn the projectile visually;
    `ProjectileHoming.launch(target, shooter, scene, origin=...)` always
    computes flight time from the shooter's UNMODIFIED `transform.world_pos`,
    passed in as `origin` — never from the anchored spawn point. `origin=None`
    (every pre-ESV-1 caller) falls back to the projectile's own spawn
    position, today's exact expression. Damage-arrival timing is therefore
    provably invariant under any muzzle value.
  - **feat-projectile-anchored-flight — the homing MOVEMENT target is now the
    target's `impact` anchor too, basic defenders only (D4, still cosmetic).**
    Before this fix `ProjectileHoming.update` always homed toward
    `target.transform.world_pos`; the `impact` anchor existed only for the
    `projectile_hit` hit-VFX callback in `_impact`, so a shot never actually
    flew to where it visually landed. `update()` now resolves
    `game.anchors.projectile_point(self._assets, self._cs, target, "impact",
    self._lift_frac)` EVERY FRAME (the target moves) for the MOVEMENT target
    only — `self.timer` (and therefore `_impact()`'s firing frame) is
    unaffected, still decremented unconditionally every frame regardless of
    this point. `_assets`/`_cs`/`_lift_frac` are transient underscore refs
    (E-11), set by `_fire`. **Mortar shells (`ProjectileArc`, `_fire_splash`)
    are untouched** — they fly to a `_predict_lead`-computed ground point, not
    an entity, so no `impact` anchor applies (§2.4 of the brief).
  - **The muzzle spawn point's UNANCHORED fallback changed shape, not
    value.** `game.anchors.projectile_point(assets, cs, obj, name,
    lift_frac)` wraps `anchor_world_point` ("anchor wins outright" — an
    authored anchor is unaffected by any of this) and, only when absent,
    raises `obj`'s world position by `lift_frac` (`procedural.projectile.
    lift_frac`, threaded from `resolve_combat`'s existing `vfx_balance`
    argument — no new parameter) TILE HEIGHTS in SCREEN space, via the
    two-sample `screen_to_world` trick. That lift used to be added at DRAW
    time in `game/ui/effects.py submit_projectiles` (which double-counted
    against an authored anchor — the dot rendered ~19px above the muzzle
    handle even once an anchor existed); it now lives in the endpoint, so the
    draw is a pure projection and an authored anchor is never fought by a
    second, unrelated lift. **`_fire_splash` resolves its muzzle spawn
    through the SAME `projectile_point` — and it HAS to.** The "basic
    defenders only" scope covers the homing TARGET (the mortar keeps flying
    to `_predict_lead`'s ground point, no `impact` anchor), but the lift
    removal from `submit_projectiles` is shared by both draw paths, and
    `ProjectileArc.update` never moves the shell — only its timer ticks, so
    its spawn point IS its drawn point for the whole flight. Leaving
    `_fire_splash` on plain `anchor_world_point` therefore dropped the mortar
    shell ~19px the moment the draw lift went away. Routing it through
    `projectile_point` puts the lift back in the endpoint and restores the
    pre-change position (to within the float-vs-`int()` rounding step the
    move introduces everywhere). `lift_frac` reaches it through the same
    `resolve_combat` thread `_fire` uses.
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
- **ESV-5** — `resolve_combat(on_splash_impact=…)`: `ProjectileArc._impact`
  (the mortar shell's landing) fires the callback with `(gx, gy)` ALONGSIDE
  (never instead of) its unconditional cosmetic `Crater` spawn, so
  `game/ui`'s `splash_impact` trigger row can drain a ledger without this
  package importing `game/core`.
- **ESV-6** — two MORE optional callbacks, same pattern, both purely
  cosmetic (D4 — neither reads or writes anything the damage block above
  touched): `resolve_combat(on_defender_fire=…)` fires from BOTH `_fire`
  and `_fire_splash` with the ALREADY muzzle-anchored spawn point those
  functions compute for the projectile itself (never recomputed);
  `resolve_combat(on_projectile_hit=…)` fires from `ProjectileHoming._impact`
  ONLY (the homing path — the mortar keeps its own `on_splash_impact` event
  above) with the TARGET's `impact`-anchored point, whether or not the
  target is still alive that frame. Both default `None` (every pre-ESV-6
  caller, including every test in this package that doesn't pass them, is
  byte-identical) — `ProjectileHoming` also grows two transient underscore
  refs, `_assets`/`_cs` (E-11 — set by `_fire`, exactly like `_fire_splash`
  already stashes `arc._on_impact`), so `_impact` can resolve the anchor.

## Perf note that lives here
`Enemy.on_spawn`'s `find_path` (and its `find_path_ignoring_walls` fallback)
now walk the shared base flow field — a wave of hundreds of spawns pays ONE
Dijkstra per map-topology change, not one each, and `spawn_death_swarm`'s
burst rides it for free. Since ER-2 the field caches on
**`(ignore_walls, footprint)`**; since Chunk 3 it's
**`(ignore_walls, footprint, profile_key)`** (`profile_key` derived from the
caller's `cond_weights`, `None` for the map default) — so the invariant is one
Dijkstra per topology change **per (footprint, weight profile)**, still NEVER
one per enemy. At most a handful of distinct profiles ever exist (one per
enemy TYPE, never per instance), and every shipped
`EnemyTypes.<type>.condition_path_weights` is seeded identical to the map
default, so today every type still shares ONE field — see
`game/map/CLAUDE.md`'s perf section for the measurement. Passing a footprint
(and a weight profile) into `find_path` must therefore stay a plain argument;
do not add a per-enemy search.
`find_path_to_nearest_non_base_building`/`_economic`/`_defence` (the
goal-set/hunt-query variants, Chunk 4 generalised from boss-only) stay fresh
Dijkstras, as every goal-set variant does — but note BP-3 makes a hunting
unit re-path **once per kill** rather than once per wave, plus once when its
committed target dies to someone else. With the boss this is still a handful
of searches per round (there is one boss); Chunk 4 arms the SAME
`repath_on_kill` machinery for every Raider and every SiegeCannon in a wave
(both COMMON types), so this is the first time re-measuring under a real wave
matters — nothing observed regressed the affected-tier gate, but a future
phase adding more hunting types or higher counts should re-measure rather
than assume. Nothing in this package invalidates the field directly — all
mutations route through `TileMap`. Detail → `game/PERF.md`.

## Sounds (SD-5) — `sounds.py` is the ONE audio seam

Every enemy sound in the game goes through `game/enemies/sounds.py`
(`play_enemy_sound(enemy, kind)` + the pure `slot_for(enemy, kind)`); nothing
in this package touches pygame or names an audio file. `sounds.py` hands
SD-2's `engine.audio` two slot dicts and lets it resolve/pick/play.

**The four call sites — there are no others, and no type-name branch anywhere:**

| Slot | Site |
|---|---|
| `death`  | `combat.py`, the death sweep, BEFORE `scene.despawn(enemy)` |
| `attack` | `components.py`, `EnemyCombat.update` WALL branch, where the cooldown is re-armed |
| `attack` | `components.py`, `EnemyCombat.update` BUILDING branch (melee AND the NE-1 ranged stand-off — the same swing), same spot |
| `attack` | `components.py`, `BurrowAgent._strike` (the Digger eruption IS an attack) |
| `spawn`  | `spawner.py`, after `scene.spawn(enemy)` in the wave pop |

Consequences that are deliberate, not gaps:

- **The boss needs no site of its own.** `EnemyTypes.Boss.sounds.{death,attack,
  spawn}` are per-type OVERRIDES resolved at the four sites above. Same for
  `SiegeCannon.sounds.attack`.
- **A base arrival is silent.** `_resolve_base_arrivals` despawns it before the
  death sweep can see it — the same reasoning as the no-double-award note there.
- **The boss's second phase is silent.** It stays `alive` until
  `phase_complete`, so the death sound fires once, at its real death.
- **A kidnapper carrying a building home is silent** — `begin_kidnap` retags it
  out of `by_tag("enemy")`.
- **`_spawn_child` makes NO spawn sound** (death swarm / second phase). An
  era-4 burst is 55 children in one frame; the plan authors no child-spawn row.
  Do not "fix" this.
- **No throttle lives here.** SD-2's per-key cooldown and max-concurrent cap
  are the whole mechanism; a 40-enemy wipe calls `play_enemy_sound` 40 times on
  purpose and lets the engine clamp.

**The lookup key is `STAT_SUBTREE[0]`, never `ETYPE` and never
`REGISTRY_GROUP`.** `EnemyTypes` is keyed by the stat subtree; the registry
label differs (`Standard -> "Walker"`, `SiegeCannon -> "Siege Cannon"`, and
Tutorial shares `"Walker"` with Standard while owning its own subtree) and
`ETYPE` is lowercase and differs again. The two layers are
`enemies.EnemySounds.<kind>` (global default) and
`enemies.EnemyTypes.<Type>.sounds.<kind>` (override) — the case split is SD-1's
and is deliberate. `clips: []` on the default = silence; `clips: []` on the
override = inherit. That rule is `engine.audio.bank.resolve`'s; never re-derive
it here.

`sounds.sfx` is bound LAZILY (first play), because `engine/audio/sfx.py`
imports pygame at its module top and `import game.enemies` is pygame-free —
tests monkeypatch `game.enemies.sounds.sfx` with a recorder, which is the only
seam this feature has. With SD-4's `sfx.init()` absent, no audio device, or
`SDL_AUDIODRIVER=dummy`, every trigger degrades to a silent no-op.

## Verify
Scripted round asserts HP ledger matches hand-computed prototype values:
`py -m pytest tools/tests/test_<area>.py -q`.

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
