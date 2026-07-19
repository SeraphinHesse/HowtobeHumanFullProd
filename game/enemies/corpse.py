"""Corpse — the cosmetic death-animation body (Art/enemies).

When an enemy dies it is despawned the SAME frame (combat, XP, wave-clear and
death-swarms all stay byte-identical — see ``combat.py``). To let the death
animation actually play, the host additionally spawns one of these at the dead
enemy's position: a purely-visual object that plays the enemy's own ``death``
animation once, then removes itself.

It is tagged ``"corpse"`` (never ``"enemy"``) and carries no ``alive`` / Health /
PathAgent, so it is invisible to EVERY gameplay query — combat targeting,
``_resolve_base_arrivals``, the wave-clear check, and the overhead HP bars all
read ``by_tag("enemy")`` / ``alive``. It renders through the generic
``Scene.render_items`` and ages through the generic ``Scene.update`` component
tick, exactly like ``Crater``/``LightningFX``.

Lifetime is the manifest's ``death`` track ``total_ms`` (which already accounts
for loop expansion), so the row plays through exactly once. The fade clock and
the ``SpriteAnimator`` clock both advance on the same speed-scaled ``sim_dt``, so
the play-once timing holds at 1x/1.5x/2x/pause.
"""
from engine.core import Component, GameObject, SpriteAnimator, Transform

DEATH_ANIM = "death"   # the manifest row name the death animation lives under


class CorpseFade(Component):
    """Ages to ``life_ms`` then despawns the owner (the ``CraterFade`` pattern).
    ``_scene``/``_owner`` are transient environment refs (E-11 underscore)."""

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


class Corpse(GameObject):
    """A dead enemy's lingering sprite, playing its ``death`` animation once."""

    def __init__(self, wx, wy, slot_key, life_ms, layer="entities",
                 fit_tiles=0.0, scale=1.0):
        super().__init__(
            name="corpse",
            tags=("corpse",),
            transform=Transform(wx=wx, wy=wy, layer=layer),
            components=[
                SpriteAnimator(slot_key=slot_key, animation=DEATH_ANIM,
                               fit_tiles=fit_tiles, scale=scale),
                CorpseFade(life_ms=int(life_ms)),
            ],
        )


def spawn_corpse(scene, enemy, life_ms):
    """Spawn a ``Corpse`` at ``enemy``'s position playing its ``death`` row for
    ``life_ms``. No-op (returns None) if the enemy carries no ``SpriteAnimator``.
    The enemy's own slot is copied, so each spawn-variant sheet plays its own
    death animation with no extra bookkeeping."""
    anim = enemy.get_component(SpriteAnimator)
    if anim is None:
        return None
    tf = enemy.transform
    corpse = Corpse(
        wx=tf.wx, wy=tf.wy, slot_key=anim.slot_key, life_ms=life_ms,
        layer=tf.layer, fit_tiles=anim.fit_tiles, scale=anim.scale,
    )
    corpse.get_component(CorpseFade)._scene = scene
    scene.spawn(corpse)
    return corpse
