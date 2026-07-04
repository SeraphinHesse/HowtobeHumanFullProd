"""Waypoint follow (E-30): a pure step function, no state, no pygame.

Prototype-exact port of ``enemy.py`` ``_do_move``: aim at the current
waypoint; if closer than a threshold, snap exactly onto it and advance to the
next; otherwise take one ``speed * dt`` step along the unit direction. No
overshoot clamp — matching the prototype, a large step may pass the waypoint
and get pulled back next call, then snapped once inside the threshold.
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
    if dist < threshold:
        new_index = index + 1
        reached_end = new_index >= len(waypoints)
        return (tx, ty), new_index, True, reached_end
    step = speed * dt
    return (x + (dx / dist) * step, y + (dy / dist) * step), index, False, False
