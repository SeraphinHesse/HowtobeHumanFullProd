"""SDL2 / Texture render backend — the WORLD path only (G2).

This is the second and only other module in `engine/render` allowed to import
pygame's SDL2 layer (`pygame._sdl2.video`); the allow-list in
`engine/CLAUDE.md` names it explicitly alongside `backend.py`.

**Scope (plan decision D7).** It draws sprites and overlays onto a
`pygame._sdl2.video.Renderer`. The HUD stays single-implementation on
`backend.py`: `HudRect` / `HudLines` / `HudText`, nine-slice (`DrawCall.slice`)
and crop (`DrawCall.crop_rect`) are HUD-only and are *asserted* here, not
implemented — they raise `NotImplementedError`. G4 composites the Surface-drawn
HUD over the GPU frame.

**`item.round_half_up` is the authoritative quantizer, not SDL's rounding.**
`Texture.draw` accepts float rects and routes to SDL's float copy, which rounds
its own way; every dest/size/overlay point here is pre-quantized with
`round_half_up` and handed to SDL as an already-integer `pygame.Rect`. Anything
else desyncs this backend from the ground cache and every other consumer of the
quantizer (`engine/render/CLAUDE.md`, "Pixel quantizer").

**Nothing selects this backend yet** — `Renderer.flush()` still resolves
`backend_api.default_backend()` (the Surface backend). Host wiring, fallback
selection and the HUD composite are G4.

The win over `backend.py`: a source surface is uploaded to the GPU ONCE and all
scaling lives in the destination rect, so zoom != 1 costs no
`pygame.transform.scale` per frame.
"""
import weakref

import pygame
from pygame._sdl2.video import Texture

from .item import OverlayLines, OverlayPolys, round_half_up as _round

try:
    from .hud import HudLines, HudRect, HudText
except ImportError:  # pragma: no cover - mirrors backend.py's dormant dispatch
    HudRect = HudText = HudLines = ()

# Texture cache — the "one upload per source surface" deliverable.
#
# OUTER key is the SOURCE SURFACE identity in a WeakKeyDictionary, exactly like
# backend.py's _scale_cache (backend.py:31-36): each AssetStore sheet surface
# uploads once, and the grey-X placeholder (a FRESH surface every call) evicts
# with its surface instead of leaking textures.
#
# INNER key is id(target). A Texture belongs to the Renderer that created it and
# cannot be used by another ("Textures created by different Renderers cannot
# shared with each other!" — Renderer.blit's own docstring), so the renderer has
# to be part of the key. pygame-ce 2.5.7's Renderer is NOT weak-referenceable
# (measured: `weakref.ref(renderer)` raises TypeError), so a nested
# WeakKeyDictionary is impossible and id() is the fallback. The id-reuse hazard
# is bounded to nothing in practice here: the cached Texture holds a strong
# reference to its Renderer (`Texture.renderer`), so while an entry for a given
# id is alive that id cannot have been recycled by a different live Renderer.
# `clear_cache()` is what keeps tests honest across renderers.
_texture_cache = weakref.WeakKeyDictionary()


def clear_cache():
    """Drop every cached Texture (and the strong Renderer references they
    carry). Mirrors how tests clear `backend._scale_cache`."""
    _texture_cache.clear()


def _texture(target, surface):
    by_renderer = _texture_cache.get(surface)
    if by_renderer is None:
        by_renderer = _texture_cache[surface] = {}
    key = id(target)
    texture = by_renderer.get(key)
    if texture is None:
        texture = Texture.from_surface(target, surface)
        # Explicit rather than relying on from_surface's default: the Surface
        # backend alpha-blends every sprite blit, so the GPU path must too.
        texture.blend_mode = pygame.BLENDMODE_BLEND
        by_renderer[key] = texture
    return texture


def _scratch_texture(target, surface):
    """Upload a per-call scratch surface. Deliberately NOT cached — its pixels
    are unique to one overlay call."""
    texture = Texture.from_surface(target, surface)
    texture.blend_mode = pygame.BLENDMODE_BLEND
    return texture


