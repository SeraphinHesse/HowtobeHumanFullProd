"""The gold buff arrow and the red debuff arrow (BossUpgradeTimelinePLAN D20).

``FloaterManager.submit_buff_arrows`` / ``submit_debuff_arrows`` are gated on
``game.enemies.components.buff_signs(enemy, "move_speed")`` — **two independent
booleans, never the two signs of one netted aggregate**. That distinction is
the whole point of the follow-up fix this module pins: an enemy simultaneously
buffed by a Drummer AND slowed by a mortar is a real state, and hiding
whichever effect loses the sum (or both, on an exact cancel) is what the
earlier `buff_total`-gated version did.

The other half is GEOMETRY: the two badges sit in two genuinely different
spots — gold centred ABOVE the hp bar, red to its LEFT, vertically centred on
it — so they can be shown together without overlapping each other or the bar.

Headless/pure, the ``test_enemy_hp_bars.py`` pattern: real enemies + a real
``CoordinateSystem`` over the pinned fixture snapshot, a ``RecordingRenderer``
instead of a window, and a ``FakeScene`` that only answers ``by_tag("enemy")``.
``renderer.assets`` is pinned per test rather than inherited: whether the two
``vfx_*_arrow`` slots have imported art decides the sprite-vs-triangle branch,
and "the slot has no art" is exactly the assumption ``data/CLAUDE.md`` says
put 18 tests permanently in the red.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.coords import load_coordinate_system
from engine.core import Health
from engine.render import HudLines, HudRect, HudSprite
from game.core import load_balance
from game.enemies import create_enemy
from game.enemies.components import BuffState, apply_slow, buff_signs
from game.map.tile_map import TileMap
from game.ui import effects
from game.ui.effects import (
    BUFF_ARROW_SLOT, DEBUFF_ARROW_SLOT, FloaterManager,
)

MAPBAL = load_balance(FIXTURE_DATA, "map")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")
ENEM_BAL = load_balance(FIXTURE_DATA, "enemies")

DRUMMER_SOURCE = "a-drummer-uuid"
SLOW_SOURCE = "boss_upgrade:mortar_slow"


class _NoArt:
    """An asset store in which NO slot has imported art — the E-37 fallback
    branch. PIN, don't assume: the shipped manifest may gain a
    ``vfx_buff_arrow`` sheet any day, which would silently flip every geometry
    assertion here onto the ``HudSprite`` branch."""

    #: a fixed sheet size, so `_sprite_top` (and therefore the hp bar and both
    #: badges) lands on hand-checkable arithmetic instead of on whatever the
    #: shipped walker sheet is cut at this month.
    FRAME = (22, 32)

    def animation_total_ms(self, _slot, _anim):
        return None

    def entry(self, _slot):
        return None

    def frame_size(self, _slot):
        return self.FRAME

    def anchor(self, _slot, _name):
        # No authored anchor -> `anchor_world_point` returns None -> both
        # passes take the `_sprite_top` fallback baseline, which is what this
        # module measures (`test_hp_bar_anchors.py` owns the anchored path).
        return None


class _AllArt(_NoArt):
    """...and its twin, in which both arrow slots DO have art."""

    def animation_total_ms(self, slot, _anim):
        return 100 if slot in (BUFF_ARROW_SLOT, DEBUFF_ARROW_SLOT) else None


class RecordingRenderer:
    def __init__(self, assets=None):
        self.items = []
        self.assets = assets if assets is not None else _NoArt()

    def submit_hud(self, item):
        self.items.append(item)

    def triangles(self):
        return [i for i in self.items if isinstance(i, HudLines)]

    def sprites(self):
        return [i for i in self.items if isinstance(i, HudSprite)]

    def rects(self):
        return [i.rect for i in self.items if isinstance(i, HudRect)]


class FakeScene:
    def __init__(self, enemies):
        self._enemies = enemies

    def by_tag(self, tag):
        return [e for e in self._enemies if tag in e.tags]


def make_cs():
    cs = load_coordinate_system(FIXTURE_DATA)
    cs.camera.zoom = 1
    cs.camera.pan_x = cs.camera.pan_y = 0
    return cs


def synth():
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth", cols=12, rows=12,
        legend={}, terrain=[list("b" * 12) for _ in range(12)],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


TM = synth()


def make_enemy(col=4, row=4, buffed=False, slowed=False, alive=True):
    e = create_enemy("standard", col, row, ENEM_BAL, TM)
    if buffed:
        # A Drummer's aura: the one thing that lifts move_speed today.
        e.get_component(BuffState).apply(DRUMMER_SOURCE, 0.0, 0.0, 0.5, 0.0)
    if slowed:
        apply_slow(e, SLOW_SOURCE, 0.2, 2.5)
    if not alive:
        e.get_component(Health).damage(10 ** 9)
    return e


def submit(enemies, assets=None):
    """Both arrow passes over ``enemies``; returns (renderer, cs, fm)."""
    fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
    r, cs = RecordingRenderer(assets), make_cs()
    scene = FakeScene(enemies)
    fm.submit_buff_arrows(r, cs, scene)
    gold = len(r.items)
    fm.submit_debuff_arrows(r, cs, scene)
    return r, cs, gold


# ---------------------------------------------------------------------------
# buff_signs — the gate, read INDEPENDENTLY (never a netted sign)
# ---------------------------------------------------------------------------
class TestBuffSigns(unittest.TestCase):
    def test_nothing_applied_reads_as_neither(self):
        self.assertEqual(buff_signs(make_enemy(), "move_speed"),
                         (False, False))

    def test_a_buff_alone_reads_positive_only(self):
        self.assertEqual(buff_signs(make_enemy(buffed=True), "move_speed"),
                         (True, False))

    def test_a_slow_alone_reads_negative_only(self):
        self.assertEqual(buff_signs(make_enemy(slowed=True), "move_speed"),
                         (False, True))

    def test_both_at_once_read_as_BOTH(self):
        e = make_enemy(buffed=True, slowed=True)
        self.assertEqual(buff_signs(e, "move_speed"), (True, True))

    def test_an_exact_cancel_still_reads_as_both(self):
        """The regression the netted-aggregate gate could not express: two
        contributions that sum to exactly 0 are still two real effects."""
        e = make_enemy()
        e.get_component(BuffState).apply(DRUMMER_SOURCE, 0.0, 0.0, 0.2, 0.0)
        apply_slow(e, SLOW_SOURCE, 0.2, 2.5)
        from game.enemies.components import buff_total
        self.assertAlmostEqual(buff_total(e, "move_speed"), 0.0)
        self.assertEqual(buff_signs(e, "move_speed"), (True, True))

    def test_an_owner_with_no_buff_state_reads_as_neither(self):
        self.assertEqual(buff_signs(None, "move_speed"), (False, False))


# ---------------------------------------------------------------------------
# The four gating cases
# ---------------------------------------------------------------------------
class TestArrowGating(unittest.TestCase):
    def _counts(self, **kw):
        r, _cs, gold = submit([make_enemy(**kw)])
        tris = r.triangles()
        return len(tris[:gold]), len(tris[gold:])

    def test_neither_draws_nothing(self):
        self.assertEqual(self._counts(), (0, 0))

    def test_gold_only(self):
        self.assertEqual(self._counts(buffed=True), (1, 0))

    def test_red_only(self):
        self.assertEqual(self._counts(slowed=True), (0, 1))

    def test_BOTH_arrows_show_at_once(self):
        self.assertEqual(self._counts(buffed=True, slowed=True), (1, 1))

    def test_a_dead_enemy_gets_neither(self):
        self.assertEqual(self._counts(buffed=True, slowed=True, alive=False),
                         (0, 0))

    def test_a_dmg_only_aura_shows_no_gold_arrow(self):
        """`submit_buff_arrows` is narrowed to a POSITIVE move_speed
        contribution — a Drummer lifting only dmg/hp is not a speed buff."""
        e = make_enemy()
        e.get_component(BuffState).apply(DRUMMER_SOURCE, 0.0, 0.5, 0.0, 0.3)
        r, _cs, gold = submit([e])
        self.assertEqual(r.triangles(), [])

    def test_the_colours_are_distinct(self):
        r, _cs, gold = submit([make_enemy(buffed=True, slowed=True)])
        tris = r.triangles()
        self.assertEqual(tris[0].color, effects._BUFF_ARROW_GOLD)
        self.assertEqual(tris[1].color, effects._DEBUFF_ARROW_RED)
        self.assertNotEqual(tris[0].color, tris[1].color)

    def test_every_slowed_enemy_gets_its_own_badge(self):
        enemies = [make_enemy(col=c, slowed=True) for c in (2, 4, 6)]
        r, _cs, gold = submit(enemies)
        self.assertEqual(len(r.triangles()[gold:]), 3)


# ---------------------------------------------------------------------------
# Geometry — the two badges never overlap each other or the bar
# ---------------------------------------------------------------------------
class TestArrowGeometry(unittest.TestCase):
    def _bar_and_arrows(self):
        """The hp bar's own rect plus both badges, for ONE enemy carrying
        both effects and enough damage to make the bar draw."""
        e = make_enemy(buffed=True, slowed=True)
        health = e.get_component(Health)
        health.hp = health.max_hp // 2
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        r, cs = RecordingRenderer(), make_cs()
        scene = FakeScene([e])
        fm.submit_enemy_hp_bars(r, cs, scene)
        bar = r.rects()[0]                       # the red under-bar
        r.items.clear()
        fm.submit_buff_arrows(r, cs, scene)
        fm.submit_debuff_arrows(r, cs, scene)
        gold, red = r.triangles()
        return bar, gold, red

    @staticmethod
    def _bounds(tri):
        xs = [p[0] for p in tri.points]
        ys = [p[1] for p in tri.points]
        return min(xs), min(ys), max(xs), max(ys)

    def test_gold_sits_above_the_bar_and_never_overlaps_it(self):
        (bx, by, bw, bh), gold, _red = self._bar_and_arrows()
        _gx0, _gy0, _gx1, gy1 = self._bounds(gold)
        self.assertLessEqual(gy1, by, "the gold badge must end at or above "
                                      "the hp bar's top edge")

    def test_red_sits_to_the_LEFT_of_the_bar_and_never_overlaps_it(self):
        (bx, by, bw, bh), _gold, red = self._bar_and_arrows()
        rx0, ry0, rx1, ry1 = self._bounds(red)
        self.assertLess(rx1, bx, "the red badge must end left of the bar's "
                                 "left edge")
        # ...and it rides the bar's own vertical band, not above it
        self.assertGreater(ry1, by)

    def test_the_two_badges_never_overlap_each_other(self):
        _bar, gold, red = self._bar_and_arrows()
        gx0, gy0, gx1, gy1 = self._bounds(gold)
        rx0, ry0, rx1, ry1 = self._bounds(red)
        overlaps = (gx0 < rx1 and rx0 < gx1) and (gy0 < ry1 and ry0 < gy1)
        self.assertFalse(overlaps, f"gold {(gx0, gy0, gx1, gy1)} overlaps "
                                   f"red {(rx0, ry0, rx1, ry1)}")

    def test_both_badges_are_the_same_size(self):
        _bar, gold, red = self._bar_and_arrows()
        gx0, gy0, gx1, gy1 = self._bounds(gold)
        rx0, ry0, rx1, ry1 = self._bounds(red)
        self.assertEqual((gx1 - gx0, gy1 - gy0), (rx1 - rx0, ry1 - ry0))
        self.assertEqual(gx1 - gx0, effects._BUFF_ARROW_W)
        self.assertEqual(gy1 - gy0, effects._BUFF_ARROW_H)

    def test_a_badge_is_camera_anchored(self):
        """Both passes anchor through ``world_to_screen``, so a pan moves the
        badge with the enemy rather than leaving it parked on screen."""
        def red_x(pan):
            fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
            r, cs = RecordingRenderer(), make_cs()
            cs.camera.pan_x = pan
            fm.submit_debuff_arrows(r, cs, FakeScene([make_enemy(slowed=True)]))
            return self._bounds(r.triangles()[0])[0]

        self.assertNotEqual(red_x(0), red_x(120))


# ---------------------------------------------------------------------------
# E-37: imported art wins, no art falls back to the procedural triangle
# ---------------------------------------------------------------------------
class TestSwappableArt(unittest.TestCase):
    def test_no_art_draws_procedural_triangles(self):
        r, _cs, _gold = submit([make_enemy(buffed=True, slowed=True)],
                               assets=_NoArt())
        self.assertEqual(len(r.triangles()), 2)
        self.assertEqual(r.sprites(), [])

    def test_imported_art_draws_sprites_from_the_two_vfx_slots(self):
        r, _cs, _gold = submit([make_enemy(buffed=True, slowed=True)],
                               assets=_AllArt())
        self.assertEqual(r.triangles(), [])
        self.assertEqual([s.slot_key for s in r.sprites()],
                         [BUFF_ARROW_SLOT, DEBUFF_ARROW_SLOT])

    def test_the_sprite_occupies_the_same_span_as_the_triangle(self):
        """Both branches must cover ``[y - H, y]`` — otherwise swapping art in
        would move the badge relative to whatever ``y`` was chosen to clear."""
        e = make_enemy(slowed=True)
        tri = submit([e], assets=_NoArt())[0].triangles()[0]
        sprite = submit([e], assets=_AllArt())[0].sprites()[0]
        xs = [p[0] for p in tri.points]
        ys = [p[1] for p in tri.points]
        self.assertEqual(sprite.dest, (min(xs), min(ys)))
        self.assertEqual(sprite.size,
                         (effects._BUFF_ARROW_W, effects._BUFF_ARROW_H))

    def test_a_renderer_with_no_asset_store_still_draws(self):
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)

        class _Bare:
            def __init__(self):
                self.items = []

            def submit_hud(self, item):
                self.items.append(item)

        r = _Bare()
        fm.submit_debuff_arrows(r, make_cs(), FakeScene([make_enemy(
            slowed=True)]))
        self.assertEqual(len(r.items), 1)


if __name__ == "__main__":
    unittest.main()
