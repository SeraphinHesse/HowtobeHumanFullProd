"""player-identity: high-score persistence, the menu matrix, the prompt, the id.

Four narrow contracts, one per class — the pieces of the feature that are pure
logic and therefore cheaply pinnable:

1. the ``scores/highscores.json`` round trip (append -> reload -> ``last_player``),
   including the CORRUPT-FILE path: an unreadable file is moved aside, never
   overwritten, and renaming inside one is refused outright,
2. ``MainMenu``'s four-way availability matrix + its both-off fail-safe,
3. ``PlayerIntroScreen``'s radio selection + ``hit()``/``handle_key()`` strings,
4. that a player identity actually reaches the ``DebugRecorder`` run id (hence
   all four artifact filenames),
5. ``HighscoresScreen``'s rename seam — that the committed index is the DISK
   index, not the display row.

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
from game.ui.highscores import HighscoresScreen
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


class TestUnreadableScoresFile(unittest.TestCase):
    """The bug this class exists for: ``append_score`` used to load through
    ``load_highscores`` — which returns an EMPTY doc for an unreadable file —
    and then write that empty doc back, so one truncated byte turned the whole
    play history into a one-entry file. A write must tell 'absent' from
    'unloadable' and never overwrite the second."""

    CORRUPT = '{"entries": [{"name": "Ada"'      # truncated mid-object

    def _corrupt_file(self, tmp):
        path = Path(tmp) / "scores" / "highscores.json"
        path.parent.mkdir(parents=True)
        path.write_text(self.CORRUPT, encoding="utf-8")
        return path

    def test_read_highscores_separates_absent_from_unloadable(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "scores" / "highscores.json"
            self.assertEqual(
                highscores.read_highscores(missing, FIXTURE_DATA)[1], True)
            path = self._corrupt_file(tmp)
            doc, ok = highscores.read_highscores(path, FIXTURE_DATA)
        self.assertFalse(ok)
        self.assertEqual(doc["entries"], [])     # readers still get a doc

    def test_append_moves_the_bad_file_aside_instead_of_wiping_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._corrupt_file(tmp)
            highscores.append_score(
                path, highscores.make_entry("Bob", "never", 2, 0, 0),
                FIXTURE_DATA)
            rescued = path.with_name("highscores.corrupt.json")
            self.assertTrue(rescued.exists())
            self.assertEqual(rescued.read_text(encoding="utf-8"), self.CORRUPT)
            doc = highscores.load_highscores(path, FIXTURE_DATA)
        self.assertEqual([e["name"] for e in doc["entries"]], ["Bob"])

    def test_a_second_corruption_gets_its_own_rescue_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._corrupt_file(tmp)
            path.with_name("highscores.corrupt.json").write_text(
                "older", encoding="utf-8")
            highscores.append_score(
                path, highscores.make_entry("Bob", "never", 2, 0, 0),
                FIXTURE_DATA)
            first = path.with_name("highscores.corrupt.json")
            second = path.with_name("highscores.corrupt.1.json")
            self.assertEqual(first.read_text(encoding="utf-8"), "older")
            self.assertEqual(second.read_text(encoding="utf-8"), self.CORRUPT)

    def test_rename_refuses_rather_than_rewriting_an_unreadable_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._corrupt_file(tmp)
            with self.assertRaises(OSError):
                highscores.rename_entry(path, 0, "Ada", FIXTURE_DATA)
            self.assertEqual(path.read_text(encoding="utf-8"), self.CORRUPT)


class TestRenameEntry(unittest.TestCase):
    """``rename_entry`` addresses the FILE (play order), not the table."""

    def _seed(self, tmp):
        path = Path(tmp) / "scores" / "highscores.json"
        for name, rnd in (("Ada", 3), ("Bob", 9), ("Cyd", 5)):
            highscores.append_score(
                path, highscores.make_entry(name, "never", rnd, 0, 0),
                FIXTURE_DATA)
        return path

    def test_renames_by_disk_index_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            highscores.rename_entry(path, 0, "  Ada L.  ", FIXTURE_DATA)
            doc = highscores.load_highscores(path, FIXTURE_DATA)
        self.assertEqual([e["name"] for e in doc["entries"]],
                         ["Ada L.", "Bob", "Cyd"])
        # Not the last entry, so the identity prefill is untouched.
        self.assertEqual(highscores.last_player(doc), ("Cyd", "never"))

    def test_renaming_the_last_run_refreshes_last_player(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            highscores.rename_entry(path, 2, "", FIXTURE_DATA)   # blank
            doc = highscores.load_highscores(path, FIXTURE_DATA)
        self.assertEqual(doc["entries"][2]["name"], highscores.ANONYMOUS)
        self.assertEqual(highscores.last_player(doc),
                         (highscores.ANONYMOUS, "never"))

    def test_an_index_with_no_entry_raises_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._seed(tmp)
            before = path.read_text(encoding="utf-8")
            with self.assertRaises(IndexError):
                highscores.rename_entry(path, 3, "Nope", FIXTURE_DATA)
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_ranked_rows_carry_the_disk_index(self):
        doc = {"version": 1, "last_player": {"name": "", "skill": "unknown"},
               "entries": [{"name": "Ada", "round_reached": 3},
                           {"name": "Bob", "round_reached": 9}]}
        self.assertEqual([(i, e["name"]) for i, e in highscores.ranked_rows(doc)],
                         [(1, "Bob"), (0, "Ada")])
        self.assertEqual([e["name"] for e in highscores.ranked(doc)],
                         ["Bob", "Ada"])


class TestHighscoreScreenRename(unittest.TestCase):
    """The screen commits a ``(disk_index, name)`` pair and writes nothing."""

    DOC = {"version": 1, "last_player": {"name": "", "skill": "unknown"},
           "entries": [{"name": "Ada", "skill": "never", "round_reached": 3,
                        "buildings_placed": 0, "enemies_killed": 0},
                       {"name": "Bob", "skill": "never", "round_reached": 9,
                        "buildings_placed": 0, "enemies_killed": 0}]}

    def _screen(self):
        screen = HighscoresScreen(VW, VH)
        screen.set_doc(self.DOC)
        return screen

    def test_enter_commits_the_disk_index_of_the_selected_display_row(self):
        screen = self._screen()
        # Display row 1 is "Ada" (round 3 sorts BELOW Bob's 9) — disk index 0.
        screen.handle_key("", "down")            # selects display row 0 (Bob)
        screen.handle_key("", "down")            # -> display row 1 (Ada)
        self.assertEqual(screen.selected, 1)
        self.assertIsNone(screen.handle_key("", "return"))   # begin editing
        self.assertTrue(screen.editing)
        self.assertEqual(screen.edit_text, "Ada")
        screen.handle_key("", "backspace")
        screen.handle_key("x", None)
        self.assertEqual(screen.handle_key("", "return"), "rename")
        self.assertEqual(screen.pending_rename, (0, "Adx"))
        self.assertFalse(screen.editing)

    def test_escape_cancels_the_edit_instead_of_leaving_the_screen(self):
        screen = self._screen()
        screen.handle_key("", "down")
        screen.handle_key("", "return")
        screen.handle_key("z", None)
        self.assertIsNone(screen.handle_key("", "escape"))
        self.assertFalse(screen.editing)
        self.assertIsNone(screen.pending_rename)
        # Only now does Esc mean BACK.
        self.assertEqual(screen.handle_key("", "escape"), "back")

    def test_rename_button_is_dead_until_a_row_is_picked(self):
        screen = self._screen()
        screen.update(0.0, -1000, -1000, False)
        self.assertFalse(screen.rename_btn.enabled)
        self.assertIsNone(screen.hit(*center(screen.rename_btn.rect)))
        screen.handle_key("", "down")
        screen.update(0.0, -1000, -1000, False)
        self.assertTrue(screen.rename_btn.enabled)
        self.assertIsNone(screen.hit(*center(screen.rename_btn.rect)))
        self.assertTrue(screen.editing)          # first press = start editing
        screen.update(0.0, -1000, -1000, False)
        self.assertEqual(screen.rename_btn.label, "SAVE")
        self.assertEqual(screen.hit(*center(screen.rename_btn.rect)), "rename")

    def test_keep_view_survives_the_host_re_handing_the_document(self):
        screen = self._screen()
        screen.handle_key("", "down")
        screen.set_doc(self.DOC, keep_view=True)
        self.assertEqual(screen.selected, 0)
        screen.set_doc(self.DOC)                 # a fresh open rewinds
        self.assertIsNone(screen.selected)


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
        exactly as it did before this feature."""
        menu = MainMenu(VW, VH)
        self.assertTrue(all(self._visible(menu).values()))
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
