"""``engine.input`` tests (feature: rebindable hotkeys).

Pure Python — load/save round-trip through a tempdir plus the two pure
helpers (``find_conflict``/``rebind``). Schema resolution reads the pinned
``FIXTURE_DATA`` snapshot (``test_fixture_guard.py`` forbids a new test from
reading live ``data/``), the ``test_player_identity.py`` precedent for
``scores/``-shaped persistence.
"""
import json
import tempfile
import unittest
from pathlib import Path

from tools.tests.fixture_data import FIXTURE_DATA

from engine import input as key_input

SCHEMA_PATH = FIXTURE_DATA / "schemas" / "keybindings.schema.json"

DEFAULTS = {
    "combat_speed_1": "1",
    "combat_speed_2": "2",
    "combat_speed_3": "3",
    "confirm_purchase": "return",
    "end_turn": "space",
    "quick_skip_combat": "p",
    "toggle_cheat_menu": "ctrl+l",
    "toggle_heatmap": "h",
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


if __name__ == "__main__":
    unittest.main()
