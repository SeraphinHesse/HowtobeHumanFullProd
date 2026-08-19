"""Scene spatial-query tests (E-13/E-31): query_area + query_chebyshev via the
lazily-rebuilt grid, plus Movement driving a GameObject's transform through the
on_added owner seam. Pure Python — no pygame."""
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
        # The grid buckets by position at rebuild (the first query after it went
        # stale), but the exact distance test reads the LIVE transform. Either
        # way membership stays fresh enough that a query at the object's new
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


class TestGridIsLazy(unittest.TestCase):
    """The grid must be rebuilt only when someone asks. Nothing in game/ queries
    it today, so an unconditional per-frame rebuild is pure tax."""

    def _counting_scene(self):
        scene = Scene()
        scene._grid.rebuild = _Counter(scene._grid.rebuild)
        return scene

    def test_update_alone_never_rebuilds(self):
        scene = self._counting_scene()
        scene.spawn(GameObject(name="a", transform=Transform(0.0, 0.0)))
        for _ in range(10):
            scene.update(0.016)
        self.assertEqual(scene._grid.rebuild.calls, 0)

    def test_first_query_of_a_frame_rebuilds_once(self):
        scene = self._counting_scene()
        a = scene.spawn(GameObject(name="a", transform=Transform(0.0, 0.0)))
        scene.update(0.016)
        self.assertEqual(scene.query_area((0, 0), 1.0), [a])
        self.assertEqual(scene.query_area((0, 0), 1.0), [a])  # cached
        self.assertEqual(scene._grid.rebuild.calls, 1)
        scene.update(0.016)                                   # dirtied again
        self.assertEqual(scene.query_area((0, 0), 1.0), [a])
        self.assertEqual(scene._grid.rebuild.calls, 2)

    def test_mid_frame_despawn_invalidates(self):
        # A query, then a despawn in the same update: the next query must not
        # hand back the dead object out of a stale bucket.
        scene = Scene()
        a = scene.spawn(GameObject(name="a", transform=Transform(0.0, 0.0)))
        scene.update(0.016)
        self.assertEqual(scene.query_area((0, 0), 1.0), [a])
        scene.despawn(a)
        scene.update(0.016)
        self.assertEqual(scene.query_area((0, 0), 1.0), [])


class _Counter:
    """Wrap a bound method, counting calls."""

    def __init__(self, fn):
        self._fn = fn
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return self._fn(*args, **kwargs)


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

class TestTagIndex(unittest.TestCase):
    """`by_tag` is served from a cached tag index; these pin the three ways it
    must invalidate. Each asserts the indexed answer equals the linear scan it
    replaced."""

    def _live(self, scene, tag):
        return [o for o in scene._objects if tag in o.tags]

    def test_spawn_and_despawn_invalidate(self):
        scene = Scene()
        a = scene.spawn(GameObject(name="a", tags=("enemy",)))
        scene.update(0.0)
        self.assertEqual(scene.by_tag("enemy"), [a])
        b = scene.spawn(GameObject(name="b", tags=("enemy",)))
        scene.update(0.0)
        self.assertEqual(scene.by_tag("enemy"), [a, b])  # spawn order preserved
        scene.despawn(a)
        scene.update(0.0)
        self.assertEqual(scene.by_tag("enemy"), [b])

    def test_runtime_retag_invalidates(self):
        # game/enemies/kidnap.py does exactly this to drop a carrier off every
        # by_tag("enemy") query at once.
        scene = Scene()
        e = scene.spawn(GameObject(name="e", tags=("enemy",)))
        scene.update(0.0)
        self.assertEqual(scene.by_tag("enemy"), [e])
        e.tags = ("kidnapper",)
        self.assertEqual(scene.by_tag("enemy"), [])
        self.assertEqual(scene.by_tag("kidnapper"), [e])

    def test_by_tag_inside_on_spawn_sees_the_live_list_so_far(self):
        # The index must tick per appended object, not once per spawn batch:
        # on_spawn queries mid-merge and must not freeze a half-built index.
        scene = Scene()
        seen = []

        class Watcher(GameObject):
            def on_spawn(self):
                seen.append(len(scene.by_tag("enemy")))

        for i in range(3):
            scene.spawn(Watcher(name="w%d" % i, tags=("enemy",)))
        scene.update(0.0)
        self.assertEqual(seen, [1, 2, 3])
        self.assertEqual(len(scene.by_tag("enemy")), 3)

    def test_returned_list_is_a_snapshot(self):
        scene = Scene()
        a = scene.spawn(GameObject(name="a", tags=("enemy",)))
        scene.update(0.0)
        got = scene.by_tag("enemy")
        got.clear()  # mutating the result must not damage the cache
        self.assertEqual(scene.by_tag("enemy"), [a])


if __name__ == "__main__":
    unittest.main()
