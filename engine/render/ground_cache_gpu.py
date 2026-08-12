"""GroundCacheGpu — the SDL2/Texture port of ``ground_cache.GroundCache`` (G3).

Same public surface (``ensure``/``blit``/``invalidate``) and the same
scroll-and-fill technique, ported from a ``pygame.Surface`` to a pair of
render-target ``pygame._sdl2.video.Texture``s so it can sit in front of the
GPU world backend (``backend_gpu.py``, G2) once a host draws the world onto
an SDL ``Renderer`` instead of a ``pygame.Surface`` — at that point there is
no Surface frame buffer left to blit the cache onto, so this class is what
gives the ground layer a legal way to draw at all (G4 wires the host; nothing
here is selected yet).

**Why caching the ground layer is legal in the first place**: ``depth_key``
in ``engine.coords`` makes the draw LAYER the primary sort key, so the entire
``ground`` layer is guaranteed to draw before any ``entities``/``deco``/
``overlay`` item — that layer-primary invariant is what makes it correct to
composite the ground into a cache and draw it first each frame, independent
of whatever the cache is backed by (Surface here, Texture there).

**The one hard rule this class exists to satisfy**: never hand a mutated
Surface to ``backend_gpu`` — its texture cache (``backend_gpu.py:66``)
snapshots a source Surface at first upload and never refreshes it, so a
consumer that repaints a Surface in place and keeps handing it to the same
``DrawCall`` would render correctly on the Surface backend and silently
freeze at first-frame contents here, with no error. This class therefore
paints directly into a render-target ``Texture`` and draws that texture; no
cache Surface exists on this path, and no ``Texture.update()`` re-upload
happens per frame.

``item.round_half_up`` is the quantizer here too, not SDL's own rounding —
same rule and same reason as ``backend_gpu.py``: every dest this class hands
to SDL is pre-quantized and reaches SDL as an already-integer ``pygame.Rect``.

pygame's SDL2 layer (``pygame._sdl2.video``) is allowed here — this is the
second and only other module (besides ``backend_gpu.py``) in this package
that imports it; the allow-list lives in ``engine/CLAUDE.md``. Deliberately a
SEPARATE module from ``ground_cache.py`` rather than a variant class in it, so
the Surface path (the game host, ``tools/profile_render.py``, the CPU test
class) never pulls in the SDL2 layer merely by importing ``ground_cache``.

No game/editor imports — like ``GroundCache``, the caller supplies ground
``RenderItem``s through a callback, so this stays content-agnostic.
"""
import pygame
from pygame._sdl2.video import SCALEQUALITY_NEAREST, Texture

from engine.coords import Camera, CoordinateSystem

from . import backend_gpu
from .ground_cache import band_for_rect
from .item import round_half_up as _round
from .renderer import Renderer


