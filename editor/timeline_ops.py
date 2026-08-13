"""Pure load/validate/write helpers for the Timeline panel's authored unlock
schedule (``data/balancing/progression.json`` — TimelinePLAN T5). Qt-free,
pygame-free (``TestPurity``): ``editor/panels/timeline.py`` is the only
caller, staging every drag-and-drop edit into an in-memory doc and calling
``save_progression`` only on an explicit Save.

Cross-checks JSON Schema cannot express — ``village_level`` uniqueness
across ``Timeline.levels``, and ``(building_type, tier_index)`` uniqueness
across the whole Timeline (a tier must not be assigned twice) — are
enforced here, before every write (the ``engine.tilemap.load_map``
cross-check precedent: schema for shape, Python for what it can't express).
The second of those is **skipped under ``exact_offer_slots``**, where a row is
the literal card set and repeating a card at two levels is a legitimate
authoring choice.

The per-level ``round`` schedule (``scripted_leveling``) is validated the other
way round — ``round_warnings`` returns human-readable strings and nothing ever
raises, so a designer can save a half-authored schedule and keep working
(user decision: warn, don't block).
"""
from engine import data_io

from editor import domains


def progression_path(data_dir=None):
    return domains.balancing_path("progression", data_dir)


def progression_schema_path(data_dir=None):
    return domains.schema_path("progression", data_dir)


def load_progression(data_dir=None):
    """``data/balancing/progression.json``, schema-validated. Raises on a
    missing/invalid file — the Timeline panel opens on this only after its
    selector leaf is selected, so a broken tree should be loud here (the
    same argument as ``tutorial_ops.load_tutorial``)."""
    return data_io.load_validated(
        progression_path(data_dir), progression_schema_path(data_dir))


def load_building_catalog(data_dir=None):
    """Every building type's identity + card art, read from
    ``data/balancing/buildings.json`` (TimelinePLAN T1's ``building_type``/
    ``card_slots`` fields) — the Timeline browse list's data source.

    Returns a list of ``{building_type, label, tiers: [{tier_index, name,
    slot}]}``, one entry per building-type group, in file order. Never
    hardcodes the family/group names — walks whatever groups carry a
    ``building_type`` key, so a new building type needs no editor change.
    """
    doc = data_io.load_validated(
        domains.balancing_path("buildings", data_dir),
        domains.schema_path("buildings", data_dir))
    catalog = []
    for _family, groups in doc.items():
        if not isinstance(groups, dict):
            continue
        for group_label, group in groups.items():
            if not isinstance(group, dict) or "building_type" not in group:
                continue
            tiers = group.get("tiers", [])
            card_slots = group["card_slots"]
            catalog.append({
                "building_type": group["building_type"],
                "label": group_label,
                "tiers": [
                    {
                        "tier_index": idx,
                        "name": tier.get("name", group_label),
                        "slot": card_slots[idx],
                    }
                    for idx, tier in enumerate(tiers)
                ],
            })
    return catalog


def _find_level(doc, village_level):
    for level in doc["Timeline"]["levels"]:
        if level["village_level"] == village_level:
            return level
    return None


def add_level(doc, village_level, round_num=0):
    """Insert a new, empty level record. No-op if one already exists.

    ``round_num`` seeds the scripted-leveling schedule; the panel passes that
    level's best-case round so a fresh row starts somewhere sensible, and the
    implicit creations below (``add_slot``/``assign_slot``) take the 0
    default."""
    if _find_level(doc, village_level) is not None:
        return
    doc["Timeline"]["levels"].append(
        {"village_level": village_level, "round": round_num,
         "offer_slots": []})
    doc["Timeline"]["levels"].sort(key=lambda lvl: lvl["village_level"])


def remove_level(doc, village_level):
    """Drop a level record entirely, and every slot it held. No-op if the
    level doesn't exist."""
    doc["Timeline"]["levels"] = [
        lvl for lvl in doc["Timeline"]["levels"]
        if lvl["village_level"] != village_level]


def add_slot(doc, village_level):
    """Append one empty offer slot to a level (creating the level first if
    it doesn't exist yet)."""
    add_level(doc, village_level)
    _find_level(doc, village_level)["offer_slots"].append({"assignment": None})


def remove_slot(doc, village_level, slot_index):
    """Drop the slot at ``slot_index``. No-op if the level/index doesn't
    exist."""
    level = _find_level(doc, village_level)
    if level is None:
        return
    slots = level["offer_slots"]
    if 0 <= slot_index < len(slots):
        slots.pop(slot_index)


def assign_slot(doc, village_level, slot_index, kind, building_type, tier_index):
    """Place a card into a slot, creating the level/slot first if needed
    (padding with empty slots up to ``slot_index``). Overwrites
    unconditionally — dropping a new card onto an occupied slot replaces it
    (the confirmed drag-and-drop requirement)."""
    add_level(doc, village_level)
    slots = _find_level(doc, village_level)["offer_slots"]
    while len(slots) <= slot_index:
        slots.append({"assignment": None})
    slots[slot_index]["assignment"] = {
        "kind": kind, "building_type": building_type, "tier_index": tier_index,
    }


def clear_slot(doc, village_level, slot_index):
    """Empty a slot without removing it. No-op if the level/index doesn't
    exist."""
    level = _find_level(doc, village_level)
    if level is None:
        return
    slots = level["offer_slots"]
    if 0 <= slot_index < len(slots):
        slots[slot_index]["assignment"] = None


