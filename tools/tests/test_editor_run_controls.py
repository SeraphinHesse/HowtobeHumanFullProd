"""Phase 7 acceptance tests: MainWindow's run-controls wiring (ED-50/51/52).

Same headless conventions as the other editor tests. RunControls.play is
monkeypatched to a no-op spy so no real `py game/main.py` subprocess ever
launches during the unit test — that's a live-verification-only step.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtWidgets import QApplication

from editor.main import MainWindow
from editor.run_controls import RunControls

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)

STARTER = "first_light"


class RunControlsWiringCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        self.window = MainWindow(data_dir=self.data_dir)
        self.addCleanup(self.window.close)

    def test_toolbar_has_three_run_actions(self):
        self.assertEqual(self.window.play_action.text(), "Play")
        self.assertEqual(self.window.build_action.text(), "Build")
        self.assertEqual(self.window.playbuild_action.text(), "Playbuild")

    def test_playbuild_enabled_matches_build_exists(self):
        self.assertEqual(
            self.window.playbuild_action.isEnabled(),
            self.window.run_controls.can_playbuild())

    def test_playbuild_disabled_has_hint_tooltip(self):
        if self.window.run_controls.can_playbuild():
            self.skipTest("a build already exists in this repo")
        self.assertFalse(self.window.playbuild_action.isEnabled())
        self.assertIn("Build first", self.window.playbuild_action.toolTip())

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
