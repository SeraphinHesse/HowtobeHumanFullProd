"""pygame render backend — the ONLY place in engine/render that imports
pygame. Blits a flat DrawCall list onto a caller-provided target Surface.

The list is heterogeneous: sprite DrawCalls (blit with scale/flip/tint),
OverlayLines (E-24 world polylines, already screen-space here), and — Phase
9B — the screen-space HUD primitives the renderer folds in AFTER the sprites
and overlays: HudRect / HudLines / HudText (HudSprite is resolved to a plain
DrawCall by the renderer, so it never reaches the backend). HUD items carry
pixel coords already; the backend does NOT convert them. Dispatch is by
isinstance, mirroring OverlayLines. Text uses the lazy font cache in
engine.render.fonts — no font is built unless HudText is actually drawn.
"""
import weakref

import pygame

from engine.assets.nine_slice import clamp_pair as _clamp_pair

from . import fonts
from .item import OverlayLines, OverlayPolys, round_half_up as _round

try:
    # The HUD primitive dataclasses are the parallel 9B half (pure Python in
    # engine/render/hud.py). Until that lands, the branches below simply never
    # match — isinstance(x, ()) is a valid, always-False test — so the backend
    # keeps working (OverlayLines + sprites) with the HUD dispatch dormant.
    from .hud import HudLines, HudRect, HudText
except ImportError:  # pragma: no cover - exercised only pre-merge
    HudRect = HudText = HudLines = ()

# Scaled-surface cache: at zoom != 1.0 the same tile/sprite surface is scaled to
# the same size every frame. Cache the resample keyed by the SOURCE surface's
# identity (frame slices are memoized in AssetStore, so identity is stable) with
# a WeakKeyDictionary so the entry evicts when the source surface is GC'd — the
# grey-X placeholder (a fresh surface each call) therefore never leaks. Only the
# scale is cached; flip/tint stay per-call (they vary per instance and copy).
_scale_cache = weakref.WeakKeyDictionary()

# Overlay/HUD scratch — ONE reused SRCALPHA buffer for every translucent
# primitive, instead of a fresh `pygame.Surface(..., SRCALPHA)` per call per
# frame. This is the Surface-backend port of the GPU backend's G5 buffer
# (`backend_gpu._overlay_buffer`) and follows the same two rules:
#
#   * the bbox is CLIPPED to the target first, so an off-screen overlay costs
#     nothing and a partly-visible one only ever sizes the buffer to what is
#     actually on screen (`target.blit` clipped it anyway — this just stops the
#     allocation from being paid);
#   * the buffer GROWS to the high-water mark and is never shrunk, so a steady
#     frame allocates nothing at all.
#
# Unlike the GPU path there is no companion Texture to invalidate on growth:
# the blit reads a `(0, 0, w, h)` sub-rect via its `area` argument, so a small
# primitive drawn from a large buffer draws only its used corner.
_overlay_scratch = None


def _clip_to_target(target, x, y, w, h):
    """Intersect a primitive's bbox with the target's own bounds. Returns the
    clipped `pygame.Rect` (whose `.x`/`.y` are the CLIPPED origin the caller
    must translate its points by — the raw origin only matches when nothing
    was clipped), or `None` when the primitive is wholly off-target."""
    clipped = pygame.Rect(x, y, w, h).clip(target.get_rect())
    if clipped.w <= 0 or clipped.h <= 0:
        return None
    return clipped


def _overlay_buffer(w, h):
    """The module-level reused scratch, grown (never shrunk) to at least
    `w` x `h`, with its used `(0, 0, w, h)` corner cleared to transparent."""
    global _overlay_scratch
    cur_w = _overlay_scratch.get_width() if _overlay_scratch is not None else 0
    cur_h = _overlay_scratch.get_height() if _overlay_scratch is not None else 0
    if w > cur_w or h > cur_h:
        _overlay_scratch = pygame.Surface((max(w, cur_w), max(h, cur_h)),
                                          pygame.SRCALPHA)
    else:
        _overlay_scratch.fill((0, 0, 0, 0), pygame.Rect(0, 0, w, h))
    return _overlay_scratch


