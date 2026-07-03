"""Camera state (E-5): pan in screen pixels, zoom factor.

Pure state — input mapping (mouse drag, wheel) lives in the host (game or
editor). Mutation goes through CoordinateSystem (pan / set_zoom / clamp),
which owns the map bounds and the allowed zoom levels.
"""
from dataclasses import dataclass


@dataclass
class Camera:
    pan_x: float = 0.0
    pan_y: float = 0.0
    zoom: float = 1.0
