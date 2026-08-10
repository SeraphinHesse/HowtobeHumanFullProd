"""HUD primitives (E-12 HUD pass) — pure screen-space data, no pygame.

The host submits these to the Renderer, which folds them into the flat
DrawCall list AFTER the world sprites and overlay lines (HUD always draws on
top, in screen pixels, with no coords conversion and no depth sort). HudSprite
is resolved to a DrawCall by the renderer; the other three are passed through
as-is and isinstance-dispatched by the pygame backend, exactly like
OverlayLines. All coordinates are screen-space pixels.
"""
from dataclasses import dataclass, fields


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
    their positions."""

    slot_key: str
    dest: tuple
    size: tuple
    tint: tuple = None
    flip: bool = False
    animation: str = "idle"
    anim_time_ms: int = 0


@dataclass(frozen=True)
class HudLines:
    """A screen-space polyline (already in pixels — unlike OverlayLines, which
    is submitted in world space and converted)."""

    points: tuple
    color: tuple
    width: int = 1
    closed: bool = False


# -- JSON round-trip (UT-2) --------------------------------------------------
#
# A recorded draw list crosses a process boundary as JSON: `tools/` records
# what a game screen submits, the EDITOR replays it in its screen-mode preview
# (`data/ui/screen_previews.json`). Both sides consume `engine/`, and neither
# may import the other, so the one serialization rule lives here beside the
# dataclasses it describes rather than being written twice.

#: `type` tag -> dataclass. The tag is the on-disk contract
#: (`screen_previews.schema.json`'s enum); the class name is an implementation
#: detail, so renaming either stays local.
HUD_ITEM_TYPES = {
    "rect": HudRect,
    "text": HudText,
    "sprite": HudSprite,
    "lines": HudLines,
}
_HUD_TAG_BY_CLASS = {cls: tag for tag, cls in HUD_ITEM_TYPES.items()}


def _jsonable(value):
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    return value


def hud_item_to_json(item):
    """One HUD primitive -> a plain JSON dict `{type, ...fields}`.

    EVERY field is emitted, defaults included, so a reader never has to know
    this module's default values — and a default changed here shows up as a
    real diff in the generated file rather than silently re-meaning every
    existing entry.
    """
    tag = _HUD_TAG_BY_CLASS.get(type(item))
    if tag is None:
        raise TypeError(f"not a HUD primitive: {item!r}")
    out = {"type": tag}
    for f in fields(item):
        out[f.name] = _jsonable(getattr(item, f.name))
    return out


def _detuple(value):
    """Every JSON array back to a tuple, at every depth — `HudLines.points` is
    a tuple OF point tuples, and a half-restored `([0, 0], ...)` compares
    unequal to the item it was written from."""
    if isinstance(value, (list, tuple)):
        return tuple(_detuple(v) for v in value)
    return value


def hud_item_from_json(spec):
    """The inverse of `hud_item_to_json`. JSON arrays come back as tuples —
    what every downstream consumer unpacks. Unknown keys are ignored so a file
    written by a newer field set still loads."""
    data = dict(spec)
    cls = HUD_ITEM_TYPES[data.pop("type")]
    kwargs = {f.name: _detuple(data[f.name])
              for f in fields(cls) if f.name in data}
    return cls(**kwargs)
