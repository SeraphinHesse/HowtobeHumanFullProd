"""Phase 2 acceptance tests for engine/core (E-10, E-11, E-13, E-14, E-15).

All pure Python — no pygame anywhere in these tests; the purity test proves
engine.core itself keeps it that way.
"""
import pathlib
import subprocess
import sys
import unittest

from engine.core import (
    Component,
    GameObject,
    Health,
    Scene,
    Transform,
    component_from_dict,
)

REPO = pathlib.Path(__file__).resolve().parents[2]


class Marker(Component):
    """Minimal test component with declared, typed fields (E-11)."""

    label: str = ""
    count: int = 0


class Ticker(Component):
    """Appends its owner's name to a shared log on update — order probe."""

    log_key: str = ""

    def update(self, dt):
        UPDATE_LOG.setdefault(self.log_key, []).append(dt)


UPDATE_LOG = {}


class TestComponentFields(unittest.TestCase):
    """E-11: declared, typed, serializable fields."""

    def test_declared_fields_collected(self):
        self.assertEqual(Marker._fields, {"label": str, "count": int})

    def test_defaults_and_overrides(self):
        m = Marker(label="a")
        self.assertEqual(m.label, "a")
        self.assertEqual(m.count, 0)

    def test_unknown_field_rejected(self):
        with self.assertRaises(TypeError):
            Marker(nope=1)

    def test_wrong_type_rejected(self):
        with self.assertRaises(TypeError):
            Marker(count="not an int")

    def test_non_json_field_type_rejected_at_declaration(self):
        with self.assertRaises(TypeError):

            class Bad(Component):
                surface: object = None

    def test_int_accepted_for_float_field(self):
        class Ratio(Component):
            value: float = 0.0

        r = Ratio(value=1)  # ints are valid JSON numbers for float fields
        self.assertEqual(r.value, 1)


class TestSerialization(unittest.TestCase):
    """E-15: any GameObject round-trips through a JSON dict."""

    def test_component_round_trip(self):
        m = Marker(label="hi", count=3)
        d = m.to_dict()
        self.assertEqual(d, {"type": "Marker", "fields": {"label": "hi", "count": 3}})
        m2 = component_from_dict(d)
        self.assertIsInstance(m2, Marker)
        self.assertEqual(m2.label, "hi")
        self.assertEqual(m2.count, 3)

    def test_unknown_component_type_rejected(self):
        with self.assertRaises(KeyError):
            component_from_dict({"type": "NoSuchComponent", "fields": {}})

    def test_gameobject_round_trip(self):
        go = GameObject(
            name="thing",
            tags=("enemy", "flying"),
            transform=Transform(wx=3.5, wy=7.25, layer="deco"),
            components=[Marker(label="x", count=9), Health(max_hp=50, hp=20)],
        )
        d = go.to_dict()
        go2 = GameObject.from_dict(d)
        self.assertEqual(go2.id, go.id)
        self.assertEqual(go2.name, "thing")
        self.assertEqual(go2.tags, ("enemy", "flying"))
        self.assertEqual(go2.transform.wx, 3.5)
        self.assertEqual(go2.transform.wy, 7.25)
        self.assertEqual(go2.transform.layer, "deco")
        self.assertEqual(len(go2.components), 2)
        self.assertEqual(go2.get_component(Marker).count, 9)
        self.assertEqual(go2.get_component(Health).hp, 20)
        # dict form is JSON-clean: re-dump equals first dump
        self.assertEqual(go2.to_dict(), d)

    def test_ids_are_stable_and_unique(self):
        a, b = GameObject(), GameObject()
        self.assertNotEqual(a.id, b.id)
        self.assertEqual(GameObject.from_dict(a.to_dict()).id, a.id)


class TestSubclassStateGuard(unittest.TestCase):
    """E-11 mechanical rule: no authoritative state as subclass attributes."""

    def test_public_subclass_attribute_rejected(self):
        class Building(GameObject):
            def __init__(self):
                super().__init__(name="b")
                self.gold = 5  # authoritative state outside a component

        with self.assertRaises(AttributeError):
            Building()

    def test_underscore_cache_allowed(self):
        class Building(GameObject):
            def __init__(self):
                super().__init__(name="b")
                self._cache = 5  # transient, never serialized — allowed

        self.assertEqual(Building()._cache, 5)

    def test_engine_fields_still_writable(self):
        go = GameObject(name="a")
        go.name = "renamed"
        self.assertEqual(go.name, "renamed")


