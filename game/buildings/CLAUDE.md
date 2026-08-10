# CLAUDE.md — game/buildings (Phase 9D)

`Building(GameObject)` hierarchy. You reached here from `game/CLAUDE.md`. 9D ships
the Musician (economy) + Defender (defence) lines + the untiered `BaseBuilding`.
Ports the prototype's `src/buildings/*`. When you change building conventions,
update THIS doc. **Adding a building? Use the `/add-building` skill.**

## Rules
- **All state in components** (E-11): `components.py` holds `TierState`
  (building_type + tier/level cursor), `Nameplate` (rebirth chain), `RoundStats`
  (per-round damage), `Attacker` (defence combat marker), `YieldEconomy` (economy
  marker); plus engine `Health` / `SpriteAnimator` / `RangeSensor`. The duck-typed
  values `game/map` reads — `alive` / `building_type` /
  `damage_dealt_last_round` — are guard-safe `@property`s backed by those
  components (never plain instance attrs); the balancing dict + tier table live as
  `_`-prefixed transients.
- **Derived values are computed methods on the parents**, never stored (prototype
  `update_stats_from_tier`): `max_hp`, `upgrade_cost`, `level`, `yield_amount`
  (economy), `damage`/`upkeep`/`range_tiles`/`attack_speed` (defence). Formulas are
  `base + (level_in_tier-1)*per_level`; **every `upgrade()`/`advance_tier()`
  full-heals** (sets hp = max_hp). Leaves are ≤ ~10 lines: `SUBTREE` path into
  `buildings.json`, `BUILDING_TYPE`, `TIER_SPRITES` prefixes.
- **Values come from `data/balancing/buildings.json`** (the 9A REPLAN tree —
  authoritative; the prototype `.py` defaults drifted). ×10 combat scale is baked
  in; `BaseBuilding` HP is `core.json TheHole.base_hp` = 10 (the NOT-×10
  exception). The base carries **no SpriteAnimator** — its sprite is the static map
  render (`doc.base` slot), so attaching one would double-draw.
- **Attacker + `"combat"` tag replace the prototype `IS_COMBAT` flag** (SPEC G-3)
  so the combat sweep stays type-agnostic. 9D wires the seam (RangeSensor range
  from the tier, an Attacker clock) but NO enemy acquisition/damage — that is 9E.
- **10C economy lines** (`painter.py`, `meditator.py`) subclass `EconomyBuilding`,
  each a thin leaf + a little computed state:
  - **Painter** (risky lump-sum) adds a `PainterProgress` component
    (`progress`/`gone_for_good`); `yield_amount()` is `0` (out of the income +
    upkeep sweeps), and `payout_amount()`/`rounds_to_payout()`/`goneforgood()`/
    `is_ready()`/`advance_progress()` drive the payday Painter slot (slot 6, in
    `game/core/payday.py`) that pays the lump sum, frees + permanently bars the
    tile (`used_painter_tiles`), or removes a dead gone-for-good painter with a
    "painting lost!" message. The used-tile bar is enforced in `registry.place_building`.
  - **Meditator** (compounding streak) reuses `YieldEconomy.streak`. Its
    `yield_amount()` is **PURE** (three callers: payday, the panel, the HUD
    readout) — the streak side-effect (disturbance reset → pay → advance) lives in
    `collect_income(disturbed)`, called ONLY by the payday income sweep, which
    derives `disturbed` from `RoundStats.dmg_taken_last_round`. Do NOT move the
    side-effect back into `yield_amount()`.
  Both add one `research.py` row (Painter: locked type, `min_village_level` gate;
  Meditator: bare `ResearchSpec()` — its unlock card is gated by whether its
  tier 0 has a Timeline placement (TimelinePLAN T4), and unlocking it makes
  tier 1 immediately placeable).
- **10B defence lines** (`aoe_defence.py` Maw Mortar, `sun_scorcher.py` Sun
  Scorcher) subclass `DefenceBuilding` and add ONE extra capability component +
  a couple computed methods each: AOE adds `SplashAttacker` (marker) +
  `splash_radius()`; Beam adds `BeamAttacker` (ramp/death-cooldown state) +
  `ramp_per_tick()`/`ramp_max()`/`target_death_cooldown()`. The **firing
  behaviour** those markers select lives in the combat sweep (`game/enemies/
  combat.py`), NOT here — the building must not import `game/enemies` (that
  closes a cycle). AOE sets its own `CONTENT_KEY = "aoe_defence_building"` (its
  own pathfinder weight); Beam keeps the shared `"defence_building"`.
