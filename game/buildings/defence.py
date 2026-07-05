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
from .components import Attacker


class DefenceBuilding(Building):
    CONTENT_KEY = "defence_building"
    EXTRA_TAGS = ("combat",)

    def _extra_components(self, tier0):
        return [Attacker(), RangeSensor(range_tiles=tier0["range_tiles"])]

    def damage(self):
        d = self.tier_data()
        return d["base_dmg"] + self._lvl_idx * d["dmg_per_level"]

    def range_tiles(self):
        return self.tier_data()["range_tiles"]

    def attack_speed(self):
        """Seconds between shots (prototype ``attack_speed``)."""
        return self.tier_data()["attack_speed"]

    def upkeep(self):
        d = self.tier_data()
        return d["base_upkeep"] + self._lvl_idx * d["upkeep_per_level"]

    def _on_apply_stats(self):
        sensor = self.get_component(RangeSensor)
        if sensor is not None:
            sensor.range_tiles = self.range_tiles()
