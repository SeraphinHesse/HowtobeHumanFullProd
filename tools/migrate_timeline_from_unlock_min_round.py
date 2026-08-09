"""One-time (but kept, re-runnable) migration: bucket every building tier's
current ``unlock_min_round`` gate into a Timeline village_level placement
(TimelinePLAN T6).

Reviewable, not automatic: prints a diff table (``old unlock_min_round ->
computed village_level -> curve round``) for a human to sanity-check BEFORE
T4 deletes ``unlock_min_round`` from schema + content. The bucketing is a
best-effort heuristic translating two different axes (round vs. village
level) — a designer should eyeball outliers (e.g. two things far apart on
the old round axis landing on the same village_level).

Algorithm:
1. For every ``(building_type, tier_index)`` in ``data/balancing/
   buildings.json``, read its current ``tiers[tier_index].unlock_min_round``
   (tier 0 doubles as the type's own unlock-card gate — the existing rule).
2. Run ``game/core/xp_curve.best_case_curve`` over the CURRENT, unmigrated
   balancing data to get ``round -> cumulative_xp`` and
   ``village_level -> round``.
3. Bucket each ``(building_type, tier_index, unlock_min_round=R)`` into the
   SMALLEST village_level whose computed round is ``>= R``.
4. Write the result through ``editor.timeline_ops.save_progression``
   (schema-validated, deterministic, uniqueness-checked).

Usage:
    py tools/migrate_timeline_from_unlock_min_round.py [--data-dir PATH] [--dry-run]

``--dry-run`` prints the diff table without writing ``progression.json``.
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from editor import timeline_ops
from game.core import balance, xp_curve

# Generous headroom over the highest unlock_min_round in shipped data
# (measured: 40) and the repo's rounds/levels bounds policy (0-1000) —
# large enough that every real tier's bucket round is found well inside
# the computed range, never None.
_ROUND_MAX = 300
_MAX_LEVELS = 60


def _tiers_with_gates(buildings_balance):
    """Yield (building_type, tier_index, unlock_min_round, group_label) for
    every tier of every building-type group — the same generic
    family/group walk ``timeline_ops.load_building_catalog`` uses, so a
    future new building type needs no change here either."""
    for _family, groups in buildings_balance.items():
        if not isinstance(groups, dict):
            continue
        for group_label, group in groups.items():
            if not isinstance(group, dict) or "building_type" not in group:
                continue
            for tier_index, tier in enumerate(group.get("tiers", [])):
                yield (group["building_type"], tier_index,
                       tier["unlock_min_round"], group_label, tier.get("name", ""))


def _bucket_village_level(round_gate, level_to_round):
    """The smallest village_level whose computed best-case round is
    ``>= round_gate``. Levels are walked in ascending order (dict insertion
    order from ``threshold_crossing_rounds`` is already 1..max_levels)."""
    for level in sorted(level_to_round):
        round_num = level_to_round[level]
        if round_num is not None and round_num >= round_gate:
            return level
    return None


def compute_migration(buildings_balance, core_balance, enemies_balance,
                       round_max=_ROUND_MAX, max_levels=_MAX_LEVELS):
    """Pure: returns ``(progression_doc, diff_rows)``.

    ``diff_rows`` is a list of ``(building_type, tier_index, group_label,
    tier_name, old_unlock_min_round, village_level, curve_round)`` tuples,
    in the same order ``_tiers_with_gates`` yields them — the human-review
    table."""
    _cumulative, level_to_round = xp_curve.best_case_curve(
        core_balance, enemies_balance, 0, round_max, max_levels=max_levels)

    doc = {"Timeline": {"levels": []}}
    diff_rows = []
    for building_type, tier_index, round_gate, group_label, tier_name in \
            _tiers_with_gates(buildings_balance):
        village_level = _bucket_village_level(round_gate, level_to_round)
        if village_level is None:
            raise ValueError(
                f"{building_type} tier {tier_index} (unlock_min_round="
                f"{round_gate}) never buckets within round_max={round_max}/"
                f"max_levels={max_levels} — widen the range")
        kind = "unlock" if tier_index == 0 else "tier"
        timeline_ops.assign_slot(
            doc, village_level, _next_free_slot(doc, village_level),
            kind, building_type, tier_index)
        diff_rows.append((
            building_type, tier_index, group_label, tier_name, round_gate,
            village_level, level_to_round.get(village_level)))
    return doc, diff_rows


def _next_free_slot(doc, village_level):
    """The first slot index in this level not yet assigned (or the next
    trailing index) — used only while building fresh migration output, so
    slots pack from 0 with no gaps."""
    for level in doc["Timeline"]["levels"]:
        if level["village_level"] == village_level:
            return len(level["offer_slots"])
    return 0


def print_diff_table(diff_rows):
    print(f"{'building_type':<16} {'tier':<5} {'group':<16} {'name':<20} "
          f"{'old_round':>10} {'village_level':>14} {'curve_round':>12}")
    for (building_type, tier_index, group_label, tier_name, round_gate,
         village_level, curve_round) in sorted(
            diff_rows, key=lambda r: (r[5], r[0], r[1])):
        print(f"{building_type:<16} {tier_index:<5} {group_label:<16} "
              f"{tier_name:<20} {round_gate:>10} {village_level:>14} "
              f"{str(curve_round):>12}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=None,
                         help="defaults to the repo's own data/")
    parser.add_argument("--dry-run", action="store_true",
                         help="print the diff table without writing")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir) if args.data_dir else REPO / "data"
    buildings_balance = balance.load_balance(data_dir, "buildings")
    core_balance = balance.load_balance(data_dir, "core")
    enemies_balance = balance.load_balance(data_dir, "enemies")

    doc, diff_rows = compute_migration(
        buildings_balance, core_balance, enemies_balance)
    print_diff_table(diff_rows)
    print()
    print(f"{len(diff_rows)} tier/unlock cards bucketed into "
          f"{len(doc['Timeline']['levels'])} village_level(s).")

    if args.dry_run:
        print("--dry-run: not written.")
        return
    timeline_ops.save_progression(doc, data_dir)
    print(f"Written: {timeline_ops.progression_path(data_dir)}")


if __name__ == "__main__":
    main()
