"""Per-domain balancing version history (data/balancing_history/<domain>.json).

A flat, newest-first, unbounded JSON array of full-document snapshots,
mirroring the old prototype's balancing_sessions.json but split one file per
domain (this codebase locks/edits domains independently, unlike the
prototype's single combined editor window). Appended ONLY by the editor's
explicit Save Balancing Changes action (editor/panels/balancing.py) — never
on individual field edits.

Reads/writes go through engine.data_io (D-2) against the shared
balancing_history.schema.json (a SCHEMA-PAIRING EXCEPTION, same pattern as
map_file.schema.json: many content files, one schema, keyed by directory not
filename stem — see data/CLAUDE.md and tools/smoke.py).

save_session/delete_session are read-modify-write (load the full array,
mutate in Python, write the whole file back) — without a guard, two calls
racing (two editor processes/agents pointed at the same data/ dir, or even
two quick clicks) can interleave: the second call's load reads a copy that's
missing the first call's just-written entry, and its write then clobbers the
file, silently dropping history. _history_lock() serializes the
read-modify-write across processes via an exclusive-create lock FILE
(atomic on both POSIX and Windows/NTFS) next to the history file — a stale
lock older than STALE_LOCK_SECONDS (left behind by a crashed process) is
reclaimed rather than deadlocking future saves forever.

Pure Python, no Qt, no pygame.
"""
import contextlib
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from engine import data_io

REPO = Path(__file__).resolve().parents[1]

STALE_LOCK_SECONDS = 30
LOCK_TIMEOUT_SECONDS = 10
LOCK_POLL_SECONDS = 0.05


class HistoryLockTimeout(RuntimeError):
    """Another process held the history lock past LOCK_TIMEOUT_SECONDS."""


@contextlib.contextmanager
def _history_lock(path):
    """Serialize the read-modify-write on `path` across processes/threads."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                age = time.time() - lock_path.stat().st_mtime
            except FileNotFoundError:
                continue  # released between the open() failure and stat()
            if age > STALE_LOCK_SECONDS:
                lock_path.unlink(missing_ok=True)
                continue
            if time.monotonic() >= deadline:
                raise HistoryLockTimeout(
                    f"timed out waiting for balancing history lock {lock_path}"
                )
            time.sleep(LOCK_POLL_SECONDS)
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def history_path(domain, data_dir=None):
    base = Path(data_dir) if data_dir is not None else REPO / "data"
    return base / "balancing_history" / f"{domain}.json"


def history_schema_path(data_dir=None):
    base = Path(data_dir) if data_dir is not None else REPO / "data"
    return base / "schemas" / "balancing_history.schema.json"


def load_sessions(domain, data_dir=None):
    """Newest-first list of history entries; [] if none exist yet."""
    path = history_path(domain, data_dir)
    if not path.exists():
        return []
    return data_io.load_validated(path, history_schema_path(data_dir))


def save_session(domain, name, description, snapshot, data_dir=None):
    """Prepend a new snapshot entry and write the domain's history file.

    Returns the new entry.
    """
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "name": name,
        "description": description,
        "snapshot": snapshot,
    }
    path = history_path(domain, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _history_lock(path):
        sessions = [entry] + load_sessions(domain, data_dir)
        data_io.write_validated(sessions, path, history_schema_path(data_dir))
    return entry


def delete_session(domain, session_id, data_dir=None):
    path = history_path(domain, data_dir)
    with _history_lock(path):
        sessions = [s for s in load_sessions(domain, data_dir) if s["id"] != session_id]
        data_io.write_validated(sessions, path, history_schema_path(data_dir))
