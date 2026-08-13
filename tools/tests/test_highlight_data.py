"""VfxAuthoringPLAN VA-5: the seven tile highlights are DATA.

`tools/tests/test_theme_data.py`'s shape, applied to the values that moved out
of it: hardcoded stock values (never read from live `data/`), a fallback-equals-
data pin so the two cannot silently drift, and a rebind-reaches-consumers test
so a designer's edit provably lands on screen.

Every test that calls `configure_highlights` MUST restore module state
afterwards — the same no-leak rule the fonts/palette tests follow, for the same
reason: these are module-level globals shared with every other test in the run.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import copy

from engine import data_io
from game.ui import widgets
from tools.tests.fixture_data import FIXTURE_DATA

# The stock values — verbatim from the C_* constants VA-5 deleted
# (C_HIGHLIGHT / C_HIGHLIGHT2 / C_RANGE_HIGHLIGHT, which were palette keys,
# and C_MOVE_HIGHLIGHT / C_TUTORIAL_HIGHLIGHT, which were bare code
# constants). Hardcoded here rather than read from the live file, per the
# house rule this module inherits.
_STOCK = {
    "tile_selected": {"color": (255, 230, 60), "border_width": 2, "fill_alpha": 0},
    "section_2x2": {"color": (255, 180, 60), "border_width": 2, "fill_alpha": 0},
    "attack_range": {"color": (180, 40, 40), "border_width": 2, "fill_alpha": 0},
    "move_target": {"color": (80, 200, 255), "border_width": 2, "fill_alpha": 0},
    "wall_edge": {"color": (255, 230, 60), "border_width": 4, "fill_alpha": 0},
    "upgrade_batch": {"color": (255, 230, 60), "border_width": 2, "fill_alpha": 0},
    "tutorial_highlight": {"color": (255, 255, 255), "border_width": 2,
                           "fill_alpha": 0},
}


def _fixture_vfx():
    return data_io.load_json(FIXTURE_DATA / "balancing" / "vfx.json")


class _NoLeak(unittest.TestCase):
    """Snapshot/restore the module globals `configure_highlights` rebinds."""

    def setUp(self):
        highlights = copy.deepcopy(widgets._HIGHLIGHTS)
        triggers = dict(widgets._HIGHLIGHT_TRIGGERS)
        self.addCleanup(widgets._HIGHLIGHTS.update, highlights)
        self.addCleanup(widgets._HIGHLIGHT_TRIGGERS.update, triggers)


class TestFallbackEqualsData(_NoLeak):
    """The literals in widgets.py are the UNCONFIGURED FALLBACK; if they drift
    from the shipped JSON, a bare test/tool renders one thing and the game
    another."""

    def test_every_stock_value_matches_the_committed_data(self):
        shipped = _fixture_vfx()["procedural"]["highlights"]
        self.assertEqual(set(shipped), set(_STOCK))
        for name, stock in _STOCK.items():
            with self.subTest(name=name):
                self.assertEqual(tuple(shipped[name]["color"]), stock["color"])
                self.assertEqual(shipped[name]["border_width"],
                                 stock["border_width"])
                self.assertEqual(shipped[name]["fill_alpha"],
                                 stock["fill_alpha"])

    def test_the_module_fallback_matches_the_stock_table(self):
        for name, stock in _STOCK.items():
            with self.subTest(name=name):
                self.assertEqual(widgets._HIGHLIGHTS[name], stock)


class TestConfigure(_NoLeak):
    def test_a_configured_value_reaches_highlight_color(self):
        doc = _fixture_vfx()
        doc["procedural"]["highlights"]["tile_selected"]["color"] = [1, 2, 3]
        widgets.configure_highlights(doc)
        self.assertEqual(widgets.highlight_color("tile_selected"), (1, 2, 3))

    def test_a_missing_key_fails_loud(self):
        """configure_palette's argument: a dropped highlight would otherwise
        leave one silently on its fallback, which reads as "my edit did
        nothing"."""
        doc = _fixture_vfx()
        del doc["procedural"]["highlights"]["wall_edge"]
        with self.assertRaises(ValueError):
            widgets.configure_highlights(doc)

    def test_an_unknown_key_fails_loud(self):
        doc = _fixture_vfx()
        doc["procedural"]["highlights"]["not_a_highlight"] = {
            "color": [1, 2, 3], "border_width": 1, "fill_alpha": 0}
        with self.assertRaises(ValueError):
            widgets.configure_highlights(doc)

    def test_it_picks_up_the_trigger_bindings(self):
        doc = _fixture_vfx()
        doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        doc["triggers"]["tile_selected"]["draw_in_front"] = False
        widgets.configure_highlights(doc)
        self.assertEqual(widgets._HIGHLIGHT_TRIGGERS["tile_selected"],
                         ("vfx_tile_selected", False))


class _FakeRenderer:
    def __init__(self):
        self.fills = []
        self.items = []

    def submit_world_fill(self, points, world_pos, layer="entities",
                          color=None, border=None, border_width=2, rank=0):
        self.fills.append({"world_pos": world_pos, "color": color,
                           "border": border, "border_width": border_width,
                           "rank": rank})

    def submit(self, item):
        self.items.append(item)


