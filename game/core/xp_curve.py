"""XP-curve calculator vocabulary adapter (TimelinePLAN T3/D7).

``engine.xp_curve`` is deliberately vocabulary-free; this module carries the
small amount of game vocabulary it needs to reproduce ``game/enemies/
spawner.py``'s per-round composition rules as a pure, UPPER-BOUND (best-case)
calculation — no pygame, no scene, no rng. It duplicates two small mappings
that otherwise exist only as Python class attributes
(``game/enemies/enemy.py``'s ``ETYPE``/``STAT_SUBTREE`` pairs) — the same
``registry_group`` precedent ``data/CLAUDE.md`` already uses for this class of
problem. ``editor/timeline_curve.py`` is a DELIBERATE second copy of this
whole module (editor/ may never import game/, ESV-3b/D7 precedent); a
cross-package drift test pins the two together.
"""
from engine import era_math
from engine import xp_curve as _xc
from game.core.xp import XP_KEY_FOR_ETYPE

# EnemyTypes block key -> Enemy.ETYPE (game/enemies/enemy.py class attrs,
# verified against the live class roster). A second, un-refactored home for
# the same mapping — same drift shape as REGISTRY_GROUP/registry_group.
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

# Boss.round_counts[] row key -> the EnemyTypes block it substitutes counts
# for (game/enemies/spawner.py::_boss_round). "commander" is wired but ships
# 0 in every committed row.
_BOSS_TABLE_KEY_TO_BLOCK = {
    "regular": "Standard",
    "raiders": "Raider",
    "siege": "SiegeCannon",
    "commander": "Commander",
}

# Non-boss types spawner._boss_round falls back to past Boss.round_counts'
# table (the ordinary per-type formula) — the same four keys as the table.
_BOSS_FALLBACK_BLOCKS = ("Standard", "Raider", "SiegeCannon", "Commander")

_BOSS_KEY = "__boss__"


def _type_configs(enemies_balance):
    """Every non-Boss EnemyTypes block as an engine.xp_curve type_cfg."""
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
    """{EnemyTypes block key: flat per-kill XP}, plus the boss pseudo-key."""
    xp = core_balance["XP"]
    per_block = {
        block: xp[XP_KEY_FOR_ETYPE.get(etype, "xp_per_standard_enemy")]
        for block, etype in _ETYPE_FOR_BLOCK.items()
    }
    per_block[_BOSS_KEY] = xp["xp_per_boss"]
    return per_block


def _counts_for_round(round_num, enemies_balance, type_configs):
    """Mirrors ``spawner.py::_compose``'s per-round composition exactly:
    round 0 is the tutorial's forced Standard-only count; a boss round
    composes from ``Boss.round_counts`` (falling back to the ordinary
    per-type formula past the table) plus exactly one boss, with Formation/
    Sniper/Digger/Drummer never appearing; every other round sums every
    non-boss type's own formula."""
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
    """The CUMULATIVE xp requirement to reach each of the first ``n_levels``
    village-level level-ups, reproducing ``game/core/xp.py``'s
    ``advance_village_level`` threshold walk read-only (never mutates a
    RunState). Ships the documented 50/65/85/110/140... per-level curve as
    running sums: ``[50, 115, 200, 310, 450, ...]``."""
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
    """The best-case (upper-bound) XP curve and its level crossings.

    Returns ``(cumulative_xp_by_round, level_to_round)``:
    ``cumulative_xp_by_round`` is ``{round: cumulative_xp}`` for every round
    in ``[round_min, round_max]``; ``level_to_round`` is ``{village_level:
    earliest_round_or_None}`` for the first ``max_levels`` village levels —
    the round at which THAT level's level-up would fire assuming every
    enemy spawned so far was killed. Never assert this equals a real
    playthrough (see the module's own upper-bound caveat).
    """
    type_configs = _type_configs(enemies_balance)
    xp_per_block = _xp_per_block(core_balance)

    def counts_for_round(round_num):
        return _counts_for_round(round_num, enemies_balance, type_configs)

    cumulative = _xc.cumulative_best_case_xp(
        round_min, round_max, xp_per_block, counts_for_round)
    thresholds = threshold_sequence(core_balance, max_levels)
    level_to_round = _xc.threshold_crossing_rounds(cumulative, thresholds)
    return cumulative, level_to_round
