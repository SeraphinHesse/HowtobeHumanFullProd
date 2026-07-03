"""pygame render backend — the ONLY place in engine/render that imports
pygame. Blits a flat DrawCall list onto a caller-provided target Surface;
OverlayLines entries (E-24, screen-space by the time they get here) are
drawn with pygame.draw.lines.
"""
import pygame

from .item import OverlayLines


def draw(target, draw_calls):
    for call in draw_calls:
        if isinstance(call, OverlayLines):
            points = [(round(x), round(y)) for x, y in call.points]
            pygame.draw.lines(target, call.color, call.closed, points, call.width)
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
