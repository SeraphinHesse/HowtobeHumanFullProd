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

## Perf invariant that lives here
Placement occupancy is incremental (`occupancy.set` per placed tile, not a
full-map `sync_occupancy`). Detail → `game/PERF.md`.

## Verify
Headless test upgrades both lines to tier max asserting hp/dmg/yield per REPLAN
tables at every step; live: both animate on tiles.
`py -m unittest discover -s tools/tests -t .` + `py game/main.py`.