class GroundCacheGpu:
    def __init__(self, sdl_renderer, coords, assets, *, pixel_margin=192,
                 bg_color):
        if bg_color is None:
            # The Surface class's `None` -> SRCALPHA branch exists for
            # static (non-scrolling) consumers; this class has none — the
            # scroll-fill path is its only consumer and it needs an opaque
            # fill for the exposed strip (ground_cache.py's docstring).
            raise ValueError("GroundCacheGpu requires bg_color (no SRCALPHA "
                              "mode: the scroll-fill path needs an opaque "
                              "fill for the exposed strip)")
        self._sdl = sdl_renderer               # the host's live SDL Renderer
        self._coords = coords                  # the host's live CoordinateSystem
        self._margin = int(pixel_margin)
        self._bg_color = bg_color
        # Private coords/renderer so a rebuild never touches the host camera
        # (re-entrancy clean) — identical in name and meaning to
        # ground_cache.GroundCache's private CoordinateSystem/Renderer.
        self._cache_cs = CoordinateSystem(coords.geometry, Camera())
        self._renderer = Renderer(self._cache_cs, assets, backend=backend_gpu.draw)

        # Two identically-sized render-target textures, ping-ponged by
        # _scroll: SDL cannot read and write one render target in a single
        # pass, so a self-blit needs a second target to draw into.
        self._front = None
        self._back = None
        self._anchor_pan = (0.0, 0.0)          # host pan the front texture was baked at
        self._anchor_zoom = None
        self._view_size = None                 # (view_w, view_h) it was sized for
        self._generation = 0                   # bumped by invalidate()
        self._seen_generation = -1             # generation baked into the front texture

    def invalidate(self):
        """Force a full rebuild on the next ``ensure`` (ground content changed)."""
        self._generation += 1

    def ensure(self, view_w, view_h, ground_items_fn):
        """Bring the cached ground texture up to date for the current camera.
        Identical decision tree to ``GroundCache.ensure`` — see that
        docstring; only the surface this paints into differs."""
        cam = self._coords.camera
        pan = (cam.pan_x, cam.pan_y)
        zoom = cam.zoom

        if (self._front is None or self._view_size != (view_w, view_h)
                or zoom != self._anchor_zoom
                or self._generation != self._seen_generation):
            self._rebuild(view_w, view_h, pan, zoom, ground_items_fn)
            return

        sx = -_round(pan[0] - self._anchor_pan[0])
        sy = -_round(pan[1] - self._anchor_pan[1])
        if sx == 0 and sy == 0:
            return
        cw, ch = self._front.width, self._front.height
        if abs(sx) >= cw or abs(sy) >= ch:  # jumped clear off the cached region
            self._rebuild(view_w, view_h, pan, zoom, ground_items_fn)
            return
        self._scroll(sx, sy, zoom, ground_items_fn)

    def blit(self, target):
        """Draw the cached ground at the current pan offset.

        ``target`` is accepted for signature parity with
        ``GroundCache.blit`` (both callers keep the same three-method shape)
        but is not otherwise used: this class always draws through the SDL
        ``Renderer`` bound at construction, and which target that renderer is
        currently pointed at (window or another texture) is the caller's
        concern — same target-agnostic contract as ``Renderer.flush``.

        Same arithmetic as ``GroundCache.blit`` (``screen = iso*zoom - pan``):
        a texture baked at anchor pan ``pan_a`` (minus margin M) sits
        on-screen at ``anchor_pan - current_pan - M``. The dest is quantized
        with ``round_half_up`` and handed to SDL as an already-integer Rect,
        never a float — same rule as ``backend_gpu.py``."""
        if self._front is None:
            return
        cam = self._coords.camera
        m = self._margin
        dx = self._anchor_pan[0] - cam.pan_x - m
        dy = self._anchor_pan[1] - cam.pan_y - m
        cw, ch = self._front.width, self._front.height
        self._front.draw(dstrect=pygame.Rect(_round(dx), _round(dy), cw, ch))

    # -- internals ----------------------------------------------------------

    def _make_texture(self, w, h):
        tex = Texture(self._sdl, (w, h), target=True,
                      scale_quality=SCALEQUALITY_NEAREST)
        # A target=True texture's blend_mode is BLENDMODE_NONE on
        # construction (measured) — correct here (the cache is opaque and
        # fully covers the viewport, so blending a full-cover opaque quad
        # would be wasted work), but set it EXPLICITLY rather than inherit
        # it silently: G2 was bitten by inheriting this value once already.
        tex.blend_mode = pygame.BLENDMODE_NONE
        return tex

    def _anchor_cache_camera(self, zoom):
        """Point the private camera so cache pixel (0,0) maps to host screen
        (-M, -M) at the current anchor pan — identical to
        ``GroundCache._anchor_cache_camera``."""
        cam = self._cache_cs.camera
        cam.pan_x = self._anchor_pan[0] - self._margin
        cam.pan_y = self._anchor_pan[1] - self._margin
        cam.zoom = zoom

    def _paint(self, rect, ground_items_fn):
        """Composite the ground into front-texture pixel ``rect`` (clipped):
        fill with the background, then draw every tile whose diamond can
        touch the rect. The private camera must already be anchored
        (``_anchor_cache_camera``). Band derivation is IDENTICAL to
        ``GroundCache._paint`` (shared via ``band_for_rect`` — not restated).

        The clip here is SDL's ``set_viewport``, not ``Surface.set_clip``,
        and it measures as clipping AND translating: the strip's top-left
        becomes the new (0, 0). That translation is compensated by shifting
        the private camera's pan by the SAME integer (x0, y0) for the
        duration of the paint. This is rounding-exact, not approximate:
        ``round_half_up(v) = floor(v + 0.5)`` satisfies
        ``floor(v + k + 0.5) == floor(v + 0.5) + k`` for any integer k, and
        x0/y0 are always integers (cache-pixel rect coordinates) — so every
        dest lands on exactly the pixel it would have without a viewport.
        The band derivation below uses the UNCOMPENSATED pan with the
        original (un-translated) rect, which is algebraically identical to
        using the compensated pan with a rect at the origin.

        The background fill is ``fill_rect``, never ``clear()`` — measured:
        ``clear()`` ignores the viewport and wipes the WHOLE target, which
        would silently erase the entire cache every scroll.

        Steps that set renderer/viewport state and the steps that reset it
        are symmetric even on an exception (``try/finally``), exactly like
        ``backend_gpu.py``'s tint-modulation bracket, for the same reason:
        leaked target/viewport state on a shared SDL Renderer corrupts the
        host's entire next frame with no error."""
        cam = self._cache_cs.camera
        z = cam.zoom
        hw = self._coords.geometry.tile_w / 2 * z
        hh = self._coords.geometry.tile_h / 2 * z
        d_min, d_max, s_min, s_max = band_for_rect(
            rect, cam.pan_x, cam.pan_y, hw, hh)
        x0, y0, w, h = (int(v) for v in rect)
        orig_pan_x, orig_pan_y = cam.pan_x, cam.pan_y
        try:
            self._sdl.target = self._front
            self._sdl.set_viewport(pygame.Rect(x0, y0, w, h))
            cam.pan_x = orig_pan_x + x0
            cam.pan_y = orig_pan_y + y0
            self._sdl.draw_color = self._bg_color
            self._sdl.fill_rect(pygame.Rect(0, 0, w, h))
            for item in ground_items_fn(d_min, d_max, s_min, s_max):
                self._renderer.submit(item)
            self._renderer.flush(self._sdl)
        finally:
            cam.pan_x, cam.pan_y = orig_pan_x, orig_pan_y
            self._sdl.set_viewport(None)
            self._sdl.target = None

    def _rebuild(self, view_w, view_h, pan, zoom, ground_items_fn):
        m = self._margin
        cw, ch = view_w + 2 * m, view_h + 2 * m
        if (self._front is None
                or (self._front.width, self._front.height) != (cw, ch)):
            self._front = self._make_texture(cw, ch)
            self._back = self._make_texture(cw, ch)
        self._anchor_pan = pan
        self._anchor_zoom = zoom
        self._view_size = (view_w, view_h)
        self._seen_generation = self._generation
        self._anchor_cache_camera(zoom)
        self._paint((0, 0, cw, ch), ground_items_fn)

    def _scroll(self, sx, sy, zoom, ground_items_fn):
        """Shift the baked front texture by (sx, sy) via a self-blit into the
        back texture (SDL cannot read and write one render target in a
        single pass), swap front/back, then repaint the exposed edge strips —
        same signs and same four rects as ``GroundCache._scroll``. The region
        outside the vacated L is fully overwritten by the self-blit, and the L
        itself is fully repainted below, so nothing stale from two frames ago
        can survive on the newly-front texture."""
        cw, ch = self._front.width, self._front.height
        try:
            self._sdl.target = self._back
            self._front.draw(dstrect=pygame.Rect(sx, sy, cw, ch))
        finally:
            self._sdl.target = None
        self._front, self._back = self._back, self._front
        self._anchor_pan = (self._anchor_pan[0] - sx, self._anchor_pan[1] - sy)
        self._anchor_cache_camera(zoom)
        if sx > 0:
            self._paint((0, 0, sx, ch), ground_items_fn)
        elif sx < 0:
            self._paint((cw + sx, 0, -sx, ch), ground_items_fn)
        if sy > 0:
            self._paint((0, 0, cw, sy), ground_items_fn)
        elif sy < 0:
            self._paint((0, ch + sy, cw, -sy), ground_items_fn)
