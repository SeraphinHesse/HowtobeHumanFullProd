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
  E-30) — pure waypoint step, ported from `enemy.py _do_move` with one
  DELIBERATE divergence: the step is clamped to the remaining distance. Snap
  onto the waypoint and advance the index when within `threshold` OR when
  `speed*dt >= dist` to the waypoint; otherwise step `speed*dt` along the unit
  direction. Without the clamp, a step over `threshold` overshoots and the next
  call walks back onto the waypoint (a visible per-tile reversal), and once the
  step reaches `2*threshold` the unit locks into a permanent two-position
  oscillation with `index` never advancing. The clamp never carries leftover
  distance across multiple waypoints in one call — at most one waypoint is
  consumed per `advance()`, since `PathAgent` (game/enemies/components.py)
  checks the next tile for a blocker/wall once per frame before `Movement`
  runs; skipping several waypoints in one call would let a unit tunnel past a
  check that never happened. Returns `(new_pos, new_index, arrived_this_step,
  reached_end)`.

The `Movement`/`RangeSensor` *components* that wrap these live in `engine/core/`
(they need the GameObject/Component machinery); Scene's `query_area` /
`query_chebyshev` delegate here.

## Verify
Unit tests (grid radius/Chebyshev queries, occupancy, waypoint advance):
`py -m pytest tools/tests/test_<area>.py -q`

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
