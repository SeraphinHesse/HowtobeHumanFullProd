"""Building factory + placement seam (Phase 9D).

``create`` maps a ``building_type`` string to its leaf class — also the way to
reconstruct a subclass after ``GameObject.from_dict`` (which returns a base
GameObject, losing subclass identity). ``place_building`` ports the prototype's
placement gate that applies in 9D (buildable tile + affordability) and wires the
new building through the 9C seams: ``tile.occupant``/``content_key``/``state``,
``Scene.spawn``, ``TileMap.sync_occupancy``. Love is passed in (no game-state
store until 9F); per-type unlock gates + UI batching are 9F/9G.

``BaseBuilding`` is NOT in the placeable registry — it has a different
constructor (core balance) and is attached to its pre-seeded tile via
``attach_base`` during bootstrap.
"""
from game.map.tiles import TileState
from .defender import Defender
from .musician import Musician

# building_type -> leaf class. Only the 9D leaves; families grow in 10x.
BUILDING_CLASSES = {
    "defence": Defender,
    "economic": Musician,
}


class PlacementError(Exception):
    """A building could not be placed (non-buildable tile or not enough love)."""


def create(building_type, col, row, buildings_balance):
    """Construct a placeable building of ``building_type`` at ``(col, row)``."""
    return BUILDING_CLASSES[building_type](col, row, buildings_balance)


def build_cost(building_type, buildings_balance):
    """Tier-0 build cost for ``building_type`` (the placement price)."""
    tiers = BUILDING_CLASSES[building_type]._resolve_tiers(buildings_balance)
    return tiers[0]["build_cost"]


def place_building(tilemap, tile, building_type, love, buildings_balance,
                   scene, occupancy):
    """Place ``building_type`` on ``tile``. Returns ``(building, cost)``.

    Raises ``PlacementError`` if the tile is not BUILDABLE or ``love`` is below
    the build cost (prototype ``Game.place_building`` gate; the full per-type
    unlock gates + UI batching are 9F/9G). On success sets the tile's
    occupant/content_key/state, spawns the building into ``scene``, and re-syncs
    ``occupancy`` — the single 9C occupancy seam.
    """
    if tile.state != TileState.BUILDABLE:
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is {tile.state.name}, not BUILDABLE")
    cost = build_cost(building_type, buildings_balance)
    if love < cost:
        raise PlacementError(
            f"{building_type} costs {cost} love, have {love}")
    building = create(building_type, tile.col, tile.row, buildings_balance)
    tile.occupant = building
    tile.content_key = building.CONTENT_KEY
    tile.state = TileState.BUILT
    scene.spawn(building)
    tilemap.sync_occupancy(occupancy)
    return building, cost


def attach_base(tilemap, base_building, scene, occupancy):
    """Attach the ``BaseBuilding`` to the pre-seeded base tile (already BUILT +
    ``base_building`` content key from ``TileMap`` construction), spawn it, and
    sync occupancy. The 9C↔9D base contract."""
    tile = tilemap.get(tilemap.base_col, tilemap.base_row)
    tile.occupant = base_building
    scene.spawn(base_building)
    tilemap.sync_occupancy(occupancy)
    return base_building
