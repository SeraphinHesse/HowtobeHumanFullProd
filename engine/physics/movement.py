"""Waypoint follow (E-30): a pure step function, no state, no pygame.

Ported from ``enemy.py`` ``_do_move``, with one DELIBERATE divergence from the
prototype: the step is clamped to the remaining distance to the waypoint.
Without the clamp, a step longer than `threshold` overshoots and the next
call walks BACK onto the waypoint — a visible per-tile reversal — and once
the step reaches `2 * threshold` the unit locks into a permanent
two-position oscillation, making zero progress forever (this is what
happens to fast units, e.g. raiders, on low/variable frame rates or at 2x
combat speed). The clamp aims at the current waypoint; if closer than
`threshold`, or if this step would reach or pass it, it snaps exactly onto
it and advances to the next waypoint; otherwise it takes one `speed * dt`
step along the unit direction.

The clamp never carries leftover distance over into a second waypoint
within the same call — at most one waypoint is consumed per `advance()`.
`PathAgent` (game/enemies/components.py) runs once per frame before
`Movement` and decides whether the *next* tile is blocked; skipping several
waypoints in one call would let a unit tunnel past a blocker or wall that
was never checked. That "one waypoint per frame" cap is a safety property,
not an oversight, and the clamp preserves it.
"""
import math

DEFAULT_THRESHOLD = 0.06  # tiles; prototype uses <2 px on a 32 px tile pitch


def advance(pos, waypoints, index, speed, dt, threshold=DEFAULT_THRESHOLD):
    """Advance one step along `waypoints`.

    Returns ``(new_pos, new_index, arrived_this_step, reached_end)``:
      - new_pos: (x, y) after this step.
      - new_index: index of the waypoint now being pursued.
      - arrived_this_step: True if a waypoint was snapped onto this call.
      - reached_end: True once the final waypoint has been reached (or when
        there is nothing left to follow).
    """
    x, y = pos
    if not waypoints or index >= len(waypoints):
        return (x, y), index, False, True
    tx, ty = waypoints[index]
    dx = tx - x
    dy = ty - y
    dist = math.hypot(dx, dy)
    step = speed * dt
    # Snap when we are already close enough OR when this step would reach or
    # pass the waypoint. The second clause is the overshoot clamp: without it a
    # step longer than `threshold` lands beyond the waypoint and the next call
    # walks BACK to it — a visible per-tile reversal, and a permanent
    # two-position oscillation once the step reaches 2*threshold.
    if dist < threshold or step >= dist:
        new_index = index + 1
        reached_end = new_index >= len(waypoints)
        return (tx, ty), new_index, True, reached_end
    return (x + (dx / dist) * step, y + (dy / dist) * step), index, False, False
