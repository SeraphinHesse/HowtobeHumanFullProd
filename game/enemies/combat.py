"""Combat resolution (Phase 9E): defender fire, projectiles, base/death.

The type-agnostic combat sweep the host (and tests) call each frame AFTER
``scene.update(dt)``. It ports the prototype's three combat concerns onto clean
architecture:

1. **Defender fire** — every combatant (selected by the ``"combat"`` tag, never
   by class, per SPEC G-3) keeps its sticky target if it is still alive and in
   Chebyshev range, else acquires the nearest in-range enemy by Euclidean world
   distance (game-side tiebreak). On its cooldown it spawns a ``Projectile``;
   the reset interval is clamped to ``DefenceBuildings.globals.min_attack_speed``.
2. **Base arrival** — an enemy whose ``PathAgent.reached_base`` is set is
   consumed at the base. With no ``on_base_hit`` callback (9E tests) it deals its
   ``dmg`` straight to the base's ``Health`` (+ its ``RoundStats``). With a
   callback (9F ``Session``) the sweep hands off exactly ONE arrival per frame,
   then despawns it and bails — the prototype's ``_update_enemy_phase`` returns
   on the first base hit, so lives/HP/game-over/round-wipe stays a core concern
   and ``game/enemies`` never imports ``game/core``.
3. **Death cleanup** — any enemy with a dead ``Health`` is despawned.

**Projectiles** travel then deal GUARANTEED damage on arrival if the target is
still alive (prototype ``defence_building.Projectile``): a shot in flight is
wasted only if its target dies first — never a collision/accuracy miss. Travel
time = ``distance / projectile_speed_tiles``. They stay logical GameObjects
(no sprite); the UI layer draws them off the ``"projectile"`` tag (10J).
"""
import math

from engine.core import (
    Component, GameObject, Health, Movement, SpriteAnimator, Transform,
)
from engine.vfx.play_once import spawn_play_once
from game.anchors import anchor_world_point, projectile_point
from game.buildings.components import (
    Attacker, BeamAttacker, RoundStats, SplashAttacker,
)
from .components import EnemyCombat, Kidnap, PathAgent
from .kidnap import begin_kidnap

# AOE_TRAVEL_TIME / BEAM_MIN_TICK are SIMULATION TIMING, not balancing (NOT
# cosmetics — D4, ESV-3b §1.3): the mortar shell's fixed flight time (feeds
# _predict_lead's aim, and decides when splash damage lands) and the beam's
# own fast tick floor (the Sun Scorcher must tick far below the shared
# ``min_attack_speed`` = 0.2, so its cadence is clamped to this instead).
# Never move either into data/balancing/vfx.json.
AOE_TRAVEL_TIME = 0.55   # seconds a shell arcs to its fixed ground point
BEAM_MIN_TICK = 0.02     # beam tick-rate floor (prototype ``_MIN_TICK``)
# CRATER_LIFE is a declared-field FALLBACK only (the Component base requires
# a default per field); the runtime source of truth is data/balancing/
# vfx.json procedural.crater.life (ESV-3b), threaded through resolve_combat's
# required vfx_balance argument. Kept here so a bare CraterFade() built with
# no override still has a sane value (Crater/ProjectileAOE themselves require
# crater_life explicitly — no silent fallback on the production path, G-7).
CRATER_LIFE = 1.0        # seconds a spent-shell crater lingers before fading out
# vfx-projectile-spritesheets: the shared slot a designer imports art into to
# swap the procedural Crater for a one-shot PlayOnceVfx at impact (the same
# "shared slot, never per-building" rule vfx_projectile/vfx_shell follow).
CRATER_SLOT = "vfx_crater"


