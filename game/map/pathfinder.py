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

FOOTPRINTS (ER-2). Every query takes a trailing ``footprint`` (N, default 1).
A size-N unit anchored at ``(c, r)`` occupies the N×N block
``{(c+i, r+j) | 0 <= i,j < N}`` — the anchor is the block's MIN corner and the
body extends right and down (the repo's existing 2×2 convention: ``_find_2x2``,
the ``start_area`` marker, unlock chunks). It may stand there only if the WHOLE
block is in bounds and under ``impassable_weight`` and no live wall sits on an
INTERNAL edge of the block; stepping to a 4-adjacent anchor also clears the
whole leading FACE (N edges, not one). Entering a block costs the worst weight
under the body. A goal is reached when the block COVERS it, not when the anchor
sits on it — so the flow field is seeded at every base-covering anchor and
``_dijkstra`` expands its goal set the same way (a 2×2 standing beside the hole
IS on the hole; requiring it to anchor there would strand it whenever the block
at the base is not clear). Paths are sequences of ANCHORS throughout.

N = 1 collapses every one of those rules to its pre-ER-2 expression — the block
is the tile, there are no internal edges, the face is the single crossed edge,
the block weight is the tile weight and the goal set is the goal — so the
single-tile path is unchanged. The flow-field cache key is
``(ignore_walls, footprint, profile_key)``: still ONE Dijkstra per topology
change per (footprint, weight profile) — NEVER one per enemy (``game/PERF.md``).

