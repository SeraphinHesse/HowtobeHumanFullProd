"""Boost buildings — the configurable-range buff/curse support line (Phase 10D;
range made configurable in the booster-range-config feature).

Ports the prototype's ``BoostBuilding`` family (``src/buildings/boost_building.py``).
A booster buffs the COMBAT buildings within its configured range
(``BoostBuildings.globals.range_tiles``/``.range_shape`` — shared by all three
lines) — never economy, never another booster. ``range_shape`` picks the
tile-offset geometry (``game/buildings/range_shape.py``): ``"plus"`` (the
shipped default, magnitude 1 — the original cardinal-4 behaviour) or
``"square"`` (a full Chebyshev square, e.g. every one of the 8 surrounding
tiles at magnitude 1). Three data lines share ONE behaviour class; the leaves
are pure identity:

  ``boost_speed``  — reduces neighbours' ``attack_speed`` (faster attacks)
  ``boost_damage`` — raises neighbours' ``damage``
  ``boost_hp``     — raises neighbours' ``max_hp``

Two modes (``BoostBuildings.globals.flat_mode``): RAMP (default) accumulates a
little every surviving income phase; FLAT applies a one-time 10× boost on placement,
reversed on death. A booster's death has NO other effect — the "explosion" debuff
it used to stamp on its neighbours is removed.

All the buff state lives on the NEIGHBOUR's ``BoostReceiver`` component (E-11
— no ad-hoc attrs); this class only pushes deltas into it. The booster's own state
is a ``BoostEmitter`` marker + the computed ``boost_value`` from the tier table.
Orchestration (the per-turn sweep and the placement adjacency block) lives in
``game/core/payday.py`` and ``game/buildings/registry.py``
— exactly where the prototype's ``Game`` drove it. The placement-adjacency block
(no booster next to another booster) is a SEPARATE, fixed cardinal-4 rule in
``registry.py`` — deliberately independent of this configurable buff range.

**Wall-hp-boost feature**: the HP line (``boost_hp``) ALSO reaches nearby
WallBuilders' walls, via a second, parallel adjacency scan
(``_adjacent_structures``, duck-typed on ``hasattr(b, "wall_hp")`` — the same
precedent ``game/buildings/movement.py``'s ``is_movable`` uses) and a SEPARATE
dedicated rate (``wall_boost_per_turn``/``wall_boost_increase_per_level`` —
``wall_boost_value()``, independent of ``boost_value()``) pushed into
``WallBuilderState.wall_hp_pct`` (never ``BoostReceiver`` — a WallBuilder never
carries one, so its own body HP is provably unaffected). Only the ``"hp"``
stat does this; Speed/Damage never touch walls.
"""
from engine.core import Health

from . import range_shape
from .building import Building
from .components import BoostEmitter, BoostReceiver, WallBuilderState


