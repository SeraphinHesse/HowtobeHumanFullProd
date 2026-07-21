"""Pure load/validate/write helpers for the Theme panel's two data files
(``data/ui/fonts.json``, ``data/ui/palette.json`` — UH-6, D5). Qt-free,
pygame-free (in ``test_editor_viewport.TestPurity``'s import list, the same
convention as ``editor/selection.py``): ``panels/game_theme.py`` is the only
caller, and ``screen_details.py`` uses ``font_keys`` to source its font
combos from data instead of a hardcoded tuple.
"""
from pathlib import Path

from engine import data_io

_FONTS_FILE = ("ui", "fonts.json")
_FONTS_SCHEMA = "fonts.schema.json"
_PALETTE_FILE = ("ui", "palette.json")
_PALETTE_SCHEMA = "palette.schema.json"

# Editor-side graceful degrade (E-37) fallback for font_keys() ONLY — the
# combo must show SOMETHING even with a missing/corrupt data/ui/fonts.json.
# Mirrors engine/render/fonts.py's _FONT_SPECS key set. The game's own boot
# load (game/main.py) fails loud instead, per D-2 (this is data, not art).
_FALLBACK_FONT_KEYS = ("sm", "md", "lg", "xl", "xxl", "hud_phase", "hud_lvl")


def fonts_path(data_dir):
    return Path(data_dir).joinpath(*_FONTS_FILE)


def fonts_schema_path(data_dir):
    return Path(data_dir) / "schemas" / _FONTS_SCHEMA


def palette_path(data_dir):
    return Path(data_dir).joinpath(*_PALETTE_FILE)


def palette_schema_path(data_dir):
    return Path(data_dir) / "schemas" / _PALETTE_SCHEMA


def load_fonts(data_dir):
    """``data/ui/fonts.json``, schema-validated. Raises on a missing/invalid
    file — the editor's Theme panel opens on this only after a slot is
    selected, so a broken tree should be visible, not silently emptied."""
    return data_io.load_validated(fonts_path(data_dir), fonts_schema_path(data_dir))


def write_fonts(doc, data_dir):
    data_io.write_validated(doc, fonts_path(data_dir), fonts_schema_path(data_dir))


def load_palette(data_dir):
    """``data/ui/palette.json``, schema-validated. Raises on a missing/
    invalid file (same argument as ``load_fonts``)."""
    return data_io.load_validated(palette_path(data_dir), palette_schema_path(data_dir))


def write_palette(doc, data_dir):
    data_io.write_validated(doc, palette_path(data_dir), palette_schema_path(data_dir))


def font_keys(data_dir):
    """The font combo's key list, read fresh from ``data/ui/fonts.json`` —
    replaces ``screen_details.py``'s old hardcoded ``_FONT_KEYS`` tuple
    (UH-6 §2.6). Degrades to the literal fallback if the file is missing/
    unreadable (editor-side E-37 grace; MainWindow/ScreenDetailsPanel must
    still open on a broken data/ tree)."""
    try:
        return tuple(load_fonts(data_dir).keys())
    except Exception:
        return _FALLBACK_FONT_KEYS
