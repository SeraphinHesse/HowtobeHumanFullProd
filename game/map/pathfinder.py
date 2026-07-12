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

Large-map perf (see ``game/PERF.md``): the two BASE-goal variants —
``find_path`` (the per-enemy spawn query) and its ``find_path_ignoring_walls``
fallback — no longer run a forward Dijkstra per call. Each walks a SHARED
reverse-Dijkstra flow field seeded at the base (``_build_flow_field``),
cached on the tilemap and rebuilt only when ``TileMap._path_version`` moves
(any weight/blocking mutation), so a wave of hundreds of spawns pays ONE
Dijkstra instead of one each. The goal-set variants stay fresh forward
searches (~one boss per wave; their base-path fallback rides the field).
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


def _build_flow_field(tilemap, ignore_walls):
    """One reverse Dijkstra seeded at the base, expanding outward over the
    TRANSPOSED edge graph. Edge rules are byte-identical to ``_dijkstra``
    (``_neighbors`` 4-connectivity, ``_wall_blocks`` on the edge, the gated
    ``w >= impassable`` skip) — only the direction flips: relaxing neighbour
    ``v`` from a settled ``u`` costs ``weight(u)``, the tile a FORWARD walker
    enters when stepping v→u. Forward path cost is the sum of the weights of
    every tile entered after the start (the start tile itself is never paid),
    so a node's field distance equals the forward start→base ``_dijkstra``
    cost exactly. An impassable tile may still HOLD a distance — it can be a
    query start, exactly as in the forward search — but never expands (no
    forward edge enters it).

    Returns ``(dist, next_step)``: ``dist`` maps every base-reachable
    ``(col, row)`` to its start→base cost; ``next_step`` maps each of them
    except the base to the neighbour one step closer — the shortest-path tree
    every ``find_path`` query walks in O(path length)."""
    dist = {}
    next_step = {}
    if tilemap.base_col is None or tilemap.base_row is None:
        return dist, next_step  # base-less map: nothing is base-reachable
    impassable = tilemap.impassable_weight
    best = {}   # tentative costs, so only a strictly better relax re-parents
    heap = [(0, tilemap.base_col, tilemap.base_row)]
    while heap:
        cost, col, row = heapq.heappop(heap)
        if (col, row) in dist:
            continue
        dist[(col, row)] = cost
        tile = tilemap.get(col, row)
        if tile is None:
            continue
        w = tilemap.weight(tile)
        if w >= impassable:
            continue   # a start-only leaf: no forward edge may enter it
        for nc, nr in _neighbors(col, row, tilemap):
            if (nc, nr) in dist:
                continue
            if not ignore_walls and _wall_blocks(tilemap, col, row, nc, nr):
                continue
            nd = cost + w
            if nd < best.get((nc, nr), float("inf")):
                best[(nc, nr)] = nd
                next_step[(nc, nr)] = (col, row)
                heapq.heappush(heap, (nd, nc, nr))
    return dist, next_step


def _ensure_flow_field(tilemap, ignore_walls):
    """The cached ``(dist, next_step)`` field for ``tilemap``, rebuilt only
    when its ``_path_version`` moved (bumped by every weight/blocking
    mutation — see ``TileMap._bump_path_version``). The walls-respecting and
    walls-ignoring fields cache side by side (each built lazily) so the two
    ``find_path*`` base variants tie-break identically — with no walls the
    builds are the same search, keeping them byte-equal as before. The cache
    lives ON the tilemap as an underscore transient so per-map fields can
    never cross; ``getattr`` guards keep duck-typed test stubs (no counter →
    version 0) working."""
    version = getattr(tilemap, "_path_version", 0)
    cache = getattr(tilemap, "_flow_cache", None)
    if cache is None or cache[0] != version:
        cache = (version, {})
        tilemap._flow_cache = cache
    fields = cache[1]
    if ignore_walls not in fields:
        fields[ignore_walls] = _build_flow_field(tilemap, ignore_walls)
    return fields[ignore_walls]


def _field_path(tilemap, start_col, start_row, ignore_walls):
    """O(path-length) walk down the cached next-step tree, or ``[]`` when the
    start is outside the field (base unreachable)."""
    dist, next_step = _ensure_flow_field(tilemap, ignore_walls)
    cur = (start_col, start_row)
    if cur not in dist:
        return []
    path = [cur]
    while cur in next_step:   # the base is the only field node with no step
        cur = next_step[cur]
        path.append(cur)
    return path


def find_path(tilemap, start_col, start_row):
    """Cheapest path from (start_col, start_row) to the base tile.

    Backed by the shared flow field: after the usual pre-query refresh the
    query is a walk down the cached next-step tree — same cost as the old
    per-query forward Dijkstra, computed once per topology change instead of
    once per enemy. A start outside the field (base unreachable) returns
    ``[]`` so the ``find_path_ignoring_walls`` fallback in ``Enemy.on_spawn``
    still fires."""
    _pre_query_refresh(tilemap)
    return _field_path(tilemap, start_col, start_row, ignore_walls=False)


def find_path_ignoring_walls(tilemap, start_col, start_row):
    """Cheapest path to the base treating wall edges as passable — the fallback
    when walls fully enclose the base (the enemy attacks blocking walls en
    route). Identical to ``find_path`` until walls exist (10E). Also
    field-backed: when the base IS enclosed, every spawn in the wave takes
    this fallback, so it must not regress to a per-enemy Dijkstra."""
    _pre_query_refresh(tilemap)
    return _field_path(tilemap, start_col, start_row, ignore_walls=True)


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
