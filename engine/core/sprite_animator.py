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
        )
