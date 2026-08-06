"""Pure tilemap paint operations (ED-20) — no Qt, no pygame, no disk.

Every mutating op edits doc.terrain IN PLACE and returns the change list
[(col, row, old_code, new_code), ...] with out-of-bounds cells and no-op
writes dropped — exactly the shape the undo commands consume (one command
per stroke, ED-24). Cell math is plain grid arithmetic; SCREEN→cell
picking stays in the viewport via engine.coords (E-3) — nothing here may
do iso math.

The *_cells generators are exported separately so the viewport can ghost
a pending line/rect without mutating the document.
"""
import string


def _in_bounds(doc, col, row):
    return 0 <= col < doc.cols and 0 <= row < doc.rows


def _set(doc, col, row, code, changes):
    if not _in_bounds(doc, col, row):
        return
    old = doc.terrain[row][col]
    if old == code:
        return
    doc.terrain[row][col] = code
    changes.append((col, row, old, code))


def paint(doc, col, row, code):
    changes = []
    _set(doc, col, row, code, changes)
    return changes


def line_cells(c0, r0, c1, r1):
    """Bresenham cells from (c0,r0) to (c1,r1), inclusive."""
    cells = []
    dc, dr = abs(c1 - c0), -abs(r1 - r0)
    sc = 1 if c0 < c1 else -1
    sr = 1 if r0 < r1 else -1
    err = dc + dr
    col, row = c0, r0
    while True:
        cells.append((col, row))
        if (col, row) == (c1, r1):
            return cells
        e2 = 2 * err
        if e2 >= dr:
            err += dr
            col += sc
        if e2 <= dc:
            err += dc
            row += sr


def rect_cells(c0, r0, c1, r1):
    """All cells of the normalized inclusive rectangle (ED-20 rect FILL)."""
    lo_c, hi_c = sorted((c0, c1))
    lo_r, hi_r = sorted((r0, r1))
    return [(c, r) for r in range(lo_r, hi_r + 1) for c in range(lo_c, hi_c + 1)]


def line(doc, c0, r0, c1, r1, code):
    changes = []
    for col, row in line_cells(c0, r0, c1, r1):
        _set(doc, col, row, code, changes)
    return changes


def rect_fill(doc, c0, r0, c1, r1, code):
    changes = []
    for col, row in rect_cells(c0, r0, c1, r1):
        _set(doc, col, row, code, changes)
    return changes


def bucket_fill(doc, col, row, code):
    """4-connected flood fill of the region sharing the start cell's code."""
    if not _in_bounds(doc, col, row):
        return []
    target = doc.terrain[row][col]
    if target == code:
        return []
    changes = []
    stack = [(col, row)]
    while stack:
        c, r = stack.pop()
        if not _in_bounds(doc, c, r) or doc.terrain[r][c] != target:
            continue
        _set(doc, c, r, code, changes)
        stack.extend(((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)))
    return changes


def pick(doc, col, row):
    """Eyedropper: the code under the cell, or None outside the grid."""
    return doc.terrain[row][col] if _in_bounds(doc, col, row) else None


def apply_changes(doc, changes, reverse=False):
    """Re-apply (redo) or roll back (undo) a change list — set-to-value
    writes, so re-applying over live-painted cells is idempotent."""
    if reverse:
        for col, row, old, _new in reversed(changes):
            doc.terrain[row][col] = old
    else:
        for col, row, _old, new in changes:
            doc.terrain[row][col] = new


# -- spawn reserve: the INVISIBLE spawnable-background overlay ---------------
# Direct mirrors of the terrain paint ops above, over doc.spawnable_background
# ({(col, row): stage}) instead of doc.terrain. The change tuple keeps the
# same (col, row, old, new) shape — old/new are the STAGE NUMBER or None
# ("no mark here") — so the undo command is the exact twin of _StrokeCommand.
# A mark is an overlay, never a legend code: the underlying terrain keeps
# drawing and the game never sees it as a tile kind.

def _set_reserve(doc, col, row, n, changes):
    if not _in_bounds(doc, col, row):
        return
    old = doc.spawnable_background.get((col, row))
    if old == n:
        return
    if n is None:
        doc.spawnable_background.pop((col, row), None)
    else:
        doc.spawnable_background[(col, row)] = n
    changes.append((col, row, old, n))


def set_reserve(doc, col, row, n):
    """Mark the cell for release at stage n; ``n=None`` erases."""
    changes = []
    _set_reserve(doc, col, row, n, changes)
    return changes


