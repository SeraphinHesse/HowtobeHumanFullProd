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
  Meditator: bare `ResearchSpec()` — its unlock card is gated by
  `Meditators.tiers[0].unlock_min_round`, and unlocking it makes tier 1
  immediately placeable).
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
  (`BoostBuildings.{Speed,Damage,HP}`); `CONTENT_KEY="economic_building"` (the
  prototype's boost pathfinding-weight fallback — no map change), tag `"boost"`.
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
  trio)` (no `gate_kind` — each line's own `tiers[0].unlock_min_round` is 10,
  read via `tier_offerable`) + a shared `starts_unlocked_path` pointing at
  `BoostBuildings.globals.starts_unlocked` (data-driven — see the Research/gating
  seam section); the roll offers ONE unlock card (the lead `boost_speed`), then
  each type researches its own tiers (see `game/core`).
- **10E structure line** (`structure.py`: `StructureBuilding` family + thin `Blocker`
  / `WallBuilder` leaves) subclasses `Building` directly (passive — no attack, no
  yield), `CONTENT_KEY="economic_building"` (traversable weight — enemies attack, not
  reroute), tag `"structure"`. Both use a SINGLE flat art slot per type (override
  `slot_key()` → `SLOT`, matching the flat `blocker`/`wall_builder` slots in
  `data/slots.json`; `_tier_option` in `game/core/levelup.py` reads that same flat
  `SLOT` for the research card). **Blocker** is a pure tier-HP soak (no new enemy code
  — the standard block-and-attack handles it). **WallBuilder** adds a `WallBuilderState`
  component (its only field is `wall_snapshot`, the frozen `[c1,r1,c2,r2]` edge list)
  + computed `wall_hp()` (NOT ×10) / `upkeep()`; `on_placed()` calls
  `TileMap.place_walls_for_builder(self)` and `_on_apply_stats()` resyncs owned wall
  HP on a tier upgrade. The edge-wall registry itself lives in `game/map` (see that
  doc); the payday teardown/rebuild is `game/core` (slots 8/10). Research: both
  `blocker` and `wall_builder` are bare `ResearchSpec()` rows — each type's
  UNLOCK card is gated by its own `tiers[0].unlock_min_round` (Blocker 5,
  WallBuilder 10), and unlocking either makes its tier 1 immediately placeable
  (no separate "research tier 1" step). **Both start LOCKED as a type** (a
  deliberate balance change from the prototype's
  `blocker_tiers_unlocked = 1`): `starts_unlocked` is now a `buildings.json` flag
  per type (see the Research/gating seam section) — only `defence`/Stone Thrower and
  `economic`/Flute Player start unlocked; every other type, blocker and wall_builder
  included, is earned via a level-up unlock card. `registry.place_building` now
  calls `building.on_placed(tilemap)` UNCONDITIONALLY (a `Building` base no-op hook —
  boost + wall-builder override it), replacing the boost-only special-case.
- **Storm Priest** (`storm_priest.py`: `StormPriest`) is a plain 3-tier
  `DefenceBuilding` leaf — no new building behaviour, just the standard defence
  line (Storm Acolyte → Storm Priest → Storm High Priest). Its ONE novelty is a
  capability tag: `EXTRA_TAGS = ("combat", "lightning_source")` (the subclass
  MUST re-include `"combat"` — `EXTRA_TAGS` fully overrides, `building.py:54`).
  The tag is the seam to the Lightning Strike ability: `game.ui`'s placement flow
  calls `game.core.lightning.unlock_from_placement(state, building)` after every
  successful place, which unlocks lightning (`lightning_level 0→1`, a `max()`
  latch) iff the placed building carries `"lightning_source"`. The rule is
  **tag-gated, not type-string-gated**, so `registry.place_building` stays
  type-agnostic (no `storm_priest` branch) — the same G-3 discipline as the
  `IS_COMBAT`→`"combat"` tag. Research row: a bare `ResearchSpec(...)` (no
  `gate_kind`; its `tiers[0].unlock_min_round` is 0) with `starts_unlocked:
  false` in `buildings.json` — offered in the level-up unlock pool from round 1
  but not unlocked at the start. (Lightning itself now boots LOCKED — see
  `game/core/CLAUDE.md`.)
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
    `defence_covered_tiles` (Chebyshev union of alive defenders' RAW range,
    `building_type == "aoe_defence"` EXCLUDED — pathfinding-only; the RANGE
    overlay still shows the mortar; every alive `"boost"`-tagged occupant adds
    an r=1 square — prototype boosters carry `range_tiles = 1`, but the repo
    booster keeps NO `range_tiles()` method so the selection highlight stays a
    plus-shape; empty set when
    `BuildingsGlobal.defence_range_pathfinding.enabled` is off) +
    `wire_defence_coverage` (injects callable + weight add into the tilemap —
    the host calls it once per run; the map layer never imports this package).
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

## Research / gating seam (10A, regated in the Joel-Balancing pass)
- **`game/buildings/research.py`** is the extension seam: `LEAF_CLASSES` + a
  `RESEARCH` table of `ResearchSpec` rows (`gate_kind`/`gate_path`,
  `starts_unlocked_path`, `unlock_group`, UI copy). A spec never stores a gate
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
- **There is exactly ONE round gate per type: `tiers[0].unlock_min_round`.**
  It gates the type's UNLOCK card (via `tier_offerable(state, btype, 0,
  buildings_balance)` in `game/core/levelup.py`'s roll) — a locked type never
  shows a tier card, only its unlock card, so tier 0's own round doubles as
  the type's era gate; no separate `<group>.era_unlock_round` key exists
  anymore. **Unlocking a type makes its tier 1 immediately placeable** —
  `ResearchSpec.starts_with_tier` was deleted along with it, closing off the
  double-unlock-card bug (Meditator/WallBuilder used to need a free unlock
  card AND a same-named "research tier 1" card before they were placeable).
  Only the SINGLE next locked tier (`idx == tiers_unlocked`) is ever offerable
  for research past tier 1, gated by that tier's own `tiers[idx].unlock_min_round`.
  Research is GLOBAL per type.
- **10B rows** (`aoe_defence`, `sun_scorcher`) both start locked (earned via a
  level-up unlock card). Maw Mortar uses
  `gate_kind="min_village_level"` reading a NEW `AOEDefence.unlock_min_village_level`
  key (value 1 — offered from the first level-up; the prototype had it only as a
  `.py` constant, absent from the live JSON 9A migrated, so 10B added it to
  data+schema). Sun Scorcher needs NO `gate_kind`: its unlock card is gated by
  `BeamDefence.tiers[0].unlock_min_round = 10` (was era-gated to 14 before the
  `era_unlock_round` key was deleted — an approved balance shift, not a
  migration of the old number).

## Perf invariant that lives here
Placement occupancy is incremental (`occupancy.set` per placed tile, not a
full-map `sync_occupancy`). Detail → `game/PERF.md`.

## Verify
Headless test upgrades both lines to tier max asserting hp/dmg/yield per REPLAN
tables at every step; live: both animate on tiles.
`py -m unittest discover -s tools/tests -t .` + `py game/main.py`.