class ProjectileHoming(Component):
    """A homing shot: moves toward its (live) target and, when its travel timer
    expires, applies guaranteed damage if the target still lives, then despawns
    itself. Target / shooter / scene are transient refs (not serialized)."""

    dmg: int = 0
    speed: float = 1.0
    timer: float = 0.0

    def on_added(self, owner):
        self._proj = owner
        self._target = None
        self._shooter = None
        self._scene = None
        # ESV-6: transient refs for the projectile_hit trigger (E-11 — not
        # serialized, not declared fields). Set by _fire, which already has
        # assets/cs in scope, exactly as _fire_splash stashes arc._on_impact.
        self._assets = None
        self._cs = None
        self._on_hit = None
        # debug-mode-telemetry (Phase 3): the optional level-2 damage
        # callback, set by _fire — the same transient-ref pattern as
        # _on_hit above.
        self._on_damage = None
        # feat-projectile-anchored-flight: the COSMETIC lift fraction (E-11,
        # like _assets/_cs) — set by _fire from vfx_balance's
        # procedural.projectile.lift_frac, read by update() to resolve the
        # unanchored-target fallback point the SAME way _fire resolves its
        # unanchored-spawn fallback. Never read by launch()'s timer math (D4).
        self._lift_frac = 0.0

    def launch(self, target, shooter, scene, origin=None):
        """``origin`` (ESV-1, D4): the point flight time is measured FROM —
        never the projectile's (possibly muzzle-anchored) visual spawn point.
        ``None`` falls back to ``self._proj.transform.world_pos``, today's
        exact expression, so every existing caller is byte-identical. Used
        SOLELY for this distance/timer computation and then discarded — it
        is a parameter, not component state (E-11)."""
        self._target = target
        self._shooter = shooter
        self._scene = scene
        px, py = origin if origin is not None else self._proj.transform.world_pos
        tx, ty = target.transform.world_pos
        dist = math.hypot(tx - px, ty - py)
        self.timer = dist / self.speed if self.speed > 0 else 0.0

    def update(self, dt):
        """feat-projectile-anchored-flight (D4 — COSMETIC only, never the
        timer): the homing MOVEMENT target is now the target's `impact`
        anchor (or its unanchored lifted fallback), re-resolved every frame
        since the target moves — never `target.transform.world_pos` directly
        any more. `self.timer` (decremented below, unconditionally) still
        drives WHEN `_impact()` fires and is never a function of this point."""
        proj = getattr(self, "_proj", None)
        target = getattr(self, "_target", None)
        if proj is None:
            return
        if target is not None:
            point = projectile_point(
                getattr(self, "_assets", None), getattr(self, "_cs", None),
                target, "impact", getattr(self, "_lift_frac", 0.0))
            tx, ty = point if point is not None else target.transform.world_pos
            px, py = proj.transform.world_pos
            dx, dy = tx - px, ty - py
            d = math.hypot(dx, dy)
            step = self.speed * dt
            if d > 1e-9 and step < d:
                proj.transform.wx = px + dx / d * step
                proj.transform.wy = py + dy / d * step
            else:
                proj.transform.wx, proj.transform.wy = tx, ty
        self.timer -= dt
        if self.timer <= 0:
            self._impact()

    def _impact(self):
        target = getattr(self, "_target", None)
        shooter = getattr(self, "_shooter", None)
        scene = getattr(self, "_scene", None)
        # BR-3/D2: a shot already in flight when its target entered a delayed
        # second phase does NOTHING — the same "wasted if the target dies
        # first" rule, extended to "or became untouchable first".
        if (target is not None and getattr(target, "alive", False)
                and getattr(target, "targetable", True)):
            health = target.get_component(Health)
            health.damage(self.dmg)
            if shooter is not None:
                rs = shooter.get_component(RoundStats)
                if rs is not None:
                    rs.dmg_dealt_this_round += self.dmg
            # debug-mode-telemetry (Phase 3, level 2 only): fired at exactly
            # the RoundStats credit site above. attacker is None when the
            # shooter is gone (e.g. despawned mid-flight) — the null case is
            # load-bearing, see resolve_combat's docstring.
            on_dmg = getattr(self, "_on_damage", None)
            if on_dmg is not None:
                on_dmg(getattr(shooter, "building_type", None)
                       if shooter is not None else None,
                       getattr(target, "ETYPE", None), self.dmg, health.hp)
        # ESV-6: the projectile_hit trigger, at the TARGET's impact anchor.
        # Purely visual (D4) — reads nothing the damage block above wrote.
        # Fires whether or not the target is STILL alive this frame (a hit
        # VFX on a target that died in the same frame is correct); only a
        # missing target (no point to anchor against) guards it.
        on_hit = getattr(self, "_on_hit", None)
        if target is not None and on_hit is not None:
            assets = getattr(self, "_assets", None)
            cs = getattr(self, "_cs", None)
            point = anchor_world_point(assets, cs, target, "impact")
            if point is None:
                point = target.transform.world_pos
            on_hit(*point)
        if scene is not None:
            scene.despawn(self._proj)


class Projectile(GameObject):
    """A defender's in-flight shot (logical only in 9E; no sprite)."""

    def __init__(self, wx, wy, dmg, speed):
        super().__init__(
            name="projectile",
            tags=("projectile",),
            transform=Transform(wx=wx, wy=wy, layer="entities"),
            components=[ProjectileHoming(dmg=dmg, speed=speed)],
        )


# -- AOE mortar: arcing shell + splash on impact + crater (Phase 10B) ------