def reserve_line(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in line_cells(c0, r0, c1, r1):
        _set_reserve(doc, col, row, n, changes)
    return changes


def reserve_rect(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in rect_cells(c0, r0, c1, r1):
        _set_reserve(doc, col, row, n, changes)
    return changes


def reserve_bucket(doc, col, row, n):
    """4-connected flood fill of the region sharing the start cell's UNDERLYING
    TERRAIN CODE — not the region sharing a mark. Marking a whole painted
    background patch in one gesture is what a designer means by "bucket" here,
    and the marks themselves are usually empty (nothing to flood).

    Unlike bucket_fill, the terrain is never mutated, so the visited set is
    what terminates the walk."""
    if not _in_bounds(doc, col, row):
        return []
    target = doc.terrain[row][col]
    changes = []
    seen = set()
    stack = [(col, row)]
    while stack:
        c, r = stack.pop()
        if (c, r) in seen or not _in_bounds(doc, c, r) \
                or doc.terrain[r][c] != target:
            continue
        seen.add((c, r))
        _set_reserve(doc, c, r, n, changes)
        stack.extend(((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)))
    return changes


def pick_reserve(doc, col, row):
    """Eyedropper: the stage number marked on the cell, or None (no mark /
    outside the grid)."""
    return doc.spawnable_background.get((col, row)) if _in_bounds(doc, col, row) \
        else None


def apply_reserve_changes(doc, changes, reverse=False):
    """Re-apply (redo) or roll back (undo) a reserve change list — set-to-value
    writes (None removes the key), so re-applying over live-painted marks is
    idempotent. Mirrors apply_changes."""
    if reverse:
        steps = ((col, row, old) for col, row, old, _new in reversed(changes))
    else:
        steps = ((col, row, new) for col, row, _old, new in changes)
    for col, row, value in steps:
        if value is None:
            doc.spawnable_background.pop((col, row), None)
        else:
            doc.spawnable_background[(col, row)] = value


# -- spawn despawn: the INVISIBLE despawnable-spawn overlay ------------------
# The exact twin of the spawn-reserve ops above, over doc.despawnable_spawn
# ({(col, row): stage}) instead of doc.spawnable_background. Same
# (col, row, old, new) change tuple, old/new the STAGE NUMBER or None.
# A mark is an overlay, never a legend code: the underlying SPAWNING tile keeps
# drawing, and the runtime flips every cell numbered n from SPAWNING to COMBAT
# when the run's stage counter reaches n.

def _set_despawn(doc, col, row, n, changes):
    if not _in_bounds(doc, col, row):
        return
    old = doc.despawnable_spawn.get((col, row))
    if old == n:
        return
    if n is None:
        doc.despawnable_spawn.pop((col, row), None)
    else:
        doc.despawnable_spawn[(col, row)] = n
    changes.append((col, row, old, n))


def set_despawn(doc, col, row, n):
    """Mark the cell for retirement at stage n; ``n=None`` erases."""
    changes = []
    _set_despawn(doc, col, row, n, changes)
    return changes


def despawn_line(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in line_cells(c0, r0, c1, r1):
        _set_despawn(doc, col, row, n, changes)
    return changes


def despawn_rect(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in rect_cells(c0, r0, c1, r1):
        _set_despawn(doc, col, row, n, changes)
    return changes


def despawn_bucket(doc, col, row, n):
    """4-connected flood fill of the region sharing the start cell's UNDERLYING
    TERRAIN CODE — not the region sharing a mark; the exact mirror of
    reserve_bucket (marking a whole painted spawn patch in one gesture).

    Unlike bucket_fill, the terrain is never mutated, so the visited set is
    what terminates the walk."""
    if not _in_bounds(doc, col, row):
        return []
    target = doc.terrain[row][col]
    changes = []
    seen = set()
    stack = [(col, row)]
    while stack:
        c, r = stack.pop()
        if (c, r) in seen or not _in_bounds(doc, c, r) \
                or doc.terrain[r][c] != target:
            continue
        seen.add((c, r))
        _set_despawn(doc, c, r, n, changes)
        stack.extend(((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)))
    return changes


def pick_despawn(doc, col, row):
    """Eyedropper: the stage number marked on the cell, or None (no mark /
    outside the grid)."""
    return doc.despawnable_spawn.get((col, row)) if _in_bounds(doc, col, row) \
        else None


def apply_despawn_changes(doc, changes, reverse=False):
    """Re-apply (redo) or roll back (undo) a despawn change list — set-to-value
    writes (None removes the key), so re-applying over live-painted marks is
    idempotent. Mirrors apply_reserve_changes."""
    if reverse:
        steps = ((col, row, old) for col, row, old, _new in reversed(changes))
    else:
        steps = ((col, row, new) for col, row, _old, new in changes)
    for col, row, value in steps:
        if value is None:
            doc.despawnable_spawn.pop((col, row), None)
        else:
            doc.despawnable_spawn[(col, row)] = value


# -- stage zones: the INVISIBLE stage-advance overlay ------------------------
# The third overlay of the same shape, over doc.stage_zones
# ({(col, row): stage}). Same (col, row, old, new) change tuple, old/new the
# STAGE NUMBER or None. A mark is an overlay, never a legend code: the
# underlying COMBAT tile keeps drawing, and buying a 2×2 that intersects the
# painted set advances the run's stage counter to the HIGHEST number among the
# four bought tiles — the only thing that ever advances it, and therefore the
# only thing that fires the spawnable_background / despawnable_spawn batches.

def _set_stage(doc, col, row, n, changes):
    if not _in_bounds(doc, col, row):
        return
    old = doc.stage_zones.get((col, row))
    if old == n:
        return
    if n is None:
        doc.stage_zones.pop((col, row), None)
    else:
        doc.stage_zones[(col, row)] = n
    changes.append((col, row, old, n))


def set_stage(doc, col, row, n):
    """Mark the cell as advancing the run to stage n; ``n=None`` erases."""
    changes = []
    _set_stage(doc, col, row, n, changes)
    return changes


def stage_line(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in line_cells(c0, r0, c1, r1):
        _set_stage(doc, col, row, n, changes)
    return changes


def stage_rect(doc, c0, r0, c1, r1, n):
    changes = []
    for col, row in rect_cells(c0, r0, c1, r1):
        _set_stage(doc, col, row, n, changes)
    return changes


def stage_bucket(doc, col, row, n):
    """4-connected flood fill of the region sharing the start cell's UNDERLYING
    TERRAIN CODE — not the region sharing a mark; the exact mirror of
    reserve_bucket / despawn_bucket (marking a whole painted combat patch in
    one gesture).

    Unlike bucket_fill, the terrain is never mutated, so the visited set is
    what terminates the walk."""
    if not _in_bounds(doc, col, row):
        return []
    target = doc.terrain[row][col]
    changes = []
    seen = set()
    stack = [(col, row)]
    while stack:
        c, r = stack.pop()
        if (c, r) in seen or not _in_bounds(doc, c, r) \
                or doc.terrain[r][c] != target:
            continue
        seen.add((c, r))
        _set_stage(doc, c, r, n, changes)
        stack.extend(((c + 1, r), (c - 1, r), (c, r + 1), (c, r - 1)))
    return changes


def pick_stage(doc, col, row):
    """Eyedropper: the stage number marked on the cell, or None (no mark /
    outside the grid)."""
    return doc.stage_zones.get((col, row)) if _in_bounds(doc, col, row) \
        else None


def apply_stage_changes(doc, changes, reverse=False):
    """Re-apply (redo) or roll back (undo) a stage-zone change list —
    set-to-value writes (None removes the key), so re-applying over
    live-painted marks is idempotent. Mirrors apply_despawn_changes."""
    if reverse:
        steps = ((col, row, old) for col, row, old, _new in reversed(changes))
    else:
        steps = ((col, row, new) for col, row, _old, new in changes)
    for col, row, value in steps:
        if value is None:
            doc.stage_zones.pop((col, row), None)
        else:
            doc.stage_zones[(col, row)] = value


# -- deco + base (the other undoable map edits, ED-20/ED-24) -----------------

def place_deco(doc, col, row, slot, flip=False):
    """Cell-snapped deco placement; returns the entry appended. `flip` mirrors
    the prop horizontally; unset (the default) produces an entry byte-identical
    to a map with no flipped decos (the "flip" key is omitted, not written as
    False)."""
    if not _in_bounds(doc, col, row):
        return None
    entry = {"col": col, "row": row, "slot": slot}
    if flip:
        entry["flip"] = True
    doc.deco.append(entry)
    return entry


def top_deco_index(doc, col, row):
    """Index of the most recently placed deco on the cell, or None — a
    pure peek so the undo command can own the actual pop."""
    for i in range(len(doc.deco) - 1, -1, -1):
        if doc.deco[i]["col"] == col and doc.deco[i]["row"] == row:
            return i
    return None


def remove_top_deco(doc, col, row):
    """Remove the most recently placed deco on the cell; (index, entry) or
    None — the index lets undo re-insert at the exact position."""
    i = top_deco_index(doc, col, row)
    return None if i is None else (i, doc.deco.pop(i))


def move_base(doc, col, row):
    """Reposition the base; returns (old_col, old_row) or None for a no-op
    (same cell / out of bounds / no base). Kept for the drag path."""
    if not _in_bounds(doc, col, row) or doc.base is None:
        return None
    old = (doc.base["col"], doc.base["row"])
    if old == (col, row):
        return None
    doc.base["col"], doc.base["row"] = col, row
    return old


def move_camera(doc, col, row):
    """Reposition the camera startpoint; returns (old_col, old_row) or None for
    a no-op (same cell / out of bounds / no startpoint). Mirrors move_base."""
    if not _in_bounds(doc, col, row) or doc.camera_start is None:
        return None
    old = (doc.camera_start["col"], doc.camera_start["row"])
    if old == (col, row):
        return None
    doc.camera_start["col"], doc.camera_start["row"] = col, row
    return old


# -- background-legend growth + map-requirement warnings (ED-20 follow-up) ----

def next_free_code(legend):
    """Lowest single-char terrain code (a-z then 0-9) not already in the
    legend — the code a new background type claims. Raises if exhausted."""
    for ch in string.ascii_lowercase + string.digits:
        if ch not in legend:
            return ch
    raise ValueError("no free single-char legend code left")


# (zone slot, warning label) — the const-pinned zone slots a playable map needs
# at least one of. Derived-by-slot (not hardcoded b/c/s codes) so it survives a
# legend that renamed the codes.
_REQUIRED_ZONE_SLOTS = (
    ("tile_buildable", "buildable tile"),
    ("tile_combat", "combat tile"),
    ("tile_spawning", "spawning tile"),
)


def map_requirement_warnings(doc):
    """What the map is missing to be playable — the editor's non-blocking yellow
    Set-Active warning. A playable map needs at least one buildable, combat and
    spawning tile painted, plus a hole (base), a camera startpoint and a 2×2
    starting area — and the starting area's four cells must be painted
    buildable (the marker anchors the game's unlock grid but never forces tile
    states: painted terrain wins).

    Two further NON-BLOCKING labels cover the spawnable-background reserve:
    the map carrying no marks at all, and a mark sitting on a ZONE code
    (legend ``checker: true``) — the runtime only flips BACKGROUND tiles, so
    a mark on a zone tile is a silent no-op the designer should see.

    Two more mirror them for the despawnable-spawn overlay: no marks at all,
    and a mark sitting on a code that is not a SPAWNING tile (slot
    ``tile_spawning``) — flipping SPAWNING → COMBAT is meaningless anywhere
    else, so such a mark is a silent no-op too. The predicate is deliberately
    NARROWER than the reserve's ``checker`` test: this mark belongs on spawn
    tiles specifically, not on any zone tile.

    Two more mirror them again for the stage-zone overlay: no marks at all,
    and a mark sitting on a code that is not a COMBAT tile (slot
    ``tile_combat``) — the stage only ever advances when the player buys a 2×2
    intersecting a painted COMBAT area, so such a mark is a silent no-op too.
    The predicate is the ``tile_spawning`` one with the slot swapped, NOT the
    reserve's ``checker`` test.

    Returns a list of labels (empty when nothing is missing)."""
    codes_by_slot = {}
    for code, entry in doc.legend.items():
        codes_by_slot.setdefault(entry["slot"], set()).add(code)
    used = set()
    for row in doc.terrain:
        used.update(row)
    warnings = [label for slot, label in _REQUIRED_ZONE_SLOTS
                if not (codes_by_slot.get(slot, set()) & used)]
    if doc.base is None:
        warnings.append("hole")
    if doc.camera_start is None:
        warnings.append("camera startpoint")
    if doc.start_area is None:
        warnings.append("starting area")
    else:
        buildable_codes = codes_by_slot.get("tile_buildable", set())
        covered = (doc.terrain[doc.start_area["row"] + dr]
                   [doc.start_area["col"] + dc]
                   for dr in range(2) for dc in range(2))
        if any(code not in buildable_codes for code in covered):
            warnings.append("buildable tiles under starting area")
    if not doc.spawnable_background:
        warnings.append("spawnable background tiles")
    else:
        zone_codes = {code for code, entry in doc.legend.items()
                      if entry["checker"]}
        if any(doc.terrain[row][col] in zone_codes
               for (col, row) in doc.spawnable_background
               if _in_bounds(doc, col, row)):
            warnings.append("spawnable background on non-background tiles")
    if not doc.despawnable_spawn:
        warnings.append("despawnable spawn tiles")
    else:
        spawn_codes = codes_by_slot.get("tile_spawning", set())
        if any(doc.terrain[row][col] not in spawn_codes
               for (col, row) in doc.despawnable_spawn
               if _in_bounds(doc, col, row)):
            warnings.append("despawnable spawn on non-spawn tiles")
    if not doc.stage_zones:
        warnings.append("stage zone tiles")
    else:
        combat_codes = codes_by_slot.get("tile_combat", set())
        if any(doc.terrain[row][col] not in combat_codes
               for (col, row) in doc.stage_zones
               if _in_bounds(doc, col, row)):
            warnings.append("stage zones on non-combat tiles")
    return warnings
