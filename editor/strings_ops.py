"""Pure load/write helpers for the Strings panel's data file
(``data/ui/strings.json`` — Phase C). Qt-free, pygame-free (in
``test_editor_viewport.TestPurity``'s import list, the same convention as
``editor/theme_ops.py``): ``panels/strings_panel.py`` is the only caller.

A separate module from ``theme_ops.py`` on purpose — that module is scoped to
fonts/palette/font_manifest/active_font (the font+color THEME), while
``strings.json`` is a different document with a different shape (a flat
``{string_id: template}`` map, no per-key schema `$defs`) — one file per
concern, the same split ``asset_import.py``/``font_import.py`` already keep."""
from pathlib import Path

from engine import data_io

_STRINGS_FILE = ("ui", "strings.json")
_STRINGS_SCHEMA = "strings.schema.json"


def strings_path(data_dir):
    return Path(data_dir).joinpath(*_STRINGS_FILE)


def strings_schema_path(data_dir):
    return Path(data_dir) / "schemas" / _STRINGS_SCHEMA


def load_strings(data_dir):
    """``data/ui/strings.json``, schema-validated. Raises on a missing/
    invalid file — the panel opens on this only after the "Strings" leaf is
    selected, so a broken tree should be visible, not silently emptied
    (same argument as ``theme_ops.load_fonts``)."""
    return data_io.load_validated(strings_path(data_dir), strings_schema_path(data_dir))


def write_strings(doc, data_dir):
    data_io.write_validated(doc, strings_path(data_dir), strings_schema_path(data_dir))


def placeholders(template):
    """The ``{name}`` placeholder names a template mentions, in order of
    first appearance, de-duplicated — a read-only hint for the panel so a
    designer editing a templated row can see what it still needs to fill,
    without validating correctness (str.format() raises at GAME render time
    on a bad edit, same as any other data typo; this is a hint, not a
    save-time gate)."""
    import string

    seen = []
    for _, field_name, _, _ in string.Formatter().parse(template):
        if field_name and field_name not in seen:
            seen.append(field_name)
    return seen
