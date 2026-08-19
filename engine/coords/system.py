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
import math

from .camera import Camera

#: The rank an effect passes to say "draw me IN FRONT, always" — it beats iso
#: depth instead of only breaking an exact tie (fix/showinfront-always-wins).
#: Ranks below it (the deco -1, the +1/-1 tie-breaks) keep the VA-3 meaning:
#: last word on an otherwise exact tie. See depth_key.
FRONT_RANK = 2


class CoordinateSystem:
    def __init__(self, geometry, camera=None):
        self.geometry = geometry
        self.camera = camera if camera is not None else Camera()
        self._half_w = geometry.tile_w / 2
        self._half_h = geometry.tile_h / 2
        # Optional CameraLimit narrowing clamp() beyond the map bounds. Set by
        # the HOST, never by data loading — the editor deliberately never sets
        # one, so its viewport stays free-roam.
        self.camera_limit = None

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

    def depth_key(self, wx, wy, layer_index=0, rank=0):
        """Sortable draw key: draw layer first, then the ALWAYS-IN-FRONT tier
        (``rank >= FRONT_RANK``), then iso depth (wx+wy), then wy as a
        deterministic tiebreak for equal-depth items, then ``rank`` itself as
        the last word on an otherwise exact tie.

        ``rank`` (VfxAuthoringPLAN VA-3/D5) is how a cosmetic effect says it
        draws in front of or behind the building or enemy standing on its own
        tile. It has TWO tiers, and the split is the whole of
        fix/showinfront-always-wins:

        * ``rank < FRONT_RANK`` (the -1/0/+1 values, and the deco -1) is a
          TIE-BREAK only — position still decides, so a deco tile still
          y-sorts against the enemy walking past it rather than sitting
          unconditionally behind it. This is the original VA-3 meaning and is
          unchanged.
        * ``rank >= FRONT_RANK`` is ABSOLUTE within the layer: the effect
          draws over every same-layer item whatever the iso depth says. This
          is what a VFX row's ``draw_in_front`` now maps to. It used to map to
          +1, which only won an EXACT tie — and once feet-based Y-sorting
          (``depth_pivot``) moved sprites off their tile's exact depth, exact
          ties stopped happening and "show in front" stopped doing anything.

        Layer stays primary above both tiers: the ground cache depends on it,
        so no rank can lift an item out of its layer.

        One bool, not two, is a consequence of this shape: buildings and
        enemies share the ``entities`` layer and sort against each other by
        the same iso depth, so no single total order can put an effect in
        front of one and behind the other.
        """
        return (layer_index, 1 if rank >= FRONT_RANK else 0,
                wx + wy, wy, rank)

    # -- camera (E-5): pure state mutation, no input handling ------------
    #
    # INTEGER-PAN INVARIANT: every mutator below leaves pan_x/pan_y whole.
    # Pan is in screen pixels, and a fractional pan makes each render path
    # quantize it independently at blit time — the ground cache steps at one
    # global threshold while per-item sprites (deco/conditions) step at
    # per-item sub-pixel phases, so the layers visibly desync while panning
    # (worst at zoom 0.5, where frame-width/2 terms land on quarter pixels).
    # Fractions only ever entered via clamp-centring and zoom-recentre
    # division; rounding them here is imperceptible (≤ half a pixel, once).

    def pan(self, dx, dy):
        self.camera.pan_x = round(self.camera.pan_x + dx)
        self.camera.pan_y = round(self.camera.pan_y + dy)

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

    def set_camera_limit(self, limit):
        """Install (or clear, with None) the CameraLimit clamp() honours."""
        self.camera_limit = limit

    def limit_center_bounds(self):
        """(min_x, min_y, max_x, max_y) of where the viewport CENTRE may sit,
        in the same pre-pan iso pixels as map_pixel_bounds and at the current
        zoom; None when no limit is installed. An axis whose max_tiles is
        non-positive is unlimited and comes back as (-inf, +inf), so a
        per-axis disable needs no branch at the call site."""
        lim = self.camera_limit
        if lim is None:
            return None
        z = self.camera.zoom
        a_ix = (lim.anchor_wx - lim.anchor_wy) * self._half_w * z
        a_iy = (lim.anchor_wx + lim.anchor_wy) * self._half_h * z
        rx = lim.max_tiles_x * self._half_w * z
        ry = lim.max_tiles_y * self._half_h * z
        inf = float("inf")
        return (
            a_ix - rx if rx > 0 else -inf,
            a_iy - ry if ry > 0 else -inf,
            a_ix + rx if rx > 0 else inf,
            a_iy + ry if ry > 0 else inf,
        )

    def clamp(self, viewport_w, viewport_h):
        """Clamp pan so the viewport stays on the map; if the map is smaller
        than the viewport on an axis, centre it instead.

        With a CameraLimit installed the allowed region is additionally
        narrowed to the leash box (map bounds ∩ leash) — the tighter of the
        two always wins, and an intersection narrower than the viewport falls
        into the same centring branch as a too-small map. The leash bounds the
        viewport CENTRE, so its centre box is widened by half a viewport to
        become a region box like map_pixel_bounds': _clamp_axis then puts pan
        (the region's left/top edge) in [a - r - view/2, a + r - view/2],
        i.e. the centre within r of the anchor."""
        min_x, min_y, max_x, max_y = self.map_pixel_bounds()
        centre = self.limit_center_bounds()
        if centre is not None:
            hw, hh = viewport_w / 2, viewport_h / 2
            min_x = max(min_x, centre[0] - hw)
            min_y = max(min_y, centre[1] - hh)
            max_x = min(max_x, centre[2] + hw)
            max_y = min(max_y, centre[3] + hh)
        self.camera.pan_x = round(_clamp_axis(self.camera.pan_x, min_x, max_x, viewport_w))
        self.camera.pan_y = round(_clamp_axis(self.camera.pan_y, min_y, max_y, viewport_h))

    def visible_tile_window(self, viewport_w, viewport_h, margin=0):
        """Integer (col_min, col_max, row_min, row_max) of the tiles whose
        diamonds can touch the viewport — for windowed culling (only these
        tiles need to be generated/submitted, no matter how big the map is).

        The visible region is a rotated rectangle in world space; its
        axis-aligned world bounding box has its extrema at the four screen
        corners (an affine map of a rectangle attains min/max at corners), so
        min/max over the four `screen_to_world` corners is exact. `margin` pads
        the box (whole tiles) for tall-sprite overhang / anti-pop-in. Not
        clamped to the map — the tile emitter clamps to [0, cols/rows)."""
        corners = (
            self.screen_to_world(0, 0),
            self.screen_to_world(viewport_w, 0),
            self.screen_to_world(0, viewport_h),
            self.screen_to_world(viewport_w, viewport_h),
        )
        wxs = [wx for wx, _ in corners]
        wys = [wy for _, wy in corners]
        return (
            math.floor(min(wxs)) - margin,
            math.ceil(max(wxs)) + margin,
            math.floor(min(wys)) - margin,
            math.ceil(max(wys)) + margin,
        )

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
