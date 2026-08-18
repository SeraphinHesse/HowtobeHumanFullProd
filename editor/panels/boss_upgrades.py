"""BossUpgradesPanel (BossUpgradeTimelinePLAN BU-5) — the right-pane form
shown while the "Boss Upgrade Timeline" leaf (selector ▸ Bosses ▸ Boss
Upgrade Timeline) is selected: a single document
(``data/balancing/boss_upgrades.json``), reached the selection-driven way
(ED-3).

It is the building Timeline panel's sibling (``panels/timeline.py``) and
copies its shape deliberately — staged edits through a pure ops module, ONE
Save button, a browse list on the left, drop targets on the right, a custom
MIME type, silent overwrite on an occupied slot (D10). Three things differ,
and each is a decision, not an accident:

* **Text-only cards (D9).** No icons, no ``slot_qimage`` provider, no art
  pipeline anywhere in this panel — a boss upgrade card has no sprite, in the
  editor or in the run.
* **The catalog is EDITABLE here.** A building card's title comes from
  ``buildings.json``; a boss upgrade's ``name``/``description``/``params``
  are this document's own designer content, so every browse card carries
  inline fields that stage straight through
  ``boss_upgrades_ops.set_catalog_field``. Param widgets are built from the
  SCHEMA (``catalog_param_specs``) — integer params get a spin, number params
  a double spin, both ranged by the schema (ED-30), never retyped here.
* **A placed card stays draggable.** The Timeline panel DISABLES an
  already-placed browse card, because a duplicate there is a Save-time error.
  Here the roster is fixed at 12 and moving an upgrade from one milestone to
  another is the normal gesture, so a placed card is MARKED ("in milestone 2
  · slot 1") rather than disabled, and a genuine double-placement surfaces in
  the warning label under the toolbar via
  ``boss_upgrades_ops.validate_uniqueness`` (D3: warn, don't block — the
  ``timeline_ops.round_warnings`` stance).

The grid is the 4-milestone cycle (D1): milestone ``(boss_num - 1) % 4``,
three always-shown slots each (D2), plus that milestone's
``retaliation_bonus_love`` — the love a LOST bossfight there pays (D7).
"""
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor import boss_upgrades_ops
from editor.panels.balancing import (
    CollapsibleSection,
    _NoWheelDoubleSpinBox,
    _NoWheelSpinBox,
)

REPO = Path(__file__).resolve().parents[2]

_MIME_TYPE = "application/x-htbh-boss-upgrade"
_SLOT_WIDTH = 150
_SLOT_HEIGHT = 64


def _encode_upgrade(upgrade_id):
    return upgrade_id.encode("utf-8")


def _decode_upgrade(data):
    return bytes(data).decode("utf-8")


