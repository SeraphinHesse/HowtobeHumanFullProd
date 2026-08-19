"""SaveGamePLAN SG-6: MainMenu's CONTINUE visibility + SaveFilesScreen.hit().

Pure-logic UI tests, the test_player_identity.py TestMenuAvailabilityMatrix
shape.
"""
import unittest

from game.ui.main_menu import MainMenu
from game.ui.save_files import SaveFilesScreen, _format_timestamp

VW, VH = 640, 360


def center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


class TestContinueVisibility(unittest.TestCase):
    def test_hidden_with_no_saves(self):
        menu = MainMenu(VW, VH)   # has_saves=False by default
        for btn, slot in menu.buttons:
            if slot == "continue":
                self.assertFalse(btn.visible)
                return
        raise AssertionError("no continue slot")

    def test_visible_once_a_save_exists(self):
        menu = MainMenu(VW, VH, has_saves=True)
        for btn, slot in menu.buttons:
            if slot == "continue":
                self.assertTrue(btn.visible)
                return
        raise AssertionError("no continue slot")

    def test_set_has_saves_flips_visibility_live(self):
        menu = MainMenu(VW, VH)
        menu.set_has_saves(True)
        menu.layout(VW, VH)   # re-run layout, the per-frame refresh
        visible = {slot: btn.visible for btn, slot in menu.buttons}
        self.assertTrue(visible["continue"])

    def test_nine_row_stack_stays_on_screen(self):
        """The row count grew 7 -> 9 (CONTINUE + SAVE FILES) - the stack
        must not overflow the 360px logical surface (the arithmetic bug this
        phase's layout fix addresses)."""
        menu = MainMenu(VW, VH, has_saves=True)
        bottoms = [btn.rect[1] + btn.rect[3] for btn, _ in menu.buttons
                  if btn.visible]
        self.assertLessEqual(max(bottoms), VH)
        tops = [btn.rect[1] for btn, _ in menu.buttons if btn.visible]
        self.assertGreaterEqual(min(tops), 0)


def _slot(slot_id, pinned=False):
    return {"slot_id": slot_id, "pinned": pinned, "created_at": "t",
           "updated_at": "t", "map_id": "m", "round_num": 5}


class TestFormatTimestamp(unittest.TestCase):
    """User decisions: DD-MM-YYYY date order, seconds dropped."""

    def test_reorders_to_day_month_year_and_drops_seconds(self):
        self.assertEqual(_format_timestamp("2026-08-19T14:35:22"),
                         "19-08-2026 14:35")

    def test_malformed_input_falls_back_to_the_raw_string(self):
        self.assertEqual(_format_timestamp("t"), "t")
        self.assertEqual(_format_timestamp(""), "")


class TestSaveFilesHit(unittest.TestCase):
    def setUp(self):
        self.screen = SaveFilesScreen(VW, VH)
        self.screen.set_index({"version": 1, "slots": [_slot("a"), _slot("b")]})
        self.screen.layout(VW, VH)

    def test_back_button(self):
        self.assertEqual(self.screen.hit(*center(self.screen.back_btn.rect)),
                         "back")

    def test_pin_button_on_first_row(self):
        pin_btn, _del_btn = self.screen._row_buttons[0]
        # newest-first display: slot "b" (appended last) is row 0
        self.assertEqual(self.screen.hit(*center(pin_btn.rect)), ("pin", "b"))

    def test_delete_button_on_first_row(self):
        _pin_btn, del_btn = self.screen._row_buttons[0]
        self.assertEqual(self.screen.hit(*center(del_btn.rect)),
                         ("delete", "b"))

    def test_row_body_loads(self):
        left = self.screen._left
        row_top = 68  # _LIST_TOP
        # A point inside the row but away from the pin/delete buttons.
        point = (left + 30, row_top + 13)
        self.assertEqual(self.screen.hit(*point), ("load", "b"))

    def test_empty_index_shows_no_rows(self):
        self.screen.set_index({"version": 1, "slots": []})
        self.screen.layout(VW, VH)
        self.assertIsNone(self.screen.hit(VW // 2, 100))


if __name__ == "__main__":
    unittest.main()
