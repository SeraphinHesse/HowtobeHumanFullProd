"""feat-sniper-tracer — the Sniper's cosmetic bullet.

The Sniper's hit lands instantly on its cooldown (``EnemyCombat``, NE-1); this
feature adds ONLY the visual: a bullet flying from the firing enemy's muzzle
to the CENTRE of the victim building's sheet, drawn off ``FloaterManager``'s
own list. Four pins:

1. A stand-off shot (``PathAgent.in_range``, never ``blocked``) is seen at all
   — the watcher's gate used to read ``blocked`` alone, so the one ranged type
   fired no FX.
2. The bullet's endpoints are the muzzle anchor and the target's sheet centre.
3. It draws the MAX-LEVEL ``vfx_projectile`` variant — never ``vfx_shell``.
4. It ages out and never touches the simulation.
"""
import unittest

from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.test_combat_anchors import CS, VFX, make_store
from tools.tests.test_esv6_converge import (
    UI_BAL, CORE_BAL, _TagScene, make_store_two,
)

from engine.assets.registry import SlotRegistry
from engine.core import GameObject, SpriteAnimator, Transform
from engine.render.hud import HudRect, HudSprite
from game.anchors import sprite_center_world
from game.enemies.components import EnemyCombat, PathAgent
from game.ui.effects import FloaterManager


class _Sniper(GameObject):
    ETYPE = "sniper"


class _Recorder:
    """The one renderer surface the tracer draw uses."""

    def __init__(self):
        self.hud = []

    def submit_hud(self, item):
        self.hud.append(item)


def _registry():
    """Nine interchangeable projectile variants, stated as a literal doc (the
    test_vfx_variants precedent) rather than inherited from the fixture."""
    return SlotRegistry({"categories": [{
        "key": "vfx",
        "display_name": "VFX",
        "frame_w": 32,
        "frame_h": 32,
        "animations": ["idle"],
        "groups": [{"label": "Effects", "children": [
            {"label": "Projectile",
             "slots": ["vfx_projectile", "vfx_projectile_v2",
                       "vfx_projectile_v3"]},
            {"label": "Shell", "slots": ["vfx_shell", "vfx_shell_v2"]},
        ]}],
    }]})


def _fire(fm, sniper, scene):
    """Two watcher passes with a cooldown RESET between them — the "an attack
    just landed" signal watch_enemies reads."""
    fm.watch_enemies(scene)
    sniper.get_component(EnemyCombat).cooldown += 1.0
    fm.watch_enemies(scene)


def _setup(anchor=(40, -10), in_range=True, blocked=False):
    assets = make_store_two("sniper_art", anchor, "target_art", anchor)
    target = GameObject(tags=("building",), transform=Transform(wx=6.0, wy=3.0),
                       components=[SpriteAnimator(slot_key="target_art")])
    sniper = _Sniper(tags=("enemy",), transform=Transform(wx=2.0, wy=3.0),
                    components=[EnemyCombat(cooldown=1.0),
                                PathAgent(blocked=blocked),
                                SpriteAnimator(slot_key="sniper_art")])
    pa = sniper.get_component(PathAgent)
    pa.in_range = in_range
    pa._target = target
    fm = FloaterManager(UI_BAL, CORE_BAL, VFX)
    fm.assets, fm.cs = assets, CS
    return fm, sniper, target, _TagScene([sniper])


class TestSniperTracer(unittest.TestCase):
    def test_stand_off_shot_spawns_one_bullet(self):
        """`in_range` with `blocked` False — the Sniper's ONLY state. It used
        to spawn nothing at all."""
        fm, sniper, _target, scene = _setup()
        _fire(fm, sniper, scene)
        self.assertEqual(len(fm._tracers), 1)

    def test_endpoints_are_muzzle_and_target_sheet_centre(self):
        fm, sniper, target, scene = _setup()
        _fire(fm, sniper, scene)
        t = fm._tracers[0]
        self.assertEqual(t["from"],
                        fm._anchored(sniper, "muzzle",
                                    *sniper.transform.world_pos))
        self.assertEqual(t["to"], sprite_center_world(fm.assets, CS, target))

    def test_draws_the_max_level_projectile_variant(self):
        """The top variant of the PROJECTILE family — never the shell's.
        `AssetStore.registry` is read-only, so the slot resolver is asked
        through a bare store stub carrying just the one attribute it reads."""
        fm, _sniper, _target, _scene = _setup()

        class _Store:
            registry = _registry()

        fm.assets = _Store()
        self.assertEqual(fm._tracer_slot(), "vfx_projectile_v3")

    def test_no_art_falls_back_to_the_stone_dot_and_ages_out(self):
        fm, sniper, _target, scene = _setup()
        _fire(fm, sniper, scene)
        r = _Recorder()
        fm.submit_tracers(r, CS)
        self.assertEqual(len(r.hud), 1)
        self.assertIsInstance(r.hud[0], (HudRect, HudSprite))
        fm.update(fm._tracers[0]["life"] + 0.01)
        self.assertEqual(fm._tracers, [])

    def test_melee_enemy_never_spawns_one(self):
        fm, sniper, _t, scene = _setup(blocked=True, in_range=False)
        sniper.__class__ = GameObject          # ETYPE falls back to "standard"
        _fire(fm, sniper, scene)
        self.assertEqual(fm._tracers, [])


if __name__ == "__main__":
    unittest.main()
