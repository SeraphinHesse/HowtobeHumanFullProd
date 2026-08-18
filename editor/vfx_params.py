"""Pure Qt-free mirror of ``game/ui/effects.py``'s ``_color``/``_ramp``/
``_params_from_balance`` (ESV-4).

``editor/`` may never import ``game/`` (root ``CLAUDE.md`` layering rule), so
the vfx preview panel cannot reuse the game-side adapter that turns a
validated ``data/balancing/vfx.json`` dict into ``engine.vfx`` dataclasses.
This module is the editor's own local copy of that ONE mapping (JSON key
names <-> dataclass fields) — a DELIBERATE, sanctioned drift, precedented by
``editor/panels/_screen_primitives.py`` re-implementing ``game/ui``'s
unskinned widget look for the same layering reason (see
``editor/CLAUDE.md``). Do not "fix" the duplication by importing
``game.ui.effects`` or by moving this mapping into ``engine/vfx`` — the
engine package must never learn a JSON key name (D5); that duplication is
reported upward in the ESV-4 phase report, not resolved here.

Stdlib + ``engine.vfx`` only. No Qt, no pygame, no ``data/`` access, no
``game`` import.
"""
from engine.vfx import (
    AnnounceParams,
    BeamParams,
    BurstParams,
    CraterParams,
    DrummerAuraParams,
    FloaterParams,
    GoldParams,
    LightningParams,
    MuzzleParams,
    ProjectileParams,
    ShardBurstParams,
    SlashParams,
    SplatterParams,
    VfxParams,
)


def color(c):
    return tuple(c)


def ramp(stops):
    """A ``{stop_0, stop_1, stop_2}`` named-stop object -> the engine's
    3-tuple-of-colour-tuples shape. Mirrors ``game/ui/effects.py::_ramp``:
    the named-stop shape is load-bearing (a bare array-of-arrays crashes the
    balancing form's ``_make_widget`` for the whole ``vfx`` domain — see that
    function's docstring), so this NEVER reorders or flattens the stops."""
    return (color(stops["stop_0"]), color(stops["stop_1"]),
            color(stops["stop_2"]))


def spark_burst_params(spark, preset_key):
    """Resolve one spark preset (``place``/``level1``/``level2``/``tier`` —
    game vocabulary, opaque to ``engine.vfx``) to a ``BurstParams``."""
    preset = spark["presets"][preset_key]
    return BurstParams(
        life=preset["life"], count=preset["count"], gravity=spark["gravity"],
        ramp=ramp(spark["ramp"]),
        vx_min=spark["vx_min"], vx_max=spark["vx_max"],
        vy_min=spark["vy_min"], vy_max=spark["vy_max"],
        size_w=spark["size_w"], size_h=spark["size_h"])


def death_burst_params(death):
    return ShardBurstParams(
        life=death["life"], count=death["count"], gravity=death["gravity"],
        colors=ramp(death["colors"]),
        vx_min=death["vx_min"], vx_max=death["vx_max"],
        vy_min=death["vy_min"], vy_max=death["vy_max"],
        size_w_min=death["size_w_min"], size_w_max=death["size_w_max"],
        size_h_min=death["size_h_min"], size_h_max=death["size_h_max"])


def muzzle_params(mz):
    return MuzzleParams(
        life=mz["life"], life_strong=mz["life_strong"],
        count=mz["count"], count_strong=mz["count_strong"],
        gravity=mz["gravity"], ramp=ramp(mz["ramp"]),
        smoke_color=color(mz["smoke_color"]), smoke_chance=mz["smoke_chance"],
        vx_min=mz["vx_min"], vx_max=mz["vx_max"],
        vy_min=mz["vy_min"], vy_max=mz["vy_max"],
        size_w=mz["size_w"], size_h=mz["size_h"])


def slash_params(sl):
    return SlashParams(
        life=sl["life"], colors=ramp(sl["colors"]),
        lines_min=sl["lines_min"], lines_max=sl["lines_max"],
        ox_min=sl["ox_min"], ox_max=sl["ox_max"],
        oy_min=sl["oy_min"], oy_max=sl["oy_max"],
        size=sl["size"], size_large=sl["size_large"])


def gold_params(gh):
    return GoldParams(
        life=gh["life"], fade_in=gh["fade_in"], hold=gh["hold"],
        fill_color=color(gh["fill_color"]),
        border_color=color(gh["border_color"]),
        fill_alpha=gh["fill_alpha"], border_width=gh["border_width"])


def splatter_params(sp):
    return SplatterParams(
        color=color(sp["color"]), alpha=sp["alpha"],
        radius_px=sp["radius_px"], jitter=sp["jitter"])


