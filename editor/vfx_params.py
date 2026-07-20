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
    BurstParams,
    GoldParams,
    MuzzleParams,
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
        splatter=splatter_params(proc["splatter"]))
