"""engine.render — RenderItem pipeline (E-20..E-26).

This __init__ and renderer.py stay pure Python; pygame lives only in
engine.render.backend (loaded lazily on first flush, or injected).
"""
from .hud import HudLines, HudRect, HudSprite, HudText
from .item import LAYERS, DrawCall, OverlayLines, OverlayPolys, RenderItem
from .renderer import Renderer, fit_factor

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
    "fit_factor",
]