WEIGHT PROFILES (Chunk 3). Every query below also takes a trailing
``cond_weights`` (``None`` by default — "use the map's own
``TileConditions.path_weights``", today's behaviour). A caller with a
per-enemy-type profile (``EnemyTypes.<type>.condition_path_weights``) passes
its own ``{forest, mountain, pond}`` mapping instead, so a raider can be tuned
to route through terrain a walker would avoid. The flow field caches one field
PER DISTINCT profile: ``_ensure_flow_field`` derives a hashable
``profile_key`` (``None``, or the ``(forest, mountain, pond)`` tuple) from
``cond_weights`` for the cache key, so identical profiles — the shipped seed
has every type identical to the map default — collapse onto ONE cached field,
never one per enemy.
"""
import heapq


# Occupant building_type values counted as "economy" (prototype pathfinder.py:36).
_ECONOMY_BUILDING_TYPES = {"economic", "meditator", "painter"}

# NE-0/D1: every ATTACK-CAPABLE building — the "defence" hunt category. It used
# to be the single literal ``building_type == "defence"``, i.e. the Defender
# only, which left the three later attack buildings (mortar, Storm Priest, Sun
# Scorcher) invisible to a hunter sent to kill defences. Widening it is a
# DELIBERATE, user-approved balance change and it is SHARED: SiegeCannon already
# ships ``hunts: "defence"``, so from NE-0 it hunts these four from its existing
# ``start_round: 14`` onward.
_ATTACK_BUILDING_TYPES = {"defence", "aoe_defence", "storm_priest",
                          "sun_scorcher"}

# NE-0/D2: every NON-economy, NON-boost, NON-base building — the "structure"
# hunt category (the attack set above plus the two structure buildings). Named
# for the thing a hunter wants to knock down to open a route: blockers and wall
# builders are the common case, but the category is deliberately not limited to
# them. Keep it in sync with game/buildings' BUILDING_TYPE constants: the whole
# roster is this set + _ECONOMY_BUILDING_TYPES + the three boost_* types + base.
# Spelled out literally rather than derived from the set above: the two
# categories answer different questions and one is not defined as the other
# plus two, so a future attack-capable type must be added to BOTH on purpose.
_STRUCTURE_BUILDING_TYPES = {"blocker", "wall_builder", "defence",
                             "aoe_defence", "storm_priest", "sun_scorcher"}


def _pre_query_refresh(tilemap):
    """Refresh damage-weight reductions, defence-range coverage (when core has
    wired a coverage function), and the buildings-overwrite-tileweights flag
    set before a query — the prototype's ``_apply_damage_weights`` plus its
    rework-era sibling. All three producers are dormant/short-circuited on a
    tilemap that doesn't carry them (headless stubs, 9C-era fixtures) via the
    same guarded ``getattr`` style."""
    refresh = getattr(tilemap, "refresh_damage_weight_reductions", None)
    if refresh is not None:
        refresh()
    fn = getattr(tilemap, "_defence_coverage_fn", None)
    if fn is not None and hasattr(tilemap, "refresh_defence_range_coverage"):
        tilemap.refresh_defence_range_coverage(fn())
    refresh_overwrite = getattr(tilemap, "refresh_building_overwrite_flags", None)
    if refresh_overwrite is not None:
        refresh_overwrite()


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


# -- footprints (ER-2): the ONE definition of the N×N block convention -----
# Public, not underscored: game/enemies/components.py + spawner.py import them,
# so the anchor/passability rules are never re-derived anywhere else.

def block_tiles(col, row, footprint=1):
    """The tiles a size-N unit anchored at (col, row) occupies. The anchor is
    the block's MIN corner: the block extends right and down. N=1 -> just the
    anchor tile."""
    return [(col + i, row + j)
            for j in range(footprint) for i in range(footprint)]


def block_covers(col, row, footprint, tc, tr):
    """True if tile (tc, tr) lies inside the block anchored at (col, row) — the
    goal test: a unit has REACHED a goal when its body covers it."""
    return (col <= tc < col + footprint) and (row <= tr < row + footprint)


def internal_edges(col, row, footprint=1):
    """Every edge BETWEEN two tiles of the block (N=1 -> none). A live wall on
    one of these runs through the unit's body, so it may not stand here."""
    edges = []
    for j in range(footprint):
        for i in range(footprint):
            if i + 1 < footprint:
                edges.append((col + i, row + j, col + i + 1, row + j))
            if j + 1 < footprint:
                edges.append((col + i, row + j, col + i, row + j + 1))
    return edges


def face_edges(col, row, ncol, nrow, footprint=1):
    """The edges a size-N body sweeps stepping from anchor (col,row) to the
    4-adjacent anchor (ncol,nrow) — the whole leading face, not one edge.
    Symmetric in the two anchors (wall keys are order-independent), so the
    forward ``_dijkstra`` and the reverse ``_build_flow_field`` share it and
    their edge rules stay identical. N=1 -> exactly the single edge
    (col,row)-(ncol,nrow), i.e. today's ``_wall_blocks`` arguments."""
    dc, dr = ncol - col, nrow - row
    if abs(dc) + abs(dr) != 1:          # defensive: only cardinal steps exist
        return [(col, row, ncol, nrow)]
    out = []
    for k in range(footprint):
        if dc == 1:
            out.append((col + footprint - 1, row + k, col + footprint, row + k))
        elif dc == -1:
            out.append((col, row + k, col - 1, row + k))
        elif dr == 1:
            out.append((col + k, row + footprint - 1, col + k, row + footprint))
        else:
            out.append((col + k, row, col + k, row - 1))
    return out


def block_passable(tilemap, col, row, footprint=1, ignore_walls=False,
                   cond_weights=None):
    """Every tile of the block is in bounds and under the impassable threshold,
    and (unless ignore_walls) no live wall sits on an internal edge. N=1
    collapses to ``tile is not None and weight(tile) < impassable``."""
    return _block_entry_weight(
        tilemap, col, row, footprint, ignore_walls, cond_weights) is not None


def block_weight(tilemap, col, row, footprint=1, cond_weights=None):
    """Cost of ENTERING the block: the worst tile under the body, so a 2×2
    avoids a pond even if only one of its four tiles is the pond. N=1 -> exactly
    ``tilemap.weight(tilemap.get(col, row), cond_weights)``."""
    if footprint == 1:
        return tilemap.weight(tilemap.get(col, row), cond_weights)
    return max(tilemap.weight(tilemap.get(c, r), cond_weights)
               for c, r in block_tiles(col, row, footprint))


def _block_entry_weight(tilemap, col, row, footprint=1, ignore_walls=False,
                        cond_weights=None):
    """``block_weight`` if the body may stand here, else None — ``block_passable``
    and ``block_weight`` FUSED into one pass. The Dijkstra relax needs both for
    every candidate anchor, and each is a get+weight sweep over the block; run
    apart they walk it twice. At N=1 this is one ``get`` + one ``weight``, i.e.
    exactly the pre-ER-2 inner loop — the flow field rebuilds on every
    building placement / wall change / tile unlock, so this stays hot
    (``game/PERF.md``)."""
    impassable = tilemap.impassable_weight
    if footprint == 1:
        tile = tilemap.get(col, row)
        if tile is None:
            return None
        w = tilemap.weight(tile, cond_weights)
        return None if w >= impassable else w
    worst = 0
    for c, r in block_tiles(col, row, footprint):
        tile = tilemap.get(c, r)
        if tile is None:
            return None
        w = tilemap.weight(tile, cond_weights)
        if w >= impassable:
            return None
        if w > worst:
            worst = w
    if not ignore_walls:
        for e in internal_edges(col, row, footprint):
            if _wall_blocks(tilemap, *e):
                return None
    return worst


def _face_blocked(tilemap, col, row, ncol, nrow, footprint=1):
    if footprint == 1:      # the face IS the single crossed edge — no list
        return _wall_blocks(tilemap, col, row, ncol, nrow)
    return any(_wall_blocks(tilemap, *e)
               for e in face_edges(col, row, ncol, nrow, footprint))


def _expand_goals(goals, footprint):
    """The anchor set whose block covers at least one goal tile. N=1 -> goals."""
    return {(gc - i, gr - j) for gc, gr in goals
            for i in range(footprint) for j in range(footprint)}


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


def _dijkstra(tilemap, start_col, start_row, goals, ignore_walls, footprint=1,
              cond_weights=None):
    """Cheapest ANCHOR path from start to the nearest anchor whose block covers
    a tile in `goals`, or [] if none is reachable. Assumes the caller already
    ran ``_pre_query_refresh``. Only anchors a size-N body can legally occupy
    are ever relaxed, so a covering anchor it cannot stand on is never returned;
    the one exception is a start that is already a goal anchor (mirroring
    today's ``find_path(tm, base_col, base_row) == [(base)]``)."""
    goals = _expand_goals(goals, footprint)
    # Hot loop: hoist every invariant and take the N=1 branch inline. The helper
    # calls (one per node + one per EDGE) are pure overhead at footprint 1 and
    # cost more than the work they do — see game/PERF.md.
    single = footprint == 1
    impassable = tilemap.impassable_weight
    tm_get = tilemap.get
    tm_weight = tilemap.weight
    dist = {}
    prev = {}
    # `best` is the TENTATIVE distance map, and keeping it separate from `dist`
    # (the SETTLED one) is load-bearing, exactly as in _build_flow_field. Guard
    # the relax on `dist` instead and every relaxation of an unsettled node
    # passes — `dist.get()` is inf until the node settles — so a LATER, WORSE
    # relaxation happily overwrites `prev` with a worse parent. The goal still
    # settles at the right cost (the heap pops it in order), but `_reconstruct`
    # then walks the clobbered back-pointers and hands back a path that is not
    # the one Dijkstra costed: on a pond board this returned a 23-cost route to
    # a goal it had already reached at cost 12, doubling back through the water.
    # That is a large part of the boss's "wandering" (BossPathfindingPLAN #3).
    best = {(start_col, start_row): 0}
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
            if not ignore_walls:
                if single:
                    if _wall_blocks(tilemap, col, row, nc, nr):
                        continue
                elif _face_blocked(tilemap, col, row, nc, nr, footprint):
                    continue
            if single:
                tile = tm_get(nc, nr)
                if tile is None:
                    continue
                w = tm_weight(tile, cond_weights)
                if w >= impassable:
                    continue
            else:
                w = _block_entry_weight(tilemap, nc, nr, footprint,
                                        ignore_walls, cond_weights)
                if w is None:
                    continue
            nd = cost + w
            if nd < best.get((nc, nr), float("inf")):
                best[(nc, nr)] = nd
                prev[(nc, nr)] = (col, row)
                heapq.heappush(heap, (nd, nc, nr))
    if reached is None:
        return []
    return _reconstruct(prev, start_col, start_row, reached)


def _build_flow_field(tilemap, ignore_walls, footprint=1, cond_weights=None):
    """One reverse Dijkstra seeded at EVERY base-covering anchor, expanding
    outward over the TRANSPOSED edge graph. Edge rules are byte-identical to
    ``_dijkstra`` (``_neighbors`` 4-connectivity, ``_face_blocked`` on the
    swept face, the gated ``block_passable`` skip) — only the direction flips:
    relaxing neighbour ``v`` from a settled ``u`` costs ``block_weight(u)``,
    the block a FORWARD walker enters when stepping v→u; face edges are
    symmetric, so the two searches agree. Forward path cost is the sum of the
    weights of every block entered after the start (the start block itself is
    never paid), so a node's field distance equals the forward start→base
    ``_dijkstra`` cost exactly. An anchor whose block is not passable may still
    HOLD a distance — it can be a query start, exactly as in the forward search
    — but never expands (no forward edge may enter it).

    The multi-source seed is what lets a size-N body REACH the base: it has
    arrived once its block covers the hole, so every anchor whose block covers
    it starts at distance 0. N=1 -> the single base tile, i.e. today's seed.

    Returns ``(dist, next_step)``: ``dist`` maps every base-reachable ANCHOR to
    its start→base cost; ``next_step`` maps each of them except the seeds to the
    anchor one step closer — the shortest-path tree every ``find_path`` query
    walks in O(path length)."""
    dist = {}
    next_step = {}
    if tilemap.base_col is None or tilemap.base_row is None:
        return dist, next_step  # base-less map: nothing is base-reachable
    seeds = [(tilemap.base_col - i, tilemap.base_row - j)
             for i in range(footprint) for j in range(footprint)]
    # Seeds are the goal — cost 0, and NOTHING may re-parent them. Pre-seeding
    # `best` is load-bearing, not tidiness: the seeds are 4-adjacent to each
    # other for N>1, so the first one popped would otherwise relax its siblings
    # (still absent from `dist`, `best` = inf, and any nd >= 0) and write a
    # back-pointer INTO itself. The sibling's `dist` would still settle to 0,
    # but the bogus `next_step` survives — and `_field_path` would then walk a
    # unit that already covers the base onward to the lex-min covering anchor
    # instead of stopping. N=1 has one seed and no sibling, hence unaffected.
    best = {s: 0 for s in seeds}   # only a STRICTLY better relax re-parents
    heap = [(0, c, r) for c, r in seeds]
    heapq.heapify(heap)
    # Hot loop — see _dijkstra: hoist the invariants, inline the N=1 branch.
    # This rebuilds on EVERY building placement / wall change / tile unlock.
    single = footprint == 1
    impassable = tilemap.impassable_weight
    tm_get = tilemap.get
    tm_weight = tilemap.weight
    while heap:
        cost, col, row = heapq.heappop(heap)
        if (col, row) in dist:
            continue
        dist[(col, row)] = cost
        if single:
            tile = tm_get(col, row)
            if tile is None:
                continue   # a start-only leaf: no forward edge may enter it
            w = tm_weight(tile, cond_weights)
            if w >= impassable:
                continue
        else:
            w = _block_entry_weight(tilemap, col, row, footprint, ignore_walls,
                                    cond_weights)
            if w is None:
                continue
        for nc, nr in _neighbors(col, row, tilemap):
            if (nc, nr) in dist:
                continue
            if not ignore_walls:
                if single:
                    if _wall_blocks(tilemap, col, row, nc, nr):
                        continue
                elif _face_blocked(tilemap, col, row, nc, nr, footprint):
                    continue
            nd = cost + w
            if nd < best.get((nc, nr), float("inf")):
                best[(nc, nr)] = nd
                next_step[(nc, nr)] = (col, row)
                heapq.heappush(heap, (nd, nc, nr))
    return dist, next_step


def _ensure_flow_field(tilemap, ignore_walls, footprint=1, cond_weights=None):
    """The cached ``(dist, next_step)`` field for ``tilemap``, rebuilt only
    when its ``_path_version`` moved (bumped by every weight/blocking
    mutation — see ``TileMap._bump_path_version``). Fields cache side by side
    keyed on ``(ignore_walls, footprint, profile_key)`` — ``profile_key`` is
    ``None`` or the hashable ``(forest, mountain, pond)`` tuple derived from
    ``cond_weights`` (a dict is not hashable, so the cache key derives its own
    tuple rather than storing the dict itself). IDENTICAL profiles collapse
    onto ONE key regardless of which caller supplied them — with every
    shipped ``EnemyTypes.<type>.condition_path_weights`` seeded equal to the
    map's own ``TileConditions.path_weights``, every type shares one field,
    exactly as before this profile seam existed. THE PERF INVARIANT
    (``game/PERF.md``): one Dijkstra per topology change per (footprint,
    profile), never one per enemy — at most a handful of distinct profiles
    ever exist. The cache lives ON the tilemap as an underscore transient so
    per-map fields can never cross; ``getattr`` guards keep duck-typed test
    stubs (no counter → version 0) working."""
    version = getattr(tilemap, "_path_version", 0)
    cache = getattr(tilemap, "_flow_cache", None)
    if cache is None or cache[0] != version:
        cache = (version, {})
        tilemap._flow_cache = cache
    fields = cache[1]
    profile_key = (None if cond_weights is None else
                  (cond_weights["forest"], cond_weights["mountain"],
                   cond_weights["pond"]))
    key = (ignore_walls, footprint, profile_key)
    if key not in fields:
        fields[key] = _build_flow_field(tilemap, ignore_walls, footprint,
                                        cond_weights)
    return fields[key]


def _field_path(tilemap, start_col, start_row, ignore_walls, footprint=1,
                cond_weights=None):
    """O(path-length) walk down the cached next-step tree, or ``[]`` when the
    start is outside the field (base unreachable)."""
    dist, next_step = _ensure_flow_field(tilemap, ignore_walls, footprint,
                                         cond_weights)
    cur = (start_col, start_row)
    if cur not in dist:
        return []
    path = [cur]
    while cur in next_step:   # a seed is the only field node with no step
        cur = next_step[cur]
        path.append(cur)
    return path


def find_path(tilemap, start_col, start_row, footprint=1, cond_weights=None):
    """Cheapest path from the anchor (start_col, start_row) to the base tile —
    for a size-N unit, until its BLOCK covers the base (see the module
    docstring); N=1 is today's path to the base tile itself.

    Backed by the shared flow field: after the usual pre-query refresh the
    query is a walk down the cached next-step tree — same cost as the old
    per-query forward Dijkstra, computed once per topology change (per
    footprint) instead of once per enemy. A start outside the field (base
    unreachable) returns ``[]`` so the ``find_path_ignoring_walls`` fallback in
    ``Enemy.on_spawn`` still fires. ``cond_weights`` (Chunk 3): the caller's
    per-enemy-type weight profile, ``None`` for the map default."""
    _pre_query_refresh(tilemap)
    return _field_path(tilemap, start_col, start_row, ignore_walls=False,
                       footprint=footprint, cond_weights=cond_weights)


def find_path_ignoring_walls(tilemap, start_col, start_row, footprint=1,
                             cond_weights=None):
    """Cheapest path to the base treating wall edges as passable — the fallback
    when walls fully enclose the base (the enemy attacks blocking walls en
    route). Identical to ``find_path`` until walls exist (10E). Also
    field-backed: when the base IS enclosed, every spawn in the wave takes
    this fallback, so it must not regress to a per-enemy Dijkstra."""
    _pre_query_refresh(tilemap)
    return _field_path(tilemap, start_col, start_row, ignore_walls=True,
                       footprint=footprint, cond_weights=cond_weights)


def _goal_tiles(tilemap, predicate, exclude=None):
    """The goal set for a hunt: every built tile whose occupant is alive and
    satisfies ``predicate``.

    NE-2 adds ``exclude`` — an optional container of ``(col, row)`` tiles to
    drop from the set BEFORE the predicate runs. It is the seam the Digger's
    exclusive claim rides on (a tile another live Digger has already committed
    to is simply not a candidate), and it is deliberately a plain tile filter
    rather than a second predicate: the caller knows tiles, not occupants, and
    ``None`` keeps every existing query byte-identical."""
    return {
        (t.col, t.row)
        for t in tilemap.built_tiles()
        if t.occupant is not None
        and getattr(t.occupant, "alive", False)
        and (exclude is None or (t.col, t.row) not in exclude)
        and predicate(t.occupant)
    }


def _find_path_to_goals(tilemap, start_col, start_row, goals, footprint=1,
                        cond_weights=None):
    """Run a goal-set query; fall back to the base path when no goal exists or
    none is reachable (prototype behaviour)."""
    if not goals:
        return find_path(tilemap, start_col, start_row, footprint, cond_weights)
    path = _dijkstra(tilemap, start_col, start_row, goals, ignore_walls=False,
                     footprint=footprint, cond_weights=cond_weights)
    if not path:
        return find_path(tilemap, start_col, start_row, footprint, cond_weights)
    return path


def _nearest_goal_tile(goals, start_col, start_row, min_distance=0):
    """The tile in ``goals`` GEOMETRICALLY nearest to the start, or ``None``
    when ``goals`` is empty (BP-3 / decision D3, generalised — Chunk 4 — from
    the boss-only ``nearest_non_base_building_tile`` into a predicate-free
    helper every hunt query shares).

    Target CHOICE is plain squared distance — what the player sees and expects
    — deliberately NOT the weighted Dijkstra cost that picks the *route*. One
    weighted search used to do both jobs and the two requirements fight: terrain
    weight, defence-range coverage (+1/tile) and the round-11 damage discount
    (×0.5) all bend the cost field, so the "nearest" building could be clear
    across the map. Ties break lexicographically, so the pick is deterministic
    for a given board.

    ``min_distance`` (Digger fix, default 0 — every existing caller
    byte-identical): when positive, restrict the pool to goals at CHEBYSHEV
    distance ``>= min_distance`` from the start before picking the nearest;
    if nothing clears that bar, fall back to the nearest of the FULL set. A
    Chebyshev distance is never negative, so ``min_distance=0`` keeps every
    goal and changes nothing."""
    if not goals:
        return None
    pool = goals
    if min_distance > 0:
        far = {g for g in goals
               if max(abs(g[0] - start_col), abs(g[1] - start_row)) >= min_distance}
        if far:
            pool = far
    return min(pool, key=lambda g: ((g[0] - start_col) ** 2
                                    + (g[1] - start_row) ** 2, g[0], g[1]))


def _hunt(tilemap, start_col, start_row, goals, footprint=1,
         cond_weights=None, min_distance=0):
    """The one hunt-query body (Chunk 4), shared by every prey-hunting
    variant below: choose the nearest goal by squared geometric distance,
    route to it by the ordinary weighted ``_dijkstra`` (D3 — choose by
    distance, route by cost: terrain weight, defence-range coverage and the
    damage discount all bend the cost field, so the "nearest" target by cost
    can be clear across the map from the "nearest" target by distance). If
    that route turns out to be unreachable, one multi-goal search over the
    WHOLE goal set finds any other reachable one before giving up — so a
    walled-off target can never force an early fallback. With NO goals at
    all, falls back to the base path — for
    ``find_path_to_nearest_non_base_building`` this is the ONE way the
    boss's ``goal_is_base`` ever becomes True; extracted verbatim from that
    function (formerly the whole of its body) so ``find_path_to_nearest_
    economic``/``_defence`` get the identical distance-choice fix instead of
    the cost-choice bug they shipped dormant with.

    ``min_distance`` (Digger fix) is threaded ONLY into the target CHOICE
    (``_nearest_goal_tile``) — the unreachable-target fallback still searches
    the whole goal set, because reachability always wins over a distance
    preference, exactly like every other fallback in this module."""
    if not goals:
        return find_path(tilemap, start_col, start_row, footprint, cond_weights)
    target = _nearest_goal_tile(goals, start_col, start_row, min_distance)
    path = _dijkstra(tilemap, start_col, start_row, {target},
                     ignore_walls=False, footprint=footprint,
                     cond_weights=cond_weights)
    if path:
        return path
    return _find_path_to_goals(tilemap, start_col, start_row, goals, footprint,
                               cond_weights)


def find_path_to_nearest_economic(tilemap, start_col, start_row, footprint=1,
                                  cond_weights=None):
    """Cheapest path to the nearest alive economy building (Flute Player,
    Meditator, Painter), by geometric distance (Chunk 4 — was cost-choice via
    ``_find_path_to_goals`` alone, a bug that let a cost-cheaper building beat
    a geometrically-closer pond building; dormant until Raider.hunts ==
    "economic" armed it). Falls back to the base path if none exist."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(
        tilemap,
        lambda b: getattr(b, "building_type", None) in _ECONOMY_BUILDING_TYPES,
    )
    return _hunt(tilemap, start_col, start_row, goals, footprint, cond_weights)


def find_path_to_nearest_defence(tilemap, start_col, start_row, footprint=1,
                                 cond_weights=None):
    """Cheapest path to the nearest alive ATTACK-CAPABLE building, by geometric
    distance (Chunk 4, same distance-choice fix as the economic variant
    above; dormant until SiegeCannon.hunts == "defence" armed it). Falls back
    to the base path if none exist.

    NE-0/D1: the goal predicate is ``_ATTACK_BUILDING_TYPES`` — Defender,
    mortar (``aoe_defence``), Storm Priest and Sun Scorcher — not the single
    literal ``"defence"`` it shipped with. A deliberate, user-approved balance
    change to an EXISTING type: SiegeCannon (``hunts: "defence"``) hunts all
    four from its existing ``start_round: 14`` onward."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(
        tilemap,
        lambda b: getattr(b, "building_type", None) in _ATTACK_BUILDING_TYPES,
    )
    return _hunt(tilemap, start_col, start_row, goals, footprint, cond_weights)


