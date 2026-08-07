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
- **A designer-controlled STAGE counter drives everything, and it outranks the
  implicit recede.** `self._stage` starts at 0 and never decreases. **The only
  thing that advances it is the third painted overlay, `stage_zones`**
  (`{(col, row): stage}` marks on COMBAT tiles, `data/CLAUDE.md`) — NOT the
  number of 2×2s bought. `_unlock_purchases` survives as a raw tally and gates
  nothing. `do_unlock`'s tail, in precedence order:
  1. `_advance_stage(chunk)` takes the MAX stage painted under the bought
     chunk's four tiles; if it exceeds `_stage`, it loops
     `for k in range(_stage + 1, new + 1)` calling `_release_spawn_reserve(k)`
     then `_despawn_spawn_reserve(k)`, sets `_stage = new` and returns True.
     `_release_spawn_reserve(n)` flips every `spawnable_background` mark
     numbered n BACKGROUND → SPAWNING; `_despawn_spawn_reserve(n)` flips every
     `despawnable_spawn` mark numbered n SPAWNING → COMBAT (the released tiles'
     scheduled death, and the reason a designer can hand-author the whole
     band's life cycle). **The ascending catch-up is load-bearing**: a jump from
     stage 2 to 5 fires batches 3, 4 and 5 in order, so nothing painted is ever
     stranded and both mark sets still exhaust on schedule.
  2. `if not advanced and _stage >= _scripted_max` (`max(_reserve_max,
     _despawn_max)` — the stage at or past which no painted mark of EITHER kind
     can fire): `_retire_spawn_reserve()` retires ONE `spawnable_background`
     batch, ascending `n`, per further purchase (`_retire_batches` =
     `sorted(_reserve)`, `_retire_cursor` = how many are spent), flipping that
     batch's cells SPAWNING → COMBAT. The tiles the reserve released die in
     the order they were born. **Only reserve-released cells are eligible** —
     legend-painted `s` tiles are never touched here; the implicit recede
     still owns those.
  3. `elif` the retire batches are spent too **and** `map.json`
     `TileUnlocking.spawn_recede_enabled`: the old dual-axis recede below.
  Consequences worth knowing: `not advanced` keeps the implicit stages off on
  any purchase that moved the designer's stage counter — the designer's
  placement is the whole move; the `elif` means a purchase that retires a batch
  is itself the whole move too; **a map with no marks of ANY of the three kinds
  has `_scripted_max == 0`, an empty `_retire_batches` and `advanced` always
  False, so the guard is true from the first purchase and the `elif` falls
  straight through — behaviour is bit-for-bit what it always was**; and
  `spawn_recede_enabled: false` disables the old rule permanently without
  touching any overlay. `_reserve`/`_despawn` (inverted `stage -> [cells]`) and
  `_stage_zones` (kept FLAT, since its lookup is per-tile) are all built in
  `__init__` by ONE pass over the MARKS (never over the map — the
  O(strip)-never-O(map) rule below). A mark whose tile is not in the expected
  state (the designer repainted over it, an earlier stage claimed it) is skipped
  silently but still counts as fired, so both mark sets and the retire stage
  always exhaust and can never wedge the old rule off forever.
- **Spawn recede is DUAL-AXIS and backfills strictly BEHIND** (the old,
  implicit rule — gated as above): a successful
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
  from their zone; occupied tiles carry the key set at placement — 17 keys total
  since the buildings-overwrite-tileweights rework below: the 4 non-building keys
  plus one per building type, including `painter_building` and the previously
  economy-key-sharing boost/structure leaves). Composition order is
  PROTOTYPE-EXACT: base → +condition (`path_weights`) → +defence-range coverage →
  ×damage discount, all gated `0 < w < impassable` — **except the condition step
  is now itself conditional (buildings-overwrite-tileweights rework)**: a live
  building (`occupant.alive`) whose tile's condition-weight resolution
  OVERWRITES rather than adds (`Tile._overwrites_condition`, an OR of three
  designer-controlled switches — the master `Pathfinding.
  buildings_overwrite_tileweights`, a per-building-type `Pathfinding.
  content_weight_overwrites[content_key]`, or a per-condition `TileConditions.
  path_weight_overwritable[condition]`) skips the `+condition` add entirely, so
  the building's own content weight stands alone (stops the water-parking
  exploit: an economy building on a pond used to cost 1+9 instead of just 1). A
  dead occupant (content_key survives death) reverts to additive. Every dict in
  `_overwrites_condition` is indexed DIRECTLY (no `.get()` default) — a missing
  key fails loud (D-2).
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
  - **Conditions have ART since the terrain layer landed, and it is STATE-DRIVEN
    since the per-state restructuring.** `data/slots.json`'s asset-only
    `conditions` category holds it, restructured so each condition type
    (`Grass`/`Mountain`/`Pond`/`Forest`) is its OWN top-level group, and WITHIN
    each, one leaf child per zone state (`Buildable`/`Built`/`Combat`/
    `Spawning`, 64×96) — `cond_mountain_buildable`, `cond_mountain_built`, …,
    16 slots total. `tiles.py` holds the TWO enum→registry tables this depends
    on: `CONDITION_LABEL` (condition → its top-level group label) and
    `CONDITION_STATE_LABEL` (`TileState.BUILDABLE/BUILT/COMBAT/SPAWNING` →
    their group labels; `BACKGROUND` stays absent — background tiles never get
    condition art, unchanged rule). `Tile.condition_variant_idx` is the stable
    index into whichever state-family is currently active.
    `TileMap.__init__` takes a `registry=` beside `rng=` and stores it
    (`self._registry`) for later: a SECOND pass after the condition roll picks
    each non-BACKGROUND tile's `condition_variant_idx` (sized against its OWN
    INITIAL state's family) and resolves `Tile.condition_slot` from
    `(condition, state, variant_idx)` via the pure `_resolve_condition_slot`
    (`tile_map.py`) — `variant_idx % len(variants)` keeps the index
    well-defined even when a state's pool is smaller (e.g. Spawning starts with
    fewer/no imported variants). **`set_tile_state` re-resolves `condition_slot`
    on EVERY transition** (after its existing zone/terrain-override bookkeeping,
    gated on `self._registry is not None and new_state != BACKGROUND`) at that
    SAME variant index against the new state's family — so a tile's art
    switches LIVE between buildable/built/combat/spawning looks as its zone
    actually changes (a building placed → BUILT, a wave arriving → COMBAT, …),
    never re-rolling which variant, only which state's slot. One accepted side
    effect: a tile that starts `BACKGROUND` (skipped by the initial art roll)
    and later recedes into play via the spawn-band backfill now picks up
    condition art for the first time when `set_tile_state` fires — previously
    such tiles stayed slotless forever. **That second init pass is deliberately
    separate from the roll**: the roll's eligibility rules are prototype-exact
    gameplay every path-cost fixture depends on, whereas ART covers the
    starting pocket too (so imported grass art has no hole where the base
    sits). `registry=None` or `rng=None` ⇒ every slot stays `None` ⇒ nothing
    draws, which is the state every headless
    fixture runs in. Variants roll per tile within a state's own family, so a
    `cond_mountain_buildable_v3` added in the editor grows that pool with NO
    code change (same contract as deco types and enemy eras).
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
  - **Spawn-band tree deco rides the SAME condition-art init pass** (folded in
    on purpose — a third O(map) walk is the explicit perf invariant this
    avoids). `SpawnDeco.tree_chance` (balancing `map` domain) is rolled once
    per tile — including BACKGROUND tiles, since those are exactly what later
    backfills into SPAWNING via spawn recede and nothing re-rolls them at that
    point — into `Tile.spawn_deco_roll`, ONE packed int (`-1` = no tree, else
    `variant_idx * 2 + flip_bit`; no resolved-slot string field, same
    8-bytes-per-tile rationale as `condition_variant_idx`).
    **`spawn_deco.spawn_tree_slots(registry)` is the ONE family definition**,
    and BOTH consumers must go through it: `TileMap` sizes each roll against
    its `len()`, `game/main.py` manifest-filters it for the emitter. Deriving
    it twice is a live trap, not a style nit — the emitter re-bases an
    out-of-range index with `% len`, so a disagreement would silently SKEW the
    variant distribution instead of failing. It reads `data/slots.json`'s
    asset-only `deco` category at group path `("Props", "Tree")`
    (`DECO_CATEGORY`/`SPAWN_DECO_GROUP`, `tiles.py`), minus
    `SPAWN_TREE_EXCLUDED` — an ART call (those variants read wrong at
    spawn-band density) that scopes to the RUNTIME roll only: the excluded
    slots stay first-class `deco` slots the editor offers and hand-placed map
    deco still renders.
    **`spawn_deco.py` is the ONE emitter**, on the **`deco`** layer (above
    `entities` — enemies walk partly behind the treeline) — and unlike
    condition art, it reads `tile.state` **live at emit time** rather than
    caching a resolved slot: a tile only ever draws its tree while
    CURRENTLY `SPAWNING`, so a SPAWNING→COMBAT conversion (spawn recede)
    makes it stop being emitted the very next frame with **no
    `set_tile_state` hook at all** — the roll itself is never touched by a
    zone transition. `rng=None` or `registry=None` ⇒ every roll stays `-1`,
    the same headless-fixture escape hatch condition art uses.
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
  - **Chunk 4 extracted this choose-then-route-then-fallback body into a
    shared `_hunt(tilemap, start_col, start_row, goals, footprint,
    cond_weights)`**, with `nearest_non_base_building_tile` itself thinned
    into a wrapper over the predicate-free `_nearest_goal_tile(goals,
    start_col, start_row)` (kept under its original name — tests reference it
    directly). `find_path_to_nearest_non_base_building` is byte-identical
    through this refactor; `find_path_to_nearest_economic`/`_defence` (below)
    are its two new callers.
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
- **A HUNT IS A PREDICATE OVER `building_type`, nothing more** — the goal set
  is `_goal_tiles(tilemap, predicate)` and the search is the shared `_hunt`
  body below. Every category is ONE module-level frozen-vocabulary set at the
  top of `pathfinder.py`, and a new category is a set + a
  `find_path_to_nearest_*` wrapper + a `_HUNT_QUERIES` row + the `hunts` schema
  enum — **never new pathfinding machinery** (NE-0 is the worked example).
  - `_ECONOMY_BUILDING_TYPES` = `{economic, meditator, painter}`.
  - **`_ATTACK_BUILDING_TYPES` = `{defence, aoe_defence, storm_priest,
    sun_scorcher}`. NE-0/D1 WIDENED `find_path_to_nearest_defence` to this**
    from the single literal `building_type == "defence"`, which had left the
    three later attack buildings invisible to a defence hunter. It is a
    **deliberate, user-approved gameplay change to a LIVE type**, not a
    refactor: `SiegeCannon` ships `hunts: "defence"`, so it hunts all four from
    its unchanged `start_round: 14` onward.
  - **`_STRUCTURE_BUILDING_TYPES` = `{blocker, wall_builder, defence,
    aoe_defence, storm_priest, sun_scorcher}` — the NE-0/D2 `"structure"`
    category** behind the new `find_path_to_nearest_structure` (same shape as
    the defence variant, same `_hunt` body): every non-economy, non-boost,
    non-base building. Written out literally rather than derived from the
    attack set, so a future attack-capable type must be added to BOTH
    deliberately. It ships with **no consumer** (the Digger, NE-2, is the
    first) — landed early on purpose so a predicate mistake surfaces against
    `SiegeCannon`'s existing coverage rather than a brand-new type's.
  - The sets partition the roster exactly: structure ∪ economy ∪ the three
    `boost_*` ∪ `base` is every `BUILDING_TYPE` in `game/buildings`, and
    attack ⊂ structure. `test_pathfinder.TestHuntCategories` asserts both, and
    runs each predicate against the WHOLE roster — so a building type no
    category claims shows up as a failing subtest, not as silent drift.
