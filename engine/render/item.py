"""RenderItem (E-20) and DrawCall — pure data, no pygame.

Game objects submit RenderItems (visual intent, world space); the renderer
resolves them into DrawCalls (screen space, concrete surface) for the
backend. LAYERS is the fixed named draw order (E-26); HUD is drawn by the
host after flush, not through the item pipeline.
"""
import math
from dataclasses import dataclass

LAYERS = ("ground", "terrain", "entities", "deco", "overlay")


def round_half_up(v):
    """THE pixel quantizer for screen coordinates (backend dests/points, the
    ground cache's scroll/blit offsets). Builtin round() is banker's
    (half-to-even): two dests both ending in .5 can round OPPOSITE ways, and a
    pan crossing a .5 tie can double-step 2px — per item, inconsistently.
    floor(x + 0.5) breaks every tie the same way, so equal sub-pixel phases
    always land on the same pixel. One expression for the same reason as
    fit_factor: a second copy would drift the moment the rule changes."""
    return math.floor(v + 0.5)


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
    column: int = 0          # master-sheet column block to cut from; 0 = the
                             # entry's own stored column


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


@dataclass(frozen=True)
class WorldFill:
    """fix/depth-sorted-world-fills: a flat-color world-space polygon fill
    (optional border), submitted via ``Renderer.submit_world_fill`` and
    sorted into the SAME depth-ordered queue as ``RenderItem`` — unlike
    ``OverlayLines``/``OverlayPolys`` (always drawn dead last, after every
    sprite, regardless of when submitted), a ``WorldFill``'s draw position is
    decided by its own ``world_pos``/``layer`` exactly like a building's, via
    the SAME ``depth_key`` formula. That is what lets a tile highlight or a
    wall segment draw BEHIND a specific building standing on/near it — a
    fixed always-on-top or always-behind layer can only ever approximate
    that; this participates in real per-tile depth instead.

    ``points`` are WORLD-space (converted via coords at flush, same contract
    as ``OverlayPolys``/``OverlayLines``). ``world_pos`` is the depth-sort
    anchor — pass the SAME ``(col, row)`` a building's own ``Transform``
    would use for the tile this fill belongs to, so ties against a same-tile
    building resolve by SUBMISSION ORDER (Python's stable sort): submit the
    fill before the building's ``RenderItem`` to draw it behind, after to
    draw it in front. ``color`` is the fill (``None`` = outline only);
    ``border`` is an optional outline colour drawn on top of the fill."""

    points: tuple             # world-space polygon points, closed implicitly
    world_pos: tuple          # (wx, wy) depth-sort anchor — the RenderItem convention
    layer: str = "entities"
    color: tuple = None       # RGB/RGBA fill; None = outline only
    border: tuple = None      # RGB/RGBA outline colour; None = no outline
    border_width: int = 2
