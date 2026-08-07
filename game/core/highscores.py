"""Runtime persistence of finished-run high scores (player identity feature).

The SECOND runtime data write in the game after ``names.py`` — and unlike that
one it does NOT write into ``data/``: the document lives in the gitignored
``scores/`` directory at the repo root, because it is per-machine play history,
not designer content. It still goes through the validating writer
(``engine.data_io.write_validated`` against
``data/schemas/highscores.schema.json``), so the single write path holds and the
file stays schema-canonical (D-3) — the ``dispatch_handoff`` precedent.

Pure Python (no pygame); disk I/O lives HERE, out of the pygame-pure
``game/ui``.

**Reads never raise.** A missing, unreadable or schema-invalid scores file
returns a fresh empty document (one logged warning if a file was actually
there), because a corrupt play-history file must never stop the game booting.
Writes DO raise on invalid data (D-2) — a caller building an entry from live
run state cannot produce one, so nothing is coerced defensively.
"""
import logging
from datetime import datetime
from pathlib import Path

from engine import data_io

#: The experience levels the identity prompt offers, in prompt order.
SKILLS = ("never", "a_bit", "a_lot", "developer")
#: Stamped when identity was never asked, or the answer was not one of SKILLS.
UNKNOWN_SKILL = "unknown"

#: Name stamped for a blank/whitespace-only entry.
ANONYMOUS = "Anonymous"

_log = logging.getLogger(__name__)


def _schema_path(data_dir):
    return Path(data_dir) / "schemas" / "highscores.schema.json"


def _empty_doc():
    return {"version": 1,
            "last_player": {"name": "", "skill": UNKNOWN_SKILL},
            "entries": []}


def default_path(repo_root):
    """The canonical scores file: ``<repo_root>/scores/highscores.json``."""
    return Path(repo_root) / "scores" / "highscores.json"


def load_highscores(path, data_dir):
    """Load and validate the scores document at ``path``.

    Returns a fresh empty document when the file does not exist (silently — a
    first run is not an error) or when it exists but cannot be read/validated
    (ONE logged warning). Never raises.
    """
    path = Path(path)
    if not path.exists():
        return _empty_doc()
    try:
        return data_io.load_validated(path, _schema_path(data_dir))
    except Exception as exc:                                   # noqa: BLE001
        _log.warning("could not load high scores from %s (%s) — "
                     "starting from an empty record", path, exc)
        return _empty_doc()


def append_score(path, entry, data_dir):
    """Append ``entry``, refresh ``last_player``, and persist to ``path``.

    Returns the updated document. The parent directory is created if needed;
    the write goes through ``write_validated``, so a schema-invalid entry
    raises before anything touches disk (D-2).
    """
    path = Path(path)
    doc = load_highscores(path, data_dir)
    doc["entries"].append(entry)
    doc["last_player"] = {"name": entry["name"], "skill": entry["skill"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _schema_path(data_dir))
    return doc


def make_entry(name, skill, round_reached, buildings_placed, enemies_killed,
               run_id=None, debug=False):
    """Build one schema-shaped entry, stamped with the current local time.

    This is the ONE place the ``Anonymous`` / ``unknown`` defaults live: a
    blank or whitespace-only ``name`` becomes ``Anonymous`` and a ``skill``
    outside ``SKILLS`` becomes ``UNKNOWN_SKILL``.
    """
    name = (name or "").strip() or ANONYMOUS
    if skill not in SKILLS:
        skill = UNKNOWN_SKILL
    return {
        "name": name,
        "skill": skill,
        "round_reached": int(round_reached),
        "buildings_placed": int(buildings_placed),
        "enemies_killed": int(enemies_killed),
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "debug": bool(debug),
    }


def last_player(doc):
    """``(name, skill)`` of the last recorded run — the identity prompt's
    pre-fill. Tolerates a document with no ``last_player`` key at all."""
    last = (doc or {}).get("last_player") or {}
    return last.get("name", ""), last.get("skill", UNKNOWN_SKILL)


def ranked(doc):
    """Entries sorted by ``round_reached`` descending. Python's sort is stable,
    so ties keep insertion (play) order — the oldest run of a tied pair ranks
    first."""
    entries = list((doc or {}).get("entries") or [])
    entries.sort(key=lambda e: e.get("round_reached", 0), reverse=True)
    return entries