- **`find_path_to_nearest_economic` / `_defence` are LIVE (Chunk 4 — was
  "dormant, queried by nothing")** — armed via `EnemyTypes.<type>.hunts`
  (`Raider` → `"economic"`, `SiegeCannon` → `"defence"`), dispatched by
  `game/enemies/components.py`'s `_HUNT_QUERIES` (which gained a `"structure"`
  row in NE-0). All three now share the same
  `_hunt` helper `find_path_to_nearest_non_base_building` uses — choose the
  nearest goal by geometric distance, route by weighted cost, multi-goal
  fallback if the chosen one is unreachable, base path if no goal exists at
  all — which is the FIX, not just the activation: before Chunk 4 both went
  straight through `_find_path_to_goals` alone, i.e. picked by cost, so a
  cost-cheaper building (e.g. one not ringed by pond) could beat a
  geometrically-nearer one. See `game/enemies/CLAUDE.md`'s prey-hunting
  section for the per-type wiring.
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
  `wall_snapshot()` / `set_wall_snapshot()` / `building_type` / `alive` /
  `wall_slot()`), same as it already duck-types occupants.
  - **`wall_render.py` is the ONE wall-art emitter** (pure, the `conditions.py`
    sibling): `wall_render_items(tile_map, col_min, col_max, row_min, row_max,
    art_slots, anim_time_ms)` → `RenderItem`s on the **`terrain`** layer, one per
    EDGE, positioned on the PLAYER tile (`(edge.col_a, edge.row_a)` — both
    `place_walls_for_builder` and the `rebuild_walls` snapshot store the player
    tile first; `_wall_key` normalises only the dict KEY, never the dataclass
    fields). Slot = `edge.owner.wall_slot()` (duck-typed); animation row =
    `SIDE_OF_DELTA[(dcol, drow)]`, the `walls` category's four
    `edge_se`/`edge_sw`/`edge_nw`/`edge_ne` rows. Same E-37 `art_slots` gating
    as condition art — an un-imported wall tier emits NOTHING, never a grey X.
    Several edges on one tile emit several items (different animation rows of
    the SAME slot) — a corner tile really is walled on two sides.
    - **It deliberately DIFFERS from `conditions.py` in two ways, both
      load-bearing.** (1) It iterates `tile_map.wall_edges.values()` and filters
      to the window instead of walking the window's tiles: `wall_edges` is
      PERIMETER-sized (tens to low hundreds even on 1024²), so this is strictly
      cheaper than the per-tile scan and still honours the no-full-map-scans
      invariant — do not "fix" it into a grid scan. (2) NO per-cell animation
      phase jitter: a wall is one continuous structure and must animate in
      lockstep, so `anim_time_ms` passes straight through.
    - **`SIDE_OF_DELTA` and `edge_world_points` are DERIVED from
      `engine/coords/system.py`, and the derivation is in the module
      docstring.** With `ix=(wx−wy)·tile_w/2`, `iy=(wx+wy)·tile_h/2`:
      `(+1,0)`=down-right=`edge_se`, `(0,+1)`=down-left=`edge_sw`,
      `(−1,0)`=up-left=`edge_nw`, `(0,−1)`=up-right=`edge_ne`. **The
      prototype's comments call `(0,+1)` "NE" — WRONG for this repo's coord
      authority; never "fix" the table back to it.** `edge_world_points`
      returns the two shared diamond corners in WORLD TILE UNITS (what
      `submit_overlay_lines` consumes), COMPUTED from the delta rather than
      from a second lookup table, so it and `SIDE_OF_DELTA` cannot disagree;
      `None` for a non-adjacent pair.
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
invariant was **ONE Dijkstra per topology change PER FOOTPRINT, never one per
enemy**.

