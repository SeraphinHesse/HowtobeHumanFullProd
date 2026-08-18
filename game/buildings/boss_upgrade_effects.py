"""Boss-upgrade effects that need BUILDING knowledge (BossUpgradeTimelinePLAN
BU-3, sub-tasks 3.1 + 3.2).

``game/core/boss_upgrades.py`` is the effect engine and may import NOTHING from
``game.buildings`` — that is a hard rule, not a preference (see its module
docstring). Two of the twelve upgrades need exactly that, though: #9
``stone_thrower_sync`` has to walk every placed ``Defender`` and level it, and
#5 ``musician_auto_level`` has to level a freshly-placed ``Musician``. This
module is where that half lives, and it is the ONLY place in the codebase that
knows how to advance a building for FREE.

**The free-advance path is ``upgrade()`` / ``advance_tier()``, never a
``TierState`` write.** Those are the same two methods
``game/ui/building_ui.py``'s upgrade-panel branches call after taking the
player's love, so a boss-granted level goes through exactly the same machinery
a bought one does — most importantly ``Building.apply_tier_stats()``, which
recomputes ``max_hp``/the sprite slot/the family ``_on_apply_stats`` hook and
full-heals. Poking ``TierState.current_level_in_tier`` directly would skip all
of it and leave a building's stats stale against its own displayed level.

**The panel's two documented side-hooks are deliberately NOT called here, and
that is provably a no-op rather than an omission.**
``game.core.lightning.sync_level_from_tier`` is gated on the
``"lightning_source"`` TAG and ``game.core.wall_era.sync_wall_art_era`` is
duck-typed on ``hasattr(building, "stamp_era")``; the only two tier lines this
module ever advances are the ``Defender`` line (Stone Thrower -> Slinger ->
Pistoleer) and the ``Musician`` line (Flute Player -> Harp Player -> Trio),
and neither carries either marker. Calling them would cost an import from
``game.core`` (and, for ``sync_wall_art_era``, an ``enemies_balance`` argument
the one-time-hook contract does not supply) to reach a guaranteed no-op. **If a
future boss upgrade advances a Storm Priest or a Wall Builder, both calls must
be added here** — that is the whole reason this paragraph exists.
"""
from .defender import Defender
from .musician import Musician

#: How many advance steps a single sync may take before it gives up. A tier
#: line is 3 tiers x 3 levels today, so this is unreachable in practice — it
#: exists so a malformed tier table can never spin the frame forever.
_MAX_STEPS = 64


def advance_free_to_level(building, target_level):
    """Level ``building`` up (crossing tier boundaries as needed) until its
    global ``level`` reaches ``target_level``. Costs nothing.

    ``Building.level`` is the sum of every earlier tier's ``levels`` plus the
    in-tier level, so it is a single monotone rank over a whole tier line —
    which is what makes "match the best one" a plain integer comparison rather
    than a (tier, level) lexicographic walk. Returns how many steps it took.

    Stops early at the line's ceiling: ``upgrade()`` returns False at a tier's
    max level and ``advance_tier()`` returns False at the final tier, so a
    target that cannot be reached simply lands as high as it can.
    """
    steps = 0
    while building.level < target_level and steps < _MAX_STEPS:
        steps += 1
        if building.upgrade():
            continue
        if not building.advance_tier():
            break
    return steps


def advance_free_levels(building, levels):
    """Level ``building`` up ``levels`` times WITHIN its current tier, free.

    Deliberately never calls ``advance_tier()``: a tier advance is gated on
    research (``RunState.tiers_unlocked``), and a placement-time bonus must not
    hand out a tier the run has not earned. A building already at its tier's
    max level simply keeps it. Returns how many levels were actually granted.
    """
    granted = 0
    for _ in range(max(0, levels)):
        if not building.upgrade():
            break
        granted += 1
    return granted


def placed_buildings(tilemap, cls):
    """Every placed instance of ``cls`` on the board, dead ones included.

    Walks ``TileMap.built_tiles()`` — the ``_by_state`` index, i.e. O(built
    tiles) and never a full-map scan (``game/map/CLAUDE.md``'s perf
    invariants) — exactly as ``game/ui/overlays.py``'s TIER OVERVIEW pass and
    ``registry.count_tag`` do. A DEAD building is included on purpose: it is
    not a freed slot (payday's slot-9 revive brings it back), so it is still
    one of "all placed X".
    """
    return [t.occupant for t in tilemap.built_tiles()
            if isinstance(t.occupant, cls)]


def sync_stone_throwers(state, tilemap, scene):
    """Boss upgrade #9 ``stone_thrower_sync`` — ONE-TIME (D17, no ongoing
    re-sync rule).

    Levels every placed ``Defender`` up to match the best one, for free,
    through the normal advance path above. Installed by the HOST at boot via
    ``game.core.boss_upgrades.set_one_time_hook("stone_thrower_sync", …)`` and
    called with ``(state, tilemap, scene)`` from ``apply_pick``.

    ``state`` and ``scene`` are part of that fixed hook signature and are
    deliberately unused: the buildings are reached off the tilemap (the same
    occupant contract every other sweep in the game uses), the advance is free
    so no love is spent, and nothing is spawned or despawned.

    Returns the number of buildings it actually changed (0 with fewer than two
    defenders on the board, or when they are already level-matched).
    """
    defenders = placed_buildings(tilemap, Defender)
    if len(defenders) < 2:
        return 0
    target = max(b.level for b in defenders)
    changed = 0
    for b in defenders:
        if b.level < target and advance_free_to_level(b, target):
            changed += 1
    return changed


def apply_musician_auto_level(building, run_state, boss_upgrades_balance):
    """Boss upgrade #5 ``musician_auto_level`` — the placement-time half.

    Called by ``registry.place_building`` right after ``on_placed``. Scoped to
    the Musician tier line ONLY (D12) — an ``isinstance`` check rather than a
    ``building_type`` string, since this module may legally know the leaf
    classes and G-3's "no type-string branching" is about the type-agnostic
    seams, not about a line-scoped bonus whose scope IS the line.

    Stacks additively (D4): picked twice grants ``2 * bonus_levels``. Returns
    how many levels were granted (0 whenever the hook is inert).
    """
    if not isinstance(building, Musician):
        return 0
    # Lazy import: game.core.__init__ pulls in payday, which imports
    # game.buildings.movement — a module-level import from here would close
    # that cycle (see boss_upgrades.py's threading-pattern section).
    from game.core import boss_upgrades

    n, params = boss_upgrades.hook_stacks(
        run_state, boss_upgrades_balance, "musician_auto_level")
    if not n:
        return 0
    return advance_free_levels(building, n * params.get("bonus_levels", 1))
