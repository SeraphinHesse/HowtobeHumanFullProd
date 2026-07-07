"""MapSession — the editor's open-map state (ED-20/ED-24, D-21/D-22).

ONE session per MainWindow: the TileMapDoc being edited (one map open at
a time), THE global QUndoStack every undoable editor action goes through
(ED-24 — Phase 6 scope: tilemap strokes, base moves, deco place/remove,
display-name edits; balancing/import undo is deferred until those panels
are next touched), dirty tracking via the stack's clean state, and the
disk lifecycle: open / create / duplicate / save / set-active. All disk
writes go through engine.data_io's validating writer; set_active is the
ONLY writer of data/maps/active_map.json (D-21).

Stroke commands re-apply set-to-value change lists, so pushing after the
viewport already painted the cells live is idempotent (QUndoStack calls
redo() on push).
"""
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from editor import tilemap_ops
from engine import data_io, tilemap

REPO = Path(__file__).resolve().parents[1]


class _StrokeCommand(QUndoCommand):
    def __init__(self, doc, changes, text):
        super().__init__(text)
        self._doc, self._changes = doc, changes

    def redo(self):
        tilemap_ops.apply_changes(self._doc, self._changes)

    def undo(self):
        tilemap_ops.apply_changes(self._doc, self._changes, reverse=True)


class _BaseSetCommand(QUndoCommand):
    """Place / move / remove the single base (hole). ``old`` and ``new`` are
    full base dicts (``{'col','row','slot'}``) or ``None`` (no hole)."""

    def __init__(self, doc, old, new, text):
        super().__init__(text)
        self._doc = doc
        self._old = dict(old) if old is not None else None
        self._new = dict(new) if new is not None else None

    def redo(self):
        self._doc.base = dict(self._new) if self._new is not None else None

    def undo(self):
        self._doc.base = dict(self._old) if self._old is not None else None


class _AddBackgroundCommand(QUndoCommand):
    """Add a new BACKGROUND legend entry (code -> slot) to the open map — the
    palette's '+ Level' button. Undo drops the code again (paint commands that
    used it sit ABOVE this on the stack, so they undo first)."""

    def __init__(self, doc, code, slot):
        super().__init__(f"add background {slot}")
        self._doc, self._code = doc, code
        self._entry = {"checker": False, "slot": slot}

    def redo(self):
        self._doc.legend[self._code] = dict(self._entry)

    def undo(self):
        self._doc.legend.pop(self._code, None)


class _DecoPlaceCommand(QUndoCommand):
    def __init__(self, doc, col, row, slot):
        super().__init__(f"place {slot}")
        self._doc, self._cell, self._slot = doc, (col, row), slot
        self._entry = None

    def redo(self):
        self._entry = tilemap_ops.place_deco(
            self._doc, self._cell[0], self._cell[1], self._slot)

    def undo(self):
        for i in range(len(self._doc.deco) - 1, -1, -1):
            if self._doc.deco[i] is self._entry:
                self._doc.deco.pop(i)
                return


class _DecoRemoveCommand(QUndoCommand):
    def __init__(self, doc, index):
        super().__init__(f"remove {doc.deco[index]['slot']}")
        self._doc, self._index, self._entry = doc, index, doc.deco[index]

    def redo(self):
        self._doc.deco.pop(self._index)

    def undo(self):
        self._doc.deco.insert(self._index, self._entry)


class _RenameCommand(QUndoCommand):
    def __init__(self, doc, old, new):
        super().__init__("rename map")
        self._doc, self._old, self._new = doc, old, new

    def redo(self):
        self._doc.display_name = self._new

    def undo(self):
        self._doc.display_name = self._old


