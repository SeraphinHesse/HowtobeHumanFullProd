"""``engine.input`` tests (feature: rebindable hotkeys).

Pure Python — load/save round-trip through a tempdir plus the two pure
helpers (``find_conflict``/``rebind``). Schema resolution reads the pinned
``FIXTURE_DATA`` snapshot (``test_fixture_guard.py`` forbids a new test from
reading live ``data/``), the ``test_player_identity.py`` precedent for
``scores/``-shaped persistence.

Also covers ``game/main.py``'s ``_binding_pygame_key``/``_binding_held`` — the
REVERSE of ``_binding_key_name``, used to poll the movement hotkeys every
frame (held-down camera panning) rather than dispatch them on a single
KEYDOWN. pygame needs a real (dummy-driver) init for the ctrl-modifier check,
the ``test_game_boot.py`` precedent.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402

from tools.tests.fixture_data import FIXTURE_DATA  # noqa: E402

from engine import input as key_input  # noqa: E402
from game import main as game_main  # noqa: E402

SCHEMA_PATH = FIXTURE_DATA / "schemas" / "keybindings.schema.json"

DEFAULTS = {
    "combat_speed_1": "1",
    "combat_speed_2": "2",
    "combat_speed_3": "3",
    "confirm_purchase": "return",
    "end_turn": "space",
    "move_down": "s",
    "move_left": "a",
    "move_right": "d",
    "move_up": "w",
    "quick_skip_combat": "p",
    "toggle_cheat_menu": "ctrl+l",
    "toggle_drag_select": "q",
    "toggle_heatmap": "h",
    "toggle_range": "r",
    "toggle_tier_overview": "t",
    "zoom_level_1": "4",
    "zoom_level_2": "5",
    "zoom_level_3": "6",
}


class TestFindConflict(unittest.TestCase):
    def test_no_conflict_on_a_free_key(self):
        self.assertIsNone(
            key_input.find_conflict(DEFAULTS, "end_turn", "j"))

    def test_a_taken_key_reports_the_other_action(self):
        self.assertEqual(
            key_input.find_conflict(DEFAULTS, "toggle_heatmap", "space"),
            "end_turn")

    def test_an_action_never_conflicts_with_its_own_current_key(self):
        self.assertIsNone(
            key_input.find_conflict(DEFAULTS, "end_turn", "space"))


class TestRebind(unittest.TestCase):
    def test_rebind_is_pure_and_only_touches_the_named_action(self):
        updated = key_input.rebind(DEFAULTS, "end_turn", "j")
        self.assertEqual(updated["end_turn"], "j")
        self.assertEqual(updated["toggle_heatmap"], "h")
        # the input dict is untouched — the caller decides when to commit
        self.assertEqual(DEFAULTS["end_turn"], "space")


class TestLoadSaveRoundTrip(unittest.TestCase):
    def test_missing_file_returns_the_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "keybindings.json"
            loaded = key_input.load_keybindings(path, SCHEMA_PATH, DEFAULTS)
        self.assertEqual(loaded, DEFAULTS)
        self.assertIsNot(loaded, DEFAULTS)  # a copy, not the same object

    def test_save_then_load_round_trips_a_rebind(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "keybindings.json"
            updated = key_input.rebind(DEFAULTS, "end_turn", "j")
            key_input.save_keybindings(path, SCHEMA_PATH, updated)
            self.assertTrue(path.exists())  # parent dir created on demand

            reloaded = key_input.load_keybindings(path, SCHEMA_PATH, DEFAULTS)
        self.assertEqual(reloaded, updated)

    def test_a_corrupt_file_falls_back_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "keybindings.json"
            path.parent.mkdir(parents=True)
            path.write_text("not json at all", encoding="utf-8")

            loaded = key_input.load_keybindings(path, SCHEMA_PATH, DEFAULTS)
        self.assertEqual(loaded, DEFAULTS)

    def test_a_schema_invalid_file_falls_back_to_defaults_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "keybindings.json"
            path.parent.mkdir(parents=True)
            # missing every required key — schema-invalid, not just odd JSON
            path.write_text(json.dumps({"end_turn": "space"}), encoding="utf-8")

            loaded = key_input.load_keybindings(path, SCHEMA_PATH, DEFAULTS)
        self.assertEqual(loaded, DEFAULTS)


class TestBindingPygameKeyReverse(unittest.TestCase):
    """``game.main._binding_pygame_key``/``_binding_held`` — the reverse
    lookup the movement hotkeys poll through every frame."""

    @classmethod
    def setUpClass(cls):
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        pygame.quit()

    def test_resolves_a_bare_letter(self):
        self.assertEqual(game_main._binding_pygame_key("w"), pygame.K_w)

    def test_resolves_a_digit(self):
        self.assertEqual(game_main._binding_pygame_key("4"), pygame.K_4)

    def test_strips_the_ctrl_prefix_before_resolving(self):
        self.assertEqual(game_main._binding_pygame_key("ctrl+l"), pygame.K_l)

    def test_resolves_a_named_key(self):
        self.assertEqual(game_main._binding_pygame_key("space"), pygame.K_SPACE)

    def test_unresolvable_binding_returns_none(self):
        self.assertIsNone(game_main._binding_pygame_key(""))

    def _keys(self, *held):
        pressed = [False] * 512
        for key in held:
            pressed[key] = True
        return pressed

    def test_binding_held_true_when_the_key_is_pressed(self):
        self.assertTrue(
            game_main._binding_held("w", self._keys(pygame.K_w)))

    def test_binding_held_false_when_the_key_is_not_pressed(self):
        self.assertFalse(game_main._binding_held("w", self._keys()))

    def test_ctrl_binding_requires_the_modifier_too(self):
        # the base key alone is not enough for a ctrl+-prefixed binding
        self.assertFalse(
            game_main._binding_held("ctrl+l", self._keys(pygame.K_l)))


if __name__ == "__main__":
    unittest.main()
