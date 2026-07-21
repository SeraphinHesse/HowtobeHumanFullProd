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
        # 3-4-5 triangle: speed 5, dt 1 covers exactly the 5-unit distance,
        # and the overshoot clamp snaps exactly onto the target since
        # step (5.0) >= dist (5.0).
        pos, index, arrived, end = advance((0.0, 0.0), [(3.0, 4.0)], 0, 5.0, 1.0)
        self.assertAlmostEqual(math.hypot(pos[0], pos[1]), 5.0, places=6)
        self.assertEqual(pos, (3.0, 4.0))
        self.assertEqual(index, 1)
        self.assertTrue(arrived)
        self.assertTrue(end)

    def test_overshoot_clamp_snaps_onto_waypoint(self):
        # A step longer than the remaining distance must land exactly ON the
        # waypoint and advance the index, not overshoot past it.
        pos, index, arrived, end = advance((0.0, 0.0), [(1.0, 0.0)], 0, 10.0, 1.0)
        self.assertEqual(pos, (1.0, 0.0))
        self.assertEqual(index, 1)
        self.assertTrue(arrived)
        self.assertTrue(end)

    def test_no_permanent_oscillation_regression(self):
        # Regression pin for the jitter bug: a raider at 2x combat speed on a
        # 30 fps frame (speed=5.4, dt=1/30 -> step=0.18, over 2*threshold=0.12)
        # used to lock into a permanent two-position oscillation and never
        # advance `index`. Walking a straight 20-waypoint path, x must be
        # monotonically non-decreasing on every call, and the unit must reach
        # the end within a few hundred calls.
        waypoints = [(float(i), 0.0) for i in range(20)]
        pos, index = (0.0, 0.0), 1
        prev_x = pos[0]
        end = False
        for _ in range(500):
            pos, index, _arrived, end = advance(pos, waypoints, index, 5.4, 1 / 30)
            self.assertGreaterEqual(
                pos[0], prev_x, "x position must never move backward"
            )
            prev_x = pos[0]
            if end:
                break
        self.assertTrue(end, "unit failed to reach the end of the path")


if __name__ == "__main__":
    unittest.main()