class ProjectileArc(Component):
    """A mortar shell arcing to a FIXED ground point (prototype ``AOEProjectile``
    — NOT homing). It carries the damage + splash radius LOADED at fire time, so
    the shooter dying or the original target vanishing mid-flight is a non-event.
    When the flight timer expires it deals ``dmg`` to EVERY alive enemy within
    ``radius`` of the landing point (Euclidean, full damage, no falloff, no
    target cap), spawns a cosmetic ``Crater``, then despawns itself.

    ``crater_life`` (ESV-3b): the fade lifetime the spawned ``Crater`` is
    built with, carried from ``data/balancing/vfx.json`` (``procedural.
    crater.life``) all the way down from ``resolve_combat``'s required
    ``vfx_balance`` argument. The class default (``CRATER_LIFE``) is only the
    declared-field fallback the ``Component`` base requires — every
    production path sets it explicitly at construction (``_fire_splash``)."""

    dmg: int = 0
    radius: float = 0.0
    timer: float = 0.0
    crater_life: float = CRATER_LIFE

    def on_added(self, owner):
        self._proj = owner
        self._shooter = None
        self._scene = None
        self._gx = 0.0
        self._gy = 0.0
        # ESV-5: an optional (wx, wy) -> None callback fired at impact,
        # ALONGSIDE whichever impact cosmetic _impact spawns below (Crater or
        # a sprite one-shot) — never a replacement for it. Set (or left None)
        # by _fire_splash, transient (E-11).
        self._on_impact = None
        # debug-mode-telemetry (Phase 3): the optional level-2 damage
        # callback, set by _fire_splash — same transient-ref pattern.
        self._on_damage = None
        # vfx-projectile-spritesheets: the AssetStore, so _impact can check
        # whether CRATER_SLOT has imported art (the has_art signal
        # submit_projectiles/spawn_play_once already use). Set by
        # _fire_splash, transient (E-11).
        self._assets = None

    def launch(self, gx, gy, shooter, scene, travel_time):
        self._gx, self._gy = gx, gy
        self._shooter = shooter
        self._scene = scene
        self.timer = travel_time

    def update(self, dt):
        proj = getattr(self, "_proj", None)
        if proj is None:
            return
        self.timer -= dt
        if self.timer > 0:
            return
        self._impact()

    def _impact(self):
        scene = getattr(self, "_scene", None)
        if scene is None:
            return
        shooter = getattr(self, "_shooter", None)
        rs = shooter.get_component(RoundStats) if shooter is not None else None
        on_dmg = getattr(self, "_on_damage", None)
        for enemy in scene.by_tag("enemy"):
            # BR-3/D2: splash passes over an untargetable second-phase boss.
            if (not getattr(enemy, "alive", False)
                    or not getattr(enemy, "targetable", True)):
                continue
            ex, ey = _enemy_center_world(enemy)   # the body's centre (ER-2)
            if math.hypot(ex - self._gx, ey - self._gy) <= self.radius:
                health = enemy.get_component(Health)
                health.damage(self.dmg)
                if rs is not None:
                    rs.dmg_dealt_this_round += self.dmg
                # debug-mode-telemetry (Phase 3, level 2 only): fired at
                # exactly the RoundStats credit site above, once per enemy
                # actually hit by the splash.
                if on_dmg is not None:
                    on_dmg(getattr(shooter, "building_type", None)
                           if shooter is not None else None,
                           getattr(enemy, "ETYPE", None), self.dmg, health.hp)
        # vfx-projectile-spritesheets: a designer-imported CRATER_SLOT sheet
        # swaps the procedural Crater (a scaled, alpha-faded ring) for a
        # fixed-size one-shot PlayOnceVfx — the same has_art signal
        # submit_projectiles already uses. No art -> byte-identical Crater
        # spawn, same as before this existed.
        assets = getattr(self, "_assets", None)
        has_art = (assets is not None
                  and assets.animation_total_ms(CRATER_SLOT, "idle") is not None)
        if has_art:
            spawn_play_once(scene, assets, CRATER_SLOT, self._gx, self._gy)
        else:
            crater = Crater(self._gx, self._gy, self.radius, self.crater_life)
            crater.get_component(CraterFade)._scene = scene
            scene.spawn(crater)
        # ESV-5: the splash_impact trigger ledger push — cosmetic, additive,
        # never gating the (unconditional) Crater spawn above.
        on_impact = getattr(self, "_on_impact", None)
        if on_impact is not None:
            on_impact(self._gx, self._gy)
        scene.despawn(self._proj)


class ProjectileAOE(GameObject):
    """A mortar's in-flight shell (logical only in 10B; no sprite).

    ``crater_life`` (ESV-3b, required — no default: the caller always has a
    live ``vfx_balance`` to read it from, and a silent code-side fallback
    here would be a second home for the value, G-7): carried straight onto
    the shell's ``ProjectileArc`` so its eventual ``Crater`` fades on the
    balancing-authored lifetime."""

    def __init__(self, wx, wy, dmg, radius, crater_life):
        super().__init__(
            name="shell",
            tags=("projectile",),
            transform=Transform(wx=wx, wy=wy, layer="entities"),
            components=[ProjectileArc(dmg=dmg, radius=radius,
                                      crater_life=crater_life)],
        )


class CraterFade(Component):
    """A spent-shell crater's fade clock (prototype ``Crater``). Purely cosmetic
    — no gameplay effect. Ages to ``life`` then despawns; ``radius`` and
    ``fade_frac`` (via the owner) are read by the FX layer."""

    radius: float = 0.0
    life: float = CRATER_LIFE
    age: float = 0.0

    def on_added(self, owner):
        self._owner = owner
        self._scene = None

    def update(self, dt):
        self.age += dt
        if self.age >= self.life:
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(self._owner)


class Crater(GameObject):
    """A cosmetic impact crater at a mortar landing point (Phase 10B). Logical
    only; the FX layer draws a fading marker from its ``radius`` + ``fade_frac``.

    ``life`` (ESV-3b, required — no default, G-7): the fade lifetime, always
    supplied by the one caller (``ProjectileArc._impact``) from its
    balancing-authored ``crater_life``."""

    def __init__(self, wx, wy, radius, life):
        super().__init__(
            name="crater",
            tags=("crater",),
            transform=Transform(wx=wx, wy=wy, layer="overlay"),
            components=[CraterFade(radius=radius, life=life)],
        )

    @property
    def radius(self):
        return self.get_component(CraterFade).radius

    @property
    def fade_frac(self):
        """1.0 fresh -> 0.0 gone (drives the FX fade)."""
        cf = self.get_component(CraterFade)
        return max(0.0, 1.0 - cf.age / cf.life) if cf.life else 0.0


