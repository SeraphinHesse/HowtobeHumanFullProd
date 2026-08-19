"""DefenceBuilding — attacking building family (Phase 9D).

Defender / AOE / Beam share this family; 9D ships the Defender. Its ``Attacker``
component + ``"combat"`` tag replace the prototype's ``IS_COMBAT`` class flag
(SPEC G-3): the core combat sweep (9E) selects combatants by tag, never by type.
9D wires the attack SEAM only — RangeSensor range from the tier table and an
Attacker firing clock. Enemy acquisition, projectiles and damage resolution are
9E, so no enemies are referenced here.
"""
from engine.core import RangeSensor
from .building import Building
from .components import Attacker, BoostReceiver, SplashAttacker


class DefenceBuilding(Building):
    CONTENT_KEY = "defence_building"
    EXTRA_TAGS = ("combat",)

    def _extra_components(self, tier0):
        # BoostReceiver makes this a boostable target (10D): a cardinal-adjacent
        # booster writes its pct here; damage/attack_speed/max_hp read it below.
        # Inert (all zero) until a booster touches it.
        return [Attacker(), RangeSensor(range_tiles=tier0["range_tiles"]),
                BoostReceiver()]

    def damage(self):
        """Base tier damage, lifted by an adjacent ``boost_damage`` and cut by a
        FOREST tile (10I) — order: boost → condition → ``max(1, …)`` (prototype
        ``_effective_damage``, ``defence_building.py:125-147``, minus the removed
        booster-death explosion debuff)."""
        d = self.tier_data()
        base = d["base_dmg"] + self._lvl_idx * d["dmg_per_level"]
        rcv = self.get_component(BoostReceiver)
        dmg = int(base * (1.0 + rcv.damage_pct)) if rcv is not None else base
        # -- 10I: forest damage cut (between the boost multiply + the debuffs) --
        pen = self._condition_mod("def_dmg_penalty")
        if pen:
            dmg = int(dmg * (1.0 - pen))
        # -- /10I --
        return max(1, dmg)

    def range_tiles(self):
        """RAW tier range — NO mountain bonus. This is what feeds defence-range
        pathfinding coverage + the RANGE overlay (10I keeps the raw/effective
        split, prototype ``game.py:601`` / ``:2014``)."""
        return self.tier_data()["range_tiles"]

    # -- 10I: effective range (targeting / panel / selection highlight) -----

    def effective_range_tiles(self):
        """Range after the MOUNTAIN +1 bonus (prototype
        ``defence_building.py:161-168``). Consumed by the panel Range row and
        the selection range highlight (and, except for the mortar, targeting —
        see ``targeting_range_tiles``); pathfinding coverage and the RANGE
        overlay read the RAW ``range_tiles()`` instead."""
        return self.range_tiles() + self._condition_mod("def_range_bonus")

    def targeting_range_tiles(self):
        """Range the combat sweep ACQUIRES targets with. Basic defence + beam
        use the effective (mountain-boosted) value (prototype
        ``defence_building.py:264``); the mortar — selected by its
        ``SplashAttacker`` capability marker, never by class — targets with
        RAW range (prototype ``aoe_defence_building.py:308`` ``_in_range``
        reads raw ``range_tiles``; the mountain bonus only ever shows in its
        panel row). A prototype-inherited inconsistency, kept for parity."""
        if self.get_component(SplashAttacker) is not None:
            return self.range_tiles()
        return self.effective_range_tiles()

    # -- /10I --

    def attack_speed(self):
        """Seconds between shots, sped up by an adjacent ``boost_speed`` and
        slowed by a POND tile (10I, +30% interval) — order: boost → condition
        (prototype ``_effective_attack_speed``, ``defence_building.py:149-159``,
        minus the removed booster-death explosion debuff).
        The shared ``min_attack_speed`` floor is applied by the combat sweep
        (``combat.attack_interval``; the beam floors at ``BEAM_MIN_TICK``)."""
        spd = self.tier_data()["attack_speed"]
        rcv = self.get_component(BoostReceiver)
        if rcv is not None:
            spd *= (1.0 - rcv.speed_pct)
        # -- 10I: pond slows attacks (between the boost multiply + the debuffs) --
        pen = self._condition_mod("def_attack_speed_penalty")
        if pen:
            spd *= (1.0 + pen)
        # -- /10I --
        return spd

    def boosted_stats(self):
        """Original (un-boosted) values for the stats a booster is currently
        lifting — the panel shows the base beside the boosted value (prototype
        ``Building.boosted_stats``). Empty when nothing adjacent is boosting."""
        rcv = self.get_component(BoostReceiver)
        if rcv is None:
            return {}
        d = self.tier_data()
        out = {}
        if rcv.damage_pct:
            out["Damage"] = d["base_dmg"] + self._lvl_idx * d["dmg_per_level"]
        if rcv.hp_pct:
            out["HP"] = d["base_hp"] + self._lvl_idx * d["hp_per_level"]
        if rcv.speed_pct:
            out["Atk speed"] = f'{d["attack_speed"]:.1f}s'
        # -- 10I: a forest cut also shows the un-modified damage beside the
        # cut value — but only when the cut actually changes it (prototype
        # ``defence_building.py:118-122`` gates on effective != base, so a
        # 1-damage defender on forest shows no row) --
        if "Damage" not in out and self._condition_mod("def_dmg_penalty"):
            base_dmg = d["base_dmg"] + self._lvl_idx * d["dmg_per_level"]
            if self.damage() != base_dmg:
                out["Damage"] = base_dmg
        # -- /10I --
        return out

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    def _on_apply_stats(self):
        sensor = self.get_component(RangeSensor)
        if sensor is not None:
            # 10I: the sensor mirrors the TARGETING range (effective for
            # basic/beam, raw for the mortar); raw range keeps feeding
            # pathfinding coverage either way.
            sensor.range_tiles = self.targeting_range_tiles()
