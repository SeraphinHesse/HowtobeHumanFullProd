"""Waypoint advance tests (E-30): snap, index advance, reached-end, multi-step.
Prototype-exact port of enemy.py _do_move. Pure Python — no pygame."""
import math
import unittest

from engine.physics import advance
from engine.physics.movement import DEFAULT_THRESHOLD


class TestAdvance(unittest.TestCase):
    def test_step_toward_waypoint(self):
        # 1 unit away, speed 1, dt 0.5 → move half way, no arrival
        pos, index, arrived, end = advance((0.0, 0.0), [(1.0, 0.0)], 0, 1.0, 0.5)
        self.assertAlmostEqual(pos[0], 0.5)
        self.assertAlmostEqual(pos[1], 0.0)
        self.assertEqual(index, 0)
        self.assertFalse(arrived)
        self.assertFalse(end)

    def test_snaps_and_advances_index(self):
        # within threshold of waypoint 0 → snap exactly, advance to index 1
        start = (1.0 - DEFAULT_THRESHOLD / 2, 0.0)
        pos, index, arrived, end = advance(
            start, [(1.0, 0.0), (2.0, 0.0)], 0, 1.0, 0.016
        )
        self.assertEqual(pos, (1.0, 0.0))  # snapped exactly onto the waypoint
        self.assertEqual(index, 1)
        self.assertTrue(arrived)
        self.assertFalse(end)  # more waypoints remain

    def test_reached_end_on_last_waypoint(self):
        pos, index, arrived, end = advance(
            (2.0, 0.0), [(1.0, 0.0), (2.0, 0.0)], 1, 1.0, 0.016
        )
        self.assertEqual(pos, (2.0, 0.0))
        self.assertEqual(index, 2)
        self.assertTrue(arrived)
        self.assertTrue(end)

    def test_index_past_end_is_terminal(self):
        pos, index, arrived, end = advance((5.0, 5.0), [(1.0, 1.0)], 1, 1.0, 0.1)
        self.assertEqual(pos, (5.0, 5.0))
        self.assertEqual(index, 1)
        self.assertFalse(arrived)
        self.assertTrue(end)

    def test_empty_waypoints_terminal(self):
        pos, index, arrived, end = advance((3.0, 4.0), [], 0, 1.0, 0.1)
        self.assertEqual(pos, (3.0, 4.0))
        self.assertTrue(end)

    def test_multi_step_traverses_path(self):
        # Walk a 3-waypoint L-shaped path to the end with small steps.
        waypoints = [(2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]
        pos, index, end = (0.0, 0.0), 0, False
        for _ in range(1000):
            pos, index, _arrived, end = advance(pos, waypoints, index, 1.0, 0.05)
            if end:
                break
        self.assertTrue(end)
        self.assertEqual(index, len(waypoints))
        self.assertEqual(pos, (0.0, 2.0))  # snapped onto the final waypoint

    def test_diagonal_unit_direction(self):
        # 3-4-5 triangle: speed 5, dt 1 covers exactly the 5-unit distance...
        pos, index, arrived, end = advance((0.0, 0.0), [(3.0, 4.0)], 0, 5.0, 1.0)
        # ...but with no clamp it lands ON the target only up to float error;
        # here dist(5) is not < threshold so it steps the full unit vector.
        self.assertAlmostEqual(math.hypot(pos[0], pos[1]), 5.0, places=6)
        self.assertAlmostEqual(pos[0], 3.0, places=6)
        self.assertAlmostEqual(pos[1], 4.0, places=6)
        self.assertFalse(arrived)


if __name__ == "__main__":
    unittest.main()
