"""AD-3: the generic "Add new X" form, rendered entirely from ONE form spec
(`data/agent_forms/<id>.json`, already schema-validated by
`agent_forms.load_form_specs`). No form is hardcoded — a new spec on disk is a
new dialog, no editor code.

Two rules shaped this module:

- **The free-text description box is built in, not a spec field** (AD plan §3):
  every form gets it for free, it carries no `key`, and it is the fallback slug
  source for the auto branch name when the spec's `slug_field` is empty.
- **Spinbox ranges come from the spec** (`minimum`/`maximum`, schema-REQUIRED on
  numeric fields), so out-of-range input is *unrepresentable* rather than merely
  rejected (ED-30) — the same bargain the balancing panel strikes with its
  schema. The three `_NoWheel*` widgets are imported from
  `editor.panels.balancing` (their home; a wheel over them can never silently
  nudge a value), never re-implemented here.

**Import direction (deliberate):** this module imports `editor.spawnclaude` at
the top; `spawnclaude`'s launcher imports `AgentFormDialog` LAZILY inside
`_open_form`. That breaks what would otherwise be a cycle (launcher → form
dialog → dispatch) and keeps `spawnclaude`'s pure builders importable without
dragging the whole Qt form in.
"""
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QVBoxLayout,
)

from editor import agent_forms, spawnclaude
from editor.panels.balancing import (
    _NoWheelComboBox,
    _NoWheelDoubleSpinBox,
    _NoWheelSpinBox,
)

REPO = Path(__file__).resolve().parents[1]

FREE_TEXT_LABEL = "Describe it in your own words"
FREE_TEXT_PLACEHOLDER = (
    "What should it do, how should it feel, anything the fields below don't "
    "capture. The agent reads this first."
)

# Types whose widget can be empty — the only ones that can gate Dispatch (§1.4:
# a checkbox and a spinbox always hold a valid value).
_EMPTYABLE = ("string", "text", "enum")


def _make_widget(field):
    """(widget, getter, change_signal) for one spec field.

    The ONE `field["type"]` switch in the form stack — nothing else may branch
    on it. `getter` is a zero-arg callable returning the JSON-safe value;
    `change_signal` is the signal that gates Dispatch (None for the types that
    cannot be empty). Unknown type → ValueError naming the key (mirrors
    `panels/balancing.py::_make_widget`'s final `else: raise`).
    """
    ftype = field["type"]
    default = field.get("default")
    if ftype == "string":
        widget = QLineEdit()
        if default is not None:
            widget.setText(str(default))
        if field.get("placeholder"):
            widget.setPlaceholderText(field["placeholder"])
        getter = lambda w=widget: w.text().strip()
        change = widget.textChanged
    elif ftype == "text":
        widget = QPlainTextEdit()
        if default is not None:
            widget.setPlainText(str(default))
        if field.get("placeholder"):
            widget.setPlaceholderText(field["placeholder"])
        getter = lambda w=widget: w.toPlainText().strip()
        change = widget.textChanged
    elif ftype == "boolean":
        widget = QCheckBox()
        widget.setChecked(bool(default))
        getter = lambda w=widget: bool(w.isChecked())
        change = None
    elif ftype == "integer":
        widget = _NoWheelSpinBox()
        widget.setRange(int(field["minimum"]), int(field["maximum"]))  # ED-30
        widget.setValue(int(default if default is not None else field["minimum"]))
        getter = lambda w=widget: int(w.value())
        change = None
    elif ftype == "number":
        widget = _NoWheelDoubleSpinBox()
        widget.setRange(float(field["minimum"]), float(field["maximum"]))  # ED-30
        widget.setDecimals(4)  # balancing-panel idiom
        widget.setSingleStep(0.1)
        widget.setValue(
            float(default if default is not None else field["minimum"]))
        getter = lambda w=widget: float(w.value())
        change = None
    elif ftype == "enum":
        widget = _NoWheelComboBox()
        for option in field["options"]:
            widget.addItem(str(option), option)  # currentData() → the real value
        if default is not None:
            index = widget.findData(default)
            if index >= 0:
                widget.setCurrentIndex(index)
        getter = lambda w=widget: w.currentData()
        change = widget.currentIndexChanged  # enum is in _EMPTYABLE: it re-gates
    else:
        raise ValueError(f"{field['key']}: no widget for field type {ftype!r}")
    widget.setToolTip(field["description"])  # schema-required on every field
    return widget, getter, change


