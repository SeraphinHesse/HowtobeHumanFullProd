"""Tile-condition ART as RenderItems on the ``terrain`` draw layer.

Conditions (grass/mountain/pond/forest) roll once per tile at
``TileMap.__init__``, which also picks each tile's art slot
(``Tile.condition_slot``) from the ``conditions`` slot category. This module is
the ONE place that turns those slots into RenderItems.

Why its own layer: condition art must draw ABOVE the base map tiles (the
``ground`` layer, which the game composites through ``GroundCache``) and BELOW
buildings, enemies, the base and deco. ``engine.render.LAYERS`` names that
position ``terrain``, between ``ground`` and ``entities``.

Windowed by construction, mirroring ``engine.tilemap.visible_render_items`` —
a large map must never pay a full-grid scan per frame (the `game/PERF.md`
invariant). Pure Python — no pygame.
"""
from engine.render.item import RenderItem

from .tiles import TileState

LAYER = "terrain"


def condition_render_items(tile_map, col_min, col_max, row_min, row_max,
                           art_slots, anim_time_ms=0, column=None):
    """Condition-art RenderItems for the tiles inside a visible tile window.

    ``art_slots`` is the set of condition slot keys that actually HAVE imported
    art (the host derives it from the asset manifest). A tile whose slot is
    absent from it emits nothing — an un-imported condition draws no sprite at
    all rather than the engine's grey-X placeholder, and `game/ui/overlays.py`
    keeps drawing its colour diamond for that tile instead.

    A ``SPAWNING`` tile never emits condition art — enemies spawn there and
    the condition tint/sprite would otherwise show through the spawn band.
    The tile keeps its rolled ``condition`` (pathfinding weight is
    unaffected); this is a render-only skip, so the art resumes the instant
    the tile converts to ``COMBAT`` (spawn recede), the same live-state
    pattern ``game/map/spawn_deco.py`` uses for its tree emitter.

    ``anim_time_ms`` feeds idle animation; a deterministic per-cell phase is
    added so identical neighbouring tiles don't animate in lockstep (the same
    rule, and the same constants, as the deco branch of
    ``engine.tilemap.visible_render_items``).

    ``column`` is an OPAQUE master-sheet column passed straight through onto
    every emitted item — this emitter reads no run state and gives the value
    no meaning. ``None`` (the default) means "no live column", leaving each
    slot's stored column in charge; ``0`` is a REAL column, not "unset", so
    the value is never tested for truthiness.
    """
    if not art_slots:
        return []
    items = []
    r0 = max(0, row_min)
    r1 = min(tile_map.rows, row_max + 1)
    c0 = max(0, col_min)
    c1 = min(tile_map.cols, col_max + 1)
    for row in range(r0, r1):
        for col in range(c0, c1):
            tile = tile_map.get(col, row)
            if tile is None or tile.state == TileState.SPAWNING:
                continue
            slot = tile.condition_slot
            if slot is None or slot not in art_slots:
                continue
            phase = (col * 131 + row * 197) % 997   # ms, deterministic & pure
            items.append(RenderItem(slot, (col, row), layer=LAYER,
                                    anim_time_ms=anim_time_ms + phase,
                                    column=column))
    return items


def draws_tint(condition_slot, condition_art):
    """Whether the flat colour diamond should still be drawn for a tile.

    ``condition_art`` is the host's ``{slot_key: tint_overlay}`` map over the
    condition slots that have a manifest entry. Two cases draw it: the tile's
    slot has no art at all (so the sprite would be a grey X — there IS no
    sprite), or its entry explicitly asks for the tint under the art. Both
    consumers (this predicate and ``condition_render_items``) read the SAME
    map, so a sprite and its tint can never disagree about what exists.
    """
    if condition_slot is None:
        return True
    return condition_art.get(condition_slot, True)
