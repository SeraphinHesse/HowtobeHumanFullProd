"""Enemy overhead HP bars (``FloaterManager.submit_enemy_hp_bars``).

The prototype's rules: a bar shows ONLY below full HP, its per-type width comes
from the enemy class (``HP_BAR_W``/``HP_BAR_H``), and bars from enemies sharing
a tile stack upward instead of smearing over each other. The boss goes through
this same pass (its ``"enemy"`` tag comes free with ``Enemy.EXTRA_TAGS``), so it
can never end up with two overhead bars.

Headless/pure: real enemies + real coords over the shipped data, a recording
renderer instead of a window.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine.coords import load_coordinate_system
from engine.core import Health
from engine.render import HudRect
from game.core import load_balance
from game.enemies.enemy import Boss, Enemy, Raider, SiegeCannon
from game.ui.effects import _ENEMY_BAR_STACK, FloaterManager

ENEMIES_BAL = load_balance(REPO / "data", "enemies")
CORE_BAL = load_balance(REPO / "data", "core")
UI_BAL = load_balance(REPO / "data", "ui")


class RecordingRenderer:
    """``submit_bar`` only ever emits through ``submit_hud``."""

    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)

    def bars(self):
        """The (x, y, w, h) of every submitted rect, in submission order."""
        return [i.rect for i in self.items if isinstance(i, HudRect)]


class FakeScene:
    """``submit_enemy_hp_bars`` only ever asks for ``by_tag("enemy")``."""

    def __init__(self, enemies):
        self._enemies = enemies

    def by_tag(self, tag):
        return [e for e in self._enemies if tag in e.tags]


class _StubTileMap:
    """Enemies cache a tilemap ref; nothing here paths, so it stays inert."""
    balance = {}


def make_enemy(cls, col, row, hp=None):
    e = cls(col, row, ENEMIES_BAL, _StubTileMap())
    if hp is not None:
        e.get_component(Health).hp = hp
    return e


def make_cs():
    # 1 zoom keeps the arithmetic checkable by hand.
    cs = load_coordinate_system(REPO / "data")
    cs.camera.zoom = 1
    cs.camera.pan_x = cs.camera.pan_y = 0
    return cs


def submit(enemies):
    """Run the bar pass over `enemies`; return (renderer, cs)."""
    fm = FloaterManager(UI_BAL, CORE_BAL)
    r, cs = RecordingRenderer(), make_cs()
    fm.submit_enemy_hp_bars(r, cs, FakeScene(enemies))
    return r, cs


class TestVisibilityGate(unittest.TestCase):
    def test_full_hp_enemy_draws_nothing(self):
        r, _ = submit([make_enemy(Enemy, 4, 4)])
        self.assertEqual(r.bars(), [])

    def test_damaged_enemy_draws_a_bar(self):
        e = make_enemy(Enemy, 4, 4)
        e.get_component(Health).hp = e.get_component(Health).max_hp - 1
        r, _ = submit([e])
        self.assertEqual(len(r.bars()), 2)  # red under-bar + green fill

    def test_dead_enemy_drops_its_bar_immediately(self):
        e = make_enemy(Enemy, 4, 4, hp=0)
        self.assertFalse(e.alive)
        r, _ = submit([e])
        self.assertEqual(r.bars(), [])


class TestBarGeometry(unittest.TestCase):
    def test_fill_width_tracks_the_hp_ratio(self):
        e = make_enemy(Enemy, 4, 4)
        health = e.get_component(Health)
        health.hp = health.max_hp // 4
        r, _ = submit([e])
        under, fill = r.bars()
        self.assertEqual(under[2], Enemy.HP_BAR_W)
        self.assertEqual(fill[2], int(Enemy.HP_BAR_W * health.hp / health.max_hp))
        self.assertLess(fill[2], under[2])

    def test_bar_sits_above_the_tile_centre_and_is_camera_anchored(self):
        e = make_enemy(Enemy, 4, 4, hp=1)
        r, cs = submit([e])
        (x, y, w, h), _ = r.bars()
        cx, cy = cs.world_to_screen(4.5, 4.5)
        self.assertEqual((x, y), (int(cx - w / 2), int(cy) - Enemy.HP_BAR_LIFT))
        self.assertEqual((w, h), (Enemy.HP_BAR_W, Enemy.HP_BAR_H))

    def test_lift_scales_with_zoom_but_the_bar_does_not(self):
        """The sprite grows with the camera, so the bar has to lift further to
        stay clear of its head — while staying a fixed screen size."""
        fm = FloaterManager(UI_BAL, CORE_BAL)
        seen = {}
        for zoom in (1, 2):
            e = make_enemy(Enemy, 4, 4, hp=1)
            r, cs = RecordingRenderer(), make_cs()
            cs.camera.zoom = zoom
            fm.submit_enemy_hp_bars(r, cs, FakeScene([e]))
            x, y, w, h = r.bars()[0]
            cy = cs.world_to_screen(4.5, 4.5)[1]
            seen[zoom] = (int(cy) - y, w, h)
        self.assertEqual(seen[1], (Enemy.HP_BAR_LIFT, 14, 2))
        self.assertEqual(seen[2], (Enemy.HP_BAR_LIFT * 2, 14, 2))

    def test_per_type_widths_and_lifts(self):
        """Each type's bar is sized and lifted for ITS sprite — the shipped
        walker sheet is 22x26, the boss's 72x56 (prototype values)."""
        got = {}
        for cls, col, row in ((Enemy, 2, 2), (Raider, 4, 4),
                              (SiegeCannon, 6, 6), (Boss, 8, 8)):
            e = make_enemy(cls, col, row, hp=1)
            r, cs = submit([e])
            x, y, w, h = r.bars()[0]
            got[cls.__name__] = (w, h, int(cs.world_to_screen(
                col + 0.5, row + 0.5)[1]) - y)
        self.assertEqual(got, {"Enemy": (14, 2, 26), "Raider": (14, 2, 26),
                               "SiegeCannon": (24, 2, 28), "Boss": (48, 4, 48)})


