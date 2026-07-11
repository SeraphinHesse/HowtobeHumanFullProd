# CLAUDE.md — engine/physics

Waypoint movement, spatial grid (radius + Chebyshev queries), tile occupancy
(E-30..E-32). You reached here from `engine/CLAUDE.md`. **Deliberately simple —
do not grow forces or collision response without the user asking.** When you
change physics conventions, update THIS doc.

Everything here is pure Python — no pygame — and headless-testable. Generic; **no
game vocabulary** (no "raider", no "tower").

## Primitives
- `SpatialGrid(cell_size=1.0)` (`grid.py`, E-31) — buckets objects by
  `(floor(wx/cell), floor(wy/cell))`; objects expose `obj.transform.world_pos`.
  `insert/remove/move/rebuild`; `query_radius(world_pos, radius)` (Euclidean;
  scans candidate cells then exact-tests) and `query_chebyshev(center_tile,
  range_tiles)` (tile = `(round(wx), round(wy))`, `max(|Δcol|,|Δrow|) <= range`).
  Returns are in **insertion order** (deterministic). Cell membership is fixed at
  insert/rebuild; the exact tests read **live** `world_pos`, so callers keep
  membership fresh via `move()` or a periodic `rebuild()`.
- `TileOccupancy` (`occupancy.py`, E-32) — `(col,row) -> obj`, one occupant per
  tile: `set/clear/get/is_occupied` (tile keys normalized to tuples).
- `advance(pos, waypoints, index, speed, dt, threshold=0.06)` (`movement.py`,
  E-30) — pure waypoint step, prototype-exact (`enemy.py _do_move`): snap onto the
  waypoint and advance the index when within `threshold`, else step `speed*dt`
  along the unit direction (no overshoot clamp). Returns `(new_pos, new_index,
  arrived_this_step, reached_end)`.

The `Movement`/`RangeSensor` *components* that wrap these live in `engine/core/`
(they need the GameObject/Component machinery); Scene's `query_area` /
`query_chebyshev` delegate here.

## Verify
Unit tests (grid radius/Chebyshev queries, occupancy, waypoint advance):
`py -m unittest discover -s tools/tests -t .`
