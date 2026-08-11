"""Pure best-case XP-curve math (TimelinePLAN T3/D7).

Vocabulary-free, stdlib-only: it knows "type configs", "eras" and "counts"
(via ``engine.era_math``), never a raider or a boss — callers pass
already-loaded balancing dicts and their own per-round composition rule.
Nothing here opens a file or names a balancing key.

Computes the UPPER-BOUND cumulative XP curve — assuming every enemy spawned
in a round is killed that same round, which is never quite what a real
playthrough does (real XP depends on the player's kill rate) — and the round
at which that curve first crosses each of a sequence of village-level
thresholds.
"""
from engine import era_math


def type_count_for_round(round_num, era_cfg, type_cfg):
    """How many of one enemy type spawn on ``round_num``, via the same
    closed-form formula the real Spawner uses.

    ``era_cfg``: ``{"rounds_per_era": int}``. ``type_cfg``: ``{"eras": [...],
    "endgame_scaling": dict, "start_round": int}`` — one type's own era rows,
    exactly as authored in its balancing block.
    """
    rounds_per_era = era_cfg["rounds_per_era"]
    era = era_math.era_of_round(round_num, rounds_per_era)
    row = era_math.resolve_era_row(
        type_cfg["eras"], era, type_cfg["endgame_scaling"])
    return era_math.count_at_round(
        row, round_num, era * rounds_per_era + 1, type_cfg["start_round"])


def enemy_counts_for_round(round_num, era_cfg, type_configs):
    """``{type_key: count}`` for every entry in ``type_configs``, for one
    round. ``type_configs`` maps an opaque type_key to a ``type_cfg`` (see
    ``type_count_for_round``)."""
    return {
        key: type_count_for_round(round_num, era_cfg, cfg)
        for key, cfg in type_configs.items()
    }


def cumulative_best_case_xp(round_min, round_max, xp_per_type, counts_for_round):
    """Cumulative best-case XP through each round in ``[round_min,
    round_max]``, assuming every enemy spawned that round is killed.

    ``counts_for_round(round_num) -> {type_key: count}`` is the CALLER's own
    per-round composer — this module never decides what a "boss round" or
    "round 0" means, so a caller can special-case either without this module
    learning either concept. ``xp_per_type`` maps the SAME type_keys to a
    flat per-kill XP amount (a missing key contributes 0).

    Returns ``{round_num: cumulative_xp_through_that_round}``.
    """
    out = {}
    total = 0
    for round_num in range(round_min, round_max + 1):
        counts = counts_for_round(round_num)
        total += sum(
            count * xp_per_type.get(key, 0) for key, count in counts.items())
        out[round_num] = total
    return out


def threshold_crossing_rounds(cumulative_xp_by_round, level_thresholds):
    """``{level: first_round_num}`` — for each 1-based index into
    ``level_thresholds`` (an ORDERED list of CUMULATIVE xp requirements),
    the first round (in ascending order) whose cumulative XP meets or
    exceeds it, or ``None`` if the range never reaches it.
    """
    rounds_sorted = sorted(cumulative_xp_by_round)
    out = {}
    for level, threshold in enumerate(level_thresholds, start=1):
        found = None
        for round_num in rounds_sorted:
            if cumulative_xp_by_round[round_num] >= threshold:
                found = round_num
                break
        out[level] = found
    return out
