"""Save-slot storage primitives (SaveGamePLAN SG-1).

The slot/index file mechanics only — no ``RunState``/``Session``/``TileMap``/
``Building`` serialization lives here (that is SG-2/SG-3/SG-4; this module
treats a slot's body as an opaque dict it validates and writes verbatim).

Mirrors ``game/core/highscores.py``'s shape exactly: two more gitignored
per-machine documents under ``scores/`` (``scores/saves/<slot_id>.json`` per
slot, ``scores/saves/index.json`` for the lightweight per-slot summary the
Save Files screen lists from), both going through
``engine.data_io.write_validated``/``load_validated`` against
``data/schemas/savegame.schema.json``/``saves_index.schema.json`` — a fourth
"no ``data/`` content file" schema pair (``data/CLAUDE.md``).

**Reads never raise.** A missing, unreadable or schema-invalid index or slot
file returns a documented fallback (an empty index; ``None`` for a slot),
because a corrupt save must never stop the game booting. Writes DO raise on
invalid data (D-2).

Pure Python (no pygame); disk I/O lives HERE, out of the pygame-pure
``game/ui``.
"""
import logging
import uuid
from datetime import datetime
from pathlib import Path

from engine import data_io

#: FIFO cap enforced by evict_for_new_slot's default — the "10 save slots" rule.
MAX_SLOTS = 10

_log = logging.getLogger(__name__)


def _savegame_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "savegame.schema.json"


def _index_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "saves_index.schema.json"


def _empty_index():
    return {"version": 1, "slots": []}


def default_dir(repo_root):
    """The canonical save-slot directory: ``<repo_root>/scores/saves``."""
    return Path(repo_root) / "scores" / "saves"


def index_path(repo_root):
    return default_dir(repo_root) / "index.json"


def slot_path(repo_root, slot_id):
    return default_dir(repo_root) / f"{slot_id}.json"


def new_slot_id():
    """A fresh, unique slot id (opaque — never parsed for meaning)."""
    return uuid.uuid4().hex


def load_index(path, data_dir):
    """Load and validate the save-slot index at ``path``.

    Returns a fresh empty index when the file does not exist (silently — a
    first run is not an error) or when it exists but cannot be read/validated
    (ONE logged warning). Never raises.
    """
    path = Path(path)
    if not path.exists():
        return _empty_index()
    try:
        return data_io.load_validated(path, _index_schema_path(data_dir))
    except Exception as exc:                                    # noqa: BLE001
        _log.warning("could not load save index from %s (%s) — "
                     "starting from an empty index", path, exc)
        return _empty_index()


def write_index(path, doc, data_dir):
    """Persist the save-slot index. Raises on schema-invalid data (D-2)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _index_schema_path(data_dir))


def load_slot(path, data_dir):
    """Load and validate one save-slot body at ``path``.

    Returns ``None`` when the file does not exist, or when it exists but
    cannot be read/validated (ONE logged warning) — a corrupt/missing slot is
    a "this save is unavailable" condition for the caller, never a crash.
    """
    path = Path(path)
    if not path.exists():
        return None
    try:
        return data_io.load_validated(path, _savegame_schema_path(data_dir))
    except Exception as exc:                                    # noqa: BLE001
        _log.warning("could not load save slot from %s (%s) — "
                     "treating it as unavailable", path, exc)
        return None


def write_slot(path, doc, data_dir):
    """Persist one save-slot body. Raises on schema-invalid data (D-2)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(doc, path, _savegame_schema_path(data_dir))


def delete_slot(repo_root, slot_id):
    """Remove one slot's on-disk body. A missing file is not an error."""
    path = slot_path(repo_root, slot_id)
    path.unlink(missing_ok=True)


def make_summary(slot_doc):
    """The index row for a full slot document — the exact subset of fields
    ``saves_index.schema.json`` needs, so the Save Files screen never has to
    load a slot's full body just to list it."""
    return {
        "slot_id": slot_doc["slot_id"],
        "pinned": slot_doc["pinned"],
        "created_at": slot_doc["created_at"],
        "updated_at": slot_doc["updated_at"],
        "map_id": slot_doc["map_id"],
        "round_num": slot_doc["round_num"],
        "thumbnail_cols": slot_doc["tile_map"].get("cols", 1) if isinstance(
            slot_doc["tile_map"], dict) else 1,
        "thumbnail_rows": slot_doc["tile_map"].get("rows", 1) if isinstance(
            slot_doc["tile_map"], dict) else 1,
        "unlocked_tiles": [list(t) for t in slot_doc["unlocked_tiles"]],
    }


