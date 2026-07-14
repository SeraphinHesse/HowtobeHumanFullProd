"""Plan management (AD-7): read the active-plan mirror, list the `planning/`
sources, and build the prompts the editor spawns to CHANGE them.

PURE: no Qt, no pygame (`TestPurity`), and no `editor.run_controls` import — the
launch primitive stays in `spawnclaude`/`run_controls`, so this module is stdlib
only.

**The editor NEVER writes root `PLAN.md` or anything under `planning/`.** It
*reads* PLAN.md's line-1 `<!-- active-plan: … -->` marker and *spawns*
`/setcurrentplan` or `/createplan` to do the writing — the same delegation model
the editor already uses for locks (`locks.py` reads, `/start-domain` writes).
The marker is the SINGLE source of truth: no second pointer file, and a hand-edit
that strips it yields `None` (never an exception).

Plan names carry the `.md` extension end to end (`list_plans`, `active_plan`,
`set_current_plan_prompt`) — that is what the marker stores and what
`.claude/commands/setcurrentplan.md`'s `argument-hint` asks for, so label, picker
and marker compare with zero massaging.
"""
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# Line-1 marker: `<!-- active-plan: MIGRATION_PLAN.md | set: 2026-07-13 -->`.
# The name is non-greedy and MUST be terminated by the `|` tail or the comment
# close, so a hand-edit that drops the tail (`<!-- active-plan: X.md-->`) still
# yields `X.md` and an empty marker (`<!-- active-plan: -->`) degrades to None —
# never to a garbage name like `--`. Tolerating hand-edits is the whole point.
_MARKER = re.compile(r"<!--\s*active-plan:\s*(?P<name>[^|\s>]+?)\s*(?:\||-->)")


def planning_dir(repo=None):
    """`<repo>/planning` — where the plan sources of truth live."""
    return (Path(repo) if repo is not None else REPO) / "planning"


def plan_mirror_path(repo=None):
    """`<repo>/PLAN.md` — the GENERATED mirror of the active plan."""
    return (Path(repo) if repo is not None else REPO) / "PLAN.md"


def list_plans(repo=None):
    """Sorted file NAMES of `planning/*.md` (with the extension).

    Deliberately literal — every `.md` in `planning/`, no filename convention
    filter (schemas over convention). Missing `planning/` → `[]`."""
    directory = planning_dir(repo)
    if not directory.is_dir():
        return []
    return sorted(path.name for path in directory.glob("*.md"))


def active_plan(repo=None):
    """The active plan's name from root `PLAN.md`'s LINE 1 marker, else `None`.

    Missing file, empty file, markerless first line, unreadable file → `None`.
    NEVER raises: a stripped marker must show as "— none set" in the launcher,
    not crash the editor. Only line 1 is parsed (`setcurrentplan.md` step 4
    pins the marker there)."""
    try:
        with open(plan_mirror_path(repo), encoding="utf-8", errors="replace") as handle:
            first_line = handle.readline()
    except OSError:
        return None
    match = _MARKER.search(first_line)
    return match.group("name") if match else None


def reveal_command(path):
    """argv that opens `path` in the OS file manager.

    Windows `explorer`, macOS `open`, else `xdg-open`. Reads `sys.platform` at
    CALL time (tests patch it). Returns ONE argv list; the caller splits it into
    `program, arguments` for `run_controls.start_detached`."""
    path = str(path)
    if sys.platform == "win32":
        return ["explorer", path]
    if sys.platform == "darwin":
        return ["open", path]
    return ["xdg-open", path]


def set_current_plan_prompt(name):
    """Claude's opening input to re-mirror a plan: `/setcurrentplan <name>.md`
    (the skill accepts the full filename — the form the marker/picker use)."""
    return f"/setcurrentplan {(name or '').strip()}".strip()


def create_plan_prompt(text):
    """Claude's opening input for the planning agent: the literal `/createplan`
    slash command with the plan brief appended (blank → bare `/createplan`)."""
    text = (text or "").strip()
    return f"/createplan {text}" if text else "/createplan"
