"""Pure load/validate/write helpers for the Tutorial panel's one data file
(``data/tutorial/tutorial.json`` — D3/TU-1, TU-4). Qt-free, pygame-free (in
``test_editor_viewport.TestPurity``'s import list, the same convention as
``editor/theme_ops.py``): ``panels/tutorial_panel.py`` is the only caller.
"""
from pathlib import Path

from engine import data_io

_TUTORIAL_FILE = ("tutorial", "tutorial.json")
_TUTORIAL_SCHEMA = "tutorial.schema.json"


def tutorial_path(data_dir):
    return Path(data_dir).joinpath(*_TUTORIAL_FILE)


def tutorial_schema_path(data_dir):
    return Path(data_dir) / "schemas" / _TUTORIAL_SCHEMA


def load_tutorial(data_dir):
    """``data/tutorial/tutorial.json``, schema-validated. Raises on a
    missing/invalid file — the editor's Tutorial panel opens on this only
    after the "Tutorial" leaf is selected, so a broken tree should be loud
    here (the same argument as ``theme_ops.load_fonts``)."""
    return data_io.load_validated(
        tutorial_path(data_dir), tutorial_schema_path(data_dir))


def write_tutorial(doc, data_dir):
    data_io.write_validated(
        doc, tutorial_path(data_dir), tutorial_schema_path(data_dir))
