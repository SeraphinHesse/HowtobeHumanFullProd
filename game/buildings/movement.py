"""Moving an already-placed building to another tile (Building Movement).

The pure-logic sibling of ``registry.place_building``: ``start_move`` is the
ONE legal way a placed building leaves its tile for another, exactly as
``place_building`` is the one legal way a fresh one arrives (the same reason
the painter-tile bar and the boost-adjacency block live in that function and
not in the UI — the panel's disabled button is a convenience, this is the
enforcement).

Cost and duration both scale with the **Manhattan** (straight-line-only) tile
distance ``|dcol| + |drow|`` between origin and destination, floor-divided
into steps::

    value = base + (distance // increment) * increase

There is deliberately no tilemap/ownership check anywhere in this module: a
tile the player does not yet own, if it lies between the origin and
destination, is not special-cased — it simply adds to the distance exactly
like any other tile, because the metric counts every tile actually stepped
over (no diagonal shortcut) rather than the two endpoints' geometry alone.

…or a flat ``0`` when the matching ``*_enabled`` flag is off. Every number
comes from ``data/balancing/buildings.json``'s ``BuildingsGlobal.Movement``
group (G-7) — the caller passes that subtree in, this module never loads it.

**A move in transit is represented by ABSENCE, not by a new tile state.** On
``start_move`` the building is despawned from the scene and its origin tile is
cleared to ``TileState.BUILDABLE`` with no occupant; the destination tile was
already BUILDABLE. That is deliberate and is what makes every other system do
the right thing with ZERO new guards: the combat sweep
(``scene.by_tag("combat")``), the HP-bar pass (``scene.by_tag("building")``),
payday's income/upkeep/boost sweeps (which walk ``built_tiles()`` occupants)
and the boss's goal set all simply stop seeing an in-transit building, and
pick it back up the instant it lands. Both tiles resolve to the
``buildable_tile`` pathfinding weight while the move runs — walkable by
enemies, which is the intended behaviour — and ``TileMap.is_moving`` is what
bars them from hosting a new building meanwhile.

Arrival re-runs ``Building.on_placed(tilemap)``, the same post-placement family
hook ``place_building`` calls, so a moved booster re-applies its flat-mode buff
to its NEW cardinal neighbours. A moved booster's OLD neighbours keep whatever
``BoostReceiver`` state they had (never touched), and the moved building's own
``BoostReceiver`` travels with the Python object untouched — the building is
the SAME object throughout, only its tile changes.

**A WallBuilder is the ONE exception to that re-run** (feature:
wallbuilder-restricted-move, user decision). It IS movable, but only to a
tile its OWN claimed wall edges are attached to — see
``wall_builder_move_targets`` — and arrival does NOT call ``on_placed``: its
walls stay exactly the frozen perimeter they always were, and a move must
never let it re-scan the map and pick up newly-unclaimed segments elsewhere
as a side effect of relocating. Skipping the hook is safe because
``on_placed`` does nothing else for this type (`WallBuilder.on_placed` only
caches the tilemap reference and raises the perimeter — the reference is
already cached from its original placement and the tilemap object never
changes mid-run).
"""
import types

from game.map.tiles import TileState

#: The flat `data/slots.json` art slot (``core`` category) the host draws on
#: BOTH endpoints of a move in progress — the `blocker`/`wall_builder`
#: flat-slot convention. Defined here, with the feature, so the host has one
#: place to import it from rather than re-spelling the string.
MOVING_SIGN_SLOT = "moving_sign"


class MoveError(Exception):
    """A building could not be moved (bad destination, unmovable type, or
    not enough love). The ``registry.PlacementError`` sibling."""


def move_distance(from_col, from_row, to_col, to_row):
    """Manhattan (straight-line-only) tile distance — no diagonal shortcut,
    so every tile actually stepped over between origin and destination
    counts once, whether the player owns it or not. There is deliberately no
    tilemap/ownership check anywhere in this module: an unowned tile crossed
    by a move is not special-cased, it simply adds to the distance like any
    other tile."""
    return abs(to_col - from_col) + abs(to_row - from_row)