def clear_cache():
    """Drop every cached scaled/9-patched/cropped surface and the reused
    overlay scratch. Mirrors `backend_gpu.clear_cache()`."""
    global _overlay_scratch
    _scale_cache.clear()
    _overlay_scratch = None


def _scaled(surface, size):
    if size == surface.get_size():
        return surface
    by_size = _scale_cache.get(surface)
    if by_size is None:
        by_size = _scale_cache[surface] = {}
    scaled = by_size.get(size)
    if scaled is None:
        scaled = by_size[size] = pygame.transform.scale(surface, size)
    return scaled


def _nine_patch(surface, size, margins):
    """Composite `surface` into `size` as a 9-patch: corners blit 1:1, edges
    stretch on one axis, the centre on both.

    Memoized in the SAME weak scale cache, under a ("9p", size, margins) key —
    a 3-tuple, so it can never collide with a plain scale's bare `size` key, and
    the composite dies with its source surface exactly like a plain scale does.
    The margins are IN the key because the editor re-draws one cached frame at
    several margins while the designer drags the slice spinboxes.

    transform.scale (nearest, alpha-safe), not smoothscale: our sheets are pixel
    art with per-pixel alpha, and smoothscale filters RGB across alpha edges
    (fringing). Only the 4 edges + centre are ever resampled — the corners never
    are — so this is a one-line swap if real art ever wants filtering.
    """
    key = ("9p", size, margins)
    by_key = _scale_cache.get(surface)
    if by_key is None:
        by_key = _scale_cache[surface] = {}
    patched = by_key.get(key)
    if patched is not None:
        return patched

    sw, sh = surface.get_size()
    dw, dh = size
    sl, sr = _clamp_pair(margins[0], margins[2], sw)   # margins <= the frame...
    st, sb = _clamp_pair(margins[1], margins[3], sh)
    dl, dr = _clamp_pair(sl, sr, dw)                   # ...and <= the dest
    dt, db = _clamp_pair(st, sb, dh)

    src_cols = ((0, sl), (sl, sw - sl - sr), (sw - sr, sr))
    dst_cols = ((0, dl), (dl, dw - dl - dr), (dw - dr, dr))
    src_rows = ((0, st), (st, sh - st - sb), (sh - sb, sb))
    dst_rows = ((0, dt), (dt, dh - dt - db), (dh - db, db))

    patched = pygame.Surface(size, pygame.SRCALPHA)
    for (sx, sw_i), (dx, dw_i) in zip(src_cols, dst_cols):
        for (sy, sh_i), (dy, dh_i) in zip(src_rows, dst_rows):
            if min(sw_i, sh_i, dw_i, dh_i) <= 0:
                continue          # empty band (degenerate clamp / zero margin)
            region = surface.subsurface(pygame.Rect(sx, sy, sw_i, sh_i))
            if (dw_i, dh_i) != (sw_i, sh_i):
                region = pygame.transform.scale(region, (dw_i, dh_i))
            patched.blit(region, (dx, dy))
    by_key[key] = patched
    return patched


def _cropped(surface, rect):
    """Sub-rect of `surface` (frame-px `(x, y, w, h)`), clamped into the
    surface's own bounds so an out-of-range crop degrades rather than
    raising (E-37) — same tolerance style as `_nine_patch`'s `_clamp_pair`.

    Memoized in the SAME weak scale cache as `_scaled`/`_nine_patch`, under a
    `("crop", (x, y, w, h))` key — a 2-tuple whose first element is a string
    literal distinct from `_nine_patch`'s `"9p"`, so the three kinds of cache
    entry can never collide. The cropped surface is itself a valid cache key
    for a subsequent `_scaled`/`_nine_patch` call (see `draw()`), so "crop,
    then stretch to dest size" shares the existing scale/9-patch machinery
    unchanged.
    """
    sw, sh = surface.get_size()
    x = max(0, min(int(rect[0]), sw - 1))
    y = max(0, min(int(rect[1]), sh - 1))
    w = max(1, min(int(rect[2]), sw - x))
    h = max(1, min(int(rect[3]), sh - y))
    key = ("crop", (x, y, w, h))
    by_key = _scale_cache.get(surface)
    if by_key is None:
        by_key = _scale_cache[surface] = {}
    cropped = by_key.get(key)
    if cropped is None:
        cropped = by_key[key] = surface.subsurface(pygame.Rect(x, y, w, h))
    return cropped


