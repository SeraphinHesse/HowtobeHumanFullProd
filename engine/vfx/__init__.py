"""engine.vfx — procedural particle/gold/slash/splatter VFX (ESV-3a).

Pure Python (no pygame, no data/ access — D5): every dataclass in
``params.py`` arrives with its numbers already resolved by the caller from
``data/balancing/vfx.json`` (``game/ui/effects.py``'s ``_params_from_balance``
adapter). This module never imports a balancing loader, never opens a file
directly, never learns a JSON key name.

Public surface: the param dataclasses, ``Particle``/``GoldHighlight``/
``Slash``, and ``VfxSystem``. ``emitters.py`` (the pure ``emit_*`` functions)
is imported by its full path, like ``engine.render.ground_cache`` — it is the
primitive layer ``VfxSystem`` is built from, not a top-level surface of its
own.
"""
from .params import (
    BurstParams,
    GoldParams,
    MuzzleParams,
    ShardBurstParams,
    SlashParams,
    SplatterParams,
    VfxParams,
)
from .particle import GoldHighlight, Particle, Slash
from .system import VfxSystem

__all__ = [
    "BurstParams",
    "GoldHighlight",
    "GoldParams",
    "MuzzleParams",
    "Particle",
    "ShardBurstParams",
    "Slash",
    "SlashParams",
    "SplatterParams",
    "VfxParams",
    "VfxSystem",
]
