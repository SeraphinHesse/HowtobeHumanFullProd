# CLAUDE.md — game/map (Phase 9C)

Runtime tile layer + pathfinder. You reached here from `game/CLAUDE.md`. Ports the
prototype's `src/map/*` behaviour. When you change map-runtime conventions, update
THIS doc.

Runtime layer over an `engine.tilemap.TileMapDoc` (**never re-parse map JSON**):
`tiles.py` (`Tile`, `TileState`, `TileCondition`), `tile_map.py` (`TileMap`),
`pathfinder.py`, `picking.py`.

Conventions that differ from the prototype (deliberate, clean-arch):
- **Zones seed from the map file's terrain codes**, not procedural rings —
  `b`→BUILDABLE, `c`→COMBAT, `s`→SPAWNING, `f/l/o`→BACKGROUND, `doc.base`
  tile→BUILT. The map file is the source of truth. The playfield window anchors
  at the base corner (`base_col/row` .. `dim-1`); the 2×2 unlock/section grid is
  offset one row up from that (`_sec_row_origin = base_row-1`) so the hole is the
  **bottom-left** tile of its own section (0,0), not the top-left corner.
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
- **Dormant hooks, ported but fed neutral** until their producers land: tile
  conditions (all GRASS → +0, random roll in **10I**), damage-weight reduction
  (`set_round`/`refresh_damage_weight_reductions` present, no building damage yet,
  **10F**), defence-range coverage (`_defence_coverage_fn`=None, add value from the
  *buildings* domain, **10I**), and the four building-targeting `find_path_*`
  variants (goal by occupant `building_type`; no occupants yet → all fall back to
  `find_path`).
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
`_by_state` index consistent); `_find_2x2` uses an expanding-window search. Full
rationale + measured numbers → `game/PERF.md`.

## Verify
Unlock-chunk fixture asserts receded tiles + costs match prototype; spawn→base
path matches prototype on identical grid:
`py -m unittest discover -s tools/tests -t .`
