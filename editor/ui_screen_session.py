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

**UT-1: the session holds a SECOND doc**, the global string table
``data/ui/strings.json``, so a designer can edit the TEMPLATE behind a
widget's ``text_id`` in the same panel (and the same undo stack) as its rect
and colour. It is deliberately not per-screen: one id, one text, everywhere.
``save()`` writes it only when it changed, and ``strings_dirty`` is a value
comparison rather than a latch so undoing the only template edit un-dirties it
again.

Qt-only, no game imports (TestPurity).
"""
import copy
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

from engine import data_io
from editor.widget_tree import PARENT_KEY

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


def strings_path(data_dir):
    return Path(data_dir) / "ui" / "strings.json"


def strings_schema_path(data_dir):
    return Path(data_dir) / "schemas" / "strings.schema.json"


class _NoParent:
    """Sentinel for an explicit JSON ``null`` override, as distinct from
    ``None``, which every push_* method already spends on "no override — the
    key is ABSENT".

    Exactly one key needs the distinction (UiEditorParentingPLAN D3): a
    widget's ``parent``. Absent means "keep the exporter's default parent";
    ``null`` means "the designer REJECTED it — this widget is a root". Undoing
    a re-root has to put the default back, so the two states cannot share a
    representation.

    ``__deepcopy__`` returns the singleton itself: ``_DocFieldCommand``
    deep-copies both old and new, and a copied sentinel would silently stop
    being recognised.
    """

    def __deepcopy__(self, _memo):
        return self

    def __copy__(self):
        return self

    def __repr__(self):
        return "NO_PARENT"


#: The one instance — compare with ``is``, never ``==``.
NO_PARENT = _NoParent()


def parent_override(widget_override):
    """The stored ``parent`` override in push_field's own vocabulary:
    ``None`` when the key is ABSENT, ``NO_PARENT`` when it is an explicit
    JSON null, else the parent id. The ONE place the three states are read,
    so the panel's combo, its reset button and the tree drop cannot disagree
    about what "old" was."""
    if PARENT_KEY not in (widget_override or {}):
        return None
    value = widget_override[PARENT_KEY]
    return NO_PARENT if value is None else value


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
    if value is NO_PARENT:
        _set_at(doc, path, None)   # a REAL JSON null (D3) — see _NoParent
    elif value is None:
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


class _DocFieldsCommand(QUndoCommand):
    """SEVERAL fields set/cleared as ONE undo step — the multi-widget twin of
    ``_DocFieldCommand``, modelled on ``map_session``'s stroke commands: a
    change LIST of full old/new values, never a delta, so pushing after the
    viewport already mutated the doc live (a drag in progress) is idempotent.

    Its one user is the parenting cascade (UiEditorParentingPLAN P-3): moving
    a parent rewrites the absolute rect of the parent AND every descendant,
    and one Ctrl+Z has to put all of them back.
    """

    def __init__(self, doc, changes, text):
        super().__init__(text)
        self._doc = doc
        self._changes = [(tuple(path), copy.deepcopy(old), copy.deepcopy(new))
                         for path, old, new in changes]

    def redo(self):
        for path, _old, new in self._changes:
            _apply_field(self._doc, path, copy.deepcopy(new))

    def undo(self):
        # Reverse order so the pruning of a shared parent container
        # (`widgets/<id>`) unwinds in the order it was built.
        for path, old, _new in reversed(self._changes):
            _apply_field(self._doc, path, copy.deepcopy(old))


class UIScreenSession(QObject):
    screen_opened = Signal(str)   # screen_id — a (different) doc is now open
    view_changed = Signal(object)  # view_id (str) or None — active view changed

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.doc = None
        self.screen_id = None
        self.view = None
        # UT-1: the GLOBAL string table (data/ui/strings.json), edited
        # alongside the screen doc — see push_string. `None` when the file is
        # missing or invalid, which disables template editing rather than
        # failing the whole screen-mode entry (E-37 grace, editor side).
        self.strings_doc = None
        self._strings_clean = None
        self.undo_stack = QUndoStack(self)

    # -- lifecycle -------------------------------------------------------------

    @property
    def dirty(self):
        if self.doc is None:
            return False
        return not self.undo_stack.isClean() or self.strings_dirty

    @property
    def strings_dirty(self):
        """True when the open string table differs from what is on disk.

        Compared by VALUE rather than tracked with a flag, because string
        edits share the screen doc's one `QUndoStack` — undoing the only
        template edit must un-dirty the table again, which a latch cannot do.
        """
        if self.strings_doc is None:
            return False
        return self.strings_doc != self._strings_clean

    def open(self, screen_id):
        self.doc = data_io.load_validated(
            screen_path(self._data_dir, screen_id),
            screen_schema_path(self._data_dir))
        self.screen_id = screen_id
        self.view = None
        self._load_strings()
        self.undo_stack.clear()
        self.screen_opened.emit(screen_id)
        return self.doc

    def _load_strings(self):
        try:
            doc = data_io.load_validated(strings_path(self._data_dir),
                                         strings_schema_path(self._data_dir))
        except Exception:
            doc = None
        self.strings_doc = doc
        self._strings_clean = copy.deepcopy(doc)

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
        if self.strings_dirty:
            data_io.write_validated(
                self.strings_doc, strings_path(self._data_dir),
                strings_schema_path(self._data_dir))
            self._strings_clean = copy.deepcopy(self.strings_doc)
        self.undo_stack.setClean()

    def screen_ids(self):
        d = self._data_dir / "ui" / "screens"
        if not d.exists():
            return ()
        return tuple(sorted(p.stem for p in d.glob("*.json")))

    # -- undoable edits (ED-24) — viewport/screen_details push through these --

    def _push(self, path, old, new, text):
        self._push_doc(self.doc, path, old, new, text)

    def _push_doc(self, doc, path, old, new, text):
        """`_push` against an explicit doc — the screen override doc for every
        widget/background/defaults edit, the global string table for
        `push_string`. Both share this session's one undo stack."""
        if old == new:
            return
        self.undo_stack.push(_DocFieldCommand(doc, path, old, new, text))

    def push_move(self, widget_id, old_rect, new_rect):
        self._push(("widgets", widget_id, "rect"), old_rect, new_rect,
                   f"move {widget_id}")

    def push_move_subtree(self, changes, text=None):
        """ONE undoable command moving a widget AND every descendant
        (UiEditorParentingPLAN P-3, D2).

        ``changes`` is ``[(widget_id, old_rect, new_rect), ...]`` — full
        rects, never deltas, ``None`` meaning "no override" exactly as
        ``push_move`` does. Rows whose old and new agree are dropped, and a
        cascade that comes down to a single widget is left to ``push_move``
        by the caller: this method exists for the subtree case, not to
        replace it.

        The saved doc stays ABSOLUTE (D2) — the cascade happens here, at edit
        time, and the game's own ``layout()`` is untouched.
        """
        real = [c for c in changes if c[1] != c[2]]
        if not real:
            return
        label = text or f"move {real[0][0]} + {len(real) - 1} child(ren)"
        self.undo_stack.push(_DocFieldsCommand(
            self.doc,
            [(("widgets", widget_id, "rect"), old, new)
             for widget_id, old, new in real],
            label))

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

    def push_string(self, text_id, old_value, new_value):
        """Rewrite ONE `data/ui/strings.json` template, undoably (UT-1, D2).

        The string table is GLOBAL, not per-screen: a widget's `text_id`
        points into it, and editing the template here changes that text
        everywhere it is used. It rides this session's one `QUndoStack` (so
        Ctrl+Z crosses both docs in the order the designer made the edits) but
        writes to its own doc, saved by `save()` only when it actually
        changed.

        `new_value` is never `None` — the table is a closed key set
        (`additionalProperties: false`, every key `required`), so a template
        can be rewritten but never removed. Editing an id the table does not
        already carry is refused for the same reason; adding a key is a schema
        change, i.e. a code change (D3).
        """
        if self.strings_doc is None or text_id not in self.strings_doc:
            return
        self._push_doc(self.strings_doc, (text_id,), old_value, new_value,
                       f"edit text {text_id}")

    # -- UL-6: layer operations ------------------------------------------------
    # A widget's `layers` is an ARRAY of layer-spec dicts (see
    # data/schemas/ui_screen.schema.json), NOT an id-keyed object, so a layer
    # op cannot address one entry with a `_DocFieldCommand` path the way
    # push_field addresses `widgets/<id>/<key>`: `_set_at` walks dicts only,
    # and a path ending in a layer id would write an OBJECT where the schema
    # demands an array. Every layer op therefore pushes ONE command at
    # ("widgets", <widget_id>, "layers") carrying the FULL old array and the
    # FULL new array — the same "never a delta" contract as every other push_*,
    # and still exactly one undo step per op. `None` for the new value (an
    # emptied array) prunes the key, and `widgets/<id>` with it when that was
    # the widget's only override.

    def layers(self, widget_id):
        """The widget's layer array — a DEEP COPY, so a caller cannot edit the
        doc by mutating what it reads back. Empty list when the widget has no
        layers (or no override at all)."""
        return copy.deepcopy(self._layers_raw(widget_id))

    def _layers_raw(self, widget_id):
        """The live array inside the doc (never mutated here — every op builds
        a new list and pushes it). `[]` when absent."""
        if self.doc is None:
            return []
        entry = self.doc.get("widgets", {}).get(widget_id, {})
        value = entry.get("layers", [])
        return value if isinstance(value, list) else []

    def _layer_index(self, layers, layer_id):
        """Index of the FIRST entry whose non-empty `id` matches, else None —
        the same first-wins rule `engine.ui_layers.ordered` dedupes by."""
        if not layer_id:
            return None
        for i, entry in enumerate(layers):
            if isinstance(entry, dict) and entry.get("id") == layer_id:
                return i
        return None

    def _push_layers(self, widget_id, old_layers, new_layers, text):
        """Push ONE command replacing the whole array. An empty new array is
        pushed as `None` so `_apply_field` prunes the key (and the widget
        entry when nothing else is overridden) instead of leaving `[]`."""
        old = list(old_layers) if old_layers else None
        new = list(new_layers) if new_layers else None
        self._push(("widgets", widget_id, "layers"), old, new, text)

    def add_layer(self, widget_id, layer_id, layer_spec):
        """Append one layer to `widget_id`, undoably.

        `layer_spec` is a complete layer dict (offset/z/band/slot/... — keys
        pinned by the schema); its `id` is forced to `layer_id` so the array
        and the caller can never disagree about what the entry is called.
        Ignored (no command pushed) when `layer_id` is empty or already used
        by this widget: ids are the only handle remove/reorder/set have, and
        `ordered()` silently drops a duplicate, so admitting one would create
        a layer that draws but cannot be edited. The PANEL generates unique
        ids, so this guard is a backstop, not the normal path.
        """
        if not layer_id or self.doc is None:
            return
        old = self._layers_raw(widget_id)
        if self._layer_index(old, layer_id) is not None:
            return
        entry = copy.deepcopy(layer_spec) if layer_spec else {}
        entry["id"] = layer_id
        self._push_layers(widget_id, old, list(old) + [entry],
                          f"add layer {layer_id} to {widget_id}")

    def remove_layer(self, widget_id, layer_id):
        """Drop one layer from `widget_id`, undoably. Removing the last layer
        prunes the `layers` key entirely (and `widgets/<id>` when that was its
        only override) — the same "None = absent" rule every reset follows."""
        old = self._layers_raw(widget_id)
        index = self._layer_index(old, layer_id)
        if index is None:
            return
        new = list(old)
        del new[index]
        self._push_layers(widget_id, old, new,
                          f"remove layer {layer_id} from {widget_id}")

    def set_layer_field(self, widget_id, layer_id, field_key, old_value,
                        new_value, text=None):
        """Set (or clear, with `new_value=None`) ONE key on ONE layer.

        Mirrors `push_field`'s signature — the caller passes the FULL old and
        new values and the old==new guard refuses a no-op. `old_value` is the
        caller's record of what the key held; it is used only for that guard
        (the command itself stores whole arrays), so a caller that does not
        track it may pass the current value.
        """
        if old_value == new_value:
            return
        old = self._layers_raw(widget_id)
        index = self._layer_index(old, layer_id)
        if index is None:
            return
        entry = copy.deepcopy(old[index])
        if new_value is None:
            entry.pop(field_key, None)
        else:
            entry[field_key] = copy.deepcopy(new_value)
        new = list(old)
        new[index] = entry
        self._push_layers(widget_id, old, new,
                          text or f"edit layer {layer_id}.{field_key}")

    def reorder_layer(self, widget_id, layer_id, new_z):
        """Move one layer within its band by rewriting only its `z` (D2 —
        paint order is z within band, so nothing else needs to move)."""
        old = self._layers_raw(widget_id)
        index = self._layer_index(old, layer_id)
        if index is None:
            return
        self.set_layer_field(widget_id, layer_id, "z",
                             old[index].get("z", 0), new_z,
                             text=f"reorder layer {layer_id}")