**Chunk 3 (weight profiles) extends the key to `(ignore_walls, footprint,
profile_key)`** — the invariant is now **one Dijkstra per topology change PER
(footprint, weight profile), still never one per enemy**. Every `find_path*`
query takes an optional trailing `cond_weights` (a caller's own `{forest,
mountain, pond}` mapping, e.g. `EnemyTypes.<type>.condition_path_weights`);
`profile_key` is `None`, or the hashable `(forest, mountain, pond)` tuple
`_ensure_flow_field` derives from it for the cache key (a dict is not
hashable, so the tuple — not the dict — is what collapses identical profiles
onto one key). At most a handful of distinct profiles ever exist (one per
enemy type, not one per enemy instance), and every shipped
`condition_path_weights` is seeded equal to the map's own
`TileConditions.path_weights`, so today every type still shares ONE field —
measured: `test_pathfinder.py`'s `TestWeightProfileSharing` spawns two
enemies with identical (default) profiles and asserts the tilemap's
`_flow_cache` holds exactly one entry for their shared `(ignore_walls,
footprint)` pair. EVERY weight/blocking mutation must bump the
counter: `set_tile_state`, `set_tile_content` (the ONE occupant/content-key
seam — never write `tile.occupant`/`tile.content_key` directly from outside
the map layer), wall add/remove/death (mid-HP wall hits don't bump —
`_wall_blocks` is hp>0), and the THREE pre-query weight producers, which
change-detect their flag sets (`_dmg_reduced_prev` / `_defence_covered_prev` /
`_overwrite_prev`) and bump only on a real difference. **`_overwrite_prev`
(buildings-overwrite-tileweights rework) is a NEW hazard, not a cosmetic
addition**: before this rework a building's `content_key` survived its death
untouched, so nothing about a death ever changed its tile's weight and no bump
was needed; now the occupant's `alive` flag is itself part of the weight
calculation (see the weight-composition bullet above), so a building dying
changes its tile's weight and `TileMap.refresh_building_overwrite_flags` —
wired into `pathfinder._pre_query_refresh` via the same guarded `getattr` style
as the other two producers — is what catches it. It short-circuits to a no-op
scan when no overwrite can ever be active under the current balancing (master
switch off, every per-building override off, every per-condition override
off), so a headless fixture with the feature off pays nothing beyond one bool
+ two dict reads. Goal-set `find_path_to_nearest_*` variants stay fresh
Dijkstras. Full rationale + measured numbers → `game/PERF.md`.

## Verify
Unlock-chunk fixture asserts receded tiles + costs match prototype; spawn→base
path matches prototype on identical grid:
`py -m unittest discover -s tools/tests -t .`