class BoostBuilding(Building):
    """Family base: identity is set by the three leaves, behaviour lives here."""

    # No CONTENT_KEY here: each leaf below sets its own
    # (map.json content_weights carries a key per boost type since the
    # buildings-overwrite-tileweights rework). All three seed to the same
    # traversable weight (1) the shared economy key used to fall back to —
    # the intent (a boost tile stays cheap to walk through) is preserved by
    # the seeded VALUE now, not by sharing a key.
    EXTRA_TAGS = ("boost",)

    # Set by leaves:
    _boost_stat = None      # "damage" | "speed" | "hp" — which receiver accumulator
    _boost_color = (255, 255, 255)
    _boost_label = "Boost/turn"
    # UT-3: the stat-row key the building panel names this row's two
    # id'd widgets after, and the `building.stat.<key>` string id it
    # resolves its label through. `_boost_label` stays as the code-side
    # fallback the string table was seeded from.
    _boost_stat_key = "boost"

    def _extra_components(self, tier0):
        return [BoostEmitter()]

    def flat_mode(self):
        """Global ramp-vs-flat switch (``BoostBuildings.globals.flat_mode``): False
        accumulates a little each income phase, True applies a one-time 10× boost on
        placement (removed on death)."""
        return self._balance["BoostBuildings"]["globals"]["flat_mode"]

    def on_placed(self, tilemap):
        """Post-placement hook (prototype ``Game._on_boost_placed``): in flat
        mode apply this booster's one-time 10× boost immediately."""
        if self.flat_mode():
            self.apply_flat(tilemap)
            self.get_component(BoostEmitter).flat_applied = True

    # -- computed stats (prototype ``update_stats_from_tier`` boost_value/upkeep) --

    def boost_value(self):
        """Fraction granted per surviving income phase at the current level."""
        d = self.tier_data()
        return d["boost_per_turn"] + self._lvl_idx * d["boost_increase_per_level"]

    def range_tiles(self):
        """Magnitude of this booster's buff/curse range — shared by all three
        boost lines and every tier (``BoostBuildings.globals.range_tiles``).
        Also what the panel Range row, the RANGE overlay, the selection
        highlight and defence-range pathfinding coverage duck-type on."""
        return self._balance["BoostBuildings"]["globals"]["range_tiles"]

    def range_shape(self):
        """``"plus"`` (cardinal arms) or ``"square"`` (Chebyshev) — which
        tile-offset geometry ``range_tiles()`` is interpreted with
        (``BoostBuildings.globals.range_shape``, ``game/buildings/range_shape.py``)."""
        return self._balance["BoostBuildings"]["globals"]["range_shape"]

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    # -- adjacency (prototype ``adjacent_tiles`` / ``_adjacent_combat_buildings``) --

    def _adjacent_combat(self, tilemap):
        """(tile, building) for each alive COMBAT building within this
        booster's configured range (``"combat"`` tag = the prototype's
        ``_COMBAT_TYPES`` membership)."""
        out = []
        for dc, dr in range_shape.offsets(self.range_tiles(), self.range_shape()):
            tile = tilemap.get(self._col + dc, self._row + dr)
            if tile is None:
                continue
            b = tile.occupant
            if b is not None and getattr(b, "alive", False) and "combat" in b.tags:
                out.append((tile, b))
        return out

    def _adjacent_structures(self, tilemap):
        """(tile, building) for each alive wall-owning structure within this
        booster's configured range — the wall-hp-boost feature's counterpart
        to ``_adjacent_combat``. Duck-typed on ``hasattr(b, "wall_hp")``
        (the ``movement.py`` ``is_movable`` precedent) rather than a tag or
        type string, since ``"structure"`` also covers ``Blocker``, which has
        no walls to boost."""
        out = []
        for dc, dr in range_shape.offsets(self.range_tiles(), self.range_shape()):
            tile = tilemap.get(self._col + dc, self._row + dr)
            if tile is None:
                continue
            b = tile.occupant
            if b is not None and getattr(b, "alive", False) and hasattr(b, "wall_hp"):
                out.append((tile, b))
        return out

    # -- boost application (prototype ``_apply_delta`` per subtype) --------------

    def _apply_delta(self, building, delta):
        """Accumulate ``delta`` of this booster's stat onto ``building``'s receiver.
        HP is the exception: it changes a cached ``Health.max_hp``, so refresh +
        heal by the increase (prototype ``BoostHPBuilding._apply_delta``)."""
        rcv = building.get_component(BoostReceiver)
        if self._boost_stat == "damage":
            rcv.damage_pct += delta
        elif self._boost_stat == "speed":
            rcv.speed_pct += delta
        else:  # "hp"
            rcv.hp_pct += delta
            _refresh_max_hp(building)

    def wall_boost_value(self):
        """Fraction granted to adjacent WALLS per surviving income phase —
        the DEDICATED ``wall_boost_per_turn``/``wall_boost_increase_per_level``
        tier fields (wall-hp-boost feature), independent of ``boost_value()``'s
        combat-building rate. Only meaningful for the HP line; every call site
        below gates on ``self._boost_stat == "hp"`` before reading it."""
        d = self.tier_data()
        return (d["wall_boost_per_turn"]
                + self._lvl_idx * d["wall_boost_increase_per_level"])

    def _apply_wall_delta(self, building, delta):
        """Accumulate ``delta`` onto a WallBuilder's DEDICATED
        ``wall_hp_pct`` accumulator (never ``BoostReceiver``) and resync its
        owned wall edges by the delta (never a full heal — mirrors
        ``_refresh_max_hp``)."""
        building.get_component(WallBuilderState).wall_hp_pct += delta
        building.resync_wall_hp(full_heal=False)

    def apply_per_turn(self, tilemap):
        """RAMP mode: add one turn's boost to every adjacent combat building
        (and, for the HP line, every adjacent WallBuilder's walls).
        Returns ``[(col, row, text)]`` for the payday floater ledger."""
        events = []
        value = self.boost_value()
        for tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, value)
            events.append((tile.col, tile.row, self._vfx_text(value)))
        if self._boost_stat == "hp":
            wall_value = self.wall_boost_value()
            for tile, b in self._adjacent_structures(tilemap):
                self._apply_wall_delta(b, wall_value)
                events.append((tile.col, tile.row, self._vfx_text(wall_value)))
        return events

    def apply_flat(self, tilemap):
        """FLAT mode: apply the one-time permanent 10× boost on placement."""
        flat = self.boost_value() * 10
        for _tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, flat)
        if self._boost_stat == "hp":
            wall_flat = self.wall_boost_value() * 10
            for _tile, b in self._adjacent_structures(tilemap):
                self._apply_wall_delta(b, wall_flat)

    def remove_flat(self, tilemap):
        """FLAT mode: reverse this booster's 10× contribution on death."""
        flat = self.boost_value() * 10
        for _tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, -flat)
        if self._boost_stat == "hp":
            wall_flat = self.wall_boost_value() * 10
            for _tile, b in self._adjacent_structures(tilemap):
                self._apply_wall_delta(b, -wall_flat)

    def _vfx_text(self, value):
        return f"+{value * 100:.0f}%{self._boost_stat[:3]}"


