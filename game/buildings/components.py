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
from engine.core import Component, SpriteAnimator


class BuildingSprite(SpriteAnimator):
    """A building's sprite, hidden while the building is DEAD.

    A killed building stays in the scene until the round-end revive
    (``Building.rebuild``) — the payday slots, the explosion debuffs and the XP
    award all read it as ``alive == False``. Only its *visual* should go away,
    so this yields no RenderItem while the owner is dead and comes back by
    itself the moment ``rebuild`` restores HP: nothing to save, nothing to
    restore, no ``slot_key`` to stash (an empty key would draw the grey-X
    placeholder, not nothing). Same "component renders conditionally, no engine
    change" precedent as ``Kidnap.render_items``.

    Kidnapped buildings are exactly this case too: ``begin_kidnap`` only COPIES
    the sprite fields onto the carrier (which redraws them in its arms) and
    leaves the dead victim standing on its tile, so this is what hides it until
    payday revives it.

    ``reveal_delay`` (feature: placement reveal delay) is a PURELY COSMETIC
    countdown, seconds remaining until this sprite starts drawing —
    ``registry.place_building`` stamps it from
    ``BuildingsGlobal.placement_reveal_delay_seconds`` right after placement,
    so the building's occupancy/stats/combat are all live immediately while
    only its VISUAL appearance is held back a beat (giving the placement VFX,
    ``triggers.building_placed``, a moment to play before the sprite itself
    pops in). Payday's revive sweep (``game/core/payday.py`` slot 9) stamps
    the SAME value on a building that just came back from the dead, for the
    same reason and with the same guarantee: the respawn is complete and
    fully live the instant the slot runs — HP, occupancy, boosts, walls — and
    only the sprite waits out the beat while ``triggers.building_respawn``
    plays. It fits inside the INCOME phase (``PhaseLoop`` opens that phase for
    ``income_phase_duration`` = 1.805s, longer than the 1.2s delay), so the
    reveal never spills past the phase it belongs to. It counts down every frame in ``update`` alongside the existing
    animation clock — no host wiring needed, the same "component renders
    conditionally" shape the dead-building guard above already uses; it is
    just a second condition on the same early-return.
    """

    reveal_delay: float = 0.0

    def on_added(self, owner):
        self._owner = owner  # transient back-ref (never serialized)

    def update(self, dt):
        if self.reveal_delay > 0.0:
            self.reveal_delay = max(0.0, self.reveal_delay - dt)
        super().update(dt)

    @property
    def hidden(self):
        """True exactly when this sprite yields no RenderItem.

        The dead-owner and reveal-delay conditions ``render_items`` used to
        early-return on, factored into ONE predicate so an effect drawn
        ALONGSIDE the building can hide on the identical condition instead of
        keeping a second copy that can drift. ``game/ui/effects.py``'s
        ``submit_boost_auras`` is the first such reader: a boost aura behind a
        dead or not-yet-revealed booster must be absent for the same reasons
        the sprite is, and "dead" here also covers kidnapped buildings (they
        are the dead case — see the class docstring).
        """
        owner = getattr(self, "_owner", None)
        if owner is not None and not getattr(owner, "alive", True):
            return True
        return self.reveal_delay > 0.0

    def render_items(self, transform):
        if self.hidden:
            return
        yield from super().render_items(transform)


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
    """Boost accumulators a COMBAT building carries (Phase 10D, prototype
    ``_boost_*_pct`` ad-hoc attrs, which E-11 forbids here). Present on every
    defence-family building so a booster can write into it; the combat building
    READS it when computing effective stats:

    - ``damage_pct`` / ``speed_pct`` / ``hp_pct`` — fractions ACCUMULATED each
      surviving income phase by a cardinal-adjacent booster (ramp mode) or once at
      placement (flat mode). Never rolled back when the booster dies (ramp); flat
      mode reverses its own contribution on death.

    A dead booster used to ALSO stamp a one-shot "explosion" penalty here
    (``explosion_debuffs``); that mechanic is REMOVED — a booster's death now
    only stops (ramp) or reverses (flat) its own contribution.
    """

    damage_pct: float = 0.0
    speed_pct: float = 0.0
    hp_pct: float = 0.0


class BoostEmitter(Component):
    """Marks a boost building (Phase 10D). Its PRESENCE + the ``"boost"`` tag are
    the boost-family capability marker (symmetric with ``Attacker`` /
    ``YieldEconomy``). Carries two guards the payday boost sweep + placement need:

    The boost magnitude is a computed method on ``BoostBuilding`` (from the tier
    table), never stored. One guard the payday boost sweep needs:

    - ``flat_applied`` — in flat mode, whether this booster's one-time 10× boost is
      currently applied to its neighbours, so death-removal is exact + idempotent.
    """

    flat_applied: bool = False


class SplashAttacker(Component):
    """Marks an AOE (splash) combat building (Phase 10B). Its PRESENCE tells the
    type-agnostic combat sweep to fire the splash path — a fixed-ground-point
    shell that damages every enemy within the building's ``splash_radius`` on
    impact (prototype ``AOEDefenceBuilding``). Carries no state: the radius is a
    computed method on ``AOEDefenceBuilding``, the firing clock lives on the
    shared ``Attacker``. Present alongside ``Attacker`` on AOE buildings."""


class WallBuilderState(Component):
    """WallBuilder state (Phase 10E, prototype ``WallBuilderBuilding``). A
    WallBuilder raises a perimeter of destructible EDGE walls when placed; the
    edges themselves live in the map-owned ``TileMap.wall_edges`` registry, but
    the per-builder SNAPSHOT of which edges it raised is frozen here so the
    payday rebuild step can restore destroyed segments without re-deriving the
    perimeter (walls never expand when the player unlocks more tiles later).

    JSON-safe (E-11): a list of ``[c1, r1, c2, r2]`` edge coordinate lists (a
    Component can't hold the prototype's tuple-keyed dict). Empty until the
    builder is placed. No ``walls_need_removal`` flag is needed — the payday
    wall-teardown slot sweeps dead builders directly, exactly like the painter /
    boost slots see a building that died this round as ``alive == False``.

    ``art_era`` (wall-era-art feature) is the FROZEN 1-indexed era the walls'
    art last resolved against (0 = unstamped, i.e. draw the Base tier/level
    art with no era override) — stamped only at placement and at
    upgrade/tier-advance time (``game/core/wall_era.py``), never live off the
    round clock, per the design decision that a wall's look changes only when
    the WallBuilder itself is upgraded.

    ``wall_hp_pct`` (wall-hp-boost feature) is a DEDICATED accumulator for the
    fraction an adjacent HP booster has added to ``wall_hp()`` — deliberately
    separate from ``BoostReceiver.hp_pct`` (which only combat buildings carry)
    so a WallBuilder's own body HP is never affected, only the walls it owns.

    A dead HP booster used to ALSO stamp a one-shot wall-HP penalty here
    (``wall_hp_debuffs``); that mechanic is REMOVED alongside its
    ``BoostReceiver`` twin."""

    wall_snapshot: list = []
    art_era: int = 0
    wall_hp_pct: float = 0.0


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
