"""Phase 7 acceptance tests: MainWindow's run-controls wiring (ED-50/51/52).

Same headless conventions as the other editor tests. RunControls.play is
monkeypatched to a no-op spy so no real `py game/main.py` subprocess ever
launches during the unit test — that's a live-verification-only step.
"""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase
from tools.tests.temp_data import TempDataCase

from PySide6.QtWidgets import QApplication

from editor.main import MainWindow
from editor.run_controls import RunControls

REPO = Path(__file__).resolve().parents[2]

STARTER = "first_light"


class RunControlsWiringCase(TempDataCase):
    def setUp(self):
        super().setUp()
        self.window = self.track(MainWindow(data_dir=self.data_dir))

    def test_toolbar_has_three_run_actions(self):
        self.assertEqual(self.window.play_action.text(), "Play")
        self.assertEqual(self.window.build_action.text(), "Build")
        self.assertEqual(self.window.playbuild_action.text(), "Playbuild")

    def test_playbuild_enabled_matches_build_exists(self):
        self.assertEqual(
            self.window.playbuild_action.isEnabled(),
            self.window.run_controls.can_playbuild())

    def test_playbuild_disabled_has_hint_tooltip(self):
        """CONSTRUCT the no-build condition instead of skipping when reality
        does not happen to match it.

        This used to `self.skipTest("a build already exists in this repo")`
        whenever `dist/HowToBeHuman/HowToBeHuman.exe` was present — so it went
        silently missing on exactly the machines that build the game, while
        passing in CI, which never has one. An unexpected skip is a gate
        failure (root `CLAUDE.md`, Step 2: "a test that quietly stops running
        is indistinguishable from one that passes"), so the skip turned a
        developer's own build into a red gate on an unrelated branch.
        """
        with patch.object(RunControls, "can_playbuild", return_value=False):
            window = self.track(MainWindow(data_dir=self.data_dir))
            self.assertFalse(window.playbuild_action.isEnabled())
            self.assertIn("Build first", window.playbuild_action.toolTip())

    def test_play_saves_dirty_map_before_launching(self):
        self.window.selector.select_map(STARTER)
        session = self.window.map_session
        session.push_rename("Renamed Map")
        self.assertTrue(session.dirty)

        with patch.object(RunControls, "play") as spy:
            self.window._on_play()

        self.assertFalse(session.dirty)
        spy.assert_called_once()

    def test_play_skips_launch_on_validation_failure(self):
        with patch("editor.main.validate_data", side_effect=ValueError("boom")), \
             patch.object(RunControls, "play") as spy, \
             patch("editor.main.QMessageBox.critical") as msg:
            self.window._on_play()

        spy.assert_not_called()
        msg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
