"""Unlock mode's tile-condition cards, and the terrain box as id'd widgets.

The unlock panel lists the terrain a purchase covers: one card per DISTINCT
condition across every 2x2 chunk in the selection, each carrying the
condition's own art, its name, how many bought tiles have it, and its effect
lines. The badge + effect box that state the same thing in construct/upgrade
mode are widgets too now, rather than bare rects sized around a live text
measurement.

Driven off `tools/screen_mocks`' panel — the same object the exporter records
`screen_defaults.json` from — so these tests and the committed artifact can
never disagree about what a card is made of (the `test_construct_card.py`
argument, for the other dynamic-count family).
"""
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from game.map.tiles import TileCondition  # noqa: E402
from game.ui.building_ui import (  # noqa: E402
    _COND_CARD_ID_PREFIX, _COND_EFFECT_LINES, _COND_EFFECT_ROWS_PER_LINE,
    _cond_effect_rows,
)
from tools import screen_mocks  # noqa: E402

#: LIVE data/ on purpose — allowlisted in test_fixture_guard.py, same reason
#: test_construct_card.py is: the card tree asserted here must agree with the
#: committed screen_defaults.json, which is exported from the live tree.
DATA = REPO / "data"

#: The child ids every terrain card carries, relative to its own
#: `cond_card_<condition>` id.
CARD_PARTS = ("_sprite", "_name", "_count") + tuple(
    f"_effect_{i}" for i in range(_COND_EFFECT_LINES))


def _panel():
    """A `building_panel` in unlock mode over the mock's four-condition chunk."""
    balances = screen_mocks.load_balances(DATA)
    session = screen_mocks.build_session(DATA, balances)
    return screen_mocks.build_bp_view("unlock", 640, 360, balances,
                                      session).panel


class TestCondCardTree(unittest.TestCase):
    def setUp(self):
        self.panel = _panel()

    def test_one_card_per_distinct_condition(self):
        """The mock forces all four conditions onto the chunk, so all four
        cards build — and each appears exactly once however many of the four
        tiles carry it."""
        keys = [c.name for c, _ in self.panel._cond_cards]
        self.assertEqual(keys, [c.name for c in TileCondition])

    def test_every_card_is_a_full_widget_tree(self):
        for cond, _parts in self.panel._cond_cards:
            key = f"{_COND_CARD_ID_PREFIX}{cond.name.lower()}"
            self.assertIn(key, self.panel.ids)
            for part in CARD_PARTS:
                self.assertIn(key + part, self.panel.ids,
                              f"{key}{part} is not an overridable widget")

    def test_cards_do_not_overlap_and_stay_in_the_viewport(self):
        top, bottom = self.panel._cond_card_viewport()
        prev_bottom = top
        for _cond, parts in self.panel._cond_cards:
            x, y, w, h = parts.body.rect
            self.assertGreaterEqual(y, prev_bottom)
            self.assertLessEqual(y + h, bottom,
                                 "the worst case (4 conditions) must fit "
                                 "without scrolling")
            prev_bottom = y + h

    def test_clearing_drops_every_card_id(self):
        self.panel._clear_cond_card_ids()
        self.assertEqual(
            [k for k in self.panel.ids if k.startswith(_COND_CARD_ID_PREFIX)],
            [])


class TestCondEffectRows(unittest.TestCase):
    """The wrap is a DRAW-time concern; the row budget the rects are sized
    against is not, which is what keeps a stored rect off a live measurement."""

    def test_rows_are_capped(self):
        many = [f"effect line number {i} which is quite long" for i in range(9)]
        self.assertLessEqual(len(_cond_effect_rows(many, 112)),
                             _COND_EFFECT_LINES)

    def test_a_long_line_wraps_within_its_budget(self):
        rows = _cond_effect_rows(["-25% atk speed for defenders"], 112)
        self.assertGreater(len(rows), 1)
        self.assertLessEqual(len(rows), _COND_EFFECT_ROWS_PER_LINE)

    def test_no_effects_means_no_rows(self):
        self.assertEqual(_cond_effect_rows([], 112), [])


class TestTerrainBoxIsEditable(unittest.TestCase):
    """The badge and the effect box were the two things on this panel a
    designer could not touch."""

    def test_construct_mode_exposes_the_box_widgets(self):
        balances = screen_mocks.load_balances(DATA)
        session = screen_mocks.build_session(DATA, balances)
        panel = screen_mocks.build_bp_view("construct", 640, 360, balances,
                                           session).panel
        for name in ("cond_badge", "cond_badge_text", "cond_effect_box"):
            self.assertIn(name, panel.ids)
        for i in range(_COND_EFFECT_LINES):
            self.assertIn(f"cond_effect_line_{i}", panel.ids)

    def test_unlock_mode_drops_the_badge(self):
        """The cards say the same thing for all four tiles, so the pill that
        named only the primary tile's condition is gone from this mode."""
        panel = self.panel = _panel()

        class Rec:
            def __init__(self):
                self.items = []

            def submit_hud(self, item):
                self.items.append(item)

            def submit_world_fill(self, *a, **k):
                pass

            def submit_world(self, *a, **k):
                pass

        balances = screen_mocks.load_balances(DATA)
        session = screen_mocks.build_session(DATA, balances)
        panel.submit(Rec(), session)
        self.assertIsNone(panel._cond_badge_rect)


if __name__ == "__main__":
    unittest.main()
