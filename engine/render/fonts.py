"""Lazy SysFont("monospace", …) cache + TextMetrics (Phase 9B).

Mirrors the prototype's src/ui/fonts.py size set for the engine HUD pass, so
the render backend can turn HudText items into blitted surfaces and game/ui
can measure strings for layout WITHOUT importing pygame itself (it asks
TextMetrics). pygame.font works headless under SDL dummy; the cache is built
lazily (fonts created on first request) so callers that never draw text pay
nothing, and font.init() is called defensively so construction never crashes.

font_key set: sm/md/lg/xl/xxl mirror the prototype 1:1 (lg/xl/xxl bold), plus
hud_phase/hud_lvl for the phase (bottom-left) and village-level readouts.
"""
import pygame

# font_key -> (point size, bold). Prototype fonts.init() parity for the shared
# set; lg/xl/xxl are bold there, the hud_* corners are not.
_FONT_SPECS = {
    "sm": (9, False),
    "md": (11, False),
    "lg": (13, True),
    "xl": (18, True),
    "xxl": (26, True),
    "hud_phase": (14, False),
    "hud_lvl": (12, False),
}

_FALLBACK_KEY = "md"

_cache = {}


def _ensure_init():
    if not pygame.font.get_init():
        pygame.font.init()


def _is_usable(font):
    """A SysFont whose pygame.font session was torn down (a prior pygame.quit)
    raises 'font module quit since font created' on ANY use — even after a fresh
    pygame.init leaves get_init() True. Probe cheaply so ``get_font`` can rebuild
    a stale cache entry (matters when a host re-boots pygame in one process:
    tools tests / smoke run game.main repeatedly)."""
    try:
        font.get_height()
        return True
    except pygame.error:
        return False


def get_font(font_key):
    """Cached SysFont for font_key (created on first use, rebuilt if its pygame
    session died). Unknown keys fall back to 'md', mirroring the prototype's
    fonts.get()."""
    _ensure_init()
    key = font_key if font_key in _FONT_SPECS else _FALLBACK_KEY
    font = _cache.get(key)
    if font is not None and not _is_usable(font):
        font = None
    if font is None:
        size, bold = _FONT_SPECS[key]
        font = pygame.font.SysFont("monospace", size, bold=bold)
        _cache[key] = font
    return font


class TextMetrics:
    """Measures rendered text for HUD layout without blitting — a pure size
    query over the shared font cache (`font.size(text)` → (w, h) in px)."""

    def size(self, text, font_key):
        return get_font(font_key).size(text)
