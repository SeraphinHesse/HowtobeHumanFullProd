"""Pure load/write helpers for the Credits panel's data file
(``data/ui/credits.json``). Qt-free, pygame-free (in
``test_editor_viewport.TestPurity``'s import list) — ``panels/credits_panel.py``
is the only caller.

Its own module rather than a corner of ``strings_ops.py``: that file is scoped
to the flat ``{string_id: template}`` table, this one to an ORDERED row list
with insert/remove/move semantics a key map has no use for — the one-file-per-
concern split ``theme_ops``/``strings_ops`` already keep.

The row-list mutators below are the panel's whole edit vocabulary, kept here so
they are testable without Qt. They all take and return the plain
``{"rows": [...]}`` doc shape and mutate it in place."""
from pathlib import Path

from engine import data_io

_CREDITS_FILE = ("ui", "credits.json")
_CREDITS_SCHEMA = "credits.schema.json"


def credits_path(data_dir):
    return Path(data_dir).joinpath(*_CREDITS_FILE)


def credits_schema_path(data_dir):
    return Path(data_dir) / "schemas" / _CREDITS_SCHEMA


def load_credits(data_dir):
    """``data/ui/credits.json``, schema-validated. Raises on a missing/invalid
    file — the panel opens on this only after the "Credits" leaf is selected,
    so a broken tree should be visible, not silently emptied (the
    ``strings_ops.load_strings`` argument)."""
    return data_io.load_validated(credits_path(data_dir),
                                  credits_schema_path(data_dir))


def write_credits(doc, data_dir):
    data_io.write_validated(doc, credits_path(data_dir),
                            credits_schema_path(data_dir))


def is_spacer(row):
    """A row with NEITHER column filled renders as a blank gap, not a text
    line — the game's own rule (``game/ui/credits.py``), restated here so the
    panel can label the row instead of showing two empty boxes."""
    return not row["role"] and not row["name"]


def new_person(role="", name=""):
    return {"role": role, "name": name}


def new_spacer():
    return {"role": "", "name": ""}


def insert_row(doc, index, row):
    doc["rows"].insert(max(0, min(index, len(doc["rows"]))), row)


def remove_row(doc, index):
    del doc["rows"][index]


def move_row(doc, index, delta):
    """Move one row by ``delta`` positions, clamped — a no-op at either end
    (the panel disables the button there too, but clamping here means a
    caller can't reorder its way out of the list)."""
    rows = doc["rows"]
    target = index + delta
    if not (0 <= index < len(rows)) or not (0 <= target < len(rows)):
        return index
    rows.insert(target, rows.pop(index))
    return target
