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
  Meditator: `starts_with_tier=0`, era-gated from `Meditators.era_unlock_round`).
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
  placement / reverses on death. Research: three `starts_unlocked=False` rows sharing
  `unlock_group=(the trio)` + `gate_kind="min_round"`; the roll offers ONE unlock card
  (the lead `boost_speed`), then each type researches its own tiers (see `game/core`).
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
  doc); the payday teardown/rebuild is `game/core` (slots 8/10). Research: `blocker`
  is `ResearchSpec()` (always unlocked, placeable from round 1; Bulwark/Bastion tiers
  round-gated); `wall_builder` is `ResearchSpec(starts_with_tier=0)` (era-gated from
  `WallBuilder.era_unlock_round`, like the meditator). `registry.place_building` now
  calls `building.on_placed(tilemap)` UNCONDITIONALLY (a `Building` base no-op hook —
  boost + wall-builder override it), replacing the boost-only special-case.
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
    `def_range_bonus` (feeds targeting in the combat sweep, the panel Range
    row, the selection highlight, and the RangeSensor via `_on_apply_stats`).
    `boosted_stats()` also emits the pre-forest Damage base when the cut is
    active.
  - **Economy**: `EconomyBuilding.yield_amount` applies mountain
    `max(0, int(y×0.9))` / pond+forest `int(y×1.1)` ON READ (payday, HUD,
    panel all see it). Meditator + Painter override `yield_amount` and take NO
    condition modifier (prototype-exact).
  - **`coverage.py`** is the defence-range pathfinding producer:
    `defence_covered_tiles` (Chebyshev union of alive defenders' RAW range,
    `building_type == "aoe_defence"` EXCLUDED — pathfinding-only; the RANGE
    overlay still shows the mortar; empty set when
    `BuildingsGlobal.defence_range_pathfinding.enabled` is off) +
    `wire_defence_coverage` (injects callable + weight add into the tilemap —
    the host calls it once per run; the map layer never imports this package).
- **`registry.py` is the factory + placement seam**: `create(building_type,…)`
  (also reconstructs a subclass after `GameObject.from_dict`), and
  `place_building(tilemap, tile, type, love, …)` — buildable-tile + affordability
  gate → sets `tile.occupant/content_key/state` → `scene.spawn` → `sync_occupancy`
  → raises `PlacementError` on a bad tile / too little love. `attach_base` wires the
  `BaseBuilding` onto its pre-seeded tile. Love is passed in (no game-state store
  until 9F); UI batching + per-type unlock gates are 9F/9G.

## Research / gating seam (10A)
- **`game/buildings/research.py`** is the extension seam: `LEAF_CLASSES` + a
  `RESEARCH` table of `ResearchSpec` rows (`starts_unlocked`, `starts_with_tier`,
  `gate_kind`/`gate_path`, `unlock_group`, UI copy). A spec never stores a gate
  VALUE, only where in `buildings.json` to read it. **10B–10E add a leaf class +
  one row and NEVER reopen the roll.** It lives there (not `registry.py`) because
  `registry` imports `game.map.tiles` → `game.core.balance`; `game/core/levelup.py`
  must read the table without closing that cycle. `registry` re-exports
  `LEAF_CLASSES` as `BUILDING_CLASSES` and gates `place_building` on
  `buildable(state, btype)`.
- **Three gates stack**, all read live from `buildings.json`: the type unlock
  (`RunState.unlocked_buildings`), the **era gate** `<group>.era_unlock_round`, and
  the per-tier `tiers[idx].unlock_min_round`. Only the SINGLE next locked tier
  (`idx == tiers_unlocked`) is ever offerable. Research is GLOBAL per type.
  `<group>.era_unlock_round` is the ONE canonical era key (10A lifted it off the
  tier dicts onto the group).
- **10B rows** (`aoe_defence`, `sun_scorcher`) are both `starts_unlocked=False`
  (earned via a level-up unlock card). Maw Mortar uses
  `gate_kind="min_village_level"` reading a NEW `AOEDefence.unlock_min_village_level`
  key (value 1 — offered from the first level-up; the prototype had it only as a
  `.py` constant, absent from the live JSON 9A migrated, so 10B added it to
  data+schema). Sun Scorcher needs NO `gate_kind`: its era gate resolves from
  `BeamDefence.era_unlock_round = 14`.

## Perf invariant that lives here
Placement occupancy is incremental (`occupancy.set` per placed tile, not a
full-map `sync_occupancy`). Detail → `game/PERF.md`.

## Verify
Headless test upgrades both lines to tier max asserting hp/dmg/yield per REPLAN
tables at every step; live: both animate on tiles.
`py -m unittest discover -s tools/tests -t .` + `py game/main.py`.
