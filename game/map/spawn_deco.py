"""Spawn-band tree deco as RenderItems on the ``deco`` draw layer.

A tree identity (variant + orientation) rolls once per tile at
``TileMap.__init__`` (``SpawnDeco.tree_chance``, folded into the condition-art
pass — see ``tile_map.py``), packed into ``Tile.spawn_deco_roll`` (-1 = no
tree). This module is the ONE place that turns that roll into RenderItems, and
it is the ONLY thing deciding whether a tile's tree actually draws right now:
it reads ``tile.state`` LIVE, so a tile that converts SPAWNING -> COMBAT
(spawn recede) simply stops being emitted the very next frame — no
``set_tile_state`` hook needed, unlike condition art's re-resolve.

Why the ``deco`` layer: a treeline should partly occlude enemies walking out
of it, and ``engine.render.LAYERS`` places ``deco`` (index 3) above
``entities`` (index 2, enemies + buildings) — `depth_key` makes the layer the
PRIMARY sort key, so this is the entire z-order fix, no per-item tuning.

Windowed by construction, mirroring ``conditions.py``/
``engine.tilemap.visible_render_items`` — cost is bounded by the viewport, not
by how large a spawn zone a designer paints. Pure Python — no pygame.
"""
from engine.render.item import RenderItem
from .tiles import DECO_CATEGORY, SPAWN_DECO_GROUP, TileState

LAYER = "deco"

# Tree variants deliberately kept OUT of the spawn scatter (an ART call, not a
# data problem — they read wrong at spawn-band density). They stay first-class
# `deco` slots: the editor still offers them and hand-placed map deco still
# renders them. This excludes them from the RUNTIME roll only.
SPAWN_TREE_EXCLUDED = frozenset((
    "deco_tree_v6", "deco_tree_v7", "deco_tree_v8",
))


def spawn_tree_slots(registry):
    """THE tree family the spawn scatter draws from, in registry order.

    Deliberately the ONE definition, shared by both consumers: ``TileMap``
    sizes each tile's roll against ``len()`` of this, and the host filters it
    by the asset manifest before handing it to ``spawn_deco_render_items``.
    Deriving it twice would let the roll's modulus and the emitter's family
    disagree — and since the emitter re-bases an out-of-range index with
    ``% len``, that disagreement would silently SKEW the variant distribution
    rather than fail, which is exactly the kind of bug nothing would catch.

    Returns ``()`` when the category/group is absent (a data dir without the
    deco tree family), which degrades to "no trees" at both call sites.
    """
    try:
        family = registry.group_slots(DECO_CATEGORY, SPAWN_DECO_GROUP)
    except KeyError:
        return ()
    return tuple(s for s in family if s not in SPAWN_TREE_EXCLUDED)


def spawn_deco_render_items(tile_map, col_min, col_max, row_min, row_max,
                             tree_slots, anim_time_ms=0, column=None):
    """Spawn-deco RenderItems for the tiles inside a visible tile window.

    ``tree_slots`` is the host's manifest-filtered tree family (art cannot
    change mid-run). A tile draws its tree only when it is CURRENTLY
    SPAWNING and carries a roll (``spawn_deco_roll >= 0``) — a BACKGROUND
    tile that later backfills into SPAWNING already has its roll waiting,
    and a converted-to-COMBAT tile's roll is simply never read again.

    ``anim_time_ms`` feeds idle animation; the same deterministic per-cell
    phase as the other two window emitters keeps identical neighbouring
    tiles from animating in lockstep.

    ``column`` is an OPAQUE master-sheet column passed straight through onto
    every emitted item — this emitter reads no run state and gives the value
    no meaning. ``None`` (the default) means "no live column", leaving each
    slot's stored column in charge; ``0`` is a REAL column, never "unset", so
    the value is never tested for truthiness here or downstream.
    """
    if not tree_slots:
        return []
    items = []
    r0 = max(0, row_min)
    r1 = min(tile_map.rows, row_max + 1)
    c0 = max(0, col_min)
    c1 = min(tile_map.cols, col_max + 1)
    n_slots = len(tree_slots)
    for row in range(r0, r1):
        for col in range(c0, c1):
            tile = tile_map.get(col, row)
            if tile is None:
                continue
            if tile.state is not TileState.SPAWNING or tile.spawn_deco_roll < 0:
                continue
            roll = tile.spawn_deco_roll
            # `% n_slots` mirrors `_resolve_condition_slot`'s guard: the
            # host's manifest-filtered family can be smaller than the
            # registry family the roll was sized against, and the index
            # must stay well-defined either way.
            slot = tree_slots[(roll // 2) % n_slots]
            flip = bool(roll % 2)
            phase = (col * 131 + row * 197) % 997   # ms, deterministic & pure
            items.append(RenderItem(slot, (col, row), layer=LAYER,
                                    anim_time_ms=anim_time_ms + phase,
                                    flip=flip, column=column))
    return items
