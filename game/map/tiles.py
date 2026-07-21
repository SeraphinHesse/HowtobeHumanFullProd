"""Tile runtime state + per-tile pathfinding weight (Phase 9C).

Ports the prototype's ``src/map/tile.py`` runtime model onto clean
architecture. Two deliberate divergences from the prototype:

* **Zones come from the map file's terrain codes**, not a procedural ring
  computation (``initial_tile_state``). ``TileMap`` seeds ``state`` from the
  legend code; ``Tile`` itself is zone-agnostic.
* **Pathfinding weight reads balancing data** (``data/balancing/map.json``
  ``Pathfinding.content_weights`` + ``TileConditions.path_weights``) via a
  per-tile *content key*, instead of ``isinstance``-ing Building subclasses.
  An empty tile's content key is derived from its zone; an occupied tile
  carries the key its occupant set at placement (9D).

Pure Python — no pygame.
"""
from enum import Enum, auto


class TileState(Enum):
    """Zone / unlock state of a tile. A tile is 'unlocked' once BUILDABLE or
    BUILT; BACKGROUND is impassable terrain; SPAWNING is where enemies enter."""

    BUILT = auto()
    BUILDABLE = auto()
    COMBAT = auto()
    SPAWNING = auto()
    BACKGROUND = auto()


class TileCondition(Enum):
    """Terrain condition affecting pathfinding weight (and, from 10I, gameplay
    modifiers). GRASS is neutral (adds 0). Dormant in 9C: every tile is GRASS
    until 10I rolls conditions per ``TileConditions.spawn_chances``."""

    GRASS = auto()
    MOUNTAIN = auto()
    POND = auto()
    FOREST = auto()


# Empty-tile content key by zone state (occupied tiles carry their own key).
_STATE_CONTENT_KEY = {
    TileState.BUILDABLE: "buildable_tile",
    TileState.COMBAT: "combat_tile",
    TileState.SPAWNING: "spawning_tile",
}

# Condition -> key in TileConditions.path_weights (GRASS has no entry -> +0).
_CONDITION_WEIGHT_KEY = {
    TileCondition.MOUNTAIN: "mountain",
    TileCondition.POND: "pond",
    TileCondition.FOREST: "forest",
}

# -- 10I: condition -> key in TileConditions.modifiers ----------------------
# GRASS is deliberately absent (no modifiers anywhere). Every consumer of the
# stat-modifier subtree (buildings, enemies, tooltips) maps enum -> subtree key
# through this ONE table so they cannot drift.
CONDITION_MODIFIER_KEY = {
    TileCondition.MOUNTAIN: "Mountain",
    TileCondition.POND: "Pond",
    TileCondition.FOREST: "Forest",
}
# -- /10I --

# -- condition ART -----------------------------------------------------------
# Condition -> its group PATH in the `conditions` slot category
# (``data/slots.json``). GRASS IS present here (unlike the two tables above):
# a condition's ART is a separate concern from its gameplay effect, and grass
# tiles get a slot too so imported grass art covers the map uniformly. Each
# leaf group holds interchangeable variants (`cond_mountain`,
# `cond_mountain_v2`, …) — the editor's "+ Variant" shape, same as deco types
# and enemy eras. This is the ONE enum->registry table; the roll in
# `tile_map.py` is its only consumer, so nothing can drift from it.
CONDITION_CATEGORY = "conditions"

CONDITION_GROUP = {
    TileCondition.GRASS: ("Terrain", "Grass"),
    TileCondition.MOUNTAIN: ("Terrain", "Mountain"),
    TileCondition.POND: ("Terrain", "Pond"),
    TileCondition.FOREST: ("Terrain", "Forest"),
}


class Tile:
    # __slots__ (not a behaviour change): a large map builds one Tile per cell
    # (a 1024×1024 map = ~1M tiles). Dropping the per-instance __dict__ cuts
    # each tile's memory footprint by well over half, which on big maps saves
    # hundreds of MB of resident RAM — the difference between fitting in
    # physical memory and paging every frame. The attribute set is fixed (all
    # assigned here or by the placement/unlock/UI code that reads them), so
    # slots cost nothing in flexibility. Paired with the host's gc.freeze()
    # (see game/main.py), this is what keeps very large maps performant.
    __slots__ = (
        "col", "row", "state", "content_key", "occupant", "condition",
        "condition_slot",
        "damage_weight_reduced", "defence_range_covered",
        "highlighted", "unlock_highlight", "range_highlight",
    )

    def __init__(self, col, row, state, content_key=None, occupant=None,
                 condition=TileCondition.GRASS):
        self.col = col
        self.row = row
        self.state = state
        # str | None — drives pathfinding weight. None for an empty tile
        # (weight then derives from `state`); set to an occupant's weight key
        # at placement (9D). The base tile carries "base_building".
        self.content_key = content_key
        # GameObject | None — the building/base occupying this tile. Set at
        # placement (9D); consumed by damage-weight refresh + occupancy sync.
        self.occupant = occupant
        self.condition = condition
        # str | None — the `conditions`-category slot key whose art this tile
        # draws on the `terrain` layer. Rolled once beside `condition` at map
        # construction (a random variant of that condition's group); None means
        # "no art for this tile" — the state every headless fixture stays in,
        # and what makes the terrain layer emit nothing.
        self.condition_slot = None
        # Dormant weight drivers — fed neutral values until 10F / 10I wire
        # their producers (building damage, defender coverage).
        self.damage_weight_reduced = False
        self.defence_range_covered = False
        # Render-only UI flags (used by the 9G building/selection UI).
        self.highlighted = False
        self.unlock_highlight = False
        self.range_highlight = False

    # -- state predicates -------------------------------------------------

    @property
    def is_passable(self):
        return self.state != TileState.BACKGROUND

    @property
    def is_unlocked(self):
        return self.state in (TileState.BUILDABLE, TileState.BUILT)

    @property
    def is_occupied(self):
        return self.content_key is not None

    # -- pathfinding weight (prototype tile.py:61-110) --------------------

    def _base_weight(self, weights):
        if self.content_key is not None:
            return weights[self.content_key]
        if self.state == TileState.BACKGROUND:
            return weights["impassable"]
        key = _STATE_CONTENT_KEY.get(self.state)
        if key is not None:
            return weights[key]
        # BUILT without a content key should not occur; stay safe.
        return weights["impassable"]

    def pathfinding_weight(self, balance, defence_range_add=0):
        """Dijkstra edge weight for stepping onto this tile.

        PROTOTYPE-EXACT composition order (``tile.py:61-96``): base content
        weight -> + terrain condition -> + defence-range coverage -> ×
        damage-reduction discount. The three modifiers are gated to
        ``0 < base < impassable`` so the goal (base, 0) and impassable walls
        (999) are exempt.
        """
        pf = balance["Pathfinding"]
        weights = pf["content_weights"]
        cond_weights = balance["TileConditions"]["path_weights"]
        reduction = pf["damage_reduction"]["reduction"]
        impassable = weights["impassable"]

        base = self._base_weight(weights)
        if 0 < base < impassable:
            ck = _CONDITION_WEIGHT_KEY.get(self.condition)
            if ck is not None:
                base += cond_weights[ck]
        if self.defence_range_covered and 0 < base < impassable:
            base += defence_range_add
        if self.damage_weight_reduced and 0 < base < impassable:
            return max(1, int(round(base * reduction)))
        return base
