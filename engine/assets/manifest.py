"""Manifest v2 loader — INTERFACE STUB (full implementation is Phase 5,
E-35..E-38). Pure metadata code: no pygame.

Phase 1 contract: a manifest maps slot keys to entries; `entry()` returning
None means "no asset assigned" and the store falls back to the grey-X
placeholder (E-23/E-33).
"""


class Manifest:
    """Empty manifest — every slot resolves to 'no entry' (placeholder)."""

    def entry(self, slot_key):
        return None


def load_manifest(path):
    """Phase 5 (E-35): parse data/sprites/asset_manifest.json (v2) into a
    Manifest with row/animation/playback_order semantics."""
    raise NotImplementedError("manifest v2 loading lands in Phase 5 (E-35)")
