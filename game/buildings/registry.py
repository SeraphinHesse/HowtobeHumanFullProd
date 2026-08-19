"""Building factory + placement seam (Phase 9D; feature-storm-acolyte-multi-
build's escalating-cost seam).

``create`` maps a ``building_type`` string to its leaf class — also the way to
reconstruct a subclass after ``GameObject.from_dict`` (which returns a base
GameObject, losing subclass identity). ``place_building`` ports the prototype's
placement gate: buildable tile + affordability (9D) + the per-type research gate
(10A — the type must be unlocked; its tier 1 is immediately placeable the
moment it is, ``starts_with_tier`` no longer exists), and wires the new
building through the 9C seams: ``tile.occupant``/``content_key``/``state``,
``Scene.spawn``, ``TileMap.sync_occupancy``. Love + the run state are passed in;
this module never reaches into ``game.core``.

``BUILDING_CLASSES`` is the same dict as ``research.LEAF_CLASSES`` — it lives
there so ``game/core/levelup.py`` can read it without importing this module (see
the import-boundary note in ``research.py``).

``BaseBuilding`` is NOT in the placeable registry — it has a different
constructor (core balance) and is attached to its pre-seeded tile via
``attach_base`` during bootstrap.
"""
import random  # stdlib — pure; the default draw when no rng is injected

from engine.core import SpriteAnimator

from game.map.tiles import CONDITION_BLOCKS_BUILD, TileState
from .research import LEAF_CLASSES, RESEARCH, buildable, tiers_unlocked_for

# building_type -> leaf class. Only the 9D leaves; families grow in 10x.
BUILDING_CLASSES = LEAF_CLASSES

# MasterSheetColumnsPLAN B1: the `data/slots.json` category every placeable
# building's art slot lives under. It lives HERE, with the feature that needs
# it, for the same reason `WALL_CATEGORY` lives in `game/map/wall_render.py` —
# and it is a bare string, so this package still imports NOTHING from the asset
# layer (D6). The HOST (`game/main.py`) is what resolves it against the slot
# registry + manifest and hands the result back down as `colour_columns`.
BUILDINGS_CATEGORY = "buildings"


class PlacementError(Exception):
    """A building could not be placed (non-buildable tile or not enough love)."""


def create(building_type, col, row, buildings_balance, tier_idx=0):
    """Construct a placeable building of ``building_type`` at ``(col, row)``,
    starting at ``tier_idx`` (0 = the type's first tier)."""
    return BUILDING_CLASSES[building_type](col, row, buildings_balance, tier_idx)


# Storm Acolyte multi-build (feature-storm-acolyte-multi-build): the ONE tag
# whose already-built count escalates a fresh placement's price, via each
# group's OPTIONAL ``repeat_cost_multiplier`` balancing key (today only
# ``DefenceBuildings.StormPriest`` carries it). Tag-gated (G-3) — never a
# ``building_type == "storm_priest"`` branch anywhere on this seam.
LIGHTNING_SOURCE_TAG = "lightning_source"


def count_tag(tilemap, tag):
    """Count of BUILT-tile occupants (alive OR dead — a dead one is not a
    freed slot, payday's slot-9 revive brings it back) carrying ``tag``.
    O(built tiles) via ``TileMap.built_tiles()``'s ``_by_state`` index — never
    a full-map scan (``game/map/CLAUDE.md``'s perf invariants)."""
    return sum(1 for t in tilemap.built_tiles()
              if t.occupant is not None and tag in t.occupant.tags)


