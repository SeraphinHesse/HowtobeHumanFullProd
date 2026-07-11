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
from .components import Attacker, BoostReceiver


class DefenceBuilding(Building):
    CONTENT_KEY = "defence_building"
    EXTRA_TAGS = ("combat",)

    def _extra_components(self, tier0):
        # BoostReceiver makes this a boostable target (10D): a cardinal-adjacent
        # booster writes its pct + explosion debuffs here; damage/attack_speed/
        # max_hp read it below. Inert (all zero) until a booster touches it.
        return [Attacker(), RangeSensor(range_tiles=tier0["range_tiles"]),
                BoostReceiver()]

    def damage(self):
        """Base tier damage, lifted by an adjacent ``boost_damage`` and halved per
        ``boost_damage`` explosion debuff (prototype ``_effective_damage``)."""
        d = self.tier_data()
        base = d["base_dmg"] + self._lvl_idx * d["dmg_per_level"]
        rcv = self.get_component(BoostReceiver)
        if rcv is None:
            return base
        dmg = int(base * (1.0 + rcv.damage_pct))
        for _ in range(rcv.count_debuffs("damage")):
            dmg = max(1, dmg // 2)
        return max(1, dmg)

    def range_tiles(self):
        return self.tier_data()["range_tiles"]

    def attack_speed(self):
        """Seconds between shots, sped up by an adjacent ``boost_speed`` and slowed
        ×1.5 per ``boost_speed`` explosion debuff (prototype
        ``_effective_attack_speed``). The shared ``min_attack_speed`` floor is
        applied by the combat sweep (``combat.attack_interval``)."""
        spd = self.tier_data()["attack_speed"]
        rcv = self.get_component(BoostReceiver)
        if rcv is None:
            return spd
        spd *= (1.0 - rcv.speed_pct)
        for _ in range(rcv.count_debuffs("speed")):
            spd *= 1.5
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
        return out

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    def _on_apply_stats(self):
        sensor = self.get_component(RangeSensor)
        if sensor is not None:
            sensor.range_tiles = self.range_tiles()
