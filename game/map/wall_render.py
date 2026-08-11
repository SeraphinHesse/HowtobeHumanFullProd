"""Edge-wall ART as RenderItems on the ``terrain`` draw layer.

``TileMap.wall_edges`` is the map-owned registry of destructible perimeter
``WallEdge``s a WallBuilder raised (see ``game/map/CLAUDE.md``). This module is
the ONE place that turns those edges into RenderItems — the sibling of
``conditions.py``, which does the same job for tile-condition art.

Why its own layer: like condition art, a wall must draw ABOVE the base map tiles
(the ``ground`` layer the game composites through ``GroundCache``) and BELOW
buildings, enemies, the base and deco. ``engine.render.LAYERS`` names that
position ``terrain``, between ``ground`` and ``entities``.

Windowed like ``conditions.py`` / ``engine.tilemap.visible_render_items`` — but
by a DIFFERENT mechanism, and that is deliberate. ``conditions.py`` walks the
window's tiles; this module iterates ``tile_map.wall_edges.values()`` and filters
each edge against the window. ``wall_edges`` is PERIMETER-sized (tens to low
hundreds of entries, even on a 1024² map), so iterating it is strictly cheaper
than the per-tile walk, and it still honours `game/PERF.md`'s "no full-map scans"
invariant. **Do not "fix" this into a grid scan to match ``conditions.py``.**

Also unlike ``conditions.py``: no per-cell animation phase jitter. Condition art
jitters so identical neighbouring tiles don't animate in lockstep; a wall is one
continuous structure and SHOULD animate in lockstep, so ``anim_time_ms`` is
passed straight through.

Pure Python — no pygame.

The delta -> side table and the edge geometry below are DERIVED from the coord
authority (``engine/coords/system.py``), not guessed. Recorded here so nobody
re-derives them wrong:

  ``ix = (wx - wy) * tile_w/2``, ``iy = (wx + wy) * tile_h/2``, with
  ``world_pos = (col, row)``. So, on screen, a neighbour delta of

      (+1,  0) moves DOWN-RIGHT  -> ``edge_se``
      ( 0, +1) moves DOWN-LEFT   -> ``edge_sw``
      (-1,  0) moves UP-LEFT     -> ``edge_nw``
      ( 0, -1) moves UP-RIGHT    -> ``edge_ne``

  **The prototype's comments called ``(0, +1)`` "NE". That is WRONG for this
  repo's coord authority** — it is the SOUTH-WEST edge here. Do not "fix" the
  table back to the prototype's naming.

  Tile ``(c, r)``'s diamond has four world-space corners:
  top ``(c, r)`` · right ``(c+1, r)`` · bottom ``(c+1, r+1)`` · left ``(c, r+1)``.
  The two corners an edge shares with its neighbour therefore are:

      edge_se -> ((c+1, r),   (c+1, r+1))    right -> bottom
      edge_sw -> ((c,   r+1), (c+1, r+1))    left  -> bottom
      edge_nw -> ((c,   r),   (c,   r+1))    top   -> left
      edge_ne -> ((c,   r),   (c+1, r))      top   -> right

  ``edge_world_points`` COMPUTES those from the delta rather than carrying a
  second lookup table, so it and ``SIDE_OF_DELTA`` can never disagree. The points
  are in WORLD TILE UNITS — what ``Renderer.submit_overlay_lines`` consumes (it
  converts through ``engine.coords`` at flush).
"""
from engine.render.item import RenderItem

WALL_CATEGORY = "walls"
LAYER = "terrain"

#: neighbour delta (d_col, d_row) -> the ``walls`` category animation row that
#: draws the shared edge. See the module docstring for the derivation.
SIDE_OF_DELTA = {
    (1, 0): "edge_se",
    (0, 1): "edge_sw",
    (-1, 0): "edge_nw",
    (0, -1): "edge_ne",
}


