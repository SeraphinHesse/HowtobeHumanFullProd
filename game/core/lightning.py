"""Lightning strike ability (Phase 10H; Storm Priest rework; feature-storm-
acolyte-multi-build) — pure rules + the strike FX object + the Storm Priest's
``LightningCaster`` puppeting/cooldown.

Ports the prototype's lightning fields on ``Game`` (``game.py:116-119``),
``_handle_lightning_click`` / ``_activate_lightning`` (``game.py:492-514``)
and the cooldown tick (``game.py:1243-1246``). Every gameplay tunable comes
from ``core.json`` ``LightningStrike`` (cooldown/damage/radius per level,
max_level); the two FX lifetimes are cosmetic and come from
``data/balancing/vfx.json`` ``procedural.lightning.bolt_life``/``marker_life``
(ESV-3b) via ``strike()``'s ``vfx`` argument — never touching this file's
gameplay tunables, and never simulation timing (D4). The caster's "attack"-pose
hold duration is ``core.json`` ``LightningStrike.attack_hold_seconds``, index-
aligned with cooldown/damage/radius per level (feature: storm-acolyte-attack-
hold-duration) — not a code constant; it defaults to the same seconds as
``cooldown`` so the pose covers the whole reload window, but is an ordinary
per-tier balancing value a designer can retune.

**BossUpgradeTimelinePLAN BU-3 3.3 — upgrade #7 ``stormpriest_slow``.**
``strike()`` grows an optional trailing ``boss_upgrades_balance`` (the BALANCE
half of the standard BU-3 pair — ``state`` already IS the ``RunState``, the
documented ``place_building`` exception) and, when the upgrade has been picked,
slows every enemy a bolt damages. The debuff PRIMITIVE lives with ``BuffState``
in ``game.enemies.components`` (D19) and reaches this module through the
host-installed ``set_slow_hook`` seam, NEVER an import: ``game/core`` imports
nothing from ``game/enemies``, and that rule is not relaxed for a status
effect. See ``_SLOW_HOOK`` below.

**Radius semantics** (prototype ``game.py:505-508``): the blast is a Euclidean
CIRCLE in the PROJECTED pixel plane — ``radius_px = radius_tiles * TILE_HW``
around the click, hit-tested on projected coordinates. It is NOT the Chebyshev
defender range and NOT tile-space Euclidean like the mortar splash. Both the
strike point and each enemy are projected through the coords authority
(``cs.world_to_screen``): the camera pan cancels in the delta and zoom scales
the threshold linearly, so ``radius_tiles * tile_w / 2 * zoom`` is exact and
no iso math leaks out of ``engine.coords``.

**feature-storm-acolyte-multi-build: the cooldown moved OFF ``RunState`` and
ONTO ``LightningCaster`` — one clock per placed acolyte, not one clock for
the whole run.** ``RunState.lightning_level`` STAYS, with its existing
latching-max semantics, but its meaning NARROWS to "is lightning unlocked /
what is the best tier ever placed" — a pure UI/gating signal. Nothing here
reads it for damage/radius/cooldown any more; every fired bolt reads those
off the FIRING BUILDING's own ``tier_number()``. ``tick``/``can_strike`` both
gained a required ``scene`` argument for this reason — they now walk
``scene.by_tag("lightning_source")`` instead of a single state field.
``strike()`` fires EVERY alive, ready caster at the clicked point in one
click, each contributing its own tier's damage/radius/cooldown and spawning
its OWN ``LightningFX`` marker (several nested rings landing together reads
as several bolts, and is honest about which tiers actually contributed) —
the old "stop after the first ``lightning_source``" ``break`` is gone.

State lives on ``RunState`` (``lightning_level`` only now) + each acolyte's
own ``LightningCaster.cooldown``; this module is pure functions over them
plus ``LightningFX`` (the ``Crater`` pattern: it ages in ``scene.update`` —
i.e. on the host's ENEMY-scaled sim dt, prototype-exact — self-despawns at
its own ``marker_life``, and the FX layer just draws it). Damage pays no
``RoundStats`` credit — lightning has no shooter; kills flow through the next
``resolve_combat`` sweep's ``on_enemy_death``, so they pay XP and count as
kills like any other kill.

**Storm Priest rework**: there is no love-priced level-up any more
(``next_cost``/``upgrade`` are gone). Leveling is driven entirely by each
Storm Priest's own tier, via ``sync_level_from_tier`` (called from
``game/ui/building_ui.py``'s tier-advance branch), and ``strike()`` puppets
each firing Storm Priest's ``SpriteAnimator`` into its "attack" pose through
its own ``LightningCaster`` component (since the building itself no longer
fires in combat — it dropped the ``"combat"`` tag).
"""
from engine.core import Component, GameObject, Health, SpriteAnimator, Transform