def _has_alpha(color):
    return len(color) == 4 and color[3] < 255


# Antialiasing is OFF for every HUD string, deliberately.
#
# The game draws into a FIXED 640x360 logical buffer (data/display.json) and
# upscales that whole frame to the monitor — 3x on a 1080p panel, 4x on 1440p.
# So a glyph is authored ~9-13px tall and every one of its pixels is blown up
# into a 3x3 or 4x4 block. An antialiased render spends most of the glyph on
# partial-alpha EDGE pixels, and each of those becomes a solid block of grey
# mud at that magnification. Measured with the shipped active font
# (`pixel_gosub`), share of inked pixels that are partial alpha: `sm` (9pt)
# 67.3%, `md` (11pt) 57.1%, `lg` 30.2%, `xl` 25.7%. Two-thirds of the HUD's
# body text was fringe, not letter.
#
# It is also simply the wrong call for the content: EVERY font in
# data/fonts/font_manifest.json is a pixel font, and a pixel font is drawn on
# a whole-pixel grid by design. Measured at every preset in data/ui/fonts.json,
# AA off gives perfectly uniform stems (8 stems of `IIIIIIII`, all identical
# width) — the glyphs land exactly on grid, so there is nothing for
# antialiasing to smooth except detail the designer did not draw.
#
# Layout is UNAFFECTED: `font.render(text, True, ...)` and
# `font.render(text, False, ...)` return byte-identical surface sizes at every
# preset (measured), and `font.size()` — what `fonts.TextMetrics` and the
# pinned `fonts.layout_h` table read — never consulted this flag at all.
_TEXT_ANTIALIAS = False


def _to_alpha_surface(surface):
    """A 32-bit SRCALPHA copy of `surface`, WITHOUT `convert_alpha()`.

    `convert_alpha` needs a display format to convert to and raises "No
    convert format has been set" when none exists — and this backend is
    routinely driven with no display at all (the headless render tests blit
    into bare Surfaces, `tools/smoke.py` runs under SDL dummy). Blitting into
    a fresh SRCALPHA surface reaches the same 32-bit per-pixel-alpha result
    with no display dependency; the source's colorkey is honoured by the blit,
    so the glyph's transparent ground stays transparent."""
    out = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    out.blit(surface, (0, 0))
    return out


def _draw_hud_text(target, call):
    font = fonts.get_font(call.font_key, call.family)
    surface = font.render(call.text, _TEXT_ANTIALIAS, call.color[:3])
    if _has_alpha(call.color):
        # Promote to 32-bit FIRST — this is not cosmetic. An ANTIALIASED
        # render returns a 32-bit per-pixel-alpha surface, where `set_alpha`
        # is a whole-surface multiplier and the colour survives. A NON-
        # antialiased render returns an 8-BIT COLORKEYED surface, where the
        # same call premultiplies the alpha into RGB on blit: measured,
        # translucent red text landed as (128, 0, 0, 128) instead of
        # (255, 0, 0, 128) — every faded string (floaters, hover hints, the
        # cutscene skip prompt) would have darkened as it faded.
        surface = _to_alpha_surface(surface)
        surface.set_alpha(call.color[3])
    x, y = call.pos
    if call.align == "center":
        x -= surface.get_width() / 2
    elif call.align == "right":
        x -= surface.get_width()
    target.blit(surface, (_round(x), _round(y)))


