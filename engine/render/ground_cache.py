"""GroundCache — a cached, scroll-updated surface for the static ground layer.

The ground/terrain layer is static during play, yet the naive loop regenerates
+ re-sorts + re-blits every visible tile every frame — thousands of software
blits that cap a large map at a few fps. Because ``depth_key`` in engine.coords
makes the draw LAYER the primary sort key, the entire ``ground`` layer is
guaranteed to draw before any ``entities``/``deco``/``overlay`` item, so it can
be composited into an oversized surface and blitted first each frame with
pixel-identical results.

The surface is oversized (viewport + a pixel margin all round) and baked at an
"anchor" pan. Steady state (pan unchanged) costs ONE blit. When the camera pans,
the surface is SCROLLED in place (a memmove) and only the thin newly-exposed
edge strip is re-composited — work proportional to pan *speed*, not map size or
viewport area. This is the classic scrolling-tilemap technique: an earlier
version rebuilt the WHOLE viewport whenever the pan escaped the margin, which
cost ~70 ms per rebuild (== the old per-frame full render) and stuttered a large
map to a few fps while panning. Scroll-and-fill removes that stall entirely. A
full rebuild happens only on first use, a zoom step, a resize, or an explicit
``invalidate`` (ground content changed).

pygame is allowed here (this is a render surface cache, like the asset store and
the backend). No game/editor imports — the caller supplies the ground
RenderItems through a callback, so this stays content-agnostic (terrain/tint
eyes are the caller's concern).
"""
import math

import pygame

from engine.coords import Camera, CoordinateSystem

from .renderer import Renderer


