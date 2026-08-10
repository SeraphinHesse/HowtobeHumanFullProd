"""RenderItem (E-20) and DrawCall — pure data, no pygame.

Game objects submit RenderItems (visual intent, world space); the renderer
resolves them into DrawCalls (screen space, concrete surface) for the
backend. LAYERS is the fixed named draw order (E-26); HUD is drawn by the
host after flush, not through the item pipeline.
"""
from dataclasses import dataclass

LAYERS = ("ground", "terrain", "entities", "deco", "overlay")


@dataclass(frozen=True)
class RenderItem:
    slot_key: str
    world_pos: tuple
    layer: str = "entities"
    animation: str = "idle"
    anim_time_ms: int = 0
    tint: tuple = None
    flip: bool = False
    fit_tiles: float = 0.0   # 0 = no fit: draw at the raw frame size
    scale: float = 1.0       # extra multiplier applied after the fit


@dataclass(frozen=True)
class DrawCall:
    surface: object  # opaque to everything except the backend
    dest: tuple  # screen-space topleft (floats; backend rounds)
    size: tuple  # final blit size in px (backend scales if != surface size)
    tint: tuple = None
    flip: bool = False
    slice: tuple = None  # nine-slice margins (frame px) — HUD sprites only
    crop_rect: tuple = None  # (x, y, w, h) source sub-rect (frame px) — HUD only


@dataclass(frozen=True)
class OverlayLines:
    """E-24 overlay primitive: a polyline. Submitted in WORLD points via
    Renderer.submit_overlay_lines; the renderer emits a screen-space copy
    after all sprite DrawCalls (overlays draw last)."""

    points: tuple  # ((x, y), ...) — world at submit, screen in the backend
    color: tuple
    width: int = 1
    closed: bool = False


@dataclass(frozen=True)
class OverlayPolys:
    """Filled polygon overlay (10J). Same world→screen contract as
    OverlayLines; color may be RGBA — an alpha < 255 alpha-blends onto the
    target (tile fills, splatters, glows)."""

    points: tuple  # ((x, y), ...) — world at submit, screen in the backend
    color: tuple  # RGB or RGBA
