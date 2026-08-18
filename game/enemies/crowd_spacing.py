"""Tile-crowding visual offset (feature) — Standard/Walker and Raider.

When 2+ SAME-TYPE enemies genuinely share a tile (not just briefly crossing
paths), they ease into small evenly-spread positions instead of drawing
stacked on top of each other. A Raider and a Standard sharing a tile never
share a layout — each type groups only with its own kind, and each has its
own independently-tuned ``data/balancing/enemies.json`` ``CrowdSpacing.<Type>``
block (dwell threshold, offset magnitude, ease time, max slots).

This is a REAL position offset — it is written into the same
``Transform.wx/wy`` combat/range-gating reads, a deliberate user decision
accepting that target-selection tiebreaks and mortar splash checks are
measurably (if very slightly) affected. See ``game/enemies/CLAUDE.md``'s
"Crowd spacing" section for the full design rationale, including why a naive
per-frame nudge would fight ``Movement``.

State lives in the declared ``CrowdSpacing`` component (E-11); the LOGIC is
two pure, host-called functions — the ``DeathSpawn`` / ``Enemy.
advance_second_phase`` / ``Spawner._advance_second_phases`` split applied
here, because grouping enemies by tile is naturally a single O(N) pass over
the whole enemy list, not something each enemy's own ``Component.update()``
should redo independently (that would be O(N^2) — Standard/Walker is the
single most common enemy type and can run into the hundreds, unlike the 1-4
``DrummerAura`` instances that scan-per-instance is fine for).

Frame order (``game/main.py``, mirroring the documented ``pre_sim ->
scene.update -> resolve_combat -> post_sim`` sequence):

    restore_crowd_positions(scene)      # BEFORE scene.update
    scene.update(sim_dt)                # Movement steps from the clean,
                                         # un-offset position this restores
    apply_crowd_spacing(scene, sim_dt, crowd_balance)   # AFTER scene.update,
                                         # BEFORE resolve_combat
    resolve_combat(...)
"""
from engine.core import Component

# Anchor layouts: fractions of a type's own `max_offset_tiles`, one row per
# occupant count (2..6), chosen in WORLD space so they read as clean
# horizontal/vertical spacing on SCREEN under the iso projection
# (ix = (dx-dy)*half_w, iy = (dx+dy)*half_h) — e.g. (1,-1) is pure
# screen-horizontal, (1,1) is pure screen-vertical. No entry exceeds +/-1.0
# on either axis; the balancing schema's `max_offset_tiles` maximum (0.4)
# relies on that to guarantee an offset enemy never rounds into a
# neighboring tile (a tile owns wx/wy in [c-0.5, c+0.5)). MAX_TABLE_SIZE is
# this table's own ceiling — the schema's `max_slots` bound (2-6) can never
# ask for a layout this module doesn't define.
ANCHOR_TABLE = {
    2: [(1.0, -1.0), (-1.0, 1.0)],
    3: [(0.0, -1.0), (1.0, 0.5), (-1.0, 0.5)],
    4: [(1.0, -1.0), (-1.0, 1.0), (1.0, 1.0), (-1.0, -1.0)],
    5: [(0.85, -0.85), (-0.85, 0.85), (0.85, 0.85), (-0.85, -0.85), (0.0, 0.0)],
    6: [(-1.0, -0.6), (0.0, -1.0), (1.0, -0.6),
        (-1.0, 0.6), (0.0, 1.0), (1.0, 0.6)],
}
MAX_TABLE_SIZE = 6


class CrowdSpacing(Component):
    """Declared state only (E-11) — no ``update()``; the logic lives in the
    two module functions below, called once per frame from ``game/main.py``.

    * ``base_wx``/``base_wy`` — the clean, un-offset (path-following)
      position. ``-1.0`` is the "not yet seeded" sentinel (the
      ``PathAgent.target_col/_row`` -1-sentinel precedent), since a real
      world position is always >= 0.
    * ``dwell_time`` — seconds this enemy has continuously held
      ``dwell_tile_col``/``dwell_tile_row``. Resets to 0 the moment its
      rounded tile changes.
    * ``offset_dx``/``offset_dy`` — the current EASED visual offset (world
      tile units), added onto ``base_wx``/``base_wy`` to produce the drawn
      (and combat-visible) position.

    Carries no per-type identity of its own — ``_crowd_group_key`` derives
    which ``CrowdSpacing.<Type>`` balancing block an enemy reads from its
    OWN class (``STAT_SUBTREE``), not from a field here, so every type
    carrying this component uses the identical constructor.
    """

    base_wx: float = -1.0
    base_wy: float = -1.0
    dwell_time: float = 0.0
    dwell_tile_col: int = -1
    dwell_tile_row: int = -1
    offset_dx: float = 0.0
    offset_dy: float = 0.0


