"""AnchorsPanel (ESV-2) — the per-anchor authoring form that sits beside
the entity preview. It owns the SOLE authoritative {name: (x, y)} anchors
mapping for the previewed slot; the viewport (panels/viewport.py) is a VIEW
of it plus a live drag delta (editor/panels/CLAUDE.md "Anchor handles").
Every name in engine.assets.manifest.ANCHOR_NAMES gets a row — no name is
ever hardcoded here, so a newly declared name needs zero editor edits
(ESV-1 brief §1.1, this brief §1.2) — `depth_pivot`, the seventh, was added
without touching this file at all.

Two "nothing" states, kept apart (§1.6): a slot with a manifest entry but no
`anchors` key shows every row UNCHECKED (ticking one creates that anchor
at [0, 0], immediately draggable); a slot with NO manifest entry at all
disables every row and shows guidance instead — the schema's entry object
has no anchors-only shape to attach to, so this phase never synthesises one.

Writes go through editor.anchor_ops (write_validated, ED-31) on a checkbox
toggle or a spinbox `editingFinished` (never `valueChanged` — typing "128"
would otherwise write three times, the same reasoning as
`details.py:_on_frame_size_changed`) — never during a live drag, where the
viewport instead emits per-move deltas this panel only mirrors into the
spinboxes. No undo: this panel writes immediately, like details.py's
Save/Clear (accepted for this phase, ESV-2 brief §1.5).
"""
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from editor import anchor_ops, asset_import
from editor.panels.balancing import _NoWheelSpinBox
from engine.assets.manifest import ANCHOR_NAMES

REPO = Path(__file__).resolve().parents[2]
_BOUND = 4096   # asset_manifest.schema.json anchors[*] items minimum/maximum
_SELECTED_STYLE = "QWidget#anchorRow { border: 1px solid #ffdc50; }"


