"""HUD primitives (E-12 HUD pass) — pure screen-space data, no pygame.

The host submits these to the Renderer, which folds them into the flat
DrawCall list AFTER the world sprites and overlay lines (HUD always draws on
top, in screen pixels, with no coords conversion and no depth sort). HudSprite
is resolved to a DrawCall by the renderer; the other three are passed through
as-is and isinstance-dispatched by the pygame backend, exactly like
OverlayLines. All coordinates are screen-space pixels.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class HudRect:
    """Filled (width=0) or outlined (width>0) rectangle. rect = (x, y, w, h)."""

    rect: tuple
    color: tuple
    border_radius: int = 0
    width: int = 0


@dataclass(frozen=True)
class HudText:
    """A run of text. pos = (x, y); align is 'left' | 'center' | 'right'."""

    text: str
    pos: tuple
    font_key: str
    color: tuple
    align: str = "left"


@dataclass(frozen=True)
class HudSprite:
    """A sprite slot blitted in screen space. dest = (x, y), size = (w, h).
    Resolved to a DrawCall by the renderer via assets.frame(slot_key)."""

    slot_key: str
    dest: tuple
    size: tuple
    tint: tuple = None
    flip: bool = False


@dataclass(frozen=True)
class HudLines:
    """A screen-space polyline (already in pixels — unlike OverlayLines, which
    is submitted in world space and converted)."""

    points: tuple
    color: tuple
    width: int = 1
    closed: bool = False
