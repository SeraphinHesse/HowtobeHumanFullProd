"""Storm Priest — lightning-unlocking defence line (Storm Priest wiring).

Mirrors ``Defender`` in shape: subtree path, type key, per-tier slot prefixes.
Placing one unlocks ``lightning_level`` (see ``game/core/lightning.py``), which
is why it carries the extra ``"lightning_source"`` tag on top of the usual
defence ``"combat"`` tag (``EXTRA_TAGS`` fully OVERRIDES the base — must
re-include ``"combat"`` or this stops counting as a combatant).
"""
from .defence import DefenceBuilding


class StormPriest(DefenceBuilding):
    BUILDING_TYPE = "storm_priest"
    SUBTREE = ("DefenceBuildings", "StormPriest")
    TIER_SPRITES = ("storm_priest_i", "storm_priest_ii", "storm_priest_iii")
    EXTRA_TAGS = ("combat", "lightning_source")
