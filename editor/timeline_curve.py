"""XP-curve calculator vocabulary adapter — editor half (TimelinePLAN T3/D7).

A DELIBERATE second copy of ``game/core/xp_curve.py``'s vocabulary and
computation, Qt-free and pygame-free. ``editor/`` may never import ``game/``
(root CLAUDE.md layering rule), so the small amount of game vocabulary that
module carries (which EnemyTypes block maps to which XP key, how a round's
composition is built) has to live here too — the same ``vfx_params.py`` /
``_screen_primitives.py`` precedent this repo already uses for exactly this
class of problem. A cross-package drift test
(``tools/tests/test_xp_curve.py``) pins the two modules' output equal on the
same fixture data, so they cannot silently diverge.

Pure computation lives in ``engine.xp_curve`` (vocabulary-free); this module
adds the mapping tables plus a thin ``data/`` loader for the Timeline panel.
"""
from engine import data_io, era_math
from engine import xp_curve as _xc

from editor import domains

# Keep these five in lockstep with game/core/xp_curve.py — see that module's
# own comments for what each one means and where the values come from.
_ETYPE_FOR_BLOCK = {
    "Standard": "standard",
    "Raider": "raider",
    "SiegeCannon": "siege",
    "Formation": "formation",
    "Commander": "commander",
    "Sniper": "sniper",
    "Digger": "digger",
    "Drummer": "drummer",
}

_XP_KEY_FOR_ETYPE = {
    "standard": "xp_per_standard_enemy",
    "raider": "xp_per_raider",
    "siege": "xp_per_siege_enemy",
    "boss": "xp_per_boss",
}

_BOSS_TABLE_KEY_TO_BLOCK = {
    "regular": "Standard",
    "raiders": "Raider",
    "siege": "SiegeCannon",
    "commander": "Commander",
}

_BOSS_FALLBACK_BLOCKS = ("Standard", "Raider", "SiegeCannon", "Commander")

_BOSS_KEY = "__boss__"


def load_curve_balance(data_dir=None):
    """``(core_balance, enemies_balance)`` — the two domains this module's
    calculator needs, loaded + schema-validated. ``data_dir=None`` defaults
    to the repo's own ``data/`` (test-injectable, the whole-editor
    convention)."""
    core = data_io.load_validated(
        domains.balancing_path("core", data_dir),
        domains.schema_path("core", data_dir))
    enemies = data_io.load_validated(
        domains.balancing_path("enemies", data_dir),
        domains.schema_path("enemies", data_dir))
    return core, enemies


def _type_configs(enemies_balance):
    types = enemies_balance["EnemyTypes"]
    return {
        block: {
            "eras": block_data["eras"],
            "endgame_scaling": block_data["endgame_scaling"],
            "start_round": block_data["start_round"],
        }
        for block, block_data in types.items()
        if block != "Boss"
    }


def _xp_per_block(core_balance):
    xp = core_balance["XP"]
    per_block = {
        block: xp[_XP_KEY_FOR_ETYPE.get(etype, "xp_per_standard_enemy")]
        for block, etype in _ETYPE_FOR_BLOCK.items()
    }
    per_block[_BOSS_KEY] = xp["xp_per_boss"]
    return per_block


def _counts_for_round(round_num, enemies_balance, type_configs):
    scaling = enemies_balance["EnemyScaling"]
    era_cfg = {"rounds_per_era": scaling["rounds_per_era"]}

    if round_num == 0:
        return {"Standard": scaling["tutorial_round_enemy_count"]}

    if era_math.is_boss_round(
            round_num, scaling["rounds_per_era"], scaling["boss_round_in_era"]):
        boss_idx = era_math.era_of_round(round_num, scaling["rounds_per_era"])
        table = enemies_balance["EnemyTypes"]["Boss"]["round_counts"]
        if boss_idx < len(table):
            row = table[boss_idx]
            counts = {
                block: row[table_key]
                for table_key, block in _BOSS_TABLE_KEY_TO_BLOCK.items()
            }
        else:
            counts = {
                block: _xc.type_count_for_round(
                    round_num, era_cfg, type_configs[block])
                for block in _BOSS_FALLBACK_BLOCKS
            }
        counts[_BOSS_KEY] = 1
        return counts

    return _xc.enemy_counts_for_round(round_num, era_cfg, type_configs)


def threshold_sequence(core_balance, n_levels):
    """See ``game/core/xp_curve.py::threshold_sequence`` — byte-identical
    logic, pinned by the drift test."""
    xp = core_balance["XP"]
    threshold = xp["village_xp_base_threshold"]
    inc = xp["village_xp_threshold_inc"]
    growth = xp["village_xp_threshold_inc_growth"]
    cumulative = 0
    out = []
    for _ in range(n_levels):
        cumulative += threshold
        out.append(cumulative)
        threshold += inc
        inc += growth
    return out


def best_case_curve(core_balance, enemies_balance, round_min, round_max,
                     max_levels=200):
    """See ``game/core/xp_curve.py::best_case_curve`` — byte-identical
    logic, pinned by the drift test. Returns ``(cumulative_xp_by_round,
    level_to_round)``."""
    type_configs = _type_configs(enemies_balance)
    xp_per_block = _xp_per_block(core_balance)

    def counts_for_round(round_num):
        return _counts_for_round(round_num, enemies_balance, type_configs)

    cumulative = _xc.cumulative_best_case_xp(
        round_min, round_max, xp_per_block, counts_for_round)
    thresholds = threshold_sequence(core_balance, max_levels)
    level_to_round = _xc.threshold_crossing_rounds(cumulative, thresholds)
    return cumulative, level_to_round
