"""BalancingPanel (ED-30/31/32) — schema-generated form over one domain.

set_domain(d) reloads data/balancing/<d>.json fresh from disk and rebuilds
the form from data/schemas/<d>.schema.json. Since Phase 9A the domains are
nested REPLAN trees, so the build recurses: object -> CollapsibleSection
(depth-1 groups start expanded, deeper ones collapsed), array of objects ->
one collapsed sub-section per index (titled with the tier's name field when
present), array of scalars -> one row per index. Arrays of objects get
`+ Row`/`- Row` (ER-5) gated entirely by the schema's own minItems/maxItems —
an array whose schema pins minItems == maxItems (`tiers`, `scale_tiers`,
`round_counts`) shows neither button and is unchanged. Arrays of SCALARS get
the same buttons only when their own property additionally sets
`"x-array-editable": true` (feature-enemy-intro-dialogue) — `minItems !=
maxItems` alone is not enough, since `random_names` (`minItems: 1`, no
maxItems) already has that shape and must keep growing only via the game's
add-name menu, never this panel; `EnemyIntro.entries[i].hidden_frames` is the
one property that opts in today. Scalar leaves: integer -> QSpinBox, number -> QDoubleSpinBox (ranges
from the schema's minimum/maximum, so out-of-range input is unrepresentable,
not merely rejected), enum -> QComboBox, boolean -> QCheckBox, string ->
QLineEdit (empty input is restored, not written, when the schema demands
minLength >= 1). Tier-shape subschemas live in each schema's $defs and are
resolved via local #/$defs/ refs only. Each widget's tooltip carries the
leaf's schema description (units / x10 combat-scale hints, D-12).
Underscore-prefixed keys never appear as fields at any depth.

Widgets register in self._widgets keyed by '/'-joined paths, e.g.
"DefenceBuildings/BasicDefence/tiers/0/base_dmg". The numeric/enum widgets
never react to mouse-wheel scrolling (_NoWheelSpinBox/_NoWheelDoubleSpinBox/
_NoWheelComboBox ignore wheelEvent so scrolling the panel can never nudge a
value by accident) — the wheel event propagates to the enclosing
QScrollArea instead.

Edits are STAGED, not written immediately: every change updates self._doc in
memory and toggles a small pending-change dot next to that field (comparing
against self._baseline, a snapshot taken at load/last-save time). The
toolbar's "Save Balancing Changes" button is the ONE place that calls
engine.data_io.write_validated (ED-31) — validation raises before disk — and
it also appends a full-document snapshot to this domain's version history
(editor.balancing_history, data/balancing_history/<domain>.json) after
prompting for a session name/description. "Version History" opens a dialog
listing that domain's history newest-first; "Load into Editor" replays a
past snapshot into the live widgets (staged, not written — the dirty dots
reappear for whatever differs from the current baseline) and the user must
Save again to persist it.

A leaf whose path sits inside an `.../eras/<int>/...` subtree with an index
above 0 also carries a greyed, disabled, read-only reference label showing what
that field resolves to on the LAST round of the PREVIOUS era (D9,
engine.era_math.prev_era_reference). Era 0 shows nothing. Detection is purely
path-shape based, so any future type that grows era rows inherits it; the values
come from the STAGED doc and refresh on every edit, so retuning era 0 updates
era 1's reference before anything is saved.

Undo via the global QUndoStack (ED-24) remains deferred.

A numeric weight leaf whose schema property carries `"x-toggle": "<sibling
key>"` (a house-style JSON Schema annotation, ignored by validation — schemas
still validate structurally, unknown keywords are just data) gets a paired
QCheckBox rendered immediately LEFT of its spinbox, inside the same row
widget. The sibling is resolved as a SIBLING OF THE LEAF'S PARENT OBJECT: for
`Pathfinding/content_weights/defence_building`, the toggle bool lives at
`Pathfinding/content_weight_overwrites/defence_building` (same leaf key, one
level up then across to the sibling object named by `x-toggle`, `_schema_node_at`
walks the schema's OWN properties tree the same way, from the root, so the
sibling's tooltip description resolves independently of the current recursion
branch). The checkbox commits straight to the sibling's OWN path via the same
`_commit` every widget uses, so dirty tracking and the single Save write path
need no changes; it registers in `self._widgets` under the sibling path like
any other widget. A toggle object itself (e.g. `content_weight_overwrites`)
carries `"x-paired": true` so `_build_object` skips it as its own section —
its only rendering is inline, paired with its partner weights. Missing
sibling object/key degrades to a plain row (no exception) so a domain whose
doc doesn't carry the toggle object still builds.

A schema node carrying `"x-widget": "<name>"` (SD-3; `sound_slot` is the first
and only one) is claimed WHOLE by a composite widget: `_build_object` routes it
straight to `_add_leaf_row` instead of the object/array recursion below (a sound
slot IS an object, so it would otherwise become a CollapsibleSection of raw
rows), and `_make_widget`'s first branch builds it. Reusing `_add_leaf_row` is
what gives the composite the dirty dot, the `self._widgets` registration and the
description tooltip for free; `_set_widget_value` learns the type so Version
History's `_apply_snapshot` sets the whole object rather than silently skipping
it. The widget stages through this panel's `_commit` — no second doc, no second
dirty set, no second writer.
"""
import copy
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor import balancing_history, domains, sound_import
from engine import data_io, era_math

