"""TimelinePanel (TimelinePLAN T5) — the right-pane form shown while the
"Timeline" leaf (selector -> buildings -> Timeline) is selected: a single
document (``data/balancing/progression.json``), reached the selection-driven
way (ED-3), sibling of Screens/Theme/Cutscenes/Tutorial/Strings — see that
family's shape in ``editor/panels/CLAUDE.md``.

Shows the whole authored building-unlock schedule at once: a graph strip
(computed best-case round position per player village-level, via
``editor.timeline_curve`` — an explicit UPPER BOUND, never a real
playthrough's timing), then one row per authored village_level with its
offer slots (empty squares a building/tier card gets dragged into), and a
browse list of every building type's cards to drag from.

Edits are STAGED, not written immediately — the ``tutorial_panel.py``/
``game_theme.py`` pattern: every drag/clear/add/remove mutates an in-memory
doc via the pure ``editor.timeline_ops`` helper + a dirty flag; ONE "Save
Timeline" button (enabled only while dirty) is the sole
``timeline_ops.save_progression`` (``write_validated``) call site.

Drag-and-drop is genuinely new ground in this editor (no prior QDrag/
QMimeData usage anywhere in ``editor/``) — a custom MIME type carries
``"<kind>|<building_type>|<tier_index>"``. Dropping onto an occupied slot
replaces it unconditionally (the confirmed UX requirement, no confirm
dialog — the palette's "click a new brush, it replaces the armed one"
precedent). An already-placed browse card is disabled (never a drag
source) rather than allowing a duplicate placement that would only surface
as a Save-time uniqueness error.

Card icons come through the SAME injected icon-provider pattern
``editor/panels/palette.py`` uses (``viewport.slot_qimage`` — a real
engine-resolved frame, ED-22-clean, never hand-drawn art).
"""
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor import timeline_curve, timeline_ops
from editor.panels.balancing import _NoWheelSpinBox

REPO = Path(__file__).resolve().parents[2]

_MIME_TYPE = "application/x-htbh-timeline-card"
_CARD_SIZE = 48
_DEFAULT_VIEW_MAX_ROUND = 50


def _encode_card(kind, building_type, tier_index):
    return f"{kind}|{building_type}|{tier_index}".encode("utf-8")


def _decode_card(data):
    kind, building_type, tier_index = bytes(data).decode("utf-8").split("|")
    return kind, building_type, int(tier_index)


