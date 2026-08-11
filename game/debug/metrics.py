"""Per-round balance metrics — PURE. No I/O, no pygame, no ``data/`` access.

Everything here is a read-only function over a ``RunState`` + a ``TileMap`` +
payday's own ``built`` list. It is the arithmetic half of the debug recorder;
``recorder.py`` owns the buffering and the file handles.

**The one rule that matters:** the "potential" (undamaged) income sweep calls
the PURE ``yield_amount()`` and NEVER ``collect_income()``. ``collect_income``
resets/advances the Meditator streak (``payday.py`` step 4) — calling it from
telemetry would move gameplay, which is the one thing this feature must never
do. See the "Actual vs potential income" section of ``events.py``'s docstring
for exactly what each half contains.

The three functions map onto the three payday hooks:

``payday_start_metrics`` -> ``on_payday_start``: everything that must be read
BEFORE payday step 2 zeroes ``RoundStats``, plus the potential ledger.
``actual_ledger``        -> folded into ``round_summary``: splits
``RunState.income_events`` after payday step 6.
``round_summary``        -> ``on_payday_end``: the finished flat row.
"""
from game.buildings.components import RoundStats
from game.core.xp import scaled_base_income

#: The round row schema. The CSV header IS this tuple (``test_debug_log`` pins
#: header == ROUND_FIELDS so they cannot drift), and every row ``round_summary``
#: returns has exactly these keys, in this order.
ROUND_FIELDS = (
    "round", "love_start", "love_end",
    "income_actual", "income_potential", "income_lost_to_damage",
    "base_income", "building_income_actual", "building_income_potential",
    "painter_income", "story_income",
    "upkeep_actual", "upkeep_potential", "upkeep_unpaid_from_deaths",
    "net_actual", "net_potential",
    "dmg_dealt", "dmg_dealt_lightning", "lightning_hits", "dmg_taken_buildings",
    "lives_lost", "lives_end",
    "enemies_spawned", "kills", "leaks", "kidnaps",
    "buildings_built", "buildings_dead_at_payday", "buildings_placed",
    "love_spent_buildings",
    "village_level", "player_xp", "wave_size", "enemy_tier", "cheated",
)

#: The mutable per-round counters the recorder accumulates between paydays and
#: hands to ``round_summary``. ``new_accum()`` returns a zeroed one.
ACCUM_FIELDS = (
    "story_income", "dmg_dealt_lightning", "lightning_hits",
    "lives_lost", "leaks", "kills", "kidnaps", "enemies_spawned",
    "buildings_placed", "love_spent_buildings",
    "wave_size", "enemy_tier", "cheated",
)


def new_accum():
    """A zeroed per-round counter dict (see ``ACCUM_FIELDS``)."""
    return dict.fromkeys(ACCUM_FIELDS, 0)


def _amount(building, method):
    """Duck-typed zero-arg stat call; absent -> 0. Mirrors ``payday._amount``."""
    fn = getattr(building, method, None)
    return fn() if fn is not None else 0


def _round_stats(building):
    get = getattr(building, "get_component", None)
    return get(RoundStats) if get is not None else None


def _btype(building):
    return getattr(building, "building_type", None) or "unknown"


def _bump(d, key, amount):
    d[key] = d.get(key, 0) + amount


# ---------------------------------------------------------------------------
def damage_totals(built):
    """Sum ``RoundStats`` across ``built`` — call BEFORE payday step 2 zeroes
    the this-round fields. Returns ``(dealt, taken, dealt_by_type,
    taken_by_type)``. Includes the base (it carries ``RoundStats`` too); a base
    BREACH applies no HP damage, so the base's ``taken`` is siege/melee chip
    damage only. Lightning is NOT here — it has no shooter and earns no credit;
    see ``note_lightning``."""
    dealt = taken = 0
    dealt_by_type, taken_by_type = {}, {}
    for _tile, b in built:
        rs = _round_stats(b)
        if rs is None:
            continue
        bt = _btype(b)
        if rs.dmg_dealt_this_round:
            dealt += rs.dmg_dealt_this_round
            _bump(dealt_by_type, bt, rs.dmg_dealt_this_round)
        if rs.dmg_taken_this_round:
            taken += rs.dmg_taken_this_round
            _bump(taken_by_type, bt, rs.dmg_taken_this_round)
    return dealt, taken, dealt_by_type, taken_by_type


