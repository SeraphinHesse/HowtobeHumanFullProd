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
    """Filled (width=0) or outlined (width>0) rectangle. rect = (x, y, w, h).
    color may be RGBA — alpha < 255 blends onto the target (10J)."""

    rect: tuple
    color: tuple  # RGB or RGBA
    border_radius: int = 0
    width: int = 0


@dataclass(frozen=True)
class HudText:
    """A run of text. pos = (x, y); align is 'left' | 'center' | 'right'.
    color may be RGBA — alpha < 255 fades the whole run (10J)."""

    text: str
    pos: tuple
    font_key: str
    color: tuple  # RGB or RGBA
    align: str = "left"


@dataclass(frozen=True)
class HudSprite:
    """A sprite slot blitted in screen space. dest = (x, y), size = (w, h).
    Resolved to a DrawCall by the renderer via
    assets.frame(slot_key, animation, anim_time_ms) — same slot/animation/time
    contract as RenderItem, so a HUD element animates like a world sprite. A
    missing animation row falls back to idle (manifest semantics); a
    single-frame track is time-invariant.

    animation/anim_time_ms are appended LAST on purpose: the shipping call
    sites pass (slot_key, dest, size) positionally, so tint/flip must keep
    their positions. crop/hidden_frames are appended after them for the same
    reason (feature-enemy-intro-dialogue): a shipping call passing animation/
    anim_time_ms positionally must not shift.

    crop = (x, y, w, h) in source FRAME pixels — a sub-rect of the resolved
    frame to draw instead of the whole thing, stretched to `size` exactly like
    the whole-frame case. `None` (default) means no crop. hidden_frames is an
    optional tuple of frame-column indices to additionally skip during
    playback, on top of whatever the manifest row's own `hidden` already
    drops (see `engine.assets.manifest.Manifest.current_frame`'s
    `extra_hidden`)."""

    slot_key: str
    dest: tuple
    size: tuple
    tint: tuple = None
    flip: bool = False
    animation: str = "idle"
    anim_time_ms: int = 0
    crop: tuple = None
    hidden_frames: tuple = ()


@dataclass(frozen=True)
class HudLines:
    """A screen-space polyline (already in pixels — unlike OverlayLines, which
    is submitted in world space and converted)."""

    points: tuple
    color: tuple
    width: int = 1
    closed: bool = False