def build_cost(building_type, buildings_balance, tier_idx=0, repeat_count=0,
               run_state=None, boss_upgrades_balance=None):
    """Build cost for ``building_type`` at ``tier_idx`` (the placement price).

    ``repeat_count`` (feature-storm-acolyte-multi-build) escalates the price
    by the group's own ``repeat_cost_multiplier ** repeat_count`` when that
    OPTIONAL balancing key is present; ``repeat_count=0`` (the default) and a
    group with no such key both leave today's price untouched, so every
    caller that predates this feature is unaffected.

    ``run_state``/``boss_upgrades_balance`` are BU-3's standard optional
    trailing pair (``game/core/boss_upgrades.py``'s threading-pattern
    section): with both present, a ``"structure"``-tagged type
    (``Blocker``/``WallBuilder``) is cut by the ``wall_cost_discount`` boss
    upgrade, applied LAST so it discounts the escalated price rather than the
    other way round. This is the module-level twin of
    ``Building.build_cost()`` — the one a fresh placement and the upgrade
    panel's tier-advance button actually charge — and both go through the same
    reducer, so they can never disagree."""
    cls = BUILDING_CLASSES[building_type]
    tiers = cls._resolve_tiers(buildings_balance)
    cost = tiers[tier_idx]["build_cost"]
    if repeat_count:
        mult = cls._resolve_group(buildings_balance).get(
            "repeat_cost_multiplier")
        if mult is not None:
            cost = round(cost * (mult ** repeat_count))
    if (run_state is not None and boss_upgrades_balance is not None
            and "structure" in cls.EXTRA_TAGS):
        # Lazy import: game.core.__init__ pulls in payday, which imports
        # game.buildings.movement — a module-level import from this package
        # closes that cycle (boss_upgrades.py documents the rule).
        from game.core import boss_upgrades
        cost = boss_upgrades.discounted(
            cost, run_state, boss_upgrades_balance, "wall_cost_discount",
            "cost_reduction_pct", 50, floor=1)
    return cost


