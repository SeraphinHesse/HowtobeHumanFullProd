"""Defence-range pathfinding coverage — the 10I producer.

Port of the prototype's ``Game.defence_covered_tiles`` (``game.py:583-608``):
the set of ``(col, row)`` tiles inside any alive defender's Chebyshev range
square, which the pathfinder charges ``path_weight_add`` extra to step onto —
so enemies mildly prefer lanes outside tower fire.

Rules (prototype-exact except where noted):

* Toggle: ``BuildingsGlobal.defence_range_pathfinding.enabled`` — off returns
  the empty set, so callers never branch.
* Every ALIVE built occupant with duck-typed ``range_tiles() > 0`` contributes
  its OWN tile plus a Chebyshev square around it (``game/buildings/
  range_shape.py``'s ``offsets(r, "square")``, which excludes the origin —
  this producer is ALWAYS square, deliberately independent of an occupant's
  own ``range_shape()``; see the boost note below; off-map coords are
  harmlessly included — the map lookup ignores them), EXCEPT the Maw Mortar
  line (``building_type == "aoe_defence"``, ``game.py:599-600``). NOTE: the
  mortar exclusion is pathfinding-only — the RANGE overlay still shows it.
* Boost buildings count too, via the SAME real ``range_tiles()``
  (``BoostBuildings.globals.range_tiles``, configurable — the
  booster-range-config feature) that also drives the buff itself. This
  producer intentionally does NOT consult a
  booster's ``range_shape()`` — pathfinding coverage stays a square at the
  configured MAGNITUDE regardless of whether the visual buff/curse uses
  ``"plus"`` or ``"square"`` (matching the prototype's own ``range_tiles = 1``
  pathfinding convention, prior to this feature a hardcoded special case,
  now just the configured magnitude).
* RAW ``range_tiles()`` — a mountain-boosted defender covers its base range
  only (``game.py:601``); the +1 effective range is targeting-side.

This module lives in ``game/buildings`` (it reads the buildings balance and
duck-types occupants); the map layer only ever sees the injected callable, so
its no-``game.buildings``-import rule holds. Cost is O(defenders · r²), never
a full-map scan (large-map invariant); the pathfinder refreshes coverage
before every query (``pathfinder._pre_query_refresh``).

CACHING (perf). "Before every query" means once per enemy spawn — hundreds in
a boss round — and the map-side mirror (``TileMap.refresh_defence_range_
coverage``) only change-detects the RESULT: it could not stop this module from
re-expanding every defender's r² square and re-allocating the whole set first,
so the O(defenders · r²) build, the set copy and the set compare were paid per
query even when nothing had moved. The wired callable
(``wire_defence_coverage``) now splits the work in two: a **signature** —
``_coverage_signature``, O(built defenders), no r² expansion and no set
arithmetic — and the expansion, which runs only when the signature actually
moves. An unchanged signature returns the SAME set object, which the map-side
mirror short-circuits on identity. The signature covers every input the set
depends on (the toggle, and each contributing occupant's tile + raw range), so
it moves on placement, death, sale, movement and a balance-toggle flip alike;
it deliberately does NOT ride ``TileMap._path_version``, which a building death
does not reliably bump (``refresh_building_overwrite_flags`` short-circuits
when the overwrite feature is off). The cached set is never mutated in place —
a signature change builds a fresh one — so a caller holding the previous object
(the mirror's ``_defence_covered_prev``) keeps a valid snapshot.
"""
from . import range_shape


def _contributors(tilemap, buildings_balance):
    """``(col, row, raw_range)`` for every built occupant that contributes
    coverage, or None when the feature is toggled off. O(built tiles) — the
    rule set of the module docstring, evaluated WITHOUT expanding any range
    square, so it is cheap enough to run before every pathfinder query."""
    cfg = buildings_balance["BuildingsGlobal"]["defence_range_pathfinding"]
    if not cfg["enabled"]:
        return None
    out = []
    for tile in tilemap.built_tiles():
        b = tile.occupant
        if b is None or not getattr(b, "alive", False):
            continue
        if getattr(b, "building_type", None) == "aoe_defence":
            continue   # Maw Mortar line: excluded from pathfinding coverage
        rfn = getattr(b, "range_tiles", None)
        if rfn is None:
            continue
        r = int(rfn())   # RAW range — no mountain bonus (game.py:601)
        if r <= 0:
            continue
        out.append((tile.col, tile.row, r))
    return out


def _coverage_signature(tilemap, buildings_balance):
    """A hashable, order-insensitive digest of everything the coverage set
    depends on — None when the feature is off. ``built_tiles()`` comes off a
    set index, so its order is not stable: a frozenset, not a list."""
    contributors = _contributors(tilemap, buildings_balance)
    if contributors is None:
        return None
    return frozenset(contributors)


def _expand(contributors):
    """The coverage set for a ``_contributors`` result. O(defenders · r²)."""
    covered = set()
    for col, row, r in contributors:
        covered.add((col, row))   # the occupant's own tile too
        for dc, dr in range_shape.offsets(r, "square"):
            covered.add((col + dc, row + dr))
    return covered


def defence_covered_tiles(tilemap, buildings_balance):
    """The coverage set under the current buildings, or ``set()`` when the
    ``defence_range_pathfinding`` toggle is off. Uncached — always a freshly
    built set; the per-query path goes through ``wire_defence_coverage``."""
    contributors = _contributors(tilemap, buildings_balance)
    if contributors is None:
        return set()
    return _expand(contributors)


def wire_defence_coverage(tilemap, buildings_balance):
    """Inject the coverage producer + weight add into ``tilemap`` (called once
    per run by the host). The map layer stays import-free of this package —
    it only holds the callable + the integer.

    The injected callable is the CACHED one (see the module docstring): it
    re-expands the range squares only when its signature moves, and otherwise
    hands back the identical set object it returned last time."""
    cache = {}   # {"sig": …, "set": …} — populated on the first call

    def produce():
        sig = _coverage_signature(tilemap, buildings_balance)
        if cache and cache["sig"] == sig:
            return cache["set"]
        covered = set() if sig is None else _expand(sig)
        cache["sig"] = sig
        cache["set"] = covered
        return covered

    tilemap._defence_coverage_fn = produce
    tilemap._defence_range_add = buildings_balance["BuildingsGlobal"][
        "defence_range_pathfinding"]["path_weight_add"]
