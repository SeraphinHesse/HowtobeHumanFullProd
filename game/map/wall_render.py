"""Edge-wall ART as RenderItems, depth-sorted against buildings for real.

``TileMap.wall_edges`` is the map-owned registry of destructible perimeter
``WallEdge``s a WallBuilder raised (see ``game/map/CLAUDE.md``). This module is
the ONE place that turns those edges into RenderItems — the sibling of
``conditions.py``, which does the same job for tile-condition art.

**fix/depth-sorted-world-fills (supersedes fix/wall-render-front-edges)**:
every wall item now draws on the **same** ``entities`` layer as buildings —
NOT split across ``deco``/``terrain`` any more. A prior version tried to
approximate "near walls in front, far walls behind" with a fixed per-side
layer choice; that only works UNIFORMLY (every front wall in front of EVERY
building, regardless of actual position) because the renderer sorts by layer
first (`engine/render/CLAUDE.md`) — a real user-visible bug, since a
back-facing wall segment that is actually NEARER the camera than some
building elsewhere would still draw behind it, unconditionally.

Putting every wall on ``entities`` fixes that for real, because buildings
themselves are positioned at their tile's RAW origin corner for depth-sort
purposes (`Transform(wx=float(col), wy=float(row))`,
`game/buildings/building.py`) — the EXACT SAME anchor `wall_render_items`
already uses (`(edge.col_a, edge.row_a)`). So a wall and a building on
DIFFERENT tiles now sort by the ordinary `wx+wy`/`wy` iso depth rule, exactly
like two buildings already sort against each other — no special-casing
needed, and no possibility of disagreeing with how the rest of the world
already renders.

**The one case this doesn't resolve on its own is a wall and a building
sharing the SAME tile** — their `world_pos` and `layer` are then IDENTICAL, a
genuine depth-sort tie, resolved by Python's stable sort purely on
SUBMISSION ORDER. `game/main.py` is what decides that order (a host/frame
concern, not this module's): it submits the two FAR sides
(``edge_nw``/``edge_ne``, `FRONT_SIDES` below is `False` for these) BEFORE
`world.scene.render_items()` (so a same-tile building draws on top — the
wall is behind, correct: a back wall shouldn't float in front of the
building sitting on it) and the two NEAR sides (``edge_se``/``edge_sw``)
AFTER it (so the wall draws on top — a fence along the near edge of a tile
should occlude the building behind it, the way a real fence would). See
`game/CLAUDE.md`'s host-wiring section for the exact call sites.

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
LAYER = "entities"  # fix/depth-sorted-world-fills: same layer as buildings

#: neighbour delta (d_col, d_row) -> the ``walls`` category animation row that
#: draws the shared edge. See the module docstring for the derivation.
SIDE_OF_DELTA = {
    (1, 0): "edge_se",
    (0, 1): "edge_sw",
    (-1, 0): "edge_nw",
    (0, -1): "edge_ne",
}

#: fix/depth-sorted-world-fills: the two near/bottom sides — PUBLIC so
#: `game/main.py` can split wall submission around `world.scene.render_items()`
#: for correct same-tile tie-breaking (see the module docstring). `edge_nw`/
#: `edge_ne` (the far sides, `animation not in FRONT_SIDES`) go before
#: buildings; these two go after.
FRONT_SIDES = frozenset(("edge_se", "edge_sw"))


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

    **fix/depth-sorted-world-fills**: every item's ``layer`` is the SAME
    constant (``LAYER``, ``"entities"``) regardless of side — depth against
    buildings is resolved by real tile position (the ordinary iso sort), not
    by which side the edge is on. See the module docstring for the one
    remaining case (same-tile ties) and where that's resolved.

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
