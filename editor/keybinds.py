"""Editor keybinds — tool shortcuts, brush shortcuts, and the undo/redo swap.

Persisted as one nested blob under the "keybinds" key of `.editor_prefs.json`,
the same file `editor/theme.py` uses for the chrome theme (read-modify-write,
preserving every other key already in the file). Each load backfills any
missing tool/brush entry from the defaults, so a partially-written or
hand-edited prefs file — or a newly added tool — never crashes.

Qt-free and unit-testable; only the settings dialog needs Qt.
"""
import json

TOOL_NAMES = ("none", "paint", "erase", "line", "rect", "bucket", "picker")
BRUSH_SLOTS = ("brush_1", "brush_2", "brush_3", "brush_4", "brush_5")

DEFAULT_TOOL_KEYBINDS = {
    "none": "P", "paint": "B", "erase": "N", "line": "L",
    "rect": "M", "bucket": "G", "picker": "I",
}
DEFAULT_BRUSH_KEYBINDS = {
    "brush_1": "1", "brush_2": "2", "brush_3": "3",
    "brush_4": "4", "brush_5": "5",
}
DEFAULT_UNDO_REDO_SWAPPED = False

PREFS_KEY = "keybinds"


def _read_prefs(prefs_path):
    try:
        with open(prefs_path, encoding="utf-8") as handle:
            prefs = json.load(handle)
    except (OSError, ValueError):
        return {}
    return prefs if isinstance(prefs, dict) else {}


def _write_prefs(prefs_path, prefs):
    with open(prefs_path, "w", encoding="utf-8") as handle:
        json.dump(prefs, handle, indent=2, sort_keys=True)
        handle.write("\n")


def load_keybinds(prefs_path):
    """The persisted keybinds, backfilled from defaults for any missing or
    invalid entry. Returns {"tools": {...}, "brushes": {...},
    "undo_redo_swapped": bool}."""
    stored = _read_prefs(prefs_path).get(PREFS_KEY, {})
    if not isinstance(stored, dict):
        stored = {}
    tools = stored.get("tools", {})
    if not isinstance(tools, dict):
        tools = {}
    brushes = stored.get("brushes", {})
    if not isinstance(brushes, dict):
        brushes = {}
    swapped = stored.get("undo_redo_swapped", DEFAULT_UNDO_REDO_SWAPPED)
    if not isinstance(swapped, bool):
        swapped = DEFAULT_UNDO_REDO_SWAPPED
    return {
        "tools": {name: tools.get(name, DEFAULT_TOOL_KEYBINDS[name])
                  for name in TOOL_NAMES},
        "brushes": {slot: brushes.get(slot, DEFAULT_BRUSH_KEYBINDS[slot])
                    for slot in BRUSH_SLOTS},
        "undo_redo_swapped": swapped,
    }


def save_keybinds(prefs_path, tools, brushes, undo_redo_swapped):
    """Persist the keybinds, preserving every other key already in the file
    (including "theme")."""
    prefs = _read_prefs(prefs_path)
    prefs[PREFS_KEY] = {
        "tools": dict(tools),
        "brushes": dict(brushes),
        "undo_redo_swapped": bool(undo_redo_swapped),
    }
    _write_prefs(prefs_path, prefs)
