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
  carries a `start_area` marker (the editor's 2×2 "Starting Area" object), the
  2×2 unlock/section grid anchors at its min corner — the marker IS section
  (0,0). The marker never forces tile states (painted terrain wins; the editor
  warns if its 4 cells aren't `b`). Maps without a marker fall back to the
  legacy base anchoring: section grid offset one row up
  (`_sec_row_origin = base_row-1`) so the hole is the **bottom-left** tile of
  its own section (0,0). There is NO playfield window anymore — the old
  quarter-plane window (start corner → map max) blocked every recede left/above
  the start area; the directional backfill rule below does the real filtering.
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
- **Spawn recede is DUAL-AXIS and backfills strictly BEHIND**: a successful
  unlock converts the nearest SPAWNING 2×2 row-aligned with the bought chunk
  AND the nearest col-aligned one to COMBAT (an axis with no aligned band is
  skipped — no nearest-overall fallback), then each converted block backfills
  the nearest BACKGROUND 2×2 strictly behind it (`_backfill_spawn_behind`):
  beyond the block on the recede axis, away from the chunk, anchor pinned to
  the block's own cross-axis anchor — a clean band translation. Nothing
  qualifies behind (map edge) → NO backfill, the band shrinks by one block
  (deliberately no any-background fallback — that's exactly the wrong-side
  placement this rule removes). Both conversions happen before either
  backfill so the second axis can't re-find the first's block or its fresh
  backfill. Axis alignment + behindness are expressed as `_find_2x2` anchor
  clamp bounds (`c_bounds`/`r_bounds`), which also keep every backfill and
  no-match axis search O(strip), never O(map).
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
  - **Conditions have ART since the terrain layer landed.** `data/slots.json`'s
    asset-only `conditions` category (`Terrain` → `Grass`/`Mountain`/`Pond`/
    `Forest`, one leaf group each, 64×96) holds it, and `TileMap.__init__` takes
    a `registry=` beside `rng=`: a SECOND pass after the condition roll assigns
    every non-BACKGROUND tile a `Tile.condition_slot` — a random variant of its
    condition's group, `CONDITION_GROUP` (`tiles.py`) being the ONE enum→group
    table. **That second pass is deliberately separate from the roll**: the
    roll's eligibility rules are prototype-exact gameplay every path-cost
    fixture depends on, whereas ART covers the starting pocket too (so imported
    grass art has no hole where the base sits). `registry=None` or `rng=None` ⇒
    every slot stays `None` ⇒ nothing draws, which is the state every headless
    fixture runs in. Variants roll per tile, so a `cond_mountain_v3` added in
    the editor grows the pool with NO code change (same contract as deco types
    and enemy eras).
  - **`conditions.py` is the ONE emitter** (pure): `condition_render_items(
    tile_map, col_min, col_max, row_min, row_max, art_slots, anim_time_ms)` →
    `RenderItem`s on the **`terrain`** draw layer, which
    `engine.render.LAYERS` places between `ground` and `entities` — condition
    art draws OVER the map tiles and UNDER buildings/enemies/the base/deco.
    Windowed like `engine.tilemap.visible_render_items` (never a full-grid
    per-frame scan) with the same deterministic per-cell animation phase.
    `art_slots` is the host's `{slot: tint_overlay}` map over the condition
    slots that actually have a manifest entry, so an **un-imported condition
    emits nothing rather than a grey X**; `draws_tint(slot, art)` — the shared
    predicate `game/ui/overlays.py` calls — then keeps drawing the flat colour
    diamond for exactly those tiles (plus any slot whose entry opts back in via
    `tint_overlay`). Both consumers read the SAME map, so a sprite and its tint
    can never disagree about what exists. **Perf note:** this is one RenderItem
    per visible tile WITH art, every frame — importing grass art puts the whole
    visible window on the layer. Measure before shipping grass art;
    `GroundCache` cannot absorb it (scroll-fill needs an opaque `bg_color`).
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
- **`find_path_to_nearest_non_base_building` is the boss's query (BP-2 / D2)** —
  the goal set is every alive building whose `building_type != "base"` (the same
  duck-typed occupant contract the rest of the module reads, never a
  `base_col`/`base_row` comparison), falling back to `find_path` when the board
  is clear. `find_path_to_nearest_building` cannot serve: its predicate is
  `lambda b: True`, so the base is IN the goal set, and
  `content_weights.base_building` is **0** — cheaper than any real building
  (1–2), so the search walked the boss past its prey and onto the hole.
  - **`nearest_non_base_building_tile` chooses by geometric DISTANCE; the route
    to it stays the weighted `_dijkstra` (D3).** Cost and distance are different
    questions and one search cannot answer both: terrain, defence-range coverage
    and the damage discount all bend the cost field, so the cost-nearest building
    can be across the map from the player's "nearest". If the chosen victim is
    unreachable, one multi-goal search finds any other reachable one before we
    fall back to the base — a walled-off building can never send the boss home
    early.
- **`_dijkstra` keeps a SEPARATE tentative-`best` map, and that is load-bearing**
  (same reason `_build_flow_field` does — its docstring has the long version).
  It used to guard the relax on `dist`, the **settled** map: `dist.get(node)` is
  `inf` for anything not yet settled, so *every* relaxation passed and a later,
  worse one would overwrite `prev` with a worse parent. The goal still settled at
  the right cost — the heap pops in order — but `_reconstruct` then walked the
  clobbered back-pointers and returned a route that was **not** the one Dijkstra
  costed (measured: a 23-cost path to a goal already reached at cost 12, doubling
  back through a pond). Every goal-set variant runs through here, so this was a
  real part of the boss's "wandering". Pinned by
  `test_pathfinder.TestDijkstraReturnsTheRouteItCosted`, which compares the
  returned path's cost against an independent settle-only Dijkstra over 40 random
  pond boards.
- Still dormant: `find_path_to_nearest_economic` / `_defence` are queried by
  nothing (raider/siege re-path deferred — see `game/enemies/CLAUDE.md`).
- **`find_path_to_nearest_spawn(tilemap, start_col, start_row, footprint=1)`
  is the kidnapper's route home (Art/enemies)** — goal set is every
  `tilemap.spawning_tiles()`, `[]` when there is none / none reachable (the
  carrier despawns on the spot in that case; see `game/enemies/CLAUDE.md`).
  **`ignore_walls=True` is deliberate**: a carrier is inert
  (`PathAgent.carrying` — no blocker/wall scan, no re-path), so a wall it
  cannot break must never be able to trap it; buildings are traversable
  weights, never `impassable_weight`, so a live occupant cannot trap it
  either. A fresh `_dijkstra` like every other goal-set variant, **NOT**
  flow-field backed: a kidnap fires at most once per building kill, well
  inside the one-Dijkstra-per-topology-change invariant below — it does not
  need its own cached field.
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

## Footprints — the N×N block convention (ER-2)
Every `find_path*` (and `_dijkstra`) takes a trailing `footprint` (N, default
**1**). `pathfinder.py` holds the ONE definition — `block_tiles`,
`block_covers`, `internal_edges`, `face_edges`, `block_passable`, `block_weight`
are **public** because `game/enemies` (`components.py`, `spawner.py`) imports
them; never re-derive the rules anywhere else.
- **Anchor = the block's MIN corner.** A size-N unit at `(c,r)` occupies
  `{(c+i, r+j) | 0 ≤ i,j < N}` — the body extends **right and down**. Same
  convention as `_find_2x2`, the `start_area` marker and unlock chunks; it is
  the only one that works for an even N (no centre tile) and keeps every
  coordinate an integer. Paths, waypoints and spawn tiles are all **anchors**.
- **Passable** = every block tile in bounds and under `impassable_weight`, AND
  (unless `ignore_walls`) no live wall on an **internal** edge of the block. A
  **step** to a 4-adjacent anchor additionally clears the whole leading **face**
  (N edges, not one). `face_edges` is symmetric in its two anchors, so the
  forward `_dijkstra` and the reverse `_build_flow_field` share it and their
  edge rules stay identical (the flow-field equivalence proof depends on that).
- **Entering a block costs `max(weight)` under the body** — a 2×2 avoids a pond
  even if only one of its four tiles is the pond.
- **A goal is reached when the block COVERS it**, not when the anchor sits on
  it: the field is seeded at every base-covering anchor and `_dijkstra` expands
  its goal set the same way. A 2×2 beside the hole IS on the hole. (Requiring it
  to *anchor* on the base would strand every 2×2 whenever the block at the base
  is not clear — which no map guarantees.)
- **N = 1 collapses every rule to its pre-ER-2 expression** (block = the tile, no
  internal edges, face = the single crossed edge, block weight = tile weight,
  goal set = the goal), so the single-tile path is unchanged. **This is a PERF
  contract, not just a semantic one:** `_dijkstra` / `_build_flow_field` hoist
  their loop invariants and take an inline `single = footprint == 1` branch, so
  at footprint 1 they do exactly the pre-ER-2 work — one `get`, one `weight`, one
  `_wall_blocks` per edge. Calling the block helpers per node/edge instead
  (they allocate a `block_tiles`/`face_edges` list and re-read the
  `impassable_weight` property) made a 300×300 rebuild **2.1× slower at
  footprint 1**. Do not "simplify" that branch away.
- **Seeding is multi-source and `best` MUST be pre-seeded to 0.** For N>1 the
  covering anchors are 4-adjacent to each other, so without it the first seed
  popped relaxes its siblings and writes a back-pointer into itself — their
  `dist` still settles to 0, but the bogus `next_step` survives and a unit that
  already covers the base walks on to the lex-min covering anchor instead of
  stopping.
- Footprints are a **pathfinding** property only (D5): enemies never enter
  `TileOccupancy` and do not block each other.

## Perf invariants that live here
Tile-state writes MUST route through `TileMap.set_tile_state` (keeps the
`_by_state` index consistent); `_find_2x2` uses an expanding-window search.
**Base pathfinding is a shared flow field**: `find_path` +
`find_path_ignoring_walls` walk one cached reverse-Dijkstra field
(`pathfinder._build_flow_field` — reverse edges cost the weight of the *block* a
forward walker would enter, so field distances equal forward costs exactly),
keyed by `TileMap._path_version`. Since ER-2 the field is **footprint-aware**
and the per-version cache is keyed on **`(ignore_walls, footprint)`** — so the
invariant is now **ONE Dijkstra per topology change PER FOOTPRINT, never one per
enemy**. EVERY weight/blocking mutation must bump the
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
