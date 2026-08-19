"""fix-mortar-shell-arc — the minimal pins for the mortar shell's flight.

The bug: `ProjectileArc.update` only ticked its timer, so the shell sat at
its muzzle spawn point for the whole `AOE_TRAVEL_TIME` and then vanished
while a crater appeared tiles away — it was never seen to fly.

Two tests, matching the two halves of the fix:

1. The shell MOVES, on an arc that is high in the middle, and ENDS at the
   tile-diamond centre of the landing point — the same screen point the
   crater (procedural ring or imported `vfx_crater` one-shot) is drawn on.
2. The arc is cosmetic (D4): the impact time and the splash's landing point
   are bit-identical with the arc on and off.

Reuses `test_combat_anchors.py`'s pinned fixture harness.
"""
import unittest

from tools.tests.test_combat_anchors import BUILD, CS, ENEM, synth

from engine.core import Movement, Scene
from game.buildings.aoe_defence import AOEDefenceBuilding
from game.enemies.combat import (
    AOE_TRAVEL_TIME, CRATER_LIFE, ProjectileArc, _fire_splash, _predict_lead,
    _TILE_CENTRE,
)
from game.enemies.enemy import create_enemy

ARC_HEIGHT = 3.0


def _mortar_and_target():
    tm = synth(["bcs"])
    scene = Scene()
    mortar = AOEDefenceBuilding(1, 1, BUILD)
    scene.spawn(mortar)
    scene.update(0.0)
    target = create_enemy("standard", 2, 1, ENEM, tm)
    scene.spawn(target)
    scene.update(0.0)
    mv = target.get_component(Movement)
    mv.waypoints = [[0.0, 1.0]]
    mv.index = 0
    mv.speed = 1.5
    return scene, mortar, target


class TestShellActuallyFlies(unittest.TestCase):
    def test_shell_travels_arcs_and_lands_on_the_crater_point(self):
        scene, mortar, target = _mortar_and_target()
        gx, gy = _predict_lead(target, AOE_TRAVEL_TIME)
        _fire_splash(mortar, target, scene, CRATER_LIFE, cs=CS,
                     arc_height_frac=ARC_HEIGHT)
        scene.update(0.0)                 # flush the spawn queue
        shell = scene.by_tag("projectile")[0]
        arc = shell.get_component(ProjectileArc)
        start = CS.world_to_screen(*shell.transform.world_pos)

        step = AOE_TRAVEL_TIME / 10.0
        seen = []
        for _ in range(9):                # 0.9 of the flight — no impact yet
            arc.update(step)
            seen.append(CS.world_to_screen(*shell.transform.world_pos))

        # it MOVED (the bug: every one of these equalled `start`)
        self.assertNotEqual(seen[0], start)
        self.assertEqual(len(set(seen)), len(seen))
        # and it went UP first: mid-flight is above the straight line between
        # the endpoints (smaller screen y = higher).
        end = CS.world_to_screen(gx + _TILE_CENTRE, gy + _TILE_CENTRE)
        mid = seen[4]
        straight_y = start[1] + (end[1] - start[1]) * 0.5
        self.assertLess(mid[1], straight_y - 1.0)

        # the last frame before impact is essentially on the crater's own
        # screen point — where the splash and its crater fx are centred.
        arc.update(step * 0.999)
        near = CS.world_to_screen(*shell.transform.world_pos)
        self.assertAlmostEqual(near[0], end[0], delta=1.0)
        self.assertAlmostEqual(near[1], end[1], delta=1.0)


class TestArcIsCosmetic(unittest.TestCase):
    def test_timer_and_landing_point_match_a_flat_shell(self):
        pins = []
        for height in (0.0, ARC_HEIGHT):
            scene, mortar, target = _mortar_and_target()
            _fire_splash(mortar, target, scene, CRATER_LIFE, cs=CS,
                         arc_height_frac=height)
            scene.update(0.0)
            arc = scene.by_tag("projectile")[0].get_component(ProjectileArc)
            arc.update(AOE_TRAVEL_TIME / 2.0)
            pins.append((arc.timer, arc._gx, arc._gy))
        self.assertEqual(pins[0], pins[1])


if __name__ == "__main__":
    unittest.main()