class AnchorsPanel(QWidget):
    #: -> viewport.set_anchors — every non-drag change (toggle, edit, or a
    #: full re-seed after a slot switch / manifest reload).
    mapping_changed = Signal(dict)
    #: name|None -> viewport.set_selected_anchor
    anchor_selected = Signal(object)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._slot_key = None
        self._has_entry = False
        self._loading = False
        self._selected = None
        self._mapping = {}   # {name: (x, y)} — the authoritative values

        self._guidance = QLabel(
            "Import a spritesheet for this slot first — anchors attach to "
            "an imported entry.")
        self._guidance.setWordWrap(True)

        self._checks = {}
        self._spin_x = {}
        self._spin_y = {}
        self._rows = {}

        rows_layout = QVBoxLayout()
        for name in ANCHOR_NAMES:
            row = QWidget()
            row.setObjectName("anchorRow")
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(4, 2, 4, 2)
            check = QCheckBox(name)
            spin_x = _NoWheelSpinBox()
            spin_y = _NoWheelSpinBox()
            for spin in (spin_x, spin_y):
                spin.setRange(-_BOUND, _BOUND)
                spin.setEnabled(False)
            row_layout.addWidget(check)
            row_layout.addWidget(QLabel("X:"))
            row_layout.addWidget(spin_x)
            row_layout.addWidget(QLabel("Y:"))
            row_layout.addWidget(spin_y)
            row_layout.addStretch(1)
            rows_layout.addWidget(row)

            check.toggled.connect(lambda checked, n=name: self._on_toggled(n, checked))
            spin_x.editingFinished.connect(lambda n=name: self._on_edited(n))
            spin_y.editingFinished.connect(lambda n=name: self._on_edited(n))

            self._checks[name] = check
            self._spin_x[name] = spin_x
            self._spin_y[name] = spin_y
            self._rows[name] = row

        layout = QVBoxLayout(self)
        layout.addWidget(self._guidance)
        layout.addLayout(rows_layout)
        layout.addStretch(1)

        self._refresh_enabled()

    # -- external state (MainWindow drives this from the tree selection) ----

    def set_slot(self, slot_key):
        """Re-seed the panel from the on-disk manifest for `slot_key` (None
        clears it) — the ONE place this panel reads disk, so a slot switch,
        a DetailsPanel save/clear, or any other manifest reload all funnel
        through here (§1.7)."""
        self._loading = True
        try:
            self._slot_key = slot_key
            if slot_key is None:
                self._has_entry = False
                mapping = {}
            else:
                doc = asset_import.load_manifest_doc(self._data_dir)
                entry = doc["entries"].get(slot_key)
                self._has_entry = entry is not None
                raw = (entry or {}).get("anchors") or {}
                mapping = {name: (int(raw[name][0]), int(raw[name][1]))
                          for name in ANCHOR_NAMES if name in raw}
            self._mapping = mapping
            self._selected = None
            self._apply_mapping_to_widgets(mapping)
            self._refresh_enabled()
        finally:
            self._loading = False
        self.mapping_changed.emit(dict(self._mapping))

    def reload(self):
        """Re-seed from disk for the CURRENT slot — MainWindow calls this
        from `_on_manifest_changed` so a DetailsPanel save/clear (or any
        other manifest write) leaves the panel and the handle agreeing
        with disk (§1.7)."""
        self.set_slot(self._slot_key)

    def select_anchor(self, name):
        """External sync (a viewport handle press) — no re-emit, mirrors
        ViewportPanel.set_selected_widget / ScreenDetailsPanel.select_widget."""
        if name == self._selected:
            return
        self._selected = name
        self._refresh_selection_style()

    # -- drag sync (ViewportPanel -> here, §1.7 "drag -> panel") -------------

    def on_anchor_dragged(self, name, x, y):
        """Live drag position, every move — spinboxes follow with signals
        BLOCKED (the established idiom, editor/main.py:551-552's subcategory
        combo); nothing is written to disk here."""
        if name not in self._checks:
            return
        self._mapping[name] = (x, y)
        self._loading = True
        self._spin_x[name].setValue(x)
        self._spin_y[name].setValue(y)
        self._loading = False

    def on_anchor_drag_finished(self, name, x, y):
        """ONE write per gesture, on release (§1.5's stroke-coalescing
        rule) — the viewport only emits this when the value actually
        changed, so a click-with-no-movement never reaches here."""
        self.on_anchor_dragged(name, x, y)
        if self._has_entry and self._slot_key is not None:
            anchor_ops.set_anchor(self._data_dir, self._slot_key, name, (x, y))

    # -- internals -------------------------------------------------------------

    def _apply_mapping_to_widgets(self, mapping):
        for name in ANCHOR_NAMES:
            check = self._checks[name]
            spin_x, spin_y = self._spin_x[name], self._spin_y[name]
            check.blockSignals(True)
            spin_x.blockSignals(True)
            spin_y.blockSignals(True)
            present = name in mapping
            check.setChecked(present)
            x, y = mapping.get(name, (0, 0))
            spin_x.setValue(x)
            spin_y.setValue(y)
            check.blockSignals(False)
            spin_x.blockSignals(False)
            spin_y.blockSignals(False)

    def _refresh_enabled(self):
        show_guidance = self._slot_key is not None and not self._has_entry
        self._guidance.setVisible(show_guidance)
        for name in ANCHOR_NAMES:
            self._checks[name].setEnabled(self._has_entry)
            present = name in self._mapping
            self._spin_x[name].setEnabled(self._has_entry and present)
            self._spin_y[name].setEnabled(self._has_entry and present)
        self._refresh_selection_style()

    def _refresh_selection_style(self):
        for name, row in self._rows.items():
            row.setStyleSheet(_SELECTED_STYLE if name == self._selected else "")

    def _select(self, name):
        if name == self._selected:
            return
        self._selected = name
        self._refresh_selection_style()
        self.anchor_selected.emit(name)

    def _on_toggled(self, name, checked):
        if self._loading or not self._has_entry or self._slot_key is None:
            return
        if checked:
            anchor_ops.set_anchor(self._data_dir, self._slot_key, name, (0, 0))
            self._mapping[name] = (0, 0)
        else:
            anchor_ops.clear_anchor(self._data_dir, self._slot_key, name)
            self._mapping.pop(name, None)
        self._loading = True
        x, y = self._mapping.get(name, (0, 0))
        self._spin_x[name].setValue(x)
        self._spin_y[name].setValue(y)
        self._spin_x[name].setEnabled(checked)
        self._spin_y[name].setEnabled(checked)
        self._loading = False
        if checked:
            self._select(name)
        elif self._selected == name:
            self._selected = None
            self._refresh_selection_style()
        self.mapping_changed.emit(dict(self._mapping))

    def _on_edited(self, name):
        if self._loading or not self._has_entry or name not in self._mapping:
            return
        self._select(name)
        x, y = self._spin_x[name].value(), self._spin_y[name].value()
        if (x, y) == self._mapping[name]:
            return
        anchor_ops.set_anchor(self._data_dir, self._slot_key, name, (x, y))
        self._mapping[name] = (x, y)
        self.mapping_changed.emit(dict(self._mapping))
