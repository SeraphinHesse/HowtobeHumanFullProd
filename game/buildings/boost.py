"""Boost buildings — the cardinal-adjacency buff/curse support line (Phase 10D).

Ports the prototype's ``BoostBuilding`` family (``src/buildings/boost_building.py``).
A booster buffs the COMBAT buildings on its four cardinal neighbours (plus-shape,
range 1) — never economy, never another booster, never diagonals. Three data lines
share ONE behaviour class; the leaves are pure identity:

  ``boost_speed``  — reduces neighbours' ``attack_speed`` (faster attacks)
  ``boost_damage`` — raises neighbours' ``damage``
  ``boost_hp``     — raises neighbours' ``max_hp``

Two modes (``BoostBuildings.globals.flat_mode``): RAMP (default) accumulates a
little every surviving income phase; FLAT applies a one-time 10× boost on placement,
reversed on death. Either way, a booster that DIES stamps an "explosion" debuff on
its neighbours until a new booster is placed on the same tile.

All the buff/curse state lives on the NEIGHBOUR's ``BoostReceiver`` component (E-11
— no ad-hoc attrs); this class only pushes deltas into it. The booster's own state
is a ``BoostEmitter`` marker + the computed ``boost_value`` from the tier table.
Orchestration (the per-turn sweep, explosion-on-death, placement adjacency block +
debuff clearing) lives in ``game/core/payday.py`` and ``game/buildings/registry.py``
— exactly where the prototype's ``Game`` drove it.
"""
from engine.core import Health

from .building import Building
from .components import BoostEmitter, BoostReceiver

# Cardinal-only plus-shape (prototype ``_PLUS_DIRS``): no diagonals.
_PLUS_DIRS = ((0, -1), (0, 1), (-1, 0), (1, 0))


class BoostBuilding(Building):
    """Family base: identity is set by the three leaves, behaviour lives here."""

    CONTENT_KEY = "economic_building"   # prototype boost tiles fall back to the
                                        # economy pathfinding weight (traversable, 1)
    EXTRA_TAGS = ("boost",)

    # Set by leaves:
    _boost_stat = None      # "damage" | "speed" | "hp" — which receiver accumulator
    _boost_color = (255, 255, 255)
    _boost_label = "Boost/turn"

    def _extra_components(self, tier0):
        return [BoostEmitter()]

    def flat_mode(self):
        """Global ramp-vs-flat switch (``BoostBuildings.globals.flat_mode``): False
        accumulates a little each income phase, True applies a one-time 10× boost on
        placement (removed on death)."""
        return self._balance["BoostBuildings"]["globals"]["flat_mode"]

    def on_placed(self, tilemap):
        """Post-placement hook (prototype ``Game._on_boost_placed``): clear any
        explosion debuffs the previous occupant of this tile left on neighbours,
        and in flat mode apply this booster's one-time 10× boost immediately."""
        self.clear_explosion_debuff_from(self._col, self._row, tilemap)
        if self.flat_mode():
            self.apply_flat(tilemap)
            self.get_component(BoostEmitter).flat_applied = True

    # -- computed stats (prototype ``update_stats_from_tier`` boost_value/upkeep) --

    def boost_value(self):
        """Fraction granted per surviving income phase at the current level."""
        d = self.tier_data()
        return d["boost_per_turn"] + self._lvl_idx * d["boost_increase_per_level"]

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    def rebuild(self):
        """Round-end revive (prototype ``Building.rebuild``) + clear the one-shot
        explosion guard so a booster that dies again later explodes again."""
        super().rebuild()
        self.get_component(BoostEmitter).exploded = False

    # -- adjacency (prototype ``adjacent_tiles`` / ``_adjacent_combat_buildings``) --

    def _adjacent_combat(self, tilemap):
        """(tile, building) for each alive COMBAT building on a cardinal neighbour
        (``"combat"`` tag = the prototype's ``_COMBAT_TYPES`` membership)."""
        out = []
        for dc, dr in _PLUS_DIRS:
            tile = tilemap.get(self._col + dc, self._row + dr)
            if tile is None:
                continue
            b = tile.occupant
            if b is not None and getattr(b, "alive", False) and "combat" in b.tags:
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

    def apply_per_turn(self, tilemap):
        """RAMP mode: add one turn's boost to every adjacent combat building.
        Returns ``[(col, row, text)]`` for the payday floater ledger."""
        events = []
        value = self.boost_value()
        for tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, value)
            events.append((tile.col, tile.row, self._vfx_text(value)))
        return events

    def apply_flat(self, tilemap):
        """FLAT mode: apply the one-time permanent 10× boost on placement."""
        flat = self.boost_value() * 10
        for _tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, flat)

    def remove_flat(self, tilemap):
        """FLAT mode: reverse this booster's 10× contribution on death."""
        flat = self.boost_value() * 10
        for _tile, b in self._adjacent_combat(tilemap):
            self._apply_delta(b, -flat)

    # -- explosion debuff on death (prototype ``_set_explosion_debuff``) ---------

    def apply_explosion_debuff(self, tilemap):
        """On death: stamp the penalty on adjacent alive combat buildings. Speed /
        damage are lazy multiplier flags; HP removes half of current max HP,
        stored so a rebuild can restore it exactly."""
        for _tile, b in self._adjacent_combat(tilemap):
            rcv = b.get_component(BoostReceiver)
            if self._boost_stat == "hp":
                health = b.get_component(Health)
                penalty = max(1, health.max_hp // 2)
                rcv.set_explosion(self._col, self._row, "hp", penalty)
                _refresh_max_hp(b)
            else:
                rcv.set_explosion(self._col, self._row, self._boost_stat)

    def clear_explosion_debuff_from(self, col, row, tilemap):
        """A new booster placed at ``(col, row)`` clears the debuffs the previous
        one stamped on its neighbours (prototype ``clear_explosion_debuff_from``).
        Only the HP case restores state (re-add the removed max-HP chunk + heal)."""
        for dc, dr in _PLUS_DIRS:
            tile = tilemap.get(col + dc, row + dr)
            if tile is None or tile.occupant is None:
                continue
            rcv = tile.occupant.get_component(BoostReceiver)
            if rcv is None:
                continue
            entry = rcv.pop_explosion(col, row)
            if entry is not None and entry["stat"] == "hp":
                _refresh_max_hp(tile.occupant)

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
    SUBTREE = ("BoostBuildings", "Speed")
    TIER_SPRITES = ("boost_speed", "boost_speed", "boost_speed")
    _boost_stat = "speed"
    _boost_color = (100, 160, 255)
    _boost_label = "Spd boost/turn"


class BoostDamage(BoostBuilding):
    BUILDING_TYPE = "boost_damage"
    SUBTREE = ("BoostBuildings", "Damage")
    TIER_SPRITES = ("boost_damage", "boost_damage", "boost_damage")
    _boost_stat = "damage"
    _boost_color = (255, 100, 100)
    _boost_label = "Dmg boost/turn"


class BoostHP(BoostBuilding):
    BUILDING_TYPE = "boost_hp"
    SUBTREE = ("BoostBuildings", "HP")
    TIER_SPRITES = ("boost_hp", "boost_hp", "boost_hp")
    _boost_stat = "hp"
    _boost_color = (255, 150, 200)
    _boost_label = "HP boost/turn"
