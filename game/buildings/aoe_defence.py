"""AOE Mortar — the splash-damage defence line (Phase 10B).

Maw Mortar -> Maw Catapult -> Maw Cannon (``DefenceBuildings.AOEDefence``).
Ports the prototype's ``AOEDefenceBuilding``: a mortar that arcs a shell to a
FIXED ground point (predictive lead) and damages every enemy within
``splash_radius`` on impact — the actual splash resolution lives in the
type-agnostic combat sweep (``game/enemies/combat.py``), routed by the
``SplashAttacker`` marker this building carries. The leaf only declares its
identity + wires the marker + computes its radius from the tier table.
"""
from .components import SplashAttacker
from .defence import DefenceBuilding


class AOEDefenceBuilding(DefenceBuilding):
    BUILDING_TYPE = "aoe_defence"
    CONTENT_KEY = "aoe_defence_building"   # its own pathfinder content weight
    SUBTREE = ("DefenceBuildings", "AOEDefence")
    TIER_SPRITES = ("maw_mortar", "maw_mortar", "maw_mortar")

    def _extra_components(self, tier0):
        return super()._extra_components(tier0) + [SplashAttacker()]

    def splash_radius(self):
        """Splash radius in TILES (prototype ``aoe_radius``); the sweep's impact
        hits every enemy within this Euclidean distance of the landing point."""
        d = self.tier_data()
        return d["base_radius"] + self._lvl_idx * d["radius_per_level"]
