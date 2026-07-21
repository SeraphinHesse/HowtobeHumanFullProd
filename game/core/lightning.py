"""Lightning strike ability (Phase 10H; Storm Priest rework) — pure rules +
the strike FX object + the Storm Priest's ``LightningCaster`` puppeting.

Ports the prototype's lightning fields on ``Game`` (``game.py:116-119``),
``_handle_lightning_click`` / ``_activate_lightning`` (``game.py:492-514``)
and the cooldown tick (``game.py:1243-1246``). Every tunable comes from
``core.json`` ``LightningStrike`` (cooldown/damage/radius per level,
max_level); the two FX lifetimes + ``CASTER_FLASH_DURATION`` are code
constants, not balancing (the ``CRATER_LIFE`` precedent).

**Radius semantics** (prototype ``game.py:505-508``): the blast is a Euclidean
CIRCLE in the PROJECTED pixel plane — ``radius_px = radius_tiles * TILE_HW``
around the click, hit-tested on projected coordinates. It is NOT the Chebyshev
defender range and NOT tile-space Euclidean like the mortar splash. Both the
strike point and each enemy are projected through the coords authority
(``cs.world_to_screen``): the camera pan cancels in the delta and zoom scales
the threshold linearly, so ``radius_tiles * tile_w / 2 * zoom`` is exact and
no iso math leaks out of ``engine.coords``.

State lives on ``RunState`` (``lightning_level`` / ``lightning_cooldown``);
this module is pure functions over it plus ``LightningFX`` (the ``Crater``
pattern: it ages in ``scene.update`` — i.e. on the host's ENEMY-scaled sim dt,
prototype-exact — self-despawns at ``MARKER_LIFE``, and the FX layer just
draws it). Damage pays no ``RoundStats`` credit — lightning has no shooter;
kills flow through the next ``resolve_combat`` sweep's ``on_enemy_death``, so
they pay XP and count as kills like any other kill.

**Storm Priest rework**: there is no love-priced level-up any more
(``next_cost``/``upgrade`` are gone). Leveling is driven entirely by the
Storm Priest's own tier, via ``sync_level_from_tier`` (called from
``game/ui/building_ui.py``'s tier-advance branch), and ``strike()`` puppets
the placed Storm Priest's ``SpriteAnimator`` into its "attack" pose through
the new ``LightningCaster`` component (since the building itself no longer
fires in combat — it dropped the ``"combat"`` tag).
"""
from engine.core import Component, GameObject, Health, SpriteAnimator, Transform

# Cosmetic FX lifetimes — code constants like CRATER_LIFE, not balancing
# (prototype effects.py:232 bolt life; AOE_DEF_CRATER_DURATION default 1.0).
BOLT_LIFE = 0.5     # seconds the jagged bolt is drawn
MARKER_LIFE = 1.0   # seconds the ground marker fades over, then despawns
CASTER_FLASH_DURATION = 0.4  # seconds the Storm Priest holds its "attack" pose


def tick(state, dt):
    """Drain the cooldown toward 0. The CALLER decides when it ticks —
    ``Session.pre_sim``'s ENEMY branch only, on the speed-scaled sim dt
    (prototype game.py:1243-1246): 2x drains it twice as fast, the in-combat
    pause freezes it, and it persists frozen across every other phase."""
    if state.lightning_cooldown > 0:
        state.lightning_cooldown = max(0.0, state.lightning_cooldown - dt)


def can_strike(state):
    """Level > 0 and off cooldown (prototype game.py:493)."""
    return state.lightning_level > 0 and state.lightning_cooldown <= 0


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


def strike(state, core, scene, cs, wx, wy):
    """Strike world point ``(wx, wy)`` (prototype ``_activate_lightning``,
    game.py:502-514). Silent no-op (False) while locked or cooling. Otherwise:
    flat damage to EVERY alive enemy inside the projected-plane circle (no
    falloff, no target cap, no love cost), the cooldown is spent
    UNCONDITIONALLY — a whiff that hits nothing still pays it and still shows
    the VFX — and a ``LightningFX`` marker is spawned. Any world point is a
    valid target: no tile/zone/bounds check, no enemies-required check."""
    if not can_strike(state):
        return False
    ls = core["LightningStrike"]
    idx = state.lightning_level - 1
    dmg = ls["damage"][idx]
    radius_tiles = ls["radius"][idx]
    radius_px = radius_tiles * cs.geometry.tile_w / 2 * cs.camera.zoom
    sx, sy = cs.world_to_screen(wx, wy)
    for enemy in scene.by_tag("enemy"):
        if not getattr(enemy, "alive", False):
            continue
        ex, ey = cs.world_to_screen(*enemy.transform.world_pos)
        if (ex - sx) ** 2 + (ey - sy) ** 2 <= radius_px ** 2:
            enemy.get_component(Health).damage(dmg)
    state.lightning_cooldown = ls["cooldown"][idx]
    fx = LightningFX(wx, wy, radius_tiles)
    fx.get_component(LightningFXFade)._scene = scene
    scene.spawn(fx)
    for b in scene.by_tag("lightning_source"):
        if getattr(b, "alive", False):
            caster = b.get_component(LightningCaster)
            if caster is not None:
                caster.trigger()
            break
    return True


class LightningCaster(Component):
    """Puppets a ``lightning_source`` building's SpriteAnimator: flips to
    "attack" when the player casts Lightning Strike (nothing else drives its
    animation any more since Storm Priest dropped the "combat" tag), reverting
    to "idle" ``CASTER_FLASH_DURATION`` seconds later."""

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

    def trigger(self):
        self.flash_timer = CASTER_FLASH_DURATION
        anim = self._owner.get_component(SpriteAnimator)
        if anim is not None:
            anim.set_animation("attack")


class LightningFXFade(Component):
    """The strike marker's age clock (the ``CraterFade`` mirror). Purely
    cosmetic — ages to ``MARKER_LIFE`` in ``scene.update`` then despawns its
    owner; the FX layer reads ``radius_tiles`` + the owner's fade fractions."""

    radius_tiles: float = 0.0
    age: float = 0.0

    def on_added(self, owner):
        self._owner = owner
        self._scene = None

    def update(self, dt):
        self.age += dt
        if self.age >= MARKER_LIFE:
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(self._owner)


class LightningFX(GameObject):
    """A cosmetic strike marker at the impact point (Phase 10H). Logical only;
    ``game/ui/effects.py submit_lightning`` draws the bolt while
    ``bolt_frac > 0`` and the fading ground diamond from ``fade_frac``."""

    def __init__(self, wx, wy, radius_tiles):
        super().__init__(
            name="lightning_fx",
            tags=("lightning_fx",),
            transform=Transform(wx=wx, wy=wy, layer="overlay"),
            components=[LightningFXFade(radius_tiles=float(radius_tiles))],
        )

    @property
    def radius_tiles(self):
        return self.get_component(LightningFXFade).radius_tiles

    @property
    def age(self):
        return self.get_component(LightningFXFade).age

    @property
    def bolt_frac(self):
        """1.0 fresh -> 0.0 at ``BOLT_LIFE`` (drives the bolt fade)."""
        return max(0.0, 1.0 - self.age / BOLT_LIFE) if BOLT_LIFE else 0.0

    @property
    def fade_frac(self):
        """1.0 fresh -> 0.0 at ``MARKER_LIFE`` (drives the ground marker)."""
        return max(0.0, 1.0 - self.age / MARKER_LIFE) if MARKER_LIFE else 0.0
