"""Build policies for the headless sim runner (debug-mode-telemetry Phase 6).

PURE decision functions. A policy is

    policy(state, tilemap, buildings_balance) -> [(tile, building_type), ...]

called ONCE per BUILDING phase by ``tools/simrun.py``, which then places each
returned pair through the REAL ``game.buildings.registry.place_building`` — so
costs, research gates, tile state, occupancy and the escalating Storm-Priest
price are all the game's own, not a policy's private idea of them. A policy
therefore never mutates anything: it proposes, the runner disposes, and a
proposal the real gate rejects is simply skipped.

**This module is deliberately NOT re-exported from ``game/debug/__init__.py``.**
It imports ``game.buildings.registry``/``research``, which reach
``game.map.tiles`` -> ``game.core.balance``; ``game.core.session`` imports
``game.debug`` at module scope, so pulling this in from the package ``__init__``
would close that cycle mid-import. ``tools/simrun.py`` imports
``game.debug.policies`` directly, after ``game.core`` is fully loaded.

The three shipped policies:

``none``            place nothing — the do-nothing baseline a balance change is
                    read against.
``greedy_defence``  the cheapest buildable DEFENCE type, on the buildable tiles
                    nearest the base.
``balanced``        alternates economy and defence by round parity.
"""
from game.buildings.registry import (
    LIGHTNING_SOURCE_TAG, BUILDING_CLASSES, build_cost, count_tag,
)
from game.buildings.research import buildable, tiers_unlocked_for
from game.buildings.defence import DefenceBuilding
from game.buildings.economy import EconomyBuilding

#: How many buildings a policy may propose in one BUILDING phase. A cap keeps
#: an early Infinite-Money-shaped board from being solved in round 1, which
#: would make every later round's telemetry meaningless.
MAX_PER_ROUND = 2

DEFENCE, ECONOMY = "defence", "economy"


def _family(building_type):
    """``DEFENCE`` / ``ECONOMY`` / ``None`` for a leaf type — read off the
    class hierarchy, never a name match, so a new family added by
    ``/add-building`` is classified for free."""
    cls = BUILDING_CLASSES.get(building_type)
    if cls is None:
        return None
    if issubclass(cls, DefenceBuilding):
        return DEFENCE
    if issubclass(cls, EconomyBuilding):
        return ECONOMY
    return None


def _priced_options(state, tilemap, buildings_balance, family):
    """``[(cost, building_type), ...]`` cheapest first, over the types of
    ``family`` the run has actually researched. The cost is what
    ``place_building`` will really charge: the type's CURRENT research ceiling
    tier, and the live ``lightning_source`` repeat count (a Storm Priest gets
    dearer with every one already standing)."""
    repeat = count_tag(tilemap, LIGHTNING_SOURCE_TAG)
    out = []
    for building_type in sorted(BUILDING_CLASSES):
        if _family(building_type) != family or not buildable(state, building_type):
            continue
        tier_idx = max(0, tiers_unlocked_for(state, building_type) - 1)
        out.append((build_cost(building_type, buildings_balance, tier_idx,
                               repeat), building_type))
    out.sort()
    return out


def _tiles_nearest_base(tilemap):
    """Buildable tiles, nearest the base first. Ties break on ``(col, row)`` so
    two runs of the same seed choose identically (the determinism pin)."""
    bc, br = tilemap.base_col, tilemap.base_row
    if bc is None:
        return sorted(tilemap.buildable_tiles(), key=lambda t: (t.col, t.row))
    return sorted(tilemap.buildable_tiles(),
                  key=lambda t: ((t.col - bc) ** 2 + (t.row - br) ** 2,
                                 t.col, t.row))


def _plan(state, tilemap, buildings_balance, families, limit=MAX_PER_ROUND):
    """Walk ``families`` in order, spending the run's love on the cheapest
    researched type of each, onto the nearest buildable tiles. Stops at
    ``limit`` placements or when the next one is unaffordable."""
    tiles = _tiles_nearest_base(tilemap)
    if not tiles:
        return []
    budget = state.love
    plan = []
    for family in families:
        options = _priced_options(state, tilemap, buildings_balance, family)
        if not options:
            continue
        cost, building_type = options[0]
        while len(plan) < limit and budget >= cost and len(plan) < len(tiles):
            plan.append((tiles[len(plan)], building_type))
            budget -= cost
        if len(plan) >= limit:
            break
    return plan


# ---------------------------------------------------------------------------
def none(state, tilemap, buildings_balance):
    """The do-nothing baseline: every round is played with the starting board,
    so the CSV is a pure read of how the wave curve scales unopposed."""
    return []


def greedy_defence(state, tilemap, buildings_balance):
    """Cheapest researched defence type, on the buildable tiles nearest the
    base — the "spend everything on guns, closest first" reading."""
    return _plan(state, tilemap, buildings_balance, (DEFENCE,))


def balanced(state, tilemap, buildings_balance):
    """Alternate economy and defence by round parity — economy on even rounds,
    defence on odd — so the run grows its income instead of stalling on it."""
    families = ((ECONOMY, DEFENCE) if state.round_num % 2 == 0
                else (DEFENCE, ECONOMY))
    return _plan(state, tilemap, buildings_balance, families)


#: The ``--strategy`` names ``tools/simrun.py`` offers.
STRATEGIES = {
    "none": none,
    "greedy_defence": greedy_defence,
    "balanced": balanced,
}