def make_slot_doc(*, slot_id, map_id, round_num, unlocked_tiles, run_state,
                   session, tile_map, buildings, pinned=False, now=None):
    """Build a schema-shaped slot document, stamped with the current local
    time — the ``highscores.make_entry`` precedent. ``tile_map`` should carry
    ``cols``/``rows`` keys so ``make_summary`` can size the minimap; SG-4
    defines that shape precisely, this function does not enforce it (SG-1
    scope: the envelope only)."""
    timestamp = (now or datetime.now()).isoformat(timespec="seconds")
    return {
        "version": 1,
        "slot_id": slot_id,
        "created_at": timestamp,
        "updated_at": timestamp,
        "pinned": bool(pinned),
        "map_id": map_id,
        "round_num": int(round_num),
        "unlocked_tiles": [list(t) for t in unlocked_tiles],
        "run_state": run_state,
        "session": session,
        "tile_map": tile_map,
        "buildings": list(buildings),
    }


def evict_for_new_slot(index_doc, keep=MAX_SLOTS):
    """The slot id to evict before adding a new one, or ``None``.

    Pure — takes/returns no disk state. ``None`` means either there is room
    (fewer than ``keep`` slots) or every slot is pinned (D3's "skip, never
    delete a pinned slot" rule) — the caller must tell the two apart only if
    it needs to (``len(index_doc["slots"]) < keep`` is the room check).
    """
    slots = index_doc["slots"]
    if len(slots) < keep:
        return None
    for slot in slots:                          # creation order: oldest first
        if not slot["pinned"]:
            return slot["slot_id"]
    return None                                  # every slot pinned


def add_slot(repo_root, slot_doc, data_dir, keep=MAX_SLOTS):
    """Write ``slot_doc`` as a new slot, evicting the oldest unpinned slot
    first if the index is already at ``keep``. Returns ``(index_doc,
    evicted_slot_id)`` — ``evicted_slot_id`` is ``None`` when nothing was
    evicted (room available, or every slot pinned and the save was skipped —
    see below).

    When every existing slot is pinned and the index is already full, the
    new save is SKIPPED (D3: never silently delete a pinned slot) — one
    logged warning, the index and disk are left exactly as they were, and
    this returns ``(index_doc, None)`` with the index UNCHANGED (the new
    slot's body is not written either, so no orphan file is left behind).
    """
    index_doc = load_index(index_path(repo_root), data_dir)
    evicted = None
    if len(index_doc["slots"]) >= keep:
        evicted = evict_for_new_slot(index_doc, keep=keep)
        if evicted is None:
            _log.warning("all %d save slots are pinned — skipping autosave "
                         "for slot %s", keep, slot_doc["slot_id"])
            return index_doc, None
        delete_slot(repo_root, evicted)
        index_doc["slots"] = [s for s in index_doc["slots"]
                               if s["slot_id"] != evicted]

    write_slot(slot_path(repo_root, slot_doc["slot_id"]), slot_doc, data_dir)
    index_doc["slots"].append(make_summary(slot_doc))
    write_index(index_path(repo_root), index_doc, data_dir)
    return index_doc, evicted


def set_pinned(repo_root, slot_id, pinned, data_dir):
    """Toggle a slot's pinned flag in both the index and its own body.

    Returns the updated index doc. A ``slot_id`` absent from the index is a
    no-op (returns the index unchanged) — the Save Files screen only ever
    calls this against a row it is currently showing, so this should not
    happen in practice, but a stale UI click must not raise.
    """
    index_doc = load_index(index_path(repo_root), data_dir)
    found = False
    for slot in index_doc["slots"]:
        if slot["slot_id"] == slot_id:
            slot["pinned"] = bool(pinned)
            found = True
            break
    if not found:
        return index_doc
    write_index(index_path(repo_root), index_doc, data_dir)

    body = load_slot(slot_path(repo_root, slot_id), data_dir)
    if body is not None:
        body["pinned"] = bool(pinned)
        write_slot(slot_path(repo_root, slot_id), body, data_dir)
    return index_doc


def remove_slot(repo_root, slot_id, data_dir):
    """Manually delete one slot (the Save Files screen's delete button).

    Removes both the on-disk body and its index entry. A ``slot_id`` absent
    from the index is a no-op. Returns the updated index doc.
    """
    index_doc = load_index(index_path(repo_root), data_dir)
    remaining = [s for s in index_doc["slots"] if s["slot_id"] != slot_id]
    if len(remaining) == len(index_doc["slots"]):
        return index_doc                                  # not found, no-op
    delete_slot(repo_root, slot_id)
    index_doc["slots"] = remaining
    write_index(index_path(repo_root), index_doc, data_dir)
    return index_doc


def most_recent_slot(index_doc):
    """The slot id CONTINUE should load, or ``None`` if there are no saves."""
    slots = index_doc["slots"]
    return slots[-1]["slot_id"] if slots else None
