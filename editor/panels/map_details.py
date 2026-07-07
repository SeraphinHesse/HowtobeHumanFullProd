"""MapDetailsPanel (ED-20 lifecycle, D-21/D-22) — the right-pane panel
shown while a map node is selected (the import DetailsPanel's sibling in
a QStackedWidget). Metadata (id read-only, display name editable and
undoable, dims fixed at creation) + New / Duplicate / Save / Set Active
and a dirty indicator driven by the session's undo-stack clean state.

Buttons drive the MapSession directly; MainWindow stays in sync through
the session's map_opened / active_changed signals. Deleting maps is
deliberately deferred (destructive; not in the Phase 6 lifecycle).
"""
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from editor import tilemap_ops
from engine import data_io, tilemap

REPO = Path(__file__).resolve().parents[2]


class NewMapDialog(QDialog):
    """id / display name / dims for New (dims hidden for Duplicate).
    Dim bounds come from map_file.schema.json (ED-30 spirit: invalid
    input unrepresentable); id validity is re-checked on accept."""

    def __init__(self, schema, existing_ids, dims=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New map" if dims else "Duplicate map")
        self._existing = set(existing_ids)
        form = QFormLayout(self)
        self.id_edit = QLineEdit(self)
        form.addRow("Id (a-z, 0-9, _)", self.id_edit)
        self.name_edit = QLineEdit(self)
        form.addRow("Display name", self.name_edit)
        self.cols_spin = self.rows_spin = None
        if dims:
            for label, attr in (("Columns", "cols_spin"), ("Rows", "rows_spin")):
                spin = QSpinBox(self)
                spin.setMinimum(schema["properties"]["cols"]["minimum"])
                spin.setMaximum(schema["properties"]["cols"]["maximum"])
                spin.setValue(128)
                setattr(self, attr, spin)
                form.addRow(label, spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel, parent=self)
        buttons.accepted.connect(self._check_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _check_accept(self):
        map_id = self.id_edit.text().strip()
        if not re.fullmatch(r"[a-z0-9_]+", map_id or ""):
            QMessageBox.warning(self, "Invalid id",
                                "Id must be a-z, 0-9 and _ only.")
            return
        if map_id in self._existing:
            QMessageBox.warning(self, "Id taken",
                                f"A map named {map_id!r} already exists.")
            return
        if not self.name_edit.text().strip():
            self.name_edit.setText(map_id)
        self.accept()

    def values(self):
        out = [self.id_edit.text().strip(), self.name_edit.text().strip()]
        if self.cols_spin is not None:
            out += [self.cols_spin.value(), self.rows_spin.value()]
        return tuple(out)


class MapDetailsPanel(QWidget):
    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._session = None
        # MainWindow injects its Save/Discard/Cancel prompt so New/Duplicate
        # respect unsaved edits like the tree-selection path does
        self.dirty_resolver = None

        layout = QVBoxLayout(self)
        self._id_label = QLabel("—", self)
        self._dims_label = QLabel("—", self)
        self._dirty_label = QLabel("", self)
        # Non-blocking yellow warning for a map that isn't playable yet (no
        # hole / buildable / combat / spawning tile). Set Active still works.
        self._warning_label = QLabel("", self)
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet(
            "color: #7a5c00; background: #fff3bf; border: 1px solid #e0c65a;"
            " padding: 3px; border-radius: 3px;")
        self._warning_label.setVisible(False)
        self.name_edit = QLineEdit(self)
        self.name_edit.editingFinished.connect(self._on_name_edited)

        form = QFormLayout()
        form.addRow("Id", self._id_label)
        form.addRow("Display name", self.name_edit)
        form.addRow("Size", self._dims_label)
        layout.addLayout(form)
        layout.addWidget(self._dirty_label)
        layout.addWidget(self._warning_label)

        self.new_button = QPushButton("New map…", self)
        self.duplicate_button = QPushButton("Duplicate…", self)
        self.save_button = QPushButton("Save", self)
        self.set_active_button = QPushButton("Set active", self)
        for btn in (self.new_button, self.duplicate_button,
                    self.save_button, self.set_active_button):
            layout.addWidget(btn)
        layout.addStretch(1)

        self.new_button.clicked.connect(self._on_new)
        self.duplicate_button.clicked.connect(self._on_duplicate)
        self.save_button.clicked.connect(self._on_save)
        self.set_active_button.clicked.connect(self._on_set_active)

    # -- session binding -------------------------------------------------------

    def set_session(self, session):
        if self._session is session:
            self.refresh()
            return
        self._session = session
        session.undo_stack.cleanChanged.connect(lambda _clean: self.refresh())
        session.map_opened.connect(lambda _map_id: self.refresh())
        self.refresh()

    def refresh(self):
        try:
            doc = self._session.doc if self._session is not None else None
            dirty = self._session.dirty if doc is not None else False
        except RuntimeError:
            return   # undo stack mid-destruction (window teardown)
        has_doc = doc is not None
        for btn in (self.duplicate_button, self.save_button,
                    self.set_active_button):
            btn.setEnabled(has_doc)
        self.name_edit.setEnabled(has_doc)
        if not has_doc:
            self._id_label.setText("—")
            self._dims_label.setText("—")
            self._dirty_label.setText("")
            self.name_edit.setText("")
            self._warning_label.setVisible(False)
            return
        self._id_label.setText(doc.map_id)
        self._dims_label.setText(f"{doc.cols} × {doc.rows} tiles")
        if not self.name_edit.hasFocus():
            self.name_edit.setText(doc.display_name)
        self._dirty_label.setText("● unsaved changes" if dirty else "saved")
        self._refresh_warning(doc)

    def _refresh_warning(self, doc):
        missing = tilemap_ops.map_requirement_warnings(doc)
        if missing:
            self._warning_label.setText("⚠ Missing: " + ", ".join(missing))
            self._warning_label.setVisible(True)
        else:
            self._warning_label.setVisible(False)

    # -- actions ---------------------------------------------------------------

    def _on_name_edited(self):
        if self._session is not None and self._session.doc is not None:
            self._session.push_rename(self.name_edit.text().strip())
            self.refresh()

    def _schema(self):
        return data_io.load_json(tilemap.map_schema_path(self._data_dir))

    def _resolve_dirty(self):
        return self.dirty_resolver() if self.dirty_resolver is not None else True

    def _on_new(self):
        if not self._resolve_dirty():
            return
        dialog = NewMapDialog(self._schema(), self._session.map_ids(),
                              dims=True, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            map_id, name, cols, rows = dialog.values()
            self._session.create(map_id, name, cols, rows)

    def _on_duplicate(self):
        if not self._resolve_dirty():
            return
        dialog = NewMapDialog(self._schema(), self._session.map_ids(),
                              dims=False, parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            map_id, name = dialog.values()
            self._session.duplicate(map_id, name)

    def _on_save(self):
        self._session.save()
        self.refresh()

    def _on_set_active(self):
        # Warn but ALLOW (user-confirmed): the yellow warning is informational;
        # a not-yet-playable map can still be made active.
        self._session.set_active()
        self.refresh()
