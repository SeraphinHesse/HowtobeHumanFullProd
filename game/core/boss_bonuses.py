"""Boss A/B bonuses (Phase 10G; reworked) — the six stacking story rewards.

Pure logic (no pygame). The stack counters live in ``RunState.boss_stacks`` (a
fresh run = a fresh ``RunState`` = the reset), and every helper takes the state
+ tilemap + core balance it reads.

**The bonus MAGNITUDES are BALANCING now, not code constants** (they were, in
10G): every number lives in ``data/balancing/core.json``'s ``BossBonuses``
block, threaded in as ``core_balance`` — the domain was chosen because
``core_balance`` already reaches every call site, so no signature grew a new
parameter CHAIN. ``choice_desc`` formats those same live numbers into the UI
copy, so the cutscene can never advertise a magnitude the math no longer uses.

The positional ids (``boss1a``..``boss3b``) and ``BONUS_IDS`` are UNCHANGED:
they encode set+option, which the cutscene labels (``WinA``/``WinB``), the
``effective_idx = (boss_num-1) % 3`` set cycle (set 0 = bosses 1,4,7…) and the
boss-history popup all key off. Picking the same option twice doubles it.

The six effects:

===========  ==================================================================
``boss1a``   +dmg per unbuilt (BUILDABLE) tile
``boss1b``   +dmg per building placed
``boss2a``   +love per building level past ``level_past_threshold``
``boss2b``   +love per building at ``low_level_target``
``boss3a``   +dmg per ``love_chunk_size`` of love held (the End-Turn snapshot)
``boss3b``   +dmg per lightning building built
===========  ==================================================================

**"Buildings" means ALIVE, non-base occupants of built tiles** in every one of
those counts — a destroyed building stops counting until payday's revive brings
it back. (10G's ``defence_count``/``aoe_count`` had NO alive filter; that
behaviour is gone with them.) Both level tests read ``TierState.
current_level_in_tier``, so a building freshly advanced into a new tier counts
as level 1 again. Lightning buildings are duck-typed off the
``"lightning_source"`` TAG (the ``payday._process_boosts`` ``"boost"``
precedent) — this module must never import ``game.buildings.registry``, which
would risk closing an import cycle (``game.core.session`` imports ``game.debug``
at module scope).

Payout sites: 1A/1B/3A/3B feed the per-shot ``dmg_bonus`` the host threads into
``resolve_combat`` (ONE flat int for the whole board); 2A/2B are payday slot 3
(``love_bonus_income``), paid silently as a whole-board sum — nothing folds into
per-recipient yields any more.
"""
from game.buildings.components import TierState

#: Duck-typed tag marking a lightning-capable building (Storm Priest). Kept as
#: a literal on purpose — see the module docstring's import-cycle note.
_LIGHTNING_TAG = "lightning_source"

# The 3 choice sets x A/B options. ``desc`` is two lines (the cutscene draws it
# line by line) and is ``.format(**core_balance["BossBonuses"])``-ed by
# ``choice_desc``, so every magnitude shown is the one the math uses.
BOSS_CHOICES = {
    0: {
        "A": {"id": "boss1a",
              "desc": "Per unbuilt tile, buildings\n"
                      "deal +{dmg_per_unbuilt_tile} extra damage"},
        "B": {"id": "boss1b",
              "desc": "Per building placed, buildings\n"
                      "deal +{dmg_per_building} extra damage"},
    },
    1: {
        "A": {"id": "boss2a",
              "desc": "Per building level past {level_past_threshold},\n"
                      "generate +{love_per_level_past} love per round"},
        "B": {"id": "boss2b",
              "desc": "Per level-{low_level_target} building, generate\n"
                      "+{love_per_low_level_building} love per round"},
    },
    2: {
        "A": {"id": "boss3a",
              "desc": "Per {love_chunk_size} love held, buildings\n"
                      "deal +{dmg_per_love_chunk} extra damage"},
        "B": {"id": "boss3b",
              "desc": "Per lightning building built,\n"
                      "buildings deal +{dmg_per_lightning_building} damage"},
    },
}