class GroundCache:
    def __init__(self, coords, assets, *, pixel_margin=192, bg_color=None):
        self._coords = coords                 # the host's live CoordinateSystem
        self._margin = int(pixel_margin)
        # bg_color None -> an SRCALPHA (transparent) cache. A concrete RGB color
        # -> an OPAQUE cache pre-filled with it: pixel-identical to the old path
        # (window.fill(bg) then tiles) and free of alpha-accumulation subtleties,
        # since the ground is the bottom layer and its cache fully covers the
        # viewport. Off-map area then reads back as bg_color (match the host's
        # own window fill so edges look unchanged). Scroll-and-fill REQUIRES the
        # opaque path: the exposed strip is filled with bg_color before repaint.
        self._bg_color = bg_color
        self._fill = bg_color if bg_color is not None else (0, 0, 0, 0)
        # Private coords/renderer so a rebuild never touches the host camera
        # (re-entrancy clean): we render the ground at a fixed "anchor" pan.
        self._cache_cs = CoordinateSystem(coords.geometry, Camera())
        self._renderer = Renderer(self._cache_cs, assets)

        self._surface = None
        self._anchor_pan = (0.0, 0.0)         # host pan the surface was baked at
        self._anchor_zoom = None
        self._view_size = None                # (view_w, view_h) it was sized for
        self._generation = 0                  # bumped by invalidate()
        self._seen_generation = -1            # generation baked into the surface
        # -- 10J underlay (world-locked background art): painted between the
        # bg fill and the tiles in every _paint, so it scrolls/clips with the
        # cache for free. (surface, world_px_x, world_px_y) at zoom 1; a
        # per-zoom scaled copy is cached lazily.
        self._underlay = None
        self._underlay_scaled = {}            # zoom -> scaled surface

    def invalidate(self):
        """Force a full rebuild on the next ``ensure`` (ground content changed)."""
        self._generation += 1

    def set_underlay(self, surface, offset_x=0, offset_y=0):
        """Install (or clear, with ``surface=None``) a world-locked underlay
        image (10J background art): drawn under every ground tile, anchored at
        iso-pixel ``(offset_x, offset_y)`` at zoom 1 and scaled with the zoom.
        Invalidates the cache."""
        self._underlay = (surface, offset_x, offset_y) if surface is not None \
            else None
        self._underlay_scaled = {}
        self.invalidate()

    def ensure(self, view_w, view_h, ground_items_fn):
        """Bring the cached ground surface up to date for the current camera.
        ``ground_items_fn(d_min, d_max, s_min, s_max) -> iterable[RenderItem]``
        supplies ONLY the ground layer for an iso-diagonal band (d = col - row,
        s = col + row — see ``_paint``); ``engine.tilemap.band_render_items`` is
        the caller-side implementation (the caller decides terrain/tint options).
        A full rebuild fires on first use / resize / zoom / invalidate; otherwise
        the surface is scrolled and only the exposed edge strips are repainted."""
        cam = self._coords.camera
        pan = (cam.pan_x, cam.pan_y)
        zoom = cam.zoom

        if (self._surface is None or self._view_size != (view_w, view_h)
                or zoom != self._anchor_zoom
                or self._generation != self._seen_generation):
            self._rebuild(view_w, view_h, pan, zoom, ground_items_fn)
            return

        # Integer pixel scroll to realign the surface with the new pan; sub-pixel
        # remainder is absorbed by blit()'s float offset (anchor stays put for it).
        sx = -round(pan[0] - self._anchor_pan[0])
        sy = -round(pan[1] - self._anchor_pan[1])
        if sx == 0 and sy == 0:
            return
        cw, ch = self._surface.get_size()
        if abs(sx) >= cw or abs(sy) >= ch:  # jumped clear off the cached region
            self._rebuild(view_w, view_h, pan, zoom, ground_items_fn)
            return
        self._scroll(sx, sy, zoom, ground_items_fn)

    def blit(self, target):
        """Blit the cached ground onto ``target`` at the current pan offset.

        Derived from ``screen = iso*zoom - pan``: a tile baked at anchor pan
        ``pan_a`` (minus the margin M) sits on-screen at
        ``anchor_pan - current_pan - M``. When the pan hasn't moved that is
        ``-M`` — the margin simply hangs off the top-left of the viewport."""
        if self._surface is None:
            return
        cam = self._coords.camera
        m = self._margin
        dx = self._anchor_pan[0] - cam.pan_x - m
        dy = self._anchor_pan[1] - cam.pan_y - m
        target.blit(self._surface, (round(dx), round(dy)))

    # -- internals ----------------------------------------------------------

    def _anchor_cache_camera(self, zoom):
        """Point the private camera so cache pixel (0,0) maps to host screen
        (-M, -M) at the current anchor pan (set fields directly — the host zoom
        is already a valid level, so skip set_zoom's re-validation)."""
        cam = self._cache_cs.camera
        cam.pan_x = self._anchor_pan[0] - self._margin
        cam.pan_y = self._anchor_pan[1] - self._margin
        cam.zoom = zoom

    def _paint(self, rect, ground_items_fn):
        """Composite the ground into cache-surface pixel ``rect`` (clipped): fill
        with the background, then blit every tile whose diamond can touch the
        rect. The private camera must already be anchored (``_anchor_cache_camera``).
        Clipping makes seams exact — a diamond straddling a scrolled/exposed
        boundary has its exposed half painted here and its scrolled half already
        in place.

        The tiles are addressed as an iso-diagonal band (``d = col - row``,
        ``s = col + row``) computed from the rect's pixel extent, NOT an
        axis-aligned tile rectangle: a thin strip is diagonal in tile space, so a
        rectangular window would balloon to the whole viewport (and scale with
        map size). ``d = (screen_x + pan_x)/(half_w*z)``, ``s = (screen_y +
        pan_y)/(half_h*z)``; a diamond spans ±1 in d and [s, s+2] down-screen, so
        pad d by 1 and s by (−2, 0) to catch every diamond that laps the rect."""
        cam = self._cache_cs.camera
        z = cam.zoom
        hw = self._coords.geometry.tile_w / 2 * z
        hh = self._coords.geometry.tile_h / 2 * z
        x0, y0, w, h = rect
        d_min = math.floor((x0 + cam.pan_x) / hw) - 1
        d_max = math.ceil((x0 + w + cam.pan_x) / hw) + 1
        s_min = math.floor((y0 + cam.pan_y) / hh) - 2
        s_max = math.ceil((y0 + h + cam.pan_y) / hh)
        clip_rect = pygame.Rect(rect)
        prev = self._surface.get_clip()
        self._surface.set_clip(clip_rect)
        self._surface.fill(self._fill, clip_rect)
        if self._underlay is not None:  # 10J world-locked background art
            surf, ox, oy = self._underlay
            scaled = self._underlay_scaled.get(z)
            if scaled is None:
                size = (max(1, round(surf.get_width() * z)),
                        max(1, round(surf.get_height() * z)))
                scaled = surf if size == surf.get_size() \
                    else pygame.transform.scale(surf, size)
                self._underlay_scaled[z] = scaled
            # screen = iso_px*zoom - pan; the clip confines it to the strip
            self._surface.blit(
                scaled, (round(ox * z - cam.pan_x), round(oy * z - cam.pan_y)))
        for item in ground_items_fn(d_min, d_max, s_min, s_max):
            self._renderer.submit(item)
        self._renderer.flush(self._surface)
        self._surface.set_clip(prev)

    def _rebuild(self, view_w, view_h, pan, zoom, ground_items_fn):
        m = self._margin
        cw, ch = view_w + 2 * m, view_h + 2 * m
        if self._surface is None or self._surface.get_size() != (cw, ch):
            flags = 0 if self._bg_color is not None else pygame.SRCALPHA
            self._surface = pygame.Surface((cw, ch), flags)
        self._anchor_pan = pan
        self._anchor_zoom = zoom
        self._view_size = (view_w, view_h)
        self._seen_generation = self._generation
        self._anchor_cache_camera(zoom)
        self._paint((0, 0, cw, ch), ground_items_fn)

    def _scroll(self, sx, sy, zoom, ground_items_fn):
        """Shift the baked surface by (sx, sy) and repaint the exposed edge
        strips. The anchor advances by the integer we scrolled; the sub-pixel
        remainder rides along in blit()'s float offset."""
        cw, ch = self._surface.get_size()
        self._surface.scroll(sx, sy)
        self._anchor_pan = (self._anchor_pan[0] - sx, self._anchor_pan[1] - sy)
        self._anchor_cache_camera(zoom)
        # scroll(sx, sy) moves content by +(sx, sy); the vacated edge is on the
        # opposite side. Repaint an L of up to two strips (their overlap corner
        # is painted twice — harmless).
        if sx > 0:
            self._paint((0, 0, sx, ch), ground_items_fn)
        elif sx < 0:
            self._paint((cw + sx, 0, -sx, ch), ground_items_fn)
        if sy > 0:
            self._paint((0, 0, cw, sy), ground_items_fn)
        elif sy < 0:
            self._paint((0, ch + sy, cw, -sy), ground_items_fn)
