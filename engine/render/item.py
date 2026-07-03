"""RenderItem (E-20) and DrawCall — pure data, no pygame.

Game objects submit RenderItems (visual intent, world space); the renderer
resolves them into DrawCalls (screen space, concrete surface) for the
backend. LAYERS is the fixed named draw order (E-26); HUD is drawn by the
host after flush, not through the item pipeline.
"""
from dataclasses import dataclass

LAYERS = ("ground", "entities", "deco", "overlay")


@dataclass(frozen=True)
class RenderItem:
    slot_key: str
    world_pos: tuple
    layer: str = "entities"
    animation: str = "idle"
    anim_time_ms: int = 0
    tint: tuple = None
    flip: bool = False


@dataclass(frozen=True)
class DrawCall:
    surface: object  # opaque to everything except the backend
    dest: tuple  # screen-space topleft (floats; backend rounds)
    size: tuple  # final blit size in px (backend scales if != surface size)
    tint: tuple = None
    flip: bool = False