class MapSession(QObject):
    map_opened = Signal(str)     # map_id — a (different) doc is now open
    active_changed = Signal(str)  # map_id now pointed at by active_map.json

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.doc = None
        self.undo_stack = QUndoStack(self)

    # -- lifecycle (D-22) ----------------------------------------------------

    @property
    def dirty(self):
        return self.doc is not None and not self.undo_stack.isClean()

    def open(self, map_id):
        self.doc = tilemap.load_map(
            tilemap.map_path(self._data_dir, map_id),
            tilemap.map_schema_path(self._data_dir))
        self.undo_stack.clear()
        self.map_opened.emit(map_id)
        return self.doc

    def create(self, map_id, display_name, cols, rows):
        """New all-background map, written to disk immediately so the Maps
        tree (and the game) can see it, then opened."""
        if tilemap.map_path(self._data_dir, map_id).exists():
            raise ValueError(f"map {map_id!r} already exists")
        doc = tilemap.new_doc(map_id, display_name, cols, rows,
                              tilemap.map_schema_path(self._data_dir))
        tilemap.save_map(doc, tilemap.map_path(self._data_dir, map_id),
                         tilemap.map_schema_path(self._data_dir))
        return self.open(map_id)

    def duplicate(self, map_id, display_name):
        if self.doc is None:
            raise ValueError("no map open to duplicate")
        if tilemap.map_path(self._data_dir, map_id).exists():
            raise ValueError(f"map {map_id!r} already exists")
        dup = tilemap.duplicate_doc(self.doc, map_id, display_name)
        tilemap.save_map(dup, tilemap.map_path(self._data_dir, map_id),
                         tilemap.map_schema_path(self._data_dir))
        return self.open(map_id)

    def save(self):
        tilemap.save_map(self.doc,
                         tilemap.map_path(self._data_dir, self.doc.map_id),
                         tilemap.map_schema_path(self._data_dir))
        self.undo_stack.setClean()

    def set_active(self):
        """The ONLY writer of active_map.json (D-21)."""
        data_io.write_validated(
            {"active": self.doc.map_id},
            tilemap.active_map_path(self._data_dir),
            tilemap.active_map_schema_path(self._data_dir))
        self.active_changed.emit(self.doc.map_id)

    def active_map_id(self):
        path = tilemap.active_map_path(self._data_dir)
        if not path.exists():
            return None
        return data_io.load_validated(
            path, tilemap.active_map_schema_path(self._data_dir))["active"]

    def map_ids(self):
        return tilemap.list_map_ids(self._data_dir)

    # -- undoable edits (ED-24) — the viewport/details push through these ----

    def push_stroke(self, changes, text="paint"):
        if changes:
            self.undo_stack.push(_StrokeCommand(self.doc, changes, text))

    def _base_slot(self):
        schema = data_io.load_json(tilemap.map_schema_path(self._data_dir))
        return tilemap.defaults_from_schema(schema)[1]

    def push_base_place(self, col, row):
        """Place the hole (if the map has none) or move the single hole to a new
        cell — ONE undoable command either way (the base is placed like a tile
        but there can only be one)."""
        old = self.doc.base
        slot = old["slot"] if old is not None else self._base_slot()
        new = {"col": col, "row": row, "slot": slot}
        if old == new:
            return
        text = "move hole" if old is not None else "place hole"
        self.undo_stack.push(_BaseSetCommand(self.doc, old, new, text))

    def push_base_remove(self):
        if self.doc.base is not None:
            self.undo_stack.push(
                _BaseSetCommand(self.doc, self.doc.base, None, "remove hole"))

    def push_base_move(self, old, new):
        """Drag path (kept for the base-drag gesture): ``old`` is the pre-move
        (col,row) or None; ``new`` is the target (col,row). Routes through the
        same set command as click-placement."""
        if old is not None and new is not None:
            self.push_base_place(new[0], new[1])

    def push_add_background(self, slot):
        """'+ Level': claim the next free legend code for a new background type
        and add it to the open map's legend. Returns the code."""
        code = tilemap_ops.next_free_code(self.doc.legend)
        self.undo_stack.push(_AddBackgroundCommand(self.doc, code, slot))
        return code

    def push_deco_place(self, col, row, slot):
        self.undo_stack.push(_DecoPlaceCommand(self.doc, col, row, slot))

    def push_deco_remove(self, col, row):
        index = tilemap_ops.top_deco_index(self.doc, col, row)
        if index is not None:
            self.undo_stack.push(_DecoRemoveCommand(self.doc, index))

    def push_rename(self, new_name):
        if new_name and new_name != self.doc.display_name:
            self.undo_stack.push(
                _RenameCommand(self.doc, self.doc.display_name, new_name))