def potential_ledger(state, tilemap, core_balance, built):
    """The income/upkeep the player WOULD have received had nothing died.

    Mirrors ``run_payday`` steps 4 + 5 with the ``alive`` filter removed — both
    real sweeps ``continue`` on ``not alive``, so a building destroyed during
    the wave earns nothing AND pays no upkeep. Base income comes from
    ``game.core.xp.scaled_base_income`` — the same single source payday uses, so
    the two cannot drift. The boss story love (payday slot 3) is NOT folded in
    here: since the boss-upgrade rework it is a whole-board sum with no
    per-recipient component at all, and it is measured separately as the love
    delta across step 3 (``story_income``).

    Returns ``{"base_income", "building_income_potential", "income_potential",
    "upkeep_potential", "income_potential_by_type", "upkeep_potential_by_type"}``.
    """
    base_income = scaled_base_income(state, core_balance)

    building_income = 0
    upkeep = 0
    income_by_type, upkeep_by_type = {}, {}
    for _tile, b in built:
        bt = _btype(b)
        # PURE read — never collect_income(), which advances the streak.
        amount = _amount(b, "yield_amount")
        if amount > 0:
            building_income += amount
            _bump(income_by_type, bt, amount)
        up = _amount(b, "upkeep")
        if up > 0:
            upkeep += up
            _bump(upkeep_by_type, bt, up)
    return {
        "base_income": base_income,
        "building_income_potential": building_income,
        "income_potential": base_income + building_income,
        "upkeep_potential": upkeep,
        "income_potential_by_type": income_by_type,
        "upkeep_potential_by_type": upkeep_by_type,
    }


def payday_start_metrics(state, tilemap, core_balance, built):
    """Everything that must be read BEFORE payday step 2 zeroes ``RoundStats``.

    ``built`` is payday's own ``[(tile, occupant)]`` list — a DEAD building is
    still ``tile.occupant``, it is filtered by the ``alive`` check inside the
    sweeps, not absent from this list. That is what makes the potential ledger
    the same list without the filter.
    """
    coord_types = {}
    n_built = n_dead = 0
    for tile, b in built:
        bt = _btype(b)
        coord_types[(tile.col, tile.row)] = bt
        if bt == "base":
            continue
        n_built += 1
        if not getattr(b, "alive", False):
            n_dead += 1

    dealt, taken, dealt_by_type, taken_by_type = damage_totals(built)
    start = {
        "round": state.round_num,
        "love_start": state.love,
        "lives_start": state.base_lives,
        "village_level_start": state.village_level,
        "player_xp_start": state.player_xp,
        "coord_types": coord_types,
        "buildings_built": n_built,
        "buildings_dead_at_payday": n_dead,
        "dmg_dealt": dealt,
        "dmg_taken_buildings": taken,
        "dmg_dealt_by_type": dealt_by_type,
        "dmg_taken_by_type": taken_by_type,
    }
    start.update(potential_ledger(state, tilemap, core_balance, built))
    return start


def actual_ledger(income_events, coord_types):
    """Split ``RunState.income_events`` — ``(col, row, amount, kind)`` — into
    what was actually paid and actually billed, attributed to a building type
    via the coords captured at ``payday_start_metrics`` time.

    The start-time map is required, not a convenience: a completed Painter's
    tile is FREED during payday step 6, so by the time this runs its occupant is
    gone and its lump-sum payout would be unattributable.

    ``upkeep_actual`` is what was BILLED. ``spend_love`` clamps at 0, so on a
    bankrupt round less than that was deducted; ``love_end`` is the truth.
    """
    income_actual = upkeep_actual = 0
    painter_income = base_ledger_income = 0
    income_by_type, upkeep_by_type = {}, {}
    for col, row, amount, kind in income_events:
        bt = coord_types.get((col, row), "unknown")
        if kind == "upkeep" or amount < 0:
            billed = abs(amount)
            upkeep_actual += billed
            _bump(upkeep_by_type, bt, billed)
        else:
            income_actual += amount
            _bump(income_by_type, bt, amount)
            if bt == "painter":
                painter_income += amount
            elif bt == "base":
                base_ledger_income += amount
    return {
        "income_actual": income_actual,
        "upkeep_actual": upkeep_actual,
        "painter_income": painter_income,
        "base_ledger_income": base_ledger_income,
        "income_actual_by_type": income_by_type,
        "upkeep_actual_by_type": upkeep_by_type,
    }