# Cosmetic FX lifetimes — declared-field FALLBACKS only (the Component base
# requires a default per field); the runtime source of truth is
# data/balancing/vfx.json procedural.lightning.bolt_life/marker_life
# (ESV-3b), threaded through strike()'s required vfx argument. Kept here as
# the CraterFade-style precedent literal and so a bare LightningFXFade()
# built with no override still has a sane value.
BOLT_LIFE = 0.5     # seconds the jagged bolt is drawn
MARKER_LIFE = 1.0   # seconds the ground marker fades over, then despawns


def tick(state, dt, scene):
    """Drain every alive ``lightning_source``'s OWN caster cooldown toward 0.
    The CALLER decides when it ticks — ``Session.pre_sim``'s ENEMY branch
    ONLY, on the speed-scaled sim dt (prototype game.py:1243-1246): 2x drains
    it twice as fast, the in-combat pause freezes it, and it persists frozen
    across every other phase. **Do not move this into ``LightningCaster.
    update(dt)``** — that runs from ``scene.update`` in EVERY phase and would
    silently break the "cooldown frozen outside ENEMY" rule this tick site
    exists to enforce. ``state`` is unused here (kept for signature symmetry
    with ``can_strike``/``strike`` — every lightning entry point takes the
    same leading args)."""
    for b in scene.by_tag("lightning_source"):
        if not getattr(b, "alive", False):
            continue
        caster = b.get_component(LightningCaster)
        if caster is not None and caster.cooldown > 0:
            caster.cooldown = max(0.0, caster.cooldown - dt)


def reset_all_cooldowns(scene):
    """Zero every alive ``lightning_source``'s OWN cooldown (feature:
    storm-acolyte-round-start-reset). Called once by ``Session.end_turn()``
    at the BUILDING -> ENEMY edge, so every placed Storm Priest is ready to
    fire the moment a new round's enemies start attacking, regardless of how
    much cooldown it had left over from the previous round. Each caster keeps
    its own independent per-tier cooldown otherwise (feature-storm-acolyte-
    multi-build) — this is a synchronized RESET, not a shared clock."""
    for b in scene.by_tag("lightning_source"):
        if not getattr(b, "alive", False):
            continue
        caster = b.get_component(LightningCaster)
        if caster is not None:
            caster.cooldown = 0.0


def can_strike(state, scene):
    """True while lightning is unlocked (``state.lightning_level > 0``) AND
    at least one alive ``lightning_source`` is off cooldown — a click with
    every acolyte still charging is a silent no-op, same as the old single-
    caster gate."""
    if state.lightning_level <= 0:
        return False
    for b in scene.by_tag("lightning_source"):
        if not getattr(b, "alive", False):
            continue
        caster = b.get_component(LightningCaster)
        if caster is not None and caster.cooldown <= 0:
            return True
    return False


def unlock_from_placement(state, building):
    """Raise ``lightning_level`` to (at least) 1 when a freshly placed
    building carries the ``"lightning_source"`` tag (Storm Priest wiring).

    Tag-gated, NOT type-string-gated — keeps ``registry.place_building`` and
    this seam type-agnostic, the same convention the ``"combat"``/``"boost"``
    tags already use elsewhere in ``game/buildings``. Latch semantics: a
    ``max()`` never re-locks an already-unlocked run (idempotent across a
    batch place, and safe to call again after later upgrades)."""
    if "lightning_source" in building.tags:
        state.lightning_level = max(state.lightning_level, 1)


def sync_level_from_tier(state, building):
    """Raise ``lightning_level`` to match a ``lightning_source`` building's
    current tier (Storm Priest wiring): tier 1/2/3 -> lightning level 1/2/3.
    Tag-gated like ``unlock_from_placement``; latch semantics (``max()``)
    so a re-sync (or a batch call) never lowers an already-higher level.
    Called from ``game.ui.building_ui``'s tier-advance branch."""
    if "lightning_source" in building.tags:
        state.lightning_level = max(state.lightning_level, building.tier_number())


