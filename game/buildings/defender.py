"""Defender — the starter defence line (Phase 9D).

Stone Thrower -> Slinger -> Pistoleer (``DefenceBuildings.BasicDefence``). Leaf:
subtree path, type key, and per-tier slot prefixes; all behaviour is on
``DefenceBuilding`` / ``Building``.
"""
from .defence import DefenceBuilding


class Defender(DefenceBuilding):
    BUILDING_TYPE = "defence"
    SUBTREE = ("DefenceBuildings", "BasicDefence")
    TIER_SPRITES = ("stone_thrower", "slinger", "pistoleer")
