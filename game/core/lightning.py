"""Lightning strike ability (Phase 10H) — pure rules + the strike FX object.

Ports the prototype's lightning fields on ``Game`` (``game.py:116-119``),
``upgrade_lightning`` (``game.py:517-526``), ``_handle_lightning_click`` /
``_activate_lightning`` (``game.py:492-514``) and the cooldown tick
(``game.py:1243-1246``). Every gameplay tunable comes from ``core.json``
``LightningStrike`` (cooldown/damage/radius per level, max_level, unlock +
upgrade costs — already prototype-exact); the two FX lifetimes are cosmetic
and come from ``data/balancing/vfx.json`` ``procedural.lightning.bolt_life``/
``marker_life`` (ESV-3b) via ``strike()``'s ``vfx`` argument — never touching
this file's gameplay tunables, and never simulation timing (D4).

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
prototype-exact — self-despawns at its own ``marker_life``, and the FX layer
just draws it). Damage pays no ``RoundStats`` credit — lightning has no
shooter; kills flow through the next ``resolve_combat`` sweep's
``on_enemy_death``, so they pay XP and count as kills like any other kill.
"""
from engine.core import Component, GameObject, Health, Transform

# Cosmetic FX lifetimes — declared-field FALLBACKS only (the Component base
# requires a default per field); the runtime source of truth is
# data/balancing/vfx.json procedural.lightning.bolt_life/marker_life
# (ESV-3b), threaded through strike()'s required vfx argument. Kept here as
# the CraterFade-style precedent literal and so a bare LightningFXFade()
# built with no override still has a sane value.
BOLT_LIFE = 0.5     # seconds the jagged bolt is drawn
MARKER_LIFE = 1.0   # seconds the ground marker fades over, then despawns


def next_cost(state, core):
    """Love price of the next level: ``unlock_cost`` at L0, else the per-step
    ``upgrade_costs`` entry; None at max level (prototype game.py:517-523)."""
    ls = core["LightningStrike"]
    lvl = state.lightning_level
    if lvl >= ls["max_level"]:
        return None
    if lvl <= 0:
        return ls["unlock_cost"]
    return ls["upgrade_costs"][lvl - 1]


def upgrade(state, core):
    """Buy the next level if affordable (prototype game.py:524-526). The
    cooldown timer is NOT touched by an upgrade. True on success."""
    cost = next_cost(state, core)
    if cost is None or state.love < cost:
        return False
    state.spend_love(cost)
    state.lightning_level += 1
    return True


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


def strike(state, core, vfx, scene, cs, wx, wy):
    """Strike world point ``(wx, wy)`` (prototype ``_activate_lightning``,
    game.py:502-514). Silent no-op (False) while locked or cooling. Otherwise:
    flat damage to EVERY alive enemy inside the projected-plane circle (no
    falloff, no target cap, no love cost), the cooldown is spent
    UNCONDITIONALLY — a whiff that hits nothing still pays it and still shows
    the VFX — and a ``LightningFX`` marker is spawned. Any world point is a
    valid target: no tile/zone/bounds check, no enemies-required check.

    ``vfx`` (ESV-3b, required — no default, G-7): the loaded ``vfx.json``
    dict, read for the two cosmetic fade lifetimes
    (``procedural.lightning.bolt_life``/``marker_life``) the spawned
    ``LightningFX`` is built with — never the damage/radius/cooldown above,
    which stay ``core.json`` ``LightningStrike`` (unchanged by this phase)."""
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
    lp = vfx["procedural"]["lightning"]
    fx = LightningFX(wx, wy, radius_tiles, lp["bolt_life"], lp["marker_life"])
    fx.get_component(LightningFXFade)._scene = scene
    scene.spawn(fx)
    return True


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
