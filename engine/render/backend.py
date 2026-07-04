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
    for call in draw_calls:
        if isinstance(call, OverlayLines):
            points = [(round(x), round(y)) for x, y in call.points]
            pygame.draw.lines(target, call.color, call.closed, points, call.width)
            continue
        if isinstance(call, HudRect):
            pygame.draw.rect(
                target, call.color, call.rect, call.width,
                border_radius=call.border_radius,
            )
            continue
        if isinstance(call, HudLines):
            points = [(round(x), round(y)) for x, y in call.points]
            pygame.draw.lines(target, call.color, call.closed, points, call.width)
            continue
        if isinstance(call, HudText):
            _draw_hud_text(target, call)
            continue
        surface = call.surface
        size = (max(1, round(call.size[0])), max(1, round(call.size[1])))
        if size != surface.get_size():
            surface = pygame.transform.scale(surface, size)
        if call.flip:
            surface = pygame.transform.flip(surface, True, False)
        if call.tint is not None:
            surface = surface.copy()
            surface.fill(call.tint, special_flags=pygame.BLEND_RGBA_MULT)
        target.blit(surface, (round(call.dest[0]), round(call.dest[1])))
