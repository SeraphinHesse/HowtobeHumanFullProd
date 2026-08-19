"""Level-up option roll + research gates (Phase 10A; TimelinePLAN T4).

Pure logic (no pygame). Ports the prototype's ``_roll_levelup_options`` /
``_apply_levelup_option`` / ``_tier_option`` / ``tiers_unlocked_for`` /
``_tier_offerable`` (``src/core/game.py:1444-1790``) and the five-mode upgrade
classifier from ``src/ui/building_ui.py:1327-1355``.

TWO gates stack:

1. **type unlock** — is the building type earned at all
   (``RunState.unlocked_buildings``, seeded from ``RESEARCH``)? A locked
   type's UNLOCK card is itself gated by whether it has a Timeline placement
   at ``tier_index=0`` (via ``tier_offerable(state, btype, 0, ...)``) — its
   placement doubles as the type's era gate, so there is no separate
   group-level key.
2. **per-tier eligibility gate** — is ``(btype, tier_index)`` placed on the
   Timeline (``data/balancing/progression.json``, TimelinePLAN)? A tier
   can't be researched, previewed or named until the player's
   ``village_level`` reaches its placed ``village_level`` —
   ``timeline_level_for`` is the ONE place this is resolved, and it is the
   SOLE source of unlock timing. **Row N is what the level-up REACHING level
   N offers** — the roll runs before ``advance_village_level``, so it gates on
   ``state.village_level + 1``, the same lookup ``scripted_level_due`` and
   ``exact_levelup_options`` use; row 1 is the starting loadout and never
   funds a level-up. (``upgrade_gate``'s panel readout still measures against
   the level the player HOLDS.) (``unlock_min_round`` no longer exists —
   deleted from ``buildings.json`` schema+content in this same change,
   TimelinePLAN D4/D6). A tier never placed on the Timeline is never
   offerable at all.

Only the SINGLE next locked tier of a type is ever offerable
(``idx == tiers_unlocked``), so Pistoleer stays hidden until Slinger is bought.
Tier research is GLOBAL per type: every building of that type shares the count —
and for a ``tier_group``'d family (the boost trio) one card researches the tier
for every member at once, the exact mirror of their shared unlock card.
**Researching a tier is FREE for every type**; the tier's ``build_cost`` rides
along as ``display_cost`` (preview only), and is still what a fresh placement or
the upgrade panel's advance button actually charges.
Unlocking a type makes its tier 1 immediately placeable (no more "starts at
tier 0" case — see ``game/buildings/research.py``).
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


def _timeline_row(progression_balance, village_level):
    """The Timeline's authored row for ``village_level``, or ``None`` when it
    has none (including when ``progression_balance`` is ``None`` itself — the
    same bare-``Session`` tolerance ``timeline_level_for`` carries)."""
    if progression_balance is None:
        return None
    for level in progression_balance["Timeline"]["levels"]:
        if level["village_level"] == village_level:
            return level
    return None


def scripted_level_due(village_level, round_num, progression_balance):
    """Designer-scripted leveling: does the NEXT village level fall due at the
    end of ``round_num``? True iff the Timeline holds a row for
    ``village_level + 1`` whose authored ``round`` is ``round_num``.

    A level the designer left off the Timeline simply never fires — the same
    warn-don't-block stance the editor's round validation takes; past the last
    authored level the player stops levelling, and there is no XP fallback."""
    row = _timeline_row(progression_balance, village_level + 1)
    return row is not None and row["round"] == round_num


def timeline_level_for(btype, idx, progression_balance):
    """The ``village_level`` at which ``(btype, idx)`` first becomes
    offerable, per the Timeline's authored schedule — the SOLE source of
    unlock timing (TimelinePLAN D4/D6). ``None`` when never placed on the
    Timeline (never offerable), including when ``progression_balance`` is
    ``None`` itself (a bare ``Session`` a logic test builds that never wired
    one up — the ``tutorial_gate``/``debug`` "host-set, safe when absent"
    pattern)."""
    if progression_balance is None:
        return None
    for level in progression_balance["Timeline"]["levels"]:
        for slot in level["offer_slots"]:
            assignment = slot["assignment"]
            if (assignment is not None
                    and assignment["building_type"] == btype
                    and assignment["tier_index"] == idx):
                return level["village_level"]
    return None


def tier_lead(btype):
    """The type whose Timeline placements govern ``btype``'s tiers. A
    ``tier_group``'d family (the boost trio) researches every tier from ONE
    card, so only the LEAD's placement is ever consulted — the other members'
    rows are inert, exactly as their tier-0 rows already are for the shared
    unlock card (TimelinePLAN D8). Every ungrouped type leads itself."""
    spec = RESEARCH.get(btype)
    if spec is not None and spec.tier_group:
        return spec.tier_group[0]
    return btype


def tier_offerable(state, btype, idx, progression_balance, village_level=None):
    """Is ``(btype, idx)`` past its Timeline gate?

    ``village_level`` overrides which level the gate is measured against.
    Default (``None``) = the level the player HOLDS, which is what the upgrade
    panel's ``upgrade_gate`` wants. The level-up ROLL passes the level being
    REACHED (``state.village_level + 1``) instead: a level-up window opens
    BEFORE ``advance_village_level`` runs, so measuring against the held level
    would offer the previous row's cards on this row's round — the same
    ``village_level + 1`` lookup ``scripted_level_due`` and
    ``exact_levelup_options`` already use."""
    level = timeline_level_for(tier_lead(btype), idx, progression_balance)
    have = state.village_level if village_level is None else village_level
    return level is not None and have >= level


# -- run-state gates --------------------------------------------------------
# `tiers_unlocked_for` / `type_unlocked` / `buildable` are re-exported from
# game.buildings.research (they gate placement too, and game/buildings must not
# import game/core).


def _gate_met(state, spec, buildings_balance, village_level=None):
    """The per-type unlock-reward gate (village level / none). The round axis
    is no longer a spec-level gate_kind — it is the type's own
    ``tiers[0].unlock_min_round``, checked separately via ``tier_offerable``
    in ``roll_levelup_options``."""
    if spec.gate_kind is None:
        return True
    value = reduce(lambda d, k: d[k], spec.gate_path, buildings_balance)
    if spec.gate_kind == "min_village_level":
        have = state.village_level if village_level is None else village_level
        return have >= value
    raise ValueError(f"unknown gate_kind {spec.gate_kind!r}")


# -- option builders (prototype dict shape) ---------------------------------

def _group_tier_copy(spec, idx, buildings_balance):
    """``(title, prev_name, explanation)`` for a ``tier_group``'d family's ONE
    shared research card, read live off ``spec.tier_copy_path`` (a designer
    edits it in the editor's balancing panel). ``None`` when this member is not
    the copy-owning lead, so the caller falls back to the tier's own name."""
    if not spec.tier_copy_path:
        return None
    node = reduce(lambda d, k: d[k], spec.tier_copy_path, buildings_balance)
    titles = node["tier_card_titles"]
    return (titles[idx],
            titles[idx - 1] if idx > 0 else None,
            node["tier_card_explanations"][idx])


def _tier_option(btype, idx, buildings_balance, spec=None):
    tiers = tiers_for(btype, buildings_balance)
    tier = tiers[idx]
    leaf = LEAF_CLASSES[btype]
    # Structure buildings (10E) use a single flat art slot per type (no
    # tier/level suffix, matching data/slots.json); everything else keys the card
    # art on TIER_SPRITES[idx] with the tier/level suffix.
    flat_slot = getattr(leaf, "SLOT", "")
    sprite_key = flat_slot or f"{leaf.TIER_SPRITES[idx]}_t{idx + 1}_lvl1"
    spec = spec if spec is not None else RESEARCH.get(btype)
    types = tuple(spec.tier_group) if spec is not None and spec.tier_group else (btype,)
    # A grouped card researches this tier for the WHOLE family, so no single
    # line's tier name can title it -- the copy is data (see _group_tier_copy).
    copy = _group_tier_copy(spec, idx, buildings_balance) if spec is not None else None
    title, prev_name, explanation = copy or (
        tier["name"],
        tiers[idx - 1]["name"] if idx > 0 else None,
        tier.get("explanation", ""),
    )
    return {
        "kind": "tier",
        "building_type": btype,
        "building_types": types,
        "tier_index": idx,
        "tier_no": idx + 1,
        "tier_max": len(tiers),
        "title": title,
        "prev_name": prev_name,
        "explanation": explanation,
        # Researching a tier is FREE (user decision) -- the card only lifts the
        # gate. build_cost is still the ONE price to actually GET this tier on a
        # building (a fresh placement, or the upgrade panel's advance button), so
        # it rides along as display_cost, the unlock card's preview-only shape.
        "cost": 0,
        "display_cost": tier.get("build_cost", 0),
        "cost_label": "Upgrade Cost",
        "sprite_key": sprite_key,
    }


def _unlock_option(btype, spec, buildings_balance):
    """A one-time reward that earns a whole building type. The unlock itself is
    FREE; ``display_cost`` previews the tier-1 build price (prototype)."""
    tiers = tiers_for(btype, buildings_balance)
    types = spec.unlock_group or (btype,)
    leaf = LEAF_CLASSES[btype]
    # Same flat-vs-tiered art convention as _tier_option (structure buildings
    # key one slot for the whole type, no tier/level suffix).
    flat_slot = getattr(leaf, "SLOT", "")
    sprite_key = flat_slot or f"{leaf.TIER_SPRITES[0]}_t1_lvl1"
    return {
        "kind": "unlock_building",
        "building_type": btype,
        "building_types": tuple(types),
        # Default copy names the TIER 1 building the card actually grants
        # ("Mortar"), so the card and the thing you then place agree. The
        # WORDING around that name is designer-owned — the UI runs this
        # through ``levelup.unlock_title`` (data/ui/strings.json, "{name}" by
        # default), which is why no verb is baked in here.
        # ``unlock_title`` overrides only where no single tier-1 name fits (the
        # boost trio's one card grants three lines).
        "title": spec.unlock_title or tiers[0]["name"],
        "prev_name": None,
        "explanation": spec.unlock_explanation or tiers[0].get("explanation", ""),
        "cost": 0,
        "display_cost": tiers[0].get("build_cost", 0),
        "cost_label": "Build Cost",
        "sprite_key": sprite_key,
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

def _reward_claimed(state, kind, btype, idx):
    """Has the player already been granted what this authored card offers?
    An unlock card is spent once the TYPE is unlocked; a tier card once that
    tier is researched (``apply_levelup_option`` stores ``tier_no == idx + 1``,
    so researched means ``tiers_unlocked_for(...) > idx``)."""
    if kind == "unlock":
        return type_unlocked(state, btype)
    return tiers_unlocked_for(state, btype) > idx


def exact_levelup_options(state, buildings_balance, core_balance,
                          progression_balance):
    """``Timeline.exact_offer_slots``: the level being reached shows EXACTLY
    the cards its row authors, in row order — no shuffle, no eligibility pool.

    A null slot pays the repeatable love fallback; a card whose reward is
    already claimed is DROPPED (not padded over, so the row shrinks); a row
    that ends up empty shows ONE love card. A village_level with no row at all
    falls back to today's ``OPTION_COUNT`` love cards, exactly like an
    under-populated level in the random path.

    Duplicate placements are legal in this mode (the editor stops enforcing
    ``(building_type, tier_index)`` uniqueness), so nothing here de-duplicates:
    what the designer authored is what the player sees."""
    row = _timeline_row(progression_balance, state.village_level + 1)
    if row is None:
        return [_love_fallback(core_balance) for _ in range(OPTION_COUNT)]
    options = []
    for slot in row["offer_slots"]:
        assignment = slot["assignment"]
        if assignment is None:
            options.append(_love_fallback(core_balance))
            continue
        btype = assignment["building_type"]
        idx = assignment["tier_index"]
        spec = RESEARCH.get(btype)
        # A card naming a type this build has no leaf/research row for is
        # skipped rather than crashed on, the same guard the random roll's
        # own loop opens with.
        if btype not in LEAF_CLASSES or spec is None:
            continue
        if _reward_claimed(state, assignment["kind"], btype, idx):
            continue
        if assignment["kind"] == "unlock":
            options.append(_unlock_option(btype, spec, buildings_balance))
        else:
            options.append(_tier_option(btype, idx, buildings_balance, spec))
    return options or [_love_fallback(core_balance)]


def roll_levelup_options(state, buildings_balance, core_balance, rng,
                          progression_balance):
    """Three option dicts: a unique shuffled draw from the eligible pool, padded
    with repeatable love fallbacks (prototype ``_roll_levelup_options``).
    ``progression_balance`` (TimelinePLAN) is the sole source of WHICH
    tiers/unlocks are eligible; the shuffle/take-3/fallback-pad logic below
    is otherwise byte-identical to before that change — only pool
    membership was repointed.

    ``Timeline.exact_offer_slots`` swaps the whole roll out for
    ``exact_levelup_options`` above: the row stops being an eligibility floor
    and becomes the literal card set."""
    if (progression_balance is not None
            and progression_balance["Timeline"]["exact_offer_slots"]):
        return exact_levelup_options(
            state, buildings_balance, core_balance, progression_balance)
    # The level this window is REACHING — the roll runs before
    # advance_village_level, so every gate below is measured against it, not
    # against the level being left (see tier_offerable's docstring). Row N of
    # the Timeline is what the level-up TO level N offers; row 1 is the
    # starting loadout and never funds a level-up.
    target_level = state.village_level + 1
    pool = []
    for btype, spec in RESEARCH.items():
        if btype not in LEAF_CLASSES:
            continue
        if type_unlocked(state, btype):
            # Grouped tiers (the boost trio): one card researches this tier for
            # all three, so only the LEAD offers it -- the same skip the grouped
            # unlock below does, for the same reason.
            if spec.tier_group and btype != spec.tier_group[0]:
                continue
            # Only the single next locked tier can be offered.
            idx = tiers_unlocked_for(state, btype)
            tiers = tiers_for(btype, buildings_balance)
            if idx < len(tiers) and tier_offerable(state, btype, idx,
                                                   progression_balance,
                                                   target_level):
                pool.append(_tier_option(btype, idx, buildings_balance, spec))
        elif (_gate_met(state, spec, buildings_balance, target_level)
              and tier_offerable(state, btype, 0, progression_balance,
                                 target_level)):
            # Grouped unlock (the boost trio): all members are seeded locked so
            # each offers its own tier cards after unlocking, but only the LEAD
            # type offers the shared "unlock all three" card — skip the rest so
            # the trio surfaces as ONE card, not three identical ones.
            if spec.unlock_group and btype != spec.unlock_group[0]:
                continue
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
        # A grouped card carries every member of its family (the boost trio);
        # an ordinary one carries just its own type.
        for btype in option.get("building_types", (option["building_type"],)):
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

def _next_tier_gate(state, building, buildings_balance, progression_balance,
                    boss_upgrades_balance=None):
    """The next-tier half of the classifier below, independent of whether the
    building is currently AT its tier max — ``(mode, next_name, cost)`` using
    the same four post-tier-max modes ``upgrade_gate`` returns. Shared by
    ``upgrade_gate`` (which only consults this once ``at_tier_max()``) and
    ``advance_batch_plan`` (which needs it regardless of current level, since
    the current TIER — not the level within it — is what decides whether a
    next tier exists/is researched/is offerable).

    ``tier_hidden``'s ``cost`` carries the village_level the next tier
    unlocks at (TimelinePLAN D5 — always exactly true, unlike showing the
    best-case-curve's approximate round would be), or ``None`` if it has no
    Timeline placement at all."""
    if not building.has_next_tier():
        return ("max_tier", None, 0)
    btype = building.building_type
    next_idx = building.get_component(TierState).current_tier + 1
    if not tier_offerable(state, btype, next_idx, progression_balance):
        return ("tier_hidden", None,
                timeline_level_for(tier_lead(btype), next_idx,
                                   progression_balance))
    tier = tiers_for(btype, buildings_balance)[next_idx]
    cost = _wall_discounted(tier.get("build_cost", 0), state, building,
                            boss_upgrades_balance)
    if tiers_unlocked_for(state, btype) > next_idx:
        return ("tier_upgrade", tier["name"], cost)
    return ("tier_locked", tier["name"], cost)


def _wall_discounted(cost, state, building, boss_upgrades_balance):
    """``cost`` after BU-3's ``wall_cost_discount`` (#2), structure-scoped.

    The tier-advance and batch-catch-up prices in this module read the tier
    table DIRECTLY rather than through ``Building.build_cost()``/
    ``upgrade_cost()``, so they need the same reducer applied explicitly or a
    Blocker/WallBuilder would be discounted at some price points and not
    others. Tag-gated on ``"structure"``, exactly like
    ``Building._wall_discount``. Inert without BU-3's optional trailing
    ``boss_upgrades_balance`` (``game/core/boss_upgrades.py``'s
    threading-pattern section — the RunState half is already this module's
    first argument)."""
    if boss_upgrades_balance is None or "structure" not in building.tags:
        return cost
    from . import boss_upgrades
    return boss_upgrades.discounted(
        cost, state, boss_upgrades_balance, "wall_cost_discount",
        "cost_reduction_pct", 50, floor=1)


def upgrade_gate(state, building, buildings_balance, progression_balance,
                 boss_upgrades_balance=None):
    """Classify a building's upgrade button -> ``(mode, next_name, cost)``:

    ``in_tier``      normal level-up inside the current tier
    ``tier_upgrade`` at tier max, next tier researched -> advance
    ``tier_locked``  at tier max, next tier offerable but not researched
    ``tier_hidden``  at tier max, next tier not yet offerable — see
                     ``_next_tier_gate``'s docstring for what ``cost`` means
    ``max_tier``     at tier max, no higher tier exists

    ``boss_upgrades_balance`` is BU-3's optional trailing half-pair (the
    RunState is already the first argument): present, a Blocker/WallBuilder's
    quoted price carries the ``wall_cost_discount`` reduction. This is the ONE
    seam the panel reads BOTH the label price and the charged price through
    (``_upgrade_state`` -> ``_batch_upgrade_targets``), so the two can never
    disagree about the discount.
    """
    if not building.at_tier_max():
        return ("in_tier", None,
                building.upgrade_cost(state, boss_upgrades_balance))
    return _next_tier_gate(state, building, buildings_balance,
                           progression_balance, boss_upgrades_balance)


def advance_batch_plan(state, building, buildings_balance, progression_balance,
                       boss_upgrades_balance=None):
    """``(eligible, total_cost, levels_needed)`` for the multi-select batch
    ADVANCE action (``game/ui/building_ui.py``'s ``_batch_advance_targets``).

    ``eligible`` is False when the building can never reach its next tier
    right now no matter how much love is spent — already at the final tier
    (``max_tier``), the next tier not yet researched (``tier_locked``), or
    not yet offerable per the Timeline (``tier_hidden``); those buildings are
    left for the player to handle separately (a plain in-tier UPGRADE, or
    once research/the Timeline catches up). When eligible (``tier_upgrade``,
    whether or not the building is at its tier max RIGHT NOW), ``total_cost``
    sums every remaining in-tier level-up needed to reach this tier's max
    level (projected via ``upgrade_cost()``'s own formula, without mutating
    the building) plus the next tier's advance cost; ``levels_needed`` is how
    many ``upgrade()`` calls that catch-up takes (0 if already at tier max).

    ``boss_upgrades_balance`` (BU-3's optional trailing half-pair) discounts
    both halves of the total for a Blocker/WallBuilder — the projected
    catch-up levels through the same reducer ``upgrade_cost()`` applies, and
    the tier cost through ``_next_tier_gate`` — so the batch total matches
    what the per-building path would charge one at a time."""
    mode, _next_name, tier_cost = _next_tier_gate(
        state, building, buildings_balance, progression_balance,
        boss_upgrades_balance)
    if mode != "tier_upgrade":
        return False, 0, 0
    tier_data = building.tier_data()
    max_levels = tier_data["levels"]
    base = tier_data["upgrade_cost_base"]
    increment = tier_data["upgrade_cost_increment"]
    lvl = building.get_component(TierState).current_level_in_tier
    catchup_cost = 0
    levels_needed = 0
    while lvl < max_levels:
        catchup_cost += _wall_discounted(base + (lvl - 1) * increment, state,
                                         building, boss_upgrades_balance)
        lvl += 1
        levels_needed += 1
    return True, catchup_cost + tier_cost, levels_needed
