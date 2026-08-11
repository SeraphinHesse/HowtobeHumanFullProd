"""vfx-projectile-spritesheets: swappable beam/crater sprites.

`FloaterManager.submit_beams` draws the Sun Scorcher's beam as a `HudLines`
line UNLESS `vfx_beam` has imported art, in which case it draws a looping
`HudSprite` at the live target's screen point instead (the line is REPLACED,
never layered under it) — the same has-art toggle `submit_projectiles`
already has for `vfx_projectile`/`vfx_shell`.

`ProjectileArc._impact` (`game/enemies/combat.py`) spawns a one-shot
`PlayOnceVfx` at the mortar's impact point instead of the procedural
`Crater` when `CRATER_SLOT` (`vfx_crater`) has imported art.

Headless/pure: fake scene + a recording renderer for the beam half, a real
`Scene` for the crater half (its two-frame spawn-queue semantics matter) —
the `test_projectile_sprites.py` pattern reused verbatim (`make_store_with_
art`, `RecordingRenderer`, `FakeScene`). Never touches live `data/`.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.core import GameObject, Scene, SpriteAnimator, Transform
from engine.coords import load_coordinate_system
from engine.render import HudLines, HudSprite
from game.buildings.components import BeamAttacker, TierState
from game.core import load_balance
from game.enemies.combat import CRATER_SLOT, ProjectileAOE, ProjectileArc
from game.ui.effects import FloaterManager

CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")


class RecordingRenderer:
    """`submit_beams` emits only through `submit_hud`."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


class FakeScene:
    def __init__(self, objects):
        self._objects = list(objects)

    def by_tag(self, tag):
        return [o for o in self._objects if tag in o.tags]


def make_store_with_art(*slot_keys, frame_w=64, frame_h=64):
    """An AssetStore where every slot in `slot_keys` has one imported `idle`
    frame — `animation_total_ms` returns a real number for exactly these
    slots, same E-37 signal `engine.vfx.spawn_play_once` reads."""
    entries = {}
    for slot in slot_keys:
        raw = {
            "sheet": "imported/x.png", "frame_w": frame_w, "frame_h": frame_h,
            "offset_x": 0, "offset_y": 0,
            "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                      "loop_start": 0, "loop_end": 0, "loop_count": 1}],
        }
        entries[slot] = entry_from_dict(slot, raw)
    frame_sizes = {slot: (frame_w, frame_h) for slot in slot_keys}
    return AssetStore(manifest=Manifest(entries), sprites_dir=None,
                      frame_sizes=frame_sizes)


class _AliveEnemy(GameObject):
    """A minimal live-target stand-in — `submit_beams` reads `.alive` as a
    guard-safe duck-typed property, never a settable field (E-11 forbids
    assigning an undeclared attribute after construction)."""

    @property
    def alive(self):
        return True


def make_beam_building(wx, wy, tier=0):
    return GameObject(
        name="sun_scorcher", tags=("combat",), transform=Transform(wx=wx, wy=wy),
        components=[TierState(building_type="sun_scorcher", current_tier=tier),
                    BeamAttacker()])


class TestBeamFallbackLine(unittest.TestCase):
    """No art on `vfx_beam`: byte-identical to before this feature — a
    `HudLines` from the turret to the target."""

    def test_no_art_still_draws_the_line(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        self.assertIsNone(fm.assets)
        cs = load_coordinate_system(FIXTURE_DATA)
        b = make_beam_building(2.0, 2.0)
        target = _AliveEnemy(name="enemy", tags=("enemy",),
                             transform=Transform(wx=4.0, wy=2.0))
        b.get_component(BeamAttacker)._target = target
        scene = FakeScene([b])
        renderer = RecordingRenderer()
        fm.submit_beams(renderer, cs, scene)

        self.assertEqual(len(renderer.items), 1)
        self.assertIsInstance(renderer.items[0], HudLines)


class TestBeamSprite(unittest.TestCase):
    """Art on `vfx_beam`: the line is REPLACED by a looping `HudSprite`
    centred on the target's screen point."""

    def test_art_replaces_the_line_with_a_sprite_at_the_target(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_beam")
        cs = load_coordinate_system(FIXTURE_DATA)
        cs.camera.zoom = 1.0
        b = make_beam_building(2.0, 2.0)
        target = _AliveEnemy(name="enemy", tags=("enemy",),
                             transform=Transform(wx=4.0, wy=2.0))
        b.get_component(BeamAttacker)._target = target
        scene = FakeScene([b])
        renderer = RecordingRenderer()
        fm.submit_beams(renderer, cs, scene)

        self.assertEqual(len(renderer.items), 1)
        item = renderer.items[0]
        self.assertIsInstance(item, HudSprite)
        self.assertEqual(item.slot_key, "vfx_beam")
        self.assertEqual(item.animation, "idle")

        tx, ty = cs.world_to_screen(4.5, 2.5)
        self.assertEqual(item.dest[0], int(tx - item.size[0] / 2))
        self.assertEqual(item.dest[1], int(ty - item.size[1] / 2))

    def test_dead_target_shows_nothing_art_or_not(self):
        """The `alive` gate runs before the has-art branch either way."""
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        fm.assets = make_store_with_art("vfx_beam")
        cs = load_coordinate_system(FIXTURE_DATA)
        b = make_beam_building(2.0, 2.0)
        dead = GameObject(name="corpse", tags=("enemy",),
                          transform=Transform(wx=4.0, wy=2.0))  # alive=False
        b.get_component(BeamAttacker)._target = dead
        scene = FakeScene([b])
        renderer = RecordingRenderer()
        fm.submit_beams(renderer, cs, scene)
        self.assertEqual(renderer.items, [])


class TestCraterSpawnChoice(unittest.TestCase):
    """`ProjectileArc._impact`: no art -> the procedural `Crater` unchanged;
    art on `CRATER_SLOT` -> a one-shot `PlayOnceVfx` instead, never both.

    `Scene.spawn` only QUEUES (E-13) — a shell fired with `travel_time=0.0`
    impacts on the FIRST `update`, which spawns the cosmetic into the queue;
    a SECOND `update` is needed to merge it into the live objects `by_tag`
    reads."""

    def _fire_and_impact(self, assets=None):
        scene = Scene()
        shell = ProjectileAOE(1.0, 1.0, dmg=10, radius=1.5, crater_life=1.0)
        arc = shell.get_component(ProjectileArc)
        if assets is not None:
            arc._assets = assets
        arc.launch(2.0, 3.0, shooter=None, scene=scene, travel_time=0.0)
        scene.spawn(shell)
        scene.update(0.1)   # merges the shell, ticks its timer -> _impact
        scene.update(0.1)   # merges whatever _impact queued
        return scene

    def test_no_art_spawns_the_procedural_crater(self):
        scene = self._fire_and_impact(assets=None)
        self.assertEqual(len(scene.by_tag("crater")), 1)
        self.assertEqual(scene.by_tag("vfx_oneshot"), [])

    def test_art_spawns_a_one_shot_sprite_instead(self):
        scene = self._fire_and_impact(assets=make_store_with_art(CRATER_SLOT))
        self.assertEqual(scene.by_tag("crater"), [])
        oneshot = scene.by_tag("vfx_oneshot")
        self.assertEqual(len(oneshot), 1)
        animator = oneshot[0].get_component(SpriteAnimator)
        self.assertEqual(animator.slot_key, CRATER_SLOT)
        self.assertEqual(animator.animation, "idle")


if __name__ == "__main__":
    unittest.main()