def _refresh_max_hp(building):
    """Re-cache ``Health.max_hp`` from the (boost-folded) computed ``max_hp()`` and
    reconcile current HP: heal by any increase, clamp to any decrease. Mirrors the
    prototype's ``update_stats_from_tier`` recompute without a spurious full-heal."""
    health = building.get_component(Health)
    old_max = health.max_hp
    new_max = building.max_hp()
    health.max_hp = new_max
    if new_max >= old_max:
        health.hp = min(health.hp + (new_max - old_max), new_max)
    else:
        health.hp = min(health.hp, new_max)


class BoostSpeed(BoostBuilding):
    BUILDING_TYPE = "boost_speed"
    CONTENT_KEY = "boost_speed_building"
    SUBTREE = ("BoostBuildings", "Speed")
    TIER_SPRITES = ("boost_speed", "boost_speed", "boost_speed")
    _boost_stat = "speed"
    _boost_color = (100, 160, 255)
    _boost_label = "Spd boost/turn"
    _boost_stat_key = "boost_speed"


class BoostDamage(BoostBuilding):
    BUILDING_TYPE = "boost_damage"
    CONTENT_KEY = "boost_damage_building"
    SUBTREE = ("BoostBuildings", "Damage")
    TIER_SPRITES = ("boost_damage", "boost_damage", "boost_damage")
    _boost_stat = "damage"
    _boost_color = (255, 100, 100)
    _boost_label = "Dmg boost/turn"
    _boost_stat_key = "boost_damage"


class BoostHP(BoostBuilding):
    BUILDING_TYPE = "boost_hp"
    CONTENT_KEY = "boost_hp_building"
    SUBTREE = ("BoostBuildings", "HP")
    TIER_SPRITES = ("boost_hp", "boost_hp", "boost_hp")
    _boost_stat = "hp"
    _boost_color = (255, 150, 200)
    _boost_label = "HP boost/turn"
    _boost_stat_key = "boost_hp"
