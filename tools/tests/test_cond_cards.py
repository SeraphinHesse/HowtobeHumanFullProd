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
    _BUILD_COND_CARD_ID_PREFIX, _CARD_GROUND_SLOT, _COND_CARD_ID_PREFIX,
    _COND_EFFECT_LINES, _UPGRADE_COND_CARD_ID_PREFIX, _cond_effect_rows,
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

    def test_cards_stack_inside_their_group_without_overlapping(self):
        """Cards are laid out relative to `terrain_card_list`, so the group's
        own rect is what they start from. They may run PAST its bottom — at
        full-size sprites a card is 74-138px tall and the list scrolls."""
        gx, gy, gw, _gh = self.panel._list_rect("terrain_card_list",
                                                self.panel._terrain_list)
        prev_bottom = gy
        for _cond, parts in self.panel._cond_cards:
            x, y, w, h = parts.body.rect
            self.assertEqual((x, w), (gx, gw))
            self.assertGreaterEqual(y, prev_bottom)
            prev_bottom = y + h

    def test_moving_the_group_moves_every_card(self):
        """The whole point of the group container: one authored rect shifts
        the list, instead of the cards being pinned to `panel`."""
        before = [p.body.rect[:2] for _c, p in self.panel._cond_cards]
        self.panel.skinning.widget_rect = (
            lambda sid, name: (400, 200, 118, 150)
            if name == "terrain_card_list" else None)
        self.panel._build_cond_cards(self.panel._session)
        after = [p.body.rect[:2] for _c, p in self.panel._cond_cards]
        self.assertNotEqual(before, after)
        self.assertTrue(all(x == 400 for x, _y in after))
        self.assertEqual(after[0][1], 200)

    def test_a_sprite_is_drawn_at_its_own_frame_size(self):
        """Full-size tiles, never a downscaled thumbnail: `HudSprite`
        stretches to its box, so the box IS the frame."""
        store = self.panel.assets
        self.assertIsNotNone(store, "the mock must carry an asset store")
        for _cond, parts in self.panel._cond_cards:
            piece = parts.sprite
            self.assertEqual(tuple(piece.rect[2:]),
                             tuple(store.frame_size(piece.skin)))

    def test_every_card_draws_exactly_one_preview_sprite(self):
        """No ground composite any more: one `_sprite` widget per card, so a
        designer's downsize/position override reaches all four the same way."""
        for _cond, parts in self.panel._cond_cards:
            self.assertFalse(hasattr(parts, "ground"))
            self.assertTrue(parts.sprite.skin)

    def test_grass_previews_the_plain_ground_tile(self):
        cards = dict(self.panel._cond_cards)
        self.assertEqual(cards[TileCondition.GRASS].sprite.skin,
                         _CARD_GROUND_SLOT)
        for cond in (TileCondition.MOUNTAIN, TileCondition.POND,
                     TileCondition.FOREST):
            self.assertTrue(cards[cond].sprite.skin.startswith("cond_"))

    def test_scroll_clamps_against_the_full_row_count(self):
        """Regression: clamping against the BUILT card list (which shrinks as
        you scroll) made a scroll past the end walk backwards."""
        panel = self.panel
        last = panel._cond_row_count - 1
        panel.handle_scroll(99)
        self.assertEqual(panel.cond_scroll_offset, last)
        panel.handle_scroll(99)
        self.assertEqual(panel.cond_scroll_offset, last)
        panel.handle_scroll(-99)
        self.assertEqual(panel.cond_scroll_offset, 0)

    def test_the_first_card_always_draws(self):
        """A group sized under one full-size card must clip, not blank."""
        panel = self.panel
        panel.skinning.widget_rect = (
            lambda sid, name: (516, 112, 118, 10)
            if name == "terrain_card_list" else None)
        panel._build_cond_cards(panel._session)
        first = panel._cond_cards[0][1].body.rect
        self.assertTrue(panel._cond_card_in_viewport(first, 0))
        self.assertFalse(panel._cond_card_in_viewport(first))

    def test_clearing_drops_every_card_id(self):
        self.panel._clear_cond_card_ids()
        self.assertEqual(
            [k for k in self.panel.ids if k.startswith(_COND_CARD_ID_PREFIX)],
            [])


