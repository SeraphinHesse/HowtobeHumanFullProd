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
"""
from . import range_shape


def defence_covered_tiles(tilemap, buildings_balance):
    """The coverage set under the current buildings, or ``set()`` when the
    ``defence_range_pathfinding`` toggle is off."""
    cfg = buildings_balance["BuildingsGlobal"]["defence_range_pathfinding"]
    if not cfg["enabled"]:
        return set()
    covered = set()
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
        covered.add((tile.col, tile.row))   # the occupant's own tile too
        for dc, dr in range_shape.offsets(r, "square"):
            covered.add((tile.col + dc, tile.row + dr))
    return covered


def wire_defence_coverage(tilemap, buildings_balance):
    """Inject the coverage producer + weight add into ``tilemap`` (called once
    per run by the host). The map layer stays import-free of this package —
    it only holds the callable + the integer."""
    tilemap._defence_coverage_fn = (
        lambda: defence_covered_tiles(tilemap, buildings_balance))
    tilemap._defence_range_add = buildings_balance["BuildingsGlobal"][
        "defence_range_pathfinding"]["path_weight_add"]
