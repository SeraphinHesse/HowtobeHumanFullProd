"""fix-anchor-origin-parity §2.3 — the `hp_bar` manifest anchor "wins
outright" (the designer's decision), superseding ESV-1 §1.7's compose rule:

- **Anchor authored** — the bar's reference point REPLACES the pre-anchor
  baseline outright (`cs.world_to_screen(game.anchors.anchor_world_point(
  ...))`), for both enemies and buildings — never composed on top of
  `_sprite_top`/the flat `cy - tile_h*zoom` baseline (ESV-1's old D3 rule).
- **No anchor** — both expressions reproduce their pre-fix value exactly
  (`_sprite_top`'s footprint fit for enemies, the flat baseline for
  buildings) — D3's compose rule only ever mattered when an anchor WAS
  authored, so removing it changes nothing here.

Reuses `test_enemy_hp_bars.py`'s harness (real coords, a recording renderer
instead of a window). Expected points are derived independently — via
`cs.world_to_screen`/`engine.render.fit_factor`/`block_center_offset`
composed by hand, never by calling `game.anchors.anchor_world_point`/
`engine.render.sprite_anchor_screen` (the functions under test, transitively,
through `FloaterManager.submit_*_hp_bars`) — the exact trap that let this
family of bug ship green (docs/briefs/fix-anchor-origin-parity.md §1.2).
"""
import dataclasses
import unittest

from tools.tests.fixture_data import FIXTURE_DATA
from tools.tests.test_enemy_hp_bars import (
    ASSETS, FakeScene, RecordingRenderer, expected_bar_bottom, make_cs,
    make_enemy,
)

from engine.assets import load_manifest, load_registry
from engine.assets.store import AssetStore
from engine.core import GameObject, Health, SpriteAnimator, Transform
from engine.render.renderer import block_center_offset, fit_factor
from game.core import load_balance
from game.enemies.enemy import Enemy, Formation
from game.ui.effects import FloaterManager

ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")
CORE_BAL = load_balance(FIXTURE_DATA, "core")
UI_BAL = load_balance(FIXTURE_DATA, "ui")
VFX_BAL = load_balance(FIXTURE_DATA, "vfx")  # ESV-3a: FloaterManager's 3rd arg

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


def _hand_derived_anchor_screen_point(cs, wx, wy, frame_w, fit_tiles, scale,
                                      offset_xy, anchor_xy):
    """The SAME geometry `sprite_anchor_screen` computes, spelled out by hand
    from already-pinned primitives (`world_to_screen`, `fit_factor`,
    `block_center_offset`) — an INDEPENDENT re-derivation, never a call to
    `sprite_anchor_screen`/`anchor_world_point` themselves."""
    zoom = cs.camera.zoom
    c = block_center_offset(fit_tiles)
    px, py = cs.world_to_screen(wx + c, wy + c)
    s = fit_factor(frame_w, cs.geometry.tile_w, fit_tiles) * scale
    half_h = cs.geometry.tile_h / 2
    ox, oy = offset_xy
    ax, ay = anchor_xy
    return (px + (ox + ax) * zoom * s, py + half_h * zoom + (oy + ay) * zoom * s)