#: BossUpgradeTimelinePLAN BU-3 3.3 (#7 stormpriest_slow): the opaque
#: ``BuffState`` source key every bolt's slow is written under. ONE key for the
#: whole UPGRADE, never one per firing acolyte — several casters landing on the
#: same enemy in one click must read as one slow, not N stacked ones (see
#: ``game/enemies/components.py``'s ``apply_slow``). Repeat PICKS still stack,
#: additively (D4), inside the fraction ``_slow_spec`` computes.
STORMPRIEST_SLOW_SOURCE = "boss_upgrade:stormpriest_slow"

#: The injected applier for that slow — ``fn(enemy, source, fraction,
#: duration) -> bool``. Unset by default, so a bare import of this module
#: changes nothing and every logic test that never installs one sees the
#: pre-BU-3 strike exactly.
#:
#: **It is a seam and not an import because `game/core` imports NOTHING from
#: `game/enemies`** — the same hard layering rule the ER-3 death-spawn
#: handshake and `Session.on_enemy_death`'s callbacks exist to honour. The
#: debuff primitive itself is `game.enemies.components.apply_slow` (D19: one
#: shared slow mechanism, living with `BuffState`), so it arrives the way
#: every other cross-package capability does: installed by the HOST, which is
#: the one layer allowed to import both packages —
#:
#:     # game/main.py's boot:
#:     lightning.set_slow_hook(apply_slow)
#:
#: the `boss_upgrades.set_one_time_hook` / `components.set_damage_hook` /
#: `widgets.set_skin_hit_test` precedent exactly.
_SLOW_HOOK = None


def set_slow_hook(fn):
    """Install (or clear, with ``fn=None``) the injected slow applier — see
    ``_SLOW_HOOK`` above for why this is a seam rather than an import.

    Today's ONE intended caller is ``game/main.py``'s boot, handing over
    ``game.enemies.components.apply_slow`` for boss upgrade #7
    ``stormpriest_slow``.
    """
    global _SLOW_HOOK
    _SLOW_HOOK = fn


def _slow_spec(state, boss_upgrades_balance):
    """``(source, slow_fraction, duration_seconds)`` for boss upgrade #7
    ``stormpriest_slow``, or ``None`` when it is inert.

    Unlike ``mortar_slow`` (#3) there is NO snapshot: once picked, every bolt
    from every acolyte slows, whenever the Storm Priest was built. Resolved
    ONCE per ``strike`` call rather than per enemy — the answer cannot change
    inside one click, and this keeps the per-enemy inner loop a single
    ``is not None`` test.

    ``state`` IS the ``RunState``, so this hook takes only the BALANCE half of
    the standard BU-3 pair — the documented ``place_building`` exception
    (``game/core/boss_upgrades.py``'s threading-pattern section): a hook site
    that already carries the run state never grows a second, duplicate
    reference to it.
    """
    from game.core import boss_upgrades

    n, params = boss_upgrades.hook_stacks(state, boss_upgrades_balance,
                                          "stormpriest_slow")
    if not n:
        return None
    return (STORMPRIEST_SLOW_SOURCE,
            n * params.get("slow_pct", 20) / 100.0,
            params.get("duration_seconds", 2.5))


