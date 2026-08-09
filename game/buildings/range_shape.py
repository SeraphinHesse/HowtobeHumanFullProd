"""Pure tile-offset geometry for a building's range.

Shared by every range consumer that used to duplicate this loop: the RANGE
overlay (``game/ui/overlays.py``), the panel's selection highlight
(``game/ui/building_ui.py``), defence-range pathfinding coverage
(``game/buildings/coverage.py``), and a booster's own buff/curse adjacency
(``game/buildings/boost.py``) — see ``game/buildings/CLAUDE.md``.
"""


def offsets(n, shape="square"):
    """(dc, dr) tile deltas for a range of magnitude ``n``, excluding the
    origin. ``shape="square"`` is the full Chebyshev square (the long-
    standing defence-range convention); ``shape="plus"`` is cardinal arms
    only, ``n`` tiles out in each of the 4 directions."""
    if n <= 0:
        return []
    if shape == "plus":
        out = []
        for i in range(1, n + 1):
            out += [(0, -i), (0, i), (-i, 0), (i, 0)]
        return out
    return [(dc, dr) for dc in range(-n, n + 1) for dr in range(-n, n + 1)
            if (dc, dr) != (0, 0)]
