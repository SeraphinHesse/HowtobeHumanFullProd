"""BalancingPanel (ED-30/31/32) — schema-generated form over one domain.

set_domain(d) reloads data/balancing/<d>.json fresh from disk and rebuilds
the form from data/schemas/<d>.schema.json. Since Phase 9A the domains are
nested REPLAN trees, so the build recurses: object -> CollapsibleSection
(depth-1 groups start expanded, deeper ones collapsed), array of objects ->
one collapsed sub-section per index (titled with the tier's name field when
present), array of scalars -> one row per index (fixed length — add/remove
is not a 9A editor feature; random_names grows via the game's add-name
menu). Scalar leaves: integer -> QSpinBox, number -> QDoubleSpinBox (ranges
from the schema's minimum/maximum, so out-of-range input is unrepresentable,
not merely rejected), enum -> QComboBox, boolean -> QCheckBox, string ->
QLineEdit (empty input is restored, not written, when the schema demands
minLength >= 1). Tier-shape subschemas live in each schema's $defs and are
resolved via local #/$defs/ refs only. Each widget's tooltip carries the
leaf's schema description (units / x10 combat-scale hints, D-12).
Underscore keys (_lock) never appear as fields at any depth.

Widgets register in self._widgets keyed by '/'-joined paths, e.g.
"DefenceBuildings/BasicDefence/tiers/0/base_dmg". Every change writes the
whole document through engine.data_io.write_validated (ED-31) — validation
raises before disk. A locked domain (editor.locks) renders the form
disabled with the owner in a banner (ED-32); lock state is read at
selection time. Undo via the global QUndoStack (ED-24) remains deferred.
"""
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor import locks
from engine import data_io

REPO = Path(__file__).resolve().parents[2]


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


class BalancingPanel(QWidget):
    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.domain = None
        self._doc = None
        self._schema = None
        self._widgets = {}

        self._banner = QLabel()
        self._banner.setStyleSheet("font-weight: bold; color: #b5651d;")
        self._banner.hide()
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addWidget(self._scroll)

    # -- selection drives content (ED-3) ------------------------------------

    def set_domain(self, domain):
        self.domain = domain
        self._doc = data_io.load_validated(
            locks.balancing_path(domain, self._data_dir),
            locks.schema_path(domain, self._data_dir),
        )
        self._schema = data_io.load_json(locks.schema_path(domain, self._data_dir))
        locked = locks.is_locked(domain, self._data_dir)
        self._rebuild_form(self._schema, locked)
        if locked:
            self._banner.setText(
                f"Locked by {locks.owner(domain, self._data_dir)} "
                f"since {locks.since(domain, self._data_dir)} — read-only"
            )
            self._banner.show()
        else:
            self._banner.hide()

    def _rebuild_form(self, schema, locked):
        self._widgets = {}
        old = self._scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        self._build_object(schema, self._doc, (), content_layout, locked, depth=0)
        content_layout.addStretch(1)
        self._scroll.setWidget(content)

    # -- recursive schema walk (Phase 9A nested tree) ------------------------

    def _deref(self, node):
        """Resolve local #/$defs/ refs — the only kind the house style allows."""
        while "$ref" in node:
            ref = node["$ref"]
            if not ref.startswith("#/$defs/"):
                raise ValueError(f"{self.domain}: non-local $ref {ref!r}")
            node = self._schema["$defs"][ref.removeprefix("#/$defs/")]
        return node

    def _build_object(self, node, value, path, parent_layout, locked, depth):
        """One object level: scalar leaves collect into QFormLayouts, nested
        objects/arrays become CollapsibleSections, in sorted key order."""
        form = None
        for key, prop in sorted(node["properties"].items()):
            if key.startswith("_"):
                continue
            if key not in value:
                continue  # schema-optional leaf absent here (e.g. era_unlock_round on later tiers)
            prop = self._deref(prop)
            kind = prop.get("type")
            if kind in ("object", "array"):
                form = None
                section = CollapsibleSection(
                    key, prop.get("description", ""), expanded=depth == 0
                )
                if kind == "object":
                    self._build_object(
                        prop, value[key], path + (key,),
                        section.content_layout, locked, depth + 1,
                    )
                else:
                    self._build_array(
                        prop, value[key], path + (key,),
                        section.content_layout, locked, depth + 1,
                    )
                parent_layout.addWidget(section)
            else:
                if form is None:
                    form = QFormLayout()
                    parent_layout.addLayout(form)
                self._add_leaf_row(form, key, prop, value[key], path + (key,), locked)

    def _build_array(self, node, items, path, parent_layout, locked, depth):
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
                    section.content_layout, locked, depth + 1,
                )
                parent_layout.addWidget(section)
        else:
            form = QFormLayout()
            parent_layout.addLayout(form)
            for i, item in enumerate(items):
                self._add_leaf_row(
                    form, f"[{i}]", item_schema, item, path + (str(i),), locked
                )

    def _add_leaf_row(self, form, label, prop, value, path, locked):
        widget = self._make_widget(path, prop, value)
        widget.setToolTip(prop.get("description", ""))
        widget.setEnabled(not locked)
        form.addRow(label, widget)
        self._widgets["/".join(path)] = widget

    # -- widget per schema type: invalid input unrepresentable (ED-30) ------

    def _make_widget(self, path, prop, value):
        key = "/".join(path)
        if "enum" in prop:
            widget = QComboBox()
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
            widget = QSpinBox()
            widget.setRange(int(prop.get("minimum", -(2**31))),
                            int(prop.get("maximum", 2**31 - 1)))
            widget.setValue(value)
            widget.valueChanged.connect(lambda v, k=key: self._commit(k, int(v)))
        elif prop.get("type") == "number":
            widget = QDoubleSpinBox()
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

    # -- the one write path (ED-31) ------------------------------------------

    def _value_at(self, key):
        node = self._doc
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
        data_io.write_validated(
            self._doc,
            locks.balancing_path(self.domain, self._data_dir),
            locks.schema_path(self.domain, self._data_dir),
        )
