"""engine.assets — slot resolution, manifest (v2 in Phase 5), grey-X placeholder.

Import boundary: this package __init__ and the metadata modules (types,
manifest) are pure Python. pygame lives only in the surface-side modules —
import those explicitly:

    from engine.assets.store import AssetStore          # pygame (placeholder)
    from engine.assets.placeholder import placeholder_surface  # pygame
"""
from .manifest import (
    Manifest,
    ManifestEntry,
    Track,
    entry_from_dict,
    load_manifest,
    parse_loop,
    playback_order,
)
from .registry import Category, GroupNode, SlotRegistry, load_registry
from .types import Frame, PLACEHOLDER

__all__ = [
    "Category",
    "Frame",
    "GroupNode",
    "Manifest",
    "ManifestEntry",
    "PLACEHOLDER",
    "SlotRegistry",
    "Track",
    "entry_from_dict",
    "load_manifest",
    "load_registry",
    "parse_loop",
    "playback_order",
]
