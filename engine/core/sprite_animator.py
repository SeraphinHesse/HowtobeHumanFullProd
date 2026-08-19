"""SpriteAnimator (E-12/E-20): the visual-presence component.

Holds the asset slot key, current animation name, a phase offset (so
identical entities don't animate in lockstep) and the item's sizing
(`fit_tiles`/`scale` — see engine/render). update(dt) advances the
animation clock; render_items(transform) emits one RenderItem per frame —
world space only, no pixels, no pygame.
"""
from engine.render.item import RenderItem

from .component import Component


class SpriteAnimator(Component):
    slot_key: str = ""
    animation: str = "idle"
    phase_ms: int = 0
    anim_time_ms: float = 0.0
    fit_tiles: float = 0.0
    scale: float = 1.0
    visible: bool = True
    # The LIVE master column this sprite is driven at, or **-1 for "no driver"**
    # (emitted as RenderItem.column=None, so the entry's own stored `column`
    # wins per D3). A Component field must be JSON-safe — `_JSON_FIELD_TYPES`
    # in component.py rejects `int | None` outright — so the sentinel is a
    # negative int rather than None. It cannot be 0: season 0 and colour index
    # 0 are legitimate live values.
    column: int = -1
    # Mirror the sprite horizontally. The sheet holds ONE facing; a walker
    # whose heading points to the screen-right half of the iso diamond (NE or
    # SE — see `Facing` in game/enemies/components.py) sets this so it faces
    # where it walks. Nothing in the engine decides WHEN to flip: the field is
    # written by whoever owns the facing rule, exactly like `animation`.
    flip: bool = False

    def update(self, dt):
        self.anim_time_ms += dt * 1000.0

    def set_animation(self, name):
        """Switch animation and restart its clock."""
        self.animation = name
        self.anim_time_ms = 0.0

    def render_items(self, transform):
        if not self.visible:
            return
        yield RenderItem(
            self.slot_key,
            transform.world_pos,
            layer=transform.layer,
            animation=self.animation,
            anim_time_ms=self.anim_time_ms + self.phase_ms,
            fit_tiles=self.fit_tiles,
            scale=self.scale,
            column=self.column if self.column >= 0 else None,
            flip=self.flip,
            # VA-3: read off the transform beside `layer`, for the same reason
            # — both are the OBJECT's draw-order metadata, not this
            # component's. 0 everywhere but a cosmetic one-shot that opted in.
            rank=transform.rank,
        )
