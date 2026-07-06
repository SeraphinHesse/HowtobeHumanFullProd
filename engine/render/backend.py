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

from . import fonts
from .item import OverlayLines

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


def _draw_hud_text(target, call):
    font = fonts.get_font(call.font_key)
    surface = font.render(call.text, True, call.color)
    x, y = call.pos
    if call.align == "center":
        x -= surface.get_width() / 2
    elif call.align == "right":
        x -= surface.get_width()
    target.blit(surface, (round(x), round(y)))


def draw(target, draw_calls):
    # Sprite blits accumulate into one batch (target.blits) — far less Python
    # per-blit overhead with hundreds of entities/projectiles. A non-sprite call
    # (overlay/HUD) flushes the batch first so draw order is exact. The dispatch
    # tuple is built here (not a module constant) so it reads the CURRENT module
    # names — the pre-merge HUD test patches backend.HudRect/HudText/HudLines and
    # relies on isinstance seeing the swap. One tuple per draw() call is nothing.
    non_sprite = (OverlayLines, HudRect, HudLines, HudText)
    batch = []
    for call in draw_calls:
        if isinstance(call, non_sprite):
            if batch:
                target.blits(batch, doreturn=False)
                batch.clear()
            if isinstance(call, OverlayLines):
                points = [(round(x), round(y)) for x, y in call.points]
                pygame.draw.lines(target, call.color, call.closed, points,
                                  call.width)
            elif isinstance(call, HudRect):
                pygame.draw.rect(
                    target, call.color, call.rect, call.width,
                    border_radius=call.border_radius,
                )
            elif isinstance(call, HudLines):
                points = [(round(x), round(y)) for x, y in call.points]
                pygame.draw.lines(target, call.color, call.closed, points,
                                  call.width)
            else:  # HudText
                _draw_hud_text(target, call)
            continue
        size = (max(1, round(call.size[0])), max(1, round(call.size[1])))
        surface = _scaled(call.surface, size)
        if call.flip:
            surface = pygame.transform.flip(surface, True, False)
        if call.tint is not None:
            surface = surface.copy()
            surface.fill(call.tint, special_flags=pygame.BLEND_RGBA_MULT)
        batch.append((surface, (round(call.dest[0]), round(call.dest[1]))))
    if batch:
        target.blits(batch, doreturn=False)