def find_path_to_nearest_structure(tilemap, start_col, start_row, footprint=1,
                                   cond_weights=None, exclude=None,
                                   min_distance=0):
    """Cheapest path to the nearest alive STRUCTURE — every non-economy,
    non-boost, non-base building (``_STRUCTURE_BUILDING_TYPES``: blocker,
    wall builder, and the four attack-capable types) — by geometric distance,
    routed by weighted cost through the shared ``_hunt`` body like every other
    prey query. Falls back to the base path if none exist.

    NE-0/D2. The ``"structure"`` hunt category, added for the Digger (NE-2) but
    landed a phase early so it rides the same reviewed helper the other hunts
    do. Blockers and wall builders are the common case in practice; the
    category is deliberately not restricted to those two.

    NE-2 adds ``exclude``: ``(col, row)`` tiles to drop from the goal set. This
    is the ONE hunt query that takes it, because the Digger is the one type
    with an exclusive claim — another live Digger's committed target is not a
    candidate for this one. ``None`` (every other caller, including
    ``_HUNT_QUERIES``' generic dispatch) is byte-identical to NE-0.

    ``min_distance`` (Digger fix, default 0): forwarded straight to ``_hunt``'s
    target-CHOICE preference — see ``_nearest_goal_tile``. This is also the
    ONE hunt query that takes it, since ``find_path_to_nearest_structure`` is
    itself the Digger's only caller today; every other hunt category stays at
    the default and is unaffected.

    **Caution — an empty goal set still falls back to the BASE path** (``_hunt``
    does, for every hunt). A caller that must never march at the hole when
    exclusion empties the board — the Digger, which "only builds towards
    buildings" — has to detect that itself: ``PathAgent.adopt_goal`` flips
    ``goal_is_base`` True on exactly that path, which is what
    ``BurrowAgent.retarget`` reads to stand down instead."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(
        tilemap,
        lambda b: getattr(b, "building_type", None) in _STRUCTURE_BUILDING_TYPES,
        exclude,
    )
    return _hunt(tilemap, start_col, start_row, goals, footprint, cond_weights,
                min_distance)


def find_path_to_nearest_building(tilemap, start_col, start_row, footprint=1,
                                  cond_weights=None):
    """Cheapest path to the nearest alive building of any type; base path if
    none exist."""
    _pre_query_refresh(tilemap)
    goals = _goal_tiles(tilemap, lambda b: True)
    return _find_path_to_goals(tilemap, start_col, start_row, goals, footprint,
                               cond_weights)


def _non_base_goals(tilemap):
    """Every alive building tile EXCEPT the base — the boss's hunting ground.

    Keyed on ``building_type != "base"``, the same duck-typed occupant contract
    the rest of this module reads (and the same key the prototype excludes the
    hole by), never a comparison against ``base_col``/``base_row``."""
    return _goal_tiles(
        tilemap, lambda b: getattr(b, "building_type", None) != "base")


def nearest_non_base_building_tile(tilemap, start_col, start_row):
    """The alive non-base building tile GEOMETRICALLY nearest to the start, or
    ``None`` when the board is clear (BP-3 / decision D3). Thin wrapper over
    the generalised ``_nearest_goal_tile`` (Chunk 4) — kept under its
    original name because ``test_boss.py``/``test_pathfinder.py`` reference
    it directly."""
    return _nearest_goal_tile(_non_base_goals(tilemap), start_col, start_row)


def find_path_to_nearest_spawn(tilemap, start_col, start_row, footprint=1,
                               cond_weights=None):
    """Cheapest path from (start_col, start_row) to the nearest SPAWNING tile —
    the kidnapper's route home. ``[]`` when there is no spawn tile at all, or
    none reachable.

    ``ignore_walls=True`` is deliberate: a carrier is inert (``PathAgent`` no
    longer scans for blockers or walls once ``carrying`` is set — see
    ``game/enemies/CLAUDE.md``), so a wall it cannot break must never be able
    to trap it on the way home. Buildings are traversable weights, never
    ``impassable_weight``, so a live occupant cannot trap it either.

    A fresh ``_dijkstra`` like every other goal-set variant, NOT flow-field
    backed: a kidnap fires at most once per building kill, so this stays well
    inside the one-Dijkstra-per-topology-change invariant (``game/PERF.md``)
    rather than needing its own cached field."""
    _pre_query_refresh(tilemap)
    goals = {(t.col, t.row) for t in tilemap.spawning_tiles()}
    if not goals:
        return []
    return _dijkstra(tilemap, start_col, start_row, goals,
                     ignore_walls=True, footprint=footprint,
                     cond_weights=cond_weights)


def find_path_to_nearest_non_base_building(tilemap, start_col, start_row,
                                           footprint=1, cond_weights=None):
    """Route to the nearest alive NON-BASE building; the base path when the
    board is clear (BP-2 / decision D2 — the boss turns on the hole ONLY once
    nothing else is left standing).

    ``find_path_to_nearest_building`` cannot do this job: its goal predicate is
    ``lambda b: True``, so the base sits in the goal set, and
    ``Pathfinding.content_weights.base_building`` is **0** — cheaper than any
    real building (1–2). A weighted search therefore walks past the buildings it
    was sent to destroy and stops at the hole. Excluding the base from the goal
    set is the whole fix; the fallback to ``find_path`` when no goal remains is
    the ONE way the boss's ``goal_is_base`` ever becomes True.

    D3 — **choose by distance, route by cost.** The victim is picked
    geometrically (above), then reached by the ordinary weighted ``_dijkstra``,
    so the boss still walks AROUND a pond rather than through it while still
    hunting the building the player would call nearest. If that victim turns out
    to be unreachable, one multi-goal search over the whole non-base set finds
    any other reachable victim before we give up and head for the hole — so a
    walled-off building can never send the boss to the base early.

    Fresh Dijkstras (~one per boss per re-path), like the other goal-set
    variants — the ``game/PERF.md`` flow-field invariant is untouched.

    Chunk 4: the body is now the shared ``_hunt`` helper — byte-identical to
    the pre-Chunk-4 version (pinned by ``test_boss.py``'s existing fixtures)."""
    _pre_query_refresh(tilemap)
    goals = _non_base_goals(tilemap)
    return _hunt(tilemap, start_col, start_row, goals, footprint, cond_weights)
