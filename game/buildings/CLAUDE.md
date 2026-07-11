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