class TestStacking(unittest.TestCase):
    def test_bars_on_one_tile_stack_upward(self):
        enemies = [make_enemy(Enemy, 5, 5, hp=1) for _ in range(3)]
        r, _ = submit(enemies)
        unders = r.bars()[::2]   # skip each fill rect
        self.assertEqual(len(unders), 3)
        xs = {u[0] for u in unders}
        self.assertEqual(len(xs), 1)                  # same column
        ys = [u[1] for u in unders]
        self.assertEqual(ys, [ys[0], ys[0] - _ENEMY_BAR_STACK,
                              ys[0] - 2 * _ENEMY_BAR_STACK])

    def test_full_hp_enemy_consumes_no_slot(self):
        """Compact slots (our divergence): the healthy enemy in the middle
        must NOT leave a gap in the stack."""
        enemies = [make_enemy(Enemy, 5, 5, hp=1),
                   make_enemy(Enemy, 5, 5),          # full HP — no bar
                   make_enemy(Enemy, 5, 5, hp=1)]
        r, _ = submit(enemies)
        unders = r.bars()[::2]
        self.assertEqual(len(unders), 2)
        self.assertEqual(unders[1][1], unders[0][1] - _ENEMY_BAR_STACK)

    def test_enemies_on_different_tiles_do_not_stack(self):
        """Separate tiles are separate stacks — each bar sits at slot 0 of its
        own tile, never lifted by a neighbour's."""
        r, cs = submit([make_enemy(Enemy, 5, 5, hp=1),
                        make_enemy(Enemy, 8, 2, hp=1)])
        unders = r.bars()[::2]
        self.assertEqual(len(unders), 2)
        for (x, y, _, _), (col, row) in zip(unders, ((5, 5), (8, 2))):
            cx, cy = cs.world_to_screen(col + 0.5, row + 0.5)
            # slot 0 of its own stack — no neighbour's offset applied
            self.assertEqual(y, int(cy) - Enemy.HP_BAR_LIFT)
            self.assertEqual(x, int(cx - Enemy.HP_BAR_W / 2))

    def test_grouping_rounds_to_the_nearest_tile(self):
        """Fractional walkers drifting around the same tile centre still
        share one stack (prototype: group by nearest tile)."""
        a = make_enemy(Enemy, 5, 5, hp=1)
        b = make_enemy(Enemy, 5, 5, hp=1)
        b.transform.wx, b.transform.wy = 5.2, 4.8   # same rounded tile
        r, _ = submit([a, b])
        unders = r.bars()[::2]
        self.assertEqual(len(unders), 2)
        self.assertEqual(unders[1][1] - unders[0][1], -_ENEMY_BAR_STACK)


class TestBoss(unittest.TestCase):
    def test_boss_gets_exactly_one_overhead_bar(self):
        """The boss is tagged "enemy" AND "boss"; the enemy pass owns its
        overhead bar, and `submit_boss_bars` no longer draws a second one."""
        boss = make_enemy(Boss, 6, 6, hp=1)
        self.assertIn("enemy", boss.tags)
        self.assertIn("boss", boss.tags)
        r, _ = submit([boss])
        self.assertEqual(len(r.bars()), 2)          # one bar = under + fill
        self.assertEqual(r.bars()[0][2], Boss.HP_BAR_W)


if __name__ == "__main__":
    unittest.main()
