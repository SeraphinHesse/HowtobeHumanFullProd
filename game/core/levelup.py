"""Level-up option roll + research gates (Phase 10A).

Pure logic (no pygame). Ports the prototype's ``_roll_levelup_options`` /
``_apply_levelup_option`` / ``_tier_option`` / ``tiers_unlocked_for`` /
``_tier_offerable`` / ``_era_unlock_round`` (``src/core/game.py:1444-1790``) and
the five-mode upgrade classifier from ``src/ui/building_ui.py:1327-1355``.

Three gates stack, all read live from ``data/balancing/buildings.json``:

1. **type unlock** — is the building type earned at all
   (``RunState.unlocked_buildings``, seeded from ``RESEARCH``)?
2. **era gate** — ``<group>.era_unlock_round``: a type is out of the pool
   entirely until the run reaches that round. Absent -> 0 -> never gated.
   This is the ONE canonical era key (10A lifted it off the tier dicts).
3. **per-tier round gate** — ``tiers[idx].unlock_min_round``: a tier can't be
   researched, previewed or named before that round.

Only the SINGLE next locked tier of a type is ever offerable
(``idx == tiers_unlocked``), so Pistoleer stays hidden until Slinger is bought.
Tier research is GLOBAL per type: every building of that type shares the count.
"""
from functools import reduce

from game.buildings.components import TierState
from game.buildings.research import (
    LEAF_CLASSES, RESEARCH, buildable, tiers_unlocked_for, type_unlocked,
)

# The prototype always shows exactly three cards, and the window's geometry is
# built around three. Not a balance knob.
OPTION_COUNT = 3


# -- balancing lookups ------------------------------------------------------

def _group(btype, buildings_balance):
    """The ``buildings.json`` subtree node for a building type."""
    subtree = LEAF_CLASSES[btype].SUBTREE
    return reduce(lambda d, k: d[k], subtree, buildings_balance)


def tiers_for(btype, buildings_balance):
    return _group(btype, buildings_balance)["tiers"]


def era_unlock_round(btype, buildings_balance):
    """Earliest round this TYPE may appear in the level-up pool (0 = no gate)."""
    return _group(btype, buildings_balance).get("era_unlock_round", 0)


def tier_unlock_min_round(btype, idx, buildings_balance):
    tiers = tiers_for(btype, buildings_balance)
    if 0 <= idx < len(tiers):
        return tiers[idx].get("unlock_min_round", 0)
    return 0


def tier_offerable(state, btype, idx, buildings_balance):
    return state.round_num >= tier_unlock_min_round(btype, idx, buildings_balance)


# -- run-state gates --------------------------------------------------------
# `tiers_unlocked_for` / `type_unlocked` / `buildable` are re-exported from
# game.buildings.research (they gate placement too, and game/buildings must not
# import game/core).


def _gate_met(state, spec, buildings_balance):
    """The per-type unlock-reward gate (village level / round / none)."""
    if spec.gate_kind is None:
        return True
    value = reduce(lambda d, k: d[k], spec.gate_path, buildings_balance)
    if spec.gate_kind == "min_village_level":
        return state.village_level >= value
    if spec.gate_kind == "min_round":
        return state.round_num >= value
    raise ValueError(f"unknown gate_kind {spec.gate_kind!r}")


# -- option builders (prototype dict shape) ---------------------------------

def _tier_option(btype, idx, buildings_balance):
    tiers = tiers_for(btype, buildings_balance)
    tier = tiers[idx]
    sprites = LEAF_CLASSES[btype].TIER_SPRITES
    return {
        "kind": "tier",
        "building_type": btype,
        "tier_index": idx,
        "tier_no": idx + 1,
        "tier_max": len(tiers),
        "title": tier["name"],
        "prev_name": tiers[idx - 1]["name"] if idx > 0 else None,
        "explanation": tier.get("explanation", ""),
        # tier_unlock_cost IS what building_ui charges to advance one building
        # out of the previous tier's top level.
        "cost": tier.get("tier_unlock_cost", 0),
        "cost_label": "Upgrade Cost",
        "sprite_key": f"{sprites[idx]}_t{idx + 1}_lvl1",
    }


