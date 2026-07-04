"""Spawnclaude (ED-60/61/62): dispatch a domain-scoped `claude` session from
the editor.

Three modes, all opening a Windows Terminal (`wt`) tab running `claude` in the
repo. The session's first input is the literal slash command, so Claude loads
that skill directly (no wordy natural-language wrapper):
- **Domain** → `/start-domain <domain>`. **Lock model (user-confirmed
  delegation):** the editor NEVER writes a domain lock — the spawned
  `/start-domain` skill does, so the branch+lock protocol stays the single
  lock-writer, preserving `editor/locks.py`'s read-only invariant and ED-62's
  "one enforcement point."
- **Small tweak** → `/smalltweak <task>`. Straight into the skill; no lock, no
  domain scope (the scope guard fail-opens when no domain is active).
- **Admin** → a blank `claude` session (no initial input, no lock, no scope) for
  unguarded work.

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

from editor import locks, run_controls

REPO = Path(__file__).resolve().parents[1]


# -- pure builders (no Qt state; unit-testable) -----------------------------

def domain_choices(data_dir=None):
    """`[{domain, locked, owner, since}]` in D-10 order — drives the dialog's
    greying of already-locked domains (ED-61). Reads locks only (never writes)."""
    out = []
    for domain in locks.DOMAINS:
        locked = locks.is_locked(domain, data_dir)
        out.append({
            "domain": domain,
            "locked": locked,
            "owner": locks.owner(domain, data_dir) if locked else None,
            "since": locks.since(domain, data_dir) if locked else None,
        })
    return out


def start_domain_prompt(domain):
    """Claude's opening input for a domain choice: the literal `/start-domain`
    slash command, so Claude loads that skill directly (delegation model — the
    skill, not the editor, writes the lock)."""
    return f"/start-domain {domain}"


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


def dispatch(domain=None, tweak_prompt=None, admin=False, repo=None, detach=None):
    """Build + launch the terminal detached. Returns `started_ok` (bool).

    Mode precedence: `admin` (blank session, no input) > `domain`
    (`/start-domain`) > small-tweak (`/smalltweak`). `detach` defaults to
    `run_controls.start_detached` (which strips the SDL dummy vars via
    `_real_window_environment` and uses the instance-form
    `QProcess().startDetached()`); it is injectable so tests substitute a fake
    launcher instead of spawning a real terminal."""
    repo = Path(repo) if repo is not None else REPO
    detach = detach or run_controls.start_detached
    if admin:
        prompt = None  # blank claude, no scope, no lock
    elif domain is not None:
        prompt = start_domain_prompt(domain)
    else:
        prompt = small_tweak_prompt(tweak_prompt)
    argv = spawn_command(prompt, repo=repo)
    return detach(argv[0], argv[1:], repo)


# -- Qt dialog --------------------------------------------------------------

class SpawnClaudeDialog(QDialog):
    """Pick a domain (locked ones greyed with owner shown, ED-61) or small-tweak
    mode, then dispatch a scoped claude terminal. Reads locks fresh on open; the
    dialog itself never writes a lock (the spawned /start-domain does, ED-60)."""

    def __init__(self, data_dir=None, repo=None, parent=None, detach=None):
        super().__init__(parent)
        self.setWindowTitle("Spawn Claude")
        self._repo = Path(repo) if repo is not None else REPO
        self._detach = detach  # None -> dispatch() uses run_controls.start_detached

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dispatch a scoped Claude session:"))

        self._group = QButtonGroup(self)
        self._domain_buttons = {}
        for info in domain_choices(data_dir):
            domain = info["domain"]
            if info["locked"]:
                text = (f"{domain} — locked by {info['owner']} "
                        f"since {info['since']}")
            else:
                text = domain
            button = QRadioButton(text)
            if info["locked"]:
                button.setEnabled(False)  # greyed out (ED-61)
            self._group.addButton(button)
            self._domain_buttons[domain] = button
            layout.addWidget(button)

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

        # Default selection: first unlocked domain, else small-tweak.
        for button in self._domain_buttons.values():
            if button.isEnabled():
                button.setChecked(True)
                break
        else:
            self._tweak_radio.setChecked(True)

        buttons = QDialogButtonBox()
        self._dispatch_button = buttons.addButton(
            "Dispatch", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_dispatch)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_domain(self):
        """The chosen domain, or None for small-tweak / admin mode."""
        if self._tweak_radio.isChecked() or self._admin_radio.isChecked():
            return None
        for domain, button in self._domain_buttons.items():
            if button.isChecked():
                return domain
        return None

    def _on_dispatch(self):
        if self._admin_radio.isChecked():
            dispatch(admin=True, repo=self._repo, detach=self._detach)
        elif self._tweak_radio.isChecked():
            dispatch(tweak_prompt=self._tweak_edit.text(),
                     repo=self._repo, detach=self._detach)
        else:
            domain = self.selected_domain()
            if domain is None:
                return  # nothing actionable selected
            dispatch(domain=domain, repo=self._repo, detach=self._detach)
        self.accept()
