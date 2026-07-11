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

## Next known large-map frontier — per-spawn pathfinding (NOT yet done)
`Enemy.on_spawn` runs a full `find_path` Dijkstra to the base **per enemy**
(`game/enemies/enemy.py`), which is O(reachable tiles) — the dominant cost when
hundreds of enemies spawn on a huge map (staggered, so a per-spawn micro-hitch,
not a sustained fps drop). The intended fix is a single shared reverse-Dijkstra
"flow field" from the base, recomputed once per wave / map-topology change and
reused by every enemy, instead of one Dijkstra per spawn. Left for a dedicated
pass — it touches path-equivalence, the wall hook, and the goal-set variants.

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
Windowed runs print `sim/submit/flush/flip` avg ms beside the fps line (gated on
`tune_gc`, so headless stays silent) — the on-hardware measure of where a frame
goes.