def _unlock_option(btype, spec, buildings_balance):
    """A one-time reward that earns a whole building type. The unlock itself is
    FREE; ``display_cost`` previews the tier-1 build price (prototype)."""
    tiers = tiers_for(btype, buildings_balance)
    types = spec.unlock_group or (btype,)
    return {
        "kind": "unlock_building",
        "building_type": btype,
        "building_types": tuple(types),
        "title": spec.unlock_title or tiers[0]["name"],
        "prev_name": None,
        "explanation": spec.unlock_explanation or tiers[0].get("explanation", ""),
        "cost": 0,
        "display_cost": tiers[0].get("build_cost", 0),
        "cost_label": "Build Cost",
        "sprite_key": f"{LEAF_CLASSES[btype].TIER_SPRITES[0]}_t1_lvl1",
    }


def _love_fallback(core_balance):
    """The repeatable pad reward. The prototype's second fallback (+1 Base HP)
    is lives-mode-excluded, and the hole here is lives-only — so this is the
    only fallback, and an empty pool shows three of it."""
    amount = core_balance["XP"]["levelup_love_reward"]
    return {
        "kind": "fallback",
        "reward": "love",
        "amount": amount,
        "title": f"+{amount} Love",
        "prev_name": None,
        "explanation": "A gift of love from the village.",
        "cost": 0,
        "cost_label": "",
        "sprite_key": None,
    }


# -- the roll ---------------------------------------------------------------

def roll_levelup_options(state, buildings_balance, core_balance, rng):
    """Three option dicts: a unique shuffled draw from the eligible pool, padded
    with repeatable love fallbacks (prototype ``_roll_levelup_options``)."""
    pool = []
    for btype, spec in RESEARCH.items():
        if btype not in LEAF_CLASSES:
            continue
        era = era_unlock_round(btype, buildings_balance)
        if state.round_num < era:
            continue  # era gate hides the type entirely
        if type_unlocked(state, btype):
            # Only the single next locked tier can be offered.
            idx = tiers_unlocked_for(state, btype)
            tiers = tiers_for(btype, buildings_balance)
            if idx < len(tiers) and tier_offerable(state, btype, idx,
                                                   buildings_balance):
                pool.append(_tier_option(btype, idx, buildings_balance))
        elif _gate_met(state, spec, buildings_balance):
            pool.append(_unlock_option(btype, spec, buildings_balance))

    rng.shuffle(pool)
    options = pool[:OPTION_COUNT]
    while len(options) < OPTION_COUNT:
        options.append(_love_fallback(core_balance))
    return options


def apply_levelup_option(state, option, core_balance):
    """Grant the chosen reward. Costs are spent clamped at >= 0 (RunState)."""
    kind = option["kind"]
    if kind == "tier":
        btype = option["building_type"]
        state.tiers_unlocked[btype] = max(
            tiers_unlocked_for(state, btype), option["tier_no"])
        state.spend_love(option["cost"])
    elif kind == "unlock_building":
        for btype in option["building_types"]:
            state.unlocked_buildings[btype] = True
        state.spend_love(option["cost"])
    elif kind == "fallback":
        state.add_love(option["amount"])
    else:
        raise ValueError(f"unknown level-up option kind {kind!r}")


# -- the upgrade-panel classifier -------------------------------------------

def upgrade_gate(state, building, buildings_balance):
    """Classify a building's upgrade button -> ``(mode, next_name, cost)``:

    ``in_tier``      normal level-up inside the current tier
    ``tier_upgrade`` at tier max, next tier researched -> advance
    ``tier_locked``  at tier max, next tier offerable but not researched
    ``tier_hidden``  at tier max, next tier round-gated. Name/preview hidden;
                     ``cost`` carries the round it unlocks at.
    ``max_tier``     at tier max, no higher tier exists
    """
    if not building.at_tier_max():
        return ("in_tier", None, building.upgrade_cost())
    if not building.has_next_tier():
        return ("max_tier", None, 0)
    btype = building.building_type
    next_idx = building.get_component(TierState).current_tier + 1
    if not tier_offerable(state, btype, next_idx, buildings_balance):
        return ("tier_hidden", None,
                tier_unlock_min_round(btype, next_idx, buildings_balance))
    tier = tiers_for(btype, buildings_balance)[next_idx]
    cost = tier.get("tier_unlock_cost", 0)
    if tiers_unlocked_for(state, btype) > next_idx:
        return ("tier_upgrade", tier["name"], cost)
    return ("tier_locked", tier["name"], cost)
