"""Camera state (E-5): pan in screen pixels, zoom factor.

Pure state — input mapping (mouse drag, wheel) lives in the host (game or
editor). Mutation goes through CoordinateSystem (pan / set_zoom / clamp),
which owns the map bounds and the allowed zoom levels — and keeps pan_x/pan_y
INTEGER (see the integer-pan invariant in system.py): a fractional pan makes
the ground cache and the per-item sprite path quantize it at different
sub-pixel phases, visibly desyncing the layers while panning. The fields stay
typed float only so direct construction (tests, the ground cache's private
anchor camera) remains unrestricted.
"""
from dataclasses import dataclass


@dataclass
class Camera:
    pan_x: float = 0.0
    pan_y: float = 0.0
    zoom: float = 2.0
