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


@dataclass(frozen=True)
class CameraLimit:
    """Leash the camera CENTRE to a box around a world anchor point.

    Sizes are in TILES (grid steps), so the leash means the same thing at
    every zoom level; 0 (or negative) = unlimited on that axis. Bounds the
    viewport CENTRE, not the visible edge — the viewer still sees roughly
    half a viewport beyond the limit.

    Vocabulary-free like the rest of this package: it knows an anchor and a
    tile count, never a "spawn point" or a map. The host decides what the
    anchor is (game/main.py: the map's camera_start marker, else the map
    centre) and installs it via CoordinateSystem.set_camera_limit.
    """
    anchor_wx: float
    anchor_wy: float
    max_tiles_x: float = 0.0
    max_tiles_y: float = 0.0
