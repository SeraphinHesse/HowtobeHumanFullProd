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


def _buildings(tilemap):
    """Every occupant of a BUILT tile (the base + all built buildings)."""
    return [t.occupant for t in tilemap.built_tiles() if t.occupant is not None]


def _amount(building, method):
    """Duck-typed call of a zero-arg stat method; absent -> 0."""
    fn = getattr(building, method, None)
    return fn() if fn is not None else 0


def run_payday(state, tilemap, core_balance):
    hole = core_balance["TheHole"]
    buildings = _buildings(tilemap)

    # 1. Reset income floaters — the floater VFX list (9G/10J); nothing here yet.

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

    # 4. Base income + yield sweep. Base income is always paid; village-level
    #    scaling is 10A (village_level == 1 here, so it's the flat base_income).
    #    Then a duck-typed sweep adds each alive economy building's yield.
    state.add_love(hole["base_income"])
    for b in buildings:
        if not getattr(b, "alive", False):
            continue
        amount = _amount(b, "yield_amount")
        if amount > 0:
            state.add_love(amount)

    # 5. Upkeep sweep. Mirror of income: every alive building is asked for its
    #    upkeep(); the total is deducted, love clamped at 0 (bills never push it
    #    negative — the prototype logs any shortfall; the log is 9G).
    total_upkeep = 0
    for b in buildings:
        if not getattr(b, "alive", False):
            continue
        up = _amount(b, "upkeep")
        if up > 0:
            total_upkeep += up
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
