"""engine.render — RenderItem pipeline (E-20..E-26).

This __init__ and renderer.py stay pure Python; pygame lives only in
engine.render.backend (loaded lazily on first flush, or injected).
"""
from .hud import HudLines, HudRect, HudSprite, HudText
from .item import LAYERS, DrawCall, OverlayLines, OverlayPolys, RenderItem
from .renderer import (
    Renderer, block_center_offset, fit_factor, sprite_anchor_screen,
)

__all__ = [
    "LAYERS",
    "DrawCall",
    "HudLines",
    "HudRect",
    "HudSprite",
    "HudText",
    "OverlayLines",
    "OverlayPolys",
    "RenderItem",
    "Renderer",
    "block_center_offset",
    "fit_factor",
    "sprite_anchor_screen",
]