class TestCondEffectRows(unittest.TestCase):
    """Row 0 names the effect, row 1 carries its number — always exactly
    `_COND_EFFECT_LINES` entries, so row `i` addresses the same half."""

    def test_rows_are_always_the_reserved_count(self):
        self.assertEqual(len(_cond_effect_rows([])), _COND_EFFECT_LINES)
        self.assertEqual(len(_cond_effect_rows(["a", "b", "c"])),
                         _COND_EFFECT_LINES)

    def test_the_pair_is_name_then_value(self):
        self.assertEqual(_cond_effect_rows(["Range", "+1"]), ["Range", "+1"])

    def test_a_condition_with_a_bonus_reads_as_a_name_and_a_number(self):
        panel = _panel()
        self.assertEqual(
            panel._tile_cond_effect_lines(TileCondition.MOUNTAIN),
            ["Range", "+1"])


class TestTerrainBoxIsEditable(unittest.TestCase):
    """The badge and its effect box are DELETED: every mode that names a
    terrain draws a card (feature: construct-terrain-card)."""

    def test_upgrade_mode_shows_a_card_not_a_badge(self):
        balances = screen_mocks.load_balances(DATA)
        session = screen_mocks.build_session(DATA, balances)
        panel = screen_mocks.build_bp_view("upgrade", 640, 360, balances,
                                           session).panel
        self.assertIn("upgrade_terrain_card_list", panel.ids)
        self.assertTrue(any(k.startswith(_UPGRADE_COND_CARD_ID_PREFIX)
                            for k in panel.ids))
        for gone in ("cond_badge", "cond_badge_text", "cond_effect_box",
                     "cond_effect_line_0"):
            self.assertNotIn(gone, panel.ids)

    def test_unlock_mode_drops_the_badge(self):
        """The cards say the same thing for all four tiles, so the pill that
        named only the primary tile's condition is gone — from this mode
        first, and now from the panel altogether."""
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
        self.assertFalse(hasattr(panel, "_cond_badge_rect"))


class TestConstructTerrainCard(unittest.TestCase):
    """feature: construct-terrain-card — build mode ends in the same card
    unlock mode draws, in its own id family, with nothing hover-gated."""

    def setUp(self):
        balances = screen_mocks.load_balances(DATA)
        session = screen_mocks.build_session(DATA, balances)
        self.panel = screen_mocks.build_bp_view("construct", 640, 360,
                                                balances, session).panel

    def test_it_builds_the_same_tree_under_its_own_prefix(self):
        """The mock selects a four-condition chunk, so all four trees build —
        each with the child ids an unlock card has."""
        keys = [c.name for c, _ in self.panel._construct_cond_cards]
        self.assertEqual(keys, [c.name for c in TileCondition])
        self.assertIn("build_terrain_card_list", self.panel.ids)
        for cond, _parts in self.panel._construct_cond_cards:
            root = f"{_BUILD_COND_CARD_ID_PREFIX}{cond.name.lower()}"
            for part in ("",) + CARD_PARTS:
                self.assertIn(root + part, self.panel.ids)

    def test_the_effect_rows_are_filled_without_any_hover(self):
        """The pill this replaces only revealed its effect box under the
        cursor; the card carries the lines outright."""
        self.assertFalse(hasattr(self.panel, "_cond_hover"))
        cards = dict(self.panel._construct_cond_cards)
        self.assertEqual(cards[TileCondition.MOUNTAIN].lines, ["Range", "+1"])

    def test_the_two_families_do_not_share_ids(self):
        """Overrides are per-id, so a build card must not answer to an unlock
        card's key — that is what lets the two modes place theirs apart."""
        for cond, _parts in self.panel._construct_cond_cards:
            self.assertNotIn(f"{_COND_CARD_ID_PREFIX}{cond.name.lower()}",
                             self.panel.ids)


if __name__ == "__main__":
    unittest.main()