def beam_params(bm):
    return BeamParams(
        colors=ramp(bm["colors"]), width_base=bm["width_base"],
        origin_lift_tiles=bm["origin_lift_tiles"])


def crater_params(cr):
    return CraterParams(
        color=color(cr["color"]), alpha=cr["alpha"], life=cr["life"],
        segments=cr["segments"])


def lightning_params(lp):
    return LightningParams(
        bolt_segments=lp["bolt_segments"], bolt_jitter_px=lp["bolt_jitter_px"],
        bolt_color_start=color(lp["bolt_color_start"]),
        bolt_color_end=color(lp["bolt_color_end"]),
        bolt_width=lp["bolt_width"], bolt_life=lp["bolt_life"],
        flash_radius_px=lp["flash_radius_px"],
        flash_color=color(lp["flash_color"]), flash_alpha=lp["flash_alpha"],
        marker_color=color(lp["marker_color"]),
        marker_fill_alpha=lp["marker_fill_alpha"],
        marker_outline_width=lp["marker_outline_width"],
        marker_life=lp["marker_life"],
        marker_segments=lp["marker_segments"])


def announce_params(an):
    return AnnounceParams(
        color=color(an["color"]), max_alpha=an["max_alpha"])


def floater_params(fl):
    """ESV-6: mirrors ``game/ui/effects.py::_params_from_balance``'s new
    ``floaters`` read. ``floaters`` carries no preview lever of its own
    (``_EMIT_FAMILIES`` in ``vfx_preview.py`` still degrades it to the
    graceful-placeholder branch — it is text colours/lifetimes, not a
    particle emitter) — this is required purely so ``VfxParams`` (a required,
    no-default field, G-7) can still be constructed for every OTHER family's
    preview."""
    return FloaterParams(
        upkeep_color=color(fl["upkeep_color"]),
        xp_color=color(fl["xp_color"]), xp_life=fl["xp_life"],
        painter_finished_color=color(fl["painter_finished_color"]),
        painter_lost_color=color(fl["painter_lost_color"]),
        painter_life=fl["painter_life"],
        boost_color=color(fl["boost_color"]), income_life=fl["income_life"])


def projectile_params(pr):
    """fix-anchor-offset-and-bullet-sprites Fix 2: mirrors ``game/ui/
    effects.py::_params_from_balance``'s new ``projectile`` read. Like
    ``floaters``, it carries no preview lever of its own (``_EMIT_FAMILIES``
    degrades it to the graceful-placeholder branch — a projectile is a
    continuous in-flight object the game draws itself, not a particle
    emitter this preview drives) — required purely so ``VfxParams`` (a
    required, no-default field, G-7) stays constructible for every OTHER
    family's preview."""
    return ProjectileParams(
        stone_color=color(pr["stone_color"]),
        shell_color=color(pr["shell_color"]),
        stone_size=pr["stone_size"], shell_size=pr["shell_size"],
        lift_frac=pr["lift_frac"])


def drummer_aura_params(da):
    """Mirrors ``game/ui/effects.py::_params_from_balance``'s new
    ``drummer_aura`` read. Like ``floaters``/``projectile``, it carries no
    preview lever of its own (``_EMIT_FAMILIES`` degrades it to the
    graceful-placeholder branch — it is a live-component-driven ring, not a
    particle this preview emits) — required purely so ``VfxParams`` (a
    required, no-default field, G-7) stays constructible for every OTHER
    family's preview."""
    return DrummerAuraParams(
        color=color(da["color"]), alpha_min=da["alpha_min"],
        alpha_max=da["alpha_max"], pulse_period_s=da["pulse_period_s"],
        segments=da["segments"])


def params_from_balance(proc):
    """Mirrors ``game/ui/effects.py::_params_from_balance``'s structure, but
    takes the already-unwrapped ``procedural`` dict — the vfx preview panel
    reads ``BalancingPanel.staged_value("procedural")``, never the full
    ``vfx.json`` doc. Returns ``(spark_presets, VfxParams)``, same shape as
    the game-side function."""
    spark = proc["spark"]
    spark_presets = {key: spark_burst_params(spark, key)
                      for key in spark["presets"]}
    return spark_presets, VfxParams(
        death_burst=death_burst_params(proc["death_burst"]),
        muzzle=muzzle_params(proc["muzzle"]),
        slash=slash_params(proc["slash"]),
        gold=gold_params(proc["gold_highlight"]),
        splatter=splatter_params(proc["splatter"]),
        beam=beam_params(proc["beam"]),
        crater=crater_params(proc["crater"]),
        lightning=lightning_params(proc["lightning"]),
        announce=announce_params(proc["announce"]),
        floaters=floater_params(proc["floaters"]),
        projectile=projectile_params(proc["projectile"]),
        drummer_aura=drummer_aura_params(proc["drummer_aura"]))
