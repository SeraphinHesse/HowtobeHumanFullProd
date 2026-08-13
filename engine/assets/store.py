"""AssetStore — resolves a RenderItem's slot/animation/time to a Frame.

Surface-side asset code (pygame allowed). The pure manifest answers WHICH
(sheet_row, sheet_col) a slot/animation shows at a time (E-36); this store
loads the sheet PNG and slices that frame out. Missing/corrupt sheets log
once and fall back to the grey-X placeholder — rendering never raises on
bad art (E-23/E-37).

Never call convert()/convert_alpha() here: they need a display mode and the
editor runs under SDL dummy drivers. Sliced frames are subsurfaces, so the
parent sheet must stay cached for as long as the store lives. Sheets are
cached by SOURCE PATH, so one PNG decodes once however many slots name it
(entries claim their own row band of a shared sheet via `row_start`). There
is no cache invalidation — when the manifest changes, build a new AssetStore.
"""
import logging
from pathlib import Path

import pygame

from engine.assets.manifest import Manifest
from engine.assets.nine_slice import dest_to_source
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
        # Sheets are keyed by SOURCE PATH: many slots may name one PNG (a
        # linked sheet, or a master sheet each slot windows with `row_start`),
        # and one file must decode exactly once into exactly one Surface.
        self._sheets = {}   # entry.sheet -> Surface | _LOAD_FAILED
        # Frames and hit masks stay SLOT-keyed even though the sheet no longer
        # is — this is decision D10, and it is deliberate, not an oversight.
        # Only the raw Surface is safe to share. Two slots naming one PNG cut
        # it DIFFERENTLY: each applies its own `row_start` window, and each may
        # declare its own frame_w/frame_h, so the same (row, col) means
        # different pixels per slot. A sheet-keyed frame cache would hand slot
        # B slot A's art — a silent wrong-pixels bug, not a crash. Note the
        # frame-size half stands on its own: two `row_start: 0` slots on one
        # shared PNG at different frame sizes are already unsafe to merge.
        # Folding frame_w/frame_h/row_start into the key to dedup frames too is
        # a NOTED FOLLOW-UP, deliberately not done here.
        self._frames = {}   # (slot_key, row, col) -> Surface | _LOAD_FAILED
        self._hit_masks = {}   # (slot_key, row, col) -> pygame.Mask

    def animation_total_ms(self, slot_key, name):
        """The named animation's total playback duration in ms for a slot, or
        ``None`` when the slot or that animation is absent (no idle fallback).
        Pure metadata lookup — delegates to the manifest."""
        return self._manifest.animation_ms(slot_key, name)

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

    def anchor(self, slot_key, name):
        """(x, y) frame-px anchor point named `name` (ESV-1) for a slot's
        manifest entry, or None when the slot, its entry, or that anchor name
        is absent. Anchors are metadata, not frame geometry — unlike
        `frame()` this never touches pygame or a sheet surface."""
        entry = self._manifest.entry(slot_key)
        if entry is None:
            return None
        return entry.anchor(name)

    def offset(self, slot_key):
        """(x, y) int frame-px draw nudge (`offset_x`/`offset_y`) for a
        slot's manifest entry, or `(0, 0)` when the slot or its entry is
        absent. Metadata, not frame geometry — never touches pygame or a
        sheet surface, same shape as `anchor()`."""
        entry = self._manifest.entry(slot_key)
        if entry is None:
            return (0, 0)
        return (entry.offset_x, entry.offset_y)

    def frame(self, slot_key, animation="idle", anim_time_ms=0, extra_hidden=None):
        """Never raises on missing/corrupt art: falls back to the grey X.

        `extra_hidden` (optional): passed straight through to
        `Manifest.current_frame` — a caller-side frame-column narrowing on
        top of whatever the manifest row already hides."""
        ref = self._manifest.current_frame(slot_key, animation, int(anim_time_ms),
                                            extra_hidden=extra_hidden)
        if ref is PLACEHOLDER:
            return self._placeholder(slot_key)
        entry = self._manifest.entry(slot_key)
        surface = self._frame_surface(entry, ref)
        if surface is _LOAD_FAILED:
            return self._placeholder(slot_key)
        return Frame(surface=surface, frame_w=entry.frame_w,
                     frame_h=entry.frame_h, offset_x=entry.offset_x,
                     offset_y=entry.offset_y, slice=entry.slice)

    def hit_opaque(self, slot_key, animation="idle", anim_time_ms=0,
                   dest_size=None, rel_xy=(0, 0)):
        """Opaque-pixel test for a slot's frame at a destination coord
        (pixel-perfect hit test for skinned buttons — E-37/R2).

        Args:
            slot_key: asset slot key.
            animation: animation row (default "idle"); falls back to idle if
                missing, same as `frame()`.
            anim_time_ms: frame resolution time (default 0).
            dest_size: (dw, dh) blit destination size in pixels; defaults to
                the frame size. Used by the nine-patch inverse to map screen
                coords back to the source frame.
            rel_xy: (x, y) screen-space click coords relative to the dest
                top-left (default (0, 0)). The CALLER must clamp this to
                `[0, dest_size[0]) x [0, dest_size[1])` — this method never
                validates bounds against `dest_size`, only against the
                resolved SOURCE frame (see below).

        Returns:
            True if the pixel at `rel_xy` is opaque (alpha > 0) in the
            resolved frame. Never raises: a placeholder frame (no art yet)
            or a corrupt/missing sheet degrades to True (E-37 — opaque
            everywhere, so a partially-imported build stays fully
            clickable); a `rel_xy` that maps outside the source frame
            (e.g. an out-of-bounds click the caller failed to clamp)
            degrades to False rather than raising."""
        ref = self._manifest.current_frame(slot_key, animation, int(anim_time_ms))
        if ref is PLACEHOLDER:
            return True   # placeholder: opaque everywhere
        entry = self._manifest.entry(slot_key)
        surface = self._frame_surface(entry, ref)
        if surface is _LOAD_FAILED:
            return True   # corrupt/missing sheet: degrade to opaque

        row, col = ref
        key = (entry.slot_key, row, col)
        mask = self._hit_masks.get(key)
        if mask is None:
            mask = self._hit_masks[key] = pygame.mask.from_surface(
                surface, threshold=0)

        if dest_size is None:
            dest_size = (entry.frame_w, entry.frame_h)
        sx, sy = dest_to_source(rel_xy, dest_size,
                                (entry.frame_w, entry.frame_h), entry.slice)

        if not (0 <= sx < entry.frame_w and 0 <= sy < entry.frame_h):
            return False   # OOB in source: safe read, never raise
        return bool(mask.get_at((sx, sy)))

    # ── internals ──────────────────────────────────────────────────────────

    def _placeholder(self, slot_key):
        w, h = self.frame_size(slot_key)
        return Frame(surface=placeholder_surface(w, h), frame_w=w, frame_h=h)

    def _sheet(self, entry):
        # Cache key is the sheet PATH, not the slot key — see __init__.
        # Consequence, accepted deliberately: a failing sheet is logged ONCE,
        # naming only the FIRST slot that asked for it, not every slot sharing
        # it. That is fine — the resolved path is printed and it is the
        # actionable half. Do not "fix" this by enumerating slots.
        sheet_key = entry.sheet
        if sheet_key in self._sheets:
            return self._sheets[sheet_key]
        if self._sprites_dir is None:
            log.warning("no sprites_dir configured — %s renders as placeholder",
                        entry.slot_key)
            surface = _LOAD_FAILED
        else:
            path = self._sprites_dir / entry.sheet
            try:
                surface = pygame.image.load(str(path))
            except (OSError, pygame.error) as exc:
                log.warning("could not load sheet %s for %s: %s — using "
                            "placeholder", path, entry.slot_key, exc)
                surface = _LOAD_FAILED
        self._sheets[sheet_key] = surface
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
            # THE one place the entry's row window is applied: `row` is an
            # index into this entry's own rows[], `sheet_row` is where that
            # lands in the (possibly shared) PNG.
            sheet_row = row + entry.row_start
            rect = pygame.Rect(col * entry.frame_w, sheet_row * entry.frame_h,
                               entry.frame_w, entry.frame_h)
            try:
                surface = sheet.subsurface(rect)
            except ValueError:
                log.warning("frame (row %d, col %d) of %s — sheet row %d "
                            "(row_start %d) — is outside its sheet %s — using "
                            "placeholder", row, col, entry.slot_key, sheet_row,
                            entry.row_start, entry.sheet)
                surface = _LOAD_FAILED
        self._frames[key] = surface
        return surface