class AgentFormDialog(QDialog):
    """One form spec → one dialog. Accepting it writes a schema-valid handoff
    and dispatches a `claude` terminal on `/dispatch <relpath>`."""

    def __init__(self, spec, data_dir=None, repo=None, parent=None, detach=None):
        super().__init__(parent)
        version = spec.get("schema_version")
        if version != agent_forms.SCHEMA_VERSION:
            raise ValueError(
                f"form spec {spec.get('id')!r}: unsupported schema_version "
                f"{version!r} (this editor renders version "
                f"{agent_forms.SCHEMA_VERSION})")
        self._spec = spec
        self._data_dir = data_dir
        self._repo = Path(repo) if repo is not None else REPO
        self._detach = detach  # None -> dispatch() uses run_controls.start_detached
        self._widgets = {}
        self._getters = {}
        self._branch_user_edited = False

        self.setWindowTitle(spec["title"])
        layout = QVBoxLayout(self)

        heading = QLabel(spec["title"])
        heading.setStyleSheet("font-weight: bold;")
        layout.addWidget(heading)
        description = QLabel(spec["description"])
        description.setWordWrap(True)
        layout.addWidget(description)

        # Built-in, spec-free: every form gets a free-text box (plan §3).
        layout.addWidget(QLabel(FREE_TEXT_LABEL))
        self._free_text = QPlainTextEdit()
        self._free_text.setPlaceholderText(FREE_TEXT_PLACEHOLDER)
        layout.addWidget(self._free_text)

        layout.addWidget(self._build_fields(spec))
        layout.addWidget(self._build_git_group(spec))

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        layout.addWidget(self._hint)

        buttons = QDialogButtonBox()
        self._dispatch_button = buttons.addButton(
            "Dispatch", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_dispatch)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Both refreshes run once here — after defaults are seeded and the
        # button exists — so a spec whose required field has a default opens
        # dispatchable, with the branch box already slugged.
        self._free_text.textChanged.connect(self._refresh_branch_name)
        self._refresh_branch_name()
        self._refresh_dispatch_enabled()

    # -- construction ------------------------------------------------------

    def _build_fields(self, spec):
        box = QGroupBox("Details")
        form = QFormLayout(box)
        slug_key = spec.get("slug_field", "name")
        for field in spec["fields"]:
            key = field["key"]
            widget, getter, change = _make_widget(field)
            self._widgets[key] = widget
            self._getters[key] = getter
            label = field["label"] + (" *" if field.get("required") else "")
            form.addRow(label, widget)
            if change is not None:
                if field.get("required"):
                    change.connect(self._refresh_dispatch_enabled)
                if key == slug_key:
                    change.connect(self._refresh_branch_name)
        return box

    def _build_git_group(self, spec):
        box = QGroupBox("Git")
        layout = QVBoxLayout(box)
        self._git_group = QButtonGroup(self)
        self._branch_radio = QRadioButton(
            "New branch off Development (ends with a PR)")
        self._current_radio = QRadioButton("Work on current branch")
        for radio in (self._branch_radio, self._current_radio):
            self._git_group.addButton(radio)
            layout.addWidget(radio)
        branch_mode = spec["git_default"] == "branch"
        (self._branch_radio if branch_mode else self._current_radio).setChecked(True)

        self._branch_edit = QLineEdit()
        self._branch_edit.setToolTip(
            "Auto-named from the form; edit it and the auto-naming stops.")
        self._branch_edit.setEnabled(branch_mode)  # only meaningful in branch mode
        # textEdited fires on USER input only — setText() does not emit it, so
        # the auto-refresh below can never flag itself as a user edit.
        self._branch_edit.textEdited.connect(self._on_branch_edited)
        self._branch_radio.toggled.connect(self._branch_edit.setEnabled)
        layout.addWidget(QLabel("Branch name"))
        layout.addWidget(self._branch_edit)
        return box

    # -- state -------------------------------------------------------------

    def values(self):
        """{field_key: value} for every spec field. Empty string/text fields are
        OMITTED rather than written as "" — the target skill reads this payload
        and an absent key is cleaner than an empty one."""
        out = {}
        for field in self._spec["fields"]:
            key = field["key"]
            value = self._getters[key]()
            if field["type"] in ("string", "text") and not value:
                continue
            out[key] = value
        return out

    def free_text(self):
        return self._free_text.toPlainText().strip()

    def git_mode(self):
        return "branch" if self._branch_radio.isChecked() else "current"

    def branch_name(self):
        return self._branch_edit.text().strip()

    def missing_required(self):
        """Labels of the required fields that are still empty. Boolean/integer/
        number fields can never be empty, so they can never block Dispatch."""
        missing = []
        for field in self._spec["fields"]:
            if not field.get("required") or field["type"] not in _EMPTYABLE:
                continue
            value = self._getters[field["key"]]()
            if value is None or value == "":
                missing.append(field["label"])
        return missing

    # -- slots -------------------------------------------------------------

    def _on_branch_edited(self, _text):
        self._branch_user_edited = True

    def _refresh_branch_name(self):
        if self._branch_user_edited:
            return
        self._branch_edit.setText(agent_forms.default_branch_name(
            self._spec, self.values(), self.free_text()))

    def _refresh_dispatch_enabled(self):
        missing = self.missing_required()
        self._dispatch_button.setEnabled(not missing)
        self._hint.setText(
            "" if not missing else "Still needed: " + ", ".join(missing))

    def _on_dispatch(self):
        git_mode = self.git_mode()
        branch = self.branch_name() if git_mode == "branch" else None
        try:
            payload = agent_forms.build_payload(
                self._spec, self.values(), self.free_text(), git_mode, branch,
                repo=self._repo)
            path = agent_forms.write_handoff(payload, repo=self._repo,
                                             data_dir=self._data_dir)
            spawnclaude.dispatch(
                handoff=agent_forms.handoff_relpath(path, self._repo),
                repo=self._repo, detach=self._detach)
        except Exception as exc:  # validation, disk, launch — the designer sees it
            QMessageBox.critical(self, "Dispatch failed", str(exc))
            return  # dialog stays open so the input isn't lost
        self.accept()