def strike(state, core, vfx, scene, cs, wx, wy, on_hit=None,
           boss_upgrades_balance=None):
    """Strike world point ``(wx, wy)`` (prototype ``_activate_lightning``,
    game.py:502-514 — feature-storm-acolyte-multi-build generalises it to
    every ready caster). Silent no-op (``False``) while locked or every
    caster is cooling. Otherwise: EVERY alive, ready ``lightning_source``
    fires, each contributing its OWN tier's flat damage to every alive enemy
    inside its OWN tier's projected-plane circle (no falloff, no target cap,
    no love cost) and spawning its OWN ``LightningFX`` marker (several
    nested rings landing together — honest about which tiers actually
    contributed). Each firing caster's cooldown is spent UNCONDITIONALLY — a
    whiff that hits nothing still pays it and still shows the VFX — and its
    ``SpriteAnimator`` flashes to "attack". Any world point is a valid
    target: no tile/zone/bounds check, no enemies-required check.

    ``vfx`` (ESV-3b, required — no default, G-7): the loaded ``vfx.json``
    dict, read for the two cosmetic fade lifetimes
    (``procedural.lightning.bolt_life``/``marker_life``) each spawned
    ``LightningFX`` is built with — never the damage/radius/cooldown above,
    which stay ``core.json`` ``LightningStrike`` (unchanged by this phase),
    indexed by EACH FIRING BUILDING's own ``tier_number()`` rather than
    ``state.lightning_level`` — the run-wide level is a UI/gating signal
    only now, never a damage source.

    ``on_hit`` (debug-mode-telemetry, optional — additive, ``None`` keeps
    every existing caller byte-identical): called as ``on_hit(dmg)`` once per
    enemy actually damaged, across every firing caster. Lightning earns no
    ``RoundStats`` credit (no shooter), so this is the ONLY place a per-strike
    damage/hit total can be counted — ``Session.lightning_strike`` sums it
    into ``DebugRecorder.note_lightning``. Never changes what gets damaged or
    by how much; it is a read of a value already about to be applied.

    ``boss_upgrades_balance`` (BossUpgradeTimelinePLAN BU-3 3.3, optional):
    the BALANCE half of the standard BU-3 hook pair — ``state`` already IS the
    ``RunState``, so this is the documented ``place_building`` exception rather
    than a second reference to it. ``None`` (every pre-BU-3 caller and every
    test in this module) keeps the strike byte-identical; present, it arms
    ``stormpriest_slow`` (#7), which applies a timed move-speed slow to every
    enemy the bolt damages — no snapshot, every acolyte, from the pick on."""
    if not can_strike(state, scene):
        return False
    ls = core["LightningStrike"]
    lp = vfx["procedural"]["lightning"]
    # BU-3 3.3 (#7): resolved once per click, before the caster loop — the
    # answer cannot change inside one strike, and this keeps the per-enemy
    # inner loop to a single `is not None` test. No installed hook (a bare
    # logic test, a headless tool) is as inert as an unpicked upgrade.
    slow = (None if boss_upgrades_balance is None or _SLOW_HOOK is None
            else _slow_spec(state, boss_upgrades_balance))
    sx, sy = cs.world_to_screen(wx, wy)
    fired = False
    for b in scene.by_tag("lightning_source"):
        if not getattr(b, "alive", False):
            continue
        caster = b.get_component(LightningCaster)
        if caster is None or caster.cooldown > 0:
            continue   # this acolyte is still charging: it sits this one out
        idx = b.tier_number() - 1
        dmg = ls["damage"][idx]
        radius_tiles = ls["radius"][idx]
        radius_px = radius_tiles * cs.geometry.tile_w / 2 * cs.camera.zoom
        for enemy in scene.by_tag("enemy"):
            # BR-3/D2: an untargetable enemy (a boss staging its second phase)
            # is immune to EVERY damage source, the storm included — the same
            # duck-typed `targetable` the combat sweep reads.
            if (not getattr(enemy, "alive", False)
                    or not getattr(enemy, "targetable", True)):
                continue
            # ER-2/AoE parity: hit-test against the true rendered BLOCK
            # CENTRE (footprint-aware), not the raw anchor tile — the same
            # point every other AoE-circle damage check (e.g. the mortar's
            # splash radius) already measures from. `world_pos` and
            # `center_world` coincide at footprint 1, so this is a no-op for
            # every enemy but the boss. NOT named `wx`/`wy` — those are the
            # STRIKE's own click-point parameters; shadowing them here once
            # corrupted the `LightningFX` marker built after this loop into
            # spawning at the last enemy iterated instead of the click.
            ewx, ewy = (getattr(enemy, "center_world", None)
                       or enemy.transform.world_pos)
            ex, ey = cs.world_to_screen(ewx, ewy)
            if (ex - sx) ** 2 + (ey - sy) ** 2 <= radius_px ** 2:
                enemy.get_component(Health).damage(dmg)
                if on_hit is not None:
                    on_hit(dmg)
                # BU-3 3.3 (#7 stormpriest_slow): right after the damage
                # line, on every enemy this bolt actually hit, through the
                # host-installed seam above. The applier itself is a no-op
                # for an owner with no `BuffState`, so a stub enemy in a
                # headless test is safe.
                if slow is not None:
                    _SLOW_HOOK(enemy, *slow)
        caster.cooldown = ls["cooldown"][idx]
        fx = LightningFX(wx, wy, radius_tiles, lp["bolt_life"], lp["marker_life"])
        fx.get_component(LightningFXFade)._scene = scene
        scene.spawn(fx)
        caster.trigger(ls["attack_hold_seconds"][idx])
        fired = True
    return fired


