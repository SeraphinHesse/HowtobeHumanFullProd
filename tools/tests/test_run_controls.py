"""Phase 7 acceptance tests: run controls (ED-50/51/52).

Pure path/command builders are exercised directly. Build's QProcess wiring
(the one tracked, streamed subprocess) is exercised with a fast injected
dummy command — never a real PyInstaller build. Play/Playbuild are
detached (`QProcess.startDetached`, no Qt object, no output capture — see
run_controls.py's module docstring for why) so their tests substitute
`RunControls._detach` with a fake rather than actually spawning a pygame
window or exe (that's a live-verification-only step, per T-5).

This file itself sets SDL_VIDEODRIVER/SDL_AUDIODRIVER to "dummy" below —
the same thing editor/panels/viewport.py does for its own offscreen render
surface — so `test_real_window_environment_strips_sdl_dummy_vars` is a
genuine regression test for the bug found live: Play/Playbuild inheriting
that dummy driver and rendering into an invisible surface.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from editor.run_controls import (
    RunControls,
    build_command,
    build_exists,
    play_command,
    playbuild_path,
)
from editor.run_controls import _real_window_environment

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


def pump_until(signal, timeout_ms=5000):
    """Spin the Qt event loop until `signal` fires once, or time out."""
    loop = QEventLoop()
    signal.connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


class TestPureBuilders(unittest.TestCase):
    def test_play_command_targets_game_main(self):
        cmd = play_command(repo=REPO)
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]), REPO / "game" / "main.py")

    def test_build_command_targets_build_script(self):
        cmd = build_command(repo=REPO)
        self.assertEqual(cmd[0], sys.executable)
        self.assertEqual(Path(cmd[1]), REPO / "tools" / "build.py")

    def test_playbuild_path(self):
        self.assertEqual(
            playbuild_path(REPO),
            REPO / "dist" / "HowToBeHuman" / "HowToBeHuman.exe")

    def test_build_exists_false_without_dist(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(build_exists(Path(tmp)))

    def test_build_exists_true_with_fake_exe(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "dist" / "HowToBeHuman" / "HowToBeHuman.exe"
            exe.parent.mkdir(parents=True)
            exe.write_bytes(b"fake")
            self.assertTrue(build_exists(Path(tmp)))

    def test_real_window_environment_strips_sdl_dummy_vars(self):
        """Regression test for the live bug: Play/Playbuild inheriting the
        editor's own offscreen SDL_VIDEODRIVER=dummy (set above, same as
        editor/panels/viewport.py) rendered into an invisible surface."""
        env = _real_window_environment()
        self.assertFalse(env.contains("SDL_VIDEODRIVER"))
        self.assertFalse(env.contains("SDL_AUDIODRIVER"))


class TestPlayPlaybuildDetached(unittest.TestCase):
    """Play/Playbuild never create a QProcess tracked by RunControls; they
    go through the injectable `RunControls._detach` hook (default
    `run_controls.start_detached`) rather than a tracked signal-emitting
    QProcess. Tests substitute a fake `_detach` — mocking `QProcess.
    startDetached` directly proved unreliable (`autospec` silently failed
    to intercept the instance-form call; the real method ran unmocked)."""

    def setUp(self):
        self.controls = RunControls(repo=REPO)
        self.addCleanup(self.controls.deleteLater)

    def test_play_calls_detach_with_game_main(self):
        calls = []
        self.controls._detach = lambda *a: (calls.append(a), True)[-1]
        events = []
        self.controls.launched.connect(lambda which, ok: events.append((which, ok)))

        self.controls.play()

        self.assertEqual(len(calls), 1)
        program, arguments, working_dir = calls[0]
        self.assertEqual(program, sys.executable)
        self.assertEqual(Path(arguments[0]), REPO / "game" / "main.py")
        self.assertEqual(Path(working_dir), REPO)
        self.assertEqual(events, [("play", True)])
        self.assertFalse(self.controls.is_running())  # never tracked

    def test_playbuild_calls_detach_with_the_exe(self):
        calls = []
        self.controls._detach = lambda *a: (calls.append(a), True)[-1]
        events = []
        self.controls.launched.connect(lambda which, ok: events.append((which, ok)))

        self.controls.playbuild()

        self.assertEqual(len(calls), 1)
        program, arguments, _working_dir = calls[0]
        self.assertEqual(Path(program), playbuild_path(REPO))
        self.assertEqual(arguments, [])
        self.assertEqual(events, [("playbuild", True)])

    def test_launched_reports_failure(self):
        self.controls._detach = lambda *a: False
        events = []
        self.controls.launched.connect(lambda which, ok: events.append((which, ok)))
        self.controls.play()
        self.assertEqual(events, [("play", False)])


class TestBuildProcess(unittest.TestCase):
    """Build is the one tracked, streamed subprocess (short-lived, progress
    matters) — exercised via `_launch` with a fast injected dummy command."""

    def setUp(self):
        self.controls = RunControls(repo=REPO)
        self.addCleanup(self.controls.deleteLater)

    def test_build_streams_output_and_reports_exit_code(self):
        events = []
        self.controls.started.connect(lambda which: events.append(("started", which)))
        self.controls.output.connect(lambda text: events.append(("output", text)))
        self.controls.finished.connect(
            lambda which, code: events.append(("finished", which, code)))

        self.controls._launch(
            "build",
            [sys.executable, "-c", "print('hi'); import sys; sys.exit(3)"])
        pump_until(self.controls.finished)

        self.assertIn(("started", "build"), events)
        self.assertTrue(any(kind == "output" and "hi" in text
                             for kind, text in
                             ((e[0], e[1]) for e in events if e[0] == "output")))
        self.assertIn(("finished", "build", 3), events)

    def test_refuses_to_stack_a_second_launch(self):
        self.controls._launch(
            "build", [sys.executable, "-c", "import time; time.sleep(1)"])
        self.assertTrue(self.controls.is_running())
        self.controls._launch("build", [sys.executable, "-c", "print('nope')"])
        # second launch was refused: the in-flight process is still tracked
        self.assertEqual(self.controls._which, "build")
        pump_until(self.controls.finished)

    def test_build_finished_reemits_build_state(self):
        seen = []
        self.controls.build_state_changed.connect(seen.append)
        self.controls._launch("build", [sys.executable, "-c", "pass"])
        pump_until(self.controls.finished)
        self.assertEqual(seen, [self.controls.can_playbuild()])


if __name__ == "__main__":
    unittest.main()
