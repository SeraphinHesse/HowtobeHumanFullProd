"""engine.vfx — procedural particle/gold/slash/splatter VFX (ESV-3a) plus the
scene-object / continuous VFX param dataclasses (ESV-3b: beam / crater /
lightning / announce), plus the one-shot sprite VFX (ESV-5: ``play_once``).

Pure Python (no pygame, no data/ access — D5): every dataclass in
``params.py`` arrives with its numbers already resolved by the caller from
``data/balancing/vfx.json`` (``game/ui/effects.py``'s ``_params_from_balance``
adapter). This module never imports a balancing loader, never opens a file
directly, never learns a JSON key name.

Public surface: the param dataclasses, ``Particle``/``GoldHighlight``/
``Slash``, ``VfxSystem``, and ``PlayOnceVfx``/``PlayOnceFade``/
``spawn_play_once``. ``emitters.py`` (the pure ``emit_*`` functions)
is imported by its full path, like ``engine.render.ground_cache`` — it is the
primitive layer ``VfxSystem`` is built from, not a top-level surface of its
own. ESV-3b's four param dataclasses carry no engine-side behaviour at all —
``VfxSystem`` never touches them (see ``params.py``'s module docstring); they
exist here only so the game side and ESV-4's editor preview share one
definition. ESV-5's ``play_once`` module is unrelated to ``VfxSystem`` too —
``PlayOnceVfx`` is a scene GameObject that ages itself (the ``Corpse``/
``Crater``/``LightningFX`` pattern), not a particle the system's lists own.
"""
from .params import (
    AnnounceParams,
    BeamParams,
    BurstParams,
    CraterParams,
    GoldParams,
    LightningParams,
    MuzzleParams,
    ShardBurstParams,
    SlashParams,
    SplatterParams,
    VfxParams,
)
from .particle import GoldHighlight, Particle, Slash
from .play_once import PlayOnceFade, PlayOnceVfx, spawn_play_once
from .system import VfxSystem

__all__ = [
    "AnnounceParams",
    "BeamParams",
    "BurstParams",
    "CraterParams",
    "GoldHighlight",
    "GoldParams",
    "LightningParams",
    "MuzzleParams",
    "Particle",
    "PlayOnceFade",
    "PlayOnceVfx",
    "ShardBurstParams",
    "Slash",
    "SlashParams",
    "SplatterParams",
    "VfxParams",
    "VfxSystem",
    "spawn_play_once",
]
