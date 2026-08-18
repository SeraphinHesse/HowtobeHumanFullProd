"""play_once — a one-shot cosmetic sprite VFX (ESV-5).

Plays a slot's sheet once at a world point, then despawns — the SAME shape as
``game/enemies/corpse.py``'s ``Corpse``/``CorpseFade``/``spawn_corpse``, copied
rather than shared because that module lives under ``game/`` (game
vocabulary the engine must not import) while this is the generic version any
trigger-table event can spawn.

Pure Python (no pygame, no ``data/`` access — D5): ``spawn_play_once`` takes
the caller's ``assets``/``scene`` as plain arguments and never opens a file or
reads a balancing dict. Completion tracking lives on ``PlayOnceFade`` here,
never on ``SpriteAnimator`` (E-12's engine-wide component, used by every
building and enemy in the game — a ``loop_count`` field there would be a
save/load + editor-inspector surface change for a problem exactly one cosmetic
object has).
"""
from engine.core import Component, GameObject, SpriteAnimator, Transform

ONESHOT_ANIM = "idle"   # the vfx slot category's one declared animation row


class PlayOnceFade(Component):
    """Ages to ``life_ms`` then despawns the owner (the ``CorpseFade``
    pattern). ``_owner``/``_scene`` are transient environment refs (E-11
    underscore)."""

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


class PlayOnceVfx(GameObject):
    """A one-shot cosmetic sprite: plays ``slot_key``'s ``idle`` row once at a
    world point, then despawns."""

    def __init__(self, wx, wy, slot_key, life_ms, layer="entities",
                 fit_tiles=0.0, scale=1.0, rank=0, column=None):
        super().__init__(
            name="vfx_oneshot",
            tags=("vfx_oneshot",),
            transform=Transform(wx=wx, wy=wy, layer=layer, rank=rank),
            components=[
                SpriteAnimator(slot_key=slot_key, animation=ONESHOT_ANIM,
                               fit_tiles=fit_tiles, scale=scale,
                               column=-1 if column is None else int(column)),
                PlayOnceFade(life_ms=int(life_ms)),
            ],
        )


def spawn_play_once(scene, assets, slot_key, wx, wy, *, layer="entities",
                    fit_tiles=0.0, scale=1.0, rank=0, column=None):
    """Spawn a ``PlayOnceVfx`` playing ``slot_key``'s sheet once. Returns
    ``None`` when the slot has no imported art — ``assets.animation_total_ms``
    returns ``None`` for a slot/animation absent from the manifest, with no
    idle fallback (unlike frame resolution) — which is the caller's cue to run
    its procedural fallback instead (E-37 art tolerance). Never raises.

    ``column`` (optional) is the LIVE master column the one-shot is cut at —
    the spawning object's own ``SpriteAnimator.column``, so a vfx sheet whose
    columns are a building's colours plays in the colour of the building that
    spawned it. ``None`` keeps the ``-1`` "no driver" sentinel, so the
    manifest entry's own stored column wins (D3) and every pre-existing
    caller stays byte-identical."""
    life_ms = assets.animation_total_ms(slot_key, ONESHOT_ANIM)
    if life_ms is None:
        return None
    vfx = PlayOnceVfx(wx, wy, slot_key, life_ms, layer=layer,
                      fit_tiles=fit_tiles, scale=scale, rank=rank,
                      column=column)
    vfx.get_component(PlayOnceFade)._scene = scene
    scene.spawn(vfx)
    return vfx
