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


# -- deco + base (the other undoable map edits, ED-20/ED-24) -----------------

def place_deco(doc, col, row, slot):
    """Cell-snapped deco placement; returns the entry appended."""
    if not _in_bounds(doc, col, row):
        return None
    entry = {"col": col, "row": row, "slot": slot}
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
    spawning tile painted, plus a hole (base) and a camera startpoint. Returns a
    list of labels (empty when nothing is missing)."""
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
    return warnings