# -- targeting helpers ----------------------------------------------------

def _enemy_footprint(enemy):
    """The enemy's footprint, guard-safe for the bare-bones stub enemies the
    combat tests build (no PathAgent -> 1)."""
    get = getattr(enemy, "get_component", None)
    pa = get(PathAgent) if get is not None else None
    return getattr(pa, "footprint", 1) or 1


def _fp_offset(enemy):
    """(N-1)/2 — the anchor->block-centre offset on each axis. N=1 -> 0.0.

    MEMOISED on the enemy as an underscore transient (E-11 allows those). The
    footprint is a static per-enemy constant, but ``_chebyshev`` runs once per
    (defender x enemy) PAIR per frame and ``get_component`` is a linear
    isinstance scan of the component list — resolving it pairwise costs ~9 ms
    on a 16.7 ms frame at footprint 1, i.e. for TODAY's enemies. Never recompute
    it in the pairwise loop (``game/PERF.md``)."""
    off = getattr(enemy, "_fp_off", None)
    if off is None:
        off = (_enemy_footprint(enemy) - 1) / 2.0
        enemy._fp_off = off
    return off


def _enemy_center_world(enemy):
    """The block centre in world coords (un-rounded). N=1 -> world_pos itself,
    not ``world_pos + 0.0`` — the zero offset is skipped so the single-tile
    value stays bit-for-bit what it was."""
    wx, wy = enemy.transform.world_pos
    off = _fp_offset(enemy)
    if not off:
        return (wx, wy)
    return (wx + off, wy + off)


def _chebyshev(center_tile, enemy, off=0.0):
    """Defender tile -> the NEAREST TILE of the enemy's N×N footprint block
    (ER-2 fix). The range GATE must reach the block from any tile touching
    it, not just from near its mathematical CENTRE: a range-1 defender
    standing adjacent to a 2×2 boss at anchor (10,10) (block (10,10)..(11,11))
    used to measure 1.5 to the centre and could never fire on it, while the
    boss's own block-and-attack scan (``components.py`` ``_blocker_ahead``, a
    block-wide occupancy check) hit that same defender fine. The block spans
    ``[anchor, anchor + 2*off]`` on each axis (``off = (N-1)/2`` ⇒
    ``2*off = N-1``), so distance-to-block is a per-axis clamp to that span,
    then Chebyshev across axes. The ``round()`` of the anchor is KEPT —
    dropping it would change the in-range set for existing 1×1 enemies
    mid-tile.

    Acquisition tiebreak (``_euclid_sq_to_enemy``), mortar predictive lead
    (``_predict_lead``) and the splash-radius measurement (``ProjectileArc.
    _impact``) are UNCHANGED and still measure to the block CENTRE — only
    this range GATE moved to nearest-tile.

    THE hot path — one call per (defender x enemy) PAIR per frame. ``off`` is
    passed IN (resolved once per enemy per frame by ``resolve_combat``), never
    looked up here, and a zero offset SKIPS the clamp entirely rather than
    running it with span 0, so the N=1 expression stays byte-identical INTEGER
    arithmetic — the anchor IS the block. At 50 defenders x 300 enemies, a
    component lookup — or floats where ints used to be — in this function is
    milliseconds of a 16.7 ms frame (``game/PERF.md``)."""
    wx, wy = enemy.transform.world_pos
    ec, er = round(wx), round(wy)
    if off:
        span = off * 2
        cc, cr = center_tile
        dc = max(cc - (ec + span), ec - cc, 0)
        dr = max(cr - (er + span), er - cr, 0)
        return max(dc, dr)
    return max(abs(ec - center_tile[0]), abs(er - center_tile[1]))


def _euclid_sq_to_enemy(defender, enemy):
    """Squared world distance from the defender to the enemy's block centre —
    the acquisition tiebreak. N=1 -> today's world_pos-to-world_pos value."""
    ax, ay = defender.transform.world_pos
    bx, by = _enemy_center_world(enemy)
    return (ax - bx) ** 2 + (ay - by) ** 2


def attack_interval(defender, min_attack_speed):
    """Seconds between shots, clamped by the shared ``min_attack_speed`` floor
    (prototype ``_effective_attack_speed``; boosts/penalties land 10B/10D)."""
    return max(min_attack_speed, defender.attack_speed())


