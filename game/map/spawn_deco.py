"""Spawn-band tree deco as RenderItems on the ``deco`` draw layer.

A tree identity (variant + orientation) rolls once per tile at
``TileMap.__init__`` (``SpawnDeco.tree_chance``, folded into the condition-art
pass — see ``tile_map.py``), packed into ``Tile.spawn_deco_roll`` (-1 = no
tree). This module is the ONE place that turns that roll into RenderItems, and
it is the ONLY thing deciding whether a tile's tree actually draws right now:
it reads ``tile.state`` LIVE, so a tile that converts SPAWNING -> COMBAT
(spawn recede) simply stops being emitted the very next frame — no
``set_tile_state`` hook needed, unlike condition art's re-resolve. The one
non-SPAWNING tile that draws is a BACKGROUND tile carrying a painted
``spawnable_background`` mark (``Tile.spawn_reserved``): the spawn RESERVE
wears its treeline before it is released, so the band does not visibly grow in
batch by batch.

**fix/y-sorted-deco**: these ride the ``entities`` layer, the SAME one as
enemies and buildings, so a tree occludes an enemy exactly when it is in front
of it and not otherwise. This module used to emit on the ``deco`` layer
(``engine.render.LAYERS`` index 3, above ``entities``) and called that "the
entire z-order fix, no per-item tuning" — which it was, for enemies standing
*inside* the band, and wrong the instant one walked out the front: since
``depth_key`` makes the layer the PRIMARY key, EVERY tree drew over EVERY
enemy regardless of feet. It also disabled the very thing that would have
sorted them correctly — ``Renderer._depth_pos`` resolves a slot's authored
``depth_pivot`` (feet) only on the ``entities`` layer, and every
``deco_tree_*`` slot has one. See ``engine.tilemap.DECO_LAYER``, which carries
the same change for hand-placed map deco.

Windowed by construction, mirroring ``conditions.py``/
``engine.tilemap.visible_render_items`` — cost is bounded by the viewport, not
by how large a spawn zone a designer paints. Pure Python — no pygame.
"""
from engine.render.item import RenderItem
from engine.tilemap import DECO_LAYER, DECO_RANK
from .tiles import DECO_CATEGORY, SPAWN_DECO_GROUP, TileState

#: fix/y-sorted-deco — deliberately the SAME constants hand-placed map deco
#: uses, imported rather than re-spelled so the two can never drift apart.
LAYER = DECO_LAYER
RANK = DECO_RANK

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
    change mid-run). A tile draws its tree when it carries a roll
    (``spawn_deco_roll >= 0``) AND is either CURRENTLY SPAWNING or a
    BACKGROUND tile carrying a painted spawn-reserve mark
    (``tile.spawn_reserved``) — the reserve's treeline is therefore whole from
    the start, and stays put when a batch releases those tiles into the spawn
    band. A BACKGROUND tile with no mark that later backfills into SPAWNING
    behind a recede already has its roll waiting, and a converted-to-COMBAT
    tile's roll is simply never read again.

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
            if tile.spawn_deco_roll < 0:
                continue
            # Two tile sets draw a tree: the LIVE spawn band, and the painted
            # spawn RESERVE while it is still BACKGROUND (`tile.spawn_reserved`,
            # stamped at `TileMap.__init__`). The reserve half is what makes the
            # treeline cover the whole painted band from frame one instead of
            # growing in batch by batch as stages release it — and because a
            # released tile is SPAWNING, its tree simply carries over unchanged.
            # Still a LIVE `tile.state` read: a reserve tile that has gone all
            # the way to COMBAT fails both arms and stops being emitted, flag or
            # no flag.
            if not (tile.state is TileState.SPAWNING
                    or (tile.state is TileState.BACKGROUND
                        and tile.spawn_reserved)):
                continue
            roll = tile.spawn_deco_roll
            # `% n_slots` mirrors `_resolve_condition_slot`'s guard: the
            # host's manifest-filtered family can be smaller than the
            # registry family the roll was sized against, and the index
            # must stay well-defined either way.
            slot = tree_slots[(roll // 2) % n_slots]
            flip = bool(roll % 2)
            phase = (col * 131 + row * 197) % 997   # ms, deterministic & pure
            items.append(RenderItem(slot, (col, row), layer=LAYER, rank=RANK,
                                    anim_time_ms=anim_time_ms + phase,
                                    flip=flip, column=column))
    return items