def _crowd_group_key(enemy):
    """The ``CrowdSpacing.<key>`` balancing group this enemy's type reads.

    Reuses ``Enemy.STAT_SUBTREE`` (already the ``EnemyTypes.<key>`` lookup
    path every type's stats resolve through) rather than a second, parallel
    type -> key table that could silently drift from it."""
    return type(enemy).STAT_SUBTREE[-1]


def restore_crowd_positions(scene):
    """Undo last frame's crowd offset BEFORE ``scene.update`` runs, so
    ``Movement`` steps from the clean path position rather than compounding
    the offset into the enemy's actual route. First-ever call for an enemy
    (``base_wx < 0``) seeds the base position from its current transform and
    leaves it alone — there is nothing to undo yet."""
    for enemy in scene.by_tag("enemy"):
        cs = enemy.get_component(CrowdSpacing)
        if cs is None:
            continue
        transform = enemy.transform
        if cs.base_wx < 0.0:
            cs.base_wx, cs.base_wy = transform.wx, transform.wy
        else:
            transform.wx, transform.wy = cs.base_wx, cs.base_wy


def apply_crowd_spacing(scene, dt, crowd_balance):
    """One O(N) pass, called AFTER ``scene.update`` and BEFORE
    ``resolve_combat`` — so combat's range gate, target-selection tiebreak
    and mortar splash all see the same final offset position this writes,
    per the user's explicit sign-off on a real (not render-only) offset.

    ``crowd_balance`` is the full ``data/balancing/enemies.json``
    ``CrowdSpacing`` block (one sub-block per type, e.g. ``Standard``/
    ``Raider``) — each enemy reads only its OWN type's sub-block, so a
    Raider and a Standard sharing a tile never share a slot layout even
    though both may be crowding independently at once."""
    members = []
    groups = {}
    for enemy in scene.by_tag("enemy"):
        cs = enemy.get_component(CrowdSpacing)
        if cs is None:
            continue
        group_key = _crowd_group_key(enemy)
        transform = enemy.transform
        base_wx, base_wy = transform.wx, transform.wy
        tile = (round(base_wx), round(base_wy))
        if tile != (cs.dwell_tile_col, cs.dwell_tile_row):
            cs.dwell_tile_col, cs.dwell_tile_row = tile
            cs.dwell_time = 0.0
        else:
            cs.dwell_time += dt
        groups.setdefault((tile, group_key), []).append(enemy)
        members.append((enemy, cs, group_key, base_wx, base_wy))

    targets = {}
    for (_tile, group_key), group in groups.items():
        settings = crowd_balance[group_key]
        dwell_threshold = float(settings["dwell_threshold_seconds"])
        max_offset = float(settings["max_offset_tiles"])
        max_slots = int(settings["max_slots"])
        eligible = [e for e in group
                   if e.get_component(CrowdSpacing).dwell_time >= dwell_threshold]
        if len(eligible) < 2:
            continue
        eligible.sort(key=lambda e: e.id)
        table_n = min(len(eligible), max_slots)
        layout = ANCHOR_TABLE[table_n]
        for index, enemy in enumerate(eligible):
            slot = min(index, table_n - 1)
            fx, fy = layout[slot]
            targets[enemy.id] = (fx * max_offset, fy * max_offset)

    for enemy, cs, group_key, base_wx, base_wy in members:
        ease_seconds = float(crowd_balance[group_key]["offset_ease_seconds"])
        ease_rate = min(1.0, dt / ease_seconds) if ease_seconds > 0.0 else 1.0
        target_dx, target_dy = targets.get(enemy.id, (0.0, 0.0))
        cs.offset_dx += (target_dx - cs.offset_dx) * ease_rate
        cs.offset_dy += (target_dy - cs.offset_dy) * ease_rate
        transform = enemy.transform
        transform.wx = base_wx + cs.offset_dx
        transform.wy = base_wy + cs.offset_dy
        cs.base_wx, cs.base_wy = base_wx, base_wy
