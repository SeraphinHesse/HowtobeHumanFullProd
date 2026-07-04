"""Scene spatial-query tests (E-13/E-31): query_area + query_chebyshev via the
grid rebuilt each update, plus Movement driving a GameObject's transform
through the on_added owner seam. Pure Python — no pygame."""
import unittest

from engine.core import GameObject, Movement, Scene, Transform


class TestSceneQueries(unittest.TestCase):
    def test_query_area_after_update(self):
        scene = Scene()
        a = GameObject(name="a", transform=Transform(0.0, 0.0))
        b = GameObject(name="b", transform=Transform(1.5, 0.0))
        c = GameObject(name="c", transform=Transform(8.0, 8.0))
        for o in (a, b, c):
            scene.spawn(o)
        scene.update(0.016)
        self.assertEqual(scene.query_area((0, 0), 2.0), [a, b])
        self.assertEqual(scene.query_chebyshev((0, 0), 1), [a])

    def test_query_uses_live_positions(self):
        # The grid buckets by position at rebuild (frame start), but the exact
        # distance test reads the LIVE transform. Rebuilding once per frame
        # keeps cell membership fresh enough that a query at the object's new
        # position still finds it (cell scan has a half-cell margin).
        scene = Scene()
        mover = GameObject(
            name="mover",
            transform=Transform(0.0, 0.0),
            components=[Movement(waypoints=[[10.0, 0.0]], speed=1.0)],
        )
        scene.spawn(mover)
        scene.update(1.0)  # bucketed at (0,0), then Movement steps it to (1,0)
        self.assertAlmostEqual(mover.transform.wx, 1.0)
        self.assertEqual(scene.query_area((1, 0), 0.5), [mover])  # its live pos
        self.assertEqual(scene.query_area((0, 0), 0.5), [])       # no longer here

    def test_empty_scene_query(self):
        self.assertEqual(Scene().query_area((0, 0), 5), [])
        self.assertEqual(Scene().query_chebyshev((0, 0), 5), [])


class TestMovementComponent(unittest.TestCase):
    def test_on_added_caches_owner_and_moves_transform(self):
        obj = GameObject(
            name="walker",
            transform=Transform(0.0, 0.0),
            components=[Movement(waypoints=[[1.0, 0.0]], speed=1.0)],
        )
        mv = obj.get_component(Movement)
        self.assertIs(mv._owner, obj)  # on_added cached the owner
        obj.update(0.5)  # half a tile toward the waypoint
        self.assertAlmostEqual(obj.transform.wx, 0.5)
        self.assertFalse(mv.arrived)

    def test_reaches_end_sets_arrived(self):
        obj = GameObject(
            name="walker",
            transform=Transform(0.0, 0.0),
            components=[Movement(waypoints=[[1.0, 0.0], [2.0, 0.0]], speed=10.0)],
        )
        mv = obj.get_component(Movement)
        for _ in range(100):
            obj.update(0.1)
            if mv.arrived:
                break
        self.assertTrue(mv.arrived)
        self.assertEqual(mv.index, 2)
        self.assertEqual(obj.transform.world_pos, (2.0, 0.0))

    def test_no_waypoints_is_inert(self):
        obj = GameObject(name="idle", transform=Transform(3.0, 3.0),
                         components=[Movement()])
        obj.update(1.0)
        self.assertEqual(obj.transform.world_pos, (3.0, 3.0))

    def test_movement_serializes(self):
        mv = Movement(waypoints=[[1.0, 2.0]], speed=2.5, index=0)
        data = mv.to_dict()
        self.assertEqual(data["type"], "Movement")
        self.assertEqual(data["fields"]["waypoints"], [[1.0, 2.0]])
        self.assertEqual(data["fields"]["speed"], 2.5)


if __name__ == "__main__":
    unittest.main()
