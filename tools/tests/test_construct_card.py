"""The construct card is a widget TREE, not one button.

Covers what `_build_construct` now produces (six ids per buildable type, all
under the one `card_` prefix `_clear_card_ids` sweeps), the scrolling list, and
the two `defaults` bools that pick the click target and the portrait art.

Everything is driven off `tools/screen_mocks`' panel — the same object the
exporter records `screen_defaults.json` from — so these tests and the committed
artifact can never disagree about what a card is made of.
"""
import pathlib
import sys
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from game.buildings.registry import BUILDING_CLASSES  # noqa: E402
from game.ui import widgets  # noqa: E402
from game.ui.building_ui import _CARD_ID_PREFIX  # noqa: E402
from tools import screen_mocks  # noqa: E402

DATA = REPO / "data"

#: The child ids every card carries, relative to its own `card_<btype>` id.
CARD_PARTS = ("_portrait", "_name", "_name2", "_price", "_price_icon",
              "_price_text")


def _panel():
    """A `building_panel` driven into construct mode with every type
    unlocked — the exporter's own mock state."""
    balances = screen_mocks.load_balances(DATA)
    session = screen_mocks.build_session(DATA, balances)
    return screen_mocks.build_bp_view("construct", 640, 360, balances,
                                      session).panel


def _set_defaults(panel, **flags):
    """Inject a `defaults` section for `building_panel` (the styling surface
    dynamic-count content reads, `ScreenSkinning.defaults`)."""
    override = panel.skinning._overrides.setdefault(panel.screen_id, {})
    override.setdefault("defaults", {}).update(flags)
    panel._build_construct()


class TestCardWidgetTree(unittest.TestCase):
    def test_every_card_emits_its_whole_tree(self):
        panel = _panel()
        self.assertTrue(panel.cards, "no buildable types in the mock state")
        for btype, _btn in panel.cards:
            key = f"{_CARD_ID_PREFIX}{btype}"
            self.assertIn(key, panel.ids)
            for part in CARD_PARTS:
                self.assertIn(key + part, panel.ids,
                              f"{btype} card is missing {part}")

    def test_kinds_match_what_the_editor_will_draw(self):
        panel = _panel()
        btype = panel.cards[0][0]
        key = f"{_CARD_ID_PREFIX}{btype}"
        expected = {
            key: "button", key + "_portrait": "panel",
            key + "_name": "label", key + "_name2": "label",
            key + "_price": "button", key + "_price_icon": "panel",
            key + "_price_text": "label",
        }
        for name, kind in expected.items():
            self.assertEqual(panel.ids[name][0], kind, name)

    def test_children_sit_inside_their_card(self):
        panel = _panel()
        for btype, btn in panel.cards:
            cx, cy, cw, ch = btn.rect
            parts = panel._card_parts[btype]
            for child in (parts.portrait, parts.price, parts.icon):
                x, y, w, h = child.rect
                self.assertTrue(cx <= x and x + w <= cx + cw
                                and cy <= y and y + h <= cy + ch,
                                f"{btype}: {child.rect} escapes {btn.rect}")

    def test_clear_card_ids_sweeps_the_whole_tree(self):
        panel = _panel()
        self.assertTrue(any(k.startswith(_CARD_ID_PREFIX) for k in panel.ids))
        panel._clear_card_ids()
        self.assertEqual([k for k in panel.ids
                          if k.startswith(_CARD_ID_PREFIX)], [])
        self.assertEqual(panel._card_parts, {})

    def test_the_name_row_stores_the_UNWRAPPED_name(self):
        """The wrap is a live font measurement, so it must happen at draw time
        — the stored label (which lands in `screen_defaults.json`) is the whole
        name, and row 2 is always empty."""
        panel = _panel()
        for btype, _btn in panel.cards:
            parts = panel._card_parts[btype]
            self.assertTrue(parts.name_1.label)
            self.assertNotIn("\n", parts.name_1.label)
            self.assertEqual(parts.name_2.label, "")

    def test_the_name_wraps_to_at_most_two_rows(self):
        panel = _panel()
        for btype, _btn in panel.cards:
            parts = panel._card_parts[btype]
            lines = widgets.wrap_text(parts.name_1.label, "sm", parts.name_w,
                                      max_lines=2)
            self.assertLessEqual(len(lines), 2, btype)