# -- the two Timeline-wide mode flags + the per-level round schedule ---------
# Staged into the in-memory doc exactly like `assign_slot`/`add_level`; the
# panel's ONE Save is still the only write path.

def scripted_leveling(doc):
    return bool(doc["Timeline"].get("scripted_leveling", False))


def set_scripted_leveling(doc, enabled):
    doc["Timeline"]["scripted_leveling"] = bool(enabled)


def exact_offer_slots(doc):
    return bool(doc["Timeline"].get("exact_offer_slots", False))


def set_exact_offer_slots(doc, enabled):
    doc["Timeline"]["exact_offer_slots"] = bool(enabled)


def level_round(doc, village_level):
    """The authored round for a level, or ``None`` if it has no row."""
    level = _find_level(doc, village_level)
    return None if level is None else level.get("round", 0)


def set_level_round(doc, village_level, round_num):
    """Set a level's authored round. No-op if the level doesn't exist."""
    level = _find_level(doc, village_level)
    if level is not None:
        level["round"] = int(round_num)


def placements(doc):
    """``{(building_type, tier_index): village_level}`` for every non-null
    assignment — the index both ``validate_uniqueness`` and the browse
    list's "already placed" greying read."""
    out = {}
    for level in doc["Timeline"]["levels"]:
        for slot in level["offer_slots"]:
            assignment = slot["assignment"]
            if assignment is not None:
                key = (assignment["building_type"], assignment["tier_index"])
                out[key] = level["village_level"]
    return out


# Above this many slots on one row the game's level-up window overflows its
# 640px view (`game/ui/levelup.py` lays out any n, but at _BOX_W = 130 the
# boxes run off screen). The editor warns rather than the game clamping.
MAX_SLOTS_PER_LEVEL = 4


def round_warnings(doc):
    """Human-readable, NON-blocking complaints about the scripted-leveling
    schedule and row widths — duplicate rounds, a level reached no later than
    the one before it, and rows wider than the level-up window can show.
    ``save_progression`` deliberately does NOT consult this (user decision:
    warn, don't block); the panel surfaces it as a label.

    ``village_level`` 1 is skipped in the round checks — the run starts there,
    so its ``round`` is unused by the runtime and ordering against it would be
    a false alarm. Never raises, never mutates ``doc``."""
    warnings = []
    levels = sorted(doc["Timeline"]["levels"],
                    key=lambda lvl: lvl["village_level"])
    scheduled = [lvl for lvl in levels if lvl["village_level"] != 1]

    seen_rounds = {}
    for level in scheduled:
        round_num = level.get("round", 0)
        if round_num in seen_rounds:
            warnings.append(
                f"Levels {seen_rounds[round_num]} and {level['village_level']} "
                f"are both scheduled for round {round_num} — only the lower "
                f"level will be reached there.")
        else:
            seen_rounds[round_num] = level["village_level"]

    for previous, level in zip(scheduled, scheduled[1:]):
        if level.get("round", 0) <= previous.get("round", 0):
            warnings.append(
                f"Level {level['village_level']} (round "
                f"{level.get('round', 0)}) is not scheduled after level "
                f"{previous['village_level']} (round "
                f"{previous.get('round', 0)}).")

    for level in levels:
        slot_count = len(level["offer_slots"])
        if slot_count > MAX_SLOTS_PER_LEVEL:
            warnings.append(
                f"Level {level['village_level']} has {slot_count} slots — the "
                f"level-up window only fits {MAX_SLOTS_PER_LEVEL} cards.")
    return warnings


def validate_uniqueness(doc):
    """Raise ``ValueError`` when ``village_level`` repeats across levels, or
    a ``(building_type, tier_index)`` pair is placed in more than one slot
    — the two invariants JSON Schema cannot express. Called before every
    write; never mutates ``doc``.

    The placement half is SKIPPED under ``exact_offer_slots``: there a row is
    the literal card set shown at that level-up, so offering the same card at
    two different levels is deliberate authoring, not a mistake. The
    ``village_level`` half holds in both modes — two rows for one level is
    ambiguous however the rows are read."""
    seen_levels = set()
    for level in doc["Timeline"]["levels"]:
        village_level = level["village_level"]
        if village_level in seen_levels:
            raise ValueError(
                f"duplicate village_level {village_level} in Timeline.levels")
        seen_levels.add(village_level)

    if exact_offer_slots(doc):
        return

    seen_placements = {}
    for level in doc["Timeline"]["levels"]:
        for slot in level["offer_slots"]:
            assignment = slot["assignment"]
            if assignment is None:
                continue
            key = (assignment["building_type"], assignment["tier_index"])
            if key in seen_placements:
                raise ValueError(
                    f"{key} is placed at both village_level "
                    f"{seen_placements[key]} and {level['village_level']}")
            seen_placements[key] = level["village_level"]


def save_progression(doc, data_dir=None):
    """The ONE ``write_validated`` call site for ``progression.json``.
    Raises before touching disk on a schema violation OR a uniqueness
    violation (``validate_uniqueness``)."""
    validate_uniqueness(doc)
    data_io.write_validated(
        doc, progression_path(data_dir), progression_schema_path(data_dir))
