"""RangeSensor component tests (E-12/E-31): in_range + grid query. Pure."""
import unittest

from engine.core import GameObject, RangeSensor, Transform
from engine.physics import SpatialGrid


class _T:
    def __init__(self, wx, wy):
        self.wx, self.wy = wx, wy

    @property
    def world_pos(self):
        return (self.wx, self.wy)


class Obj:
    def __init__(self, wx, wy):
        self.transform = _T(wx, wy)


class TestInRange(unittest.TestCase):
    def test_chebyshev_in_range(self):
        s = RangeSensor(range_tiles=2)
        self.assertTrue(s.in_range((5, 5), (7, 7)))    # Δ=(2,2) → 2 <= 2
        self.assertTrue(s.in_range((5, 5), (5, 3)))    # Δ=(0,2)
        self.assertFalse(s.in_range((5, 5), (8, 5)))   # Δ=(3,0) → 3 > 2

    def test_default_range_one(self):
        s = RangeSensor()
        self.assertEqual(s.range_tiles, 1)
        self.assertTrue(s.in_range((0, 0), (1, 1)))
        self.assertFalse(s.in_range((0, 0), (2, 0)))


class TestQuery(unittest.TestCase):
    def test_query_delegates_to_grid(self):
        grid = SpatialGrid()
        near = Obj(6.0, 5.0)
        far = Obj(9.0, 5.0)
        grid.insert(near)
        grid.insert(far)
        s = RangeSensor(range_tiles=1)
        self.assertEqual(s.query(grid, (5, 5)), [near])

    def test_serializes_as_component(self):
        s = RangeSensor(range_tiles=3)
        self.assertEqual(s.to_dict(),
                         {"type": "RangeSensor", "fields": {"range_tiles": 3}})

    def test_attaches_to_gameobject(self):
        obj = GameObject(name="tower", transform=Transform(2.0, 2.0),
                         components=[RangeSensor(range_tiles=2)])
        sensor = obj.get_component(RangeSensor)
        self.assertIsNotNone(sensor)
        self.assertEqual(sensor.range_tiles, 2)


if __name__ == "__main__":
    unittest.main()
