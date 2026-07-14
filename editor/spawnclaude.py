"""Spawnclaude (ED-60/61/62, AD-2/AD-3): dispatch a `claude` session from the
editor. `SpawnClaudeDialog` is the LAUNCHER behind the "Summon a Drunken Robot"
toolbar button.

Three modes, all opening a Windows Terminal (`wt`) tab running `claude` in the
repo. The session's first input is the literal slash command, so Claude loads
that skill directly (no wordy natural-language wrapper):
- **Form dispatch** → `/dispatch <handoff path>`. The launcher lists one entry
  per form spec (`data/agent_forms/*.json`, loaded FRESH on every open — a new
  spec needs no editor restart); the entry opens an `AgentFormDialog`, which
  writes a schema-valid handoff JSON and hands its repo-relative path to the
  `/dispatch` skill, which does git setup + payload translation and then drives
  the target `add-*` skill unmodified.
- **Small tweak** → `/smalltweak <task>`. Straight into the skill; no scope.
- **Admin** → a blank `claude` session (no initial input, no scope) for
  unguarded work.

Admin and small tweak bypass the dispatch path entirely (D5) — no handoff.
Precedence in `dispatch()`: admin > handoff > tweak.

**The branch+lock protocol is SUSPENDED** (root `CLAUDE.md`, AD plan D6): the
old domain → `/start-domain` mode is gone from this module, and this module
writes NO lock and no `.claude/active_domain` (a test asserts it exposes no
set/clear/unlock symbol). `editor/locks.py` survives for the balancing panel's
read-only `_lock` display.

Pure command/prompt builders are Qt-free and unit-testable; the detached launch
reuses `editor.run_controls.start_detached`, which already strips the editor's
`SDL_VIDEODRIVER`/`SDL_AUDIODRIVER=dummy` vars (set by the viewport for its
offscreen surface) so the spawned terminal isn't polluted.

**Import direction:** `AgentFormDialog` is imported LAZILY inside `_open_form`.
`editor.agent_form_dialog` imports this module at its top (for `dispatch`), so a
top-level import back would be a cycle; deferring it also keeps the pure
builders importable without pulling the Qt form dialog in.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from editor import agent_forms, run_controls

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
    """The launcher (AD-3): one button per form spec, plus the two prompt-only
    modes (small tweak / admin). Writes no lock and no `.claude/active_domain`
    (protocol suspended, D6).

    Built from small `_build_*_group()` helpers appended to ONE `QVBoxLayout`,
    with the button box built LAST — a deliberate seam so AD-7 can insert its
    Plans group with a single `layout.addWidget(...)` line and nothing else."""

    def __init__(self, data_dir=None, repo=None, parent=None, detach=None):
        super().__init__(parent)
        self.setWindowTitle("Spawn Claude")
        self._data_dir = data_dir  # None -> agent_forms defaults to <repo>/data
        self._repo = Path(repo) if repo is not None else REPO
        self._detach = detach  # None -> dispatch() uses run_controls.start_detached

        # Housekeeping on every open: drop stale handoffs (D2). Best-effort —
        # a failure to prune must never stop a designer from dispatching.
        try:
            agent_forms.prune_done(self._repo)
        except Exception:
            pass

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dispatch a Claude session:"))
        layout.addWidget(self._build_forms_group())
        layout.addWidget(self._build_modes_group())
        layout.addWidget(self._build_button_box())

    def _build_forms_group(self):
        """One button per form spec, read FRESH from disk on every open — a
        spec added by /add-form-spec (AD-5) shows up without an editor restart.
        A button is a door, not a mode: it opens the form, which dispatches
        itself. The two radios below stay radios."""
        box = QGroupBox("Add a new thing")
        layout = QVBoxLayout(box)
        self._form_buttons = {}
        try:
            specs = agent_forms.load_form_specs(self._data_dir)
        except Exception as exc:  # an invalid spec must not hide tweak/admin
            label = QLabel(f"Form specs failed to load: {exc}")
            label.setWordWrap(True)
            layout.addWidget(label)
            return box
        if not specs:
            layout.addWidget(QLabel("No form specs in data/agent_forms."))
        for spec in specs:
            button = QPushButton(spec["title"])
            button.setToolTip(spec["description"])
            button.clicked.connect(
                lambda _checked=False, s=spec: self._open_form(s))
            layout.addWidget(button)
            self._form_buttons[spec["id"]] = button
        return box

    def _build_modes_group(self):
        box = QGroupBox("Or dispatch a prompt-only session")
        layout = QVBoxLayout(box)
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
        return box

    def _build_button_box(self):
        """Governs the tweak/admin radios ONLY — the form buttons dispatch
        through their own dialog. Always the LAST widget in the layout."""
        buttons = QDialogButtonBox()
        self._dispatch_button = buttons.addButton(
            "Dispatch", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_dispatch)
        buttons.rejected.connect(self.reject)
        return buttons

    def _open_form(self, spec):
        # Lazy by design: agent_form_dialog imports this module at its top, so
        # a top-level import here would be a cycle (see the module docstring).
        from editor.agent_form_dialog import AgentFormDialog

        try:
            dialog = AgentFormDialog(spec, data_dir=self._data_dir,
                                     repo=self._repo, parent=self,
                                     detach=self._detach)
        except Exception as exc:  # bad field type / unknown schema_version
            QMessageBox.critical(self, "Cannot open the form", str(exc))
            return  # a raise out of a clicked slot would be swallowed by Qt
        if dialog.exec():  # dispatched already — close the launcher behind it
            self.accept()

    def _on_dispatch(self):
        if self._admin_radio.isChecked():
            dispatch(admin=True, repo=self._repo, detach=self._detach)
        else:
            dispatch(tweak_prompt=self._tweak_edit.text(),
                     repo=self._repo, detach=self._detach)
        self.accept()
