"""engine.assets — slot resolution, manifest (v2 in Phase 5), grey-X placeholder.

Import boundary: this package __init__ and the metadata modules (types,
manifest) are pure Python. pygame lives only in the surface-side modules —
import those explicitly:

    from engine.assets.store import AssetStore          # pygame (placeholder)
    from engine.assets.placeholder import placeholder_surface  # pygame
"""
from .manifest import Manifest, load_manifest
from .types import Frame

__all__ = ["Frame", "Manifest", "load_manifest"]
