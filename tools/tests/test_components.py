"""Phase 2 acceptance tests for the shipped core components (E-12 partial):
SpriteAnimator (emits RenderItems through the Phase 1 pipeline) and Health.

Movement and RangeSensor are deferred to the physics phase — no stubs, so
nothing to test here yet.
"""
import unittest

from engine.assets.types import Frame
from engine.core import GameObject, Health, Scene, SpriteAnimator, Transform
from engine.coords import Camera, CoordinateSystem, Geometry
from engine.render import Renderer, RenderItem


def make_cs():
    geo = Geometry(
        tile_w=64, tile_h=32, map_cols=20, map_rows=20, zoom_levels=(0.5, 1.0, 2.0)
    )
    return CoordinateSystem(geo, Camera())


class FakeAssets:
    def frame(self, slot_key, animation="idle", anim_time_ms=0):
        return Frame(surface=f"SURF:{slot_key}", frame_w=64, frame_h=96)


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls.extend(draw_calls)


class TestSpriteAnimator(unittest.TestCase):
    def test_emits_render_item_from_transform(self):
        go = GameObject(
            transform=Transform(wx=4.0, wy=6.0, layer="deco"),
            components=[SpriteAnimator(slot_key="slot_a", animation="walk")],
        )
        items = list(go.get_component(SpriteAnimator).render_items(go.transform))
        self.assertEqual(
            items,
            [
                RenderItem(
                    "slot_a",
                    (4.0, 6.0),
                    layer="deco",
                    animation="walk",
                    anim_time_ms=0,
                )
            ],
        )

    def test_update_advances_time_and_phase_offsets(self):
        anim = SpriteAnimator(slot_key="s", phase_ms=250)
        t = Transform()
        anim.update(0.5)  # dt seconds -> +500 ms
        anim.update(0.25)  # +250 ms
        (item,) = anim.render_items(t)
        self.assertEqual(item.anim_time_ms, 1000)  # 750 elapsed + 250 phase

    def test_scene_render_items_reach_renderer(self):
        """Scene → RenderItem → Phase 1 pipeline, end to end (E-14 submit leg)."""
        scene = Scene()
        for i, pos in enumerate([(2.0, 2.0), (5.0, 3.0)]):
            scene.spawn(
                GameObject(
                    name=f"dummy{i}",
                    transform=Transform(wx=pos[0], wy=pos[1]),
                    components=[SpriteAnimator(slot_key=f"slot{i}", phase_ms=i * 100)],
                )
            )
        scene.update(0.016)
        backend = RecordingBackend()
        renderer = Renderer(make_cs(), FakeAssets(), backend=backend)
        for item in scene.render_items():
            renderer.submit(item)
        self.assertEqual(renderer.flush(target=None), 2)
        # iso depth: (2,2) draws before (5,3)
        self.assertEqual(
            [c.surface for c in backend.calls], ["SURF:slot0", "SURF:slot1"]
        )

    def test_round_trip(self):
        anim = SpriteAnimator(slot_key="k", animation="attack", phase_ms=40)
        anim.update(0.1)
        d = anim.to_dict()
        anim2 = GameObject(components=[]).add_component(
            type(anim)(**d["fields"])
        )
        self.assertEqual(anim2.slot_key, "k")
        self.assertEqual(anim2.animation, "attack")
        self.assertEqual(anim2.phase_ms, 40)
        self.assertEqual(anim2.anim_time_ms, anim.anim_time_ms)


class TestHealth(unittest.TestCase):
    def test_damage_and_death(self):
        h = Health(max_hp=100, hp=100)
        h.damage(30)
        self.assertEqual(h.hp, 70)
        self.assertFalse(h.is_dead)
        h.damage(999)
        self.assertEqual(h.hp, 0)  # clamped at 0
        self.assertTrue(h.is_dead)

    def test_heal_clamped_to_max(self):
        h = Health(max_hp=50, hp=10)
        h.heal(5)
        self.assertEqual(h.hp, 15)
        h.heal(999)
        self.assertEqual(h.hp, 50)

    def test_round_trip(self):
        h = Health(max_hp=80, hp=33)
        d = h.to_dict()
        self.assertEqual(d, {"type": "Health", "fields": {"max_hp": 80, "hp": 33}})


if __name__ == "__main__":
    unittest.main()
