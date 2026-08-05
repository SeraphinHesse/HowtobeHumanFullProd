"""Pure era-clock / per-era stat + count math (EnemyScalingReworkPLAN D1-D5, D11).

Stdlib only — no pygame, no Qt, no game/editor imports. This is the ONE place
the era formulas live so the game runtime and the editor's read-only preview
cannot drift apart (D7); `editor/` and `game/` may not import each other, but
both consume `engine/`.

The module is deliberately vocabulary-free: it knows about "eras", "rows",
"stats" and "counts", never about a raider or a flute player. Callers pass the
already-loaded balancing dicts; nothing here opens a file or names a JSON path.

Contracts worth knowing before you call anything:

- **Round 0 is era 0** (D11). Naive floor division gives ``(0 - 1) // 10 == -1``
  which would index an era array from the end; `era_of_round` clamps at 0 and
  `is_boss_round(0, ...)` is False for every configuration.
- **Counts are computed, never accumulated** (D3'):
  ``floor(round(count_start + k * count_per_round, 9))`` with ``k`` an int.
  Repeated addition drifts off exactly the integers that matter, and
  `count_start` is a NUMBER (fractional accretion anchors are legitimate data).
- **Nothing here mutates its input.** Resolvers return fresh dicts whenever they
  compute anything; the plain in-range clamp returns the caller's own row.
"""

import math

__all__ = [
    "era_of_round",
    "round_in_era",
    "is_boss_round",
    "resolve_era_row",
    "stats_at_round",
    "count_at_round",
    "prev_era_reference",
]

# Row-leaf key -> the name of its endgame factor (D5). Any key not listed uses
# its own name; a key with no matching factor is left unscaled (that is how
# attack_speed / attack_range_tiles survive the virtual-row synthesis).
_FACTOR_FOR_KEY = {
    "count_start": "count",
    "count_per_round": "count",
}


def era_of_round(round_num, rounds_per_era):
    """0-based era index of `round_num` (D1). Round <= 0 is era 0 (D11)."""
    rounds_per_era = max(1, int(rounds_per_era))
    if round_num < 1:
        return 0
    return (int(round_num) - 1) // rounds_per_era


def round_in_era(round_num, rounds_per_era):
    """1-based position of `round_num` inside its era (D1). Round <= 0 is 1."""
    rounds_per_era = max(1, int(rounds_per_era))
    if round_num < 1:
        return 1
    return (int(round_num) - 1) % rounds_per_era + 1


def is_boss_round(round_num, rounds_per_era, boss_round_in_era):
    """True iff `round_num` is its era's boss round (D1).

    Always False for round <= 0 — the tutorial round is never a boss round, for
    every configuration (D11), so no caller has to remember the guard.
    """
    if round_num < 1:
        return False
    return round_in_era(round_num, rounds_per_era) == int(boss_round_in_era)


def _scale_leaf(value, factor, power):
    """Scale one numeric leaf by ``factor ** power``.

    Leaves that were ints in the authored row stay ints (floored) — that is D5's
    "counts floored to int", and it is what makes all-1.0 factors bit-equal to a
    plain clamp: an int leaf floors back to itself, a float leaf is untouched.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    scaled = value * (factor ** power)
    if isinstance(value, int):
        return int(math.floor(round(scaled, 9)))
    return scaled


def _scale_node(node, factors, power):
    """Recursively copy `node`, scaling every numeric leaf by its own factor."""
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                out[key] = _scale_node(value, factors, power)
            else:
                name = _FACTOR_FOR_KEY.get(key, key)
                out[key] = _scale_leaf(value, float(factors.get(name, 1.0)), power)
        return out
    if isinstance(node, list):
        return [_scale_node(item, factors, power) for item in node]
    return node


def resolve_era_row(eras, era, endgame_factors=None):
    """The era row for `era`, clamped to the last authored row (D5).

    In range: the caller's own row (never copied, never mutated).
    Past the end: a NEW dict whose numeric leaves are
    ``last_row_value * factor ** N`` with ``N = era - (len(eras) - 1)``.
    `endgame_factors` maps a factor name (``hp``/``dmg``/``move_speed``/
    ``count``/``batch_size``/``spawn_interval``/...) to a multiplier; a missing
    name means 1.0, and all-1.0 factors are exactly a plain clamp.
    """
    if not eras:
        raise ValueError("resolve_era_row: eras must hold at least one row")
    last = len(eras) - 1
    era = int(era)
    if era <= last:
        return eras[max(0, era)]
    power = era - last
    return _scale_node(eras[last], dict(endgame_factors or {}), power)


def stats_at_round(row, position_in_era):
    """The row's stats grown to `position_in_era` (1-based) inside its era (D2).

    ``stats + (position_in_era - 1) * per_round`` for every key `per_round`
    carries; every other stat is flat within the era. Returns a new dict.
    """
    stats = dict(row.get("stats") or {})
    steps = max(0, int(position_in_era) - 1)
    if not steps:
        return stats
    for key, delta in (row.get("per_round") or {}).items():
        if key in stats:
            stats[key] = stats[key] + steps * delta
    return stats


def count_at_round(row, round_num, era_first_round, start_round=1):
    """How many of this type spawn on `round_num` (D3, D3').

    ``floor(round(count_start + k * count_per_round, 9))`` where ``k`` is the
    integer number of rounds since ``r0 = max(era_first_round, start_round)``.
    Returns 0 before `start_round` (and before `r0`). Never accumulates.
    """
    round_num = int(round_num)
    if round_num < int(start_round):
        return 0
    r0 = max(int(era_first_round), int(start_round))
    steps = round_num - r0
    if steps < 0:
        return 0
    raw = row.get("count_start", 0) + steps * row.get("count_per_round", 0)
    return max(0, int(math.floor(round(raw, 9))))


def prev_era_reference(
    rows, era, rounds_per_era, start_round=1, endgame_factors=None
):
    """What this row's fields resolved to on the LAST round of era - 1 (D9).

    Read-only editor sugar: a dict shaped like an era row, where `stats` are the
    previous era's stats at its final round, `count_start` is the previous era's
    final count, and every flat field is simply the previous era's value.
    Returns None for era 0 (nothing to reference).
    """
    era = int(era)
    if era <= 0 or not rows:
        return None
    rounds_per_era = max(1, int(rounds_per_era))
    prev = resolve_era_row(rows, era - 1, endgame_factors)
    ref = _scale_node(prev, {}, 1)  # deep copy; all-1.0 factors are identity
    if "stats" in ref:
        ref["stats"] = stats_at_round(prev, rounds_per_era)
    if "count_start" in ref:
        prev_first = (era - 1) * rounds_per_era + 1
        ref["count_start"] = count_at_round(
            prev, era * rounds_per_era, prev_first, start_round
        )
    return ref
