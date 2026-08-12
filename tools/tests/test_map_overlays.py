"""``game/ui/overlays.py`` — the TIER OVERVIEW toggle pill.

The third persistent bottom-left pill (beside RANGE and HEATMAP): when active
it tints every PLAYER-BUILT building's tile by its current IN-TIER level.
Covers the feature's two load-bearing promises —

1. **No mutual exclusion.** All three toggles are independent flags; flipping
   one through a synthetic ``hit()`` at that button's own coords never
   disturbs the other two.
2. **The right colour per LEVEL, not per tier** — read off the building's own
   ``TierState.current_level_in_tier`` (1-indexed), and the 3-colour cycle
   RESETS at every tier advance (a level-1 Slinger, tier 2, is the same gold
   as a level-1 Stone Thrower, tier 1) — with the base ("the hole") and any
   occupant carrying no ``TierState`` skipped rather than raising.

Plus the JSON label surface: ``btn_tier_overview`` is an id, so its default
``"TIERS"`` text is overridable through ``data/ui/screens/overlays.json`` for
free (the generic per-widget ``label`` override). (That default was
``"TIER OVERVIEW"``, and its sibling ``"HEATMAP"``, until the static-label-fit
check was taught to measure the font the game actually boots — see
``tools/tests/test_ui_min_targets.py``.)

Pure-Python, headless — the ``test_tile_conditions.py`` fixture style (a synth
``TileMapDoc`` -> real ``TileMap``, real balancing from the PINNED fixture,
buildings placed through the one legal seam) plus the ``test_vfx.py``
recording-renderer stand-in. Never reads or writes live ``data/``.
"""
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import TierState
from game.core.balance import load_balance
from game.map.tile_map import TileMap
from game.map.tiles import TileState
from game.ui import widgets
from game.ui.overlays import _TIER_OVERVIEW_ALPHA, MapOverlays, _level_color
from game.ui.skinning import ScreenSkinning

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
LOVE = 10 ** 9

VIEW_W, VIEW_H = 800, 600


class FakeRenderer:
    """Records every submit instead of drawing (the ``test_vfx.py`` stand-in).
    fix/depth-sorted-world-fills: the tile diamonds this module draws
    (condition tint / RANGE / HEATMAP / TIER OVERVIEW) go through
    ``submit_world_fill`` now, not the always-last overlay pass — see
    ``engine/render/CLAUDE.md``'s "Depth-sorted world fills"."""

    def __init__(self):
        self.hud = []
        self.overlay_polys = []
        self.overlay_lines = []
        self.world_fills = []

    def submit_hud(self, item):
        self.hud.append(item)

    def submit_overlay_polys(self, points, color):
        self.overlay_polys.append((tuple(points), color))

    def submit_overlay_lines(self, points, color, width=1, closed=False):
        self.overlay_lines.append((tuple(points), color, width, closed))

    def submit_world_fill(self, points, world_pos, layer="entities",
                          color=None, border=None, border_width=2):
        self.world_fills.append(
            (tuple(points), world_pos, layer, color, border, border_width))


def synth(rows, base=(0, 0)):
    """A bare all-GRASS TileMap (rng=None keeps every condition GRASS, so the
    condition-tint pass in ``submit()`` draws nothing and the tier diamonds
    are the only recorded polys)."""
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def place(tm, col, row, btype="defence"):
    """Place through the ONE legal seam."""
    b, _ = place_building(tm, tm.get(col, row), btype, LOVE, BUILD,
                          Scene(), TileOccupancy())
    return b


def full_window(tm):
    return (0, tm.cols - 1, 0, tm.rows - 1)


def _center(btn):
    return btn.rect[0] + 5, btn.rect[1] + 5


def tier_polys(renderer):
    """``{(col, row): rgba}`` for every recorded diamond, keyed by its
    ``world_pos`` (fix/depth-sorted-world-fills: ``submit_tile_diamond_fill``
    passes ``world_pos=(col, row)``, the SAME anchor a building's own
    ``Transform`` uses)."""
    return {wp: color for _pts, wp, _layer, color, _border, _bw
            in renderer.world_fills}


