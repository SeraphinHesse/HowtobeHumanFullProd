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

# Condition -> key in TileConditions.path_weights / path_weight_overwritable
# (GRASS has no entry -> +0, and can never be "overwritten" — there is no
# condition weight to overwrite). Public (not `_`-prefixed): both
# `Tile.pathfinding_weight` here and `TileMap.refresh_building_overwrite_flags`
# share it, so the enum->key mapping cannot drift between the two.
CONDITION_WEIGHT_KEY = {
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

# -- tile-condition rework: conditions that block building placement --------
# Condition -> may a building never be placed on a tile with this condition,
# regardless of zone state. Absent conditions are buildable (GRASS, MOUNTAIN,
# FOREST). ONE table, so this rule cannot drift from whichever consumer needs
# it (today: game/buildings/registry.py's place_building).
CONDITION_BLOCKS_BUILD = frozenset({TileCondition.POND})

# -- map-file condition NAME -> TileCondition --------------------------------
# The one table translating a `tile_conditions` mark's `condition` name (the
# map-file schema's enum, which is the single source of truth for that
# vocabulary) into the runtime enum. GRASS IS present: a designer must be able
# to paint a tile explicitly grass and lock it out of the roll. ONE table, so
# the name->enum mapping cannot drift — same rationale as CONDITION_LABEL /
# CONDITION_WEIGHT_KEY / CONDITION_MODIFIER_KEY above. Indexed DIRECTLY by its
# consumer (`tile_map.py`), never `.get()`: an unknown name is invalid data and
# must fail loud (D-2).
CONDITION_BY_MAP_KEY = {
    "grass": TileCondition.GRASS,
    "mountain": TileCondition.MOUNTAIN,
    "pond": TileCondition.POND,
    "forest": TileCondition.FOREST,
}

# -- condition ART -----------------------------------------------------------
# Condition -> its own TOP-LEVEL group label in the `conditions` slot category
# (``data/slots.json``). GRASS IS present here (unlike the two tables above):
# a condition's ART is a separate concern from its gameplay effect, and grass
# tiles get a slot too so imported grass art covers the map uniformly. Since
# the per-state restructuring, each condition type is its OWN top-level group
# (Grass/Mountain/Pond/Forest), and WITHIN each, `CONDITION_STATE_LABEL` below
# selects the tile's current zone STATE (Buildable/Built/Combat/Spawning) —
# each state is its own leaf variant family (`cond_mountain_buildable`,
# `cond_mountain_buildable_v2`, …) — the editor's "+ Variant" shape, same as
# deco types and enemy eras. These are the TWO enum->registry tables; the
# resolver in `tile_map.py` is their only consumer, so nothing can drift.
CONDITION_CATEGORY = "conditions"

CONDITION_LABEL = {
    TileCondition.GRASS: "Grass",
    TileCondition.MOUNTAIN: "Mountain",
    TileCondition.POND: "Pond",
    TileCondition.FOREST: "Forest",
}

# Zone state -> its group label WITHIN a condition's top-level group.
# BACKGROUND and SPAWNING have NO entry, and that absence IS the rule:
# neither ever gets condition art, regardless of a tile's condition. For
# BACKGROUND that is the original rule; for SPAWNING it is the deferred-roll
# change — the spawn band is a staging area that reads as plain ground plus
# trees, and a spawn tile does not decide its condition until it converts to
# COMBAT (`TileMap._roll_condition`). A painted `tile_conditions` mark still
# applies to a spawn tile as a GAMEPLAY value (weight, modifiers); it simply
# draws no condition art while the tile is spawning.
# The four `cond_*_spawning` slots in `data/slots.json` stay first-class
# editor slots — nothing resolves them at runtime any more.
CONDITION_STATE_LABEL = {
    TileState.BUILDABLE: "Buildable",
    TileState.BUILT: "Built",
    TileState.COMBAT: "Combat",
}

# -- spawn-band deco (10I) ---------------------------------------------------
# Enum->registry table for the tree family scattered over SPAWNING tiles
# (`spawn_deco.py`), same "one consumer, cannot drift" rationale as
# CONDITION_CATEGORY above: DECO_CATEGORY is a `data/slots.json` category
# (asset-only, like `conditions`), SPAWN_DECO_GROUP the group path within it
# that holds the tree variant family (`Props -> Tree`).
DECO_CATEGORY = "deco"
SPAWN_DECO_GROUP = ("Props", "Tree")


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
        "condition_rolled",
        "condition_slot", "condition_variant_idx", "spawn_deco_roll",
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
        # bool — has this tile's condition been DECIDED yet? True once the
        # init roll rolled it, a painted `tile_conditions` mark claimed it, or
        # the deferred roll fired at COMBAT conversion — and also for the
        # starting unlocked pocket, which is deliberately GRASS forever rather
        # than pending. It is False for exactly one set: unpainted BACKGROUND
        # and SPAWNING tiles, which have not entered play yet and whose
        # condition `TileMap._roll_condition` decides the moment they convert
        # to COMBAT. That is what makes the roll fire ONCE per tile no matter
        # which route it took in (`c` at init, `s -> c`, or `f -> s -> c`).
        self.condition_rolled = False
        # str | None — the `conditions`-category slot key whose art this tile
        # draws on the `terrain` layer. Resolved from (condition, state,
        # condition_variant_idx) at map construction AND re-resolved on every
        # `TileMap.set_tile_state` transition, so the art follows the tile's
        # zone state live. None means "no art for this tile" — the state
        # every headless fixture stays in, and what makes the terrain layer
        # emit nothing.
        self.condition_slot = None
        # int — the stable index into whichever state-family is currently
        # active for this tile's condition. Picked ONCE, at the same moment
        # the tile's CONDITION is decided (the init art pass for a tile that
        # starts in play; `TileMap._roll_condition` for one that converts into
        # play later) and never re-rolled after that: a state transition
        # re-resolves `condition_slot` at this SAME index against the new
        # state's family (modulo its size), so a tile keeps "variant #2"
        # across buildable/built/combat looks.
        self.condition_variant_idx = 0
        # int — packed spawn-deco roll: -1 means "no tree", else `variant_idx *
        # 2 + flip_bit`. Rolled ONCE at `TileMap.__init__` (`SpawnDeco.
        # tree_chance`) for EVERY tile, BACKGROUND included (see the roll's own
        # comment in `tile_map.py` for why that matters) — a single small int
        # keeps the per-tile cost
        # at 8 bytes (CPython caches small ints, so this is zero extra
        # allocation) rather than a resolved-slot string. The emitter
        # (`spawn_deco.py`) reads `tile.state` LIVE to decide whether to draw
        # it, so the tree vanishes the instant a SPAWNING tile converts to
        # COMBAT with no `set_tile_state` hook at all — and a BACKGROUND tile
        # that later backfills into SPAWNING already has its roll waiting.
        self.spawn_deco_roll = -1
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

    def _overwrites_condition(self, balance, ck):
        """True iff a LIVE building occupying this tile OVERWRITES (rather
        than adds to) the terrain condition weight keyed ``ck`` — the
        buildings-overwrite-tileweights rework (stops the water-parking
        exploit: an economy building on a pond used to cost 1+9 instead of
        just 1). An OR of three independently designer-controlled switches
        (deliberate, per the orchestrator's ruling — any one of them can turn
        overwrite on): the master switch, a per-building-type override, and a
        per-condition override. Every dict is indexed DIRECTLY (no ``.get()``
        default) so a missing key fails loud (D-2) — every possible tile must
        be calculable."""
        if self.occupant is None or not getattr(self.occupant, "alive", False):
            return False
        if self.content_key is None:
            return False
        pf = balance["Pathfinding"]
        return (
            pf["buildings_overwrite_tileweights"]
            or pf["content_weight_overwrites"][self.content_key]
            or balance["TileConditions"]["path_weight_overwritable"][ck]
        )

    def pathfinding_weight(self, balance, defence_range_add=0, cond_weights=None):
        """Dijkstra edge weight for stepping onto this tile.

        PROTOTYPE-EXACT composition order (``tile.py:61-96``): base content
        weight -> + terrain condition -> + defence-range coverage -> ×
        damage-reduction discount. The three modifiers are gated to
        ``0 < base < impassable`` so the goal (base, 0) and impassable walls
        (999) are exempt. Since the buildings-overwrite-tileweights rework
        the condition step is further gated: a live building whose
        ``_overwrites_condition`` resolves true OVERWRITES the terrain
        weight instead of adding to it (nothing to add, so the step is
        simply skipped — the building's own content weight from
        ``_base_weight`` above already stands alone).

        ``cond_weights``: ``None`` (default) means "use the map's own
        ``TileConditions.path_weights``" — today's behaviour, byte-identical.
        A caller with a per-enemy-type profile (``EnemyTypes.<type>.
        condition_path_weights``, Chunk 3) passes its own
        ``{forest, mountain, pond}`` mapping here instead, so a raider can be
        tuned to swim a pond a walker would avoid.
        """
        pf = balance["Pathfinding"]
        weights = pf["content_weights"]
        weights_by_cond = (cond_weights if cond_weights is not None
                           else balance["TileConditions"]["path_weights"])
        reduction = pf["damage_reduction"]["reduction"]
        impassable = weights["impassable"]

        base = self._base_weight(weights)
        if 0 < base < impassable:
            ck = CONDITION_WEIGHT_KEY.get(self.condition)
            if ck is not None and not self._overwrites_condition(balance, ck):
                base += weights_by_cond[ck]
        if self.defence_range_covered and 0 < base < impassable:
            base += defence_range_add
        if self.damage_weight_reduced and 0 < base < impassable:
            return max(1, int(round(base * reduction)))
        return base
