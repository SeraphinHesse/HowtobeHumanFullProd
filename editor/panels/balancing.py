"""BalancingPanel (ED-30/31/32) — schema-generated form over one domain.

set_domain(d) reloads data/balancing/<d>.json fresh from disk and rebuilds
the form from data/schemas/<d>.schema.json: integer -> QSpinBox, number ->
QDoubleSpinBox (ranges from the schema's minimum/maximum, so out-of-range
input is unrepresentable, not merely rejected), enum -> QComboBox,
boolean -> QCheckBox. Each widget's tooltip carries the key's schema
description (units / x10 combat-scale hints, D-12). Underscore keys
(_lock) never appear as fields.

Every change writes the whole document through
engine.data_io.write_validated (ED-31) — validation raises before disk.
A locked domain (editor.locks) renders the form disabled with the owner
in a banner (ED-32); lock state is read at selection time. Undo via the
global QUndoStack (ED-24) is deferred to the tilemap-editor phase.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from editor import locks
from engine import data_io

REPO = Path(__file__).resolve().parents[2]


class BalancingPanel(QWidget):
    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.domain = None
        self._doc = None
        self._widgets = {}

        self._banner = QLabel()
        self._banner.setStyleSheet("font-weight: bold; color: #b5651d;")
        self._banner.hide()
        self._form = QFormLayout()
        layout = QVBoxLayout(self)
        layout.addWidget(self._banner)
        layout.addLayout(self._form)
        layout.addStretch(1)

    # -- selection drives content (ED-3) ------------------------------------

    def set_domain(self, domain):
        self.domain = domain
        self._doc = data_io.load_validated(
            locks.balancing_path(domain, self._data_dir),
            locks.schema_path(domain, self._data_dir),
        )
        schema = data_io.load_json(locks.schema_path(domain, self._data_dir))
        locked = locks.is_locked(domain, self._data_dir)
        self._rebuild_form(schema, locked)
        if locked:
            self._banner.setText(
                f"Locked by {locks.owner(domain, self._data_dir)} "
                f"since {locks.since(domain, self._data_dir)} — read-only"
            )
            self._banner.show()
        else:
            self._banner.hide()

    def _rebuild_form(self, schema, locked):
        while self._form.rowCount():
            self._form.removeRow(0)
        self._widgets = {}
        for key, prop in sorted(schema["properties"].items()):
            if key.startswith("_"):
                continue
            widget = self._make_widget(key, prop)
            widget.setToolTip(prop.get("description", ""))
            widget.setEnabled(not locked)
            self._form.addRow(key, widget)
            self._widgets[key] = widget

    # -- widget per schema type: invalid input unrepresentable (ED-30) ------

    def _make_widget(self, key, prop):
        value = self._doc[key]
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
            widget.setDecimals(2)
            widget.setSingleStep(0.1)
            widget.setValue(value)
            widget.valueChanged.connect(lambda v, k=key: self._commit(k, float(v)))
        else:
            raise ValueError(f"{self.domain}.{key}: no widget for schema {prop!r}")
        return widget

    # -- the one write path (ED-31) ------------------------------------------

    def _commit(self, key, value):
        self._doc[key] = value
        data_io.write_validated(
            self._doc,
            locks.balancing_path(self.domain, self._data_dir),
            locks.schema_path(self.domain, self._data_dir),
        )
