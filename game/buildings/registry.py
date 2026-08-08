"""Building factory + placement seam (Phase 9D; feature-storm-acolyte-multi-
build's escalating-cost seam).

``create`` maps a ``building_type`` string to its leaf class — also the way to
reconstruct a subclass after ``GameObject.from_dict`` (which returns a base
GameObject, losing subclass identity). ``place_building`` ports the prototype's
placement gate: buildable tile + affordability (9D) + the per-type research gate
(10A — the type must be unlocked; its tier 1 is immediately placeable the
moment it is, ``starts_with_tier`` no longer exists), and wires the new
building through the 9C seams: ``tile.occupant``/``content_key``/``state``,
``Scene.spawn``, ``TileMap.sync_occupancy``. Love + the run state are passed in;
this module never reaches into ``game.core``.

``BUILDING_CLASSES`` is the same dict as ``research.LEAF_CLASSES`` — it lives
there so ``game/core/levelup.py`` can read it without importing this module (see
the import-boundary note in ``research.py``).

``BaseBuilding`` is NOT in the placeable registry — it has a different
constructor (core balance) and is attached to its pre-seeded tile via
``attach_base`` during bootstrap.
"""
from game.map.tiles import TileState
from .research import LEAF_CLASSES, RESEARCH, buildable, tiers_unlocked_for

# building_type -> leaf class. Only the 9D leaves; families grow in 10x.
BUILDING_CLASSES = LEAF_CLASSES


class PlacementError(Exception):
    """A building could not be placed (non-buildable tile or not enough love)."""


def create(building_type, col, row, buildings_balance, tier_idx=0):
    """Construct a placeable building of ``building_type`` at ``(col, row)``,
    starting at ``tier_idx`` (0 = the type's first tier)."""
    return BUILDING_CLASSES[building_type](col, row, buildings_balance, tier_idx)


# Storm Acolyte multi-build (feature-storm-acolyte-multi-build): the ONE tag
# whose already-built count escalates a fresh placement's price, via each
# group's OPTIONAL ``repeat_cost_multiplier`` balancing key (today only
# ``DefenceBuildings.StormPriest`` carries it). Tag-gated (G-3) — never a
# ``building_type == "storm_priest"`` branch anywhere on this seam.
LIGHTNING_SOURCE_TAG = "lightning_source"


def count_tag(tilemap, tag):
    """Count of BUILT-tile occupants (alive OR dead — a dead one is not a
    freed slot, payday's slot-9 revive brings it back) carrying ``tag``.
    O(built tiles) via ``TileMap.built_tiles()``'s ``_by_state`` index — never
    a full-map scan (``game/map/CLAUDE.md``'s perf invariants)."""
    return sum(1 for t in tilemap.built_tiles()
              if t.occupant is not None and tag in t.occupant.tags)


def build_cost(building_type, buildings_balance, tier_idx=0, repeat_count=0):
    """Build cost for ``building_type`` at ``tier_idx`` (the placement price).

    ``repeat_count`` (feature-storm-acolyte-multi-build) escalates the price
    by the group's own ``repeat_cost_multiplier ** repeat_count`` when that
    OPTIONAL balancing key is present; ``repeat_count=0`` (the default) and a
    group with no such key both leave today's price untouched, so every
    caller that predates this feature is unaffected."""
    cls = BUILDING_CLASSES[building_type]
    tiers = cls._resolve_tiers(buildings_balance)
    cost = tiers[tier_idx]["build_cost"]
    if repeat_count:
        mult = cls._resolve_group(buildings_balance).get(
            "repeat_cost_multiplier")
        if mult is not None:
            cost = round(cost * (mult ** repeat_count))
    return cost


