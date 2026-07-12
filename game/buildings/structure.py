"""Structure buildings — the passive Blocker + WallBuilder line (Phase 10E).

Ports the prototype's ``BlockerBuilding`` (``src/buildings/blocker_building.py``)
and ``WallBuilderBuilding`` (``src/buildings/wall_builder_building.py``). Both
subclass ``Building`` directly (like ``BoostBuilding`` — neither economy nor
defence) and are PASSIVE: no attack, no yield.

  ``blocker``       — a stubborn HP-soak. It is NOT impassable: enemies path over
                      its tile and stop to attack it via the normal building
                      block-and-attack (``CONTENT_KEY="economic_building"`` = the
                      prototype's traversable weight fallback). Pure tier HP.
  ``wall_builder``  — raises a perimeter of destructible EDGE walls around the
                      player's territory when placed. The wall edges live in the
                      map-owned ``TileMap.wall_edges`` registry; this class carries
                      the per-tier ``wall_hp`` + upkeep and the placement / upgrade
                      hooks that drive the map layer. Its own value is the walls.

Slot keys are FLAT (one slot per type, no ``_t{n}_lvl{n}`` suffix) to match the
single ``blocker`` / ``wall_builder`` slots in ``data/slots.json`` — the prototype
had no per-tier/level art for either. Grey-X until real art is imported.
"""
from .building import Building
from .components import WallBuilderState


class StructureBuilding(Building):
    """Family base: passive structures (Blocker / WallBuilder). Falls back to the
    economy pathfinding weight (traversable, 1) so enemies attack rather than
    reroute, and uses a single flat art slot per type."""

    CONTENT_KEY = "economic_building"
    EXTRA_TAGS = ("structure",)
    SLOT = ""   # flat slot key (set by leaves) — no tier/level suffix

    def slot_key(self):
        return self.SLOT


class Blocker(StructureBuilding):
    BUILDING_TYPE = "blocker"
    SUBTREE = ("StructureBuildings", "Blocker")
    SLOT = "blocker"


class WallBuilder(StructureBuilding):
    BUILDING_TYPE = "wall_builder"
    SUBTREE = ("StructureBuildings", "WallBuilder")
    SLOT = "wall_builder"

    def _extra_components(self, tier0):
        return [WallBuilderState()]

    # -- computed stats (prototype ``WallBuilderBuilding``) ----------------

    def wall_hp(self):
        """HP of each perimeter wall at the current tier. NOT on the ×10 combat
        scale — read straight from balancing (prototype ``wall_hp`` property)."""
        return int(self.tier_data()["wall_hp"])

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    # -- wall-edge snapshot seam (read/written by the map layer) -----------

    def wall_snapshot(self):
        return self.get_component(WallBuilderState).wall_snapshot

    def set_wall_snapshot(self, snapshot):
        self.get_component(WallBuilderState).wall_snapshot = snapshot

    # -- placement + upgrade hooks (drive TileMap.wall_edges) --------------

    def on_placed(self, tilemap):
        """Raise the perimeter walls (prototype ``Game`` calls
        ``tilemap.place_walls_for_builder`` right after placement). Cache the
        tilemap so a later tier upgrade can resync existing edges' HP."""
        self._tilemap = tilemap
        tilemap.place_walls_for_builder(self)

    def _on_apply_stats(self):
        """On a tier upgrade, lift every wall this builder owns to the new tier's
        ``wall_hp`` (prototype ``_sync_wall_hp``). No-op before placement (no
        tilemap cached yet) and in headless stat tests."""
        tilemap = getattr(self, "_tilemap", None)
        if tilemap is None:
            return
        new_hp = self.wall_hp()
        for edge in getattr(tilemap, "wall_edges", {}).values():
            if edge.owner is self:
                edge.max_hp = new_hp
                edge.hp = min(edge.hp, new_hp)