class _CatalogCard(QWidget):
    """One browse-list card: an upgrade's editable name/description/params,
    under a drag-handle header that carries the id into a milestone slot.

    The header QLabel does not accept mouse events itself, so a press on it
    propagates to this widget and starts the drag; a press inside one of the
    editors is consumed by that editor, which is what lets the same card be
    both a drag source and a form."""

    def __init__(self, panel, upgrade_id, entry, param_specs, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.upgrade_id = upgrade_id
        self._drag_start = None
        self.param_widgets = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 4, 4, 4)
        outer.setSpacing(4)

        self._header = QLabel(self)
        self._header.setWordWrap(True)
        self._header.setToolTip(
            "Drag this header into a milestone slot on the right.")
        outer.addWidget(self._header)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit(self)
        self.name_edit.setText(entry["name"])
        self.name_edit.setToolTip("Card title shown on the boss choice card.")
        self.name_edit.editingFinished.connect(
            lambda: self._commit("name", self.name_edit.text()))
        form.addRow("Name", self.name_edit)

        self.description_edit = QLineEdit(self)
        self.description_edit.setText(entry["description"])
        self.description_edit.setToolTip(
            "Card body text. A {param_name} placeholder is filled in live "
            "with that param's value, so the card always advertises the "
            "magnitude the math actually uses.")
        self.description_edit.editingFinished.connect(
            lambda: self._commit(
                "description", self.description_edit.text()))
        form.addRow("Text", self.description_edit)

        for param, spec in param_specs.items():
            widget = self._make_param_widget(param, spec, entry["params"])
            self.param_widgets[param] = widget
            form.addRow(param, widget)
        if not param_specs:
            none_label = QLabel("no tunable parameters", self)
            none_label.setStyleSheet("color: gray;")
            form.addRow("Params", none_label)
        outer.addLayout(form)

        self.placed_label = QLabel(self)
        self.placed_label.setStyleSheet("color: #808080;")
        outer.addWidget(self.placed_label)

        self.set_entry(entry)

    def _make_param_widget(self, param, spec, params):
        """A spin ranged by the SCHEMA (ED-30) — integer params get an int
        spin, number params a double spin, so an int param can never be
        staged as a float that fails validation at Save."""
        low = spec["minimum"]
        high = spec["maximum"]
        if spec["type"] == "integer":
            widget = _NoWheelSpinBox(self)
            widget.setRange(int(low if low is not None else -10 ** 6),
                            int(high if high is not None else 10 ** 6))
            widget.setValue(int(params.get(param, low or 0)))
        else:
            widget = _NoWheelDoubleSpinBox(self)
            widget.setDecimals(2)
            widget.setSingleStep(0.1)
            widget.setRange(float(low if low is not None else -10 ** 6),
                            float(high if high is not None else 10 ** 6))
            widget.setValue(float(params.get(param, low or 0.0)))
        widget.setToolTip(spec["description"])
        widget.valueChanged.connect(
            lambda value, p=param: self._commit(p, value))
        return widget

    def _commit(self, field, value):
        self._panel.set_catalog_field(self.upgrade_id, field, value)
        if field == "name":
            self._refresh_header(value)

    def set_entry(self, entry):
        """Re-seed the header from the doc (the fields themselves are only
        ever written by the designer, so they are not re-seeded here — that
        would fight whatever is being typed)."""
        self._refresh_header(entry["name"])

    def _refresh_header(self, name):
        self._header.setText(
            f"<b>{name}</b> <span style='color:#888888'>⠿ "
            f"{self.upgrade_id}</span>")

    def set_placement(self, placement):
        """``(milestone_idx, slot_idx)`` when this upgrade sits somewhere on
        the timeline, else ``None``. Marks the card — deliberately NOT
        disabling it (see the module docstring)."""
        if placement is None:
            self.placed_label.setText("not placed")
        else:
            milestone_idx, slot_idx = placement
            self.placed_label.setText(
                f"in milestone {milestone_idx + 1} · slot {slot_idx + 1}")

    # -- drag source -------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (self._drag_start is None
                or not event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._drag_start).manhattanLength() < 4:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_TYPE, _encode_upgrade(self.upgrade_id))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start = None


