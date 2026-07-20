"""Frozen param dataclasses for the procedural VFX emitters (ESV-3a).

No defaults on any field: a default here would be a second home for a value
that belongs in ``data/balancing/vfx.json`` (G-7). ``game/ui/effects.py`` is
the ONLY place that reads the balancing dict and builds these — this module
never learns a JSON key name (D5).

One dataclass per ``procedural.*`` table in the vfx balancing schema, except
``floaters`` (colour/lifetime pairs read straight off the balancing dict at
their call sites in ``game/ui/effects.py`` — not an engine concern, see that
module) and ``spark`` presets (game-vocabulary preset keys like
``"place"``/``"tier"`` are resolved to a ``BurstParams`` on the game side; the
engine only ever sees the resolved dataclass).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class BurstParams:
    """A burst of ``count`` particles from one anchor point: a fixed
    velocity range integrated under ``gravity``, coloured by age through the
    3-stop ``ramp``. Used for spark bursts (one instance per game-side
    preset key)."""

    life: float
    count: int
    gravity: float
    ramp: tuple
    vx_min: float
    vx_max: float
    vy_min: float
    vy_max: float
    size_w: int
    size_h: int


@dataclass(frozen=True)
class ShardBurstParams:
    """A building-death shard burst: like ``BurstParams``, but each shard
    picks ONE colour from ``colors`` (held for its whole life — a 1-tuple
    ramp, not a 3-stop age ramp) and draws an independent w/h size from a
    range, instead of a shared fixed size."""

    life: float
    count: int
    gravity: float
    colors: tuple
    vx_min: float
    vx_max: float
    vy_min: float
    vy_max: float
    size_w_min: int
    size_w_max: int
    size_h_min: int
    size_h_max: int


@dataclass(frozen=True)
class MuzzleParams:
    """A ranged-attack muzzle spray: std/strong variants share one ramp,
    velocity range, gravity and size; each particle independently rolls
    ``smoke_chance`` for a 1-tuple ``smoke_color`` ramp instead of the
    3-stop ``ramp``."""

    life: float
    life_strong: float
    count: int
    count_strong: int
    gravity: float
    ramp: tuple
    smoke_color: tuple
    smoke_chance: float
    vx_min: float
    vx_max: float
    vy_min: float
    vy_max: float
    size_w: int
    size_h: int


@dataclass(frozen=True)
class SlashParams:
    """2-3 diagonal lines over a melee attacker; ``size_large`` swaps in for
    a boss-scale attacker."""

    life: float
    colors: tuple
    lines_min: int
    lines_max: int
    ox_min: float
    ox_max: float
    oy_min: float
    oy_max: float
    size: int
    size_large: int


@dataclass(frozen=True)
class GoldParams:
    """A fading gold tile diamond: fade in -> hold -> fade out. The
    fade-out duration is DERIVED (``life - fade_in - hold``), never a
    fourth field — see ``GoldHighlight.frac``."""

    life: float
    fade_in: float
    hold: float
    fill_color: tuple
    border_color: tuple
    fill_alpha: int
    border_width: int


@dataclass(frozen=True)
class SplatterParams:
    """A ground blood mark: a small alpha-filled polygon approximating a
    circle of ``radius_px`` screen pixels, ``jitter``-offset for a blobbier
    silhouette."""

    color: tuple
    alpha: int
    radius_px: float
    jitter: float


@dataclass(frozen=True)
class VfxParams:
    """Everything a ``VfxSystem`` needs beyond spark (spark presets are
    game vocabulary — the caller resolves a preset key to a ``BurstParams``
    and passes it explicitly to ``emit_burst``, so the engine never learns
    the preset names)."""

    death_burst: ShardBurstParams
    muzzle: MuzzleParams
    slash: SlashParams
    gold: GoldParams
    splatter: SplatterParams
