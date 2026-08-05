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
from tools.tests.fixture_data import FIXTURE_DATA

from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import Health, SpriteAnimator
from engine.render import HudRect
from game.core import load_balance
from game.enemies.enemy import Boss, Enemy, Raider, SiegeCannon
from game.ui.effects import _ENEMY_BAR_STACK, FloaterManager

ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")  # ESV-3a: FloaterManager's 3rd arg

# The real store, so the bar pass sizes each sprite off the SHIPPED sheets
# (walker 22x26, raider 12x18, siege 36x28, boss era 0 72x56) exactly as the
# renderer will. frame_size() is pure metadata — no surface is ever loaded.
ASSETS = AssetStore(
    manifest=load_manifest(FIXTURE_DATA / "sprites" / "asset_manifest.json"),
    registry=load_registry(FIXTURE_DATA),
    sprites_dir=FIXTURE_DATA / "sprites")
TILE_W = 64


def render_fit(cls, era=0):
    """``(footprint, sprite_scale)`` for `cls` at `era`, through the class's own
    BR-1 ``resolve_fit`` seam — which knows WHERE the pair lives (flat at the
    type root for every type but the Boss, whose is per-era in ``stats[era]``).
    `era` 0 because ``make_enemy`` constructs at the constructor default, the
    same era ``DEFAULT_SLOT`` is the art for."""
    block = ENEMIES_BAL["EnemyTypes"]
    for seg in cls.STAT_SUBTREE:
        block = block[seg]
    return cls.resolve_fit(block, era)


def drawn_sprite_h(cls, zoom=1):
    """The on-screen height `cls`'s sprite renders at — re-derived here from the
    sheet + balance rather than by calling the engine, so this test really pins
    ER-1's rule: downscale-only footprint fit, never the raw sheet height."""
    footprint, sprite_scale = render_fit(cls)
    frame_w, frame_h = ASSETS.frame_size(cls.DEFAULT_SLOT)
    fit = min(1.0, (footprint * TILE_W) / frame_w)
    return frame_h * zoom * fit * sprite_scale


def expected_bar_bottom(cls, cy, zoom=1):
    """Where the bar's BOTTOM edge must land: HP_BAR_PAD above the drawn head.

    `cy` is the ANCHOR tile's centre; a multi-tile unit draws on its BLOCK centre,
    (footprint-1)*tile_h/2 lower (ER-5). Every shipping enemy is footprint 1, so
    this term is 0 for all of them — it is exercised by the explicit 2-tile case
    in TestBarGeometry.
    """
    shift = (render_fit(cls)[0] - 1) / 2 * 32 * zoom       # tile_h = 32
    return int(cy + shift - drawn_sprite_h(cls, zoom) / 2 - cls.HP_BAR_PAD * zoom)


class RecordingRenderer:
    """``submit_bar`` only ever emits through ``submit_hud``; ``assets`` is what
    the bar pass asks for a slot's frame size (the real Renderer exposes it)."""

    def __init__(self, assets=ASSETS):
        self.items = []
        self.assets = assets

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
    cs = load_coordinate_system(FIXTURE_DATA)
    cs.camera.zoom = 1
    cs.camera.pan_x = cs.camera.pan_y = 0
    return cs


