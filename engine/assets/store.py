"""AssetStore — resolves a RenderItem's slot/animation/time to a Frame.

Surface-side asset code (pygame allowed). The pure manifest answers WHICH
(sheet_row, sheet_col) a slot/animation shows at a time (E-36); this store
loads the sheet PNG and slices that frame out. Missing/corrupt sheets log
once and fall back to the grey-X placeholder — rendering never raises on
bad art (E-23/E-37).

Never call convert()/convert_alpha() here: they need a display mode and the
editor runs under SDL dummy drivers. Sliced frames are subsurfaces, so the
parent sheet must stay cached for as long as the store lives. There is no
cache invalidation — when the manifest changes, build a new AssetStore.
"""
import logging
from pathlib import Path

import pygame

from engine.assets.manifest import Manifest
from engine.assets.placeholder import placeholder_surface
from engine.assets.types import Frame, PLACEHOLDER

log = logging.getLogger(__name__)

_LOAD_FAILED = object()   # cached marker: sheet unusable, already logged


class AssetStore:
    def __init__(self, manifest=None, registry=None, frame_sizes=None,
                 default_frame_size=(64, 32), sprites_dir=None):
        """manifest: engine.assets.Manifest (empty when omitted).
        registry: engine.assets.SlotRegistry for data-driven frame sizes
        (E-34). frame_sizes: {slot_key: (w, h)} escape hatch for slots
        outside the registry (e.g. test dummies). sprites_dir: base dir the
        manifest's relative sheet paths resolve against (data/sprites)."""
        self._manifest = manifest if manifest is not None else Manifest()
        self._registry = registry
        self._frame_sizes = dict(frame_sizes or {})
        self._default_frame_size = default_frame_size
        self._sprites_dir = Path(sprites_dir) if sprites_dir is not None else None
        self._sheets = {}   # slot_key -> Surface | _LOAD_FAILED
        self._frames = {}   # (slot_key, row, col) -> Surface | _LOAD_FAILED

    def frame_size(self, slot_key):
        """(w, h) for a slot: manifest entry > registry > frame_sizes > default."""
        entry = self._manifest.entry(slot_key)
        if entry is not None:
            return (entry.frame_w, entry.frame_h)
        if self._registry is not None:
            try:
                return self._registry.frame_size(slot_key)
            except KeyError:
                pass
        return self._frame_sizes.get(slot_key, self._default_frame_size)

    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        """Never raises on missing/corrupt art: falls back to the grey X."""
        ref = self._manifest.current_frame(slot_key, animation, int(anim_time_ms))
        if ref is PLACEHOLDER:
            return self._placeholder(slot_key)
        entry = self._manifest.entry(slot_key)
        surface = self._frame_surface(entry, ref)
        if surface is _LOAD_FAILED:
            return self._placeholder(slot_key)
        return Frame(surface=surface, frame_w=entry.frame_w,
                     frame_h=entry.frame_h, offset_x=entry.offset_x,
                     offset_y=entry.offset_y, slice=entry.slice)

    # ── internals ──────────────────────────────────────────────────────────

    def _placeholder(self, slot_key):
        w, h = self.frame_size(slot_key)
        return Frame(surface=placeholder_surface(w, h), frame_w=w, frame_h=h)

    def _sheet(self, entry):
        slot_key = entry.slot_key
        if slot_key in self._sheets:
            return self._sheets[slot_key]
        if self._sprites_dir is None:
            log.warning("no sprites_dir configured — %s renders as placeholder",
                        slot_key)
            surface = _LOAD_FAILED
        else:
            path = self._sprites_dir / entry.sheet
            try:
                surface = pygame.image.load(str(path))
            except (OSError, pygame.error) as exc:
                log.warning("could not load sheet %s for %s: %s — using "
                            "placeholder", path, slot_key, exc)
                surface = _LOAD_FAILED
        self._sheets[slot_key] = surface
        return surface

    def _frame_surface(self, entry, ref):
        row, col = ref
        key = (entry.slot_key, row, col)
        if key in self._frames:
            return self._frames[key]
        sheet = self._sheet(entry)
        if sheet is _LOAD_FAILED:
            surface = _LOAD_FAILED
        else:
            rect = pygame.Rect(col * entry.frame_w, row * entry.frame_h,
                               entry.frame_w, entry.frame_h)
            try:
                surface = sheet.subsurface(rect)
            except ValueError:
                log.warning("frame (row %d, col %d) of %s is outside its "
                            "sheet — using placeholder", row, col,
                            entry.slot_key)
                surface = _LOAD_FAILED
        self._frames[key] = surface
        return surface
