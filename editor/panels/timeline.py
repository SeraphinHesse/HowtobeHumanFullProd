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

**Card labels (user-confirmed, post-live-test)**: a card/slot shows the
building's REAL tier name (e.g. "Stone Thrower"), auto-derived from
``buildings.json`` — never a manually-typed rename, and never the old bare
"NEW"/"T2" kind badge (both replaced by ``_caption_html``'s "name + Tier N"
two-line label, applied identically to browse cards and offer slots so the
whole panel reads consistently).
"""
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QFont, QPainter, QPalette, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
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
_CARD_ICON_SIZE = 56
_CARD_WIDTH = 84
_DEFAULT_VIEW_MAX_ROUND = 50


def _encode_card(kind, building_type, tier_index):
    return f"{kind}|{building_type}|{tier_index}".encode("utf-8")


def _decode_card(data):
    kind, building_type, tier_index = bytes(data).decode("utf-8").split("|")
    return kind, building_type, int(tier_index)


class _InfoButton(QToolButton):
    """A small round "?" button that explains ONE feature on click — a
    hover tooltip alone isn't discoverable/persistent enough for a first-time
    user (user-confirmed, post-live-test: "Add level" needed exactly this).
    Reusable for any other control this panel later turns out to need one
    for; only "Add level" uses it today."""

    def __init__(self, title, body, parent=None):
        super().__init__(parent)
        self.setText("?")
        self.setFixedSize(20, 20)
        self.setToolTip(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: QMessageBox.information(self, title, body))


def _caption_html(name, tier_index):
    """The shared two-line card label: the building's real name (bold), the
    tier number small and muted underneath. Identical on browse cards and
    offer slots (user-confirmed) — no more bare "NEW"/"T2" badge text."""
    return (f"<div align='center'><b>{name}</b><br>"
            f"<span style='font-size:8pt;color:#888888'>"
            f"Tier {tier_index + 1}</span></div>")


class _CardIcon(QLabel):
    """A single card's ICON ONLY — the shared shape between a browse-list
    card and a filled offer slot. Carries no text (the name/tier caption is
    a separate label below it, see ``_caption_html``); not itself
    interactive — the owning widget (`_BrowseCard` / `_SlotWidget`) handles
    clicks/drag/drop."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(_CARD_ICON_SIZE, _CARD_ICON_SIZE)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFrameShape(QFrame.Shape.Box)

    def set_empty(self):
        self.setPixmap(QPixmap())
        self.setStyleSheet(
            "border: 1px dashed gray; background: transparent;")

    def set_image(self, image):
        self.setStyleSheet("border: 1px solid gray;")
        if image is not None:
            self.setPixmap(
                QPixmap.fromImage(image).scaled(
                    _CARD_ICON_SIZE, _CARD_ICON_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.setPixmap(QPixmap())


def _make_caption(parent):
    caption = QLabel(parent)
    caption.setTextFormat(Qt.TextFormat.RichText)
    caption.setWordWrap(True)
    caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
    caption.setFixedWidth(_CARD_WIDTH)
    return caption


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
        self.name = name
        self._drag_start = None
        self.setFixedWidth(_CARD_WIDTH)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)
        self.icon = _CardIcon(self)
        self.icon.set_empty()
        layout.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        caption = _make_caption(self)
        caption.setText(_caption_html(name, tier_index))
        layout.addWidget(caption)

    def refresh_icon(self):
        self.icon.set_image(self._panel.icon_image(self.slot_key))

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
            drag.setHotSpot(QPoint(_CARD_ICON_SIZE // 2, _CARD_ICON_SIZE // 2))
        drag.exec(Qt.DropAction.CopyAction)
        self._drag_start = None


class _SlotWidget(QWidget):
    """One offer-slot drop target on a level row: an empty dashed square, or
    a filled card (icon + name/tier caption, matching `_BrowseCard`'s look)
    with a small clear ("x") button."""

    changed = Signal()

    def __init__(self, panel, village_level, slot_index, parent=None):
        super().__init__(parent)
        self._panel = panel
        self.village_level = village_level
        self.slot_index = slot_index
        self.setAcceptDrops(True)
        self.setFixedWidth(_CARD_WIDTH)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)
        outer.setSpacing(2)
        self.icon = _CardIcon(self)
        outer.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignHCenter)
        self._caption = _make_caption(self)
        outer.addWidget(self._caption)
        self._clear_btn = QToolButton(self)
        self._clear_btn.setText("Clear")
        self._clear_btn.setToolTip("Clear this slot")
        self._clear_btn.clicked.connect(self._on_clear_clicked)
        self._clear_btn.setVisible(False)
        outer.addWidget(self._clear_btn, 0, Qt.AlignmentFlag.AlignHCenter)

        self.set_assignment(None)

    def set_assignment(self, assignment):
        self._assignment = assignment
        if assignment is None:
            self.icon.set_empty()
            self._caption.setText("")
            self._clear_btn.setVisible(False)
            self.setToolTip("Drop a building or tier card here")
            return
        catalog_entry = self._panel.catalog_tier(
            assignment["building_type"], assignment["tier_index"])
        slot_key = catalog_entry["slot"] if catalog_entry else None
        name = catalog_entry["name"] if catalog_entry else assignment["building_type"]
        self.icon.set_image(
            self._panel.icon_image(slot_key) if slot_key else None)
        self._caption.setText(_caption_html(name, assignment["tier_index"]))
        self._clear_btn.setVisible(True)
        self.setToolTip(f"{name} (Tier {assignment['tier_index'] + 1})")

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
        header_font = self._header.font()
        header_font.setBold(True)
        header_font.setPointSize(header_font.pointSize() + 1)
        self._header.setFont(header_font)
        header_row.addWidget(self._header)
        header_row.addStretch(1)
        remove_level_btn = QPushButton("Remove Level", self)
        remove_level_btn.clicked.connect(
            lambda: panel.remove_level(self.village_level))
        header_row.addWidget(remove_level_btn)
        outer.addLayout(header_row)

        self._slots_row = QHBoxLayout()
        self._slots_row.setSpacing(8)
        outer.addLayout(self._slots_row)

        buttons_row = QHBoxLayout()
        add_slot_btn = QPushButton("+ Slot", self)
        add_slot_btn.clicked.connect(lambda: panel.add_slot(self.village_level))
        remove_slot_btn = QPushButton("− Slot", self)
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
        label = f"Level {village_level}"
        if round_num is not None:
            label += f"  —  best-case round ~{round_num}"
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
        toolbar.addWidget(_InfoButton(
            "Add Level",
            "A “level” here is the player's village level "
            "(RunState.village_level) — it goes up by exactly 1 each "
            "time the player levels up in-game, starting from 1.\n\n"
            "“Add Level” creates a new, empty milestone on the "
            "Timeline at the level number you type in the box. A milestone "
            "is what makes that level-up able to offer anything at all: a "
            "village level with no milestone here offers nothing but the "
            "“+Love” fallback in-game.\n\n"
            "After adding a level, use its row's “+ Slot” button "
            "to add empty offer squares, then drag a building card from the "
            "list on the left into one. The graph above shows roughly which "
            "in-game round each level is reached at (best case), so you can "
            "line up a level's placements with when the player is likely to "
            "see them.",
            self))
        toolbar.addStretch(1)
        toolbar.addWidget(QLabel("View max round:", self))
        self._view_max_spin = _NoWheelSpinBox(self)
        self._view_max_spin.setRange(10, 1000)
        self._view_max_spin.setValue(_DEFAULT_VIEW_MAX_ROUND)
        self._view_max_spin.valueChanged.connect(self._on_view_max_changed)
        toolbar.addWidget(self._view_max_spin)
        outer.addLayout(toolbar)

        caption = QLabel(
            "Best-case / upper-bound curve — assumes every enemy spawned is "
            "killed that round. Real XP depends on the player's kill rate, "
            "so a real playthrough reaches each level LATER than shown.",
            self)
        caption_font = caption.font()
        caption_font.setItalic(True)
        caption_font.setPointSize(max(7, caption_font.pointSize() - 1))
        caption.setFont(caption_font)
        caption.setWordWrap(True)
        outer.addWidget(caption)

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
        self._rows_layout.setSpacing(12)
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
            cards_row.setSpacing(6)
            for tier in entry["tiers"]:
                card = _BrowseCard(
                    self, entry["building_type"], tier["tier_index"],
                    tier["name"], tier["slot"], self._browse_content)
                cards_row.addWidget(card)
                self._browse_cards.append(card)
            self._browse_layout.addLayout(cards_row)
            sep = QFrame(self._browse_content)
            sep.setFrameShape(QFrame.Shape.HLine)
            self._browse_layout.addWidget(sep)
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


# Round gridlines land on the first "nice" step (10/20/25/50/100/...) that
# keeps them from crowding together at a wide view_max.
_GRIDLINE_STEPS = (1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500)


def _gridline_step(view_max, target_lines=8):
    if view_max <= 0:
        return 1
    raw = view_max / target_lines
    for step in _GRIDLINE_STEPS:
        if step >= raw:
            return step
    return _GRIDLINE_STEPS[-1]


class _TimelineGraph(QWidget):
    """The round-axis strip: round gridlines, the raw cumulative-XP curve,
    and a tick + label per village_level's computed best-case round.
    Theme-aware (reads the widget's own palette, never a hardcoded color) so
    it stays readable in both light and dark chrome — see
    ``editor/theme.py``."""

    _TOP_MARGIN = 16
    _BOTTOM_MARGIN = 36
    _SIDE_MARGIN = 28
    _MIN_LABEL_GAP_PX = 46

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
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
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter):
        w, h = self.width(), self.height()
        axis_y = h - self._BOTTOM_MARGIN
        left, right = self._SIDE_MARGIN, w - self._SIDE_MARGIN

        pal = self.palette()
        text_color = pal.color(QPalette.ColorRole.WindowText)
        grid_color = pal.color(QPalette.ColorRole.Mid)
        curve_color = pal.color(QPalette.ColorRole.Highlight)

        def x_for_round(round_num):
            frac = round_num / self._view_max if self._view_max else 0
            return int(left + frac * (right - left))

        small_font = QFont(painter.font())
        small_font.setPointSize(max(7, small_font.pointSize() - 1))

        # -- round gridlines + numbers --------------------------------------
        painter.setPen(QPen(grid_color, 1))
        painter.setFont(small_font)
        step = _gridline_step(self._view_max)
        round_num = 0
        while round_num <= self._view_max:
            x = x_for_round(round_num)
            painter.drawLine(x, self._TOP_MARGIN, x, axis_y)
            painter.drawText(x - 12, axis_y + 14, 24, 14,
                             Qt.AlignmentFlag.AlignHCenter, str(round_num))
            round_num += step
        painter.drawText(w - _SIDE_MARGIN - 4, axis_y + 28, "round")

        # -- axis line --------------------------------------------------------
        painter.setPen(QPen(text_color, 1))
        painter.drawLine(left, axis_y, right, axis_y)

        # -- cumulative-XP curve ----------------------------------------------
        points = sorted(
            (r, xp) for r, xp in self._cumulative.items() if r <= self._view_max)
        max_xp = max((xp for _r, xp in points), default=1) or 1
        curve_top = self._TOP_MARGIN + 4
        painter.setPen(QPen(curve_color, 2))
        prev = None
        for round_num, xp in points:
            x = x_for_round(round_num)
            y = int(axis_y - (xp / max_xp) * (axis_y - curve_top))
            if prev is not None:
                painter.drawLine(prev[0], prev[1], x, y)
            prev = (x, y)

        # -- level ticks + labels, staggered so close ticks don't overlap ----
        levels = sorted(
            (level, r) for level, r in self._level_to_round.items()
            if r is not None and r <= self._view_max)
        painter.setPen(QPen(text_color, 1))
        painter.setFont(painter.font())
        last_x = None
        row_toggle = False
        for level, round_num in levels:
            x = x_for_round(round_num)
            if last_x is not None and x - last_x < self._MIN_LABEL_GAP_PX:
                row_toggle = not row_toggle
            else:
                row_toggle = False
            label_y = self._TOP_MARGIN if row_toggle else self._TOP_MARGIN + 16
            painter.drawLine(x, axis_y - 5, x, axis_y + 5)
            painter.drawLine(x, label_y + 10, x, axis_y - 5)
            painter.drawText(x - 24, label_y, 48, 14,
                             Qt.AlignmentFlag.AlignHCenter, f"Lv {level}")
            last_x = x