def edge_world_points(col_a, row_a, col_b, row_b):
    """The two WORLD-space diamond corners tile A shares with its neighbour B.

    Returns a 2-tuple of ``(wx, wy)`` world tile-unit points (the units
    ``Renderer.submit_overlay_lines`` takes), or ``None`` when the two tiles are
    not 4-adjacent — a wall only ever sits on a shared edge, so a non-adjacent
    pair has no edge to return.

    Derived from the delta, never from a lookup table: tile ``(c, r)``'s corners
    are top ``(c, r)``, right ``(c+1, r)``, bottom ``(c+1, r+1)``, left
    ``(c, r+1)``, and the shared pair is the two of them on B's side.
    """
    delta = (col_b - col_a, row_b - row_a)
    if delta not in SIDE_OF_DELTA:
        return None
    c, r = col_a, row_a
    top, right, bottom, left = (c, r), (c + 1, r), (c + 1, r + 1), (c, r + 1)
    d_col, d_row = delta
    # +col => the two corners with the larger col (right, bottom); -col => the
    # smaller-col pair (top, left). Likewise +row => (left, bottom),
    # -row => (top, right). One branch per axis, so the table above IS this.
    if d_col:
        return (right, bottom) if d_col > 0 else (top, left)
    return (left, bottom) if d_row > 0 else (top, right)


def wall_render_items(tile_map, col_min, col_max, row_min, row_max, art_slots,
                      anim_time_ms=0):
    """Wall-art RenderItems for the edges inside a visible tile window.

    ``art_slots`` is the set of ``walls`` slot keys that actually HAVE imported
    art (the host derives it from the asset manifest). An edge whose slot is
    absent from it emits NOTHING — an un-imported wall tier draws no sprite at
    all rather than the engine's grey-X placeholder (E-37, the same rule
    ``conditions.py`` applies to condition art).

    One item per EDGE, positioned on the PLAYER tile (``(edge.col_a, edge.row_a)``
    — ``place_walls_for_builder`` and the ``rebuild_walls`` snapshot both store
    the player tile first; ``_wall_key`` normalises only the dict KEY, never the
    dataclass fields), with the shared-edge side as the animation row. A tile
    carrying several walls therefore emits several items — different animation
    rows of the SAME slot. That is CORRECT: a corner tile really is walled on two
    sides.

    An owner without a ``wall_slot()`` method emits nothing rather than raising
    (headless fixtures own edges with stub builders).

    **Wall-era-art feature**: an owner's optional ``wall_era_slot()`` (the
    FROZEN era-specific key — see ``game/buildings/structure.py``) is tried
    FIRST; whenever it has no imported art yet (absent from ``art_slots``, or
    the owner carries no such method at all — e.g. headless test stubs), this
    falls back to ``wall_slot()`` exactly as before. Never a special case for
    "no era stamped": ``wall_era_slot()`` itself returns ``None`` then, which
    is simply never in ``art_slots``.
    """
    if not art_slots:
        return []
    items = []
    for edge in tile_map.wall_edges.values():
        col, row = edge.col_a, edge.row_a
        if not (col_min <= col <= col_max and row_min <= row <= row_max):
            continue
        animation = SIDE_OF_DELTA.get((edge.col_b - col, edge.row_b - row))
        if animation is None:
            continue                      # not a 4-adjacent edge: nothing to draw
        wall_slot = getattr(edge.owner, "wall_slot", None)
        if wall_slot is None:
            continue                      # stub/duck-typed owner without art
        wall_era_slot = getattr(edge.owner, "wall_era_slot", None)
        era_slot_key = wall_era_slot() if wall_era_slot is not None else None
        slot_key = era_slot_key if era_slot_key in art_slots else wall_slot()
        if slot_key not in art_slots:
            continue
        items.append(RenderItem(slot_key, (col, row), layer=LAYER,
                                animation=animation,
                                anim_time_ms=anim_time_ms))
    return items