class _FakeAssets:
    def __init__(self, with_art=()):
        self.with_art = set(with_art)

    def animation_total_ms(self, slot, animation):
        return 250 if slot in self.with_art else None


class TestSubmitHighlight(_NoLeak):
    def test_it_draws_an_outline_in_the_authored_colour(self):
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 3, 4)
        self.assertEqual(len(r.fills), 1)
        self.assertEqual(r.fills[0]["border"],
                         _STOCK["tile_selected"]["color"])
        self.assertIsNone(r.fills[0]["color"], "fill_alpha 0 = outline only")
        self.assertEqual(r.fills[0]["world_pos"], (3, 4))

    def test_a_non_zero_fill_alpha_fills(self):
        doc = _fixture_vfx()
        doc["procedural"]["highlights"]["tile_selected"]["fill_alpha"] = 80
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 0, 0)
        self.assertEqual(r.fills[0]["color"],
                         _STOCK["tile_selected"]["color"] + (80,))

    def test_wall_edge_carries_its_wider_line(self):
        r = _FakeRenderer()
        widgets.submit_highlight(r, "wall_edge", 0, 0)
        self.assertEqual(r.fills[0]["border_width"], 4)

    def test_draw_in_front_becomes_the_depth_rank(self):
        doc = _fixture_vfx()
        doc["triggers"]["tile_selected"]["draw_in_front"] = False
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 0, 0)
        self.assertEqual(r.fills[0]["rank"], -1)

        doc["triggers"]["tile_selected"]["draw_in_front"] = True
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 0, 0)
        self.assertEqual(r.fills[0]["rank"], 1)

    def test_a_bound_slot_with_art_draws_the_sprite_instead(self):
        doc = _fixture_vfx()
        doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 2, 5,
                                 assets=_FakeAssets({"vfx_tile_selected"}))
        self.assertEqual(r.fills, [], "the diamond must not also draw")
        self.assertEqual(len(r.items), 1)
        self.assertEqual(r.items[0].slot_key, "vfx_tile_selected")
        self.assertEqual(r.items[0].world_pos, (2, 5))

    def test_a_bound_slot_with_NO_art_falls_back_to_the_diamond(self):
        """E-37, and the same animation_total_ms signal spawn_play_once uses —
        so the two paths cannot disagree about 'imported'."""
        doc = _fixture_vfx()
        doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 0, 0,
                                 assets=_FakeAssets())
        self.assertEqual(r.items, [])
        self.assertEqual(len(r.fills), 1)

    def test_no_assets_takes_the_procedural_path(self):
        doc = _fixture_vfx()
        doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        widgets.configure_highlights(doc)
        r = _FakeRenderer()
        widgets.submit_highlight(r, "tile_selected", 0, 0, assets=None)
        self.assertEqual(len(r.fills), 1)

    def test_an_unknown_event_is_a_silent_no_op(self):
        r = _FakeRenderer()
        widgets.submit_highlight(r, "not_an_event", 0, 0)   # must not raise
        self.assertEqual(r.fills, [])
        self.assertEqual(r.items, [])


class TestTheShippedTriggerRows(unittest.TestCase):
    def test_every_highlight_has_a_row_naming_the_highlight_kind(self):
        triggers = _fixture_vfx()["triggers"]
        for name in _STOCK:
            with self.subTest(name=name):
                self.assertEqual(triggers[name]["procedural"], "highlight")
                self.assertEqual(triggers[name]["sprite_slot"], "")

    def test_every_highlight_has_a_slot_to_bind_art_to(self):
        from engine.assets.registry import load_registry
        slots = set(load_registry(FIXTURE_DATA).group_slots("vfx"))
        for name in _STOCK:
            with self.subTest(name=name):
                self.assertIn(f"vfx_{name}", slots)


class TestThePaletteKeysAreGone(unittest.TestCase):
    """D8: one home per value. Leaving them in palette.json as well would be
    the dead-data gap ESV-3a opened with procedural.floaters and ESV-6 had to
    close."""

    def test_the_three_keys_left_the_palette(self):
        palette = data_io.load_json(FIXTURE_DATA / "ui" / "palette.json")
        for key in ("highlight", "highlight2", "range_highlight"):
            with self.subTest(key=key):
                self.assertNotIn(key, palette)
                self.assertNotIn(key, widgets._PALETTE_KEYS)

    def test_the_deleted_constants_are_gone_from_widgets(self):
        for name in ("C_HIGHLIGHT", "C_HIGHLIGHT2", "C_RANGE_HIGHLIGHT",
                     "C_MOVE_HIGHLIGHT", "C_TUTORIAL_HIGHLIGHT"):
            with self.subTest(name=name):
                self.assertFalse(hasattr(widgets, name),
                                 f"{name} came back — it has one home now")


if __name__ == "__main__":
    unittest.main()
