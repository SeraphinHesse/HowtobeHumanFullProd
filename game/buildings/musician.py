"""Musician — the starter economy line (Phase 9D).

Flute Player -> Harp Player -> Trio (``EconomyBuildings.Musicians``). Leaf: just
the subtree path, type key, and per-tier slot prefixes — all behaviour is on
``EconomyBuilding`` / ``Building``.
"""
from .economy import EconomyBuilding


class Musician(EconomyBuilding):
    BUILDING_TYPE = "economic"
    SUBTREE = ("EconomyBuildings", "Musicians")
    TIER_SPRITES = ("flute_player", "harp_player", "trio")
