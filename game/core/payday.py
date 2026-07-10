"""Payday — the income phase, ordered EXACTLY like the prototype (Phase 9F).

``run_payday`` mirrors ``Game._begin_income_phase`` (``src/core/game.py``) step
for step. The ordering is SACROSANCT: later phases (10A-10G) fill the reserved
slots at their exact ordinal positions — notably the painter / boost /
wall-teardown slots MUST stay BEFORE the revive sweep so they observe a building
that died this round as ``alive == False`` (the prototype relies on this). Do
not reorder without the user.

9F drives steps 1, 2, 4, 5, 9, 11, 12 (snapshot -> base income + yield -> upkeep
clamp-0 -> revive -> round++ -> INCOME). Steps 3/6/7/8/10 are reserved no-ops
until their producing buildings exist. The income + upkeep sweeps are duck-typed
(``yield_amount`` / ``upkeep``) exactly like the prototype, so future building
types are picked up here with no edit to this loop.
"""
from game.buildings.components import RoundStats
from .phases import GamePhase
from .xp import scaled_base_income


def _built_tiles_with_occupant(tilemap):
    """(tile, occupant) for every BUILT tile that has an occupant (base + all
    built buildings). Tiles carry ``col``/``row`` for floater anchoring (9G)."""
    return [(t, t.occupant) for t in tilemap.built_tiles()
            if t.occupant is not None]


def _amount(building, method):
    """Duck-typed call of a zero-arg stat method; absent -> 0."""
    fn = getattr(building, method, None)
    return fn() if fn is not None else 0


def run_payday(state, tilemap, core_balance):
    hole = core_balance["TheHole"]
    built = _built_tiles_with_occupant(tilemap)
    buildings = [b for _, b in built]

    # 1. Reset income floaters — the per-tile ledger the 9G UI reads to spawn
    #    income/upkeep floaters (gated by ui.FX.income_floaters_enabled). Filled
    #    in steps 4 (income) + 5 (upkeep) below; the floater VFX itself is 9G.
    state.income_events.clear()

    # 2. Snapshot RoundStats: roll this-round -> last-round, then zero. Covers
    #    the base + every building (all sit on BUILT tiles). MUST be first — the
    #    reserved Boss3B bonus reads ``dmg_dealt_last_round``.
    for b in buildings:
        rs = b.get_component(RoundStats)
        if rs is None:
            continue
        rs.dmg_taken_last_round = rs.dmg_taken_this_round
        rs.dmg_dealt_last_round = rs.dmg_dealt_this_round
        rs.dmg_taken_this_round = 0
        rs.dmg_dealt_this_round = 0

    # 3. [reserved 10G] Boss-bonus payouts (Boss1B / Boss3B).

    # 4. Base income + yield sweep. Base income is always paid, scaled by the
    #    village level (10A). Then a duck-typed sweep adds each alive economy
    #    building's yield. Each payout is recorded as a floater event anchored
    #    on the paying tile.
    base_income = scaled_base_income(state, core_balance)
    state.add_love(base_income)
    state.income_events.append(
        (tilemap.base_col, tilemap.base_row, base_income, "income"))
    for tile, b in built:
        if not getattr(b, "alive", False):
            continue
        amount = _amount(b, "yield_amount")
        if amount > 0:
            state.add_love(amount)
            state.income_events.append((tile.col, tile.row, amount, "income"))

    # 5. Upkeep sweep. Mirror of income: every alive building is asked for its
    #    upkeep(); the total is deducted, love clamped at 0 (bills never push it
    #    negative — the prototype logs any shortfall; the log is 9G).
    total_upkeep = 0
    for tile, b in built:
        if not getattr(b, "alive", False):
            continue
        up = _amount(b, "upkeep")
        if up > 0:
            total_upkeep += up
            state.income_events.append((tile.col, tile.row, -up, "upkeep"))
    if total_upkeep > 0:
        state.spend_love(total_upkeep)

    # 6. [reserved 10C] Painter payout sweep — BEFORE revive.
    # 7. [reserved 10D] Boost sweep — BEFORE revive.
    # 8. [reserved 10E] Wall-teardown for dead wall-builders — BEFORE revive.

    # 9. Revive / heal: every non-base building full-heals (revives if dead).
    #    ``BaseBuilding.rebuild`` is a no-op — the base never revives.
    if hole["building_revive"]:
        for b in buildings:
            if getattr(b, "building_type", None) != "base":
                b.rebuild()

    # 10. [reserved 10E] rebuild_walls().

    # 11. round++
    state.round_num += 1

    # 12. phase -> INCOME, start the payday-floater timer.
    state.phase = GamePhase.INCOME
    state.phase_timer = core_balance["PhaseLoop"]["income_phase_duration"]
