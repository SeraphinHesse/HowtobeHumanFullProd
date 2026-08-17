"""Frozen param dataclasses for the procedural VFX emitters (ESV-3a), the
scene-object / continuous VFX (ESV-3b: beam / crater / lightning / announce)
and the floater colours/lifetimes (ESV-6: ``FloaterParams``).

No defaults on any field: a default here would be a second home for a value
that belongs in ``data/balancing/vfx.json`` (G-7). ``game/ui/effects.py`` is
the ONLY place that reads the balancing dict and builds these — this module
never learns a JSON key name (D5).

One dataclass per ``procedural.*`` table in the vfx balancing schema, except
``spark`` presets (game-vocabulary preset keys like ``"place"``/``"tier"`` are
resolved to a ``BurstParams`` on the game side; the engine only ever sees the
resolved dataclass).

ESV-3b's four dataclasses (``BeamParams``/``CraterParams``/``LightningParams``/
``AnnounceParams``), ESV-6's ``FloaterParams`` and ``DrummerAuraParams`` are
NOT consumed by ``VfxSystem`` — those effects own no particle/gold/slash/
splatter LIST (the scene already owns the crater/lightning state; floaters
are a bare colour+lifetime pair with no particle behaviour at all; the
Drummer aura ring is drawn straight off the live ``DrummerAura`` component,
no scene-object fade clock of its own). ``game/ui/effects.py`` reads them
straight off the ``VfxParams`` bundle it holds.
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
class BeamParams:
    """A continuous line from a beam-tier defender to its live target (Sun
    Scorcher): a 3-tier colour ``ramp`` indexed (clamped) by the building's
    tier, a base line width that thickens by +1 px per tier, and how many
    tile-heights above the origin the line starts. Draws no random numbers —
    read fresh off the live scene every frame, never emitted/cached."""

    colors: tuple
    width_base: int
    origin_lift_tiles: float


@dataclass(frozen=True)
class CraterParams:
    """A fading world-space scorch mark at a mortar shell's landing point.
    ``life`` seconds is the fade lifetime (carried on the ``Crater``
    GameObject's ``CraterFade`` component, not read from here at fade time —
    this dataclass only feeds the DRAW). The fill alpha scales linearly with
    the remaining fade fraction. ``segments`` is the world-unit polygon-ring
    vertex count (the shared ring helper `game/ui/effects.py` draws with —
    the mortar's splash is Euclidean in TILE space, so this ring is the exact
    damage-area shape, not just a cosmetic upgrade over the old 4-point
    diamond). Draws no random numbers."""

    color: tuple
    alpha: int
    life: float
    segments: int


@dataclass(frozen=True)
class LightningParams:
    """A lightning strike's jagged bolt + impact flash + ground marker. The
    bolt is the one ESV-3b effect that draws random numbers — EVERY
    submitted frame, not once at emit, so its horizontal jitter re-rolls and
    shimmers frame to frame (the caller's injected ``rng``, never a fresh
    ``random.Random()`` — that would desync the shared global draw stream).
    ``bolt_life``/``marker_life`` are carried on the ``LightningFX``
    GameObject's ``LightningFXFade`` component, not read from here at fade
    time — this dataclass only feeds the DRAW. ``marker_segments`` is the
    ground blast-marker's world-unit polygon-ring vertex count (the shared
    ring helper `game/ui/effects.py` draws with, generalised from the
    impact-flash octagon's own fixed 8 segments — ``bolt_segments`` stays a
    SEPARATE field, the bolt polyline is a different shape entirely)."""

    bolt_segments: int
    bolt_jitter_px: int
    bolt_color_start: tuple
    bolt_color_end: tuple
    bolt_width: int
    bolt_life: float
    flash_radius_px: float
    flash_color: tuple
    flash_alpha: int
    marker_color: tuple
    marker_fill_alpha: int
    marker_outline_width: int
    marker_life: float
    marker_segments: int


@dataclass(frozen=True)
class AnnounceParams:
    """The boss-round announcement banner's colour + alpha ceiling. The two
    copy strings (game vocabulary — screen-skinning territory) and the
    fade-in/hold/fade-out timings (already in ``ui.json`` ``FX.boss_announce``)
    stay OUT of this dataclass."""

    color: tuple
    max_alpha: int


@dataclass(frozen=True)
class FloaterParams:
    """Income/XP/painter/boost floater colours + lifetimes (ESV-6, closing
    the plan's §6 item 1 dead-data gap: ``data/balancing/vfx.json``'s
    ``procedural.floaters`` block existed since ESV-3a but was never read —
    the live values were a second copy, seven module constants in
    ``game/ui/effects.py``). Text layout itself stays HUD chrome, owned by
    that module, not this dataclass — these are colour/lifetime numbers
    only, no engine-side behaviour (like ESV-3b's four scene-object
    dataclasses, ``VfxSystem`` never touches this one either)."""

    upkeep_color: tuple
    xp_color: tuple
    xp_life: float
    painter_finished_color: tuple
    painter_lost_color: tuple
    painter_life: float
    boost_color: tuple
    # Payout-phase sequencing: the boost/economy/upkeep beat floaters'
    # lifetime (game/ui/effects.py FloaterManager.begin_payout) — decoupled
    # from core.PhaseLoop.income_phase_duration, which is now the payout
    # phase's own post-last-beat hold time, not a floater lifetime.
    income_life: float


@dataclass(frozen=True)
class ProjectileParams:
    """Fallback dot appearance for an in-flight shot with no imported sprite
    on ``vfx_projectile``/``vfx_shell`` (``game/ui/effects.py``'s
    ``submit_projectiles``): independent colour/size for the shell (mortar)
    and stone (every other defender) variants, plus how far off the ground
    plane the dot is lifted, as a fraction of ``tile_h``. Like ESV-3b's four
    scene-object dataclasses and ESV-6's ``FloaterParams``, ``VfxSystem``
    never touches this one either — projectiles are continuous in-flight
    objects the game draws itself, not a particle any list owns. The
    ``max(2, size * zoom)`` low-zoom floor is a degeneracy guard, not a
    tunable, and stays inline in ``game/ui/effects.py``."""

    stone_color: tuple
    shell_color: tuple
    stone_size: int
    shell_size: int
    lift_frac: float


@dataclass(frozen=True)
class DrummerAuraParams:
    """The Drummer's (NE-3) buff-range telegraph: a pulsing world-space ring
    around a live Drummer, sized to its own ``support_range`` — the same
    ``_polygon_ring`` world-unit N-gon technique the mortar crater draws
    with, but with NO scene-object fade clock of its own: the ring is drawn
    fresh every frame straight off the live ``DrummerAura`` component for as
    long as the Drummer is alive, never spawned/despawned as a separate
    GameObject. ``alpha_min``/``alpha_max`` bound a smooth sine breathe over
    ``pulse_period_s`` seconds (the ``hud.py`` XP-bar level-up pulse shape);
    ``segments`` is the ring's polygon-ring vertex count. Draws no random
    numbers."""

    color: tuple
    alpha_min: int
    alpha_max: int
    pulse_period_s: float
    segments: int


@dataclass(frozen=True)
class VfxParams:
    """Everything a ``VfxSystem`` needs beyond spark (spark presets are
    game vocabulary — the caller resolves a preset key to a ``BurstParams``
    and passes it explicitly to ``emit_burst``, so the engine never learns
    the preset names), plus ESV-3b's four scene-object/continuous param
    blocks, ESV-6's ``floaters`` and the fix-anchor-offset-and-bullet-sprites
    brief's ``projectile``, none of which ``VfxSystem`` touches (see the
    module docstring). APPEND ONLY — do not rename or reorder fields."""

    death_burst: ShardBurstParams
    muzzle: MuzzleParams
    slash: SlashParams
    gold: GoldParams
    splatter: SplatterParams
    beam: BeamParams
    crater: CraterParams
    lightning: LightningParams
    announce: AnnounceParams
    floaters: FloaterParams
    projectile: ProjectileParams
    drummer_aura: DrummerAuraParams