class TestPriceIsClickTarget(unittest.TestCase):
    """`defaults.price_is_click_target` picks WHICH rect opens the preview."""

    def _click(self, panel, rect):
        x, y, w, h = rect
        return panel._construct_click(x + w // 2, y + h // 2, panel._session,
                                      panel._buildings_balance)

    def test_off_by_default_the_whole_card_clicks(self):
        panel = _panel()
        btype, btn = panel.cards[0]
        # The portrait is inside the card but outside the price pill.
        portrait = panel._card_parts[btype].portrait.rect
        self.assertTrue(self._click(panel, portrait))
        self.assertIsNotNone(panel.preview)

    def test_on_only_the_price_clicks(self):
        panel = _panel()
        _set_defaults(panel, price_is_click_target=True)
        btype, _btn = panel.cards[0]
        parts = panel._card_parts[btype]
        self._click(panel, parts.portrait.rect)
        self.assertIsNone(panel.preview, "portrait should be inert")
        self._click(panel, parts.price.rect)
        self.assertIsNotNone(panel.preview, "price pill should open it")


class TestPortraitSlot(unittest.TestCase):
    def test_defaults_to_the_buildings_own_tier_sprite(self):
        panel = _panel()
        for btype, _btn in panel.cards:
            slot = panel._card_parts[btype].portrait.skin
            self.assertFalse(slot.startswith("card_portrait_"), btype)
            self.assertTrue(slot, btype)

    def test_falls_back_to_the_tier_sprite_with_no_imported_art(self):
        """The bool is on but nothing is imported (and `assets` is None in a
        headless panel), so the portrait keeps the tier sprite — E-37, never a
        grey X."""
        panel = _panel()
        before = {b: panel._card_parts[b].portrait.skin
                  for b, _ in panel.cards}
        _set_defaults(panel, use_card_portrait_slot=True)
        after = {b: panel._card_parts[b].portrait.skin
                 for b, _ in panel.cards}
        self.assertEqual(before, after)

    def test_switches_over_once_the_slot_has_art(self):
        panel = _panel()

        class _Store:
            """Every `card_portrait_*` slot reports imported idle art."""
            def animation_total_ms(self, slot, name):
                return 100 if slot.startswith("card_portrait_") else None

        panel.assets = _Store()
        _set_defaults(panel, use_card_portrait_slot=True)
        for btype, _btn in panel.cards:
            self.assertEqual(panel._card_parts[btype].portrait.skin,
                             f"card_portrait_{btype}")


class TestCardListScrolling(unittest.TestCase):
    def test_clamps_at_both_ends(self):
        panel = _panel()
        limit = max(0, len(panel.cards) - panel._cards_visible())
        panel.handle_scroll(999)
        self.assertEqual(panel.scroll_offset, limit)
        panel.handle_scroll(-999)
        self.assertEqual(panel.scroll_offset, 0)

    def test_scrolling_moves_which_cards_are_drawn(self):
        """`handle_scroll` must REBUILD — a card's rect is absolute with the
        offset baked in, so without the rebuild the offset would move and
        nothing on screen would."""
        panel = _panel()
        self.assertGreater(len(panel.cards), panel._cards_visible(),
                           "mock state must overflow the list to test scroll")

        def shown():
            return [b for b, btn in panel.cards
                    if panel._card_in_viewport(btn.rect)]

        top = shown()
        panel.handle_scroll(1)          # no manual _build_construct()
        scrolled = shown()
        self.assertEqual(len(top), panel._cards_visible())
        self.assertNotEqual(top, scrolled)
        self.assertEqual(top[1:], scrolled[:-1])

    def test_every_card_keeps_its_ids_while_scrolled_away(self):
        """Off-window cards are skipped at DRAW/HIT, never hidden by setting
        `visible` — that key belongs to the designer, and the exporter must
        still see the full id set."""
        panel = _panel()
        panel.handle_scroll(999)
        panel._build_construct()
        for btype, btn in panel.cards:
            self.assertIn(f"{_CARD_ID_PREFIX}{btype}", panel.ids)
            self.assertTrue(getattr(btn, "visible", True), btype)

    def test_closing_the_panel_resets_the_offset(self):
        panel = _panel()
        panel.handle_scroll(2)
        self.assertNotEqual(panel.scroll_offset, 0)
        panel.close()
        self.assertEqual(panel.scroll_offset, 0)

    def test_scrolling_is_a_no_op_outside_construct_mode(self):
        panel = _panel()
        panel.mode = "upgrade"
        panel.handle_scroll(3)
        self.assertEqual(panel.scroll_offset, 0)


class TestPortraitSlotRegistry(unittest.TestCase):
    def test_every_building_type_has_a_portrait_slot(self):
        """The `use_card_portrait_slot` switch is only meaningful if the art
        family actually covers every type a card can show."""
        from engine.assets.registry import load_registry

        keys = set(load_registry(DATA).slot_keys())
        for btype in BUILDING_CLASSES:
            self.assertIn(f"card_portrait_{btype}", keys, btype)


if __name__ == "__main__":
    unittest.main()