class _MilestoneSlot(QWidget):
    """One drop target in the 4×3 grid: an empty dashed box, or the placed
    upgrade's name with a Clear button. Dropping onto an occupied slot
    replaces it unconditionally (D10) — no confirm dialog, the building
    Timeline's ``_SlotWidget`` precedent."""

    def __init__(self, panel, milestone_idx, slot_idx, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.milestone_idx = milestone_idx
        self.slot_idx = slot_idx
        self.setAcceptDrops(True)
        self.setFixedSize(_SLOT_WIDTH, _SLOT_HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(4, 2, 4, 2)
        outer.setSpacing(2)
        self._label = QLabel(self)
        self._label.setWordWrap(True)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self._label)
        self._clear_btn = QToolButton(self)
        self._clear_btn.setText("Clear")
        self._clear_btn.setToolTip("Empty this slot")
        self._clear_btn.clicked.connect(
            lambda: self._panel.clear_slot(self.milestone_idx, self.slot_idx))
        self._clear_btn.setVisible(False)
        outer.addWidget(self._clear_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_upgrade(None, None)

    def set_upgrade(self, upgrade_id, name):
        self.upgrade_id = upgrade_id
        if upgrade_id is None:
            self._label.setText("")
            self._clear_btn.setVisible(False)
            self.setStyleSheet(
                "QWidget { border: 1px dashed gray; }"
                " QToolButton { border: none; }")
            self.setToolTip("Drop a boss upgrade card here")
            return
        self._label.setText(name or upgrade_id)
        self._clear_btn.setVisible(True)
        self.setStyleSheet(
            "QWidget { border: 1px solid gray; }"
            " QToolButton { border: none; }")
        self.setToolTip(upgrade_id)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_TYPE):
            return
        upgrade_id = _decode_upgrade(event.mimeData().data(_MIME_TYPE))
        self._panel.assign_slot(
            self.milestone_idx, self.slot_idx, upgrade_id)
        event.acceptProposedAction()


class BossUpgradesPanel(QWidget):
    saved = Signal()   # no consumer today (the game re-reads the file at its
                       # own next boot — the strings/Timeline precedent).

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._param_specs = {}
        self._retaliation_range = (0, 10000)   # replaced from the schema on load
        self._dirty = False
        self._cards = {}          # upgrade_id -> _CatalogCard
        self._slot_widgets = {}   # (milestone_idx, slot_idx) -> _MilestoneSlot
        self._retaliation_spins = {}   # milestone_idx -> _NoWheelSpinBox

        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.save_button = QPushButton("Save Boss Upgrades", self)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        toolbar.addWidget(self.save_button)
        toolbar.addStretch(1)
        outer.addLayout(toolbar)

        # Non-blocking D3 complaint (validate_uniqueness). Save is never gated
        # on it — the label is the whole enforcement.
        self.warnings_label = QLabel(self)
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet("color: #c07000;")
        self.warnings_label.setVisible(False)
        outer.addWidget(self.warnings_label)

        caption = QLabel(
            "Four authored milestones, cycling every 4th bossfight — boss 5 "
            "re-offers milestone 1's identical three cards, forever. Drag a "
            "card's header from the list on the left into a slot; dropping "
            "onto a full slot replaces what was there. Retaliation love is "
            "paid only when that bossfight is LOST.", self)
        caption_font = caption.font()
        caption_font.setItalic(True)
        caption_font.setPointSize(max(7, caption_font.pointSize() - 1))
        caption.setFont(caption_font)
        caption.setWordWrap(True)
        outer.addWidget(caption)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._browse_scroll = QScrollArea(splitter)
        self._browse_scroll.setWidgetResizable(True)
        self._browse_content = QWidget()
        self._browse_layout = QVBoxLayout(self._browse_content)
        self._browse_scroll.setWidget(self._browse_content)
        splitter.addWidget(self._browse_scroll)

        self._grid_scroll = QScrollArea(splitter)
        self._grid_scroll.setWidgetResizable(True)
        self._grid_content = QWidget()
        self._grid_layout = QVBoxLayout(self._grid_content)
        self._grid_scroll.setWidget(self._grid_content)
        splitter.addWidget(self._grid_scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self.set_boss_upgrades()

    # -- selection drives content (ED-3) -------------------------------------

    def set_boss_upgrades(self):
        """(Re)load ``boss_upgrades.json`` + its schema-derived param specs
        fresh from disk and rebuild both halves — called on entry (the "Boss
        Upgrade Timeline" leaf's selection handler) and by ``__init__``.

        Editor-side graceful degrade (E-37): a missing/invalid file shows a
        placeholder instead of raising out of a constructor/Qt slot."""
        try:
            self._doc = boss_upgrades_ops.load_boss_upgrades(self._data_dir)
            self._param_specs = boss_upgrades_ops.catalog_param_specs(
                self._data_dir)
            self._retaliation_range = boss_upgrades_ops.retaliation_bounds(
                self._data_dir)
        except Exception:   # noqa: BLE001 - a broken tree must not raise here
            self._doc = None
            self._param_specs = {}
            self._show_unavailable()
            return
        self._dirty = False
        self._rebuild_browse_list()
        self._rebuild_grid()
        self._refresh_warnings()
        self.save_button.setEnabled(False)

    def _show_unavailable(self):
        self._cards = {}
        self._slot_widgets = {}
        self._retaliation_spins = {}
        _clear_layout(self._browse_layout)
        _clear_layout(self._grid_layout)
        placeholder = QLabel(
            "data/balancing/boss_upgrades.json is missing or invalid — "
            "nothing to edit here.", self._grid_content)
        placeholder.setWordWrap(True)
        self._grid_layout.addWidget(placeholder)
        self.save_button.setEnabled(False)

    # -- browse list (the 12 catalog cards) ----------------------------------

    def _rebuild_browse_list(self):
        _clear_layout(self._browse_layout)
        self._cards = {}
        catalog = boss_upgrades_ops.catalog(self._doc)
        for upgrade_id in boss_upgrades_ops.upgrade_ids(self._doc):
            card = _CatalogCard(
                self, upgrade_id, catalog[upgrade_id],
                self._param_specs.get(upgrade_id, {}), self._browse_content)
            self._browse_layout.addWidget(card)
            sep = QFrame(self._browse_content)
            sep.setFrameShape(QFrame.Shape.HLine)
            self._browse_layout.addWidget(sep)
            self._cards[upgrade_id] = card
        self._browse_layout.addStretch(1)
        self._refresh_placed_state()

    def _refresh_placed_state(self):
        placements = boss_upgrades_ops.placements(self._doc)
        for upgrade_id, card in self._cards.items():
            card.set_placement(placements.get(upgrade_id))

    # -- the 4x3 milestone grid ----------------------------------------------

    def _rebuild_grid(self):
        _clear_layout(self._grid_layout)
        self._slot_widgets = {}
        self._retaliation_spins = {}
        section = CollapsibleSection(
            "Milestones", "The 4-bossfight cycle (D1).", expanded=True,
            parent=self._grid_content)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        for slot_idx in range(boss_upgrades_ops.SLOTS_PER_MILESTONE):
            header = QLabel(f"Slot {slot_idx + 1}", self._grid_content)
            header.setStyleSheet("font-weight: bold;")
            grid.addWidget(header, 0, slot_idx + 1)
        love_header = QLabel("Retaliation love (on loss)", self._grid_content)
        love_header.setStyleSheet("font-weight: bold;")
        grid.addWidget(
            love_header, 0, boss_upgrades_ops.SLOTS_PER_MILESTONE + 1)

        low, high = self._retaliation_range
        for milestone_idx in range(boss_upgrades_ops.MILESTONE_COUNT):
            row = milestone_idx + 1
            label = QLabel(
                f"Milestone {milestone_idx + 1}\n"
                f"(bosses {milestone_idx + 1}, "
                f"{milestone_idx + 1 + boss_upgrades_ops.MILESTONE_COUNT}, …)",
                self._grid_content)
            grid.addWidget(label, row, 0)
            for slot_idx in range(boss_upgrades_ops.SLOTS_PER_MILESTONE):
                widget = _MilestoneSlot(
                    self, milestone_idx, slot_idx, self._grid_content)
                grid.addWidget(widget, row, slot_idx + 1)
                self._slot_widgets[(milestone_idx, slot_idx)] = widget
            spin = _NoWheelSpinBox(self._grid_content)
            spin.setRange(int(low), int(high))
            # Populate, THEN connect (the balancing.py convention): seeding
            # the form must never dirty the document.
            spin.setValue(int(
                boss_upgrades_ops.retaliation_love(self._doc, milestone_idx)))
            spin.valueChanged.connect(
                lambda value, m=milestone_idx: self.set_retaliation_love(
                    m, value))
            grid.addWidget(
                spin, row, boss_upgrades_ops.SLOTS_PER_MILESTONE + 1)
            self._retaliation_spins[milestone_idx] = spin
        section.content_layout.addLayout(grid)
        self._grid_layout.addWidget(section)
        self._grid_layout.addStretch(1)
        self._refresh_slots()

    def _refresh_slots(self):
        catalog = boss_upgrades_ops.catalog(self._doc)
        for milestone_idx in range(boss_upgrades_ops.MILESTONE_COUNT):
            slots = boss_upgrades_ops.milestone_slots(self._doc, milestone_idx)
            for slot_idx, upgrade_id in enumerate(slots):
                widget = self._slot_widgets.get((milestone_idx, slot_idx))
                if widget is None:
                    continue
                name = (catalog[upgrade_id]["name"]
                        if upgrade_id in catalog else None)
                widget.set_upgrade(upgrade_id, name)

    def _refresh_warnings(self):
        duplicates = (boss_upgrades_ops.validate_uniqueness(self._doc)
                      if self._doc is not None else [])
        if duplicates:
            self.warnings_label.setText(
                "Placed in more than one milestone slot (each upgrade should "
                "appear only once across the whole timeline): "
                + ", ".join(duplicates))
        else:
            self.warnings_label.setText("")
        self.warnings_label.setVisible(bool(duplicates))

    # -- staged edits (every mutation goes through editor.boss_upgrades_ops) -

    def assign_slot(self, milestone_idx, slot_idx, upgrade_id):
        if self._doc is None:
            return
        try:
            boss_upgrades_ops.assign_slot(
                self._doc, milestone_idx, slot_idx, upgrade_id)
        except (KeyError, IndexError):
            return   # a stale drop payload must never raise out of a Qt slot
        self._refresh_slots()
        self._refresh_placed_state()
        self._refresh_warnings()
        self._mark_dirty()

    def clear_slot(self, milestone_idx, slot_idx):
        if self._doc is None:
            return
        boss_upgrades_ops.clear_slot(self._doc, milestone_idx, slot_idx)
        self._refresh_slots()
        self._refresh_placed_state()
        self._refresh_warnings()
        self._mark_dirty()

    def set_retaliation_love(self, milestone_idx, value):
        if self._doc is None:
            return
        boss_upgrades_ops.set_retaliation_love(self._doc, milestone_idx, value)
        self._mark_dirty()

    def set_catalog_field(self, upgrade_id, field, value):
        """Stage one inline catalog edit. Deliberately does NOT rebuild the
        browse card — that would destroy the widget the designer is typing in
        (the Timeline panel's ``set_level_round`` rule). Only the milestone
        slots, which display the name, are refreshed."""
        if self._doc is None:
            return
        try:
            boss_upgrades_ops.set_catalog_field(
                self._doc, upgrade_id, field, value)
        except KeyError:
            return   # never raise out of a Qt slot
        if field == "name":
            self._refresh_slots()
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self.save_button.setEnabled(True)

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if not self._dirty or self._doc is None:
            return
        try:
            boss_upgrades_ops.save_boss_upgrades(self._doc, self._data_dir)
        except Exception as exc:   # noqa: BLE001 - report, never crash the app
            QMessageBox.warning(self, "Save Boss Upgrades", str(exc))
            return
        self._dirty = False
        self.save_button.setEnabled(False)
        self.saved.emit()


def _clear_layout(layout):
    """Drop every widget/nested layout a rebuild replaces. Qt keeps a taken
    widget alive until deleteLater runs, which is why the panel's own dicts
    are reset by the caller rather than relied on here."""
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        child = item.layout()
        if child is not None:
            _clear_layout(child)
