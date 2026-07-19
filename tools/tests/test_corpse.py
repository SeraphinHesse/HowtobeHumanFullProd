"""Corpse — the death-animation body (Art/enemies). Pure, headless.

Pins the two halves of "play the death animation on death":
- ``Manifest.animation_ms`` / ``AssetStore.animation_total_ms`` report a named
  track's duration and, crucially, return ``None`` (no idle fallback) when the
  ``death`` row is absent — that is the "despawn instantly" signal.
- ``spawn_corpse`` drops a cosmetic ``"corpse"``-tagged body that plays ``death``
  once and self-despawns, and is invisible to every ``"enemy"`` gameplay query.
"""
import unittest

from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.core import GameObject, SpriteAnimator, Transform
from engine.core.scene import Scene
from game.enemies import DEATH_ANIM
from game.enemies.components import PathAgent
from game.enemies.corpse import Corpse, CorpseFade, spawn_corpse


def _row(animation, frames, fps=8):
    return {"animation": animation, "frames": frames, "fps": fps,
            "hidden": [], "loop_start": 0, "loop_end": 0, "loop_count": 1}


def _manifest(slot="walker_v1"):
    """A slot with idle + a 4-frame @8fps death row: dur 125ms x4 = 500ms."""
    entry = entry_from_dict(slot, {
        "sheet": "imported/x.png", "frame_w": 64, "frame_h": 96,
        "offset_x": 0, "offset_y": 0,
        "rows": [_row("idle", 3), _row(DEATH_ANIM, 4)],
    })
    return Manifest({slot: entry})


def _enemy_stub(slot="walker_v1", wx=3.0, wy=5.0, fit_tiles=1.0, scale=2.0):
    """A minimal enemy-shaped object: a SpriteAnimator + a Transform. Enough for
    spawn_corpse, which only reads those."""
    return GameObject(
        name="enemy", tags=("enemy",),
        transform=Transform(wx=wx, wy=wy, layer="entities"),
        components=[SpriteAnimator(slot_key=slot, animation="walk",
                                   fit_tiles=fit_tiles, scale=scale)],
    )


class TestAnimationDuration(unittest.TestCase):
    def test_present_row_reports_total_ms(self):
        self.assertEqual(_manifest().animation_ms("walker_v1", DEATH_ANIM), 500)

    def test_missing_animation_is_none_no_idle_fallback(self):
        # "attack" is absent — must be None, NOT the idle duration.
        self.assertIsNone(_manifest().animation_ms("walker_v1", "attack"))

    def test_missing_slot_is_none(self):
        self.assertIsNone(_manifest().animation_ms("nope", DEATH_ANIM))

    def test_store_delegates(self):
        store = AssetStore(manifest=_manifest())
        self.assertEqual(
            store.animation_total_ms("walker_v1", DEATH_ANIM), 500)
        self.assertIsNone(store.animation_total_ms("walker_v1", "attack"))


class TestSpawnCorpse(unittest.TestCase):
    def test_corpse_copies_slot_pose_and_plays_death(self):
        scene = Scene()
        enemy = _enemy_stub(slot="walker_v2", wx=3.0, wy=5.0,
                            fit_tiles=1.0, scale=2.0)
        corpse = spawn_corpse(scene, enemy, 500)
        self.assertIsInstance(corpse, Corpse)
        anim = corpse.get_component(SpriteAnimator)
        self.assertEqual(anim.slot_key, "walker_v2")
        self.assertEqual(anim.animation, DEATH_ANIM)
        self.assertEqual((anim.fit_tiles, anim.scale), (1.0, 2.0))
        self.assertEqual((corpse.transform.wx, corpse.transform.wy), (3.0, 5.0))
        self.assertEqual(corpse.transform.layer, "entities")

    def test_corpse_is_invisible_to_enemy_queries(self):
        scene = Scene()
        spawn_corpse(scene, _enemy_stub(), 500)
        scene.update(0.01)  # merge the spawn queue
        self.assertEqual(scene.by_tag("enemy"), [])
        corpses = scene.by_tag("corpse")
        self.assertEqual(len(corpses), 1)
        # No gameplay components: nothing to be shot / block / hold the round.
        self.assertIsNone(corpses[0].get_component(PathAgent))
        self.assertFalse(hasattr(corpses[0], "alive"))

    def test_corpse_self_despawns_after_lifetime(self):
        scene = Scene()
        spawn_corpse(scene, _enemy_stub(), 500)  # 500ms life
        for _ in range(4):                        # 4 x 100ms = 400ms < 500
            scene.update(0.1)
        self.assertEqual(len(scene.by_tag("corpse")), 1)
        scene.update(0.1)                         # 500ms -> despawn
        self.assertEqual(scene.by_tag("corpse"), [])

    def test_no_sprite_animator_is_a_noop(self):
        scene = Scene()
        bare = GameObject(name="enemy", tags=("enemy",),
                          transform=Transform(wx=0.0, wy=0.0))
        self.assertIsNone(spawn_corpse(scene, bare, 500))
        scene.update(0.01)
        self.assertEqual(scene.by_tag("corpse"), [])

    def test_fade_syncs_with_sim_dt(self):
        # The fade clock advances on the dt it is ticked with — so a 2x sim_dt
        # ages it twice as fast, staying in lockstep with the anim clock.
        scene = Scene()
        spawn_corpse(scene, _enemy_stub(), 500)
        scene.update(0.25)   # merge + 250ms
        scene.update(0.25)   # 500ms -> despawn
        self.assertEqual(scene.by_tag("corpse"), [])


if __name__ == "__main__":
    unittest.main()
