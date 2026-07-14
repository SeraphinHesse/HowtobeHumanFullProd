"""Pure asset-side value types (no pygame).

Frame is what the renderer receives when it resolves a RenderItem: an
opaque surface handle plus its pixel size and placement offset. The
renderer treats `surface` as opaque; only the render backend blits it.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Frame:
    surface: object
    frame_w: int
    frame_h: int
    offset_x: int = 0
    offset_y: int = 0
    slice: tuple = None   # nine-slice margins from the manifest entry, or None


class _Placeholder:
    """Unique sentinel: `Manifest.current_frame` returns it when a slot has
    no usable entry (E-36). Compare with `is`. The store maps it to the
    grey-X placeholder surface."""
    __slots__ = ()

    def __repr__(self):
        return "<PLACEHOLDER>"


PLACEHOLDER = _Placeholder()
