"""Controls screen tests (feature: rebindable hotkeys).

Pure rect math + the ``Shell`` overlay-flag routing — no pygame, no SDL,
mirroring ``test_shell.py``'s pattern. Applying a captured keypress
(collision check, persistence) is ``game/main.py``'s job and lives outside
``game/ui``'s purity boundary, so it is not exercised here; this file covers
what the screen itself owns: arming/clearing ``capturing``, the REBIND/BACK
hit-test, and the Shell-level open/close routing.
"""
import unittest

from game.core import load_balance
from game.core.phases import GameState
from game.ui import Shell
from game.ui.keybinds_screen import ACTIONS, KeybindsScreen, display_key
from tools.tests.fixture_data import FIXTURE_DATA

VW, VH = 640, 360

BINDINGS = {
    "combat_speed_1": "1",
    "combat_speed_2": "2",
    "combat_speed_3": "3",
    "confirm_purchase": "return",
    "end_turn": "space",
    "quick_skip_combat": "p",
    "toggle_cheat_menu": "ctrl+l",
    "toggle_drag_select": "q",
    "toggle_heatmap": "h",
    "toggle_range": "r",
    "toggle_tier_overview": "t",
}


def center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


class TestDisplayKey(unittest.TestCase):
    def test_uppercases_and_keeps_the_modifier_prefix(self):
        self.assertEqual(display_key("ctrl+l"), "CTRL+L")
        self.assertEqual(display_key("space"), "SPACE")


class TestActionsScope(unittest.TestCase):
    def test_cheat_menu_and_quick_skip_are_hidden_from_the_screen(self):
        shown = {action for action, _label in ACTIONS}
        self.assertNotIn("toggle_cheat_menu", shown)
        self.assertNotIn("quick_skip_combat", shown)

    def test_the_three_overlay_toggles_and_end_turn_are_shown(self):
        shown = {action for action, _label in ACTIONS}
        self.assertLessEqual(
            {"end_turn", "toggle_heatmap", "toggle_range",
             "toggle_tier_overview", "toggle_drag_select"},
            shown)


class TestKeybindsScreenCapture(unittest.TestCase):
    def _screen(self):
        return KeybindsScreen(VW, VH, dict(BINDINGS))

    def test_rebind_click_arms_capturing_for_that_action(self):
        screen = self._screen()
        action, _label, btn = screen.rows[0]
        self.assertIsNone(screen.hit(*center(btn.rect)))
        self.assertEqual(screen.capturing, action)

    def test_back_click_returns_back_and_clears_capturing(self):
        screen = self._screen()
        screen.capturing = ACTIONS[0][0]
        self.assertEqual(screen.hit(*center(screen.back_btn.rect)), "back")
        self.assertIsNone(screen.capturing)

    def test_stop_capture_clears_it(self):
        screen = self._screen()
        screen.capturing = "end_turn"
        screen.stop_capture()
        self.assertIsNone(screen.capturing)

    def test_flash_conflict_clears_capturing_and_flashes_the_row(self):
        screen = self._screen()
        _action, _label, btn = screen.rows[0]
        screen.capturing = screen.rows[0][0]
        screen.flash_conflict()
        self.assertIsNone(screen.capturing)
        self.assertGreater(btn.flash, 0)

    def test_update_shows_press_a_key_only_for_the_armed_row(self):
        screen = self._screen()
        armed_action, _label, armed_btn = screen.rows[0]
        _other_action, _label2, other_btn = screen.rows[1]
        screen.capturing = armed_action
        screen.update(0.016, -1, -1)
        self.assertEqual(armed_btn.label, "PRESS A KEY")
        self.assertEqual(other_btn.label, "REBIND")


def make_shell():
    ui = load_balance(FIXTURE_DATA, "ui")
    return Shell(VW, VH, ui, key_bindings=dict(BINDINGS))


class TestShellControlsRouting(unittest.TestCase):
    def test_controls_button_opens_the_overlay(self):
        shell = make_shell()
        shell.open_settings(GameState.MAIN_MENU)
        shell.handle_click(*center(shell.settings_screen.controls_btn.rect))
        self.assertTrue(shell.controls_open)
        self.assertIs(shell._active_screen(), shell.controls_screen)

    def test_back_closes_the_overlay_without_leaving_settings(self):
        shell = make_shell()
        shell.open_settings(GameState.MAIN_MENU)
        shell.controls_open = True
        shell.handle_click(*center(shell.controls_screen.back_btn.rect))
        self.assertFalse(shell.controls_open)
        self.assertEqual(shell.state, GameState.SETTINGS)

    def test_escape_closes_the_overlay_when_not_capturing(self):
        shell = make_shell()
        shell.open_settings(GameState.MAIN_MENU)
        shell.controls_open = True
        shell.handle_key("", "escape")
        self.assertFalse(shell.controls_open)
        self.assertEqual(shell.state, GameState.SETTINGS)

    def test_the_shared_bindings_dict_reaches_the_screen(self):
        shell = make_shell()
        self.assertIs(shell.controls_screen.bindings, shell.key_bindings)
        self.assertEqual(shell.key_bindings["end_turn"], "space")


if __name__ == "__main__":
    unittest.main()
