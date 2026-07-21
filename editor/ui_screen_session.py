"""UIScreenSession — the editor's open-UI-screen state (B4, ED-24, R3).

Structural mirror of ``editor/map_session.py``'s ``MapSession``: ONE session
per MainWindow holding the open screen's OVERRIDE doc (a plain dict — one of
``data/ui/screens/<screen_id>.json``), THE ``QUndoStack`` every screen-mode
edit goes through, and the disk lifecycle (open / save). Every push_* method
is a thin ``QUndoCommand`` wrapper storing FULL old AND new values (never a
delta — the ``map_session._BaseSetCommand`` pattern): undo replaces the whole
value, redo re-applies it, so pushing a command after the viewport already
mutated the doc live (a drag in progress) is idempotent, exactly like
``map_session``'s stroke commands.

``old``/``new`` of ``None`` means "no override" (the key is ABSENT from the
doc — schemas here never use JSON ``null``), not a literal null value.
Clearing a field therefore prunes now-empty parent containers
(``widgets/<id>`` then ``widgets`` itself) so a fully-reset widget disappears
from the doc rather than lingering as ``{}``.

Qt-only, no game imports (TestPurity).
"""
import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from engine import data_io

REPO = Path(__file__).resolve().parents[1]

# Pinned display order for building_panel's views (UH-2, §2). D-3 sorted-keys
# JSON alphabetizes the `views` object (`base_info` first) but the UI must
# present game-mode order. Selector and MainWindow both import this — one
# authority.
VIEW_ORDER = ("unlock", "construct", "upgrade", "base_info", "preview")


def ordered_views(view_ids):
    """Sort an iterable of view ids: known VIEW_ORDER names first (in that
    order), then any unknown names sorted after."""
    known = [v for v in VIEW_ORDER if v in view_ids]
    unknown = sorted(v for v in view_ids if v not in VIEW_ORDER)
    return tuple(known) + tuple(unknown)


def screen_path(data_dir, screen_id):
    return Path(data_dir) / "ui" / "screens" / f"{screen_id}.json"


def screen_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "ui_screen.schema.json"


def _remove_pruning(doc, path):
    """Remove doc[path[0]]...[path[-1]], then remove any parent dict along
    the way that becomes empty (never removes the doc root itself)."""
    key = path[0]
    if len(path) == 1:
        doc.pop(key, None)
        return
    child = doc.get(key)
    if not isinstance(child, dict):
        return
    _remove_pruning(child, path[1:])
    if not child:
        doc.pop(key, None)


def _set_at(doc, path, value):
    node = doc
    for key in path[:-1]:
        node = node.setdefault(key, {})
    node[path[-1]] = value


def _apply_field(doc, path, value):
    if value is None:
        _remove_pruning(doc, path)
    else:
        _set_at(doc, path, value)


class _DocFieldCommand(QUndoCommand):
    """Set/clear a value at a dotted path inside the open doc — the ONE
    command class behind every push_* method (mirrors map_session's
    _BaseSetCommand: full old/new storage, no delta)."""

    def __init__(self, doc, path, old, new, text):
        super().__init__(text)
        self._doc = doc
        self._path = tuple(path)
        self._old = copy.deepcopy(old)
        self._new = copy.deepcopy(new)

    def redo(self):
        _apply_field(self._doc, self._path, copy.deepcopy(self._new))

    def undo(self):
        _apply_field(self._doc, self._path, copy.deepcopy(self._old))


class UIScreenSession(QObject):
    screen_opened = Signal(str)   # screen_id — a (different) doc is now open
    view_changed = Signal(object)  # view_id (str) or None — active view changed

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.doc = None
        self.screen_id = None
        self.view = None
        self.undo_stack = QUndoStack(self)

    # -- lifecycle -------------------------------------------------------------

    @property
    def dirty(self):
        return self.doc is not None and not self.undo_stack.isClean()

    def open(self, screen_id):
        self.doc = data_io.load_validated(
            screen_path(self._data_dir, screen_id),
            screen_schema_path(self._data_dir))
        self.screen_id = screen_id
        self.view = None
        self.undo_stack.clear()
        self.screen_opened.emit(screen_id)
        return self.doc

    def set_view(self, view_id):
        """Set the active view (or None for the screen's single implicit
        view). Non-doc, non-undoable — this is display filtering, not an
        edit (UH-2, §2). The session does not validate view names against
        defaults (it holds only the override doc); validity is the caller's
        job."""
        self.view = view_id
        self.view_changed.emit(view_id)

    def save(self):
        data_io.write_validated(
            self.doc, screen_path(self._data_dir, self.screen_id),
            screen_schema_path(self._data_dir))
        self.undo_stack.setClean()

    def screen_ids(self):
        d = self._data_dir / "ui" / "screens"
        if not d.exists():
            return ()
        return tuple(sorted(p.stem for p in d.glob("*.json")))

    # -- undoable edits (ED-24) — viewport/screen_details push through these --

    def _push(self, path, old, new, text):
        if old == new:
            return
        self.undo_stack.push(_DocFieldCommand(self.doc, path, old, new, text))

    def push_move(self, widget_id, old_rect, new_rect):
        self._push(("widgets", widget_id, "rect"), old_rect, new_rect,
                   f"move {widget_id}")

    def push_resize(self, widget_id, old_rect, new_rect):
        self._push(("widgets", widget_id, "rect"), old_rect, new_rect,
                   f"resize {widget_id}")

    def push_field(self, widget_id, field_key, old_value, new_value):
        self._push(("widgets", widget_id, field_key), old_value, new_value,
                   f"edit {widget_id}.{field_key}")

    def push_skin_assign(self, widget_id, old_skin, new_skin):
        self._push(("widgets", widget_id, "skin"), old_skin, new_skin,
                   f"assign skin to {widget_id}")

    def push_background(self, background_spec):
        """Set the screen background ({slot: ...} / {color: ...} / None).
        Unlike the other push_* methods this takes only the NEW value — the
        old value is read from the open doc (mirrors MapSession.push_rename,
        which reads doc.display_name as `old` itself)."""
        old = self.doc.get("background")
        self._push(("background",), old, background_spec, "set background")

    def push_default_field(self, field_key, old_value, new_value):
        self._push(("defaults", field_key), old_value, new_value,
                   f"edit defaults.{field_key}")
