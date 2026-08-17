"""Rebindable-hotkeys capability (feature: rebindable hotkeys).

Pure Python, no pygame — action names are opaque strings supplied by the
caller (D5: this module never learns "end_turn" is anything but a dict key).
Mirrors ``editor/keybinds.py``'s tolerant-load/backfill shape, generalized and
routed through ``engine.data_io``'s schema-validating load/write, matching how
every other persisted value in this repo works (unlike the editor's bare
``.editor_prefs.json``).

A binding is a plain lowercase string, optionally ``"ctrl+"``-prefixed —
``"space"``, ``"ctrl+l"``, ``"h"``, ``"1"``, ``"return"``. Translating a real
pygame ``KEYDOWN`` event into this string is the caller's job
(``game/main.py``'s ``_binding_key_name``) — this module never imports
pygame.
"""
import logging
from pathlib import Path

from . import data_io

_log = logging.getLogger(__name__)


def load_keybindings(path, schema_path, defaults):
    """The live bindings at ``path``, falling back to ``dict(defaults)`` when
    the file does not exist (silently — a first run is not an error) or when
    it exists but cannot be read/validated (one logged warning) — the
    ``game/core/highscores.py`` "reads never raise" contract for per-machine
    save data. The schema requires every action, so a validated file is
    always complete; there is no partial-record case to backfill."""
    path = Path(path)
    if not path.exists():
        return dict(defaults)
    try:
        return data_io.load_validated(path, schema_path)
    except Exception as exc:                                   # noqa: BLE001
        _log.warning("could not load keybindings from %s (%s) — "
                     "falling back to defaults", path, exc)
        return dict(defaults)


def save_keybindings(path, schema_path, bindings):
    """Persist ``bindings`` (schema-validated, D-2/D-3 canonical form). The
    parent directory is created if needed — the ``scores/`` folder may not
    exist yet on a first write."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data_io.write_validated(dict(bindings), path, schema_path)


def find_conflict(bindings, action, new_key):
    """The OTHER action already bound to ``new_key``, or ``None`` if free.
    Pure, no I/O."""
    for other_action, key in bindings.items():
        if other_action != action and key == new_key:
            return other_action
    return None


def rebind(bindings, action, new_key):
    """A new dict with ``action`` remapped to ``new_key``, everything else
    unchanged. Pure — does not check for a conflict; call ``find_conflict``
    first if that matters to the caller."""
    updated = dict(bindings)
    updated[action] = new_key
    return updated