REPO = Path(__file__).resolve().parents[2]


class _NoWheelSpinBox(QSpinBox):
    """A wheel over this widget scrolls the panel, never changes the value."""

    def wheelEvent(self, event):
        event.ignore()


class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class CollapsibleSection(QWidget):
    """A QToolButton arrow header toggling a content widget's visibility."""

    def __init__(self, title, tooltip="", expanded=False, parent=None):
        super().__init__(parent)
        self._button = QToolButton()
        self._button.setText(title)
        self._button.setToolTip(tooltip)
        self._button.setCheckable(True)
        self._button.setChecked(expanded)
        self._button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self._button.setStyleSheet("QToolButton { border: none; font-weight: bold; }")
        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(16, 0, 0, 4)
        self.content.setVisible(expanded)
        self._sync_arrow(expanded)
        self._button.toggled.connect(self._on_toggled)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._button)
        layout.addWidget(self.content)

    def _sync_arrow(self, expanded):
        self._button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _on_toggled(self, expanded):
        self._sync_arrow(expanded)
        self.content.setVisible(expanded)


class _SaveMetaDialog(QDialog):
    """Session name (required) + description (optional) for a history entry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save Balancing Changes")
        self._name = QLineEdit()
        self._description = QLineEdit()
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_button = buttons.button(QDialogButtonBox.Ok)
        ok_button.setEnabled(False)
        self._name.textChanged.connect(
            lambda text: ok_button.setEnabled(bool(text.strip()))
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Session Name", self._name)
        form.addRow("Description", self._description)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def session_name(self):
        return self._name.text().strip()

    def session_description(self):
        return self._description.text().strip()


class _HistoryDialog(QDialog):
    """Browse a domain's saved sessions; load one back into the live form."""

    def __init__(self, panel, parent=None):
        super().__init__(parent)
        self._panel = panel
        self._sessions = []
        self.setWindowTitle(f"Version History — {panel.domain}")
        self.resize(480, 360)
        self._list = QListWidget()
        load_btn = QPushButton("Load into Editor")
        load_btn.clicked.connect(self._load_selected)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_selected)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row = QHBoxLayout()
        btn_row.addWidget(load_btn)
        btn_row.addWidget(delete_btn)
        btn_row.addStretch(1)
        btn_row.addWidget(close_btn)
        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(btn_row)
        self._reload_list()

    def _reload_list(self):
        self._sessions = balancing_history.load_sessions(
            self._panel.domain, self._panel._data_dir
        )
        self._list.clear()
        for entry in self._sessions:
            self._list.addItem(f"{entry['timestamp']} — {entry['name']}")

    def _selected_entry(self):
        row = self._list.currentRow()
        if row < 0:
            return None
        return self._sessions[row]

    def _load_selected(self):
        entry = self._selected_entry()
        if entry is None:
            return
        self._panel._apply_snapshot(entry["snapshot"])
        self.accept()

    def _delete_selected(self):
        entry = self._selected_entry()
        if entry is None:
            return
        if (
            QMessageBox.question(
                self, "Delete Session", f"Delete '{entry['name']}'?"
            )
            != QMessageBox.Yes
        ):
            return
        balancing_history.delete_session(
            self._panel.domain, entry["id"], self._panel._data_dir
        )
        self._reload_list()