def _predict_lead(target, travel_time):
    """The mortar's aim point (prototype ``_predict_intercept``): extrapolate the
    enemy's position along its heading over the shell's flight time. Heading is
    toward the enemy's current next waypoint at its move speed. If the enemy
    would reach/pass that waypoint within the flight time, aim exactly at the
    waypoint (clamp, no overshoot); with no next waypoint, aim at its current
    position. Predictive targeting is always on (prototype
    ``MORTAR_PREDICTIVE_TARGETING = True``).

    ER-2: both the position and the read waypoint are the enemy's block CENTRE
    (anchor + ``off``), so the shell lands on the body the splash test measures
    from — leaving the lead on the anchor would bias every shell half a tile off
    a formation. N=1 -> ``off = 0`` -> unchanged."""
    off = _fp_offset(target)
    px, py = _enemy_center_world(target)
    mv = target.get_component(Movement)
    if mv is None or not mv.waypoints or mv.index >= len(mv.waypoints):
        return px, py
    wx, wy = mv.waypoints[mv.index]
    wx, wy = wx + off, wy + off
    dx, dy = wx - px, wy - py
    dist = math.hypot(dx, dy)
    if dist < 1e-9:
        return px, py
    travel = mv.speed * travel_time
    if travel >= dist:
        return wx, wy
    return px + dx / dist * travel, py + dy / dist * travel


# -- the sweep ------------------------------------------------------------

def resolve_combat(scene, tilemap, dt, buildings_balance, vfx_balance,
                   on_base_hit=None, on_enemy_death=None, dmg_bonus=0,
                   assets=None, cs=None, on_splash_impact=None,
                   on_defender_fire=None, on_projectile_hit=None,
                   on_kidnap=None, on_damage=None):
    """``dmg_bonus`` (10G): a flat per-shot damage bonus every defender adds at
    fire time — the boss-bonus story damage (Boss1A/3A) crossing the package
    boundary as a plain int (the host computes it per frame from
    ``game.core.boss_bonuses.story_damage_bonus``). Default 0 keeps every
    pre-10G call byte-identical.

    ``assets``/``cs`` (ESV-1, §3.3): the host's ``AssetStore``/
    ``CoordinateSystem``, threaded down to ``_fire``/``_fire_splash`` to
    resolve a defender's ``muzzle`` anchor into a cosmetic spawn-point offset.
    Both default ``None`` (this package has neither on its own — see
    ``game/anchors.py``), so every existing headless caller and test is
    byte-identical.

    ``vfx_balance`` (ESV-3b, required — no default: a ``None``-defaulted
    optional here would be a second home for the crater fade lifetime, G-7):
    the loaded ``vfx.json`` dict, threaded down to ``_fire_splash`` so a
    freshly-fired mortar shell's eventual ``Crater`` fades on
    ``procedural.crater.life`` instead of the module constant.

    ``on_splash_impact`` (ESV-5, optional — the ``on_enemy_death`` pattern,
    NOT a required-argument G-7 case like ``vfx_balance`` above: this package
    has no other opinion about the value, it only forwards a caller-supplied
    ``(wx, wy) -> None`` callback to ``ProjectileArc._impact`` so the host can
    drain a cosmetic ledger without ``game/enemies`` importing ``game/core``):
    ``None`` (every pre-ESV-5 caller) is a no-op — the Crater still spawns.

    ``on_defender_fire``/``on_projectile_hit`` (ESV-6, optional, the same
    pattern): forwarded to ``_fire``/``_fire_splash`` (both) and
    ``ProjectileHoming`` (the homing path only — the mortar keeps its own
    ``splash_impact`` event, §1.2 of the ESV-6 brief) so the host can drain
    two more cosmetic ledgers. ``None`` (every pre-ESV-6 caller) is a no-op.

    feat-projectile-anchored-flight: ``lift_frac`` (``procedural.projectile.
    lift_frac``, the SAME cosmetic constant ``_fire_splash`` already reads
    for its shell's crater — no new parameter here) is threaded to BOTH
    ``_fire`` and ``_fire_splash``, which resolve their spawn point through
    ``game.anchors.projectile_point``. The HOMING TARGET change is
    ``_fire``-only (basic defenders): no ``impact`` anchor applies to a
    mortar shell, which flies to a predicted ground point, not an entity
    (§2.4). But the un-anchored LIFT had to reach the mortar too — the draw
    lift it used to get in ``submit_projectiles`` is gone, and
    ``ProjectileArc.update`` never moves the shell, so its spawn point is
    its drawn point for the whole flight.

    ``on_kidnap(enemy, building)`` (Art/enemies): fed to every enemy whose
    ``Kidnap.pending`` was armed this frame by ``EnemyCombat`` — see
    ``_resolve_kidnaps`` below.

    ``on_damage`` (debug-mode-telemetry, optional, level-2 only — the
    ``on_splash_impact`` pattern): forwarded to the three damage sites this
    module owns (homing impact, mortar splash, beam), invoked as
    ``on_damage(attacker_kind, target_kind, dmg, target_hp_after)`` at exactly
    the place each site already credits ``RoundStats`` — never a new damage
    application, never a reordering. ``attacker_kind`` is a
    ``building.BUILDING_TYPE``/``enemy.ETYPE`` string or ``None`` when no
    attacker is credited (e.g. a homing shot whose shooter despawned mid-
    flight). ``None`` (every pre-Phase-3 caller) is a no-op — every existing
    caller/test is byte-identical. The fourth site, an enemy attacking a
    blocking building, lives in ``game/enemies/components.py`` — it runs
    inside ``Scene.update`` (BEFORE this function is even called each frame),
    so it cannot be reached through this parameter; see
    ``components.set_damage_hook``."""
    globals_ = buildings_balance["DefenceBuildings"]["globals"]
    min_atk = globals_["min_attack_speed"]
    proj_speed = globals_["projectile_speed_tiles"]
    # ESV-3b: a cosmetic fade lifetime, NOT simulation timing (unlike
    # AOE_TRAVEL_TIME/BEAM_MIN_TICK below, which stay module constants — D4).
    crater_life = vfx_balance["procedural"]["crater"]["life"]
    lift_frac = vfx_balance["procedural"]["projectile"]["lift_frac"]

    # BR-3/D2: a boss in its delayed second phase is alive but UNTARGETABLE —
    # dropping it here removes it from every defender's `in_range` list at
    # once (homing, splash and beam alike), so no acquisition site needs its
    # own guard. `getattr` default True: buildings and the combat tests' stub
    # enemies carry no such property.
    enemies = [e for e in scene.by_tag("enemy")
               if e.alive and getattr(e, "targetable", True)]
    # ER-2: the footprint offset is a per-enemy CONSTANT. Resolve it once per
    # enemy per frame here — never inside the (defender x enemy) pairwise loop
    # below, where it would cost a component scan per pair (game/PERF.md).
    targets = [(e, _fp_offset(e)) for e in enemies]
    for defender in scene.by_tag("combat"):
        _update_defender(defender, scene, targets, dt, min_atk, proj_speed,
                         crater_life, dmg_bonus, assets, cs, on_splash_impact,
                         on_defender_fire, on_projectile_hit, lift_frac,
                         on_damage)

    _resolve_kidnaps(scene, tilemap, on_kidnap)

    _resolve_base_arrivals(scene, tilemap, on_base_hit)

    for enemy in scene.by_tag("enemy"):
        if not enemy.alive:
            # 10A: the session counts the kill + awards XP here. Base arrivals
            # left through `on_base_hit` above and were already despawned, so
            # they can never reach this sweep — no double award.
            if on_enemy_death is not None:
                on_enemy_death(enemy)
            scene.despawn(enemy)


