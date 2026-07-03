"""THE coordinate authority (E-1..E-5). No other module may do iso math.

Spaces:
  world   — fractional tile coords (wx, wy); the only space game logic uses.
  iso     — intermediate pixel plane at zoom 1 before the camera:
            ix = (wx - wy) * tile_w/2 ; iy = (wx + wy) * tile_h/2.
            world (0,0) is the TOP corner of tile (0,0)'s diamond.
  screen  — pixels on the render target: screen = iso * zoom - pan.
            Camera pan is therefore in screen pixels.

Pure Python — headless-testable, no pygame.
"""
from .camera import Camera


class CoordinateSystem:
    def __init__(self, geometry, camera=None):
        self.geometry = geometry
        self.camera = camera if camera is not None else Camera()
        self._half_w = geometry.tile_w / 2
        self._half_h = geometry.tile_h / 2

    # -- projection (E-2 / E-3) ------------------------------------------

    def world_to_screen(self, wx, wy):
        ix = (wx - wy) * self._half_w
        iy = (wx + wy) * self._half_h
        z = self.camera.zoom
        return ix * z - self.camera.pan_x, iy * z - self.camera.pan_y

    def screen_to_world(self, px, py):
        """Exact inverse of world_to_screen (round-trip < 1e-6 at zoom 1)."""
        z = self.camera.zoom
        ix = (px + self.camera.pan_x) / z
        iy = (py + self.camera.pan_y) / z
        wx = ix / self.geometry.tile_w + iy / self.geometry.tile_h
        wy = iy / self.geometry.tile_h - ix / self.geometry.tile_w
        return wx, wy

    # -- iso depth (E-4) — consumed only by engine/render ----------------

    def depth_key(self, wx, wy, layer_index=0):
        """Sortable draw key: draw layer first, then iso depth (wx+wy),
        then wy as a deterministic tiebreak for equal-depth items."""
        return (layer_index, wx + wy, wy)

    # -- camera (E-5): pure state mutation, no input handling ------------

    def pan(self, dx, dy):
        self.camera.pan_x += dx
        self.camera.pan_y += dy

    def set_zoom(self, zoom):
        if zoom not in self.geometry.zoom_levels:
            raise ValueError(
                f"zoom {zoom!r} not in data-driven levels {self.geometry.zoom_levels}"
            )
        self.camera.zoom = zoom

    def map_pixel_bounds(self):
        """(min_x, min_y, max_x, max_y) of the map's iso extent at the
        current zoom, camera-independent."""
        g = self.geometry
        z = self.camera.zoom
        return (
            -g.map_rows * self._half_w * z,
            0.0,
            g.map_cols * self._half_w * z,
            (g.map_cols + g.map_rows) * self._half_h * z,
        )

    def clamp(self, viewport_w, viewport_h):
        """Clamp pan so the viewport stays on the map; if the map is smaller
        than the viewport on an axis, centre it instead."""
        min_x, min_y, max_x, max_y = self.map_pixel_bounds()
        self.camera.pan_x = _clamp_axis(self.camera.pan_x, min_x, max_x, viewport_w)
        self.camera.pan_y = _clamp_axis(self.camera.pan_y, min_y, max_y, viewport_h)

    def center_on(self, wx, wy, viewport_w, viewport_h):
        """Pan so world (wx, wy) lands at the viewport centre, then clamp
        back onto the map. Centring on the map's own centre is always in
        bounds, so the clamp is a no-op there but still guards a narrow
        axis — unlike clamp alone, which anchors (not centres) an
        overflowing axis (E-5)."""
        z = self.camera.zoom
        ix = (wx - wy) * self._half_w * z
        iy = (wx + wy) * self._half_h * z
        self.camera.pan_x = ix - viewport_w / 2
        self.camera.pan_y = iy - viewport_h / 2
        self.clamp(viewport_w, viewport_h)


def _clamp_axis(pan, lo, hi, view):
    extent = hi - lo
    if extent <= view:
        return lo + (extent - view) / 2
    return min(max(pan, lo), hi - view)
