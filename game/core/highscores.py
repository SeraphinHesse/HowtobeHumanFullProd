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

**"Unreadable" is NOT the same as "absent", and a WRITE must tell them apart.**
``load_highscores`` collapses both to an empty document on purpose (a reader
only wants rows to draw), but ``append_score`` used to load through it and then
write the result back — so one unreadable byte turned the whole play history
into a one-entry file, silently and irreversibly. Every write path therefore
goes through ``read_highscores``, which returns ``(doc, ok)``, and **never
overwrites a file it could not read**: the bad bytes are moved aside to
``highscores.corrupt[.N].json`` first (``append_score``, so a finished run
still records its row), or the write is refused outright (``rename_entry``,
which has nothing meaningful to rewrite anyway).
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


def read_highscores(path, data_dir):
    """``(doc, ok)`` — the scores document, and whether the FILE was usable.

    ``ok`` is ``True`` for a good file AND for an absent one (a first run is
    not an error, and there is nothing to lose); it is ``False`` only when a
    file is there but could not be read or validated, which is the one case a
    writer must never paper over. ``doc`` is a fresh empty document in both
    failure shapes, so a pure reader can ignore ``ok`` entirely. Never raises.
    """
    path = Path(path)
    if not path.exists():
        return _empty_doc(), True
    try:
        return data_io.load_validated(path, _schema_path(data_dir)), True
    except Exception as exc:                                   # noqa: BLE001
        _log.warning("could not load high scores from %s (%s) — "
                     "starting from an empty record", path, exc)
        return _empty_doc(), False


def load_highscores(path, data_dir):
    """Load and validate the scores document at ``path``.

    Returns a fresh empty document when the file does not exist (silently — a
    first run is not an error) or when it exists but cannot be read/validated
    (ONE logged warning). Never raises. **Readers only** — a writer needs
    ``read_highscores``, which says which of those two happened.
    """
    return read_highscores(path, data_dir)[0]


def quarantine_path(path):
    """The first free ``<stem>.corrupt[.N]<suffix>`` beside ``path``.

    Deterministic (no timestamp) so a test can name the file it expects, and
    numbered so a second corruption cannot clobber the first rescue.
    """
    path = Path(path)
    candidate = path.with_name(f"{path.stem}.corrupt{path.suffix}")
    n = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.corrupt.{n}{path.suffix}")
        n += 1
    return candidate


def _move_aside(path):
    """Rename an unreadable scores file out of the way; return the new path.

    Raises if the move fails — deliberately: the caller must then abandon its
    write rather than overwrite bytes it could neither read nor preserve.
    """
    dest = quarantine_path(path)
    path.replace(dest)
    _log.warning("high-score file %s could not be read — kept as %s rather "
                 "than overwritten", path, dest)
    return dest


def append_score(path, entry, data_dir):
    """Append ``entry``, refresh ``last_player``, and persist to ``path``.

    Returns the updated document. The parent directory is created if needed;
    the write goes through ``write_validated``, so a schema-invalid entry
    raises before anything touches disk (D-2).

    **An unreadable existing file is moved aside, never overwritten** (see the
    module docstring): the run still gets its row in a fresh document, and the
    old bytes survive as ``highscores.corrupt[.N].json`` for recovery. If even
    that move fails, the exception propagates and nothing is written — losing
    one row beats losing the history.
    """
    path = Path(path)
    doc, ok = read_highscores(path, data_dir)
    if not ok:
        _move_aside(path)
    doc["entries"].append(entry)
    doc["last_player"] = {"name": entry["name"], "skill": entry["skill"]}
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _schema_path(data_dir))
    return doc


def rename_entry(path, index, name, data_dir):
    """Rename ``entries[index]`` to ``name`` and persist. Returns the new doc.

    ``index`` is the entry's position ON DISK (play order), not its rank on the
    high-score table — the table sorts a copy, so a caller holding a display
    row must map it back through ``ranked_rows``. ``name`` is normalised the
    way ``make_entry`` normalises it: blank or whitespace-only becomes
    ``ANONYMOUS``.

    ``last_player`` is refreshed too when the renamed entry is the most recent
    one, so the identity prompt cannot go on pre-filling a name that no longer
    exists anywhere in the file.

    Unlike the read helpers this one RAISES: ``IndexError`` for an index with
    no entry behind it, and ``OSError`` when the file exists but could not be
    read — rewriting a document we failed to parse would destroy exactly the
    history the rename was meant to touch.
    """
    path = Path(path)
    doc, ok = read_highscores(path, data_dir)
    if not ok:
        raise OSError(f"refusing to rename inside an unreadable scores file: "
                      f"{path}")
    entries = doc["entries"]
    if not -len(entries) <= index < len(entries):
        raise IndexError(f"no high-score entry at index {index} "
                         f"({len(entries)} recorded)")
    entries[index]["name"] = (name or "").strip() or ANONYMOUS
    if index in (len(entries) - 1, -1):
        doc["last_player"]["name"] = entries[index]["name"]
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


def ranked_rows(doc):
    """``[(disk_index, entry), ...]`` sorted by ``round_reached`` descending.

    Python's sort is stable, so ties keep insertion (play) order — the oldest
    run of a tied pair ranks first. The index travels WITH the row because the
    table's order is not the file's, and ``rename_entry`` addresses the file:
    without it, renaming the third row on screen would rename the third run
    ever played.
    """
    rows = list(enumerate((doc or {}).get("entries") or []))
    rows.sort(key=lambda pair: pair[1].get("round_reached", 0), reverse=True)
    return rows


def ranked(doc):
    """Entries sorted by ``round_reached`` descending — ``ranked_rows`` without
    the disk indices, for callers that only draw."""
    return [entry for _index, entry in ranked_rows(doc)]
