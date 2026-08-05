"""Structure buildings — the passive Blocker + WallBuilder line (Phase 10E).

Ports the prototype's ``BlockerBuilding`` (``src/buildings/blocker_building.py``)
and ``WallBuilderBuilding`` (``src/buildings/wall_builder_building.py``). Both
subclass ``Building`` directly (like ``BoostBuilding`` — neither economy nor
defence) and are PASSIVE: no attack, no yield.

  ``blocker``       — a stubborn HP-soak. It is NOT impassable: enemies path over
                      its tile and stop to attack it via the normal building
                      block-and-attack (``CONTENT_KEY="blocker_building"``, seeded
                      to the same traversable weight the shared economy key used
                      to fall back to). Pure tier HP.
  ``wall_builder``  — raises a perimeter of destructible EDGE walls around the
                      player's territory when placed. The wall edges live in the
                      map-owned ``TileMap.wall_edges`` registry; this class carries
                      the per-tier ``wall_hp`` + upkeep and the placement / upgrade
                      hooks that drive the map layer. Its own value is the walls.

Slot keys are FLAT (one slot per type, no ``_t{n}_lvl{n}`` suffix) to match the
single ``blocker`` / ``wall_builder`` slots in ``data/slots.json`` — the prototype
had no per-tier/level art for either. Grey-X until real art is imported.

The WALLS a ``WallBuilder`` raises are a SEPARATE art family, though: the
``walls`` slot category's 9 ``wall_t{n}_lvl{n}`` keys, resolved by
``WallBuilder.wall_slot()`` and consumed duck-typed by ``game/map/wall_render.py``.
"""
from .building import Building
from .components import WallBuilderState


class StructureBuilding(Building):
    """Family base: passive structures (Blocker / WallBuilder). Each leaf sets
    its own CONTENT_KEY (traversable weight, seeded to 1) so enemies attack
    rather than reroute, and uses a single flat art slot per type."""

    # No CONTENT_KEY here: each leaf below sets its own (map.json
    # content_weights carries a key per structure type since the
    # buildings-overwrite-tileweights rework). Both seed to the same
    # traversable weight (1) the shared economy key used to fall back to —
    # the intent (enemies attack rather than reroute) is preserved by the
    # seeded VALUE now, not by sharing a key.
    EXTRA_TAGS = ("structure",)
    SLOT = ""   # flat slot key (set by leaves) — no tier/level suffix

    def slot_key(self):
        return self.SLOT


class Blocker(StructureBuilding):
    BUILDING_TYPE = "blocker"
    CONTENT_KEY = "blocker_building"
    SUBTREE = ("StructureBuildings", "Blocker")
    SLOT = "blocker"


class WallBuilder(StructureBuilding):
    BUILDING_TYPE = "wall_builder"
    CONTENT_KEY = "wall_builder_building"
    SUBTREE = ("StructureBuildings", "WallBuilder")
    SLOT = "wall_builder"

    def _extra_components(self, tier0):
        return [WallBuilderState()]

    # -- art slot for the WALLS this builder raises -----------------------
    # (the BUILDER's own slot is the flat ``SLOT`` on ``StructureBuilding``
    #  above — this is the second, per-tier/level slot family.)

    def wall_slot(self):
        """The ``walls`` slot key for the segments this builder currently owns
        (``wall_t{tier}_lvl{level}``, both 1-based — the 9 keys in
        ``data/slots.json``'s ``walls`` category).

        WHY this lives in the BUILDING layer: the slot-key convention is a
        building concern (exactly like ``Building.slot_key``, whose
        ``_t{n}_lvl{n}`` shape this mirrors, reading the same ``TierState``
        cursor — ``current_tier`` 0-indexed, ``current_level_in_tier``
        1-indexed). ``game/map/wall_render.py`` reaches it DUCK-TYPED, as
        ``edge.owner.wall_slot()``, so the map layer keeps importing NOTHING
        from ``game.buildings`` — the same rule ``wall_hp()`` /
        ``wall_snapshot()`` / ``building_type`` already follow.
        """
        ts = self._tier
        return f"wall_t{ts.current_tier + 1}_lvl{ts.current_level_in_tier}"

    # -- computed stats (prototype ``WallBuilderBuilding``) ----------------

    def wall_hp(self):
        """HP of each perimeter wall at the current tier AND level. NOT on the
        ×10 combat scale — read straight from balancing (prototype ``wall_hp``
        property), plus the per-LEVEL term ``wall_hp_per_level`` (also not ×10),
        composed exactly like ``upkeep()`` below: base + level_idx × per_level.
        Seeded to 0 in every tier, so by default this is the prototype's flat
        per-tier value."""
        d = self.tier_data()
        return int(d["wall_hp"]) + self._lvl_idx * int(d["wall_hp_per_level"])

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
        """Resync every wall this builder owns to the current ``wall_hp()``, and
        FULL-HEAL it (prototype ``_sync_wall_hp``, now matching
        ``Building.apply_tier_stats``, which sets ``hp = max_hp`` on every
        re-apply).

        Fires on LEVEL upgrades as well as tier advances — ``apply_tier_stats``
        always ran on both, but before ``wall_hp_per_level`` existed a level
        upgrade could not change ``wall_hp()``, so only a tier advance was
        observable. It can now, so the walls follow the builder's own
        upgrade-heals-you rule at every step. No-op before placement (no tilemap
        cached yet) and in headless stat tests."""
        tilemap = getattr(self, "_tilemap", None)
        if tilemap is None:
            return
        new_hp = self.wall_hp()
        for edge in getattr(tilemap, "wall_edges", {}).values():
            if edge.owner is self:
                edge.max_hp = new_hp
                edge.hp = new_hp
