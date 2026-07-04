"""SpatialGrid tests (E-31): radius + Chebyshev queries, no full scan, stable
order. Pure Python — no pygame."""
import math
import unittest

from engine.physics import SpatialGrid


class _T:
    def __init__(self, wx, wy):
        self.wx = wx
        self.wy = wy

    @property
    def world_pos(self):
        return (self.wx, self.wy)


class Obj:
    """Minimal grid citizen: exposes obj.transform.world_pos."""

    def __init__(self, name, wx, wy):
        self.name = name
        self.transform = _T(wx, wy)


def brute_radius(objs, center, radius):
    cx, cy = center
    return [o for o in objs
            if math.hypot(o.transform.wx - cx, o.transform.wy - cy) <= radius]


def brute_chebyshev(objs, center, r):
    ccol, crow = center
    return [o for o in objs
            if max(abs(round(o.transform.wx) - ccol),
                   abs(round(o.transform.wy) - crow)) <= r]


class TestRadius(unittest.TestCase):
    def test_radius_exact_boundary(self):
        grid = SpatialGrid(cell_size=1.0)
        a = Obj("a", 0.0, 0.0)
        b = Obj("b", 2.0, 0.0)   # exactly on radius 2 boundary → included
        c = Obj("c", 3.0, 0.0)   # outside
        for o in (a, b, c):
            grid.insert(o)
        got = grid.query_radius((0, 0), 2.0)
        self.assertEqual(got, [a, b])

    def test_radius_matches_brute_force(self):
        grid = SpatialGrid(cell_size=1.5)
        objs = [Obj(str(i), (i * 1.3) % 10, (i * 2.7) % 10) for i in range(40)]
        for o in objs:
            grid.insert(o)
        for center in [(0, 0), (5, 5), (9.5, 1.2)]:
            for radius in [0.5, 2.0, 4.0]:
                self.assertEqual(
                    set(grid.query_radius(center, radius)),
                    set(brute_radius(objs, center, radius)),
                    msg=f"radius mismatch at {center} r={radius}",
                )

    def test_insertion_order_stable(self):
        grid = SpatialGrid()
        objs = [Obj(str(i), 0.1 * i, 0.0) for i in range(5)]
        for o in reversed(objs):  # insert in reverse — order follows insertion
            grid.insert(o)
        got = grid.query_radius((0, 0), 10)
        self.assertEqual([o.name for o in got], ["4", "3", "2", "1", "0"])


class TestChebyshev(unittest.TestCase):
    def test_square_range_includes_diagonals(self):
        grid = SpatialGrid()
        center_tile = (5, 5)
        inside = Obj("diag", 6.0, 6.0)   # Δ=(1,1) → Chebyshev 1
        edge = Obj("edge", 6.0, 5.0)     # Δ=(1,0)
        outside = Obj("out", 7.0, 5.0)   # Δ=(2,0) → Chebyshev 2
        for o in (inside, edge, outside):
            grid.insert(o)
        got = grid.query_chebyshev(center_tile, 1)
        self.assertEqual(set(got), {inside, edge})

    def test_chebyshev_matches_brute_force(self):
        grid = SpatialGrid(cell_size=2.0)
        objs = [Obj(str(i), (i * 0.7) % 12, (i * 1.9) % 12) for i in range(60)]
        for o in objs:
            grid.insert(o)
        for center in [(0, 0), (6, 6), (11, 2)]:
            for r in [0, 1, 3]:
                self.assertEqual(
                    set(grid.query_chebyshev(center, r)),
                    set(brute_chebyshev(objs, center, r)),
                    msg=f"chebyshev mismatch at {center} r={r}",
                )


class TestMembership(unittest.TestCase):
    def test_remove_and_move(self):
        grid = SpatialGrid()
        a = Obj("a", 0.0, 0.0)
        b = Obj("b", 5.0, 5.0)
        grid.insert(a)
        grid.insert(b)
        grid.remove(a)
        self.assertEqual(grid.query_radius((0, 0), 1), [])
        # b moves next to origin; move() must re-bucket it
        b.transform.wx, b.transform.wy = 0.5, 0.0
        grid.move(b)
        self.assertEqual(grid.query_radius((0, 0), 1), [b])

    def test_rebuild_resets(self):
        grid = SpatialGrid()
        a = Obj("a", 0.0, 0.0)
        grid.insert(a)
        b = Obj("b", 1.0, 0.0)
        c = Obj("c", 2.0, 0.0)
        grid.rebuild([b, c])
        got = grid.query_radius((0, 0), 5)
        self.assertEqual(got, [b, c])  # a gone, order follows rebuild order

    def test_double_insert_is_noop(self):
        grid = SpatialGrid()
        a = Obj("a", 0.0, 0.0)
        grid.insert(a)
        grid.insert(a)
        self.assertEqual(grid.query_radius((0, 0), 1), [a])

    def test_bad_cell_size(self):
        with self.assertRaises(ValueError):
            SpatialGrid(cell_size=0)


if __name__ == "__main__":
    unittest.main()