class _CardIcon(QLabel):
    """A single card's icon+label, shared shape between a browse-list card
    and a filled offer slot. Not itself interactive — the owning widget
    (`_BrowseCard` / `_SlotWidget`) handles clicks/drag/drop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_CARD_SIZE, _CARD_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.Box)

    def set_empty(self):
        self.setPixmap(QPixmap())
        self.setText("")
        self.setStyleSheet(
            "border: 1px dashed gray; background: transparent;")

    def set_image(self, image, badge_text=""):
        self.setStyleSheet("border: 1px solid gray;")
        if image is not None:
            self.setPixmap(
                QPixmap.fromImage(image).scaled(
                    _CARD_SIZE, _CARD_SIZE, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.setPixmap(QPixmap())
        self.setText(badge_text)


class _BrowseCard(QWidget):
    """One draggable card in the browse list: a building type's unlock card
    (tier_index 0) or one of its tier-upgrade cards (tier_index 1/2)."""

    def __init__(self, panel, building_type, tier_index, name, slot_key, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.kind = "unlock" if tier_index == 0 else "tier"
        self.building_type = building_type
        self.tier_index = tier_index
        self.slot_key = slot_key
        self._drag_start = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.icon = _CardIcon(self)
        self.icon.set_empty()
        layout.addWidget(self.icon)
        badge = "NEW" if self.kind == "unlock" else f"T{tier_index + 1}"
        caption = QLabel(f"{badge} {name}", self)
        caption.setWordWrap(True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)

    def refresh_icon(self):
        image = self._panel.icon_image(self.slot_key)
        badge = "NEW" if self.kind == "unlock" else f"T{self.tier_index + 1}"
        self.icon.set_image(image, badge)

    def set_placed(self, placed):
        self.setEnabled(not placed)  # a disabled widget cannot start a drag
        self.setToolTip(
            "Already placed on the Timeline — clear its slot first"
            if placed else "")

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
        mime.setData(_MIME_TYPE, _encode_card(
            self.kind, self.building_type, self.tier_index))
        drag.setMimeData(mime)
        pixmap = self.icon.pixmap()
        if pixmap is not None and not pixmap.isNull():
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(_CARD_SIZE // 2, _CARD_SIZE // 2))
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start = None


class _SlotWidget(QWidget):
    """One offer-slot drop target on a level row: an empty dashed square, or
    a filled card with a small clear ("x") button."""

    changed = Signal()

    def __init__(self, panel, village_level, slot_index, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.village_level = village_level
        self.slot_index = slot_index
        self.setAcceptDrops(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.icon = _CardIcon(self)
        outer.addWidget(self.icon)
        self._clear_btn = QToolButton(self)
        self._clear_btn.setText("x")
        self._clear_btn.setToolTip("Clear this slot")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        self._clear_btn.setVisible(False)
        outer.addWidget(self._clear_btn)

        self.set_assignment(None)

    def set_assignment(self, assignment):
        self._assignment = assignment
        if assignment is None:
            self.icon.set_empty()
            self._clear_btn.setVisible(False)
            self.setToolTip("Drop a building or tier card here")
            return
        catalog_entry = self._panel.catalog_tier(
            assignment["building_type"], assignment["tier_index"])
        slot_key = catalog_entry["slot"] if catalog_entry else None
        name = catalog_entry["name"] if catalog_entry else assignment["building_type"]
        badge = "NEW" if assignment["kind"] == "unlock" else \
            f"T{assignment['tier_index'] + 1}"
        image = self._panel.icon_image(slot_key) if slot_key else None
        self.icon.set_image(image, badge)
        self._clear_btn.setVisible(True)
        self.setToolTip(f"{badge} {name}")

    def _on_clear_clicked(self):
        self._panel.clear_slot(self.village_level, self.slot_index)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(_MIME_TYPE):
            return
        kind, building_type, tier_index = _decode_card(
            event.mimeData().data(_MIME_TYPE))
        self._panel.assign_slot(
            self.village_level, self.slot_index, kind, building_type, tier_index)
        event.acceptProposedAction()


class _LevelRow(QWidget):
    """One village_level's slot strip: a header ("Lv N ~round R"), its
    offer-slot squares, +/- to append/remove a trailing slot, and a
    "Remove level" button."""

    def __init__(self, panel, village_level, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.village_level = village_level

        outer = QVBoxLayout(self)
        header_row = QHBoxLayout()
        self._header = QLabel(self)
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        remove_level_btn = QPushButton("Remove Level", self)
        remove_level_btn.clicked.connect(
            lambda: panel.remove_level(self.village_level))
        header_row.addWidget(remove_level_btn)
        outer.addLayout(header_row)

        self._slots_row = QHBoxLayout()
        outer.addLayout(self._slots_row)

        buttons_row = QHBoxLayout()
        add_slot_btn = QPushButton("+ Slot", self)
        add_slot_btn.clicked.connect(lambda: panel.add_slot(self.village_level))
        remove_slot_btn = QPushButton("- Slot", self)
        remove_slot_btn.clicked.connect(
            lambda: panel.remove_last_slot(self.village_level))
        buttons_row.addWidget(add_slot_btn)
        buttons_row.addWidget(remove_slot_btn)
        buttons_row.addStretch(1)
        outer.addLayout(buttons_row)

        line = QFrame(self)
        line.setFrameShape(QFrame.Shape.HLine)
        outer.addWidget(line)

        self._slot_widgets = []
        self.set_level(village_level, [])

    def set_level(self, village_level, offer_slots):
        self.village_level = village_level
        round_num = self._panel.round_for_level(village_level)
        label = f"Lv {village_level}"
        if round_num is not None:
            label += f" (~round {round_num})"
        self._header.setText(label)

        while self._slots_row.count():
            item = self._slots_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._slot_widgets = []
        for slot_index, slot in enumerate(offer_slots):
            widget = _SlotWidget(self._panel, village_level, slot_index, self)
            widget.set_assignment(slot["assignment"])
            self._slots_row.addWidget(widget)
            self._slot_widgets.append(widget)
        self._slots_row.addStretch(1)


class TimelinePanel(QWidget):
    saved = Signal()

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._doc = None
        self._dirty = False
        self._icon_provider = None
        self._catalog = []
        self._catalog_by_key = {}
        self._level_to_round = {}
        self._row_widgets = {}   # village_level -> _LevelRow
        self._browse_cards = []  # every _BrowseCard, for refresh_icon/set_placed

        outer = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.save_button = QPushButton("Save Timeline", self)
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self._on_save)
        toolbar.addWidget(self.save_button)
        toolbar.addSpacing(16)
        toolbar.addWidget(QLabel("Add level:", self))
        self._add_level_spin = _NoWheelSpinBox(self)
        self._add_level_spin.setRange(1, 1000)
        self._add_level_spin.setValue(1)
        toolbar.addWidget(self._add_level_spin)
        add_level_btn = QPushButton("+ Add Level", self)
        add_level_btn.clicked.connect(
            lambda: self.add_level(self._add_level_spin.value()))
        toolbar.addWidget(add_level_btn)
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("View max round:", self))
        self._view_max_spin = _NoWheelSpinBox(self)
        self._view_max_spin.setRange(10, 1000)
        self._view_max_spin.setValue(_DEFAULT_VIEW_MAX_ROUND)
        self._view_max_spin.valueChanged.connect(self._on_view_max_changed)
        toolbar.addWidget(self._view_max_spin)
        outer.addLayout(toolbar)

        self._graph = _TimelineGraph(self)
        outer.addWidget(self._graph)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._browse_scroll = QScrollArea(splitter)
        self._browse_scroll.setWidgetResizable(True)
        self._browse_content = QWidget()
        self._browse_layout = QVBoxLayout(self._browse_content)
        self._browse_scroll.setWidget(self._browse_content)
        splitter.addWidget(self._browse_scroll)

        self._rows_scroll = QScrollArea(splitter)
        self._rows_scroll.setWidgetResizable(True)
        self._rows_content = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_content)
        self._rows_layout.addStretch(1)
        self._rows_scroll.setWidget(self._rows_content)
        splitter.addWidget(self._rows_scroll)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        outer.addWidget(splitter, 1)

        self.set_timeline()

    # -- selection drives content (ED-3) -------------------------------------

    def set_timeline(self):
        """(Re)load progression.json + the building catalog fresh from disk,
        recompute the best-case curve (independent of progression.json's own
        content — it only depends on core/enemies balancing, so it needs no
        recompute on later slot edits) and rebuild the form. Called on entry
        (the "Timeline" leaf's selection handler) and by __init__.

        Editor-side graceful degrade (E-37): a missing/invalid file shows a
        placeholder instead of raising out of a constructor/Qt slot."""
        try:
            self._doc = timeline_ops.load_progression(self._data_dir)
            self._catalog = timeline_ops.load_building_catalog(self._data_dir)
        except Exception:
            self._doc = None
            self._catalog = []
            self._show_unavailable()
            return
        self._catalog_by_key = {
            (entry["building_type"], tier["tier_index"]): tier
            for entry in self._catalog for tier in entry["tiers"]
        }
        self._dirty = False
        self._recompute_curve()
        self._rebuild_browse_list()
        self._rebuild_rows()
        self.save_button.setEnabled(False)

    def _show_unavailable(self):
        placeholder = QLabel(
            "data/balancing/progression.json or buildings.json is missing "
            "or invalid — nothing to edit here.", self)
        placeholder.setWordWrap(True)
        self._rows_layout.addWidget(placeholder)
        self.save_button.setEnabled(False)

    def catalog_tier(self, building_type, tier_index):
        return self._catalog_by_key.get((building_type, tier_index))

    # -- icon provider (ED-22: real engine frames, never hand-drawn) --------

    def set_icon_provider(self, provider):
        """provider(slot_key) -> QImage of the engine-resolved idle frame."""
        self._icon_provider = provider
        self.refresh_icons()

    def icon_image(self, slot_key):
        if self._icon_provider is None or slot_key is None:
            return None
        return self._icon_provider(slot_key)

    def refresh_icons(self):
        for card in self._browse_cards:
            card.refresh_icon()
        for row in self._row_widgets.values():
            for widget in row._slot_widgets:
                widget.set_assignment(widget._assignment)

    # -- best-case curve (editor.timeline_curve, D7) -------------------------

    def _recompute_curve(self):
        try:
            core, enemies = timeline_curve.load_curve_balance(self._data_dir)
        except Exception:
            self._level_to_round = {}
            return
        view_max = self._view_max_spin.value()
        cumulative, level_to_round = timeline_curve.best_case_curve(
            core, enemies, 0, view_max, max_levels=200)
        self._level_to_round = level_to_round
        self._graph.set_curve(cumulative, level_to_round, view_max)

    def _on_view_max_changed(self, _value):
        if self._doc is None:
            return
        self._recompute_curve()
        for row in self._row_widgets.values():
            row.set_level(row.village_level, self._offer_slots(row.village_level))

    def round_for_level(self, village_level):
        return self._level_to_round.get(village_level)

    # -- browse list ----------------------------------------------------------

    def _rebuild_browse_list(self):
        while self._browse_layout.count():
            item = self._browse_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._browse_cards = []
        for entry in self._catalog:
            header = QLabel(entry["label"], self)
            header.setStyleSheet("font-weight: bold;")
            self._browse_layout.addWidget(header)
            cards_row = QHBoxLayout()
            for tier in entry["tiers"]:
                card = _BrowseCard(
                    self, entry["building_type"], tier["tier_index"],
                    tier["name"], tier["slot"], self._browse_content)
                cards_row.addWidget(card)
                self._browse_cards.append(card)
            self._browse_layout.addLayout(cards_row)
        self._browse_layout.addStretch(1)
        self._refresh_placed_state()
        self.refresh_icons()

    def _refresh_placed_state(self):
        placed = set(timeline_ops.placements(self._doc)) if self._doc else set()
        for card in self._browse_cards:
            card.set_placed((card.building_type, card.tier_index) in placed)

    # -- level rows -------------------------------------------------------------

    def _offer_slots(self, village_level):
        for level in self._doc["Timeline"]["levels"]:
            if level["village_level"] == village_level:
                return level["offer_slots"]
        return []

    def _rebuild_rows(self):
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._row_widgets = {}
        levels = sorted(
            self._doc["Timeline"]["levels"], key=lambda lvl: lvl["village_level"])
        for level in levels:
            row = _LevelRow(self, level["village_level"], self._rows_content)
            row.set_level(level["village_level"], level["offer_slots"])
            self._rows_layout.addWidget(row)
            self._row_widgets[level["village_level"]] = row
        self._rows_layout.addStretch(1)

    # -- staged edits (every mutation goes through editor.timeline_ops) ------

    def add_level(self, village_level):
        if self._doc is None:
            return
        timeline_ops.add_level(self._doc, village_level)
        self._rebuild_rows()
        self._mark_dirty()

    def remove_level(self, village_level):
        if self._doc is None:
            return
        timeline_ops.remove_level(self._doc, village_level)
        self._rebuild_rows()
        self._refresh_placed_state()
        self._mark_dirty()

    def add_slot(self, village_level):
        if self._doc is None:
            return
        timeline_ops.add_slot(self._doc, village_level)
        self._row_widgets[village_level].set_level(
            village_level, self._offer_slots(village_level))
        self.refresh_icons()
        self._mark_dirty()

    def remove_last_slot(self, village_level):
        if self._doc is None:
            return
        slots = self._offer_slots(village_level)
        if not slots:
            return
        timeline_ops.remove_slot(self._doc, village_level, len(slots) - 1)
        self._row_widgets[village_level].set_level(
            village_level, self._offer_slots(village_level))
        self._refresh_placed_state()
        self._mark_dirty()

    def assign_slot(self, village_level, slot_index, kind, building_type, tier_index):
        if self._doc is None:
            return
        timeline_ops.assign_slot(
            self._doc, village_level, slot_index, kind, building_type, tier_index)
        self._row_widgets[village_level].set_level(
            village_level, self._offer_slots(village_level))
        self._refresh_placed_state()
        self.refresh_icons()
        self._mark_dirty()

    def clear_slot(self, village_level, slot_index):
        if self._doc is None:
            return
        timeline_ops.clear_slot(self._doc, village_level, slot_index)
        self._row_widgets[village_level].set_level(
            village_level, self._offer_slots(village_level))
        self._refresh_placed_state()
        self._mark_dirty()

    def _mark_dirty(self):
        self._dirty = True
        self.save_button.setEnabled(True)

    # -- save: the ONE write path (ED-31) -------------------------------------

    def _on_save(self):
        if not self._dirty or self._doc is None:
            return
        try:
            timeline_ops.save_progression(self._doc, self._data_dir)
        except ValueError as exc:
            self._header_error(str(exc))
            return
        self._dirty = False
        self.save_button.setEnabled(False)
        self.saved.emit()

    def _header_error(self, message):
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.warning(self, "Save Timeline", message)


class _TimelineGraph(QWidget):
    """The round-axis strip: tick marks + labels at each village_level's
    computed best-case round, the raw cumulative-XP curve line, and an
    always-visible best-case/upper-bound legend caption."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(120)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._cumulative = {}
        self._level_to_round = {}
        self._view_max = _DEFAULT_VIEW_MAX_ROUND

    def set_curve(self, cumulative, level_to_round, view_max):
        self._cumulative = cumulative
        self._level_to_round = level_to_round
        self._view_max = max(1, view_max)
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter):
        w, h = self.width(), self.height()
        margin = 24
        axis_y = h - margin
        painter.setPen(QPen(Qt.GlobalColor.gray))
        painter.drawText(4, 14, "Best-case / upper-bound curve — real XP "
                                 "depends on the player's kill rate")
        painter.drawLine(margin, axis_y, w - margin, axis_y)

        def x_for_round(round_num):
            frac = round_num / self._view_max if self._view_max else 0
            return int(margin + frac * (w - 2 * margin))

        values = [self._cumulative[r] for r in self._cumulative
                  if r <= self._view_max]
        max_xp = max(values) if values else 1

        # cumulative-XP curve line
        points = sorted(
            (r, xp) for r, xp in self._cumulative.items() if r <= self._view_max)
        painter.setPen(QPen(Qt.GlobalColor.cyan))
        prev = None
        for round_num, xp in points:
            x = x_for_round(round_num)
            y = int(axis_y - (xp / max_xp) * (axis_y - 20)) if max_xp else axis_y
            if prev is not None:
                painter.drawLine(prev[0], prev[1], x, y)
            prev = (x, y)

        # level tick marks + labels
        painter.setPen(QPen(Qt.GlobalColor.white))
        for level, round_num in sorted(self._level_to_round.items()):
            if round_num is None or round_num > self._view_max:
                continue
            x = x_for_round(round_num)
            painter.drawLine(x, axis_y - 4, x, axis_y + 4)
            painter.drawText(x - 20, axis_y + 18, f"Lv {level} ~r{round_num}")
