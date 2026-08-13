"""Master-sheet registry reader (MasterSheetColumnsPLAN C3). Pure Python.

Loads ``data/sprites/master_sheets.json`` (schema-validated, FAIL LOUD — the
registry is infrastructure like ``slots.json``/``geometry.json``; E-37's
log-and-placeholder tolerance is for art, not for this file). The sibling of
``registry.py``: no pygame, no Qt, no game vocabulary — sheet ids, refs and
column names are all data.

WHY IT LIVES IN ``engine/``. ``game/`` and ``editor/`` may not import each
other and both need to read this registry. That is the same argument
``engine/era_math.py`` carries for hosting the era clock; a copy per package is
exactly the drift this module exists to prevent. The editor's
``master_sheet_import.load_registry_doc`` delegates here and keeps its OWN E-37
degrade-to-empty-doc wrapper — the tolerant read is an editor policy, not this
module's.

RESOLUTION IS BY THE ENTRY'S STORED ``file``, never by re-deriving
``master/<id>.png`` from the entry key — that never-re-derive rule is
``editor/master_sheet_import.master_ref``'s explicit contract, and a
hand-edited registry can point elsewhere.
"""
from pathlib import Path

from engine import data_io

REGISTRY_SUBPATH = ("sprites", "master_sheets.json")
SCHEMA_SUBPATH = ("schemas", "master_sheets.schema.json")

#: A sheet ref belongs to a master sheet iff it starts with this. Columns are
#: MASTER-SHEET-ONLY (D2): a plain ``imported/<slot>.png`` has no column.
MASTER_PREFIX = "master/"


def registry_path(data_dir):
    """<data_dir>/sprites/master_sheets.json — no I/O."""
    return Path(data_dir).joinpath(*REGISTRY_SUBPATH)


def schema_path(data_dir):
    """<data_dir>/schemas/master_sheets.schema.json — no I/O."""
    return Path(data_dir).joinpath(*SCHEMA_SUBPATH)


def load_registry(data_dir):
    """Read the master-sheet registry validated against its schema (fail loud).

    Absent file -> OSError; schema-invalid -> jsonschema ValidationError. It
    does NOT degrade: `registry.load_registry`'s rule, for the same reason.
    """
    return data_io.load_validated(registry_path(data_dir), schema_path(data_dir))


def _entry_for(doc, sheet_ref):
    """The entry whose stored ``file`` IS `sheet_ref`, or None.

    Total: a non-dict doc, a non-dict ``entries``, a non-str/non-master ref and
    a non-dict entry all fall out as "unresolved".
    """
    if not isinstance(sheet_ref, str) or not sheet_ref.startswith(MASTER_PREFIX):
        return None
    if not isinstance(doc, dict):
        return None
    entries = doc.get("entries")
    if not isinstance(entries, dict):
        return None
    for entry in entries.values():
        if isinstance(entry, dict) and entry.get("file") == sheet_ref:
            return entry
    return None


def columns_for(doc, sheet_ref):
    """The sheet's per-column NAMES in STORED order (D4 — a sheet may author
    its columns in any order), or ``()`` when unresolvable or unnamed."""
    entry = _entry_for(doc, sheet_ref)
    columns = entry.get("columns") if entry is not None else None
    if not isinstance(columns, (list, tuple)):
        return ()
    return tuple(columns)


def column_width_for(doc, sheet_ref):
    """How many frame-columns one master column spans (D1), or ``0`` when
    unresolvable.

    No coercion: a bool, a float or a numeric string reads as 0, the same
    defensive shape `row_start` parsing uses. `0` is the "this ref has no
    column concept" answer, never a legal stored width (the schema floors it
    at 1).
    """
    entry = _entry_for(doc, sheet_ref)
    width = entry.get("column_width") if entry is not None else None
    if isinstance(width, bool) or not isinstance(width, int):
        return 0
    return width
