"""Spawnclaude (ED-60/61/62, AD-2): dispatch a `claude` session from the editor.

Three modes, all opening a Windows Terminal (`wt`) tab running `claude` in the
repo. The session's first input is the literal slash command, so Claude loads
that skill directly (no wordy natural-language wrapper):
- **Admin** → a blank `claude` session (no initial input, no scope) for
  unguarded work.
- **Dispatch handoff** → `/dispatch <handoff path>`. The editor writes a
  schema-valid handoff JSON (an "Add new X" form submission) and hands its
  repo-relative path to the `/dispatch` skill, which does git setup + payload
  translation and then drives the target `add-*` skill unmodified.
- **Small tweak** → `/smalltweak <task>`. Straight into the skill; no scope.

**The branch+lock protocol is SUSPENDED** (root `CLAUDE.md`, AD plan D6): the
old domain → `/start-domain` mode is gone from this module, and this module
writes NO lock and no `.claude/active_domain` (a test asserts it exposes no
set/clear/unlock symbol). `editor/locks.py` survives for the balancing panel's
read-only `_lock` display.

Pure command/prompt builders are Qt-free and unit-testable; the detached launch
reuses `editor.run_controls.start_detached`, which already strips the editor's
`SDL_VIDEODRIVER`/`SDL_AUDIODRIVER=dummy` vars (set by the viewport for its
offscreen surface) so the spawned terminal isn't polluted.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
)

from editor import run_controls

REPO = Path(__file__).resolve().parents[1]


# -- pure builders (no Qt state; unit-testable) -----------------------------

def dispatch_prompt(handoff_relpath):
    """Claude's opening input for a form dispatch: the literal /dispatch slash
    command with the repo-relative POSIX handoff path appended.

    Takes an ALREADY-relative POSIX string (AD-1's `agent_forms.handoff_relpath`
    produces it) — no path math here, so this module never imports agent_forms
    and stays trivially unit-testable."""
    return f"/dispatch {handoff_relpath}"


def small_tweak_prompt(text):
    """Claude's opening input for small-tweak mode: the literal `/smalltweak`
    slash command with the task appended — straight into the skill, no lock,
    no domain scope."""
    text = (text or "").strip()
    return f"/smalltweak {text}" if text else "/smalltweak"


def spawn_command(initial_prompt=None, repo=None, wt="wt"):
    """argv to open a Windows Terminal tab running `claude` in the repo. `cmd
    /k` keeps the tab open so a launch error (e.g. claude not on PATH) stays
    visible instead of the tab flashing shut. A falsy `initial_prompt` (admin
    mode) launches a blank `claude` with no opening input."""
    repo = Path(repo) if repo is not None else REPO
    argv = [wt, "-d", str(repo), "cmd", "/k", "claude"]
    if initial_prompt:
        argv.append(initial_prompt)
    return argv


def dispatch(handoff=None, tweak_prompt=None, admin=False, repo=None, detach=None):
    """Build + launch the terminal detached. Returns `started_ok` (bool).

    Mode precedence: `admin` (blank session, no input) > `handoff`
    (`/dispatch <relpath>`) > small-tweak (`/smalltweak`). Admin and small tweak
    bypass the dispatch path entirely (D5) — no handoff is written for them.
    `handoff` is a repo-relative POSIX path string. `detach` defaults to
    `run_controls.start_detached` (which strips the SDL dummy vars via
    `_real_window_environment` and uses the instance-form
    `QProcess().startDetached()`); it is injectable so tests substitute a fake
    launcher instead of spawning a real terminal."""
    repo = Path(repo) if repo is not None else REPO
    detach = detach or run_controls.start_detached
    if admin:
        prompt = None  # blank claude, no scope, no lock
    elif handoff:
        prompt = dispatch_prompt(handoff)
    else:
        prompt = small_tweak_prompt(tweak_prompt)
    argv = spawn_command(prompt, repo=repo)
    return detach(argv[0], argv[1:], repo)


# -- Qt dialog --------------------------------------------------------------

class SpawnClaudeDialog(QDialog):
    """Pick small-tweak or admin mode, then dispatch a claude terminal. Writes
    no lock and no `.claude/active_domain` (protocol suspended, D6).

    AD-3 rewrites this into the form launcher (one entry per form spec); AD-2
    keeps it minimal — the domain radios are gone, Small tweak + Admin remain."""

    def __init__(self, data_dir=None, repo=None, parent=None, detach=None):
        super().__init__(parent)
        self.setWindowTitle("Spawn Claude")
        self._repo = Path(repo) if repo is not None else REPO
        self._detach = detach  # None -> dispatch() uses run_controls.start_detached
        # `data_dir` is accepted-and-unused in AD-2 (main.py still passes it);
        # AD-3 uses it for agent_forms.load_form_specs.

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dispatch a Claude session:"))

        self._group = QButtonGroup(self)

        self._tweak_radio = QRadioButton("Small tweak (no lock)")
        self._group.addButton(self._tweak_radio)
        layout.addWidget(self._tweak_radio)
        self._tweak_edit = QLineEdit()
        self._tweak_edit.setPlaceholderText("What to tweak (scoped prompt)…")
        layout.addWidget(self._tweak_edit)

        # Admin: a blank claude session — no lock, no branch guard, no prompt.
        self._admin_radio = QRadioButton("Admin (blank session, no guards)")
        self._group.addButton(self._admin_radio)
        layout.addWidget(self._admin_radio)

        self._tweak_radio.setChecked(True)

        buttons = QDialogButtonBox()
        self._dispatch_button = buttons.addButton(
            "Dispatch", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_dispatch)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_dispatch(self):
        if self._admin_radio.isChecked():
            dispatch(admin=True, repo=self._repo, detach=self._detach)
        else:
            dispatch(tweak_prompt=self._tweak_edit.text(),
                     repo=self._repo, detach=self._detach)
        self.accept()
