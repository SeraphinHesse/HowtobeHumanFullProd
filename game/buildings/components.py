"""Building state components (Phase 9D).

ALL authoritative building state lives here — the engine E-11 rule forbids a
GameObject subclass from holding public instance state (the editor inspector and
save/load read components, not subclass attributes). Every derived value
(max_hp, damage, yield, costs) is a computed method on the Building hierarchy
from ``TierState`` + balancing data, never stored.

Only the components Musician / Defender / BaseBuilding need in 9D are defined;
the rest of the family (BoostReceiver, PainterProgress, WallBuilderState, …)
arrive with their buildings (10x).
"""
from engine.core import Component


class TierState(Component):
    """The tier/level cursor + type tag. ``building_type`` is the duck-typed key
    the pathfinder (``occupant.building_type``) and the registry read;
    ``current_tier`` is 0-indexed, ``current_level_in_tier`` is 1-indexed
    (prototype ``Building`` exact)."""

    building_type: str = ""
    current_tier: int = 0
    current_level_in_tier: int = 1


class Nameplate(Component):
    """Custom name + rebirth-generation chain (prototype ``Building.rebuild``
    naming: a named building that dies is reborn as "<base> the 2nd", etc.)."""

    custom_name: str = ""
    rebirth_base: str = ""
    rebirth_gen: int = 0


class RoundStats(Component):
    """Per-round damage bookkeeping. ``dmg_dealt_last_round`` backs the tile
    damage-weight discount that ``TileMap.refresh_damage_weight_reductions``
    reads (activated 10F); the "this round" fields roll over at payday (9F)."""

    dmg_dealt_this_round: int = 0
    dmg_dealt_last_round: int = 0
    dmg_taken_this_round: int = 0
    dmg_taken_last_round: int = 0


class Attacker(Component):
    """Marks a combat building. Its PRESENCE plus the ``"combat"`` tag replaces
    the prototype's ``IS_COMBAT`` class flag (SPEC G-3) so the core combat sweep
    stays type-agnostic. Holds only the firing clock in 9D; enemy acquisition,
    projectiles and damage resolution land in 9E."""

    cooldown: float = 0.0
    has_target: bool = False


class YieldEconomy(Component):
    """Marks a love-yielding building. ``streak`` is dormant for Musicians
    (used by Meditators, 10B); Musician yield is a computed method on
    ``EconomyBuilding``. Present as the economy capability marker, symmetric with
    the defence ``Attacker`` marker."""

    streak: int = 0
