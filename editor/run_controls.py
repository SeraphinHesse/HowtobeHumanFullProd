"""Run controls (ED-50/51/52, T-4): Play / Build / Playbuild — always
subprocesses; the editor never runs game logic in-process (root CLAUDE.md
"editor and game never import each other").

Pure path/command builders are Qt-free and independently testable.

Play and Playbuild launch a long-running GUI process (a pygame window, or
the frozen exe) that the user closes on their own schedule — tracking that
via a QProcess parented to this QObject risks a "Signal source has been
deleted" crash if anything in the editor's object tree gets torn down while
it's still running, and the editor has no reason to babysit it anyway. Both
go through `QProcess.startDetached` (a bare OS-level launch, no Qt object,
no output capture, no lifetime coupling to the editor).

`Build` is the one case that still needs progress in the console pane
(it's short-lived and its errors matter) — `RunControls` tracks exactly
that one subprocess via a QProcess and streams its merged stdout/stderr as
`output` signals. It does NOT save dirty data or validate schemas itself —
`editor/main.py` does that immediately before calling `play()`, keeping
this module a dumb subprocess launcher.
"""
import sys
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

REPO = Path(__file__).resolve().parents[1]


def play_command(python_exe=None, repo=None):
    repo = Path(repo) if repo is not None else REPO
    return [python_exe or sys.executable, str(repo / "game" / "main.py")]


def build_command(python_exe=None, repo=None):
    repo = Path(repo) if repo is not None else REPO
    return [python_exe or sys.executable, str(repo / "tools" / "build.py")]


def playbuild_path(repo=None):
    repo = Path(repo) if repo is not None else REPO
    return repo / "dist" / "HowToBeHuman" / "HowToBeHuman.exe"


def build_exists(repo=None):
    return playbuild_path(repo).is_file()


def _real_window_environment():
    """The editor's own env has SDL_VIDEODRIVER/SDL_AUDIODRIVER forced to
    "dummy" (editor/panels/viewport.py, set at import time for its offscreen
    render surface) — QProcess inherits the CURRENT process's environment,
    so Play/Playbuild would otherwise launch a real game/exe that renders
    into an invisible offscreen surface (it runs and prints fps, but no
    window ever appears — confirmed live). Strip both so the child picks
    its own real driver."""
    env = QProcessEnvironment.systemEnvironment()
    env.remove("SDL_VIDEODRIVER")
    env.remove("SDL_AUDIODRIVER")
    return env


def start_detached(program, arguments, working_dir):
    """The real launcher `RunControls` uses for Play/Playbuild — a module
    function (not a QProcess/Shiboken method) so tests can substitute it
    wholesale via `RunControls._detach` instead of trying to mock a C++-
    bound method (autospec silently failed to intercept instance-form
    `QProcess.startDetached()` in practice — the real method ran unmocked).
    The instance form (vs. the static `QProcess.startDetached(program,
    arguments, workingDirectory)`, which only takes those three and returns
    an (ok, pid) tuple) is the only way to hand the detached child a
    real-driver environment, and it returns a plain bool."""
    process = QProcess()
    process.setProgram(program)
    process.setArguments(list(arguments))
    process.setWorkingDirectory(str(working_dir))
    process.setProcessEnvironment(_real_window_environment())
    return process.startDetached()


class RunControls(QObject):
    output = Signal(str)          # one chunk of merged Build stdout+stderr
    started = Signal(str)         # "build" — the one tracked, streamed op
    finished = Signal(str, int)   # ("build", exit_code)
    build_state_changed = Signal(bool)  # re-evaluated after every Build finishes
    launched = Signal(str, bool)  # ("play" | "playbuild", started_ok) — detached

    def __init__(self, data_dir=None, repo=None, parent=None):
        super().__init__(parent)
        self._repo = Path(repo) if repo is not None else REPO
        self._data_dir = Path(data_dir) if data_dir is not None else self._repo / "data"
        self._process = None
        self._which = None
        self._detach = start_detached  # injectable per-instance for tests

    def is_running(self):
        return self._process is not None

    def can_playbuild(self):
        return build_exists(self._repo)

    def play(self):
        cmd = play_command(repo=self._repo)
        ok = self._detach(cmd[0], cmd[1:], self._repo)
        self.launched.emit("play", ok)

    def playbuild(self):
        exe = playbuild_path(self._repo)
        ok = self._detach(str(exe), [], exe.parent)
        self.launched.emit("playbuild", ok)

    def build(self):
        self._launch("build", build_command(repo=self._repo))

    # -- internals -----------------------------------------------------------

    def _launch(self, which, command):
        if self._process is not None:
            return  # a run is already in flight; refuse to stack subprocesses
        self._which = which
        process = QProcess(self)
        process.setWorkingDirectory(str(self._repo))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        # Python fully block-buffers stdout when it isn't a tty (the QProcess
        # pipe case) — without this the console pane gets nothing until the
        # subprocess exits, defeating ED-51's "progress surfaced live".
        env = QProcessEnvironment.systemEnvironment()
        env.insert("PYTHONUNBUFFERED", "1")
        process.setProcessEnvironment(env)
        process.readyReadStandardOutput.connect(
            lambda: self._on_ready_read(process))
        process.finished.connect(
            lambda code, _status: self._on_finished(code))
        self._process = process
        self.started.emit(which)
        process.start(command[0], command[1:])

    def _on_ready_read(self, process):
        if not shiboken6.isValid(self):
            return  # editor torn down mid-build; nothing left to notify
        text = bytes(process.readAllStandardOutput()).decode(
            "utf-8", errors="replace")
        if text:
            self.output.emit(text)

    def _on_finished(self, code):
        if not shiboken6.isValid(self):
            return  # editor torn down mid-build; nothing left to notify
        which = self._which
        self._process = None
        self._which = None
        self.finished.emit(which, code)
        if which == "build":
            self.build_state_changed.emit(self.can_playbuild())
