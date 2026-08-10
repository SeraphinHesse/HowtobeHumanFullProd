"""XP + village level maths (Phase 10A).

Pure logic (no pygame). Ports the prototype's ``_xp_for_enemy`` /
``_xp_for_etype`` / ``_award_xp`` / ``_award_xp_amount`` and the level-up half of
``_resolve_levelup`` (``src/core/game.py``). Everything reads
``data/balancing/core.json`` ``XP``.

Two prototype behaviours worth keeping straight:
- Crossing the threshold mid-combat only ARMS ``levelup_pending``; the window
  never opens during the enemy phase. ``Session`` opens it at ROUND_END.
- ``player_xp`` is not reset on level-up: only the OLD threshold is subtracted,
  so surplus carries forward. A single resolve grants exactly one level, and a
  carried-over surplus re-arms ``levelup_pending`` on the next kill.
"""
# etype (Enemy.ETYPE) -> the core.json XP key that pays for it. Public (not
# module-private) since TimelinePLAN T3: game/core/xp_curve.py imports this
# rather than re-declaring it, so the two vocabularies can never drift.
XP_KEY_FOR_ETYPE = {
    "standard": "xp_per_standard_enemy",
    "raider": "xp_per_raider",
    "siege": "xp_per_siege_enemy",
    "boss": "xp_per_boss",
}


def xp_for_etype(etype, core_balance):
    """XP granted by killing one enemy of ``etype``. Unknown -> standard."""
    xp = core_balance["XP"]
    return xp[XP_KEY_FOR_ETYPE.get(etype, "xp_per_standard_enemy")]


def scaled_base_income(state, core_balance):
    """The base's payout this income phase — the ONE source for payday, the HUD
    income line and the base-info panel, so the three can never drift."""
    hole, xp = core_balance["TheHole"], core_balance["XP"]
    return (hole["base_income"]
            + (state.village_level - 1) * xp["base_income_per_village_level"])


def award_xp(state, amount, world_pos=None):
    """Grant ``amount`` XP, arm ``levelup_pending`` on crossing the threshold,
    and (given a world position) queue an XP floater for the UI.

    Under designer-scripted leveling XP is not a mechanic at all, so this is a
    no-op — the ONE guard that covers every award site in ``Session``
    (``_award_building_deaths`` / ``on_base_hit`` / ``_award_enemy_xp`` /
    ``on_kidnap`` / ``_wipe_round``). It also keeps ``xp_events`` empty, which
    is what ``game/ui/effects.py``'s ``FloaterManager.spawn_xp_events``
    drains — so the floaters vanish with no change in the UI layer."""
    if state.scripted_leveling:
        return
    state.player_xp += amount
    if world_pos is not None:
        state.xp_events.append((world_pos[0], world_pos[1], amount))
    if not state.levelup_pending and state.player_xp >= state.xp_threshold:
        state.levelup_pending = True


def advance_village_level(state, core_balance):
    """The level-up threshold walk (prototype ``_resolve_levelup``). Order
    matters: the OLD threshold is what gets subtracted, then the increment grows.
    Yields the 50 -> 65 -> 85 -> 110 -> 140 curve from the shipped values."""
    xp = core_balance["XP"]
    state.village_level += 1
    old_threshold = state.xp_threshold
    state.xp_threshold += state.xp_threshold_inc
    state.xp_threshold_inc += xp["village_xp_threshold_inc_growth"]
    state.player_xp = max(0, state.player_xp - old_threshold)