def _resolve_kidnaps(scene, tilemap, on_kidnap=None):
    """The kidnap transition, placed AFTER the defender loop and BEFORE
    ``_resolve_base_arrivals`` (Art/enemies). ``begin_kidnap`` copies the
    victim's sprite fields onto the carrier, then ``on_kidnap`` lets the host
    do the session bookkeeping (XP + kill count); the victim itself is left on
    its tile as a plain dead building, to be revived at payday.
    The retag inside ``begin_kidnap`` drops the enemy out of
    ``by_tag("enemy")`` immediately, so the death sweep below never sees it
    and any defender's ``target not in in_range`` re-acquire test clears a
    lock on it next tick."""
    for enemy in list(scene.by_tag("enemy")):
        k = enemy.get_component(Kidnap)
        if k is None or not k.pending:
            continue
        building = enemy.get_component(EnemyCombat)._kidnap_victim
        begin_kidnap(scene, tilemap, enemy, building)
        if on_kidnap is not None:
            on_kidnap(enemy, building)


def _update_defender(defender, scene, targets, dt, min_atk, proj_speed,
                     crater_life, dmg_bonus=0, assets=None, cs=None,
                     on_splash_impact=None, on_defender_fire=None,
                     on_projectile_hit=None, lift_frac=0.0, on_damage=None):
    """``targets`` is ``[(enemy, footprint_offset), ...]`` — the offsets are
    resolved once per frame by ``resolve_combat`` (ER-2). ``assets``/``cs``
    (ESV-1) pass straight through to ``_fire``/``_fire_splash``; the beam
    path (``_update_beam``) needs neither — it is instant hitscan with no
    travel and no spawn point (§1.5). ``crater_life`` (ESV-3b) and
    ``on_splash_impact`` (ESV-5) pass straight through to ``_fire_splash`` —
    only the splash path ever spawns a ``Crater``/fires an impact.
    ``on_defender_fire`` (ESV-6) passes to BOTH firing paths; ``on_projectile_
    hit`` (ESV-6) passes only to ``_fire`` — the homing path — since the
    mortar's splash already has its own impact event. ``lift_frac``
    (feat-projectile-anchored-flight) passes only to ``_fire`` too — see
    that module-level function's docstring. ``on_damage`` (debug-mode-
    telemetry) passes to BOTH firing paths and to ``_update_beam``."""
    attacker = defender.get_component(Attacker)
    if attacker is None or not getattr(defender, "alive", True):
        return
    # Beam buildings have their OWN acquisition (highest-HP, death cooldown) and
    # tick model — handle them wholesale, then bail.
    if defender.get_component(BeamAttacker) is not None:
        _update_beam(defender, targets, dt, dmg_bonus, on_damage)
        return

    center = (defender.col, defender.row)
    # 10I: targeting uses the building's TARGETING range (effective mountain
    # +1 for basic defence; RAW for the mortar — prototype inconsistency, see
    # DefenceBuilding.targeting_range_tiles). The raw range_tiles() keeps
    # feeding pathfinding coverage + the RANGE overlay. Guarded so bare-bones
    # defender stubs in tests keep working.
    rng = getattr(defender, "targeting_range_tiles", defender.range_tiles)()
    in_range = [e for e, off in targets if _chebyshev(center, e, off) <= rng]

    target = getattr(attacker, "_target", None)
    if target is not None and target not in in_range:
        target = None
    if target is None and in_range:
        target = min(in_range, key=lambda e: _euclid_sq_to_enemy(defender, e))
    attacker._target = target
    attacker.has_target = target is not None
    # Play the attack animation while engaging a target (e.g. the stone
    # thrower's throw), idle otherwise — mirrors the enemy PathAgent's
    # walk/attack switch and the prototype's `_animating` state.
    _set_defender_anim(defender, "attack" if target is not None else "idle")

    attacker.cooldown -= dt
    if target is not None and attacker.cooldown <= 0:
        # Splash (mortar) buildings fire an arcing shell to a predicted ground
        # point; the plain defender fires a homing shot. The capability marker
        # (SplashAttacker), not the class, selects the path (SPEC G-3).
        if defender.get_component(SplashAttacker) is not None:
            _fire_splash(defender, target, scene, crater_life, dmg_bonus,
                        assets, cs, on_splash_impact, on_defender_fire,
                        lift_frac, on_damage)
        else:
            _fire(defender, target, scene, proj_speed, dmg_bonus, assets, cs,
                 on_defender_fire, on_projectile_hit, lift_frac, on_damage)
        attacker.cooldown = attack_interval(defender, min_atk)


