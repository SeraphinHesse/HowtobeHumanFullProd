"""engine.render — RenderItem pipeline (E-20..E-26).

This __init__ and renderer.py stay pure Python; pygame lives only in
engine.render.backend (loaded lazily on first flush, or injected).
"""
from .item import LAYERS, DrawCall, OverlayLines, RenderItem
from .renderer import Renderer

__all__ = ["LAYERS", "DrawCall", "OverlayLines", "RenderItem", "Renderer"]
