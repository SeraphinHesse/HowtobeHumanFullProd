"""feat-projectile-anchored-flight — the two MINIMAL tests the brief asks
for (docs/briefs/feat-projectile-anchored-flight.md §5). A reviewer agent
owns the rest of the coverage.

1. Endpoint parity + the D4 pin, in ONE test: a defender's `muzzle` anchor
   is the exact spawn point, the homing MOVEMENT target is the target's
   `impact` anchor (not `transform.world_pos`), and `launch()`'s timer is
   bit-identical to the value computed from the UNANCHORED positions —
   anchors move art, never flight timing.
2. Un-anchored is byte-identical: the full `resolve_combat` -> `submit_
   projectiles` pipeline, with no anchors authored, draws at exactly the
   pixel today's (pre-fix) draw-time-lift formula would have produced —
   independently recomputed here, never read off the refactored code.

Same headless `synth` tilemap + `Scene` harness as `test_combat_anchors.py` /
`test_esv6_converge.py`; reuses their pinned literals (defender @ (1,0),
target @ (2,0), the SAME muzzle/impact anchor values already independently
verified there) instead of re-deriving the iso algebra a third time.
"""
import math
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.test_combat_anchors import (
    BUILD, CS, VFX, frozen_defender, frozen_target, make_store, synth,
)
from tools.tests.test_esv6_converge import CORE_BAL, UI_BAL, make_store_two

from engine.core import Scene, SpriteAnimator
from engine.physics import TileOccupancy
from game.enemies import resolve_combat
from game.enemies.combat import ProjectileHoming
from game.ui.effects import FloaterManager

PROJ_SPEED = BUILD["DefenceBuildings"]["globals"]["projectile_speed_tiles"]


class _TagScene:
    """The minimal ``scene.by_tag(tag)`` surface ``submit_projectiles``
    reads — the ``test_vfx.py``/``test_projectile_sprites.py`` precedent."""

    def __init__(self, objects):
        self._objects = list(objects)

    def by_tag(self, tag):
        return [o for o in self._objects if tag in o.tags]