def _update_beam(defender, targets, dt, dmg_bonus=0, on_damage=None):
    """The Sun Scorcher beam (prototype ``SunScorcherBuilding.update``): lock the
    highest-HP enemy in range, ramp damage while focused, reset the ramp on any
    target change, and pause re-acquiring for ``target_death_cooldown`` after a
    kill. Instant hitscan — no projectile."""
    attacker = defender.get_component(Attacker)
    beam = defender.get_component(BeamAttacker)
    center = (defender.col, defender.row)
    # 10I: targeting range (= effective, mountain-boosted, for the beam),
    # guarded for stubs.
    rng = getattr(defender, "targeting_range_tiles", defender.range_tiles)()
    in_range = [e for e, off in targets if _chebyshev(center, e, off) <= rng]

    if beam.death_cooldown > 0:
        beam.death_cooldown -= dt

    target = getattr(attacker, "_target", None)
    if target is not None and (not getattr(target, "alive", False)
                               or not getattr(target, "targetable", True)
                               or target not in in_range):
        target = None
    if target is None and beam.death_cooldown <= 0 and in_range:
        target = max(in_range, key=lambda e: e.get_component(Health).hp)
    attacker._target = target
    beam._target = target          # the FX layer reads this
    attacker.has_target = target is not None

    # Ramp resets to 0 on any target change (the _ramp_target bookkeeping stays
    # for the fire step — prototype resets ramp here but advances _ramp_target
    # only when it actually fires, so the first tick on a new target is base
    # damage and the ramp builds from the second tick).
    if target is not getattr(beam, "_ramp_target", None):
        beam.ramp = 0.0
    _set_defender_anim(defender, "attack" if target is not None else "idle")

    attacker.cooldown -= dt
    if target is None or attacker.cooldown > 0:
        return
    if target is beam._ramp_target:
        beam.ramp = min(defender.ramp_max(), beam.ramp + defender.ramp_per_tick())
    else:
        beam.ramp = 0.0
        beam._ramp_target = target
    dmg = defender.damage() + int(beam.ramp) + dmg_bonus  # story bonus (10G)
    health = target.get_component(Health)
    health.damage(dmg)
    rs = defender.get_component(RoundStats)
    if rs is not None:
        rs.dmg_dealt_this_round += dmg
    # debug-mode-telemetry (Phase 3, level 2 only): fired at exactly the
    # RoundStats credit site above.
    if on_damage is not None:
        on_damage(getattr(defender, "building_type", None),
                  getattr(target, "ETYPE", None), dmg, health.hp)
    attacker.cooldown = max(BEAM_MIN_TICK, defender.attack_speed())
    if not getattr(target, "alive", False):     # killed this tick
        beam.ramp = 0.0
        beam._ramp_target = None
        beam._target = None
        attacker._target = None
        attacker.has_target = False
        beam.death_cooldown = defender.target_death_cooldown()


def _set_defender_anim(defender, name):
    anim = defender.get_component(SpriteAnimator)
    if anim is not None and anim.animation != name:
        anim.set_animation(name)