class TestTransform(unittest.TestCase):
    def test_layer_validated(self):
        with self.assertRaises(ValueError):
            Transform(layer="hud")

    def test_defaults(self):
        t = Transform()
        self.assertEqual((t.wx, t.wy, t.layer), (0.0, 0.0, "entities"))


class TestSceneLifecycle(unittest.TestCase):
    """E-13: spawn/despawn queues applied at frame boundaries; E-10 hooks."""

    def make_hooked(self, events, name):
        class Hooked(GameObject):
            def on_spawn(self):
                events.append(("spawn", name))

            def on_update(self, dt):
                events.append(("update", name))

            def on_despawn(self):
                events.append(("despawn", name))

        return Hooked(name=name)

    def test_spawn_applied_at_frame_start(self):
        events = []
        scene = Scene()
        scene.spawn(self.make_hooked(events, "a"))
        self.assertEqual(list(scene.objects()), [])  # queued, not live
        self.assertEqual(events, [])  # on_spawn not called yet
        scene.update(0.016)
        self.assertEqual(events, [("spawn", "a"), ("update", "a")])

    def test_spawn_mid_update_waits_for_next_frame(self):
        events = []
        scene = Scene()
        late = self.make_hooked(events, "late")

        class Spawner(GameObject):
            def on_spawn(self):
                events.append(("spawn", "spawner"))

            def on_update(self, dt):
                events.append(("update", "spawner"))
                scene.spawn(late)

        scene.spawn(Spawner(name="spawner"))
        scene.update(0.016)  # frame 1: spawner runs, late only enqueued
        self.assertEqual(
            events, [("spawn", "spawner"), ("update", "spawner")]
        )
        scene.update(0.016)  # frame 2: late spawns and updates
        self.assertEqual(events[2:4], [("spawn", "late"), ("update", "spawner")])
        self.assertIn(("update", "late"), events)

    def test_despawn_mid_update_finishes_frame(self):
        events = []
        scene = Scene()
        victim = self.make_hooked(events, "victim")

        class Killer(GameObject):
            def on_update(self, dt):
                events.append(("update", "killer"))
                scene.despawn(victim)

        scene.spawn(Killer(name="killer"))
        scene.spawn(victim)
        scene.update(0.016)
        # victim still updated this frame (killer runs first), despawned after
        self.assertIn(("update", "victim"), events)
        self.assertEqual(events[-1], ("despawn", "victim"))
        scene.update(0.016)
        self.assertNotIn(
            ("update", "victim"), events[events.index(("despawn", "victim")) + 1 :]
        )
        self.assertEqual(list(scene.objects()), [scene.objects()[0]])  # killer only

    def test_component_updates_run(self):
        UPDATE_LOG.clear()
        scene = Scene()
        scene.spawn(GameObject(components=[Ticker(log_key="t")]))
        scene.update(0.5)
        scene.update(0.25)
        self.assertEqual(UPDATE_LOG["t"], [0.5, 0.25])


class TestSceneOrderAndQueries(unittest.TestCase):
    """E-14 deterministic order; E-13 iteration by type/tag."""

    def test_update_order_is_spawn_order(self):
        order = []

        class Probe(GameObject):
            def on_update(self, dt):
                order.append(self.name)

        scene = Scene()
        for name in ["a", "b", "c", "d"]:
            scene.spawn(Probe(name=name))
        scene.update(0.016)
        scene.update(0.016)
        self.assertEqual(order, ["a", "b", "c", "d"] * 2)

    def test_by_type_and_by_tag(self):
        class Enemy(GameObject):
            pass

        scene = Scene()
        e = Enemy(name="e", tags=("hostile",))
        g = GameObject(name="g", tags=("hostile", "static"))
        scene.spawn(e)
        scene.spawn(g)
        scene.update(0.016)
        self.assertEqual(list(scene.by_type(Enemy)), [e])
        self.assertEqual(list(scene.by_tag("hostile")), [e, g])
        self.assertEqual(list(scene.by_tag("static")), [g])
        self.assertEqual(list(scene.by_tag("none")), [])

    def test_area_query_stub_until_physics(self):
        with self.assertRaises(NotImplementedError):
            Scene().query_area((0, 0), 3)


class TestPurity(unittest.TestCase):
    """Hard rule: engine.core imports no pygame — headless-testable."""

    def test_engine_core_does_not_import_pygame(self):
        code = (
            "import sys; "
            "import engine.core; "
            "assert 'pygame' not in sys.modules, 'pygame leaked into engine.core'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
