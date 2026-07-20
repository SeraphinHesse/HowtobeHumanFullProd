"""ESV-1 §1.7 — the `hp_bar` manifest anchor composes with the existing
baseline rather than replacing it (D3):

- **Enemies** — added to `_sprite_top`'s already-fitted result (the footprint
  fit stays load-bearing; a raw sheet-pixel lift would float for a
  downscaled unit, the exact ER-1 bug `_sprite_top` exists to avoid).
- **Buildings** — added on top of the flat `cy - tile_h*zoom` baseline
  (`submit_hp_bars` has no `_sprite_top` fit to compose with, and this phase
  does not introduce one — that would be a visible behaviour change, out of
  scope per the brief).

Absent anchor ⇒ `(0, 0)` ⇒ both expressions reproduce their pre-ESV-1 value
exactly. Reuses `test_enemy_hp_bars.py`'s harness (real coords, a recording
renderer instead of a window).
"""
import dataclasses
import unittest

from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.test_enemy_hp_bars import (
    ASSETS, FakeScene, RecordingRenderer, make_cs, make_enemy,
)

from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.core import GameObject, Health, SpriteAnimator, Transform
from engine.render import fit_factor
from game.anchors import screen_offset
from game.core import load_balance
from game.enemies.enemy import Enemy, Formation
from game.ui.effects import FloaterManager, _sprite_top

ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")

_BUILDING_BAR_W, _BUILDING_BAR_H = 28, 4   # game/ui/effects.py submit_hp_bars


def store_with_hp_bar_anchor(slot_key, xy):
    """A copy of the real (committed) manifest with one entry's `anchors`
    overridden to carry an `hp_bar` point — the rest of that entry (frame
    size, sheet, rows) untouched, so the drawn sprite size is unaffected."""
    manifest = load_manifest(FIXTURE_DATA / "sprites" / "asset_manifest.json")
    entry = manifest.entry(slot_key)
    new_entry = dataclasses.replace(
        entry, anchors=(("hp_bar", tuple(int(v) for v in xy)),))
    manifest = manifest.override(slot_key, new_entry)
    return AssetStore(manifest=manifest, registry=load_registry(FIXTURE_DATA),
                      sprites_dir=FIXTURE_DATA / "sprites")


class TestEnemyHpBarAnchor(unittest.TestCase):
    def _submit(self, assets, cls=Enemy, hp=1):
        e = make_enemy(cls, 4, 4, hp=hp)
        fm = FloaterManager(UI_BAL, CORE_BAL)
        r, cs = RecordingRenderer(assets), make_cs()
        fm.submit_enemy_hp_bars(r, cs, FakeScene([e]))
        return r.bars(), r, cs, e

    def test_absent_anchor_reproduces_the_current_expression(self):
        with_default, _r, _cs, _e = self._submit(ASSETS)
        without_block = store_with_hp_bar_anchor(Enemy.DEFAULT_SLOT, (0, 0))
        with_zero, _r2, _cs2, _e2 = self._submit(without_block)
        self.assertEqual(with_default, with_zero)

    def test_anchor_composes_with_the_footprint_fit(self):
        """D3, and the exact ER-1 bug class `_sprite_top` exists to avoid: the
        offset must ride the SAME downscale `_sprite_top` uses, not a raw
        sheet-pixel lift. `Formation`'s slot (128px) is wider than the tile
        (64px), so its footprint fit is measurably < 1 — verified below by
        number, not assumed from the type/footprint balancing value (the
        fixture's `Formation.footprint` is 1, a known fixture/doc mismatch
        outside this phase's scope; what matters here is the SLOT's frame_w
        vs tile_w, which drives `fit_factor` regardless)."""
        store = store_with_hp_bar_anchor(Formation.DEFAULT_SLOT, (12, -6))
        # Formation "dies" (D4 death_spawn) at half HP — damaged but ALIVE,
        # unlike the other enemy types' hp=1 convenience.
        bars, r, cs, e = self._submit(store, Formation, hp=300)
        (x, y, w, h), _fill = bars

        zoom = cs.camera.zoom
        cx, cy = cs.world_to_screen(4.5, 4.5)
        anim = e.get_component(SpriteAnimator)
        frame_w, _frame_h = store.frame_size(anim.slot_key)
        s = fit_factor(frame_w, cs.geometry.tile_w, anim.fit_tiles) * anim.scale
        self.assertLess(s, 1.0)   # the fixture really does downscale this sprite

        top = _sprite_top(r, cs, e, cy, zoom)
        dsx, dsy = screen_offset(store, cs, e, "hp_bar", zoom)
        self.assertNotEqual((dsx, dsy), (0.0, 0.0))   # the anchor really moved it
        expected_x = int(cx - Formation.HP_BAR_W / 2 + dsx)
        expected_y = (int(top - Formation.HP_BAR_PAD * zoom + dsy)
                      - Formation.HP_BAR_H)
        self.assertEqual((x, y), (expected_x, expected_y))
        self.assertEqual((w, h), (Formation.HP_BAR_W, Formation.HP_BAR_H))

        # And it genuinely differs from a RAW un-scaled pixel lift (the
        # composition this test exists to pin, not just "some offset moved
        # it") — a buggy read-site that dropped the `s` factor and applied
        # the authored anchor pixel-for-pixel would land here instead.
        raw_pixel_y = (int(top - Formation.HP_BAR_PAD * zoom - 6 * zoom)
                       - Formation.HP_BAR_H)
        self.assertNotEqual(y, raw_pixel_y)


class TestBuildingHpBarAnchor(unittest.TestCase):
    @staticmethod
    def _stub_building(slot_key):
        return GameObject(
            name="stub", tags=("building",),
            transform=Transform(wx=4.0, wy=4.0),
            components=[Health(max_hp=10, hp=5), SpriteAnimator(slot_key=slot_key)])

    def _submit(self, assets, slot_key):
        b = self._stub_building(slot_key)
        fm = FloaterManager(UI_BAL, CORE_BAL)
        r, cs = RecordingRenderer(assets), make_cs()
        fm.submit_hp_bars(r, cs, FakeScene([b]))
        return r.bars(), cs, b

    def test_absent_anchor_reproduces_the_flat_baseline(self):
        bars, cs, _b = self._submit(ASSETS, "no_such_slot_no_anchor")
        under = bars[0]   # bg, fill, border (submit_hp_bars passes border=)
        cx, cy = cs.world_to_screen(4.5, 4.5)
        zoom = cs.camera.zoom
        tile_h = cs.geometry.tile_h
        self.assertEqual(
            (under[0], under[1]),
            (int(cx - _BUILDING_BAR_W / 2), int(cy - tile_h * zoom)))

    def test_anchor_composes_with_the_flat_baseline(self):
        store = store_with_hp_bar_anchor(Enemy.DEFAULT_SLOT, (8, -20))
        bars, cs, b = self._submit(store, Enemy.DEFAULT_SLOT)
        under = bars[0]   # bg, fill, border (submit_hp_bars passes border=)

        zoom = cs.camera.zoom
        tile_h = cs.geometry.tile_h
        cx, cy = cs.world_to_screen(4.5, 4.5)
        dsx, dsy = screen_offset(store, cs, b, "hp_bar", zoom)
        self.assertNotEqual((dsx, dsy), (0.0, 0.0))
        expected_x = int(cx - _BUILDING_BAR_W / 2 + dsx)
        expected_y = int(cy - tile_h * zoom + dsy)
        self.assertEqual((under[0], under[1]), (expected_x, expected_y))


if __name__ == "__main__":
    unittest.main()
