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
    (used by Meditators, 10C); Musician yield is a computed method on
    ``EconomyBuilding``. Present as the economy capability marker, symmetric with
    the defence ``Attacker`` marker."""

    streak: int = 0


class PainterProgress(Component):
    """Painter deferred-payout state (Phase 10C, prototype ``PainterBuilding``).
    ``progress`` counts survived round-end cycles (0..``rounds_to_payout``); the
    payday painter slot advances alive painters and, once ``is_ready``, pays the
    lump sum then frees + bars the tile. ``gone_for_good`` is dormant here — a
    painter that DIES before payout is removed at the payday revive step keyed on
    its tier's ``goneforgood`` flag; the field exists so a non-gone-for-good
    variant (none in the current data) could instead reset progress and revive."""

    progress: int = 0
    gone_for_good: bool = False


class BoostReceiver(Component):
    """Boost accumulators + explosion debuffs a COMBAT building carries (Phase
    10D, prototype ``_boost_*_pct`` / ``_explosion_debuffs`` ad-hoc attrs, which
    E-11 forbids here). Present on every defence-family building so a booster can
    write into it; the combat building READS it when computing effective stats:

    - ``damage_pct`` / ``speed_pct`` / ``hp_pct`` — fractions ACCUMULATED each
      surviving income phase by a cardinal-adjacent booster (ramp mode) or once at
      placement (flat mode). Never rolled back when the booster dies (ramp); flat
      mode reverses its own contribution on death.
    - ``explosion_debuffs`` — a booster that DIES stamps a penalty on its
      neighbours "until rebuilt". JSON-safe: a list of
      ``{"col", "row", "stat", "amount"}`` (a Component can't hold a tuple-keyed
      dict), keyed logically by the dead booster's ``(col, row)``. ``stat`` is
      ``"damage"`` / ``"speed"`` (lazy multiplier flags: ×0.5 dmg / ×1.5 spd per
      entry) or ``"hp"`` (``amount`` = the max-HP chunk removed, restored exactly
      when a new booster is placed on that tile).
    """

    damage_pct: float = 0.0
    speed_pct: float = 0.0
    hp_pct: float = 0.0
    explosion_debuffs: list = []

    def hp_penalty(self):
        """Total max-HP removed by ``hp`` explosion debuffs (prototype sum)."""
        return sum(e["amount"] for e in self.explosion_debuffs
                   if e["stat"] == "hp")

    def count_debuffs(self, stat):
        """How many ``stat`` explosion debuffs are active (each applies once —
        the prototype halves damage / ×1.5 slows PER entry)."""
        return sum(1 for e in self.explosion_debuffs if e["stat"] == stat)

    def set_explosion(self, col, row, stat, amount=0):
        """Stamp (or overwrite) the debuff from booster ``(col, row)`` — prototype
        ``_explosion_debuffs[(col,row)] = …`` (same tile overwrites)."""
        self.pop_explosion(col, row)
        self.explosion_debuffs.append(
            {"col": col, "row": row, "stat": stat, "amount": amount})

    def pop_explosion(self, col, row):
        """Remove + return the debuff stamped by booster ``(col, row)`` (or None)."""
        for i, e in enumerate(self.explosion_debuffs):
            if e["col"] == col and e["row"] == row:
                return self.explosion_debuffs.pop(i)
        return None


class BoostEmitter(Component):
    """Marks a boost building (Phase 10D). Its PRESENCE + the ``"boost"`` tag are
    the boost-family capability marker (symmetric with ``Attacker`` /
    ``YieldEconomy``). Carries two guards the payday boost sweep + placement need:

    - ``exploded`` — set when a DEAD booster has already stamped its one explosion
      (reset on revive), so a booster dead across a single payday doesn't
      re-explode or stack. The boost magnitude is a computed method on
      ``BoostBuilding`` (from the tier table), never stored.
    - ``flat_applied`` — in flat mode, whether this booster's one-time 10× boost is
      currently applied to its neighbours, so death-removal is exact + idempotent.
    """

    exploded: bool = False
    flat_applied: bool = False


class SplashAttacker(Component):
    """Marks an AOE (splash) combat building (Phase 10B). Its PRESENCE tells the
    type-agnostic combat sweep to fire the splash path — a fixed-ground-point
    shell that damages every enemy within the building's ``splash_radius`` on
    impact (prototype ``AOEDefenceBuilding``). Carries no state: the radius is a
    computed method on ``AOEDefenceBuilding``, the firing clock lives on the
    shared ``Attacker``. Present alongside ``Attacker`` on AOE buildings."""


class BeamAttacker(Component):
    """Marks a ramping-beam combat building (Phase 10B, prototype
    ``SunScorcherBuilding``). Its PRESENCE routes the combat sweep to the beam
    path (instant hitscan, highest-HP targeting, damage ramp, target-death
    cooldown). ``ramp`` is the accumulated bonus damage on the current target
    (reset to 0 on any target change, capped at the tier's ``dmg_ramp_max``);
    ``death_cooldown`` is the seconds remaining in the post-kill re-acquire
    pause. The current beam target is a transient ref (``_target``), set by the
    sweep and read by the FX layer, symmetric with ``Attacker._target``."""

    ramp: float = 0.0
    death_cooldown: float = 0.0

    def on_added(self, owner):
        # Transient combat refs (never serialized): the enemy the beam is
        # currently on (read by the FX layer) and the enemy the ramp has been
        # accumulating against (the fire step compares to detect a switch).
        self._target = None
        self._ramp_target = None