def round_summary(start, state, accum):
    """The finished flat round row — exactly ``ROUND_FIELDS``, in order.

    ``start`` is the ``payday_start_metrics`` dict for this round; ``state`` is
    the ``RunState`` as of payday step 6 (after painters, BEFORE step 11's
    ``round_num += 1``); ``accum`` is the per-round counter dict (``new_accum``).
    """
    actual = actual_ledger(state.income_events, start["coord_types"])

    income_actual = actual["income_actual"]
    upkeep_actual = actual["upkeep_actual"]
    upkeep_potential = start["upkeep_potential"]
    # A completed Painter's lump sum is a PASS-THROUGH term: it is paid from
    # progress banked over many rounds, not from this round's yield sweep, and
    # `potential_ledger` (a pure pre-payday read) cannot know a painter was about
    # to complete. Adding the realised payout to BOTH sides keeps
    # `income_lost_to_damage` a clean measure of yield lost to dead buildings —
    # without it, a painter round drowns a real loss and the max(0, ...) below
    # silently clamps it to zero (which is what a designer would misread as "no
    # buildings lost"). Symmetric by construction: the same integer on each side.
    income_potential = start["income_potential"] + actual["painter_income"]
    building_income_actual = (income_actual
                              - actual["base_ledger_income"]
                              - actual["painter_income"])

    row = {
        "round": start["round"],
        "love_start": start["love_start"],
        "love_end": state.love,
        "income_actual": income_actual,
        "income_potential": income_potential,
        "income_lost_to_damage": max(0, income_potential - income_actual),
        "base_income": start["base_income"],
        "building_income_actual": building_income_actual,
        "building_income_potential": start["building_income_potential"],
        "painter_income": actual["painter_income"],
        "story_income": accum.get("story_income", 0),
        "upkeep_actual": upkeep_actual,
        "upkeep_potential": upkeep_potential,
        "upkeep_unpaid_from_deaths": max(0, upkeep_potential - upkeep_actual),
        "net_actual": income_actual - upkeep_actual,
        "net_potential": income_potential - upkeep_potential,
        "dmg_dealt": start["dmg_dealt"],
        "dmg_dealt_lightning": accum.get("dmg_dealt_lightning", 0),
        "lightning_hits": accum.get("lightning_hits", 0),
        "dmg_taken_buildings": start["dmg_taken_buildings"],
        "lives_lost": accum.get("lives_lost", 0),
        "lives_end": state.base_lives,
        "enemies_spawned": accum.get("enemies_spawned", 0),
        "kills": accum.get("kills", 0),
        "leaks": accum.get("leaks", 0),
        "kidnaps": accum.get("kidnaps", 0),
        "buildings_built": start["buildings_built"],
        "buildings_dead_at_payday": start["buildings_dead_at_payday"],
        "buildings_placed": accum.get("buildings_placed", 0),
        "love_spent_buildings": accum.get("love_spent_buildings", 0),
        "village_level": state.village_level,
        "player_xp": state.player_xp,
        "wave_size": accum.get("wave_size", 0),
        "enemy_tier": accum.get("enemy_tier", 0),
        "cheated": 1 if accum.get("cheated", 0) else 0,
    }
    # Ordered exactly like ROUND_FIELDS, and nothing outside it.
    return {k: row[k] for k in ROUND_FIELDS}


def round_breakdown(start, state, row):
    """The per-round detail that does NOT fit the flat CSV row: damage /
    income / upkeep split by building type. Kept parallel to ``rounds`` by the
    recorder and consumed by ``report.write_summary``."""
    actual = actual_ledger(state.income_events, start["coord_types"])
    return {
        "round": row["round"],
        "dmg_dealt_by_type": dict(start["dmg_dealt_by_type"]),
        "dmg_taken_by_type": dict(start["dmg_taken_by_type"]),
        "income_actual_by_type": actual["income_actual_by_type"],
        "upkeep_actual_by_type": actual["upkeep_actual_by_type"],
        "income_potential_by_type": dict(start["income_potential_by_type"]),
    }
