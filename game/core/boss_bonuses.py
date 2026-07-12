"""Boss A/B bonuses (Phase 10G) — the six stacking run-wide story rewards.

Pure logic (no pygame). Ports the prototype's ``src/core/boss_bonuses.py``
WITHOUT its global singleton: the stack counters live in
``RunState.boss_stacks`` (a fresh run = a fresh ``RunState`` = the prototype's
reset), and every helper takes the state + tilemap it reads.

The bonus MAGNITUDES are prototype-hardcoded source constants, NOT balancing
(the ``COMBAT_SPEEDS`` / ``AOE_TRAVEL_TIME`` precedent) — each stack is worth
exactly +1 of its unit, so the magnitude IS the stack count times the counted
quantity. Choice sets cycle every 3 bosses: ``effective_idx = (boss_num-1) % 3``
(set 0 = bosses 1,4,7…; set 1 = 2,5,8…; set 2 = 3,6,9…). Picking the same
option twice doubles it (stacking, prototype ``boss_bonuses.py:67-74``).

Payout sites: Boss1A/3A feed the per-shot ``dmg_bonus`` the host threads into
``resolve_combat`` (one flat int — identical for every defender); Boss1B/3B are
payday slot 3; Boss2A/2B fold into the payday income sweep (and the HUD income
readout). The desc strings are the EXACT prototype UI copy (two lines each).
"""
from game.buildings.components import RoundStats, TierState

# The 3 choice sets x A/B options (prototype BOSS_CHOICES, verbatim copy).
BOSS_CHOICES = {
    0: {
        "A": {"id": "boss1a",
              "desc": "Per unbuilt tile, buildings do\n+1 extra damage"},
        "B": {"id": "boss1b",
              "desc": "Per building level past 2,\ngenerate +1 love per round"},
    },
    1: {
        "A": {"id": "boss2a",
              "desc": "Per Stone Thrower building,\nFlute Players yield +1 love"},
        "B": {"id": "boss2b",
              "desc": "Per AOE building,\nMeditators yield +1 love"},
    },
    2: {
        "A": {"id": "boss3a",
              "desc": "Per 10 love held, defence\nbuildings deal +1 damage"},
        "B": {"id": "boss3b",
              "desc": "Per 10 dmg by top building\nlast round, +1 love/round"},
    },
}

BONUS_IDS = ("boss1a", "boss1b", "boss2a", "boss2b", "boss3a", "boss3b")


def default_stacks():
    """A fresh run's stack counters — all six start at 0."""
    return {bid: 0 for bid in BONUS_IDS}


def choice_desc(effective_idx, option):
    """The exact two-line UI copy for a set's ``"A"``/``"B"`` option."""
    return BOSS_CHOICES[effective_idx][option]["desc"]


def apply_choice(state, effective_idx, option):
    """Increment the chosen option's stack by 1 (same pick twice = doubled)."""
    state.boss_stacks[BOSS_CHOICES[effective_idx][option]["id"]] += 1


def story_damage_bonus(state, tilemap):
    """The flat per-shot damage bonus every defender adds at fire time:
    Boss1A (per BUILDABLE tile, live count) + Boss3A (per 10 love of the
    CURRENT wave's End-Turn snapshot). One int for the whole board."""
    bonus = 0
    s1a = state.boss_stacks["boss1a"]
    if s1a:
        bonus += len(tilemap.buildable_tiles()) * s1a
    s3a = state.boss_stacks["boss3a"]
    if s3a:
        bonus += (state.boss_love_snapshot // 10) * s3a
    return bonus


def boss1b_income(state, tilemap):
    """Payday slot 3, Boss1B: +1 love per stack per in-tier level past 2 over
    every ALIVE non-base building (a level-3 building pays +1 per stack)."""
    stacks = state.boss_stacks["boss1b"]
    if not stacks:
        return 0
    total = 0
    for tile in tilemap.built_tiles():
        b = tile.occupant
        if (b is None or getattr(b, "building_type", None) == "base"
                or not getattr(b, "alive", False)):
            continue
        ts = b.get_component(TierState)
        if ts is not None:
            total += max(0, ts.current_level_in_tier - 2)
    return total * stacks


def boss3b_income(state, tilemap):
    """Payday slot 3, Boss3B: +1 love per stack per 10 damage the TOP alive
    building dealt LAST round. Runs after the RoundStats snapshot, so
    ``dmg_dealt_last_round`` is the round that just ended (×10-scaled)."""
    stacks = state.boss_stacks["boss3b"]
    if not stacks:
        return 0
    top = 0
    for tile in tilemap.built_tiles():
        b = tile.occupant
        if b is None or not getattr(b, "alive", False):
            continue
        rs = b.get_component(RoundStats)
        if rs is not None:
            top = max(top, rs.dmg_dealt_last_round)
    return (top // 10) * stacks


def defence_count(tilemap):
    """Boss2A count: occupants with ``building_type == "defence"`` — NO alive
    filter, ``aoe_defence``/``sun_scorcher`` do NOT count (prototype-exact)."""
    return sum(1 for t in tilemap.built_tiles()
               if getattr(t.occupant, "building_type", None) == "defence")


def aoe_count(tilemap):
    """Boss2B count: occupants with ``building_type == "aoe_defence"`` — NO
    alive filter (prototype-exact)."""
    return sum(1 for t in tilemap.built_tiles()
               if getattr(t.occupant, "building_type", None) == "aoe_defence")