class BalancingPanel(QWidget):
    # objectName prefixes on the array +/- Row buttons: the array's '/'-joined
    # path follows, so a test can assert WHICH arrays are resizable without
    # reaching into the layout tree.
    ROW_ADD = "rowadd:"
    ROW_REMOVE = "rowremove:"
    # objectName prefix on the greyed previous-era reference labels (D9), same
    # convention: the leaf's '/'-joined path follows.
    PREV_REF = "prevref:"
    # The ONE structural marker D9's reference labels key off (see _era_context).
    ERA_ARRAY_KEY = "eras"
    # ESV-4: fires (path, value) whenever ANY value is staged into self._doc —
    # from a generic-form widget edit OR from the vfx preview panel's
    # stage_value() call (§2.3). The preview panel is the one subscriber
    # today; a listener must filter by its own domain/path interest itself
    # (this panel has none — "one staging store" stays domain-agnostic).
    value_staged = Signal(str, object)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.domain = None
        self._doc = None
        self._baseline = None
        self._schema = None
        self._widgets = {}
        self._dots = {}
        self._refs = {}
        self._scalar_item_schema = {}
        self._dirty = set()

        self._save_btn = QPushButton("Save Balancing Changes")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        history_btn = QPushButton("Version History")
        history_btn.clicked.connect(self._open_history)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self._save_btn)
        toolbar.addWidget(history_btn)
        toolbar.addStretch(1)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._scroll)

    # -- selection drives content (ED-3) ------------------------------------

    def set_domain(self, domain):
        self.domain = domain
        self._doc = data_io.load_validated(
            domains.balancing_path(domain, self._data_dir),
            domains.schema_path(domain, self._data_dir),
        )
        self._baseline = copy.deepcopy(self._doc)
        self._dirty = set()
        self._schema = data_io.load_json(domains.schema_path(domain, self._data_dir))
        self._rebuild_form(self._schema)
        self._save_btn.setEnabled(False)

    def _rebuild_form(self, schema):
        self._widgets = {}
        self._dots = {}
        self._refs = {}
        self._scalar_item_schema = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self._build_object(schema, self._doc, (), content_layout, depth=0)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)
        # Fresh widgets start with their dot hidden, so a rebuild that is NOT a
        # domain switch (adding/removing an array row) would silently drop the
        # dots of every other staged edit. `set_domain` clears `_dirty` first, so
        # this is a no-op on that path.
        for key in self._dirty:
            dot = self._dots.get(key)
            if dot is not None:
                dot.setVisible(True)
        self._save_btn.setEnabled(bool(self._dirty))

    # -- recursive schema walk (Phase 9A nested tree) ------------------------

    def _deref(self, node):
        """Resolve local #/$defs/ refs — the only kind the house style allows."""
        while "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"{self.domain}: non-local $ref {ref!r}")
            node = self._schema["$defs"][ref.removeprefix("#/$defs/")]
        return node

    def _schema_node_at(self, path):
        """Walk the FULL schema tree (from the root, not just the branch a
        recursive _build_object call happens to be holding) to the property
        node at a '/'-joined-style path tuple. Used to resolve an `x-toggle`
        sibling's own schema node (for its `description`) without needing
        every caller up the recursion to thread its schema branch through.
        Returns None on any missing segment — a domain whose doc/schema
        omits the toggle path must degrade, not raise."""
        node = self._schema
        for seg in path:
            node = self._deref(node)
            props = node.get("properties")
            if not props or seg not in props:
                return None
            node = props[seg]
        return self._deref(node)

    def _object_properties(self, node, value):
        """The ``{key: subschema}`` map to render this object level from.

        Normally just the node's own ``properties``. An OPEN object — one that
        declares no ``properties`` and types its members through
        ``additionalProperties`` instead — has no key list in the schema at
        all, so its keys come from the DOC and every one of them renders
        against that single shared subschema. ``vfx.schema.json``'s
        ``triggers_by_type`` (the per-type VFX registry, open two levels deep)
        is the first such node; without this the panel raised ``KeyError:
        'properties'`` and took the whole vfx balancing form down with it.

        A node that is open AND has no dict ``additionalProperties`` (i.e. a
        free-form blob like the tutorial's ``flags``) yields nothing, which is
        the honest answer: there is no schema to build widgets from."""
        props = node.get("properties")
        if props is not None:
            return props
        extra = node.get("additionalProperties")
        if isinstance(extra, dict) and isinstance(value, dict):
            return {key: extra for key in value}
        return {}

    def _build_object(self, node, value, path, parent_layout, depth):
        """One object level: scalar leaves collect into QFormLayouts, nested
        objects/arrays become CollapsibleSections, in sorted key order."""
        form = None
        for key, prop in sorted(self._object_properties(node, value).items()):
            if key.startswith("_"):
                continue
            if key not in value:
                continue  # schema-optional leaf absent here (e.g. era_unlock_round on later tiers)
            prop = self._deref(prop)
            if prop.get("x-paired"):
                continue  # a toggle-bool sibling object (x-toggle) renders inline, not as its own section
            if prop.get("x-widget"):
                # SD-3: a composite widget claims this node whole. Routed here
                # rather than left to `kind` below because a sound slot IS an
                # object, and the object branch would recurse it into a
                # CollapsibleSection of raw rows and never reach _make_widget.
                # Reusing _add_leaf_row is deliberate: it is what registers the
                # widget in self._widgets, attaches the dirty dot and sets the
                # tooltip — so the composite inherits dirty/history/rebuild
                # behaviour with no new bookkeeping.
                if form is None:
                    form = QFormLayout()
                    parent_layout.addLayout(form)
                self._add_leaf_row(form, key, prop, value[key], path + (key,))
                continue
            kind = prop.get("type")
            if kind in ("object", "array"):
                form = None
                section = CollapsibleSection(
                    key, prop.get("description", ""), expanded=depth == 0
                )
                if kind == "object":
                    self._build_object(
                        prop, value[key], path + (key,),
                        section.content_layout, depth + 1,
                    )
                else:
                    self._build_array(
                        prop, value[key], path + (key,),
                        section.content_layout, depth + 1,
                    )
                parent_layout.addWidget(section)
            else:
                if form is None:
                    form = QFormLayout()
                    parent_layout.addLayout(form)
                self._add_leaf_row(form, key, prop, value[key], path + (key,))

    def _build_array(self, node, items, path, parent_layout, depth):
        item_schema = self._deref(node["items"])
        if item_schema.get("type") == "object":
            for i, item in enumerate(items):
                title = f"[{i}]"
                if isinstance(item.get("name"), str):
                    title = f"[{i}] — {item['name']}"
                section = CollapsibleSection(
                    title, item_schema.get("description", ""), expanded=False
                )
                self._build_object(
                    item_schema, item, path + (str(i),),
                    section.content_layout, depth + 1,
                )
                parent_layout.addWidget(section)
            self._add_row_buttons(node, items, path, parent_layout)
        else:
            form = QFormLayout()
            parent_layout.addLayout(form)
            for i, item in enumerate(items):
                self._add_leaf_row(
                    form, f"[{i}]", item_schema, item, path + (str(i),)
                )
            if node.get("x-array-editable"):
                self._add_row_buttons(node, items, path, parent_layout,
                                      item_schema=item_schema)

    # -- variable-length arrays: + / − Row (ER-5, generalized to scalars) ----

    def _add_row_buttons(self, node, items, path, parent_layout, item_schema=None):
        """A `+ Row` / `− Row` pair under a variable-length array, gated
        ENTIRELY by the schema's own minItems/maxItems.

        That gate is the compatibility argument: every array that shipped before
        ER-5 (`tiers`, `scale_tiers`, `round_counts`) has minItems == maxItems, so
        both buttons stay hidden and those forms are unchanged. `death_spawn.spawns`
        (minItems 1, no maxItems) is the first array of OBJECTS a designer may
        actually resize — a per-era table for a type that ships with one row.

        Add COPIES THE LAST ROW rather than building a default instance from the
        schema, same as ER-5 shipped: the document validated on load, so a copy
        is schema-valid by construction — no guessing at pattern/minLength/
        required. Remove pops the LAST row, never a middle one: these arrays are
        era-indexed, so removing [1] would silently renumber every era after it.

        `item_schema`, when given, marks this as an array of SCALARS (the
        `enemy_intro_entry.hidden_frames` case, ships `minItems: 0`) rather than
        objects: unlike the object-array case, an empty scalar array has no last
        row to copy, so `_add_array_row` synthesizes one from the schema instead
        (`_default_scalar_value`). Deliberately NOT extended to arrays of
        objects — an object has no single sensible schema-derived default
        (`required`/`pattern`/cross-field constraints), which is exactly why
        object-array Add always copies a row instead.

        Callers only reach this for a scalar array when its own schema node
        carries `"x-array-editable": true` (see `_build_array`'s scalar
        branch) — an EXPLICIT opt-in, not "every array whose minItems !=
        maxItems". `BuildingsGlobal.random_names` (`buildings.schema.json`,
        `minItems: 1`, no `maxItems`) shares that exact shape but grows only
        through the game's own 9H add-name menu, never this panel — it carries
        no such marker and is unaffected. `hidden_frames` is the only property
        that sets it today.
        """
        can_add = "maxItems" not in node or len(items) < node["maxItems"]
        can_remove = len(items) > node.get("minItems", 0)
        if not (can_add or can_remove):
            return
        key = "/".join(path)
        if item_schema is not None:
            self._scalar_item_schema[key] = item_schema
        row = QHBoxLayout()
        if can_add:
            add = QPushButton("+ Row")
            add.setObjectName(f"{self.ROW_ADD}{key}")   # so tests can see WHICH
            add.setToolTip("Append a copy of the last row"
                          if items else "Append a new row")
            add.clicked.connect(lambda _c=False, k=key: self._add_array_row(k))
            row.addWidget(add)
        if can_remove:
            remove = QPushButton("− Row")
            remove.setObjectName(f"{self.ROW_REMOVE}{key}")
            remove.setToolTip("Remove the last row")
            remove.clicked.connect(lambda _c=False, k=key: self._remove_array_row(k))
            row.addWidget(remove)
        row.addStretch(1)
        parent_layout.addLayout(row)

    def _add_array_row(self, key):
        items = self._value_at(key)
        if items:
            items.append(copy.deepcopy(items[-1]))
        else:
            items.append(self._default_scalar_value(
                self._scalar_item_schema.get(key)))
        self._commit_structure(key)

    def _default_scalar_value(self, item_schema):
        """A schema-valid starting value for a brand-new row in an EMPTY
        scalar array (there is no last row to copy — see `_add_row_buttons`).
        Only reached for a scalar `items` schema; an unresolvable/absent one
        degrades to `0` rather than raising, since a Qt slot must never let an
        exception escape."""
        item_schema = self._deref(item_schema) if item_schema else {}
        if "enum" in item_schema:
            values = item_schema["enum"]
            return values[0] if values else 0
        kind = item_schema.get("type")
        if kind == "boolean":
            return False
        if kind == "string":
            return ""
        return item_schema.get("minimum", 0)

    def _remove_array_row(self, key):
        self._value_at(key).pop()
        self._commit_structure(key)

    def _commit_structure(self, key):
        """A row was added/removed: `self._doc` already carries it (staged, like
        every other edit — nothing reaches disk until Save). Re-dirty on the ARRAY
        path, which `_refresh_dirty` compares whole against the baseline, so adding
        a row and removing it again cleans itself back up; then rebuild the form so
        the new row gets widgets."""
        self._refresh_dirty(key)
        self._rebuild_form(self._schema)

    def _add_leaf_row(self, form, label, prop, value, path):
        widget = self._make_widget(path, prop, value)
        widget.setToolTip(prop.get("description", ""))
        dot = QLabel("●")
        dot.setStyleSheet("color: white;")
        dot.setFixedWidth(12)
        dot.setVisible(False)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        toggle = self._build_toggle_checkbox(prop, path)
        if toggle is not None:
            row_layout.insertWidget(0, toggle)
        row_layout.addWidget(widget)
        row_layout.addWidget(dot)
        key = "/".join(path)
        ref = self._build_reference_label(path)
        if ref is not None:
            row_layout.addWidget(ref)
            self._refs[key] = (ref, path)
        form.addRow(label, row)
        self._widgets[key] = widget
        self._dots[key] = dot

    # -- D9: the greyed previous-era reference -------------------------------

    def _era_context(self, path):
        """Split a leaf path that sits inside an `.../eras/<int>/...` subtree.

        Returns `(rows_path, era, leaf_subpath)` or None. Detection is purely
        PATH-SHAPE based — the literal segment `eras` followed by an integer
        index — so any future type that grows era rows (the Commander) inherits
        the reference label with zero edits here. No domain, type or field name
        is hardcoded.
        """
        for j in range(len(path) - 3, -1, -1):
            if path[j] == self.ERA_ARRAY_KEY and path[j + 1].isdigit():
                return path[: j + 1], int(path[j + 1]), path[j + 2:]
        return None

    def _rounds_per_era(self):
        """The staged doc's era length. Found by KEY SHAPE (the one top-level
        block carrying `rounds_per_era`), never by naming a domain's general
        block; falls back to 10 so a doc without one still renders."""
        if isinstance(self._doc, dict):
            for value in self._doc.values():
                if isinstance(value, dict) and "rounds_per_era" in value:
                    return value["rounds_per_era"]
        return 10

    def _reference_value(self, path):
        """What this leaf resolved to on the LAST round of the previous era
        (D9), read off the STAGED doc — so editing era 0 updates era 1's
        reference before anything is saved. None when there is nothing to
        show (era 0, no era subtree, a non-numeric or absent leaf)."""
        context = self._era_context(path)
        if context is None:
            return None
        rows_path, era, leaf_subpath = context
        if era <= 0 or not leaf_subpath:
            return None
        try:
            rows = self._value_at("/".join(rows_path))
            root = self._value_at("/".join(rows_path[:-1])) if len(rows_path) > 1 \
                else self._doc
            ref = era_math.prev_era_reference(
                rows,
                era,
                self._rounds_per_era(),
                start_round=root.get("start_round", 1),
                endgame_factors=root.get("endgame_scaling"),
            )
            for seg in leaf_subpath:
                ref = ref[int(seg)] if seg.isdigit() else ref[seg]
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            # This runs while building a Qt form and inside a Qt slot; a doc
            # shape the era math cannot read must degrade to no label.
            return None
        if isinstance(ref, bool) or not isinstance(ref, (int, float)):
            return None
        return ref

    @staticmethod
    def _format_reference(value):
        if isinstance(value, int):
            return f"prev ⌐ {value}"
        rounded = round(float(value), 4)
        if rounded == int(rounded):
            return f"prev ⌐ {int(rounded)}"
        return f"prev ⌐ {rounded:g}"

    def _build_reference_label(self, path):
        value = self._reference_value(path)
        if value is None:
            return None
        ref = QLabel(self._format_reference(value))
        ref.setObjectName(f"{self.PREV_REF}{'/'.join(path)}")
        ref.setToolTip(
            "What this field resolves to on the last round of the previous era "
            "(read-only)"
        )
        ref.setEnabled(False)
        # Deliberately theme-independent, like the pending dot: a mid grey that
        # stays legible on both the light and the dark chrome.
        ref.setStyleSheet("color: #8a8a8a;")
        return ref

    def _refresh_references(self):
        """Recompute every visible reference off the staged doc. Cheap enough
        to run on every edit (a domain's era leaves number in the hundreds) and
        it is the only thing that keeps era N+1's reference honest while era N
        is being typed into."""
        for label, path in self._refs.values():
            value = self._reference_value(path)
            label.setText("" if value is None else self._format_reference(value))

    def _build_toggle_checkbox(self, prop, path):
        """A weight leaf's `x-toggle` schema annotation names a SIBLING
        object (a resolved sibling of the leaf's own parent object, same
        leaf key — `Pathfinding/content_weights/defence_building`'s toggle
        lives at `Pathfinding/content_weight_overwrites/defence_building`)
        holding the paired override bool. Returns a QCheckBox built exactly
        like a generic boolean leaf's widget (`_make_widget`'s boolean
        branch), or None if there is no `x-toggle`, the path is too shallow
        to have a sibling, or the sibling object/key is missing from the doc
        or schema — a domain whose doc omits the toggle object must still
        render the row exactly as today, not raise."""
        toggle_key = prop.get("x-toggle")
        if not toggle_key or len(path) < 2:
            return None
        sibling_path = path[:-2] + (toggle_key, path[-1])
        try:
            sibling_value = self._value_at("/".join(sibling_path))
        except (KeyError, IndexError, TypeError):
            return None
        sibling_prop = self._schema_node_at(sibling_path)
        if sibling_prop is None:
            return None
        checkbox = QCheckBox()
        checkbox.setChecked(bool(sibling_value))
        checkbox.setToolTip(sibling_prop.get("description", ""))
        key = "/".join(sibling_path)
        checkbox.toggled.connect(lambda v, k=key: self._commit(k, bool(v)))
        self._widgets[key] = checkbox
        return checkbox

    # -- widget per schema type: invalid input unrepresentable (ED-30) ------

    def _make_widget(self, path, prop, value):
        key = "/".join(path)
        if prop.get("x-widget") == "sound_slot":
            # SD-3. Imported lazily: editor.panels.sound_slot imports the
            # _NoWheel* widgets FROM this module (their one home), so a
            # module-scope import here would be circular.
            from editor.panels.sound_slot import SoundSlotWidget
            widget = SoundSlotWidget(value, prop, path, self, self._data_dir)
        elif "enum" in prop:
            widget = _NoWheelComboBox()
            for option in prop["enum"]:
                widget.addItem(str(option), option)
            widget.setCurrentIndex(widget.findData(value))
            widget.currentIndexChanged.connect(
                lambda _i, k=key, w=widget: self._commit(k, w.currentData())
            )
        elif prop.get("type") == "boolean":
            widget = QCheckBox()
            widget.setChecked(value)
            widget.toggled.connect(lambda v, k=key: self._commit(k, bool(v)))
        elif prop.get("type") == "integer":
            widget = _NoWheelSpinBox()
            widget.setRange(int(prop.get("minimum", -(2**31))),
                            int(prop.get("maximum", 2**31 - 1)))
            widget.setValue(value)
            widget.valueChanged.connect(lambda v, k=key: self._commit(k, int(v)))
        elif prop.get("type") == "number":
            widget = _NoWheelDoubleSpinBox()
            widget.setRange(float(prop.get("minimum", -1e9)),
                            float(prop.get("maximum", 1e9)))
            widget.setDecimals(4)
            widget.setSingleStep(0.1)
            widget.setValue(value)
            widget.valueChanged.connect(lambda v, k=key: self._commit(k, float(v)))
        elif prop.get("type") == "string":
            widget = QLineEdit()
            widget.setText(value)
            min_length = prop.get("minLength", 0)
            widget.editingFinished.connect(
                lambda k=key, w=widget, m=min_length: self._commit_string(k, w, m)
            )
        else:
            raise ValueError(f"{self.domain}.{key}: no widget for schema {prop!r}")
        return widget

    def _commit_string(self, key, widget, min_length):
        text = widget.text()
        if len(text) < min_length:
            widget.setText(self._value_at(key))  # restore: empty is unrepresentable
            return
        if text != self._value_at(key):
            self._commit(key, text)

    # -- staged edits: every change mutates self._doc + a dirty dot ---------

    def _value_at(self, key, doc=None):
        node = self._doc if doc is None else doc
        for seg in key.split("/"):
            node = node[int(seg)] if seg.isdigit() else node[seg]
        return node

    def _commit(self, key, value):
        segments = key.split("/")
        node = self._doc
        for seg in segments[:-1]:
            node = node[int(seg)] if seg.isdigit() else node[seg]
        last = segments[-1]
        node[int(last) if last.isdigit() else last] = value
        self._refresh_dirty(key)
        self.value_staged.emit(key, value)

    # -- ESV-4: the vfx preview panel's read/write seam into staging --------
    # No second doc, no second dirty set, no second writer: the preview panel
    # holds a reference to THIS panel and goes through these two methods plus
    # value_staged above, so a lever in the preview and its twin row in the
    # generic form can never disagree (phase-esv-4-vfx-preview.md §2.3).

    def staged_value(self, path):
        """Public read of the current staged value at a `/`-joined path —
        the same lookup `_value_at` already does internally, exposed for a
        caller outside this class."""
        return self._value_at(path)

    def stage_value(self, path, value):
        """Stage `value` at `path` exactly like a generic-form widget edit
        (dirty dot + `value_staged`), and additionally push it into that
        path's OWN generic-form widget (if the form currently has one) so
        the two views of the same staged doc can never show different
        numbers.

        A `path` may address a whole ARRAY (e.g. a named-stop colour —
        `procedural/<family>/ramp/stop_0`, a 3-int RGB list) that the
        generic form has no single widget for: `_build_array`'s
        array-of-scalars branch registers one widget PER INDEX instead
        (`.../stop_0/0`, `.../stop_0/1`, `.../stop_0/2`). Fall back to those
        per-index widgets when the whole-path widget does not exist, so a
        colour picked here still lights up the three spinboxes below."""
        self._commit(path, value)
        widget = self._widgets.get(path)
        if widget is not None:
            self._set_widget_value(path, widget, value)
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                child = self._widgets.get(f"{path}/{i}")
                if child is not None:
                    self._set_widget_value(f"{path}/{i}", child, item)

    def sound_usage_docs(self):
        """SD-3: `{domain: doc_or_None}` across EVERY balancing domain, for the
        sound-clip refcount behind "Use existing…".

        This panel is the one object holding both the live staged document and
        its domain name, so it is the one place that can hand the (pure)
        refcount its own domain's UNSAVED state — otherwise a clip the designer
        attached seconds ago reads as unreferenced. The other domains come from
        disk, and one that fails to load degrades to None ("count unknown"),
        never to zero users."""
        return sound_import.usage_docs(self._data_dir, self.domain, self._doc)

    def _refresh_dirty(self, key):
        try:
            baseline = self._value_at(key, self._baseline)
        except (KeyError, IndexError, TypeError):
            # The path does not exist in the baseline at all — it is a field of a
            # row the user just ADDED (ER-5). That is dirty by definition, and the
            # lookup must not raise: this runs inside a Qt slot, where an unhandled
            # exception can take the process down.
            dirty = True
        else:
            dirty = self._value_at(key) != baseline
        if dirty:
            self._dirty.add(key)
        else:
            self._dirty.discard(key)
        dot = self._dots.get(key)
        if dot is not None:
            dot.setVisible(dirty)
        # D9: any staged edit can move a LATER era's reference (era 0's
        # per_round.hp changes what era 1 shows), so refresh them all here —
        # the one place every staged change funnels through.
        self._refresh_references()
        self._save_btn.setEnabled(bool(self._dirty))

    def _set_widget_value(self, key, widget, value):
        from editor.panels.sound_slot import SoundSlotWidget  # lazy: see _make_widget
        if isinstance(widget, SoundSlotWidget):
            # SD-3: a composite widget owns a whole object, not a scalar.
            # Without this arm _apply_snapshot (Version History) would silently
            # skip every sound slot.
            widget.set_slot(value)
        elif isinstance(widget, QComboBox):
            widget.setCurrentIndex(widget.findData(value))
        elif isinstance(widget, QCheckBox):
            widget.setChecked(bool(value))
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.setValue(value)
        elif isinstance(widget, QLineEdit):
            widget.setText(value)
            widget.editingFinished.emit()

    def _apply_snapshot(self, snapshot):
        """Load a past history snapshot into the live widgets (staged, not
        written — dirty dots reappear for whatever differs from baseline)."""
        for key, widget in self._widgets.items():
            try:
                value = self._value_at(key, snapshot)
            except (KeyError, IndexError, TypeError):
                continue
            self._set_widget_value(key, widget, value)

    # -- explicit save: the ONE write path (ED-31) + version history --------

    def _on_save(self):
        if not self._dirty:
            return
        dialog = _SaveMetaDialog(self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.save_changes(dialog.session_name(), dialog.session_description())

    def save_changes(self, name, description=""):
        """Write the staged document to disk and record a history snapshot."""
        data_io.write_validated(
            self._doc,
            domains.balancing_path(self.domain, self._data_dir),
            domains.schema_path(self.domain, self._data_dir),
        )
        balancing_history.save_session(
            self.domain, name, description, copy.deepcopy(self._doc), self._data_dir
        )
        self._baseline = copy.deepcopy(self._doc)
        self._dirty = set()
        for dot in self._dots.values():
            dot.setVisible(False)
        self._save_btn.setEnabled(False)

    def _open_history(self):
        _HistoryDialog(self, self).exec()
