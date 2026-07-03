"""AssetStore — resolves a RenderItem's slot/animation/time to a Frame.

Surface-side asset code (pygame allowed via placeholder). Phase 1 scope:
the manifest stub never has entries, so every slot resolves to the grey-X
placeholder at the slot's frame size (E-23/E-33). Phase 5 adds manifest v2
sheet slicing and current_frame() time lookup (E-35/E-36) behind this same
interface.
"""
from engine.assets.manifest import Manifest
from engine.assets.placeholder import placeholder_surface
from engine.assets.types import Frame


class AssetStore:
    def __init__(self, manifest=None, frame_sizes=None, default_frame_size=(64, 32)):
        """frame_sizes: optional {slot_key: (w, h)} until the data-driven
        slot registry lands (E-34, Phase 5); unknown slots use the default."""
        self._manifest = manifest if manifest is not None else Manifest()
        self._frame_sizes = dict(frame_sizes or {})
        self._default_frame_size = default_frame_size

    def frame_size(self, slot_key):
        return self._frame_sizes.get(slot_key, self._default_frame_size)

    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        """Never raises on missing art: no manifest entry → placeholder."""
        entry = self._manifest.entry(slot_key)
        if entry is None:
            w, h = self.frame_size(slot_key)
            return Frame(surface=placeholder_surface(w, h), frame_w=w, frame_h=h)
        raise NotImplementedError("manifest-backed frames land in Phase 5 (E-35/E-36)")