def _stepped(distance, enabled, base, increment, increase):
    """``base + (distance // increment) * increase`` when ``enabled``, else 0.

    ``increment`` is schema-floored at 1, so the floor division is always
    defined."""
    if not enabled:
        return 0
    return base + (distance // increment) * increase


def move_cost(distance, movement_balance):
    """Love charged to move a building ``distance`` tiles. 0 when the
    ``money_cost_enabled`` flag is off."""
    return _stepped(
        distance,
        movement_balance["money_cost_enabled"],
        movement_balance["base_love_cost"],
        movement_balance["love_cost_increase_increment"],
        movement_balance["love_cost_increase"],
    )


def move_time(distance, movement_balance, run_state=None,
              boss_upgrades_balance=None):
    """Rounds a move of ``distance`` tiles takes. 0 (instant — the building
    relocates the moment the move is confirmed, with no in-transit
    representation at all) when the ``time_cost_enabled`` flag is off.

    ``run_state``/``boss_upgrades_balance`` are BU-3's standard optional
    trailing pair (``game/core/boss_upgrades.py``'s threading-pattern
    section): with both present and the ``move_time_cap`` boss upgrade picked,
    the result is clamped to that upgrade's ``move_time_cap`` rounds (D14 —
    the TIME dial, the one actually enabled today; the love dial is off and is
    not capped). It does NOT stack per pick — a cap is a ceiling, and two
    ceilings are the lower one, which is the same number. The clamp lives
    HERE rather than in the shared ``_stepped`` helper because ``move_cost``
    calls that helper too and must stay untouched."""
    rounds = _stepped(
        distance,
        movement_balance["time_cost_enabled"],
        movement_balance["base_moving_time"],
        movement_balance["moving_time_increase_increment"],
        movement_balance["moving_time_increase"],
    )
    if run_state is None or boss_upgrades_balance is None:
        return rounds
    # Lazy import: game.core.__init__ pulls in payday, which imports THIS
    # module — a module-level import would close that cycle outright.
    from game.core import boss_upgrades
    n, params = boss_upgrades.hook_stacks(
        run_state, boss_upgrades_balance, "move_time_cap")
    if not n:
        return rounds
    return min(rounds, params.get("move_time_cap", 1))


def is_movable(building, tilemap=None):
    """Whether ``building`` can be moved AT ALL right now.

    Every non-WallBuilder type is always movable (the destination is still
    validated by ``start_move``). A WallBuilder is movable only when it has
    at least one legal destination within its OWN wall perimeter — see
    ``wall_builder_move_targets``, which needs the tilemap; a WallBuilder
    checked with no ``tilemap`` (a caller that cannot supply one) reports
    not-movable, the historical safe answer.

    Duck-typed on ``wall_hp`` — the same check ``game/ui/building_ui.py``'s
    ``_building_stats`` already uses to spot a wall builder, and the same
    never-import-the-leaf-class discipline the map layer follows."""
    if not hasattr(building, "wall_hp"):
        return True
    if tilemap is None:
        return False
    return bool(wall_builder_move_targets(building, tilemap))


def wall_builder_move_targets(building, tilemap):
    """Every tile ``building`` (a WallBuilder) may legally move to: a
    BUILDABLE, not-already-in-transit tile that ``building``'s OWN claimed
    wall edges are attached to on the interior side (feature:
    wallbuilder-restricted-move, user decision — "cannot be moved outside
    its own walls"). A WallBuilder's ``wall_snapshot()`` is an arbitrary set
    of perimeter EDGES, not a rectangle (it may own only whichever segments
    of the whole player-territory boundary were unclaimed when it was
    placed), so there is no enclosed area to compute — the destination set
    is simply the tiles those edges are anchored to.

    Returns a ``set`` of ``(col, row)`` pairs — used both to validate a
    chosen destination (``start_move``) and to build the move-picker's
    valid/greyed-out tile highlighting (``game/ui/building_ui.py``'s
    ``_build_move_select``)."""
    interior = {(c1, r1) for c1, r1, _c2, _r2 in building.wall_snapshot()}
    targets = set()
    for col, row in interior:
        tile = tilemap.get(col, row)
        if tile is None or tile.state != TileState.BUILDABLE:
            continue
        if tilemap.is_moving(col, row):
            continue
        targets.add((col, row))
    return targets


def _complete(tilemap, building, dest_tile, occupancy, scene):
    """Land ``building`` on ``dest_tile`` — the tail of
    ``registry.place_building``, replayed. Shared by the instant (0-round)
    branch of ``start_move`` and by ``process_moves``."""
    tilemap.set_tile_content(dest_tile, building, building.CONTENT_KEY)
    tilemap.set_tile_state(dest_tile, TileState.BUILT)
    # `occupancy`/`scene` are optional for logic tests, the same contract
    # `game/core/payday.py._free_tile` documents (payday reaches this function
    # through `process_moves` with whatever the Session handed it).
    if scene is not None:
        scene.spawn(building)
    if occupancy is not None:
        # Only this one tile changed — single-tile occupancy write, never the
        # full-map `sync_occupancy` scan (game/PERF.md).
        occupancy.set((dest_tile.col, dest_tile.row), building)
    # The transient (col, row) caches `Building.col`/`.row` read, and the
    # Transform the renderer reads — both must follow the building to its new
    # tile or it draws (and targets) from where it used to stand.
    building._col = dest_tile.col
    building._row = dest_tile.row
    building.transform.wx = float(dest_tile.col)
    building.transform.wy = float(dest_tile.row)
    # The same post-placement family hook a fresh placement fires (a booster
    # re-applies its flat-mode buff to its NEW neighbours). A WallBuilder is
    # the one exception (module docstring): its walls stay the frozen
    # perimeter they always were, so a move must never re-run the hook that
    # would otherwise re-scan the map and claim newly-unclaimed segments.
    if not hasattr(building, "wall_hp"):
        building.on_placed(tilemap)


def start_move(tilemap, building, dest_tile, movement_balance, love,
               occupancy, scene, run_state=None, boss_upgrades_balance=None):
    """Begin moving ``building`` to ``dest_tile``. Returns ``(cost, rounds)``.

    Raises ``MoveError`` if the destination is not BUILDABLE, is already an
    endpoint of another live move, if the building is a WallBuilder moving
    to a tile outside its own wall perimeter (or one with no legal
    destination at all), or if ``love`` is below the computed cost. The
    caller spends the returned ``cost`` — this module never touches the run
    state, exactly like ``place_building``.

    ``rounds == 0`` (the time cost switched off, or tuned to zero) relocates
    the building synchronously and records NO order: there is nothing to tick
    down and nothing to sign-post.

    ``run_state``/``boss_upgrades_balance`` are BU-3's standard optional
    trailing pair, forwarded verbatim to ``move_time`` so the rounds actually
    charged here match the capped figure the confirm modal quoted.
    """
    if dest_tile.state != TileState.BUILDABLE:
        raise MoveError(
            f"tile ({dest_tile.col},{dest_tile.row}) is "
            f"{dest_tile.state.name}, not BUILDABLE")
    if tilemap.is_moving(dest_tile.col, dest_tile.row):
        raise MoveError(
            f"tile ({dest_tile.col},{dest_tile.row}) is already part of a "
            f"move in progress")
    if hasattr(building, "wall_hp"):
        if (dest_tile.col, dest_tile.row) not in wall_builder_move_targets(
                building, tilemap):
            raise MoveError(
                "a wall builder may only move within its own walls")
    elif not is_movable(building):
        raise MoveError("this building cannot be moved")

    distance = move_distance(building.col, building.row,
                             dest_tile.col, dest_tile.row)
    cost = move_cost(distance, movement_balance)
    rounds = move_time(distance, movement_balance, run_state,
                       boss_upgrades_balance)
    if love < cost:
        raise MoveError(f"moving costs {cost} love, have {love}")

    # Vacate the origin. Clearing the occupant + despawning is the WHOLE
    # in-transit representation (see the module docstring) — the building
    # stops being seen by combat, income, boosts and the boss goal set for
    # free, with no new guards anywhere.
    origin_tile = tilemap.get(building.col, building.row)
    tilemap.set_tile_content(origin_tile, None, None)
    tilemap.set_tile_state(origin_tile, TileState.BUILDABLE)
    if occupancy is not None:
        occupancy.clear((origin_tile.col, origin_tile.row))
    if scene is not None:
        scene.despawn(building)

    if rounds == 0:
        _complete(tilemap, building, dest_tile, occupancy, scene)
        return cost, rounds

    tilemap.moving_orders.append(types.SimpleNamespace(
        building=building,
        from_col=origin_tile.col, from_row=origin_tile.row,
        to_col=dest_tile.col, to_row=dest_tile.row,
        rounds_left=rounds,
    ))
    return cost, rounds


def process_moves(tilemap, occupancy, scene):
    """Tick every live move down one round; land the ones that arrive.

    Called ONCE per payday, appended as its last step. Iterates a COPY of the
    order list because a completed order is removed from it."""
    for order in list(tilemap.moving_orders):
        order.rounds_left -= 1
        if order.rounds_left > 0:
            continue
        dest_tile = tilemap.get(order.to_col, order.to_row)
        # Remove the order BEFORE landing: `_complete` writes the destination
        # tile's state, and nothing downstream should still see it as an
        # endpoint of a move that has finished.
        tilemap.moving_orders.remove(order)
        if dest_tile is not None:
            _complete(tilemap, order.building, dest_tile, occupancy, scene)