BONUS_IDS = ("boss1a", "boss1b", "boss2a", "boss2b", "boss3a", "boss3b")


def default_stacks():
    """A fresh run's stack counters — all six start at 0."""
    return {bid: 0 for bid in BONUS_IDS}


def choice_desc(effective_idx, option, core_balance):
    """The two-line UI copy for a set's ``"A"``/``"B"`` option, with the LIVE
    balancing magnitudes formatted in."""
    return BOSS_CHOICES[effective_idx][option]["desc"].format(
        **core_balance["BossBonuses"])


def apply_choice(state, effective_idx, option):
    """Increment the chosen option's stack by 1 (same pick twice = doubled)."""
    state.boss_stacks[BOSS_CHOICES[effective_idx][option]["id"]] += 1


def _alive_buildings(tilemap):
    """Every ALIVE non-base occupant of a built tile — the ONE definition of
    "a building" every count below shares."""
    for tile in tilemap.built_tiles():
        b = tile.occupant
        if (b is None or getattr(b, "building_type", None) == "base"
                or not getattr(b, "alive", False)):
            continue
        yield b


def _building_count(tilemap):
    """Boss1B's count: how many buildings are standing."""
    return sum(1 for _b in _alive_buildings(tilemap))


def _lightning_count(tilemap):
    """Boss3B's count: standing buildings carrying the lightning tag."""
    return sum(1 for b in _alive_buildings(tilemap)
               if _LIGHTNING_TAG in getattr(b, "tags", ()))


def story_damage_bonus(state, tilemap, core_balance):
    """The flat per-shot damage bonus every defender adds at fire time — ONE
    int for the whole board, summing all four damage contributors:
    Boss1A (per BUILDABLE tile), Boss1B (per standing building), Boss3A (per
    ``love_chunk_size`` of the CURRENT wave's End-Turn love snapshot) and
    Boss3B (per standing lightning building). Each term is
    ``count * magnitude * stacks``."""
    bb = core_balance["BossBonuses"]
    stacks = state.boss_stacks
    bonus = 0
    s1a = stacks["boss1a"]
    if s1a:
        bonus += len(tilemap.buildable_tiles()) * bb["dmg_per_unbuilt_tile"] * s1a
    s1b = stacks["boss1b"]
    if s1b:
        bonus += _building_count(tilemap) * bb["dmg_per_building"] * s1b
    s3a = stacks["boss3a"]
    if s3a:
        chunks = state.boss_love_snapshot // bb["love_chunk_size"]
        bonus += chunks * bb["dmg_per_love_chunk"] * s3a
    s3b = stacks["boss3b"]
    if s3b:
        bonus += (_lightning_count(tilemap)
                  * bb["dmg_per_lightning_building"] * s3b)
    return bonus


def love_bonus_income(state, tilemap, core_balance):
    """Payday slot 3: the whole-board love the story bonuses pay this round —
    Boss2A (per in-tier level past ``level_past_threshold``) + Boss2B (per
    building sitting exactly at ``low_level_target``), summed in ONE walk.
    Both read ``TierState.current_level_in_tier``, so a building just advanced
    into a new tier is a level-1 building again."""
    stacks = state.boss_stacks
    s2a = stacks["boss2a"]
    s2b = stacks["boss2b"]
    if not (s2a or s2b):
        return 0
    bb = core_balance["BossBonuses"]
    levels_past = 0
    low_level = 0
    for b in _alive_buildings(tilemap):
        ts = b.get_component(TierState)
        if ts is None:
            continue
        level = ts.current_level_in_tier
        if s2a:
            levels_past += max(0, level - bb["level_past_threshold"])
        if s2b and level == bb["low_level_target"]:
            low_level += 1
    return (levels_past * bb["love_per_level_past"] * s2a
            + low_level * bb["love_per_low_level_building"] * s2b)
