"""player-identity: high-score persistence, the menu matrix, the prompt, the id.

Four narrow contracts, one per class — the pieces of the feature that are pure
logic and therefore cheaply pinnable:

1. the ``scores/highscores.json`` round trip (append -> reload -> ``last_player``),
2. ``MainMenu``'s four-way availability matrix + its both-off fail-safe,
3. ``PlayerIntroScreen``'s radio selection + ``hit()``/``handle_key()`` strings,
4. that a player identity actually reaches the ``DebugRecorder`` run id (hence
   all four artifact filenames).

**Nothing here touches ``data/``.** The scores file is written into a
``tempfile`` directory, and schema resolution reads the pinned ``FIXTURE_DATA``
snapshot (``test_fixture_guard.py`` forbids a new test from reading live
``data/``). No pygame: ``game/ui`` is pure rect math and the recorder is stdlib.
"""
import tempfile
import unittest
from pathlib import Path

from tools.tests.fixture_data import FIXTURE_DATA

from game.core import highscores
from game.debug import DebugRecorder
from game.ui import widgets
from game.ui.main_menu import MainMenu
from game.ui.player_intro import PlayerIntroScreen

VW, VH = 640, 360


def center(rect):
    x, y, w, h = rect
    return (x + w // 2, y + h // 2)


class TestHighscoreRoundTrip(unittest.TestCase):
    """Append -> reload through the validating writer, in a tempdir."""

    def test_entry_and_last_player_survive_a_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "highscores.json"
            entry = highscores.make_entry("Ada", "a_lot", 7, 12, 40,
                                          run_id="run-x", debug=True)
            highscores.append_score(path, entry, FIXTURE_DATA)

            doc = highscores.load_highscores(path, FIXTURE_DATA)
        self.assertEqual(len(doc["entries"]), 1)
        stored = doc["entries"][0]
        self.assertEqual(stored["name"], "Ada")
        self.assertEqual(stored["skill"], "a_lot")
        self.assertEqual(stored["round_reached"], 7)
        self.assertEqual(stored["buildings_placed"], 12)
        self.assertEqual(stored["enemies_killed"], 40)
        self.assertEqual(stored["run_id"], "run-x")
        self.assertTrue(stored["debug"])
        self.assertEqual(highscores.last_player(doc), ("Ada", "a_lot"))

    def test_blank_identity_normalises_to_anonymous_unknown(self):
        """The ONE place the defaults live — a regular (unstamped) run's
        ``(None, None)`` identity must still produce a schema-valid row."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "scores" / "highscores.json"
            highscores.append_score(
                path, highscores.make_entry(None, None, 3, 0, 0), FIXTURE_DATA)
            doc = highscores.load_highscores(path, FIXTURE_DATA)
        self.assertEqual(highscores.last_player(doc),
                         (highscores.ANONYMOUS, highscores.UNKNOWN_SKILL))


class TestMenuAvailabilityMatrix(unittest.TestCase):
    """The four ``regular_mode_available`` x ``debug_mode_available`` cases.

    The id/action decoupling is the point: the START NEW GAME slot keeps its
    ``btn_new_game`` id and its position in every case — only the action it
    EMITS moves."""

    @staticmethod
    def _menu(regular, debug):
        return MainMenu(VW, VH, debug_balance={
            "regular_mode_available": regular, "debug_mode_available": debug})

    @staticmethod
    def _visible(menu):
        return {slot: btn.visible for btn, slot in menu.buttons}

    @staticmethod
    def _start_slot_action(menu):
        """What clicking the top (START NEW GAME) row emits."""
        for btn, slot in menu.buttons:
            if slot == "new_game":
                return menu.hit(*center(btn.rect))
        raise AssertionError("no new_game slot")

    def test_both_available_shows_both_rows(self):
        menu = self._menu(True, True)
        visible = self._visible(menu)
        self.assertTrue(visible["new_game"])
        self.assertTrue(visible["play_debug"])
        self.assertTrue(menu.debug_gear.visible)
        self.assertEqual(self._start_slot_action(menu), "new_game")

    def test_debug_off_hides_the_play_debug_row_and_its_gear(self):
        menu = self._menu(True, False)
        visible = self._visible(menu)
        self.assertTrue(visible["new_game"])
        self.assertFalse(visible["play_debug"])
        self.assertFalse(menu.debug_gear.visible)
        self.assertEqual(self._start_slot_action(menu), "new_game")

    def test_regular_off_moves_the_debug_action_onto_the_start_slot(self):
        menu = self._menu(False, True)
        visible = self._visible(menu)
        self.assertTrue(visible["new_game"])      # the SLOT (and its id) stays
        self.assertFalse(visible["play_debug"])
        self.assertTrue(menu.debug_gear.visible)  # the gear moves up with it
        self.assertEqual(self._start_slot_action(menu), "play_debug")

    def test_both_off_falls_back_to_regular_only(self):
        """The fail-safe: never ship a menu with no way to start a game."""
        menu = self._menu(False, False)
        visible = self._visible(menu)
        self.assertTrue(visible["new_game"])
        self.assertFalse(visible["play_debug"])
        self.assertFalse(menu.debug_gear.visible)
        self.assertEqual(self._start_slot_action(menu), "new_game")

    def test_bare_construction_is_both_available(self):
        """No ``debug_balance`` at all (the exporter / the golden pin) behaves
        exactly as it did before this feature. SaveGamePLAN SG-6 exception:
        CONTINUE is hidden on a bare construction (``has_saves`` defaults to
        ``False``, a user decision — hidden entirely with no saves yet), so
        it is excluded from the "everything visible" check rather than
        changing that decision."""
        menu = MainMenu(VW, VH)
        visible = self._visible(menu)
        del visible["continue"]
        self.assertTrue(all(visible.values()))
        self.assertEqual(self._start_slot_action(menu), "new_game")


class TestPlayerIntroPrompt(unittest.TestCase):
    """Radio selection + the documented ``hit()``/``handle_key()`` strings."""

    def setUp(self):
        self.screen = PlayerIntroScreen(VW, VH)

    def _option(self, value):
        for val, btn in self.screen.options:
            if val == value:
                return btn
        raise AssertionError(f"no option {value}")

    def test_clicking_an_option_selects_it_and_deselects_the_rest(self):
        screen = self.screen
        self.assertIsNone(screen.hit(*center(self._option("developer").rect)))
        self.assertEqual(screen.skill, "developer")
        screen.update(0.0, -1000, -1000, False)   # off-screen cursor: no hover
        gold = [value for value, btn in screen.options
                if btn.text_color == widgets.C_GOLD]
        self.assertEqual(gold, ["developer"])

        # A second click moves the selection — exactly one stays selected.
        screen.hit(*center(self._option("a_bit").rect))
        screen.update(0.0, -1000, -1000, False)
        gold = [value for value, btn in screen.options
                if btn.text_color == widgets.C_GOLD]
        self.assertEqual(gold, ["a_bit"])

    def test_hit_returns_the_documented_strings(self):
        screen = self.screen
        self.assertEqual(screen.hit(*center(screen.start_btn.rect)), "start")
        self.assertEqual(screen.hit(*center(screen.back_btn.rect)), "back")
        self.assertEqual(screen.hit(*center(screen.name_rect)), "name")

    def test_handle_key_returns_the_documented_strings_and_types(self):
        screen = self.screen
        screen.reset("", None)                    # focused, first option
        self.assertEqual(screen.skill, highscores.SKILLS[0])
        self.assertIsNone(screen.handle_key("A", None))
        self.assertIsNone(screen.handle_key("d", None))
        self.assertEqual(screen.player_name, "Ad")
        self.assertIsNone(screen.handle_key("", "backspace"))
        self.assertEqual(screen.player_name, "A")
        self.assertEqual(screen.handle_key("", "return"), "start")
        self.assertEqual(screen.handle_key("", "escape"), "back")


class TestPlayerStampedRunId(unittest.TestCase):
    """The identity reaches the run id, hence all four artifact filenames."""

    def test_run_id_and_paths_carry_the_slugged_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp, player_name="Ada Lovelace!",
                                player_skill="a_lot")
            self.assertTrue(rec.run_id.endswith("-AdaLovelace-a_lot"),
                            rec.run_id)
            for key, suffix in (("jsonl", "-events.jsonl"), ("csv", "-rounds.csv"),
                                ("md", "-summary.md"), ("html", "-report.html")):
                self.assertEqual(rec.paths[key].name, f"{rec.run_id}{suffix}")

    def test_an_unnamed_run_keeps_the_plain_run_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = DebugRecorder(tmp)
            self.assertFalse(rec.run_id.endswith("-"))
            self.assertEqual(rec.run_id.count("-"), 2)  # run-<date>-<time>


if __name__ == "__main__":
    unittest.main()