# ===========================================================================
# 1 — endpoint parity (spawn @ muzzle, homes to impact) + the D4 timer pin
# ===========================================================================
class TestEndpointParityAndD4TimerPin(unittest.TestCase):
    def test_spawn_at_muzzle_homes_toward_impact_timer_unaffected(self):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        # Same positions test_combat_anchors.py / test_esv6_converge.py pin:
        # defender (1.0, 0.0), target (2.0, 0.0) — so their independently
        # verified literal anchor points apply here unchanged.
        defender = frozen_defender(tm, scene, occ, 1, 0, slot_key="def_slot")
        target = frozen_target(scene, tm, 2, 0)
        target.get_component(SpriteAnimator).slot_key = "tgt_slot"
        # def_slot's muzzle anchor (40, -10) -> (1.8125, -0.4375)
        #   (TestMuzzleShiftsTheSpawnPoint, test_combat_anchors.py).
        # tgt_slot's impact anchor (12, -30) -> (1.75, -0.625)
        #   (TestProjectileHitEvent, test_esv6_converge.py) — a DIFFERENT
        # anchor value than the muzzle one, so a bug that homed toward the
        # wrong point would be caught, not accidentally matched.
        assets = make_store_two("def_slot", (40, -10), "tgt_slot", (12, -30))

        # D4 pin: launch()'s timer is computed from the UNANCHORED shooter/
        # target positions — never an anchored or lifted point.
        bx, by = defender.transform.world_pos
        tx0, ty0 = target.transform.world_pos
        self.assertEqual((bx, by), (1.0, 0.0))
        self.assertEqual((tx0, ty0), (2.0, 0.0))
        expected_timer = math.hypot(tx0 - bx, ty0 - by) / PROJ_SPEED

        scene.update(0.05)
        resolve_combat(scene, tm, 0.05, BUILD, VFX, assets=assets, cs=CS)
        scene.update(0.0)   # flush the spawn queue; dt=0 so nothing MOVES yet
        projectiles = scene.by_tag("projectile")
        self.assertEqual(len(projectiles), 1)
        proj = projectiles[0]
        hom = proj.get_component(ProjectileHoming)
        self.assertAlmostEqual(hom.timer, expected_timer, places=9)

        # Endpoint parity — the spawn point IS the muzzle anchor's exact
        # pinned literal, not the defender's plain (1.0, 0.0).
        px, py = proj.transform.world_pos
        self.assertAlmostEqual(px, 1.8125, places=9)
        self.assertAlmostEqual(py, -0.4375, places=9)

        # One homing step moves TOWARD the target's impact anchor (1.75,
        # -0.625) — independently recomputed by the SAME step formula
        # update() uses, fed the pinned anchor literal, not
        # target.transform.world_pos (2.0, 0.0), which differs from it on
        # both axes (so a regression back to world_pos cannot pass by luck).
        tx, ty = 1.75, -0.625
        self.assertNotEqual((tx, ty), (tx0, ty0))
        dt = 0.01
        step = PROJ_SPEED * dt
        d = math.hypot(tx - px, ty - py)
        expected_px = px + (tx - px) / d * step
        expected_py = py + (ty - py) / d * step

        scene.update(dt)
        new_px, new_py = proj.transform.world_pos
        self.assertAlmostEqual(new_px, expected_px, places=9)
        self.assertAlmostEqual(new_py, expected_py, places=9)
        # ...and NOT toward the plain world_pos (proves the branch actually
        # exercised the anchor, not a coincidental near-identical path).
        wrong_d = math.hypot(tx0 - px, ty0 - py)
        wrong_px = px + (tx0 - px) / wrong_d * step
        wrong_py = py + (ty0 - py) / wrong_d * step
        self.assertNotAlmostEqual(new_px, wrong_px, places=6)


# ===========================================================================
# 2 — un-anchored draw is byte-identical to today's draw-time-lift formula
# ===========================================================================
class TestUnanchoredDrawByteIdentical(unittest.TestCase):
    def test_unanchored_projectile_draws_at_the_pre_fix_pixel(self):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        defender = frozen_defender(tm, scene, occ, 1, 0)   # slot has no anchors
        frozen_target(scene, tm, 2, 0)
        assets = make_store("anchor_test", anchor_xy=None)

        scene.update(0.05)
        resolve_combat(scene, tm, 0.05, BUILD, VFX, assets=assets, cs=CS)
        scene.update(0.0)
        projectiles = scene.by_tag("projectile")
        self.assertEqual(len(projectiles), 1)
        proj = projectiles[0]

        fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
        renderer = _RecordingRenderer()
        fm.submit_projectiles(renderer, CS, _TagScene([proj]))
        self.assertEqual(len(renderer.items), 1)
        item = renderer.items[0]

        # Today's (pre-fix) formula, independently recomputed: the dot drawn
        # at the defender's PLAIN world position, lifted by lift_frac tile
        # heights AT DRAW TIME (game/ui/effects.py's old submit_projectiles,
        # before this fix moved the lift into the spawn point) — the exact
        # expression this refactor is a no-op against for unanchored play.
        bx, by = defender.transform.world_pos
        self.assertEqual((bx, by), (1.0, 0.0))
        cx, cy = CS.world_to_screen(bx, by)
        pr = VFX["procedural"]["projectile"]
        zoom = CS.camera.zoom
        size = max(2, int(pr["stone_size"] * zoom))
        lift = int(CS.geometry.tile_h * zoom * pr["lift_frac"])
        expected = (int(cx - size / 2), int(cy - lift - size / 2))
        self.assertEqual((item.rect[0], item.rect[1]), expected)


class _RecordingRenderer:
    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


if __name__ == "__main__":
    unittest.main()