class LightningCaster(Component):
    """Per-acolyte ability state (feature-storm-acolyte-multi-build): its OWN
    cooldown clock — drained only by ``tick()``'s ENEMY-phase sweep, never by
    ``update(dt)`` (that runs every phase and would break the "cooldown
    frozen outside ENEMY" rule) — plus puppeting this building's own
    SpriteAnimator: flips to "attack" when IT fires (nothing else drives its
    animation any more since Storm Priest dropped the "combat" tag),
    reverting to "idle" ``trigger()``'s ``hold_seconds`` argument later (the
    caller resolves it from ``core.json`` ``LightningStrike.
    attack_hold_seconds``, per firing tier)."""

    cooldown: float = 0.0
    flash_timer: float = 0.0

    def on_added(self, owner):
        self._owner = owner

    def update(self, dt):
        if self.flash_timer > 0:
            self.flash_timer = max(0.0, self.flash_timer - dt)
            if self.flash_timer == 0.0:
                anim = self._owner.get_component(SpriteAnimator)
                if anim is not None:
                    anim.set_animation("idle")

    def trigger(self, hold_seconds):
        self.flash_timer = hold_seconds
        anim = self._owner.get_component(SpriteAnimator)
        if anim is not None:
            anim.set_animation("attack")


class LightningFXFade(Component):
    """The strike marker's age clock (the ``CraterFade`` mirror). Purely
    cosmetic — ages to ``marker_life`` in ``scene.update`` then despawns its
    owner; the FX layer reads ``radius_tiles`` + the owner's fade fractions.

    ``bolt_life``/``marker_life`` (ESV-3b): declared fields, fed from
    ``data/balancing/vfx.json`` (``procedural.lightning.bolt_life``/
    ``marker_life``) via ``strike()``. The class defaults (``BOLT_LIFE``/
    ``MARKER_LIFE``) are only the declared-field fallback the ``Component``
    base requires — every production path (``strike``) sets both explicitly
    at construction."""

    radius_tiles: float = 0.0
    age: float = 0.0
    bolt_life: float = BOLT_LIFE
    marker_life: float = MARKER_LIFE

    def on_added(self, owner):
        self._owner = owner
        self._scene = None

    def update(self, dt):
        self.age += dt
        if self.age >= self.marker_life:
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(self._owner)


class LightningFX(GameObject):
    """A cosmetic strike marker at the impact point (Phase 10H). Logical only;
    ``game/ui/effects.py submit_lightning`` draws the bolt while
    ``bolt_frac > 0`` and the fading ground diamond from ``fade_frac``.

    ``bolt_life``/``marker_life`` (ESV-3b, required — no default, G-7): the
    two cosmetic fade lifetimes, always supplied by the one caller
    (``strike()``) from its balancing-authored ``vfx`` argument."""

    def __init__(self, wx, wy, radius_tiles, bolt_life, marker_life):
        super().__init__(
            name="lightning_fx",
            tags=("lightning_fx",),
            transform=Transform(wx=wx, wy=wy, layer="overlay"),
            components=[LightningFXFade(radius_tiles=float(radius_tiles),
                                        bolt_life=bolt_life,
                                        marker_life=marker_life)],
        )

    @property
    def radius_tiles(self):
        return self.get_component(LightningFXFade).radius_tiles

    @property
    def age(self):
        return self.get_component(LightningFXFade).age

    @property
    def bolt_frac(self):
        """1.0 fresh -> 0.0 at ``bolt_life`` (drives the bolt fade)."""
        bolt_life = self.get_component(LightningFXFade).bolt_life
        return max(0.0, 1.0 - self.age / bolt_life) if bolt_life else 0.0

    @property
    def fade_frac(self):
        """1.0 fresh -> 0.0 at ``marker_life`` (drives the ground marker)."""
        marker_life = self.get_component(LightningFXFade).marker_life
        return max(0.0, 1.0 - self.age / marker_life) if marker_life else 0.0
