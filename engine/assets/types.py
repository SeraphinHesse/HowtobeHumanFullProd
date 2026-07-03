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