# ---------------------------------------------------------------------------
# 1. The three toggles are independent — no mutual exclusion
# ---------------------------------------------------------------------------
class TestToggleIndependence(unittest.TestCase):
    def _mo(self):
        return MapOverlays(VIEW_W, VIEW_H)

    def _flags(self, mo):
        return (mo.show_range, mo.show_heatmap, mo.show_tier_overview)

    def test_tier_overview_button_toggles_on_then_off(self):
        mo = self._mo()
        self.assertFalse(mo.show_tier_overview)
        self.assertTrue(mo.hit(*_center(mo.tier_overview_btn)))
        self.assertTrue(mo.show_tier_overview)
        self.assertTrue(mo.hit(*_center(mo.tier_overview_btn)))
        self.assertFalse(mo.show_tier_overview)

    def test_each_toggle_moves_only_its_own_flag(self):
        for idx, btn_name in enumerate(
                ("range_btn", "heatmap_btn", "tier_overview_btn")):
            mo = self._mo()
            self.assertTrue(mo.hit(*_center(getattr(mo, btn_name))))
            expected = tuple(i == idx for i in range(3))
            self.assertEqual(self._flags(mo), expected, btn_name)

    def test_all_three_can_be_active_at_once(self):
        mo = self._mo()
        for btn_name in ("range_btn", "heatmap_btn", "tier_overview_btn"):
            mo.hit(*_center(getattr(mo, btn_name)))
        self.assertEqual(self._flags(mo), (True, True, True))
        # ...and turning one back off leaves the other two alone.
        mo.hit(*_center(mo.heatmap_btn))
        self.assertEqual(self._flags(mo), (True, False, True))

    def test_the_three_pills_do_not_overlap_and_over_covers_all_three(self):
        mo = self._mo()
        rects = [mo.range_btn.rect, mo.heatmap_btn.rect,
                 mo.tier_overview_btn.rect]
        for x, _y, w, _h in rects:
            self.assertTrue(mo.over(x + 5, rects[0][1] + 5))
        xs = sorted((x, x + w) for x, _y, w, _h in rects)
        for (_lo, hi), (nxt, _) in zip(xs, xs[1:]):
            self.assertLessEqual(hi, nxt)
        self.assertFalse(mo.over(VIEW_W // 2, VIEW_H // 2))

    def test_empty_space_is_not_consumed(self):
        mo = self._mo()
        self.assertFalse(mo.hit(VIEW_W // 2, VIEW_H // 2))
        self.assertEqual(self._flags(mo), (False, False, False))


# ---------------------------------------------------------------------------
# 2. The tint: one diamond per built building, coloured by its tier
# ---------------------------------------------------------------------------
class TestTierOverviewSubmit(unittest.TestCase):
    def test_off_by_default_draws_no_diamond(self):
        tm = synth(["bbbbbb"])
        place(tm, 1, 0)
        r = FakeRenderer()
        MapOverlays(VIEW_W, VIEW_H).submit(r, tm, None, full_window(tm))
        self.assertEqual(r.world_fills, [])

    def test_one_diamond_per_building_with_the_matching_level_colour(self):
        tm = synth(["bbbbbb"])
        for col, level in ((1, 1), (2, 2), (3, 3)):
            b = place(tm, col, 0)
            b.get_component(TierState).current_level_in_tier = level
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        polys = tier_polys(r)
        self.assertEqual(len(polys), 3)
        for col, level in ((1, 1), (2, 2), (3, 3)):
            self.assertEqual(polys[(col, 0)],
                             _level_color(level) + (_TIER_OVERVIEW_ALPHA,),
                             f"level {level}")

    def test_the_colour_cycle_resets_at_every_tier_advance(self):
        """A level-1 building reads identically whether it just got PLACED
        (tier 1) or just ADVANCED (tier 2+) — the exact scenario reported
        live: a level-1 Slinger (tier 2) must be the same gold as a level-1
        Stone Thrower (tier 1), not a distinct "tier 2" colour."""
        tm = synth(["bbbbbb"])
        fresh = place(tm, 1, 0)
        advanced = place(tm, 2, 0)
        ts = advanced.get_component(TierState)
        ts.current_tier, ts.current_level_in_tier = 1, 1
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        polys = tier_polys(r)
        self.assertEqual(polys[(1, 0)], polys[(2, 0)])
        self.assertEqual(polys[(1, 0)],
                         _level_color(1) + (_TIER_OVERVIEW_ALPHA,))

    def test_the_three_level_colours_are_distinct(self):
        self.assertEqual(len({_level_color(i) for i in (1, 2, 3)}), 3)

    def test_level_colour_clamps_past_the_last_entry(self):
        self.assertEqual(_level_color(4), _level_color(3))
        self.assertEqual(_level_color(99), _level_color(3))

    def test_level_colour_is_read_fresh_from_the_palette(self):
        """UH-6/D5: never an import-time copy — a ``configure_palette`` rebind
        must reach it. Rebinding the attribute directly is the same mechanism
        ``configure_palette`` uses. (Level 3/blue reuses the non-palette-driven
        POND condition tint, not a ``widgets.C_*`` attribute — covered
        separately below, not by this rebind check.)"""
        original = widgets.C_PURPLE
        widgets.C_PURPLE = (1, 2, 3)
        try:
            self.assertEqual(_level_color(2), (1, 2, 3))
        finally:
            widgets.C_PURPLE = original
        self.assertEqual(_level_color(2), original)

    def test_level_3_reuses_the_pond_condition_tint(self):
        from game.map.tiles import TileCondition
        from game.ui.overlays import _COND_TINT
        self.assertEqual(_level_color(3), _COND_TINT[TileCondition.POND])

    def test_the_base_building_is_never_tinted(self):
        """The hole DOES carry a ``TierState`` (base_building.py), so the
        component check alone would tint it — it is tag-gated out instead."""
        tm = synth(["bbbbbb"])
        attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE),
                    Scene(), TileOccupancy())
        base_tile = tm.get(tm.base_col, tm.base_row)
        self.assertIsNotNone(base_tile.occupant)
        self.assertIsNotNone(base_tile.occupant.get_component(TierState))
        place(tm, 3, 0)
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        self.assertEqual(list(tier_polys(r)), [(3, 0)])

    def test_an_occupant_with_no_tier_state_is_skipped_without_raising(self):
        tm = synth(["bbbbbb"])
        place(tm, 1, 0)
        odd = tm.get(4, 0)
        odd.occupant = types.SimpleNamespace(
            tags=(), get_component=lambda cls: None)
        tm.set_tile_state(odd, TileState.BUILT)
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        self.assertEqual(list(tier_polys(r)), [(1, 0)])

    def test_a_built_tile_with_no_occupant_is_skipped(self):
        tm = synth(["bbbbbb"])
        empty = tm.get(2, 0)
        tm.set_tile_state(empty, TileState.BUILT)
        self.assertIsNone(empty.occupant)
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        self.assertEqual(r.world_fills, [])

    def test_tier_overview_composes_with_the_range_overlay(self):
        """Both on = both passes run; the tier diamond is drawn LAST, so it
        reads on top of the range square rather than replacing it."""
        tm = synth(["bbbbbb"])
        place(tm, 1, 0)
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_range = True
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit(r, tm, None, full_window(tm))
        tier_rgba = _level_color(1) + (_TIER_OVERVIEW_ALPHA,)  # fresh placement = level 1
        colors = [color for _pts, _wp, _layer, color, _border, _bw in r.world_fills]
        self.assertIn(widgets.C_RANGE_HIGHLIGHT + (55,), colors)
        self.assertEqual(colors[-1], tier_rgba)
        self.assertEqual(colors.count(tier_rgba), 1)


# ---------------------------------------------------------------------------
# 3. The pill itself draws, and gets the gold active treatment
# ---------------------------------------------------------------------------
class TestTierOverviewPillRender(unittest.TestCase):
    def test_the_third_pill_is_drawn_beside_the_other_two(self):
        mo = MapOverlays(VIEW_W, VIEW_H)
        r = FakeRenderer()
        mo.submit_buttons(r)
        labels = [i.text for i in r.hud if hasattr(i, "text")]
        self.assertEqual(labels, ["RANGE", "HEAT", "TIERS"])

    def test_active_gets_a_gold_rim_and_a_gold_label(self):
        mo = MapOverlays(VIEW_W, VIEW_H)
        mo.show_tier_overview = True
        r = FakeRenderer()
        mo.submit_buttons(r)
        label = next(i for i in r.hud
                     if getattr(i, "text", None) == "TIERS")
        self.assertEqual(label.color, widgets.C_GOLD)
        rims = [i for i in r.hud
                if getattr(i, "rect", None) == mo.tier_overview_btn.rect
                and getattr(i, "color", None) == widgets.C_GOLD
                and getattr(i, "width", 0) == 2]
        self.assertEqual(len(rims), 1)

    def test_inactive_pill_gets_no_gold_rim(self):
        mo = MapOverlays(VIEW_W, VIEW_H)
        r = FakeRenderer()
        mo.submit_buttons(r)
        self.assertEqual(
            [i for i in r.hud
             if getattr(i, "rect", None) == mo.tier_overview_btn.rect
             and getattr(i, "color", None) == widgets.C_GOLD], [])


# ---------------------------------------------------------------------------
# 4. The label is code-default + JSON-overridable through the widget id
# ---------------------------------------------------------------------------
class TestTierOverviewLabel(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.data_dir = fixture_copy(self._tmp.name)

    def test_default_label_is_tiers(self):
        # Cut from "TIER OVERVIEW" when the label-fit check was taught to
        # measure the SHIPPED font (data/ui/active_font.json ->
        # pixel_emulator): the old copy needed 89px in a 76px pill there.
        mo = MapOverlays(VIEW_W, VIEW_H)
        self.assertEqual(mo.tier_overview_btn.label, "TIERS")

    def test_the_widget_id_is_registered(self):
        mo = MapOverlays(VIEW_W, VIEW_H)
        self.assertEqual(mo.ids["btn_tier_overview"],
                         ("button", mo.tier_overview_btn))

    def test_a_screen_override_changes_the_label(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["overlays"] = {
            "widgets": {"btn_tier_overview": {"label": "LEVELS"}}}
        mo = MapOverlays(VIEW_W, VIEW_H, skinning)
        self.assertEqual(mo.tier_overview_btn.label, "LEVELS")
        # the siblings are untouched by that override
        self.assertEqual(mo.range_btn.label, "RANGE")
        self.assertEqual(mo.heatmap_btn.label, "HEAT")

    def test_a_rect_override_moves_the_pill_and_its_hit_box(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["overlays"] = {
            "widgets": {"btn_tier_overview": {"rect": [400, 100, 60, 20]}}}
        mo = MapOverlays(VIEW_W, VIEW_H, skinning)
        self.assertEqual(mo.tier_overview_btn.rect, (400, 100, 60, 20))
        self.assertTrue(mo.hit(410, 110))
        self.assertTrue(mo.show_tier_overview)

    def test_visible_false_is_never_hit_and_never_hovered(self):
        skinning = ScreenSkinning(self.data_dir)
        skinning._overrides["overlays"] = {
            "widgets": {"btn_tier_overview": {"visible": False}}}
        mo = MapOverlays(VIEW_W, VIEW_H, skinning)
        cx, cy = _center(mo.tier_overview_btn)
        self.assertFalse(mo.hit(cx, cy))
        self.assertFalse(mo.show_tier_overview)
        mo.update(0.016, cx, cy, False)
        self.assertFalse(mo.tier_overview_btn.hovered)


if __name__ == "__main__":
    unittest.main()