- **10D boost line** (`boost.py`: `BoostBuilding` family + thin `BoostSpeed`/
  `BoostDamage`/`BoostHP` leaves) subclasses `Building` directly (neither economy
  nor defence). ONE behaviour class, three data lines
  (`BoostBuildings.{Speed,Damage,HP}`); each leaf carries its OWN
  `CONTENT_KEY` (`boost_speed_building`/`boost_damage_building`/
  `boost_hp_building`) since the buildings-overwrite-tileweights rework gave
  every building type its own `Pathfinding.content_weights` entry — they are
  **seeded to 1, the economy weight they used to share**, so the prototype's
  boost pathfinding-weight fallback is preserved by the VALUE, not by a shared
  key, and a designer can now diverge them per type. Tag `"boost"`.
  **The buff/curse range is configurable** (booster-range-config feature):
  `BoostBuildings.globals.range_tiles`/`.range_shape` — ONE shared magnitude +
  shape for all three lines and every tier (not per-tier, a deliberate design
  choice — a designer wanting per-tier growth would need a schema change).
  `range_shape` is `"plus"` (the shipped default, magnitude 1 = the original
  cardinal-4 behaviour) or `"square"` (a full Chebyshev square — e.g. every
  one of the 8 surrounding tiles at magnitude 1). `game/buildings/
  range_shape.py`'s pure `offsets(n, shape)` computes the tile deltas and is
  shared by `_adjacent_combat`/`clear_explosion_debuff_from` here AND by the
  RANGE overlay (`game/ui/overlays.py`) and the panel's selection highlight +
  its own new Range row (`game/ui/building_ui.py`) — both duck-type an
  optional `range_shape()` alongside `range_tiles()`, defaulting to
  `"square"` when absent (every defence building, unchanged), so those two
  visually reflect a booster's configured shape. Defence-range pathfinding
  coverage (`coverage.py`, below) is the ONE exception: it deliberately does
  NOT consult `range_shape()` and always treats a booster's footprint as a
  square, at the configured magnitude — the visual buff shape and the
  pathfinding-penalty shape are independent knobs. `BoostBuilding
  .range_tiles()`/`.range_shape()` read the balance directly; there is no
  per-instance override.
  All buff/curse state lives on the NEIGHBOUR's `BoostReceiver` component
  (`damage_pct`/`speed_pct`/`hp_pct` + a JSON-safe `explosion_debuffs` list) added
  to every `DefenceBuilding`; the booster only pushes deltas. Consumed transparently
  in `DefenceBuilding.damage()`/`attack_speed()` and `Building.max_hp()` (None-safe),
  so the combat sweep needs no change. The per-turn accumulation + explosion-on-death
  run in the payday **boost slot (slot 7, before revive)**; the cardinal-4 adjacency
  placement block + `on_placed` debuff-clear/flat-apply run in `registry.place_building`.
  A `BoostEmitter` marker holds the `exploded` (one-shot per death, reset on
  `rebuild()`) + `flat_applied` guards. Both modes exist: ramp (default) accumulates
  each income phase, flat (`BoostBuildings.globals.flat_mode`) applies 10× once on
  placement / reverses on death. Research: three rows sharing `unlock_group=(the
  trio)` (no `gate_kind` — only the LEAD's tier-0 Timeline placement is ever
  consulted, read via `tier_offerable`, TimelinePLAN D8) + a shared
  `starts_unlocked_path` pointing at
  `BoostBuildings.globals.starts_unlocked` (data-driven — see the Research/gating
  seam section); the roll offers ONE unlock card (the lead `boost_speed`).
  **Tiers 2 and 3 are grouped the same way**: the same three rows carry
  `tier_group=(the trio)` so each later tier is also ONE card researching all
  three lines (`game/core`), with the lead additionally carrying
  `tier_copy_path=("BoostBuildings", "globals")` — a card granting three lines
  cannot be titled from any one line's tier name, so its copy is designer-editable
  data (`tier_card_titles`/`tier_card_explanations`, 3 entries each). Each placed
  booster still advances individually at its own `build_cost`.
  - **Wall-hp-boost feature: the HP line (`boost_hp`) ALSO reaches nearby
    WallBuilders' walls**, via a SECOND, parallel adjacency scan
    (`_adjacent_structures`, same `range_shape.offsets(...)` geometry as
    `_adjacent_combat`, but duck-typed on `hasattr(b, "wall_hp")` — the
    `movement.py` `is_movable` precedent — rather than the `"combat"` tag,
    since `"structure"` also covers `Blocker`, which has no walls). It pushes
    into a DEDICATED `WallBuilderState.wall_hp_pct` accumulator via a new
    `_apply_wall_delta`, never `BoostReceiver` — a WallBuilder never carries
    one, so its own body HP (`Building.max_hp()`) is provably unaffected;
    only `wall_hp()` (`structure.py`) reads `wall_hp_pct`. The RATE is its
    own dedicated pair, `BoostBuildings.HP.tiers[].wall_boost_per_turn`/
    `wall_boost_increase_per_level` (`$defs/boost_hp_tier` in the schema,
    HP-line-only — Speed/Damage keep the shared `$defs/boost_tier`),
    independent of `boost_per_turn`/`boost_increase_per_level`, which only
    ever affects adjacent combat buildings. Every method that already loops
    `_adjacent_combat` for the `"hp"` stat (`apply_per_turn`/`apply_flat`/
    `remove_flat`/`apply_explosion_debuff`) gained an additive, HP-gated
    block that also loops `_adjacent_structures` — same ramp/flat modes,
    same halve-on-booster-death/restore-on-replacement lifecycle, mirrored
    via `WallBuilderState.wall_hp_debuffs` (`BoostReceiver.explosion_debuffs`'
    shape, minus the unneeded `"stat"` key). `clear_explosion_debuff_from`
    checks both receiver kinds unconditionally (any booster replacing any
    previous occupant must clear whatever that occupant left, regardless of
    either one's own stat). A boosted wall resyncs via `WallBuilder
    .resync_wall_hp(full_heal=False)` — heal-by-delta/clamp-on-decrease,
    the `_refresh_max_hp` shape — never the full-heal `_on_apply_stats` uses
    for a real upgrade.
- **10E structure line** (`structure.py`: `StructureBuilding` family + thin `Blocker`
  / `WallBuilder` leaves) subclasses `Building` directly (passive — no attack, no
  yield); each leaf carries its OWN `CONTENT_KEY` (`blocker_building`/
  `wall_builder_building`) since the buildings-overwrite-tileweights rework, both
  **seeded to 1 — the economy weight they used to share** — so the traversable
  "enemies attack, not reroute" intent is preserved by the VALUE, not by a shared
  key. Tag `"structure"`. Both use a SINGLE flat art slot per type (override
  `slot_key()` → `SLOT`, matching the flat `blocker`/`wall_builder` slots in
  `data/slots.json`; `_tier_option` in `game/core/levelup.py` reads that same flat
  `SLOT` for the research card). **Blocker** is a pure tier-HP soak (no new enemy code
  — the standard block-and-attack handles it). **WallBuilder** adds a `WallBuilderState`
  component (its only field is `wall_snapshot`, the frozen `[c1,r1,c2,r2]` edge list)
  + computed `wall_hp()` (NOT ×10) / `upkeep()`; `on_placed()` calls
  `TileMap.place_walls_for_builder(self)` and `_on_apply_stats()` resyncs owned wall
  HP. The edge-wall registry itself lives in `game/map` (see that
  doc); the payday teardown/rebuild is `game/core` (slots 8/10).
  **`wall_hp()` is per TIER *and* LEVEL**: `wall_hp + lvl_idx *
  wall_hp_per_level`, composed exactly like `upkeep()` beside it.
  `wall_hp_per_level` is seeded **0** in all three tiers, so the shipped
  behaviour is the prototype's flat per-tier value until a designer tunes it.
  Consequently `_on_apply_stats()` now fires meaningfully on LEVEL upgrades too
  (it always ran on both, but a level upgrade could not previously change
  `wall_hp()`), and it **FULL-HEALS** owned edges (`edge.hp = new_hp`, was
  `min(edge.hp, new_hp)`) — matching `Building.apply_tier_stats`'s
  every-re-apply `hp = max_hp` rule, so walls follow the same
  upgrade-heals-you contract the builder itself has.
  - **The WALLS have their own art family, separate from the builder's flat
    `SLOT`**: `WallBuilder.wall_slot()` → `wall_t{tier}_lvl{level}` (both
    1-based — the 9 `Base` keys in `data/slots.json`'s `walls` category), reading the
    same `TierState` cursor `Building.slot_key` does. It lives HERE, beside
    `slot_key()`, because the slot-key convention is a building concern;
    `game/map/wall_render.py` reaches it **duck-typed** as
    `edge.owner.wall_slot()`, so the map layer keeps importing NOTHING from
    `game.buildings` — the same rule `wall_hp()` / `wall_snapshot()` /
    `building_type` already follow.
  - **Wall-era-art feature: each tier group also carries optional `Era N`
    sibling children** (`wall_t{tier}_lvl{level}_era{n}`, open-ended — however
    many a designer imports; `data/slots.json`'s `walls` category ships
    `Era 1`..`Era 5` per tier today, matching the Boss's 5-row era table, all
    art-less until imported). `WallBuilder.wall_era_slot()` resolves it off a
    FROZEN `WallBuilderState.art_era` stamp (0 = unstamped/Base). **The stamp
    changes ONLY when the WallBuilder is placed or upgraded — never live off
    the round clock** (a deliberate design decision distinct from how enemies
    re-skin per era): `game/core/wall_era.py`'s `sync_wall_art_era(state,
    building, enemies_balance)` reads the CURRENT global era
    (`engine.era_math.era_of_round`, off the SAME `EnemyScaling.
    rounds_per_era` clock enemies use — one era definition for the whole
    game, not a parallel buildings-side config) and calls
    `WallBuilder.stamp_era(era)`. It is duck-typed (`hasattr(building,
    "stamp_era")`, no type-string check — G-3) and called from
    `game/ui/building_ui.py` at exactly the placement and upgrade/tier-advance
    call sites the Storm Priest's `lightning.sync_level_from_tier` already
    hooks into — a no-op for every other building type.
    `game/map/wall_render.py`'s `wall_render_items()` tries `wall_era_slot()`
    first and falls back to `wall_slot()` whenever the era slot has no
    imported art (E-37 — never a grey X). Research: both
  `blocker` and `wall_builder` are bare `ResearchSpec()` rows — each type's
  UNLOCK card is gated by whether its own tier 0 has a Timeline placement
  (TimelinePLAN T4), and unlocking either makes its tier 1 immediately
  placeable (no separate "research tier 1" step). **Both start LOCKED as a
  type** (a deliberate balance change from the prototype's
  `blocker_tiers_unlocked = 1`): `starts_unlocked` is now a `buildings.json` flag
  per type (see the Research/gating seam section) — only `defence`/Stone Thrower and
  `economic`/Flute Player start unlocked; every other type, blocker and wall_builder
  included, is earned via a level-up unlock card. `registry.place_building` now
  calls `building.on_placed(tilemap)` UNCONDITIONALLY (a `Building` base no-op hook —
  boost + wall-builder override it), replacing the boost-only special-case.
- **Storm Priest** (`storm_priest.py`: `StormPriest`) is the Lightning Strike
  ability's vehicle, NOT a combatant (Storm Priest rework). It is a 3-tier
  `DefenceBuilding` leaf (Storm Acolyte → Storm Priest → Storm High Priest,
  matching Lightning Strike's `max_level` of 3) but `EXTRA_TAGS =
  ("lightning_source",)` deliberately DROPS the inherited `"combat"` tag
  (`EXTRA_TAGS` fully overrides, `building.py:54`) — excluded from
  `scene.by_tag("combat")`, the combat sweep's defender loop
  (`game/enemies/combat.py`), it never targets, fires or animates through
  combat. Its inherited `Attacker`/`RangeSensor`/`BoostReceiver` (from
  `DefenceBuilding._extra_components`) are harmless, inert leftovers of the
  shared family. It overrides `_extra_components` to append a
  `game.core.lightning.LightningCaster` component, which puppets its
  `SpriteAnimator` into the "attack" pose whenever `lightning.strike()` fires
  (since it no longer earns that pose through combat), reverting to "idle"
  shortly after. **`LightningCaster` is imported LAZILY inside
  `_extra_components`, never at module level** — a module-level import closes
  a real cycle (`game.buildings.__init__` -> `.storm_priest` -> `game.core`
  full package init -> `.levelup` -> `game.buildings.research` ->
  `.storm_priest`, still mid-import) — the same lazy-import discipline
  `building.py`'s `_condition_mod` already uses for `game.map.tiles`.
  - **Placement unlocks, tier ADVANCE levels.** `game.ui`'s placement flow
    still calls `game.core.lightning.unlock_from_placement(state, building)`
    after every successful place (unlocks lightning `lightning_level 0→1`, a
    `max()` latch, iff the placed building carries `"lightning_source"`).
    Advancing the Storm Priest's OWN tier — the player's ordinary
    building-upgrade panel, paying its own tier-advance cost, no separate
    love-priced lightning upgrade any more — calls
    `game.core.lightning.sync_level_from_tier(state, building)` from
    `game/ui/building_ui.py`'s tier-advance branch, raising `lightning_level`
    to match the new tier (tier 1/2/3 -> lightning level 1/2/3, latched so a
    re-sync never lowers it). Both helpers are **tag-gated, not
    type-string-gated**, so `registry.place_building` stays type-agnostic (no
    `storm_priest` branch) — the same G-3 discipline as the
    `IS_COMBAT`→`"combat"` tag.
  - **Run-singleton REMOVED (feature-storm-acolyte-multi-build)**: any number
    of Storm Priests may be placed, each levelled independently and firing
    together on one click (see `game/core/CLAUDE.md`'s lightning section for
    the per-caster level/cooldown rework and `game/ui/CLAUDE.md` for the
    charge-bar FX). Each extra one costs more: `DefenceBuildings.StormPriest`
    carries an OPTIONAL group-level `repeat_cost_multiplier` (1.8); a fresh
    placement's price is `build_cost * multiplier ** N`, `N` = the count of
    already-placed `"lightning_source"`-tagged occupants (alive OR dead — a
    dead one is not a freed slot, payday's slot-9 revive brings it back).
    `registry.count_tag(tilemap, tag)` is the O(built-tiles) counter
    (`TileMap.built_tiles()`'s `_by_state` index — never a full-map scan);
    `registry.build_cost(..., repeat_count=0)` is a no-op for every type
    without the multiplier key, so this is Storm-Priest-only in practice
    while staying **tag-gated, not type-string-gated** (G-3) — the counting
    seam never branches on `building_type == "storm_priest"`.
    `game/ui/building_ui.py`'s construct card, its hover price, and
    `ConstructPreview.total_cost` (which sums the ESCALATING batch sequence
    for a shift-multi-select placement, not a flat `cost * count`) all read
    off this same count so the label, the hover figure and the actual charge
    can never disagree.
  - Research row: a bare `ResearchSpec(...)` (no `gate_kind`; offerable as
    soon as its tier 0 has a Timeline placement, TimelinePLAN T4) with
    `starts_unlocked: false` in `buildings.json` — offered in the level-up
    unlock pool once placed but not unlocked at the start. (Lightning itself
    boots LOCKED — see `game/core/CLAUDE.md`.)
- **10I tile conditions** — snapshot at placement, computed on read:
  - `registry.place_building` stamps two E-11 transients after
    `tile.occupant = building`: `_tile_condition` (the tile's rolled condition)
    + `_condition_mods` (the `TileConditions.modifiers` subtree), then
    re-applies stats so the RangeSensor sees the snapshot. Defaults (`None`,
    `{}`) keep `create()` previews / headless tests neutral; the base building
    bypasses `Building.__init__` and never gets the attrs (always
    GRASS-neutral). `Building._condition_mod(key)` is the one lookup helper
    (lazy `game.map.tiles` import — a module-level one would close the
    `game.buildings.__init__` → `game.map` → `game.core` →
    `game.buildings.research` cycle).
  - **Defence formula order is prototype-exact: boost → condition → explosion
    debuffs (→ floor)**: `damage()` inserts the FOREST `def_dmg_penalty` cut
    between the boost multiply and the debuff halving; `attack_speed()` inserts
    the POND `def_attack_speed_penalty` slow the same way. **Raw vs effective
    range split**: `range_tiles()` stays RAW (feeds pathfinding coverage + the
    RANGE overlay); NEW `effective_range_tiles()` adds the MOUNTAIN
    `def_range_bonus` (feeds the panel Range row + the selection highlight);
    NEW `targeting_range_tiles()` is what the combat sweep + RangeSensor use —
    effective for basic/beam, but **RAW for the mortar** (selected by its
    `SplashAttacker` marker): the prototype's own `_in_range` inconsistency
    (`aoe_defence_building.py:308` reads raw while `defence_building.py:264`
    reads effective), kept deliberately for parity — 10J/parity audits must
    not "fix" it. `boosted_stats()` also emits the pre-forest Damage base when
    the cut actually changes the value (prototype gate).
  - **Economy**: `EconomyBuilding.yield_amount` applies mountain
    `max(0, int(y×0.9))` / pond+forest `int(y×1.1)` ON READ (payday, HUD,
    panel all see it). Meditator + Painter override `yield_amount` and take NO
    condition modifier (prototype-exact).
  - **`coverage.py`** is the defence-range pathfinding producer:
    `defence_covered_tiles` (Chebyshev union of alive defenders' RAW range —
    `game/buildings/range_shape.py`'s `offsets(r, "square")`, ALWAYS square —
    `building_type == "aoe_defence"` EXCLUDED — pathfinding-only; the RANGE
    overlay still shows the mortar; empty set when
    `BuildingsGlobal.defence_range_pathfinding.enabled` is off) +
    `wire_defence_coverage` (injects callable + weight add into the tilemap —
    the host calls it once per run; the map layer never imports this
    package). **Boosters carry a real `range_tiles()` now** (booster-range-
    config feature, `BoostBuildings.globals.range_tiles`, configurable per
    the 10D boost-line section above) — the old special-cased "every alive
    `"boost"`-tagged occupant adds a fixed r=1 square" branch is gone,
    boosters are picked up by the SAME duck-typed `range_tiles()` read every
    other occupant here uses — but this producer deliberately does NOT
    consult a booster's `range_shape()`: pathfinding coverage stays a square
    at the configured MAGNITUDE regardless of whether the visual buff/curse
    itself is `"plus"` or `"square"` (the RANGE overlay and the selection
    highlight DO respect `range_shape()` — see `game/ui/CLAUDE.md`).
- **`registry.py` is the factory + placement seam**: `create(building_type,…,
  tier_idx=0)` (also reconstructs a subclass after `GameObject.from_dict`), and
  `place_building(tilemap, tile, type, love, …)` — buildable-tile + affordability
  gate → sets `tile.occupant/content_key/state` → `scene.spawn` → `sync_occupancy`
  → raises `PlacementError` on a bad tile / too little love. `attach_base` wires the
  `BaseBuilding` onto its pre-seeded tile. Love is passed in (no game-state store
  until 9F); UI batching + per-type unlock gates are 9F/9G. **A fresh placement
  builds at the type's CURRENT research ceiling, not always tier 0**: `place_building`
  derives `tier_idx` from `tiers_unlocked_for(state, building_type) - 1` and threads
  it through both `build_cost(building_type, buildings_balance, tier_idx)` and
  `create(...)` — once a higher tier is researched, the lower tier is simply never
  placed again (no separate gate). `build_cost` is now the ONE price for a tier:
  the same number is charged for a fresh placement, the level-up "tier" research
  card, and the upgrade panel's advance-to-next-tier button (`tier_unlock_cost` /
  `tier_unlock_cost_per_tier` were removed from the schema — dead weight once
  `build_cost` covers all three).

## Building Movement (`movement.py`)
Moving an ALREADY-PLACED building to another unbuilt buildable tile.
`movement.py` is the pure-logic sibling of `registry.place_building`, and
`start_move` is the ONE legal way a placed building leaves its tile — the same
"single legal path" rule `place_building` holds for arrivals.
- **Cost + duration both scale with CHEBYSHEV distance**, floor-divided into
  steps: `base + (distance // increment) * increase`, or a flat `0` when the
  matching `*_enabled` flag is off. Every number is
  `BuildingsGlobal.Movement` in `data/balancing/buildings.json` (G-7); the
  caller passes that subtree in, this module never loads it. `move_cost` /
  `move_time` / `move_distance` are pure and are what the UI quotes.
- **A move in transit is represented by ABSENCE, and that is the whole
  design.** `start_move` clears the origin tile to `TileState.BUILDABLE` with
  no occupant/content key and **despawns the building from the scene**. There
  is deliberately **NO new `TileState` member**: BUILDABLE already resolves to
  the `buildable_tile` pathfinding weight (walkable, not blocked) with zero
  changes to `game/map/tiles.py`, and a new member would have rippled through
  `_STATE_CONTENT_KEY` / `CONDITION_STATE_LABEL` / `_STATE_CODE` /
  `Tile.is_unlocked` / `TileMap._is_unlocked_state` / `_is_player_territory` /
  `main.py`'s `_SEL_CATEGORY` for the same runtime behaviour. Because the
  building is out of the scene, `scene.by_tag("combat")` (combat sweep),
  `by_tag("building")` (HP bars), payday's `built_tiles()` occupant sweeps
  (income/upkeep/boost) and the boss goal set all stop seeing it and pick it
  back up the instant it lands — **with zero new guards in any of them**.
  There is no `on_removed` hook and none is needed.
- **`TileMap.moving_orders` + `is_moving` are what tell an endpoint apart**
  (see `game/map/CLAUDE.md`) — both endpoints stay BUILDABLE for pathfinding
  but are barred from hosting a new building. That bar is enforced in
  **`place_building`**, beside the painter-tile bar, for the same reason: the
  panel refusing to open construct mode on an endpoint is a convenience, the
  placement seam is the enforcement.
- **Arrival re-runs `Building.on_placed(tilemap)`** — the same post-placement
  family hook a fresh placement fires, so a moved booster re-applies its
  flat-mode buff to its NEW cardinal neighbours. Its OLD neighbours keep
  whatever `BoostReceiver` state they already had (never touched), and the
  moved building's own `BoostReceiver` travels with the Python object: it is
  the SAME object throughout, only its tile changes. `_complete` also moves
  `_col`/`_row` (the transient caches `Building.col`/`.row` read) AND the
  `Transform` — miss either and the building draws/targets from where it used
  to stand.
- **A Wall Builder can NEVER be moved** — duck-typed on `hasattr(b,
  "wall_hp")` (`is_movable`), the same check `game/ui/building_ui.py`'s
  `_building_stats` already uses; its walls are a frozen perimeter snapshot
  tied to the tile they were raised from. The UI shows the button DISABLED;
  `start_move` raises `MoveError` regardless.
- **`rounds == 0` (time cost off, or tuned to zero) relocates synchronously**
  and records no order at all — nothing to tick, nothing to sign-post.
  Otherwise a `types.SimpleNamespace` order is appended and `process_moves`
  (payday's last step, `game/core/CLAUDE.md`) ticks it down.
- `MOVING_SIGN_SLOT` (`"moving_sign"`, the flat `core`-category art slot the
  host draws on both endpoints) lives here, with the feature, so the host has
  one place to import it from.

## Research / gating seam (10A, regated in the Joel-Balancing pass; TimelinePLAN T4)
- **`game/buildings/research.py`** is the extension seam: `LEAF_CLASSES` + a
  `RESEARCH` table of `ResearchSpec` rows (`gate_kind`/`gate_path`,
  `starts_unlocked_path`, `unlock_group`, `tier_group`/`tier_copy_path`,
  UI copy). A spec never stores a gate
  VALUE, only where in `buildings.json` to read it. **10B–10E add a leaf class
  + one row and NEVER reopen the roll.** It lives there (not `registry.py`)
  because `registry` imports `game.map.tiles` → `game.core.balance`;
  `game/core/levelup.py` must read the table without closing that cycle.
  `registry` re-exports `LEAF_CLASSES` as `BUILDING_CLASSES` and gates
  `place_building` on `buildable(state, btype)`.
- **Whether a type starts unlocked is `buildings.json` DATA, not a Python
  default** — "general balancing info" alongside a type's other tunables, so a
  designer can flip it without touching code. `starts_unlocked_for(btype,
  buildings_balance)` reads it live off the leaf's own `SUBTREE` group node
  (`<group>.starts_unlocked`); a spec overrides the path only when the default
  derivation is wrong (the boost trio shares ONE flag at
  `BoostBuildings.globals.starts_unlocked`, since their own `SUBTREE`s are
  `Speed`/`Damage`/`HP`). `RunState.from_balance(core, buildings)` seeds
  `unlocked_buildings` from it ONCE at run start — it is not re-read live
  thereafter. **Only `defence` (Stone Thrower) and `economic` (Flute Player)
  start unlocked; every other type is locked from round 1**, including
  `blocker`/`meditator`/`wall_builder`, which used to default unlocked — a
  deliberate balance change, not a bug.
- **There is exactly ONE eligibility gate per tier, and since TimelinePLAN T4
  it is a Timeline placement, not a round.** `unlock_min_round` is DELETED
  from `buildings.json`'s schema and content entirely — the sole source of
  "when does `(btype, tier_index)` become offerable" is now
  `data/balancing/progression.json`, resolved via
  `game/core/levelup.py::timeline_level_for(btype, idx, progression_balance)
  -> village_level | None`, gated on `state.village_level` (not
  `state.round_num`) via `tier_offerable`. It gates the type's UNLOCK card
  the same way (`tier_offerable(state, btype, 0, progression_balance)` in
  `game/core/levelup.py`'s roll) — a locked type never shows a tier card,
  only its unlock card, so tier 0's own Timeline placement doubles as the
  type's era gate; no separate `<group>.era_unlock_round` key exists.
  **Unlocking a type makes its tier 1 immediately placeable** —
  `ResearchSpec.starts_with_tier` was deleted along with it, closing off the
  double-unlock-card bug (Meditator/WallBuilder used to need a free unlock
  card AND a same-named "research tier 1" card before they were placeable).
  Only the SINGLE next locked tier (`idx == tiers_unlocked`) is ever offerable
  for research past tier 1, gated by that tier's own Timeline placement.
  Research is GLOBAL per type. A tier with NO Timeline placement is simply
  never offerable — the editor's Timeline panel (`editor/panels/timeline.py`)
  is where a designer authors these placements now, not a `buildings.json`
  round value. The `gate_kind="min_village_level"` stacked gate (Maw Mortar's
  `AOEDefence.unlock_min_village_level`, Painter's
  `Painters.unlock_min_village_level`) is a SEPARATE, orthogonal gate,
  untouched by this change (TimelinePLAN D6).
- **10B rows** (`aoe_defence`, `sun_scorcher`) both start locked (earned via a
  level-up unlock card). Maw Mortar uses
  `gate_kind="min_village_level"` reading a NEW `AOEDefence.unlock_min_village_level`
  key (value 1 — offered from the first level-up; the prototype had it only as a
  `.py` constant, absent from the live JSON 9A migrated, so 10B added it to
  data+schema). Sun Scorcher needs NO `gate_kind`: its unlock card is gated by
  whether `BeamDefence`'s tier 0 has a Timeline placement (was era-gated to
  14, then a flat `tiers[0].unlock_min_round = 10`, before TimelinePLAN T4
  deleted that field entirely in favor of `data/balancing/progression.json`
  — each step an approved balance/architecture shift, not a migration of the
  old number).

## Perf invariant that lives here
Placement occupancy is incremental (`occupancy.set` per placed tile, not a
full-map `sync_occupancy`). Detail → `game/PERF.md`.

## Verify
Headless test upgrades both lines to tier max asserting hp/dmg/yield per REPLAN
tables at every step; live: both animate on tiles.
`py -m unittest discover -s tools/tests -t .` + `py game/main.py`.
