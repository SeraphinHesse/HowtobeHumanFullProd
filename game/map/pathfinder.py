"""Dijkstra pathfinding over the runtime tile grid (Phase 9C).

Port of the prototype's ``src/map/pathfinder.py`` — the five ``find_path*``
variants, 4-connected, min-heap, wall-block hook, and a pre-query weight
refresh. Weights and the impassable threshold come from the ``TileMap``'s
injected balancing (via ``tilemap.weight`` / ``tilemap.impassable_weight``);
goal-set variants target occupied tiles by their occupant's ``building_type``
(duck-typed), so with no buildings yet (9C) they all fall back to the base
path. Returns ``[(col, row), ...]`` start→goal, or ``[]`` if unreachable.

The four near-identical Dijkstra loops of the prototype are unified into
``_dijkstra`` (multi-goal, stops at the first goal popped); ``find_path`` and
``find_path_ignoring_walls`` are the single-goal (base) cases. Pure Python.
"""
import heapq


# Occupant building_type values counted as "economy" (prototype pathfinder.py:36).
_ECONOMY_BUILDING_TYPES = {"economic", "meditator", "painter"}


def _pre_query_refresh(tilemap):
    """Refresh damage-weight reductions (and defence-range coverage, when core
    has wired a coverage function) before a query — the prototype's
    ``_apply_damage_weights``. Both producers are dormant in 9C."""
    refresh = getattr(tilemap, "refresh_damage_weight_reductions", None)
    if refresh is not None:
        refresh()
    fn = getattr(tilemap, "_defence_coverage_fn", None)
    if fn is not None and hasattr(tilemap, "refresh_defence_range_coverage"):
        tilemap.refresh_defence_range_coverage(fn())


def _neighbors(col, row, tilemap):
    """4-directional in-bounds grid neighbours."""
    for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nc, nr = col + dc, row + dr
        if 0 <= nc < tilemap.cols and 0 <= nr < tilemap.rows:
            yield nc, nr


def _wall_blocks(tilemap, cur_col, cur_row, nb_col, nb_row):
    """True if a standing wall sits on the edge between the two tiles (10E).
    Until walls exist, ``get_wall_between`` returns None → never blocks."""
    get_wall = getattr(tilemap, "get_wall_between", None)
    if get_wall is not None:
        w = get_wall(cur_col, cur_row, nb_col, nb_row)
        if w is not None and getattr(w, "hp", 0) > 0:
            return True
    return False


def _reconstruct(prev, start_col, start_row, goal):
    path = []
    cur = goal
    while cur in prev:
        path.append(cur)
        cur = prev[cur]
    if cur == (start_col, start_row):
        path.append((start_col, start_row))
    else:
        return []  # start unreachable from goal
    path.reverse()
    return path


def _dijkstra(tilemap, start_col, start_row, goals, ignore_walls):
    """Cheapest path from start to the nearest tile in `goals`, or [] if none
    is reachable. Assumes the caller already ran ``_pre_query_refresh``."""
    impassable = tilemap.impassable_weight
    dist = {}
    prev = {}
    heap = [(0, start_col, start_row)]
    reached = None
    while heap:
        cost, col, row = heapq.heappop(heap)
        if (col, row) in dist:
            continue
        dist[(col, row)] = cost
        if (col, row) in goals:
            reached = (col, row)
            break
        for nc, nr in _neighbors(col, row, tilemap):
            if (nc, nr) in dist:
                continue
            tile = tilemap.get(nc, nr)
            if tile is None:
                continue
            if not ignore_walls and _wall_blocks(tilemap, col, row, nc, nr):
                continue
            w = tilemap.weight(tile)
            if w >= impassable:
                continue
            nd = cost + w
            if nd < dist.get((nc, nr), float("inf")):
                prev[(nc, nr)] = (col, row)
                heapq.heappush(heap, (nd, nc, nr))
    if reached is None:
        return []
    return _reconstruct(prev, start_col, start_row, reached)


def find_path(tilemap, start_col, start_row):
    """Cheapest path from (start_col, start_row) to the base tile."""
    _pre_query_refresh(tilemap)
    goal = (tilemap.base_col, tilemap.base_row)
    return _dijkstra(tilemap, start_col, start_row, {goal}, ignore_walls=False)


def find_path_ignoring_walls(tilemap, start_col, start_row):
    """Cheapest path to the base treating wall edges as passable — the fallback
    when walls fully enclose the base (the enemy attacks blocking walls en
    route). Identical to ``find_path`` until walls exist (10E)."""
    _pre_query_refresh(tilemap)
    goal = (tilemap.base_col, tilemap.base_row)
    return _dijkstra(tilemap, start_col, start_row, {goal}, ignore_walls=True)


def _goal_tiles(tilemap, predicate):
    return {
        (t.col, t.row)
        for t in tilemap.built_tiles()
        if t.occupant is not None
        and getattr(t.occupant, "alive", False)
        and predicate(t.occupant)
    }


def _find_path_to_goals(tilemap, start_col, start_row, goals):
    """Run a goal-set query; fall back to the base path when no goal exists or
    none is reachable (prototype behaviour)."""
    if not goals:
        return find_path(tilemap, start_col, start_row)
    path = _dijkstra(tilemap, start_col, start_row, goals, ignore_walls=False)
    if not path:
        return find_path(tilemap, start_col, start_row)
    return path


def find_path_to_nearest_economic(tilemap, start_col, start_row):
    """Cheapest path to the nearest alive economy building (Flute Player,
    Meditator, Painter). Falls back to the base path if none exist."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(
        tilemap,
        lambda b: getattr(b, "building_type", None) in _ECONOMY_BUILDING_TYPES,
    )
    return _find_path_to_goals(tilemap, start_col, start_row, goals)


def find_path_to_nearest_defence(tilemap, start_col, start_row):
    """Cheapest path to the nearest alive defence building; base path if none."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(
        tilemap, lambda b: getattr(b, "building_type", None) == "defence")
    return _find_path_to_goals(tilemap, start_col, start_row, goals)


def find_path_to_nearest_building(tilemap, start_col, start_row):
    """Cheapest path to the nearest alive building of any type; base path if
    none exist."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(tilemap, lambda b: True)
    return _find_path_to_goals(tilemap, start_col, start_row, goals)
