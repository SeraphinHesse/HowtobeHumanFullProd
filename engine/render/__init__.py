"""engine.render — RenderItem pipeline (E-20..E-26).

This __init__ and renderer.py stay pure Python; pygame lives only in
engine.render.backend (loaded lazily on first flush, or injected).
"""
from .hud import (
    HUD_ITEM_TYPES, HudLines, HudRect, HudSprite, HudText, hud_item_from_json,
    hud_item_to_json,
)
from .item import LAYERS, DrawCall, OverlayLines, OverlayPolys, RenderItem, WorldFill
from .renderer import (
    Renderer, block_center_offset, fit_factor, sprite_anchor_screen,
)

__all__ = [
    "HUD_ITEM_TYPES",
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
    "WorldFill",
    "block_center_offset",
    "fit_factor",
    "hud_item_from_json",
    "hud_item_to_json",
    "sprite_anchor_screen",
]