def _draw_lines(target, call):
    """OverlayLines via a CPU-drawn scratch texture.

    SDL's own `Renderer.draw_line` is 1px and has no width parameter, while
    `OverlayLines.width` is an arbitrary int (item.py:57). Reproducing
    `pygame.draw.lines`' joins/caps out of SDL primitives would be a second
    implementation of a rasterizer that has to stay pixel-identical to the
    Surface backend forever. Drawing with the SAME `pygame.draw.lines` call into
    a bounding-box SRCALPHA scratch and uploading it is parity-exact by
    construction. Overlays are a handful of calls per frame; the sprites are
    where the port's win lives.
    """
    points = [(_round(x), _round(y)) for x, y in call.points]
    pad = max(1, int(call.width))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs) - pad, min(ys) - pad
    w = max(1, max(xs) - min(xs) + 1 + 2 * pad)
    h = max(1, max(ys) - min(ys) + 1 + 2 * pad)
    scratch = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.lines(scratch, call.color, call.closed,
                      [(x - min_x, y - min_y) for x, y in points], call.width)
    _scratch_texture(target, scratch).draw(
        dstrect=pygame.Rect(min_x, min_y, w, h))


def _draw_polys(target, call):
    """OverlayPolys via a CPU-drawn scratch texture — same bounding box as
    `backend._draw_polys` (backend.py:158-171).

    SDL2's renderer primitives are points / lines / rects / triangles / quads;
    `OverlayPolys` is an ARBITRARY-length polygon (ellipses are caller-side
    polygon approximations, i.e. many points) with optional alpha, which no
    quad or triangle primitive covers in general. A scratch texture is the only
    strategy that is parity-exact for both the opaque and the alpha case.
    """
    points = [(_round(x), _round(y)) for x, y in call.points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs), min(ys)
    w = max(1, max(xs) - min_x + 1)
    h = max(1, max(ys) - min_y + 1)
    scratch = pygame.Surface((w, h), pygame.SRCALPHA)
    pygame.draw.polygon(scratch, call.color,
                        [(x - min_x, y - min_y) for x, y in points])
    _scratch_texture(target, scratch).draw(
        dstrect=pygame.Rect(min_x, min_y, w, h))


_HUD_MSG = (
    "backend_gpu draws the WORLD path only. {what} is HUD-only "
    "(engine/render/backend_api.py:34-38); the HUD stays on the Surface "
    "backend and composites over the GPU frame in G4 (plan D7)."
)


def draw(target, draw_calls):
    """Draw a flat DrawCall list onto an SDL `Renderer`. Satisfies the
    `backend_api.Backend` protocol.

    No batching: draws happen in list order, which is trivially identical to
    front-to-back (`backend_api.py:45-47`). Per-draw SDL calls are the point.
    """
    hud = (HudRect, HudLines, HudText)
    for call in draw_calls:
        if isinstance(call, OverlayLines):
            _draw_lines(target, call)
            continue
        if isinstance(call, OverlayPolys):
            _draw_polys(target, call)
            continue
        if isinstance(call, hud):
            raise NotImplementedError(
                _HUD_MSG.format(what=type(call).__name__))
        # `and any(call.slice)`: an all-zero slice tuple is TRUTHY but is
        # arithmetically a plain scale, and backend.py:216 already treats it as
        # one — so it must not trip this guard.
        if call.slice and any(call.slice):
            raise NotImplementedError(_HUD_MSG.format(what="DrawCall.slice"))
        if call.crop_rect:
            raise NotImplementedError(
                _HUD_MSG.format(what="DrawCall.crop_rect"))

        # round_half_up governs BOTH dest and size; SDL never gets a float rect.
        w = max(1, _round(call.size[0]))
        h = max(1, _round(call.size[1]))
        dst = pygame.Rect(_round(call.dest[0]), _round(call.dest[1]), w, h)
        texture = _texture(target, call.surface)
        # The texture is CACHED and SHARED, so colour/alpha modulation LEAKS
        # into the next draw from the same source — the hazard backend.py:223's
        # surface.copy() sidesteps on the Surface path. Set, draw, reset.
        tint = call.tint
        if tint is not None:
            texture.color = tuple(tint[:3])
            if len(tint) == 4:
                texture.alpha = tint[3]
        try:
            texture.draw(dstrect=dst, flip_x=bool(call.flip), flip_y=False)
        finally:
            if tint is not None:
                texture.color = (255, 255, 255)
                texture.alpha = 255