def place_building(tilemap, tile, building_type, love, buildings_balance,
                   scene, occupancy, state=None):
    """Place ``building_type`` on ``tile``. Returns ``(building, cost)``.

    Raises ``PlacementError`` if the tile is not BUILDABLE, the type is not yet
    unlocked (given a ``state``), or ``love`` is below the build cost
    (prototype ``Game.place_building`` gate). On success sets the tile's
    occupant/content_key/state, spawns the building into ``scene``, and re-syncs
    ``occupancy`` — the single 9C occupancy seam.

    ``state`` is the ``RunState`` (duck-typed: ``unlocked_buildings`` /
    ``tiers_unlocked``); omit it in stat/logic tests that predate the run state.
    """
    if tile.state != TileState.BUILDABLE:
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is {tile.state.name}, not BUILDABLE")
    if state is not None and not buildable(state, building_type):
        raise PlacementError(f"{building_type} is not researched yet")
    # 10C: a tile that completed a Painter payout is permanently barred from
    # hosting another Painter (prototype ``used_painter_tiles`` — enforced HERE,
    # the single legal placement path; the UI disabling is only a convenience).
    if (building_type == "painter" and state is not None
            and (tile.col, tile.row) in getattr(state, "used_painter_tiles", ())):
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) already sold a painting")
    # Building Movement: neither endpoint of a move in progress may host a new
    # building — the vacated origin and the reserved destination are both
    # ordinary BUILDABLE tiles (deliberately, so enemies keep walking through
    # them), so `is_moving` is the only thing that tells them apart. Enforced
    # HERE, the single legal placement path, exactly like the painter-tile bar
    # above; the panel's tile-picking is only a convenience. `getattr` keeps
    # the pre-feature tilemap stubs some logic tests build working.
    is_moving = getattr(tilemap, "is_moving", None)
    if is_moving is not None and is_moving(tile.col, tile.row):
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is part of a move in progress")
    # 10D: boosters may not be placed cardinally adjacent to another booster
    # (prototype ``Game.place_building`` 'boost_adjacent' — cardinal-4, diagonals
    # allowed). Enforced HERE, the single legal placement path.
    if building_type.startswith("boost_"):
        for dc, dr in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            adj = tilemap.get(tile.col + dc, tile.row + dr)
            if (adj is not None and adj.occupant is not None
                    and "boost" in adj.occupant.tags):
                raise PlacementError(
                    f"a boost building is already next to ({tile.col},{tile.row})")
    # A fresh placement builds at the type's CURRENT research ceiling, not
    # always tier 0 (10A follow-up): once a higher tier is researched, the
    # lower tier is simply never placed again — no separate gate needed.
    # ``state=None`` (logic tests that predate RunState) keeps tier 0.
    tier_idx = (tiers_unlocked_for(state, building_type) - 1
                if state is not None else 0)
    # feature-storm-acolyte-multi-build: every placement counts the already-
    # built ``lightning_source``-tagged occupants (tag-gated, G-3 — never a
    # ``storm_priest`` branch) and passes it through; ``build_cost`` is a
    # no-op with this for every OTHER type (no ``repeat_cost_multiplier`` key).
    repeat_count = count_tag(tilemap, LIGHTNING_SOURCE_TAG)
    cost = build_cost(building_type, buildings_balance, tier_idx, repeat_count)
    if love < cost:
        raise PlacementError(
            f"{building_type} costs {cost} love, have {love}")
    building = create(building_type, tile.col, tile.row, buildings_balance,
                      tier_idx)
    # Occupant + content key in one write through the TileMap seam — the
    # content key drives the tile's path weight, so the seam invalidates the
    # pathfinder's cached flow field (see game/map/tile_map.py).
    tilemap.set_tile_content(tile, building, building.CONTENT_KEY)
    # -- 10I: snapshot the tile condition at placement (prototype
    # ``b.tile_condition = tile.condition``, game.py:690). Conditions are
    # immutable after the map roll, so snapshot == live read. The modifiers
    # subtree rides along so stat getters need no tilemap reference.
    building._tile_condition = tile.condition
    building._condition_mods = (
        tilemap.balance["TileConditions"]["modifiers"])
    # Re-apply derived stats so condition-dependent hooks (the defence
    # RangeSensor mirrors the mountain-boosted effective range) see the
    # snapshot; the full-heal inside is a no-op at placement (hp == max).
    building.apply_tier_stats()
    # -- /10I --
    tilemap.set_tile_state(tile, TileState.BUILT)
    scene.spawn(building)
    # Only this one tile changed — update its occupancy directly instead of the
    # full-map ``sync_occupancy`` scan (an O(map) hitch on large maps, D-20).
    occupancy.set((tile.col, tile.row), building)
    # Post-placement family hook (Building.on_placed, default no-op): a booster
    # clears the tile's previous occupant's explosion debuffs + (flat mode)
    # applies its one-time boost (10D); a WallBuilder raises its perimeter walls
    # (10E).
    building.on_placed(tilemap)
    return building, cost


def attach_base(tilemap, base_building, scene, occupancy):
    """Attach the ``BaseBuilding`` to the pre-seeded base tile (already BUILT +
    ``base_building`` content key from ``TileMap`` construction), spawn it, and
    sync occupancy. The 9C↔9D base contract."""
    tile = tilemap.get(tilemap.base_col, tilemap.base_row)
    # Content key is already BASE_CONTENT_KEY (unchanged → no path-cache
    # invalidation); the seam just records the occupant.
    tilemap.set_tile_content(tile, base_building, tile.content_key)
    scene.spawn(base_building)
    # Single-tile occupancy update (see place_building) — no full-map scan.
    occupancy.set((tile.col, tile.row), base_building)
    return base_building
