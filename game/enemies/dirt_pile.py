"""DirtPile — the cosmetic mound a submerging Digger leaves behind (NE-2).

The exact shape of ``corpse.py``'s ``Corpse``/``CorpseFade``/``spawn_corpse``,
in its own module rather than as a sibling in that one: a corpse is *the dead
enemy's own sprite playing its own death row*, so it is constructed FROM an
enemy and inherits that enemy's slot/fit/scale. A dirt pile is a fixed
world decal with one shared slot and no relationship to the unit that made it.
Same pattern, different subject — and the design pillar is small single-purpose
files, so it gets its own.

Tagged ``"dirt_pile"`` (never ``"enemy"``) and carrying no ``alive`` / Health /
PathAgent, so it is invisible to EVERY gameplay query — combat targeting,
``_resolve_base_arrivals``, the wave-clear check and the overhead HP bars all
read ``by_tag("enemy")`` / ``alive``. It renders through the generic
``Scene.render_items`` and ages through the generic ``Scene.update`` component
tick, exactly like ``Corpse``/``Crater``/``LightningFX``.

Lifetime is passed in by the caller rather than read from a manifest track:
``BurrowAgent`` hands it the dig duration, so the mound is on the board for
exactly as long as the Digger is under it. The fade clock advances on the same
speed-scaled ``sim_dt`` the rest of the scene does, so that stays true at
1x/1.5x/2x/pause — the ``Corpse`` fade-clock rule.
"""
from engine.core import Component, GameObject, SpriteAnimator, Transform

#: the data/slots.json vfx slot the mound draws (grey-X placeholder until real
#: art lands via /replace-visual — a slot with no asset_manifest entry is legal
#: and common, see game/enemies/CLAUDE.md's Commander section).
DIRT_PILE_SLOT = "vfx_dirt_pile"


class DirtPileFade(Component):
    """Ages to ``life_ms`` then despawns the owner (the ``CorpseFade`` /
    ``CraterFade`` pattern). ``_scene``/``_owner`` are transient environment
    refs (E-11 underscore)."""

    life_ms: int = 0
    age_ms: float = 0.0

    def on_added(self, owner):
        self._owner = owner
        self._scene = None

    def update(self, dt):
        self.age_ms += dt * 1000.0
        if self.age_ms >= self.life_ms:
            scene = getattr(self, "_scene", None)
            if scene is not None:
                scene.despawn(self._owner)


class DirtPile(GameObject):
    """The mound of earth over a burrowed Digger's entry tile."""

    def __init__(self, wx, wy, life_ms, layer="entities",
                 slot_key=DIRT_PILE_SLOT):
        super().__init__(
            name="dirt_pile",
            tags=("dirt_pile",),
            transform=Transform(wx=float(wx), wy=float(wy), layer=layer),
            components=[
                SpriteAnimator(slot_key=slot_key, animation="idle"),
                DirtPileFade(life_ms=int(life_ms)),
            ],
        )


def spawn_dirt_pile(scene, wx, wy, life_ms):
    """Spawn a ``DirtPile`` at ``(wx, wy)`` for ``life_ms`` milliseconds.

    Returns the object (or ``None`` for a missing scene, so a headless
    component-only test never trips). The ``spawn_corpse`` seam exactly: the
    caller wires ``_scene`` onto the fade clock, because a Component cannot
    reach the scene on its own."""
    if scene is None:
        return None
    pile = DirtPile(wx, wy, life_ms)
    pile.get_component(DirtPileFade)._scene = scene
    scene.spawn(pile)
    return pile
