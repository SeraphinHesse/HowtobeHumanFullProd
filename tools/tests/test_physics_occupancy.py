"""TileOccupancy tests (E-32): set / clear / get / is_occupied, one occupant
per tile. Pure Python — no pygame."""
import unittest

from engine.physics import TileOccupancy


class TestOccupancy(unittest.TestCase):
    def test_set_get_is_occupied(self):
        occ = TileOccupancy()
        marker = object()
        self.assertFalse(occ.is_occupied((2, 3)))
        self.assertIsNone(occ.get((2, 3)))
        occ.set((2, 3), marker)
        self.assertTrue(occ.is_occupied((2, 3)))
        self.assertIs(occ.get((2, 3)), marker)

    def test_clear(self):
        occ = TileOccupancy()
        occ.set((1, 1), object())
        occ.clear((1, 1))
        self.assertFalse(occ.is_occupied((1, 1)))
        occ.clear((1, 1))  # clearing an empty tile is a no-op

    def test_single_occupant_replaced(self):
        occ = TileOccupancy()
        first, second = object(), object()
        occ.set((0, 0), first)
        occ.set((0, 0), second)  # at most one occupant — second replaces first
        self.assertIs(occ.get((0, 0)), second)

    def test_tile_accepts_list_key(self):
        occ = TileOccupancy()
        marker = object()
        occ.set([4, 5], marker)  # normalized to a tuple key
        self.assertIs(occ.get((4, 5)), marker)
        self.assertTrue(occ.is_occupied([4, 5]))


if __name__ == "__main__":
    unittest.main()