def place_building(tilemap, tile, building_type, love, buildings_balance,
                   scene, occupancy, state=None, colour_columns=None,
                   rng=None, column=None, boss_upgrades_balance=None):
    """Place ``building_type`` on ``tile``. Returns ``(building, cost)``.

    Raises ``PlacementError`` if the tile is not BUILDABLE, the type is not yet
    unlocked (given a ``state``), or ``love`` is below the build cost
    (prototype ``Game.place_building`` gate). On success sets the tile's
    occupant/content_key/state, spawns the building into ``scene``, and re-syncs
    ``occupancy`` — the single 9C occupancy seam.

    ``state`` is the ``RunState`` (duck-typed: ``unlocked_buildings`` /
    ``tiers_unlocked``); omit it in stat/logic tests that predate the run state.

    MASTER-SHEET COLOUR (MasterSheetColumnsPLAN B1). The last three arguments
    stamp the building's master-sheet colour column at placement — colour IS
    ``SpriteAnimator.column``, and it survives every later upgrade for free
    (``Building.apply_tier_stats`` rewrites only ``slot_key``):

    * ``colour_columns`` — ``{slot_key: (colour_name, ...)}``, the capability
      map the HOST derives once at boot (``game/main.py``). This package never
      reaches into the asset layer itself (D6/E-37). ``None`` ⇒ no slot has
      colours ⇒ every animator keeps its ``-1`` "no driver" sentinel, which is
      what keeps every caller that predates this feature byte-identical.
    * ``rng`` — the injected RNG; ``None`` ⇒ the stdlib ``random`` module (the
      ``game/enemies/spawner.py`` shape). Only consulted when a roll actually
      happens, so no seeded test's global draw sequence moves.
    * ``column`` — an EXPLICIT colour, e.g. the swatch the player picked in the
      construct modal. Wins over the roll verbatim; ``0`` is a real colour
      index, so this is tested with ``is not None``, never for truthiness. Not
      range-checked here — S1's D7 clamp handles an out-of-range column at cut
      time.

    ``boss_upgrades_balance`` is HALF of BU-3's standard optional trailing pair
    (``game/core/boss_upgrades.py``'s threading-pattern section) — the other
    half, the RunState, is already here under its existing name ``state``, so
    this seam grows one argument rather than a duplicate reference to the same
    object. With both present two boss upgrades come alive: the price a
    ``Blocker``/``WallBuilder`` is charged is cut by ``wall_cost_discount``
    (through ``build_cost`` below), and a freshly-placed ``Musician`` is
    levelled by ``musician_auto_level``. Absent (every caller that predates
    BU-3, every logic test) both are inert.
    """
    if tile.state != TileState.BUILDABLE:
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is {tile.state.name}, not BUILDABLE")
    # Tile Condition Rework: a pond may never host a building, regardless of
    # zone state. Enforced HERE, the single legal placement path, exactly
    # like the painter-tile bar and move-in-progress bar below.
    if tile.condition in CONDITION_BLOCKS_BUILD:
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is a pond and cannot be built on")
    if state is not None and not buildable(state, building_type):
        raise PlacementError(f"{building_type} is not researched yet")
    # 10C: a tile that completed a Painter payout is permanently barred from
    # hosting another Painter (prototype ``used_painter_tiles`` — enforced HERE,
    # the single legal placement path; the UI disabling is only a convenience).
    if (building_type == "painter" and state is not None
            and (tile.col, tile.row) in getattr(state, "used_painter_tiles", ())):
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) already sold a painting")
    # Building Movement: neither endpoint of a move in progress may host a new
    # building — the vacated origin and the reserved destination are both
    # ordinary BUILDABLE tiles (deliberately, so enemies keep walking through
    # them), so `is_moving` is the only thing that tells them apart. Enforced
    # HERE, the single legal placement path, exactly like the painter-tile bar
    # above; the panel's tile-picking is only a convenience. `getattr` keeps
    # the pre-feature tilemap stubs some logic tests build working.
    is_moving = getattr(tilemap, "is_moving", None)
    if is_moving is not None and is_moving(tile.col, tile.row):
        raise PlacementError(
            f"tile ({tile.col},{tile.row}) is part of a move in progress")
    # 10D: boosters may not be placed cardinally adjacent to another booster
    # (prototype ``Game.place_building`` 'boost_adjacent' — cardinal-4, diagonals
    # allowed). Enforced HERE, the single legal placement path. Deliberately a
    # FIXED cardinal-4 check, independent of `BoostBuildings.globals.range_tiles`/
    # `.range_shape` (the configurable buff/curse range, `game/buildings/boost.py`)
    # — a designer widening the buff range does not change this placement rule.
    if building_type.startswith("boost_"):
        for dc, dr in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            adj = tilemap.get(tile.col + dc, tile.row + dr)
            if (adj is not None and adj.occupant is not None
                    and "boost" in adj.occupant.tags):
                raise PlacementError(
                    f"a boost building is already next to ({tile.col},{tile.row})")
    # A fresh placement builds at the type's CURRENT research ceiling, not
    # always tier 0 (10A follow-up): once a higher tier is researched, the
    # lower tier is simply never placed again — no separate gate needed.
    # ``state=None`` (logic tests that predate RunState) keeps tier 0.
    tier_idx = (tiers_unlocked_for(state, building_type) - 1
                if state is not None else 0)
    # feature-storm-acolyte-multi-build: every placement counts the already-
    # built ``lightning_source``-tagged occupants (tag-gated, G-3 — never a
    # ``storm_priest`` branch) and passes it through; ``build_cost`` is a
    # no-op with this for every OTHER type (no ``repeat_cost_multiplier`` key).
    repeat_count = count_tag(tilemap, LIGHTNING_SOURCE_TAG)
    cost = build_cost(building_type, buildings_balance, tier_idx, repeat_count,
                      run_state=state,
                      boss_upgrades_balance=boss_upgrades_balance)
    if love < cost:
        raise PlacementError(
            f"{building_type} costs {cost} love, have {love}")
    building = create(building_type, tile.col, tile.row, buildings_balance,
                      tier_idx)
    # Occupant + content key in one write through the TileMap seam — the
    # content key drives the tile's path weight, so the seam invalidates the
    # pathfinder's cached flow field (see game/map/tile_map.py).
    tilemap.set_tile_content(tile, building, building.CONTENT_KEY)
    # -- 10I: snapshot the tile condition at placement (prototype
    # ``b.tile_condition = tile.condition``, game.py:690). Conditions are
    # immutable after the map roll, so snapshot == live read. The modifiers
    # subtree rides along so stat getters need no tilemap reference.
    building._tile_condition = tile.condition
    building._condition_mods = (
        tilemap.balance["TileConditions"]["modifiers"])
    # Re-apply derived stats so condition-dependent hooks (the defence
    # RangeSensor mirrors the mountain-boosted effective range) see the
    # snapshot; the full-heal inside is a no-op at placement (hp == max).
    building.apply_tier_stats()
    # -- /10I --
    # -- B1: stamp the master-sheet colour column. AFTER ``apply_tier_stats``,
    # because that is what writes ``anim.slot_key``, and the capability map is
    # keyed on the slot key. The column then rides through every later upgrade
    # untouched (``apply_tier_stats`` rewrites only ``slot_key``) — D5's
    # accepted consequence is that a chain must author its colours in the same
    # order across tiers. ``get_component(SpriteAnimator)`` is the same
    # isinstance-matching accessor ``apply_tier_stats`` uses, and is None on the
    # base building, which carries no animator at all.
    #
    # Booster exclusion (feature: boost buildings never recolour): a booster
    # (the "boost" tag, `game/buildings/boost.py`'s `EXTRA_TAGS`) is excluded
    # from colour ENTIRELY — no roll AND no explicit swatch pick, so it always
    # renders at its single default appearance. `game/ui/building_ui.py` never
    # offers a booster's swatch row in the first place (ConstructPreview /
    # `_build_colour_row`), so `column` is never non-None for one in practice;
    # the tag check here is what makes the exclusion hold even if a caller
    # (a test, `tools/simrun.py`) passes one explicitly.
    anim = building.get_component(SpriteAnimator)
    if anim is not None and "boost" not in building.tags:
        if column is not None:
            anim.column = column          # explicit swatch — no draw at all
        else:
            names = (colour_columns or {}).get(anim.slot_key, ())
            if names:
                draw = rng if rng is not None else random
                anim.column = draw.randrange(len(names))
            # else: leave anim.column at its -1 "no driver" sentinel — NOT 0,
            # which is a real colour index (engine/core/sprite_animator.py:28).
    # -- /B1 --
    # A freshly-placed building's sprite stays hidden for
    # `BuildingsGlobal.placement_reveal_delay_seconds` (purely cosmetic — see
    # `BuildingSprite.reveal_delay`, `game/buildings/components.py`; gameplay
    # — occupancy/stats/combat, all below and above this line — is unaffected).
    if anim is not None:
        anim.reveal_delay = buildings_balance["BuildingsGlobal"][
            "placement_reveal_delay_seconds"]
    tilemap.set_tile_state(tile, TileState.BUILT)
    scene.spawn(building)
    # Only this one tile changed — update its occupancy directly instead of the
    # full-map ``sync_occupancy`` scan (an O(map) hitch on large maps, D-20).
    occupancy.set((tile.col, tile.row), building)
    # Post-placement family hook (Building.on_placed, default no-op): a booster
    # in flat mode applies its one-time boost (10D); a WallBuilder raises its
    # perimeter walls (10E).
    building.on_placed(tilemap)
    # BU-3 #5 musician_auto_level: AFTER create() + on_placed(), so the bonus
    # levels land on a fully wired building (the levels themselves go through
    # the normal `upgrade()` path, never a TierState write — see
    # `boss_upgrade_effects.py`). Scoped to the Musician tier line (D12); a
    # no-op for every other type and whenever the boss-upgrade pair is absent.
    # Local import: `boss_upgrade_effects` imports the leaf classes, and this
    # module is itself imported from `game.buildings.__init__` before some of
    # them exist.
    from .boss_upgrade_effects import apply_musician_auto_level
    apply_musician_auto_level(building, state, boss_upgrades_balance)
    return building, cost


def attach_base(tilemap, base_building, scene, occupancy):
    """Attach the ``BaseBuilding`` to the pre-seeded base tile (already BUILT +
    ``base_building`` content key from ``TileMap`` construction), spawn it, and
    sync occupancy. The 9C↔9D base contract."""
    tile = tilemap.get(tilemap.base_col, tilemap.base_row)
    # Content key is already BASE_CONTENT_KEY (unchanged → no path-cache
    # invalidation); the seam just records the occupant.
    tilemap.set_tile_content(tile, base_building, tile.content_key)
    scene.spawn(base_building)
    # Single-tile occupancy update (see place_building) — no full-map scan.
    occupancy.set((tile.col, tile.row), base_building)
    return base_building
