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

**Precondition a caller must respect: a cached Texture is a SNAPSHOT of its
source surface at first draw, and is never refreshed.** `backend.py:40-42`
returns the LIVE source surface at 1:1, so a consumer that mutates a surface in
place and keeps handing it to the same `DrawCall` renders correctly there and
would silently freeze at first-frame contents here. Nothing shipped does this
(`AssetStore` frames are immutable memoized slices), but a future one must
either hand over a fresh surface or call `clear_cache()`.
"""
import weakref

import pygame
from pygame import Surface
from pygame._sdl2.video import SCALEQUALITY_NEAREST, Texture

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

# Overlay scratch — the "one reused buffer, not one alloc per call" deliverable
# (G5). `_draw_lines`/`_draw_polys` rasterize into this ONE Surface, clipped to
# the target's viewport, instead of a fresh bounding-box SRCALPHA Surface per
# call. It grows to the high-water mark and is NEVER shrunk: a call that needs
# more room than the current buffer replaces it with one sized to the max of
# old and new on each axis; a call that fits reuses it as-is. Growing
# invalidates every per-renderer overlay Texture below (they are sized to
# match), so growth also clears `_overlay_textures`.
_overlay_scratch = None

# One STREAMING Texture per renderer (id(target) keyed, same inner-key
# rationale as `_texture_cache`'s renderer key: pygame-ce's Renderer is not
# weak-referenceable). This can NOT go through `_texture()`/`_texture_cache`
# above — that cache snapshots a Texture at first draw and never refreshes it
# (module docstring, "Precondition a caller must respect"), while the overlay
# scratch's pixels are different on every call. Sized to match
# `_overlay_scratch`; recreated whenever the scratch grows.
_overlay_textures = {}


def clear_cache():
    """Drop every cached Texture (and the strong Renderer references they
    carry), including the reused overlay scratch buffer and its per-renderer
    textures. Mirrors how tests clear `backend._scale_cache`."""
    global _overlay_scratch
    _texture_cache.clear()
    _overlay_scratch = None
    _overlay_textures.clear()


def _texture(target, surface):
    by_renderer = _texture_cache.get(surface)
    if by_renderer is None:
        by_renderer = _texture_cache[surface] = {}
    key = id(target)
    texture = by_renderer.get(key)
    if texture is None:
        texture = _upload(target, surface)
        by_renderer[key] = texture
    return texture


def _upload(target, surface):
    """Upload `surface` to a Texture with BOTH filter-affecting properties set
    EXPLICITLY, never inherited.

    `Texture.from_surface` takes no `scale_quality`, so its filter comes from
    `SDL_HINT_RENDER_SCALE_QUALITY` at creation time — a process-wide default
    that the `SDL_RENDER_SCALE_QUALITY` env var can override and that is not
    contractually stable across pygame-ce versions. Pixel art with hard edges
    and per-pixel alpha is the whole aesthetic here (`engine/render/CLAUDE.md`,
    "transform.scale, not smoothscale"), and linear filtering at zoom would
    fringe every alpha edge — so the nearest-pixel sampler is pinned in code
    via the constructor, and the surface is uploaded with `update()`.
    `blend_mode` is likewise explicit: the empty-texture constructor leaves it
    at `BLENDMODE_NONE` (measured), while the Surface backend alpha-blends
    every sprite blit.
    """
    texture = Texture(target, surface.get_size(),
                      scale_quality=SCALEQUALITY_NEAREST)
    texture.update(surface)
    texture.blend_mode = pygame.BLENDMODE_BLEND
    return texture


def _clip_to_target(target, x, y, w, h):
    """Intersect a raw overlay bbox (already padded, for lines) with the
    target's on-screen bounds. Returns a `pygame.Rect` (clipped, `.x`/`.y`
    the CLIPPED origin the caller must translate points by — TRAP 1), or
    `None` if the overlay is wholly outside the target: a no-op, before any
    allocation, so a zero-size `Surface`/`Texture` never gets built (TRAP 2 —
    `Texture(renderer, (0, 0))` raises `ValueError`, unlike `Surface((0, 0))`
    which constructs silently).

    `target.get_viewport()` is the bound, not `logical_size` — measured
    (docs/briefs/phase-G5-overlay-clip-reuse.md §2a) to return the real
    on-screen Rect while `logical_size` is `(0, 0)` on an unconfigured
    renderer.
    """
    clipped = pygame.Rect(x, y, w, h).clip(target.get_viewport())
    if clipped.w <= 0 or clipped.h <= 0:
        return None
    return clipped


def _overlay_buffer(w, h):
    """Return the module-level reused overlay scratch `Surface`, grown (never
    shrunk) so it is at least `w` x `h`. A grow replaces the buffer with one
    sized to the max of old and new on each axis and invalidates every
    per-renderer overlay Texture in `_overlay_textures` (they are sized to
    match the old buffer)."""
    global _overlay_scratch
    cur_w = _overlay_scratch.get_width() if _overlay_scratch is not None else 0
    cur_h = _overlay_scratch.get_height() if _overlay_scratch is not None else 0
    if w > cur_w or h > cur_h:
        _overlay_scratch = Surface((max(w, cur_w), max(h, cur_h)),
                                   pygame.SRCALPHA)
        _overlay_textures.clear()
    return _overlay_scratch


def _overlay_texture(target):
    """One STREAMING Texture per renderer, sized to match the current
    `_overlay_scratch` and refreshed in place with `update()` per draw —
    never through `_texture()` (see module docstring precondition)."""
    texture = _overlay_textures.get(id(target))
    if texture is None:
        texture = Texture(target, _overlay_scratch.get_size(),
                          scale_quality=SCALEQUALITY_NEAREST, streaming=True)
        texture.blend_mode = pygame.BLENDMODE_BLEND
        _overlay_textures[id(target)] = texture
    return texture


def _draw_overlay_scratch(target, w, h, dst_x, dst_y):
    """Upload the buffer's used (0, 0, w, h) sub-rect — the part `_draw_lines`
    / `_draw_polys` just rasterized into — and draw only that sub-rect at
    (dst_x, dst_y). `srcrect` is required: without it, a small overlay drawn
    from the (larger, high-water-mark) reused buffer would stretch the whole
    buffer over the destination instead of drawing just the used corner."""
    area = pygame.Rect(0, 0, w, h)
    texture = _overlay_texture(target)
    texture.update(_overlay_scratch, area)
    texture.draw(srcrect=area, dstrect=pygame.Rect(dst_x, dst_y, w, h))


def _draw_lines(target, call):
    """OverlayLines via the reused CPU-drawn scratch texture, clipped to the
    target's bounds.

    SDL's own `Renderer.draw_line` is 1px and has no width parameter, while
    `OverlayLines.width` is an arbitrary int (item.py:57). Reproducing
    `pygame.draw.lines`' joins/caps out of SDL primitives would be a second
    implementation of a rasterizer that has to stay pixel-identical to the
    Surface backend forever. Drawing with the SAME `pygame.draw.lines` call
    into an SRCALPHA scratch is parity-exact by construction; only the
    scratch's origin/size (clipped to the target) and its lifetime (reused,
    not per-call) changed from the naive version.
    """
    points = [(_round(x), _round(y)) for x, y in call.points]
    pad = max(1, int(call.width))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs) - pad, min(ys) - pad
    w = max(1, max(xs) - min(xs) + 1 + 2 * pad)
    h = max(1, max(ys) - min(ys) + 1 + 2 * pad)
    clip = _clip_to_target(target, min_x, min_y, w, h)
    if clip is None:
        return
    scratch = _overlay_buffer(clip.w, clip.h)
    scratch.fill((0, 0, 0, 0), pygame.Rect(0, 0, clip.w, clip.h))
    # TRAP 1: translate by the CLIPPED origin (clip.x/clip.y), not the raw
    # bbox origin (min_x/min_y) — the raw origin only matches the clipped one
    # when nothing was clipped.
    pygame.draw.lines(scratch, call.color, call.closed,
                      [(x - clip.x, y - clip.y) for x, y in points],
                      call.width)
    _draw_overlay_scratch(target, clip.w, clip.h, clip.x, clip.y)


def _draw_polys(target, call):
    """OverlayPolys via the reused CPU-drawn scratch texture, clipped to the
    target's bounds — same bounding box as `backend._draw_polys`
    (backend.py:158-171), just intersected with the target first.

    SDL2's renderer primitives are points / lines / rects / triangles / quads;
    `OverlayPolys` is an ARBITRARY-length polygon (ellipses are caller-side
    polygon approximations, i.e. many points) with optional alpha, which no
    quad or triangle primitive covers in general. A scratch texture is the
    only strategy that is parity-exact for both the opaque and the alpha
    case.
    """
    points = [(_round(x), _round(y)) for x, y in call.points]
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs), min(ys)
    w = max(1, max(xs) - min_x + 1)
    h = max(1, max(ys) - min_y + 1)
    clip = _clip_to_target(target, min_x, min_y, w, h)
    if clip is None:
        return
    scratch = _overlay_buffer(clip.w, clip.h)
    scratch.fill((0, 0, 0, 0), pygame.Rect(0, 0, clip.w, clip.h))
    # TRAP 1: translate by the CLIPPED origin, not the raw bbox origin.
    pygame.draw.polygon(scratch, call.color,
                        [(x - clip.x, y - clip.y) for x, y in points])
    _draw_overlay_scratch(target, clip.w, clip.h, clip.x, clip.y)


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
        # The `try` opens BEFORE the first assignment: if `texture.color`
        # succeeds and `texture.alpha` then raises on a malformed tint, the
        # colour modulation would otherwise leak onto the shared cached texture
        # and silently tint every later draw from that source.
        tint = call.tint
        try:
            if tint is not None:
                texture.color = tuple(tint[:3])
                if len(tint) == 4:
                    texture.alpha = tint[3]
            texture.draw(dstrect=dst, flip_x=bool(call.flip), flip_y=False)
        finally:
            if tint is not None:
                texture.color = (255, 255, 255)
                texture.alpha = 255
