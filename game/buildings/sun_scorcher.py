"""Sun Scorcher — the ramping-beam defence line (Phase 10B).

Sun Scorcher -> Radiant Beam -> Laser Beam (``DefenceBuildings.BeamDefence``).
Ports the prototype's ``SunScorcherBuilding``: an instant hitscan beam that locks
the highest-HP enemy in range and ramps its damage while focused, resetting on
any target change and pausing (target-death cooldown) after a kill. The beam
resolution lives in the type-agnostic combat sweep (``game/enemies/combat.py``),
routed by the ``BeamAttacker`` marker this building carries; the leaf declares its
identity + wires the marker + exposes the ramp/cooldown tunables from balancing.
"""
from functools import reduce

from .components import BeamAttacker
from .defence import DefenceBuilding


class SunScorcher(DefenceBuilding):
    BUILDING_TYPE = "sun_scorcher"
    SUBTREE = ("DefenceBuildings", "BeamDefence")
    TIER_SPRITES = ("sun_scorcher", "radiant_beam", "laser_beam")

    def _extra_components(self, tier0):
        return super()._extra_components(tier0) + [BeamAttacker()]

    def ramp_per_tick(self):
        """Bonus damage added to the ramp each tick sustained on one target."""
        return self.tier_data()["dmg_ramp_per_tick"]

    def ramp_max(self):
        """Cap on the accumulated ramp bonus (prototype ``dmg_ramp_max``)."""
        return self.tier_data()["dmg_ramp_max"]

    def target_death_cooldown(self):
        """Seconds the beam pauses re-acquiring after its target dies (group-level
        ``BeamDefence.target_death_cooldown`` — not per tier)."""
        node = reduce(lambda d, k: d[k], self.SUBTREE, self._balance)
        return node["target_death_cooldown"]