class TestEnemyHpBarAnchor(unittest.TestCase):
    def _submit(self, assets, cls=Enemy, hp=1):
        e = make_enemy(cls, 4, 4, hp=hp)
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
        r, cs = RecordingRenderer(assets), make_cs()
        fm.submit_enemy_hp_bars(r, cs, FakeScene([e]))
        return r.bars(), r, cs, e

    def test_absent_anchor_reproduces_the_current_expression(self):
        """No `hp_bar` anchor authored -> `_sprite_top`'s footprint-fitted
        baseline exactly, D3 unchanged. Pinned against `test_enemy_hp_bars
        .expected_bar_bottom` — an INDEPENDENT re-derivation of the drawn
        sprite's top edge from the sheet + balance data, not from
        `_sprite_top` itself. (fix-anchor-origin-parity note: a `[0, 0]`
        anchor is no longer equivalent to "absent" — "anchor wins outright"
        makes an authored `[0, 0]` a REAL point now, see
        `TestOffsetAnchorComposition` in `test_asset_anchors.py` — so this
        test exercises the SHIPPED manifest with no `hp_bar` key at all,
        never a `[0, 0]`-authored one.)"""
        bars, _r, cs, _e = self._submit(ASSETS)
        (x, y, w, h), _fill = bars
        cx, cy = cs.world_to_screen(4.5, 4.5)
        self.assertEqual(x, int(cx - w / 2))
        self.assertEqual(y + h, expected_bar_bottom(Enemy, cy))

    def test_anchor_replaces_the_footprint_fit_baseline_outright(self):
        """"Anchor wins outright" (fix-anchor-origin-parity, designer's
        decision): with an `hp_bar` anchor authored, the bar's reference
        point is the exact handle point — it no longer composes with
        `_sprite_top`'s footprint-fitted baseline (ESV-1's old D3 rule).
        `Formation`'s slot (128px) is wider than the tile (64px), so its
        footprint fit is measurably < 1 (ER-1) — the expected point below
        still rides that fit (`fit_factor` is composed inside `sprite_
        anchor_screen`/`anchor_world_point`, never bypassed), it just no
        longer ALSO adds `_sprite_top`'s own baseline underneath it."""
        store = store_with_hp_bar_anchor(Formation.DEFAULT_SLOT, (12, -6))
        # Formation "dies" (D4 death_spawn) at half HP — damaged but ALIVE,
        # unlike the other enemy types' hp=1 convenience.
        bars, r, cs, e = self._submit(store, Formation, hp=300)
        (x, y, w, h), _fill = bars

        anim = e.get_component(SpriteAnimator)
        frame_w, _frame_h = store.frame_size(anim.slot_key)
        s = fit_factor(frame_w, cs.geometry.tile_w, anim.fit_tiles) * anim.scale
        self.assertLess(s, 1.0)   # the fixture really does downscale this sprite

        wx, wy = e.transform.world_pos
        offset_xy = store.offset(anim.slot_key)
        sx, sy = _hand_derived_anchor_screen_point(
            cs, wx, wy, frame_w, anim.fit_tiles, anim.scale, offset_xy, (12, -6))
        expected_x = int(sx - Formation.HP_BAR_W / 2)
        expected_y = int(sy) - Formation.HP_BAR_H
        self.assertEqual((x, y), (expected_x, expected_y))
        self.assertEqual((w, h), (Formation.HP_BAR_W, Formation.HP_BAR_H))


class TestBuildingHpBarAnchor(unittest.TestCase):
    @staticmethod
    def _stub_building(slot_key):
        return GameObject(
            name="stub", tags=("building",),
            transform=Transform(wx=4.0, wy=4.0),
            components=[Health(max_hp=10, hp=5), SpriteAnimator(slot_key=slot_key)])

    def _submit(self, assets, slot_key):
        b = self._stub_building(slot_key)
        fm = FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)
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

    def test_anchor_replaces_the_flat_baseline_outright(self):
        """"Anchor wins outright": the flat `cy - tile_h*zoom` baseline
        (`submit_hp_bars` has no footprint fit to compose with) is REPLACED,
        not nudged, when an `hp_bar` anchor is authored."""
        store = store_with_hp_bar_anchor(Enemy.DEFAULT_SLOT, (8, -20))
        bars, cs, b = self._submit(store, Enemy.DEFAULT_SLOT)
        under = bars[0]   # bg, fill, border (submit_hp_bars passes border=)

        anim = b.get_component(SpriteAnimator)
        frame_w, _frame_h = store.frame_size(anim.slot_key)
        wx, wy = b.transform.world_pos
        offset_xy = store.offset(anim.slot_key)
        sx, sy = _hand_derived_anchor_screen_point(
            cs, wx, wy, frame_w, anim.fit_tiles, anim.scale, offset_xy, (8, -20))
        expected_x = int(sx - _BUILDING_BAR_W / 2)
        expected_y = int(sy)
        self.assertEqual((under[0], under[1]), (expected_x, expected_y))


if __name__ == "__main__":
    unittest.main()
