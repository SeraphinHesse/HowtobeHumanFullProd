"""Editor chrome theme — light (the Qt default) or dark (Fusion + dark palette).

The ONE place the editor's Qt palette lives. Only chrome: the viewport keeps
rendering through engine/render (ED-22), so a theme switch never touches how
game content is drawn.

Light restores whatever style/palette the platform handed us at startup (captured
on the first apply); dark forces Fusion — the native Windows style ignores a dark
palette on several widgets and would half-apply.

The choice persists to `.editor_prefs.json` (gitignored, repo root — the same file
ED-1's eventual layout persistence uses, so read/modify/write keeps other keys).
The load/save/toggle half is Qt-free and unit-testable; only apply_theme needs Qt.
"""
import json

from PySide6.QtGui import QColor, QPalette

THEMES = ("light", "dark")
DEFAULT_THEME = "light"
PREFS_KEY = "theme"

# Fusion reads these roles for every widget; the QSS below only covers what a
# palette cannot express (tooltip contrast, splitter/toolbar seams).
_DARK = {
    "window": "#2b2b2b",
    "base": "#232323",
    "alt_base": "#2f2f2f",
    "text": "#e6e6e6",
    "dim_text": "#7a7a7a",
    "button": "#3a3a3a",
    "highlight": "#4a7ab5",
    "border": "#4a4a4a",
}

_DARK_QSS = f"""
QToolTip {{
    color: {_DARK['text']};
    background-color: {_DARK['alt_base']};
    border: 1px solid {_DARK['border']};
}}
QSplitter::handle {{ background: {_DARK['border']}; }}
QToolBar {{ border: none; }}
"""

_default_style = None
_default_palette = None


def normalize(name):
    """Any stored/user value → a theme in THEMES (unknown → DEFAULT_THEME)."""
    return name if name in THEMES else DEFAULT_THEME


def toggled(name):
    """The other theme."""
    return "light" if normalize(name) == "dark" else "dark"


def load_theme(prefs_path):
    """The persisted theme; DEFAULT_THEME when the file is missing/unreadable."""
    try:
        with open(prefs_path, encoding="utf-8") as handle:
            prefs = json.load(handle)
    except (OSError, ValueError):
        return DEFAULT_THEME
    if not isinstance(prefs, dict):
        return DEFAULT_THEME
    return normalize(prefs.get(PREFS_KEY))


def save_theme(prefs_path, name):
    """Persist the theme, preserving every other key already in the file."""
    try:
        with open(prefs_path, encoding="utf-8") as handle:
            prefs = json.load(handle)
    except (OSError, ValueError):
        prefs = {}
    if not isinstance(prefs, dict):
        prefs = {}
    prefs[PREFS_KEY] = normalize(name)
    with open(prefs_path, "w", encoding="utf-8") as handle:
        json.dump(prefs, handle, indent=2, sort_keys=True)
        handle.write("\n")


def dark_palette():
    palette = QPalette()
    window = QColor(_DARK["window"])
    base = QColor(_DARK["base"])
    text = QColor(_DARK["text"])
    button = QColor(_DARK["button"])
    dim = QColor(_DARK["dim_text"])

    palette.setColor(QPalette.ColorRole.Window, window)
    palette.setColor(QPalette.ColorRole.WindowText, text)
    palette.setColor(QPalette.ColorRole.Base, base)
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(_DARK["alt_base"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(_DARK["alt_base"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, text)
    palette.setColor(QPalette.ColorRole.Text, text)
    palette.setColor(QPalette.ColorRole.Button, button)
    palette.setColor(QPalette.ColorRole.ButtonText, text)
    palette.setColor(QPalette.ColorRole.BrightText, QColor("#ff5555"))
    palette.setColor(QPalette.ColorRole.Link, QColor(_DARK["highlight"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(_DARK["highlight"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, dim)

    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text,
                 QPalette.ColorRole.ButtonText, QPalette.ColorRole.HighlightedText):
        palette.setColor(QPalette.ColorGroup.Disabled, role, dim)
    return palette


def apply_theme(app, name):
    """Apply the theme to the whole application. Returns the applied theme."""
    global _default_style, _default_palette
    if _default_palette is None:
        _default_style = app.style().objectName()
        _default_palette = QPalette(app.palette())

    name = normalize(name)
    if name == "dark":
        app.setStyle("Fusion")          # before setPalette: setStyle re-seeds it
        app.setPalette(dark_palette())
        app.setStyleSheet(_DARK_QSS)
    else:
        app.setStyle(_default_style)
        app.setPalette(_default_palette)
        app.setStyleSheet("")
    return name
