"""Grey-X placeholder (E-33) — the universal "no asset yet" visual.

pygame IS allowed here (surface-side asset code). Surfaces are cached per
requested frame size; callers must not mutate them.
"""
import pygame

_FILL = (110, 110, 110, 200)
_BORDER = (160, 160, 160, 255)
_CROSS = (60, 60, 60, 255)

_cache = {}


def placeholder_surface(frame_w, frame_h):
    """Grey box with an X, at any requested frame size. Cached per size."""
    key = (frame_w, frame_h)
    surface = _cache.get(key)
    if surface is None:
        surface = pygame.Surface((frame_w, frame_h), pygame.SRCALPHA)
        surface.fill(_FILL)
        rect = surface.get_rect()
        pygame.draw.rect(surface, _BORDER, rect, 1)
        pygame.draw.line(surface, _CROSS, rect.topleft, rect.bottomright, 2)
        pygame.draw.line(surface, _CROSS, rect.bottomleft, rect.topright, 2)
        _cache[key] = surface
    return surface