def submit(enemies):
    """Run the bar pass over `enemies`; return (renderer, cs)."""
    fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
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
    def test_a_multi_tile_enemy_bar_rides_its_block_centre(self):
        """ER-5: the sprite of a footprint-N unit is drawn on its block centre,
        not on the anchor tile — so the bar hanging off its head must move with
        it. A walker's 22px-wide sheet already fits inside one tile, so raising
        fit_tiles cannot change the DRAWN size here: the only thing that moves is
        the block shift, half a tile-height down."""
        def bar_top(fit_tiles):
            e = make_enemy(Enemy, 4, 4)
            health = e.get_component(Health)
            health.hp = health.max_hp - 1
            e.get_component(SpriteAnimator).fit_tiles = fit_tiles
            r, _ = submit([e])
            under, _fill = r.bars()
            return under[0], under[1]

        x1, y1 = bar_top(1.0)
        x2, y2 = bar_top(2.0)
        self.assertEqual(x2, x1)            # iso: no horizontal shift, ever
        self.assertEqual(y2 - y1, 16)       # (2-1) * tile_h/2

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
        self.assertEqual(x, int(cx - w / 2))
        self.assertEqual(y + h, expected_bar_bottom(Enemy, cy))
        self.assertEqual((w, h), (Enemy.HP_BAR_W, Enemy.HP_BAR_H))

    def test_lift_scales_with_zoom_but_the_bar_does_not(self):
        """The sprite grows with the camera, so the bar has to lift further to
        stay clear of its head — while staying a fixed screen size."""
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        seen = {}
        for zoom in (1, 2):
            e = make_enemy(Enemy, 4, 4, hp=1)
            r, cs = RecordingRenderer(), make_cs()
            cs.camera.zoom = zoom
            fm.submit_enemy_hp_bars(r, cs, FakeScene([e]))
            x, y, w, h = r.bars()[0]
            cy = cs.world_to_screen(4.5, 4.5)[1]
            self.assertEqual(y + h, expected_bar_bottom(Enemy, cy, zoom))
            seen[zoom] = (int(cy) - y, w, h)
        self.assertEqual(seen[1][1:], (14, 2))
        self.assertEqual(seen[2][1:], (14, 2))       # bar stays fixed-size
        self.assertGreater(seen[2][0], seen[1][0])   # ...but lifts further

    def test_bar_hangs_off_the_DRAWN_sprite_not_the_sheet(self):
        """ER-1 regression: sizes come from the tile footprint now, so the lift
        must be measured off the sprite as drawn. A per-class constant tuned to
        sheet pixels (the old HP_BAR_LIFT) leaves the boss's bar floating."""
        for cls, col, row in ((Enemy, 2, 2), (Raider, 4, 4),
                              (SiegeCannon, 6, 6), (Boss, 8, 8)):
            e = make_enemy(cls, col, row, hp=1)
            r, cs = submit([e])
            x, y, w, h = r.bars()[0]
            cy = cs.world_to_screen(col + 0.5, row + 0.5)[1]
            with self.subTest(enemy=cls.__name__):
                self.assertEqual((w, h), (cls.HP_BAR_W, cls.HP_BAR_H))
                self.assertEqual(y + h, expected_bar_bottom(cls, cy))
                # and it really does hug the head — never floats off it
                gap = (cy - drawn_sprite_h(cls) / 2) - (y + h)
                self.assertAlmostEqual(gap, cls.HP_BAR_PAD, delta=1.0)

    def test_boss_bar_follows_its_era_sprite(self):
        """The boss sheet grows per era (72x56 -> 124x96) but every era now FITS
        to one tile, so the drawn heights converge — and the bar tracks that,
        instead of the old 48px constant that assumed the 56px era-0 sheet."""
        boss = make_enemy(Boss, 6, 6, hp=1)
        r, cs = submit([boss])
        _x, y, _w, h = r.bars()[0]
        cy = cs.world_to_screen(6.5, 6.5)[1]
        sprite_top = cy - drawn_sprite_h(Boss) / 2
        self.assertLess(abs((y + h) - (sprite_top - Boss.HP_BAR_PAD)), 1.0)
        # the pre-ER-1 constant would have parked it ~23px above the head
        self.assertGreater(y + h, int(cy) - 48 + 10)


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
        for (x, y, _, h), (col, row) in zip(unders, ((5, 5), (8, 2))):
            cx, cy = cs.world_to_screen(col + 0.5, row + 0.5)
            # slot 0 of its own stack — no neighbour's offset applied
            self.assertEqual(y + h, expected_bar_bottom(Enemy, cy))
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
