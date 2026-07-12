# CLAUDE.md — game/map (Phases 9C + 10I)

Runtime tile layer + pathfinder. You reached here from `game/CLAUDE.md`. Ports the
prototype's `src/map/*` behaviour. When you change map-runtime conventions, update
THIS doc.

Runtime layer over an `engine.tilemap.TileMapDoc` (**never re-parse map JSON**):
`tiles.py` (`Tile`, `TileState`, `TileCondition`), `tile_map.py` (`TileMap`),
`pathfinder.py`, `picking.py`.

Conventions that differ from the prototype (deliberate, clean-arch):
- **Zones seed from the map file's terrain codes**, not procedural rings —
  `b`→BUILDABLE, `c`→COMBAT, `s`→SPAWNING, `f/l/o`→BACKGROUND, `doc.base`
  tile→BUILT. The map file is the source of truth. **Anchoring:** when the map
  carries a `start_area` marker (the editor's 2×2 "Starting Area" object), BOTH
  the playfield window and the 2×2 unlock/section grid anchor at its min corner
  — the marker IS section (0,0). The marker never forces tile states (painted
  terrain wins; the editor warns if its 4 cells aren't `b`). Maps without a
  marker fall back to the legacy base anchoring: playfield at the base corner
  (`base_col/row` .. `dim-1`), section grid offset one row up
  (`_sec_row_origin = base_row-1`) so the hole is the **bottom-left** tile of
  its own section (0,0).
- **Unlock cost is direction-agnostic**: `base_unlock_cost +
  max(0, manhattan_section_distance − 1) * unlock_cost_distance_mod` — sections
  adjacent to the start section cost exactly the base cost, each further
  Manhattan step adds the mod, never below base (the old signed `sc+sr` formula
  went negative left/above the start).
- **Zone changes show on the ground**: `set_tile_state` records the tile's new
  zone code (state→code via `_STATE_CODE`) in `TileMap.terrain_overrides` and
  fires the host-wired `on_zone_change` callable. `game/main.py` feeds the
  overrides to `band_render_items(code_overrides=…)` and wires
  `on_zone_change = ground_cache.invalidate`, so an unlocked chunk renders
  buildable and a backfilled background block renders spawning — WITHOUT
  mutating the shared map doc (a new game builds a fresh TileMap → empty
  overrides → pristine terrain). BUILT/BACKGROUND have no code and never
  write an override.
- **Spawn recede is DUAL-AXIS**: a successful unlock converts the nearest
  SPAWNING 2×2 row-aligned with the bought chunk AND the nearest col-aligned
  one to COMBAT (an axis with no aligned band is skipped — no nearest-overall
  fallback), then backfills the in-playfield BACKGROUND 2×2 CLOSEST to each
  converted block (`_backfill_spawn_nearest` — plain nearest-by-distance, no
  strictly-behind ring rule). Both conversions happen before either backfill
  so the second axis can't re-find the first's block or its fresh backfill.
  Axis alignment is expressed as `_find_2x2` anchor clamp bounds
  (`c_bounds`/`r_bounds`), which also keep a no-match axis search O(strip),
  never O(map).
- **Pathfinding weight is content-key driven, not `isinstance(Building)`**: each
  tile resolves to a key in `map.json` `Pathfinding.content_weights` (empty tiles
  from their zone; occupied tiles carry the key set at placement). Composition
  order is PROTOTYPE-EXACT: base → +condition (`path_weights`) → +defence-range
  coverage → ×damage discount, all gated `0 < w < impassable`.
- **Picking goes through `engine.coords` only** (`screen_to_world` + floor) — no
  iso math in `game/`.
- **Balancing** loads through `game/core/balance.py` (`load_balance(data_dir,
  domain)`, the single validated loader for all five domains — 9D);
  `load_map_balance` is a thin shim over it, kept for the re-export + tests.
  `TileMap(doc, balance)` still takes the dict so tests can inject fixtures.
- **The 10C-era dormant weight hooks are LIVE since 10I**:
  - **Tile conditions roll ONCE at `TileMap.__init__(doc, balance, rng=…)`** per
    `TileConditions.spawn_chances` — every tile EXCEPT BACKGROUND-at-init and the
    starting unlocked pocket incl. the base (both stay GRASS; a receded-into-play
    tile stays GRASS forever, prototype-exact). `rng` is BOTH the on-switch and
    the determinism seam: the host passes module `random` (live) or
    `random.Random(seed)` (tests); **`rng=None` skips the roll entirely** — the
    all-GRASS fixture mode every pre-10I headless test (exact path costs) relies
    on. Conditions never change during a run.
  - `CONDITION_MODIFIER_KEY` (`tiles.py`) is the ONE enum→`TileConditions.
    modifiers` key table every stat-modifier consumer (buildings, enemies, UI
    tooltips) shares. Pond is EXPENSIVE (+9 weight), NOT impassable —
    orchestrator ruling; the "impassable" line in MIGRATION_AGENT_READ_FIRST.md
    is doc drift.
  - Damage-weight reduction: `Session.end_turn` pushes `set_round(round_num)`
    (strict gate — the discount first fires in round `min_round`+1); the
    pathfinder's pre-query refresh recomputes the top-N flags from occupant
    `damage_dealt_last_round` every query.
  - Defence-range coverage: `game/buildings/coverage.py wire_defence_coverage`
    injects `_defence_coverage_fn` + `_defence_range_add` (host, per run). The
    map layer still imports NOTHING from `game.buildings` — it only holds the
    callable.
- Still dormant: the four building-targeting `find_path_*` variants are queried
  by nothing (raider/siege re-path deferred — see `game/enemies/CLAUDE.md`).
- **Edge walls are LIVE (10E)**: `WallEdge` (a `@dataclass`: `col_a/row_a/col_b/
  row_b/hp/max_hp/owner`) + `_wall_key` (order-independent edge key) + a
  `TileMap.wall_edges` registry back `get_wall_between` (the pathfinder's
  `_wall_blocks` reads it; `find_path` routes around live walls,
  `find_path_ignoring_walls` crosses them). A WallBuilder's `on_placed` calls
  `place_walls_for_builder(builder)` — walls go only on the OUTERMOST perimeter
  (player BUILDABLE/BUILT tile edges facing an `_exterior_combat_tiles()` tile, a
  BFS from the spawn zone through COMBAT/SPAWNING only), frozen into the builder's
  snapshot. `remove_walls_for_builder` (dead builder) + `rebuild_walls` (restore
  each alive builder's snapshot to full HP) are driven by the payday slots;
  `damage_wall` (enemy attack) deletes an edge at hp≤0. The map layer stays
  IMPORT-FREE of `game.buildings` — it DUCK-TYPES the builder (`wall_hp()` /
  `wall_snapshot()` / `set_wall_snapshot()` / `building_type` / `alive`), same as it
  already duck-types occupants.
- **Occupancy is occupant-driven and updated incrementally**: a tile with a
  GameObject occupant is mirrored into `engine.physics.TileOccupancy` (BACKGROUND
  impassability is a weight concern, not occupancy). Placement seams
  (`game/buildings/registry.py`) call `occupancy.set` for the single changed tile;
  `TileMap.sync_occupancy(occupancy)` is the full-grid rebuild variant (**not on
  the placement path** — see `game/PERF.md`).

## Perf invariants that live here
Tile-state writes MUST route through `TileMap.set_tile_state` (keeps the
`_by_state` index consistent); `_find_2x2` uses an expanding-window search.
**Base pathfinding is a shared flow field**: `find_path` +
`find_path_ignoring_walls` walk one cached reverse-Dijkstra field
(`pathfinder._build_flow_field` — reverse edges cost the weight of the tile a
forward walker would enter, so field distances equal forward costs exactly),
keyed by `TileMap._path_version`. EVERY weight/blocking mutation must bump the
counter: `set_tile_state`, `set_tile_content` (the ONE occupant/content-key
seam — never write `tile.occupant`/`tile.content_key` directly from outside
the map layer), wall add/remove/death (mid-HP wall hits don't bump —
`_wall_blocks` is hp>0), and the two pre-query weight producers, which
change-detect their flag sets (`_dmg_reduced_prev` / `_defence_covered_prev`)
and bump only on a real difference. Goal-set `find_path_to_nearest_*` variants
stay fresh Dijkstras. Full rationale + measured numbers → `game/PERF.md`.

## Verify
Unlock-chunk fixture asserts receded tiles + costs match prototype; spawn→base
path matches prototype on identical grid:
`py -m unittest discover -s tools/tests -t .`
