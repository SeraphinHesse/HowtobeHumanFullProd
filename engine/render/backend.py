"""pygame render backend — the ONLY place in engine/render that imports
pygame. Blits a flat DrawCall list onto a caller-provided target Surface.
"""
import pygame


def draw(target, draw_calls):
    for call in draw_calls:
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