def _draw_hud_rect(target, call):
    if not _has_alpha(call.color):
        pygame.draw.rect(target, call.color, call.rect, call.width,
                         border_radius=call.border_radius)
        return
    x, y, w, h = call.rect
    x, y = _round(x), _round(y)
    w, h = max(1, _round(w)), max(1, _round(h))
    clip = _clip_to_target(target, x, y, w, h)
    if clip is None:
        return
    scratch = _overlay_buffer(clip.w, clip.h)
    # Draw the FULL rect into the clipped buffer at a (possibly negative)
    # offset rather than a shrunken rect: `border_radius` is authored against
    # the whole rect, so re-sizing it to the clip would round the corners of a
    # rectangle the caller never asked for.
    pygame.draw.rect(scratch, call.color,
                     pygame.Rect(x - clip.x, y - clip.y, w, h), call.width,
                     border_radius=call.border_radius)
    target.blit(scratch, (clip.x, clip.y), pygame.Rect(0, 0, clip.w, clip.h))


def _draw_polys(target, call):
    points = [(_round(x), _round(y)) for x, y in call.points]
    if not _has_alpha(call.color):
        pygame.draw.polygon(target, call.color, points)
        return
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    min_x, min_y = min(xs), min(ys)
    w = max(1, max(xs) - min_x + 1)
    h = max(1, max(ys) - min_y + 1)
    clip = _clip_to_target(target, min_x, min_y, w, h)
    if clip is None:
        return
    scratch = _overlay_buffer(clip.w, clip.h)
    # Translate by the CLIPPED origin, not the raw bbox origin.
    pygame.draw.polygon(scratch, call.color,
                        [(x - clip.x, y - clip.y) for x, y in points])
    target.blit(scratch, (clip.x, clip.y), pygame.Rect(0, 0, clip.w, clip.h))


def draw(target, draw_calls):
    # Sprite blits accumulate into one batch (target.blits) — far less Python
    # per-blit overhead with hundreds of entities/projectiles. A non-sprite call
    # (overlay/HUD) flushes the batch first so draw order is exact. The dispatch
    # tuple is built here (not a module constant) so it reads the CURRENT module
    # names — the pre-merge HUD test patches backend.HudRect/HudText/HudLines and
    # relies on isinstance seeing the swap. One tuple per draw() call is nothing.
    non_sprite = (OverlayLines, OverlayPolys, HudRect, HudLines, HudText)
    batch = []
    for call in draw_calls:
        if isinstance(call, non_sprite):
            if batch:
                target.blits(batch, doreturn=False)
                batch.clear()
            if isinstance(call, OverlayLines):
                points = [(_round(x), _round(y)) for x, y in call.points]
                pygame.draw.lines(target, call.color, call.closed, points,
                                  call.width)
            elif isinstance(call, OverlayPolys):
                _draw_polys(target, call)
            elif isinstance(call, HudRect):
                _draw_hud_rect(target, call)
            elif isinstance(call, HudLines):
                points = [(_round(x), _round(y)) for x, y in call.points]
                pygame.draw.lines(target, call.color, call.closed, points,
                                  call.width)
            else:  # HudText
                _draw_hud_text(target, call)
            continue
        size = (max(1, _round(call.size[0])), max(1, _round(call.size[1])))
        # A crop resolves first (feature-enemy-intro-dialogue) — the cropped
        # surface is then scaled/nine-patched exactly like a full frame would
        # be, since _cropped's result is itself a valid cache key. Known,
        # accepted edge case: a crop combined with a nine-slice on the SAME
        # entry is incoherent (slice margins are authored against the full
        # frame) — no shipped entry combines the two.
        source = call.surface
        if call.crop_rect:
            source = _cropped(source, call.crop_rect)
        # An all-zero slice is arithmetically a plain scale, and a 1:1 draw is
        # the identity — both take the plain path so they share its cache entry.
        margins = call.slice
        if margins and any(margins) and size != source.get_size():
            surface = _nine_patch(source, size, tuple(margins))
        else:
            surface = _scaled(source, size)
        if call.flip:
            surface = pygame.transform.flip(surface, True, False)
        if call.tint is not None:
            surface = surface.copy()
            surface.fill(call.tint, special_flags=pygame.BLEND_RGBA_MULT)
        batch.append((surface, (_round(call.dest[0]), _round(call.dest[1]))))
    if batch:
        target.blits(batch, doreturn=False)
