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
``walls`` slot category's 9 ``Base`` ``wall_t{n}_lvl{n}`` keys, resolved by
``WallBuilder.wall_slot()`` and consumed duck-typed by ``game/map/wall_render.py``.

**Wall-era-art feature**: each tier group also carries optional ``Era N``
sibling children (``wall_t{n}_lvl{n}_era{k}``, open-ended — however many a
designer has imported), resolved by ``WallBuilder.wall_era_slot()`` off a
FROZEN ``WallBuilderState.art_era`` stamp. The stamp is set only by the
host/UI layer (``game/core/wall_era.py``, at placement and every
upgrade/tier-advance), never live off the round clock — a wall's look
changes only when the builder itself is upgraded. ``wall_render.py`` tries
the era slot first and falls back to ``wall_slot()`` (E-37: no imported era
art draws nothing, never breaks).

**Wall-hp-boost feature**: an adjacent ``boost_hp`` booster (``boost.py``)
can raise ``wall_hp()`` via a DEDICATED ``WallBuilderState.wall_hp_pct``
accumulator — separate from ``BoostReceiver.hp_pct`` (this builder never
carries a ``BoostReceiver``), so only the walls are lifted, never the
builder's own body HP.
"""
from engine.core import SpriteAnimator

from .building import Building
from .components import WallBuilderState


class StructureBuilding(Building):
    """Family base: passive structures (Blocker / WallBuilder). Each leaf sets
    its own CONTENT_KEY (traversable weight, seeded to 1) so enemies attack
    rather than reroute.

    **The PLACED building now uses the standard per-tier/level art family**
    (``<prefix>_t{tier}_lvl{level}``, inherited straight from
    ``Building.slot_key``) — the flat one-slot-per-type rule this family used
    to carry is gone, so a designer can give a Bush / Wooden / Stone Wall
    Builder distinct art and grow it per level like every other line. ``SLOT``
    survives for exactly one job: the research / unlock CARD art
    (``game/core/levelup.py``'s ``getattr(leaf, "SLOT", "")``, mirrored by
    ``buildings.json``'s ``card_slots``), which stays one image per type."""

    # No CONTENT_KEY here: each leaf below sets its own (map.json
    # content_weights carries a key per structure type since the
    # buildings-overwrite-tileweights rework). Both seed to the same
    # traversable weight (1) the shared economy key used to fall back to —
    # the intent (enemies attack rather than reroute) is preserved by the
    # seeded VALUE now, not by sharing a key.
    EXTRA_TAGS = ("structure",)
    #: CARD art only (research / unlock card, `card_slots`) — one flat slot per
    #: type, no tier/level suffix. It is NOT what the placed building draws;
    #: that is `TIER_SPRITES` via the inherited `Building.slot_key`.
    SLOT = ""


class Blocker(StructureBuilding):
    BUILDING_TYPE = "blocker"
    CONTENT_KEY = "blocker_building"
    SUBTREE = ("StructureBuildings", "Blocker")
    SLOT = "blocker"
    TIER_SPRITES = ("blocker", "blocker", "blocker")


class WallBuilder(StructureBuilding):
    BUILDING_TYPE = "wall_builder"
    CONTENT_KEY = "wall_builder_building"
    SUBTREE = ("StructureBuildings", "WallBuilder")
    SLOT = "wall_builder"
    TIER_SPRITES = ("wall_builder", "wall_builder", "wall_builder")

    def _extra_components(self, tier0):
        return [WallBuilderState()]

    # -- art slot for the WALLS this builder raises -----------------------
    # (the BUILDER's own slot is ``Building.slot_key``'s
    #  ``wall_builder_t{tier}_lvl{level}`` — this is a SECOND, independent
    #  per-tier/level family for the wall segments themselves.)

    def wall_slot(self):
        """The ``walls`` slot key for the segments this builder currently owns
        (``wall_t{tier}_lvl{level}``, both 1-based — the ``Base`` child under
        each tier group in ``data/slots.json``'s ``walls`` category).

        WHY this lives in the BUILDING layer: the slot-key convention is a
        building concern (exactly like ``Building.slot_key``, whose
        ``_t{n}_lvl{n}`` shape this mirrors, reading the same ``TierState``
        cursor — ``current_tier`` 0-indexed, ``current_level_in_tier``
        1-indexed). ``game/map/wall_render.py`` reaches it DUCK-TYPED, as
        ``edge.owner.wall_slot()``, so the map layer keeps importing NOTHING
        from ``game.buildings`` — the same rule ``wall_hp()`` /
        ``wall_snapshot()`` / ``building_type`` already follow. This is the
        FALLBACK key ``wall_render.py`` draws whenever ``wall_era_slot()``
        has no imported art yet — never changed by the era-art feature.
        """
        ts = self._tier
        return f"wall_t{ts.current_tier + 1}_lvl{ts.current_level_in_tier}"

    def wall_era_slot(self):
        """The era-specific ``walls`` slot key (``wall_t{tier}_lvl{level}_era
        {n}``, the ``Era N`` children beside ``Base`` in ``data/slots.json``),
        or ``None`` if this builder's art era was never stamped (fresh/unplaced
        instance). ``n`` is the FROZEN ``WallBuilderState.art_era`` — see
        ``stamp_era()`` — never the live global era clock, so a wall's look
        changes only when the builder itself is upgraded. Duck-typed by
        ``wall_render.py`` exactly like ``wall_slot()``, tried FIRST and
        falling back to it when the era slot has no imported art (E-37)."""
        era = self.get_component(WallBuilderState).art_era
        if era <= 0:
            return None
        ts = self._tier
        return (f"wall_t{ts.current_tier + 1}_lvl{ts.current_level_in_tier}"
                f"_era{era}")

    def wall_column(self):
        """The master-sheet colour COLUMN the segments this builder owns draw
        at — i.e. the builder's OWN colour (``SpriteAnimator.column``, stamped
        once at placement by ``registry.place_building``), or ``None`` when it
        has no colour driver (the ``-1`` "no driver" sentinel, or no animator
        at all on a bare/stub instance).

        A wall is the builder's own material, so it must not roll a colour of
        its own: the wall art sheet's columns are authored in the SAME order as
        the builder's, so handing the builder's index straight through makes a
        Bush builder's walls bushes and a Stone builder's walls stone. Reached
        DUCK-TYPED by ``game/map/wall_render.py`` as ``edge.owner.wall_column()``,
        exactly like ``wall_slot()`` / ``wall_era_slot()`` — the map layer still
        imports nothing from ``game.buildings``.
        """
        anim = self.get_component(SpriteAnimator)
        if anim is None or anim.column < 0:
            return None
        return anim.column

    def stamp_era(self, era):
        """Freeze the CURRENT global era (0-indexed, ``engine.era_math
        .era_of_round``) onto this builder's art, stored 1-indexed to match
        the ``Era N`` slot-group labels. Called ONLY from the host/UI layer
        (``game/core/wall_era.py``, at placement and at every upgrade/tier
        advance) — never from inside ``game/buildings`` itself, and never on
        a bare round tick, per the "only changes on upgrade" design."""
        self.get_component(WallBuilderState).art_era = max(1, era + 1)

    # -- computed stats (prototype ``WallBuilderBuilding``) ----------------

    def wall_hp(self):
        """HP of each perimeter wall at the current tier AND level. NOT on the
        ×10 combat scale — read straight from balancing (prototype ``wall_hp``
        property), plus the per-LEVEL term ``wall_hp_per_level`` (also not ×10),
        composed exactly like ``upkeep()`` below: base + level_idx × per_level.
        Seeded to 0 in every tier, so by default this is the prototype's flat
        per-tier value. Lifted by an adjacent HP booster's DEDICATED
        ``wall_hp_pct`` accumulator (wall-hp-boost feature) — deliberately NOT
        ``BoostReceiver``/``hp_pct`` (this builder never carries a
        ``BoostReceiver``), so the builder's own body HP is never affected."""
        d = self.tier_data()
        base = int(d["wall_hp"]) + self._lvl_idx * int(d["wall_hp_per_level"])
        state = self.get_component(WallBuilderState)
        return max(1, int(base * (1.0 + state.wall_hp_pct)))

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
        upgrade-heals-you rule at every step."""
        self.resync_wall_hp(full_heal=True)

    def resync_wall_hp(self, full_heal=False):
        """Push the current ``wall_hp()`` onto every wall edge this builder
        owns. ``full_heal=True`` (upgrades/tier advances, via
        ``_on_apply_stats``) sets ``hp = max_hp`` outright, matching
        ``Building.apply_tier_stats``'s every-re-apply full heal.
        ``full_heal=False`` (an HP-booster's ramp/flat delta, wall-hp-boost
        feature — ``game/buildings/boost.py``'s ``_apply_wall_delta``) instead
        heals by the increase / clamps on a decrease, mirroring
        ``boost.py``'s own ``_refresh_max_hp`` for combat buildings, so a boost
        change never spuriously full-heals a damaged wall.

        No-op before placement (no tilemap cached yet) and in headless stat
        tests."""
        tilemap = getattr(self, "_tilemap", None)
        if tilemap is None:
            return
        new_hp = self.wall_hp()
        for edge in getattr(tilemap, "wall_edges", {}).values():
            if edge.owner is self:
                old_max = edge.max_hp
                edge.max_hp = new_hp
                if full_heal:
                    edge.hp = new_hp
                elif new_hp >= old_max:
                    edge.hp = min(edge.hp + (new_hp - old_max), new_hp)
                else:
                    edge.hp = min(edge.hp, new_hp)
