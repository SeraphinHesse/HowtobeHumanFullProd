# game/PERF.md — Large-map performance playbook

The full rationale behind the large-map perf INVARIANTS listed in
`game/CLAUDE.md`. These are the hard-won fixes that let a **1024×1024** map (~1M
tiles) run at full fps. The router carries the one-line rules; this file carries
the "why" and the measured numbers. Touch any of the hot paths below → re-read the
matching section here first.

Cross-engine: the ground cache mechanics live in `engine/render/CLAUDE.md`; the
tilemap emitters (`visible_render_items` / `band_render_items`) in
`engine/CLAUDE.md`.

## Tile-state index — THE static-camera large-map fix
`TileMap` keeps an incremental `_by_state` index (`{TileState: set()}`), so
`built_tiles()`/`buildable_tiles()`/`spawning_tiles()` are **O(result)**, not a
full `rows×cols` scan. This is what fixed a 1024² map running at ~2 fps *even with
a static camera* (and in the editor's Play): the in-round HUD (`game/ui/hud.py`)
calls those queries several times **per frame** (income breakdown + tile counter),
which on a 1024² map was ~4 full-map scans × ~1M cells ≈ **630 ms/frame**
(measured) — dwarfing all render cost. The editor's map *viewport* builds no
`TileMap` and has no HUD, so it never paid this (it rendered the same map at
~20 fps), which is what isolated the cause.

**INVARIANT: every tile-state write goes through `TileMap.set_tile_state`** (the
only place `_by_state` is kept consistent) — `do_unlock`, spawn recede, building
placement (`game/buildings/registry.py`), and the base seed all route through it.
`Tile.state` stays a plain `__slots__` attribute so *reads* (the pathfinding hot
path) pay no property overhead; only writes are routed. A consistency unit test
(`test_tile_unlock.TestStateIndexConsistency`) pins the index == a brute-force
scan across seed/unlock/recede.

## Event-driven full-map scans removed (large-map hitch cleanup)
Two routine-play actions used to scan all ~1M tiles on a 1024² map (a
multi-hundred-ms freeze each), now O(local):
- **Placement occupancy is incremental** — `place_building`/`attach_base`
  (`game/buildings/registry.py`) call `occupancy.set((col,row), building)` for the
  one tile that changed instead of the full-map `TileMap.sync_occupancy` scan.
  `sync_occupancy` is kept only as a from-scratch full rebuild (not on the
  placement path). Buildings are add-only in the current phases, so a single-tile
  `set` is exact; a remove/sell seam would `occupancy.clear` its tile likewise.
- **`TileMap._find_2x2` (spawn-recede on unlock) uses an expanding-window
  search** — the nearest matching 2×2 is almost always a few tiles from the
  reference, so it scans a doubling Chebyshev window (`_scan_2x2` inner) and
  accepts only once the window provably contains the global nearest (`best_d ≤
  (radius−2)²`), with the whole-map window as the terminating fallback. Output is
  byte-identical to the old full scan (same nearest-by-squared-distance pick, same
  first-row-major tie-break, same `min_ring`); pinned by
  `test_tile_unlock.TestFind2x2WindowedMatchesFullScan` (40×40 map vs an inlined
  brute-force oracle) plus the existing exact recede-coordinate tests.

## Shared base flow field — per-spawn pathfinding fixed (DONE)
`Enemy.on_spawn` used to run a full `find_path` Dijkstra to the base **per
enemy** (O(reachable tiles) each) — the dominant cost when hundreds of enemies
spawn on a huge map, felt as per-spawn stutter that worsened late in big waves
(the spawn ramp packs spawns closer together). Now `find_path` AND
`find_path_ignoring_walls` walk ONE shared reverse-Dijkstra **flow field**
(`game/map/pathfinder.py _build_flow_field`): a single Dijkstra seeded at the
base expands outward over the TRANSPOSED edge graph, and each query is an
O(path-length) walk down the resulting next-step tree.
- **Reverse edge-cost trick (the equivalence proof):** a forward path pays the
  weight of every tile it ENTERS after the start (the start tile is free), so
  in reverse, relaxing neighbour `v` from a settled `u` costs `weight(u)` — the
  tile a forward walker enters when stepping v→u. Edge rules stay byte-identical
  to `_dijkstra` (4-connectivity, `_wall_blocks`, the `w >= impassable` skip),
  making a node's field distance exactly its forward start→base cost. An
  impassable tile may hold a distance (a spawn can start on one) but never
  expands.
- **Invalidation:** the field caches on the `TileMap` keyed by its
  `_path_version` counter; **every weight/blocking mutation MUST bump it** (a
  stale cached path is a correctness bug). Bumpers: `set_tile_state` (zone
  changes: unlock/recede/placement), `set_tile_content` (the ONE
  occupant/content-key seam — placement, base attach, tile freeing), wall
  add/remove/death (`place_walls_for_builder` / `remove_walls_for_builder` /
  `rebuild_walls` recreations / `damage_wall` only on the hp≤0 delete — mid-HP
  hits don't change `_wall_blocks`), and the two pre-query weight producers
  (`refresh_damage_weight_reductions` / `refresh_defence_range_coverage`) which
  now change-detect their flag sets and bump only on an actual difference — so
  `set_round` and coverage churn invalidate exactly when they change weights.
- **Producing the coverage set is cached too, not just mirroring it.**
  Change-detecting the flag set stops the *invalidation* churn, but the
  producer (`game/buildings/coverage.py`) still ran before every query — one
  per enemy spawn, hundreds in a boss round — re-expanding each defender's r²
  Chebyshev square and re-allocating the whole set, only for the mirror to
  compare it away. The wired callable now computes a cheap **signature** first
  (O(built defenders): the toggle plus each contributor's tile + raw range, no
  r² expansion, no set arithmetic) and re-expands only when that moves,
  otherwise returning the SAME set object — which
  `refresh_defence_range_coverage` short-circuits on identity, skipping its
  copy and compare as well. Measured on a 40×20 board with 60 defenders / 540
  covered tiles: 300 queries 77 ms → 25 ms. The signature deliberately does
  NOT ride `_path_version` — a building *death* does not reliably bump it
  (`refresh_building_overwrite_flags` short-circuits when the
  buildings-overwrite feature is off), and a dead defender must stop covering.
  The residual cost is the O(built tiles) scan the other two pre-query
  producers already pay, so coverage is no longer the outlier among them.
- **Both base variants ride the field** (walls-respecting + walls-ignoring,
  cached side by side): when the player walls in the base, EVERY spawn takes
  the ignoring-walls fallback, so it must not stay a per-enemy Dijkstra. With
  no walls the two builds are the same search, keeping the variants byte-equal
  (a 9C test pins that). The goal-set variants (`find_path_to_nearest_*`) stay
  fresh forward searches — ~one boss per wave — and their base-path fallback
  rides the field automatically. `spawn_death_swarm`'s burst also reuses it.
- Pinned by `test_flow_field` (forward-equivalence on mixed weights + walls,
  one-build cache reuse, invalidation through every mutation seam) plus the
  existing exact-cost path tests running unchanged on the field.

### Weight profiles (Chunk 3) — the cache key grows a third component
Every `EnemyTypes.<type>` block now carries its own `condition_path_weights`
(`{forest, mountain, pond}`), threaded through every `find_path*` query as an
optional trailing `cond_weights` (`None` = the map's own
`TileConditions.path_weights`, today's byte-identical default). This is a
PER-TYPE profile, not per-instance — so it could in principle balloon the
flow-field cache from one field to "one per enemy type", which would violate
the invariant above if types diverged freely. Two things keep it from doing
so:
- **The cache key is `(ignore_walls, footprint, profile_key)`**, where
  `profile_key` is `None` or the hashable `(forest, mountain, pond)` tuple
  `_ensure_flow_field` derives from `cond_weights` (a dict is not hashable, so
  the tuple — not the dict — is what two callers with numerically identical
  profiles collapse onto: they hash and compare equal even though they are
  different dict objects).
- **Every shipped profile is seeded IDENTICAL to the map default**
  (forest 1 / mountain 2 / pond 9, matching `map.json`'s
  `TileConditions.path_weights`) — so today, despite five enemy types each
  carrying their own copy of the knob, every one of them still shares exactly
  ONE cached field. **Measured, not assumed**:
  `test_pathfinder.py::TestWeightProfileSharing` spawns two enemies (a
  Standard and a Raider — different `hunts`, identical `condition_path_
  weights`) on the same tilemap and asserts `tilemap._flow_cache[1]` holds
  exactly one entry for the `(False, 1)` `(ignore_walls, footprint)` pair
  they both query, after both have triggered `find_path`/the hunt query at
  least once.
- **The bound on distinct fields is "number of distinct
  `condition_path_weights` profiles a designer actually authors" (at most
  one per enemy TYPE — five today), never "number of enemies on the board"**
  — a wave of 300 raiders sharing one `Raider.condition_path_weights` still
  pays for exactly one Raider-profile field, built once and reused by every
  raider in the wave (and, since the seed matches the map default, that one
  field is itself the SAME field the walkers/siege/boss already share). A
  future retune that diverges one type's weights from another's adds at most
  one more field, still O(distinct profiles), not O(enemies).

## Targeting rides the spatial grid
Defender target acquisition used to be a full scan of every live enemy, run once
per defender per frame in BOTH acquisition sites (`_update_defender` and
`_update_beam`, `game/enemies/combat.py`) — O(defenders × enemies) `_chebyshev`
calls plus a fresh list per defender — while `Scene`'s `SpatialGrid` sat there
with **zero query call sites in `game/`**. Both sites now share one primitive,
`_acquire`, which asks the grid.

- **The query widens, then re-filters.** The grid measures ANCHOR-tile to
  centre-tile; `_chebyshev` measures NEAREST-BLOCK-TILE to centre-tile (ER-2), and
  a footprint block only ever extends *away* from its anchor. So anchor distance ≤
  block distance + `span` (`span = N−1` for the widest footprint on the board,
  maxed once per frame, not per defender): query at `rng + span`, then let
  `_chebyshev` drop the extra candidates. **The resulting set and its ORDER are
  identical to the old scan** — the grid returns insertion order, which is scene
  spawn order, which is what `by_tag("enemy")` gave — and that is load-bearing,
  because the `min`(nearest)/`max`(highest-HP) acquisition tiebreaks resolve ties
  by first-seen. Pinned against a brute-force oracle over a sweep of centres and
  ranges by `test_combat_anchors.TestAcquireMatchesFullScan`.
- **The per-frame `offsets` map doubles as the membership test.** The grid hands
  back buildings, projectiles and corpses too; anything not keyed in `offsets` is
  not a live targetable enemy, so the dead/untargetable filter costs a dict hit
  rather than a second pass.
- **`_GRID_ACQUIRE_MIN_ENEMIES = 64` — below it, the scan still wins.** A query
  walks every CELL its range box touches whether or not anything sits there, so
  its floor is set by `rng`, not by enemy count. Measured crossover is between 50
  and 100 enemies, so small waves keep the code path they had.
- **`Scene`'s grid is `SpatialGrid(cell_size=2.0)`, not the class default 1.0.**
  One cell per tile made a range-5 query ~144 dict lookups — worse than the scan
  at every realistic count. Two tiles per cell (~36) measured fastest-or-tied
  from 20 to 600 objects. Pure perf knob: same results, same order.
- **Measured** (corridor spread, 1×1 footprints, `rng` 5, best of 3 × 150 frames,
  per frame, scan → grid): 20 enemies/10 defenders 0.086 → 0.090 ms (same code
  path, noise); 100/30 1.29 → 1.23; 200/40 3.36 → 3.07; 300/50 **7.7 → 5.1**;
  600/50 **14.1 → 8.7**.
- The grid is rebuilt lazily (`Scene._ensure_grid`), so this costs ONE O(objects)
  rebuild per in-round frame no matter how many defenders query it, and nothing at
  all on frames with no combat.

## Large-map GC
A big map builds one `Tile` per cell (a 1024² map = ~1M long-lived objects). Left
alone, Python's cyclic GC periodically walks that whole static grid (an 80–140 ms
stall that *scales with map size*). After each `build_gameplay` the host calls
`gc.collect(); gc.freeze()` (helper `freeze_static`) to move the tile grid into a
permanent generation the collector never re-scans, so a collection costs <1 ms at
any map size; `teardown_gameplay` calls `gc.unfreeze()` first so the old world can
be reclaimed. **Gated to windowed runs** (`tune_gc = max_frames is None`) —
headless tests/smoke re-boot `main()` in-process and must not have GC state
mutated. `game/map` `Tile` carries `__slots__` for the same reason (memory: ~3×
smaller per tile).

## Ground cache (the panning fix)
The static terrain is no longer re-blitted tile-by-tile each frame. The host
builds `engine.render.ground_cache.GroundCache(cs, assets, bg_color=BACKGROUND)`
and, in the world/PAUSED render branch, calls `ground_cache.ensure(view_w,
view_h, <band emitter>)` + `ground_cache.blit(window)` FIRST, then submits base +
deco (`visible_render_items(..., terrain=False)`) + entities + UI over it. The
`ensure` callback is the iso-diagonal band emitter `lambda dmn,dmx,smn,smx:
tilemap.band_render_items(map_doc, dmn,dmx,smn,smx)` (NOT `visible_render_items` —
the cache repaints thin diagonal scroll strips; see `engine/render/CLAUDE.md`).
In-game terrain never mutates at runtime (unlock/recede change runtime zone state,
not `map_doc.terrain`; highlights are overlay-layer), so no `invalidate()` is
needed. The cache SCROLLS on pan and repaints only the exposed edge, so panning
cost tracks pan speed, not map size — a 1024² map that used to drop to ~2 fps while
panning (every margin-cross triggered a ~70 ms full recomposite) now stays smooth
(headless: ~6–14 ms/frame at 1024² zoom 1, independent of map size).

## Frame-timing HUD
Windowed runs print `sim/submit/world/hud/composite/present` avg ms beside the
fps line (gated on `tune_gc`, so headless stays silent) — the on-hardware
measure of where a frame goes. G4 split the old single `flush` bucket, which
hid the HUD's share inside the world's:
- `world` / `hud` come from `renderer.last_flush_ms`, i.e. the two backend
  calls `Renderer.flush(target, hud_target=…)` makes. On the Surface path the
  HUD rides the single call and `hud` reads 0.0.
- `composite` is the GPU path's HUD-texture upload + draw (0.0 on Surface).
- `present` replaces `flip`: `pygame.display.flip()` or `Renderer.present()`.

## Two render backends (`--backend`, G4)
`game/main.py` routes every frame-target touch point through one host-side
"presenter": `_SurfacePresenter` is the historical `pygame.SCALED` display
Surface verbatim, `_GpuPresenter` is a standalone `pygame._sdl2` Window +
`Renderer(window, target_texture=True)` drawing through
`engine.render.backend_gpu` with `GroundCacheGpu`, and the Surface-drawn HUD
composited over it as ONE streaming-`Texture` upload per frame.
- `py game/main.py --backend={auto,gpu,surface}`; default `auto` (try GPU, fall
  back). `HTBH_RENDER_BACKEND` is consulted only when there is no flag (the
  frozen exe gets no argv). An unrecognised value exits loud.
- **A headless run (`max_frames is not None`) forces the Surface path** unless
  `gpu` was asked for explicitly — that one condition is why `tools/smoke.py`
  and the boot tests need no flag of their own.
- Any failure building the window/renderer/HUD texture/ground-cache targets
  logs one line and falls back to the WHOLE Surface stack (D8) — never a hard
  failure, never a hybrid.
- **F12** saves the live frame to `build/capture_<backend>_<stamp>.png` (after
  the HUD composite, before present), so a GPU/Surface pair of PNGs can be
  compared pixel for pixel.