def _fire(defender, target, scene, proj_speed, dmg_bonus=0, assets=None,
         cs=None, on_defender_fire=None, on_projectile_hit=None,
         lift_frac=0.0, on_damage=None):
    bx, by = defender.transform.world_pos
    # ESV-1 D4: the spawn point is COSMETIC (the muzzle anchor, art). Flight
    # time is computed by `launch(origin=...)` below from the UNMODIFIED
    # `(bx, by)` — the two are deliberately different arguments so damage
    # timing can never be a function of an authored art coordinate.
    # fix-anchor-origin-parity: "anchor wins outright" — the muzzle point IS
    # the exact handle point when authored, never a delta on `(bx, by)`.
    # feat-projectile-anchored-flight: unanchored now resolves the SAME
    # cosmetic lift `submit_projectiles` used to add at draw time (never
    # `(bx, by)` bare) — `projectile_point` degrades to exactly `(bx, by)`
    # only when `cs`/`defender` are absent (E-37).
    point = projectile_point(assets, cs, defender, "muzzle", lift_frac)
    mx, my = point if point is not None else (bx, by)
    # ESV-6: the defender_fire trigger ledger push, at the SAME
    # already-computed muzzle point — never recomputed (D2).
    if on_defender_fire is not None:
        on_defender_fire(mx, my)
    proj = Projectile(mx, my, defender.damage() + dmg_bonus, proj_speed)
    hom = proj.get_component(ProjectileHoming)
    hom._assets, hom._cs, hom._on_hit = assets, cs, on_projectile_hit
    hom._lift_frac = lift_frac
    hom._on_damage = on_damage
    hom.launch(target, defender, scene, origin=(bx, by))
    scene.spawn(proj)


def _fire_splash(defender, target, scene, crater_life, dmg_bonus=0,
                 assets=None, cs=None, on_splash_impact=None,
                 on_defender_fire=None, lift_frac=0.0, on_damage=None):
    """Launch an arcing shell (prototype ``AOEDefenceBuilding._shoot``): aim a
    fixed ground point via predictive lead, load it with the current damage +
    splash radius, and let ``ProjectileArc`` resolve the splash on impact.

    ESV-1: only the shell's SPAWN point (``bx, by``) is muzzle-anchored — its
    flight time is the fixed ``AOE_TRAVEL_TIME`` (not distance-derived) and
    its landing point comes from `_predict_lead`, which reads nothing about
    the shooter, so both stay untouched by the anchor (§1.4).

    ``crater_life`` (ESV-3b, required — no default, G-7): the cosmetic fade
    lifetime the eventual impact ``Crater`` is built with — carried onto the
    shell at construction, never touching ``AOE_TRAVEL_TIME`` (simulation
    timing, D4).

    ``on_splash_impact`` (ESV-5, optional): stashed as a transient attribute
    on the shell's ``ProjectileArc`` and fired at impact, alongside (never
    instead of) whichever impact cosmetic lands.

    vfx-projectile-spritesheets: ``assets`` is also stashed on the shell's
    ``ProjectileArc`` (mirroring ``_on_impact``/``_on_damage``) so ``_impact``
    can check whether ``CRATER_SLOT`` has imported art and spawn a one-shot
    sprite instead of the procedural ``Crater`` — no new parameter, ``assets``
    already reaches this function.

    ``on_defender_fire`` (ESV-6, optional): fired immediately with the SAME
    muzzle-anchored ``(bx, by)`` the shell spawns at — never recomputed.

    ``on_damage`` (debug-mode-telemetry, optional): stashed on the shell's
    ``ProjectileArc`` and fired once per enemy the splash actually damages,
    at the same site the ``RoundStats`` credit is applied.

    ``lift_frac`` (feat-projectile-anchored-flight): the shell spawns through
    the SAME ``projectile_point`` resolver ``_fire`` uses, so an un-anchored
    mortar keeps the screen-space lift that used to be added at DRAW time in
    ``submit_projectiles``. Without this the shell would render ~19px lower
    than before this change — ``ProjectileArc.update`` never moves the shell
    (only its timer ticks), so its spawn point IS its drawn point for the
    whole flight, and the removed draw lift has to come back here or the
    mortar visibly drops. Byte-identical to pre-change for an un-anchored
    shooter; an authored ``muzzle`` anchor wins outright, as everywhere."""
    bx, by = defender.transform.world_pos
    point = projectile_point(assets, cs, defender, "muzzle", lift_frac)
    if point is not None:
        bx, by = point
    if on_defender_fire is not None:
        on_defender_fire(bx, by)
    gx, gy = _predict_lead(target, AOE_TRAVEL_TIME)
    shell = ProjectileAOE(bx, by, defender.damage() + dmg_bonus,
                          defender.splash_radius(), crater_life)
    arc = shell.get_component(ProjectileArc)
    arc._on_impact = on_splash_impact
    arc._on_damage = on_damage
    arc._assets = assets
    arc.launch(gx, gy, defender, scene, AOE_TRAVEL_TIME)
    scene.spawn(shell)


def _resolve_base_arrivals(scene, tilemap, on_base_hit=None):
    base_tile = tilemap.get(tilemap.base_col, tilemap.base_row)
    base = base_tile.occupant if base_tile is not None else None
    for enemy in scene.by_tag("enemy"):
        pa = enemy.get_component(PathAgent)
        if pa is None or not pa.reached_base:
            continue
        if on_base_hit is not None:
            # 9F: hand off ONE arrival to the session (lives/HP/game-over/wipe),
            # despawn it, and stop — the prototype returns on the first hit.
            on_base_hit(enemy)
            scene.despawn(enemy)
            return
        if base is not None:
            base.get_component(Health).damage(enemy.dmg)
            rs = base.get_component(RoundStats)
            if rs is not None:
                rs.dmg_taken_this_round += enemy.dmg
        scene.despawn(enemy)
