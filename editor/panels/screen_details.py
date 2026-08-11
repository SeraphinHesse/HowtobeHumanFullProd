"""ScreenDetailsPanel (B4, R3) — the right-pane form shown while a UI-screen
leaf is selected (screen mode's sibling of MapDetailsPanel/DetailsPanel in
the right_stack QStackedWidget).

Structure: a widget-id list (from the loaded screen_defaults, B3) driving a
per-widget form (rect spinboxes, skin/font/color, label, visible). EVERY
override-capable control carries its OWN compact "↺" reset button (per-field
reset, brief §1d) that clears just that key — rect is ONE reset for the
whole group since it's stored as a single `rect` key. A "Reset ALL" button
below the form still clears every override on the widget at once. Then a
screen-level section (background picker + reset, the `defaults` collapsible
— button_skin/panel_skin/font/text_color, each with its own reset), then
Save.

Every edit (including every reset) is an IMMEDIATE undoable command through
the open UIScreenSession (never staged like balancing.py) — push_move/
push_field/push_skin_assign/push_background/push_default_field. A reset is
just push_field(..., old, None) — `_DocFieldCommand`'s "None = absent"
pruning is what makes it a clean removal rather than writing null. Save just
calls session.save() (engine.data_io.write_validated under the hood).

The rect spinboxes and combo boxes are imported FROM editor.panels.balancing
(their home — never copied, never moved; the root router's rule for the
_NoWheel* widgets).
"""
from pathlib import Path

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from editor import theme_ops, widget_tree
from editor.panels._screen_primitives import widget_display_name
from editor.panels.balancing import (
    CollapsibleSection,
    _NoWheelComboBox,
    _NoWheelSpinBox,
)
from editor.ui_screen_session import NO_PARENT, parent_override
from editor.panels._screen_rules import (
    TOOLTIP_COLOR_CODE_OWNED,
    TOOLTIP_LABEL_CODE_OWNED,
    color_is_code_owned,
    label_is_code_owned,
    resolved_skin,
)
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]

# UH-6/D6: the Color control on a widget that resolves to a skin becomes
# Tint (D6) — it DOES reach the game (widgets.py Button.submit/submit_panel
# thread `tint` through to the HudSprite), unlike `color` on a skinned
# widget (still inert; see game/ui/skinning.py's button_kwargs docstring).
TOOLTIP_TINT_SKINNED = "Multiplies the sprite sheet — white = unchanged."

# UT-1/UT-3: shown on the Label row when the widget is bound to a string
# id. The row edits data/ui/strings.json, which is GLOBAL — the warning
# under the field says how many widgets share the id.
TOOLTIP_TEXT_TEMPLATE = (
    "This text comes from data/ui/strings.json. Editing it here changes "
    "it everywhere this string id is used. {placeholders} are filled in "
    "by the game at runtime.")

# UiEditorParentingPLAN P-4: the tooltip on the outliner. Parenting is an
# AUTHORING relationship (D2) — say so where the designer meets it, or the
# tree reads as a promise the game does not keep.
TOOLTIP_PARENT = (
    "Which widget this one hangs off in the editor. Moving a parent moves "
    "its children; resizing one does not. This is an EDITOR relationship — "
    "the saved rects stay absolute and the game never reads it.")

_RECT_MIN, _RECT_MAX = -4096, 4096

# One custom MIME type carrying the dragged widget's code id.
# editor/panels/timeline.py is the repo's one prior QDrag/QMimeData user and
# this copies its shape — including its testing note: a real OS drag cannot be
# synthesized offscreen, so a test drives `dropEvent` directly.
_MIME_TYPE = "application/x-htbh-screen-widget"


class WidgetTreeWidget(QTreeWidget):
    """The screen-mode outliner (D6): the widget HIERARCHY, replacing the flat
    `QListWidget` rather than sitting beside it — a second parallel widget
    selector would violate the editor's single-selection-model invariant.

    The `Qt.ItemDataRole.UserRole` = code id contract is UNCHANGED, so
    `widget_selected`/`select_widget` and every `push_*` call site are the
    same as they were against the list.

    Dragging an item onto another re-parents it; dropping on empty space
    re-roots it. The view never moves the item itself — it emits
    `reparent_requested` and the panel writes the change through the normal
    undoable `push_field` path, then rebuilds from the doc. That is what makes
    a re-parent undoable, resettable ("↺"/"Reset ALL" cover it with no new
    code) and impossible to leave disagreeing with the data.
    """

    reparent_requested = Signal(str, object)   # widget_id, new parent | None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setToolTip(TOOLTIP_PARENT)
        # Injected by the panel (which owns the defaults + the open doc): does
        # this drop keep the hierarchy a forest? Refusing at drag-MOVE time is
        # what makes a cycle unrepresentable rather than an error to recover
        # from (D5, ED-30).
        self.can_reparent = lambda _widget_id, _new_parent: True

    def _dragged_id(self, event):
        mime = event.mimeData()
        if not mime.hasFormat(_MIME_TYPE):
            return None
        return bytes(mime.data(_MIME_TYPE)).decode("utf-8") or None

    def _drop_parent(self, event):
        """The widget id under the cursor, or None for "drop on empty space =
        make it a root"."""
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def startDrag(self, _supported_actions):
        item = self.currentItem()
        if item is None:
            return
        widget_id = item.data(0, Qt.ItemDataRole.UserRole)
        if not widget_id:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_MIME_TYPE, str(widget_id).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if self._dragged_id(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        widget_id = self._dragged_id(event)
        if widget_id is None or not self.can_reparent(
                widget_id, self._drop_parent(event)):
            event.ignore()
            return
        event.acceptProposedAction()

    def dropEvent(self, event):
        widget_id = self._dragged_id(event)
        if widget_id is None:
            return
        new_parent = self._drop_parent(event)
        if not self.can_reparent(widget_id, new_parent):
            event.ignore()
            return
        # Deliberately NOT calling super(): Qt's own internal move would
        # reshuffle the items behind the data's back, and the rebuild that
        # follows `reparent_requested` is the ONE thing that draws this tree.
        event.acceptProposedAction()
        self.reparent_requested.emit(widget_id, new_parent)

# Quiet time after the last rect spinbox change before the live edit is
# committed as one undo step. Long enough to coalesce a burst of arrow
# clicks / a held arrow key, short enough that Ctrl+Z right after a nudge
# undoes that nudge.
_LIVE_COMMIT_MS = 400


class ScreenDetailsPanel(QWidget):
    widget_selected = Signal(object)   # str widget_id | None — viewport follows

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self._registry = load_registry(self._data_dir)
        self._session = None
        self._all_defaults = {}     # {screen_id: {widgets, mock_note}}
        self._current_widget = None
        self._populating = False    # guards spinboxes/checkbox during refresh

        # baselines: the doc's CURRENT override value for the field being
        # edited (None = no override), captured when the form is (re)
        # populated — every push_* call needs this true "old" value, not
        # merely the widget's displayed contents. `_rect_effective`/
        # `_label_effective` additionally track what's actually ON SCREEN
        # (override, else the default) so an editingFinished that didn't
        # really change anything (e.g. tabbing through an untouched field)
        # is a no-op rather than writing a redundant override.
        self._rect_baseline = None
        self._rect_effective = None
        # Commits an in-flight live rect edit after a quiet period — the half
        # of the gesture `editingFinished` never sees (arrow-button clicks,
        # a held arrow key).
        self._live_commit_timer = QTimer(self)
        self._live_commit_timer.setSingleShot(True)
        self._live_commit_timer.timeout.connect(self._on_rect_edited)
        self._skin_baseline = None
        self._font_baseline = None
        self._color_baseline = None
        self._tint_baseline = None      # UH-6/D6: the Color row's OTHER key
        self._color_is_tint = False     # UH-6: which key the row is showing
        self._text_color_baseline = None
        self._label_baseline = None
        self._label_effective = None
        self._text_id_baseline = None    # UT-1/UT-3
        self._visible_baseline = None

        layout = QVBoxLayout(self)
        self._dirty_label = QLabel("", self)
        layout.addWidget(self._dirty_label)

        layout.addWidget(QLabel("Widgets", self))
        # P-4/D6: a TREE, not a list — same `UserRole` = code id contract.
        self.widget_list = WidgetTreeWidget(self)
        self.widget_list.currentItemChanged.connect(self._on_widget_list_selected)
        self.widget_list.reparent_requested.connect(self._on_reparent_requested)
        self.widget_list.can_reparent = self._can_reparent
        # widget_id -> its item, rebuilt with the tree. A tree has no
        # `setCurrentRow`, and walking it on every external selection sync
        # would be the only place in this panel that searches by id.
        self._tree_items = {}
        layout.addWidget(self.widget_list)

        form = QFormLayout()
        self.x_spin = _NoWheelSpinBox(self)
        self.y_spin = _NoWheelSpinBox(self)
        self.w_spin = _NoWheelSpinBox(self)
        self.h_spin = _NoWheelSpinBox(self)
        for spin, (lo, hi) in ((self.x_spin, (_RECT_MIN, _RECT_MAX)),
                               (self.y_spin, (_RECT_MIN, _RECT_MAX)),
                               (self.w_spin, (0, _RECT_MAX)),
                               (self.h_spin, (0, _RECT_MAX))):
            spin.setRange(lo, hi)
            # LIVE placement: the widget follows the number as it changes
            # (arrow clicks, typing, holding an arrow down) instead of only
            # jumping once Enter/focus-out lands — see `_on_rect_changed`.
            spin.valueChanged.connect(self._on_rect_changed)
            spin.editingFinished.connect(self._on_rect_edited)
        # ONE reset for the whole rect group — it's stored as a single
        # `rect` key, not four (brief §1d: per-KEY granularity, not per-spin).
        rect_row, self.rect_reset_button = self._field_row(
            (self.x_spin, self.y_spin, self.w_spin, self.h_spin),
            "rect", lambda: self._on_reset_field("rect"))
        form.addRow("Rect (X Y W H)", rect_row)

        # P-4: the keyboard-accessible twin of the tree drag. Both refuse
        # exactly the same targets (`widget_tree.legal_parents`), so a
        # designer who cannot drag is not offered a re-parent the tree would
        # have rejected.
        self.parent_combo = _NoWheelComboBox(self)
        self.parent_combo.setToolTip(TOOLTIP_PARENT)
        self.parent_combo.activated.connect(self._on_parent_changed)
        parent_row, self.parent_reset_button = self._field_row(
            (self.parent_combo,), "parent",
            lambda: self._on_reset_field("parent"))
        form.addRow("Parent", parent_row)

        self.skin_combo = _NoWheelComboBox(self)
        self.skin_combo.activated.connect(self._on_skin_changed)
        skin_row, self.skin_reset_button = self._field_row(
            (self.skin_combo,), "skin", lambda: self._on_reset_field("skin"))
        form.addRow("Skin", skin_row)

        self.font_combo = _NoWheelComboBox(self)
        self.font_combo.activated.connect(self._on_font_changed)
        font_row, self.font_reset_button = self._field_row(
            (self.font_combo,), "font", lambda: self._on_reset_field("font"))
        form.addRow("Font", font_row)

        # UH-6/D6: this ONE control is Color on an unskinned widget, Tint on
        # a skinned one (repurposing UH-3's disabled-on-skin state — see
        # _refresh_honest_controls) — the row label + button text + which
        # doc key it reads/writes/resets all follow `self._color_is_tint`.
        self.color_button = QPushButton("Color…", self)
        self.color_button.clicked.connect(self._on_color_clicked)
        color_row, self.color_reset_button = self._field_row(
            (self.color_button,), "color/tint", self._on_reset_color_field)
        self.color_row_label = QLabel("Color", self)
        form.addRow(self.color_row_label, color_row)

        self.text_color_button = QPushButton("Text Color…", self)
        self.text_color_button.clicked.connect(self._on_text_color_clicked)
        text_color_row, self.text_color_reset_button = self._field_row(
            (self.text_color_button,), "text_color",
            lambda: self._on_reset_field("text_color"))
        form.addRow("Text Color", text_color_row)

        self.label_edit = QLineEdit(self)
        self.label_edit.editingFinished.connect(self._on_label_edited)
        label_row, self.label_reset_button = self._field_row(
            (self.label_edit,), "label", lambda: self._on_reset_field("label"))
        self.label_row_label = QLabel("Label", self)
        form.addRow(self.label_row_label, label_row)

        # -- UT-1/UT-3: the string-table binding ------------------------------
        # A widget that resolves its text through `data/ui/strings.json` shows
        # the TEMPLATE here instead of a per-widget label override. The
        # template is GLOBAL (one id, one text, everywhere), which is why the
        # shared-key warning below exists at all.
        self.text_id_combo = _NoWheelComboBox(self)
        self.text_id_combo.activated.connect(self._on_text_id_changed)
        text_id_row, self.text_id_reset_button = self._field_row(
            (self.text_id_combo,), "text_id",
            lambda: self._on_reset_field("text_id"))
        self.text_id_row_label = QLabel("Text ID", self)
        form.addRow(self.text_id_row_label, text_id_row)

        self.sample_label = QLabel("", self)
        self.sample_label.setWordWrap(True)
        self.sample_label.setStyleSheet("color: #888;")
        form.addRow("", self.sample_label)

        self.visible_check = QCheckBox("Visible", self)
        self.visible_check.toggled.connect(self._on_visible_toggled)
        visible_row, self.visible_reset_button = self._field_row(
            (self.visible_check,), "visible",
            lambda: self._on_reset_field("visible"))
        form.addRow("", visible_row)

        layout.addLayout(form)

        self.reset_button = QPushButton("Reset ALL to default", self)
        self.reset_button.setToolTip(
            "Clear every override on the selected widget at once")
        self.reset_button.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self.reset_button)

        # -- screen-level section --------------------------------------------
        bg_label_row = QWidget(self)
        bg_label_layout = QHBoxLayout(bg_label_row)
        bg_label_layout.setContentsMargins(0, 0, 0, 0)
        bg_label_layout.addWidget(QLabel("Background", self), 1)
        self.background_reset_button = self._make_reset_button(
            "background", self._on_reset_background)
        bg_label_layout.addWidget(self.background_reset_button)
        layout.addWidget(bg_label_row)
        self.background_combo = _NoWheelComboBox(self)
        self.background_combo.activated.connect(self._on_background_combo_activated)
        layout.addWidget(self.background_combo)
        self.background_color_button = QPushButton("Background Color…", self)
        self.background_color_button.clicked.connect(self._on_background_color_clicked)
        layout.addWidget(self.background_color_button)

        self.defaults_section = CollapsibleSection(
            "Defaults", tooltip="Screen-level defaults for dynamic widgets",
            expanded=True, parent=self)
        defaults_form = QFormLayout()
        self.button_skin_combo = _NoWheelComboBox(self)
        self.button_skin_combo.activated.connect(
            lambda i: self._on_default_combo_changed("button_skin", self.button_skin_combo))
        button_skin_row, self.button_skin_reset_button = self._field_row(
            (self.button_skin_combo,), "button_skin",
            lambda: self._on_reset_default_field("button_skin"))
        defaults_form.addRow("Button skin", button_skin_row)
        self.panel_skin_combo = _NoWheelComboBox(self)
        self.panel_skin_combo.activated.connect(
            lambda i: self._on_default_combo_changed("panel_skin", self.panel_skin_combo))
        panel_skin_row, self.panel_skin_reset_button = self._field_row(
            (self.panel_skin_combo,), "panel_skin",
            lambda: self._on_reset_default_field("panel_skin"))
        defaults_form.addRow("Panel skin", panel_skin_row)
        self.default_font_combo = _NoWheelComboBox(self)
        self.default_font_combo.activated.connect(
            lambda i: self._on_default_combo_changed("font", self.default_font_combo))
        default_font_row, self.default_font_reset_button = self._field_row(
            (self.default_font_combo,), "font",
            lambda: self._on_reset_default_field("font"))
        defaults_form.addRow("Font", default_font_row)
        self.default_text_color_button = QPushButton("Text Color…", self)
        self.default_text_color_button.clicked.connect(
            self._on_default_text_color_clicked)
        default_text_color_row, self.default_text_color_reset_button = self._field_row(
            (self.default_text_color_button,), "text_color",
            lambda: self._on_reset_default_field("text_color"))
        defaults_form.addRow("Text color", default_text_color_row)
        self.defaults_section.content_layout.addLayout(defaults_form)
        layout.addWidget(self.defaults_section)

        self.save_button = QPushButton("Save", self)
        self.save_button.clicked.connect(self._on_save)
        layout.addWidget(self.save_button)
        layout.addStretch(1)

        self._populate_skin_combo(self.skin_combo)
        self._populate_skin_combo(self.button_skin_combo)
        self._populate_skin_combo(self.panel_skin_combo)
        self._populate_font_combo(self.font_combo)
        self._populate_font_combo(self.default_font_combo)
        self._populate_background_combo()
        self._set_widget_form_enabled(False)
        self._refresh_background()
        self._refresh_defaults_section()

    # -- per-field reset affordance (brief §1d MEDIUM fix) -------------------
    # A compact "↺" QToolButton next to every override-capable control, one
    # per doc KEY (the rect group is ONE button — it's a single `rect` key,
    # not four spinboxes). Each fires push_field(widget_id, key, old, None):
    # the SAME "None = absent" pruning contract as every other push_*, so a
    # per-field reset and the "Reset ALL" button share one code path.

    def _make_reset_button(self, field_label, slot):
        btn = QToolButton(self)
        btn.setText("↺")
        btn.setAutoRaise(True)
        btn.setToolTip(f"Reset {field_label} to default")
        btn.clicked.connect(lambda _checked=False: slot())
        return btn

    def _field_row(self, controls, field_label, slot):
        """A control (or group of controls, for rect) + its own reset
        button, as ONE form row widget. Returns (row_widget, reset_button)."""
        row = QWidget(self)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        for control in controls:
            row_layout.addWidget(control, 1)
        reset_button = self._make_reset_button(field_label, slot)
        row_layout.addWidget(reset_button)
        return row, reset_button

    # -- combo population (registry-driven, never hardcoded slot lists) -----

    def _populate_skin_combo(self, combo):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for slot in self._registry.group_slots("ui"):
            combo.addItem(slot, slot)
        combo.blockSignals(False)

    def _populate_font_combo(self, combo):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for key in theme_ops.font_keys(self._data_dir):
            combo.addItem(key, key)
        combo.blockSignals(False)

    def _populate_background_combo(self):
        combo = self.background_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        try:
            slots = self._registry.group_slots("ui", ("Backgrounds",))
        except KeyError:
            slots = ()
        for slot in slots:
            combo.addItem(slot, slot)
        combo.blockSignals(False)

    def reload_registry(self):
        """Re-read data/slots.json (a variant/background slot was added)."""
        self._registry = load_registry(self._data_dir)
        self._populate_skin_combo(self.skin_combo)
        self._populate_skin_combo(self.button_skin_combo)
        self._populate_skin_combo(self.panel_skin_combo)
        self._populate_background_combo()

    # -- session / defaults binding -------------------------------------------

    def set_session(self, session, defaults=None):
        if self._session is not session:
            self._session = session
            session.undo_stack.cleanChanged.connect(lambda _c: self._refresh_dirty())
            session.screen_opened.connect(lambda _id: self._on_screen_opened())
            # Undo/redo (Ctrl+Z/Y) mutates the doc directly — refresh whatever
            # is currently shown so the form never displays a stale value.
            session.undo_stack.indexChanged.connect(lambda _i: self._refresh_after_undo())
        if defaults is not None:
            self.set_defaults(defaults)
        else:
            self._on_screen_opened()

    def _refresh_after_undo(self):
        # Drop (never commit) any in-flight live rect edit: the undo/redo has
        # just redefined the doc, and pushing a command from inside the undo
        # stack's own indexChanged would be re-entrant.
        #
        # The session OUTLIVES this panel (MainWindow owns both, and the undo
        # stack keeps emitting during teardown), so by the time this runs the
        # panel's C++ side may already be gone — the same window-teardown race
        # `_refresh_dirty` below already swallows. Without the guard the last
        # undo of a session raises "Internal C++ object already deleted" out
        # of a Qt slot, which can abort the process.
        try:
            self._live_commit_timer.stop()
        except RuntimeError:
            return
        # P-4: an undone/redone re-parent changes the SHAPE of the tree, not
        # just a field, so the outliner is rebuilt too. Rebuilding drops the
        # current item, so the selection is restored right after.
        selected = self._current_widget
        self._refresh_widget_list()
        if selected is not None:
            self.select_widget(selected)
        self._refresh_widget_form()
        self._refresh_background()
        self._refresh_defaults_section()

    def set_defaults(self, defaults):
        """The loaded data/ui/screen_defaults.json dict — call on screen
        entry and again whenever "Refresh Layouts" succeeds."""
        self._all_defaults = defaults or {}
        self._on_screen_opened()

    def _current_screen_defaults(self):
        """The open screen's own {widgets, mock_note} sub-dict — resolves
        the session's active `view` (UH-2) the same way
        ViewportPanel._current_screen_defaults does, so `_refresh_widget_list`
        needs no code change: it just iterates whichever dict comes back."""
        if self._session is None or self._session.doc is None:
            return {}
        entry = self._all_defaults.get(self._session.screen_id, {})
        views = entry.get("views")
        view = self._session.view
        if views and view in views:
            return views[view]
        return entry

    def _on_screen_opened(self):
        self._current_widget = None
        self._set_widget_form_enabled(False)
        self._refresh_widget_list()
        self._refresh_background()
        self._refresh_defaults_section()
        self._refresh_dirty()

    # -- widget list -----------------------------------------------------------

    def _doc_widgets(self):
        """The open doc's per-widget override map (the second half of what
        the parent resolver reads)."""
        if self._session is None or self._session.doc is None:
            return {}
        return self._session.doc.get("widgets", {})

    def _refresh_widget_list(self):
        """Rebuild the outliner from `screen_defaults` + the open doc's own
        `parent` overrides (P-4). This is the ONE thing that draws the tree:
        every re-parent writes to the doc and then lands back here."""
        self.widget_list.blockSignals(True)
        self.widget_list.clear()
        self._tree_items = {}
        widgets = self._current_screen_defaults().get("widgets", {})
        tree = widget_tree.build_tree(widgets, self._doc_widgets())

        def add(parent_id, parent_item):
            for widget_id in tree.get(parent_id, ()):
                spec = widgets.get(widget_id) or {}
                item = QTreeWidgetItem([widget_display_name(widget_id, spec)])
                item.setToolTip(0, widget_id)
                item.setData(0, Qt.ItemDataRole.UserRole, widget_id)
                if parent_item is None:
                    self.widget_list.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self._tree_items[widget_id] = item
                add(widget_id, item)

        add(widget_tree.ROOT, None)
        self.widget_list.expandAll()   # expanded by default (P-4)
        self.widget_list.blockSignals(False)

    def _on_widget_list_selected(self, current, _previous=None):
        if current is None:
            return
        widget_id = current.data(0, Qt.ItemDataRole.UserRole)
        self._populate_widget_form(widget_id)
        self.widget_selected.emit(widget_id)

    def select_widget(self, widget_id):
        """External sync (the viewport tells us a widget was clicked/
        dragged there) — populates the form WITHOUT re-emitting
        widget_selected (avoids a viewport<->panel selection feedback loop).
        Matches on `Qt.ItemDataRole.UserRole` (the code id), never item TEXT
        — display names are not guaranteed unique, the id is (UH-4)."""
        self.widget_list.blockSignals(True)
        self.widget_list.setCurrentItem(self._tree_items.get(widget_id))
        self.widget_list.blockSignals(False)
        if widget_id:
            self._populate_widget_form(widget_id)
        else:
            self._flush_live_rect()
            self._current_widget = None
            self._set_widget_form_enabled(False)

    # -- P-4: re-parenting (the tree drag and its combo twin) ----------------

    def _can_reparent(self, widget_id, new_parent):
        """The gate BOTH the drop and the combo honour: a widget may never
        become its own ancestor (D5), and a drop that changes nothing is not
        an edit."""
        widgets = self._current_screen_defaults().get("widgets", {})
        if widget_id not in widgets:
            return False
        if new_parent is not None and new_parent not in widgets:
            return False
        parents = widget_tree.parent_map(widgets, self._doc_widgets())
        if parents.get(widget_id) == new_parent:
            return False
        return not widget_tree.would_cycle(
            widget_tree.build_tree(widgets, self._doc_widgets()),
            widget_id, new_parent)

    def _on_reparent_requested(self, widget_id, new_parent):
        self._apply_reparent(widget_id, new_parent)

    def _apply_reparent(self, widget_id, new_parent):
        """Write a re-parent through the ordinary undoable per-key path, so
        the "↺" reset button and "Reset ALL" cover it with no new code.

        The override is stored only when it DIFFERS from the exporter's own
        default parent — the same "no redundant override" rule the rect and
        label rows follow. Re-rooting a widget whose default parent is not
        already root is the one case that needs an explicit JSON null
        (`NO_PARENT`, D3): clearing the key would restore the default instead.
        """
        if not self._can_reparent(widget_id, new_parent):
            return
        widgets = self._current_screen_defaults().get("widgets", {})
        default_parent = (widgets.get(widget_id) or {}).get(
            widget_tree.PARENT_KEY)
        old_value = parent_override(self._doc_widgets().get(widget_id, {}))
        if new_parent == default_parent:
            new_value = None                      # back to the default
        elif new_parent is None:
            new_value = NO_PARENT                 # explicit re-root
        else:
            new_value = new_parent
        if new_value is old_value or new_value == old_value:
            return
        self._session.push_field(
            widget_id, widget_tree.PARENT_KEY, old_value, new_value)
        self._refresh_widget_list()
        self.select_widget(widget_id)

    def _on_parent_changed(self, index):
        if self._current_widget is None or self._populating:
            return
        self._apply_reparent(self._current_widget,
                             self.parent_combo.itemData(index))

    def _refresh_parent_combo(self, widget_id):
        """Every id this widget may legally hang off, plus "(none)" for a
        root — the combo and the tree drop refuse exactly the same set."""
        widgets = self._current_screen_defaults().get("widgets", {})
        doc_widgets = self._doc_widgets()
        combo = self.parent_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(none)", None)
        for candidate in widget_tree.legal_parents(
                widgets, doc_widgets, widget_id):
            combo.addItem(
                widget_display_name(candidate, widgets.get(candidate)),
                candidate)
        current = widget_tree.parent_map(widgets, doc_widgets).get(widget_id)
        combo.setCurrentIndex(max(0, combo.findData(current)))
        combo.blockSignals(False)

    # -- per-widget form ---------------------------------------------------

    def _set_widget_form_enabled(self, enabled):
        for w in (self.x_spin, self.y_spin, self.w_spin, self.h_spin,
                  self.parent_combo,
                  self.skin_combo, self.font_combo, self.color_button,
                  self.text_color_button, self.label_edit,
                  self.text_id_combo,
                  self.visible_check, self.reset_button):
            w.setEnabled(enabled)
        if not enabled:
            # Per-field reset buttons get their REAL enabled state (does an
            # override exist for THIS key?) from _refresh_reset_buttons,
            # called at the end of _populate_widget_form — but with no
            # widget selected there is nothing to reset, full stop.
            for btn in (self.rect_reset_button, self.parent_reset_button,
                       self.skin_reset_button,
                       self.font_reset_button, self.color_reset_button,
                       self.text_color_reset_button, self.label_reset_button,
                       self.text_id_reset_button, self.visible_reset_button):
                btn.setEnabled(False)
            # UH-6: no widget selected -> nothing to be honest about; show
            # the row's plain, default state.
            self._color_is_tint = False
            self.color_row_label.setText("Color")
            self.color_button.setText("Color…")
            self.color_button.setToolTip("")

    def _refresh_reset_buttons(self, override):
        """Each per-field reset button is enabled iff THAT key currently
        has an override — resetting a field nothing overrides is a no-op
        (push_field's own None==None guard would refuse it anyway; this
        just keeps the button from inviting the click). The Color/Tint row
        (UH-6/D6) checks whichever key `self._color_is_tint` currently
        means — set by `_refresh_honest_controls`, which runs BEFORE this
        in `_populate_widget_form`."""
        self.rect_reset_button.setEnabled("rect" in override)
        # `parent` is the one key whose override can legitimately be a JSON
        # null (an explicit re-root, D3), so this tests PRESENCE, not truth.
        self.parent_reset_button.setEnabled(widget_tree.PARENT_KEY in override)
        self.skin_reset_button.setEnabled("skin" in override)
        self.font_reset_button.setEnabled("font" in override)
        self.color_reset_button.setEnabled(self._active_color_key() in override)
        self.text_color_reset_button.setEnabled("text_color" in override)
        self.label_reset_button.setEnabled("label" in override)
        self.text_id_reset_button.setEnabled("text_id" in override)
        self.visible_reset_button.setEnabled("visible" in override)

    def _active_color_key(self):
        """"tint" on a widget that resolves to a skin (D6 — the honest
        control there is Tint), else "color" (today's Color behavior,
        verbatim — UH-3's rule preserved for unskinned widgets)."""
        return "tint" if self._color_is_tint else "color"

    def _refresh_honest_controls(self, spec, override, style):
        """D3 (plan) + D6 (UH-6, ties to UH-3): a control that cannot take
        effect in the game is disabled with an explanatory tooltip, never
        silently accepted. Recomputed live (never stored) from the SAME
        `spec`/`override`/`style` accessors `_populate_widget_form` already
        uses, so it composes with UH-2's per-view filtering regardless of
        merge order.

        UH-6 REPURPOSES UH-3's "Color disabled on a skinned widget" state:
        `tint` DOES reach the game (widgets.py Button.submit/submit_panel
        thread it to the HudSprite), so the honest move for a skinned
        widget is relabel-to-Tint-and-ENABLE, not disable — the
        disabled-never-lying rule (D3) still holds, since nothing here
        writes a key the game ignores either way. An unskinned widget keeps
        today's plain Color behavior verbatim.
        """
        screen_id = self._session.screen_id if self._session is not None else None
        kind = spec.get("kind")
        code_owned_fill = color_is_code_owned(kind)
        skinned = resolved_skin(spec, override, style) is not None
        # Tint (UH-6/D6) is the honest repurposing of a skinned widget's Color
        # control for the kinds whose draw path threads `tint` into the sheet:
        #   - `button`: `Button.submit` unconditionally forwards `tint`.
        #   - `panel`: every id'd panel widget forwards `tint` at its
        #     `submit_panel` call site (`building_ui.py:238,932`,
        #     `cheat_menu.py:217`, `add_name.py:134`, `boss_cutscene.py:162`,
        #     `hud.py:321,354,448`). The two `submit_panel` sites that DROP
        #     `tint` (`building_ui.py:1252` boss popup, `levelup.py:128` option
        #     boxes) draw dynamic, NON-id'd content that never appears in
        #     `screen_defaults.json`, so they are never selectable here.
        # It is NOT offered for `field`/`label` (no skin is ever drawn for
        # them; their fill/color is code-owned) — those hit the disabled branch.
        # The final rule:
        #   skinned button/panel        -> Tint (enabled)
        #   code-owned fill kind        -> Color disabled (panel/field/label,
        #                                  when unskinned: fill is hardcoded)
        #   otherwise                   -> Color enabled (unskinned button, or
        #                                  backdrop/bar whose `.color` is live)
        # KNOWN RESIDUAL (deferred viewport quirk, finding 3): `hud.love_panel`
        # is kind `panel` but draws via `HudRect` (hardcoded fill), so a `skin`
        # override forced onto it would show Tint that no-ops. That requires
        # the same skin-on-a-non-skinnable-widget quirk that also affects
        # backdrop/bar; it is out of scope here and tracked separately.
        tintable = skinned and kind in ("button", "panel")
        self._color_is_tint = tintable
        if tintable:
            self.color_row_label.setText("Tint")
            self.color_button.setText("Tint…")
            self.color_button.setToolTip(TOOLTIP_TINT_SKINNED)
            self.color_button.setEnabled(True)
        else:
            self.color_row_label.setText("Color")
            self.color_button.setText("Color…")
            if code_owned_fill:
                self.color_button.setToolTip(TOOLTIP_COLOR_CODE_OWNED)
                self.color_button.setEnabled(False)
            else:
                self.color_button.setToolTip("")
                self.color_button.setEnabled(True)

        # UT-1/UT-3: a widget bound to a string id shows its TEMPLATE here,
        # editable, instead of the old "edit it in game code" disablement.
        text_id = self._effective_text_id(spec, override)
        code_owned = label_is_code_owned(screen_id, self._current_widget, kind,
                                         text_id)
        self.label_edit.setEnabled(not code_owned)
        self.label_edit.setToolTip(
            TOOLTIP_TEXT_TEMPLATE if text_id
            else (TOOLTIP_LABEL_CODE_OWNED if code_owned else ""))
        self.label_row_label.setText("Text template" if text_id else "Label")
        bindable = bool(self._strings_doc())
        self.text_id_row_label.setVisible(bindable)
        self.text_id_combo.setVisible(bindable)
        self.text_id_combo.setEnabled(bindable)
        self.sample_label.setVisible(bool(text_id))

    def _populate_widget_form(self, widget_id):
        defaults = self._current_screen_defaults()
        spec = defaults.get("widgets", {}).get(widget_id)
        if spec is None or self._session is None or self._session.doc is None:
            return
        # Commit any live rect edit still in flight BEFORE the form re-points
        # at another widget — `_on_rect_edited` reads `self._current_widget`,
        # so it must run while that is still the widget being edited.
        self._flush_live_rect()
        self._current_widget = widget_id
        self._populating = True
        override = self._session.doc.get("widgets", {}).get(widget_id, {})

        # Widgets show the EFFECTIVE value (override, else the default), but
        # every baseline stores the RAW override — None when absent — so a
        # no-net-change edit (type it back to the default) removes the
        # override on undo/redo rather than writing a redundant one equal to
        # the default (push_field/push_move's "None = absent" contract).
        rect = override.get("rect", spec["rect"])
        self.x_spin.setValue(rect[0])
        self.y_spin.setValue(rect[1])
        self.w_spin.setValue(rect[2])
        self.h_spin.setValue(rect[3])
        self._rect_baseline = list(override["rect"]) if "rect" in override else None
        self._rect_effective = list(rect)

        self._refresh_parent_combo(widget_id)

        skin = override.get("skin")
        self._skin_baseline = skin
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(skin)))

        font = override.get("font")
        self._font_baseline = font
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(font)))

        self._color_baseline = override.get("color")
        self._tint_baseline = override.get("tint")   # UH-6/D6
        self._text_color_baseline = override.get("text_color")

        # UT-1/UT-3: when the widget is bound to a string id the Label row
        # edits the TEMPLATE (the global string table), not a per-widget
        # override — so its text and baseline come from strings.json.
        self._text_id_baseline = override.get("text_id")
        text_id = self._effective_text_id(spec, override)
        self._refresh_text_id_combo(text_id)
        if text_id:
            label = self._strings_doc().get(text_id, "")
            self._label_baseline = self._label_effective = label
        else:
            label = override.get("label", spec.get("label", ""))
            self._label_baseline = override.get("label")
            self._label_effective = label
        self.label_edit.setText(label)
        self._refresh_sample(spec, text_id)

        # visible defaults True (schema omits it ⇒ visible); baseline stores
        # the RAW override (None = "no override", the push_field sentinel)
        self._visible_baseline = override.get("visible")
        self.visible_check.setChecked(override.get("visible", True))

        self._populating = False
        self._set_widget_form_enabled(True)
        # UH-6: honest-controls recompute FIRST — it sets self._color_is_tint,
        # which _refresh_reset_buttons' Color/Tint row reads via
        # _active_color_key(). (The one genuine UH-3/UH-6 coupling point.)
        style = self._session.doc.get("defaults", {})
        self._refresh_honest_controls(spec, override, style)
        self._refresh_reset_buttons(override)

    def _refresh_widget_form(self):
        if self._current_widget is not None:
            self._populate_widget_form(self._current_widget)

    # -- live placement (the rect spinboxes) ---------------------------------
    # A designer nudging X/Y wants to SEE the widget move, not to type a
    # number and press Enter to find out where it lands. So the rect
    # spinboxes work exactly like a viewport drag: `valueChanged` mutates
    # `session.doc` in place (the viewport's 16ms frame timer picks it up on
    # the next repaint, no signal needed) and ONE undoable `push_move` is
    # committed at the end of the gesture. `_rect_baseline` — the override
    # value the command must undo back to — is captured at the START of the
    # burst and deliberately NOT advanced by the live mutation, so a burst of
    # 30 arrow clicks is one undo step, not 30.
    #
    # "End of the gesture" is whichever comes first: `editingFinished` (Enter
    # or focus-out) or `_LIVE_COMMIT_MS` of quiet. The timer is what covers
    # arrow-button clicking and press-and-hold, neither of which ever emits
    # `editingFinished`.

    def _flush_live_rect(self):
        """Commit a pending live rect edit now, if there is one."""
        if self._live_commit_timer.isActive():
            self._on_rect_edited()

    def _on_rect_changed(self, _value=None):
        if self._current_widget is None or self._populating:
            return
        new_rect = self._current_rect_values()
        if new_rect == self._live_rect():
            return
        self._session.doc.setdefault("widgets", {}).setdefault(
            self._current_widget, {})["rect"] = new_rect
        self._live_commit_timer.start(_LIVE_COMMIT_MS)

    def _current_rect_values(self):
        return [self.x_spin.value(), self.y_spin.value(),
                self.w_spin.value(), self.h_spin.value()]

    def _live_rect(self):
        """The rect currently IN the doc for the selected widget (which the
        live mutation above may already have written), else what is on
        screen."""
        override = self._session.doc.get("widgets", {}).get(
            self._current_widget, {})
        if "rect" in override:
            return list(override["rect"])
        return list(self._rect_effective or [])

    def _on_rect_edited(self):
        """Commit the in-flight live edit as ONE undoable command. Also the
        no-op guard for a field that was merely tabbed through."""
        self._live_commit_timer.stop()
        if self._current_widget is None or self._populating:
            return
        new_rect = self._current_rect_values()
        if new_rect == self._rect_effective:
            # Nothing changed from what was on screen when the form was
            # populated — but a live mutation may still have written and
            # reverted an override, so drop it rather than leave a redundant
            # one behind.
            self._revert_live_rect()
            return
        # The live mutation already wrote `new_rect` straight into the doc;
        # push_move re-applies the same value, which is idempotent (the exact
        # argument the viewport's drag-then-commit already relies on).
        self._session.push_move(self._current_widget, self._rect_baseline, new_rect)
        self._rect_baseline = new_rect
        self._rect_effective = new_rect

    def _revert_live_rect(self):
        """Undo an uncommitted live mutation that ended up back where it
        started — restores the doc to the baseline override (removing the
        `rect` key entirely when there was none) so nothing is left dirty."""
        widgets = self._session.doc.get("widgets", {})
        entry = widgets.get(self._current_widget)
        if entry is None or "rect" not in entry:
            return
        if self._rect_baseline is None:
            del entry["rect"]
            if not entry:
                del widgets[self._current_widget]
        else:
            entry["rect"] = list(self._rect_baseline)

    def _on_skin_changed(self, index):
        if self._current_widget is None:
            return
        new_skin = self.skin_combo.itemData(index)
        old_skin = self._skin_baseline
        if new_skin == old_skin:
            return
        self._session.push_skin_assign(self._current_widget, old_skin, new_skin)
        self._skin_baseline = new_skin
        self._refresh_widget_form()

    def _on_font_changed(self, index):
        if self._current_widget is None:
            return
        new_font = self.font_combo.itemData(index)
        old_font = self._font_baseline
        if new_font == old_font:
            return
        self._session.push_field(self._current_widget, "font", old_font, new_font)
        self._font_baseline = new_font

    def _pick_color(self, current):
        base = QColor(*current[:3]) if current else QColor(255, 255, 255)
        chosen = QColorDialog.getColor(base, self, "Pick a color")
        if not chosen.isValid():
            return None
        return [chosen.red(), chosen.green(), chosen.blue()]

    def _on_color_clicked(self):
        """UH-6/D6: writes `tint` on a skinned widget, `color` on an
        unskinned one — whichever `_active_color_key()` (set by
        `_refresh_honest_controls`) says the row is currently showing."""
        if self._current_widget is None:
            return
        key = self._active_color_key()
        baseline = self._tint_baseline if key == "tint" else self._color_baseline
        new_color = self._pick_color(baseline)
        if new_color is None or new_color == baseline:
            return
        self._session.push_field(self._current_widget, key, baseline, new_color)
        if key == "tint":
            self._tint_baseline = new_color
        else:
            self._color_baseline = new_color

    def _on_reset_color_field(self):
        """The Color/Tint row's own reset (UH-6/D6): targets whichever key
        is currently active, not a fixed "color"."""
        self._on_reset_field(self._active_color_key())

    def _on_text_color_clicked(self):
        if self._current_widget is None:
            return
        new_color = self._pick_color(self._text_color_baseline)
        if new_color is None or new_color == self._text_color_baseline:
            return
        self._session.push_field(
            self._current_widget, "text_color", self._text_color_baseline, new_color)
        self._text_color_baseline = new_color

    def _on_label_edited(self):
        if self._current_widget is None or self._populating:
            return
        new_label = self.label_edit.text()
        if new_label == self._label_effective:
            return   # nothing actually changed from what's on screen
        text_id = self._current_text_id()
        if text_id:
            # UT-1/UT-3: this row is the TEMPLATE, so the edit goes to the
            # global string table, not to a per-widget override.
            self._session.push_string(text_id, self._label_baseline, new_label)
            self._refresh_sample(self._current_spec(), text_id)
        else:
            self._session.push_field(
                self._current_widget, "label", self._label_baseline, new_label)
        self._label_baseline = new_label
        self._label_effective = new_label

    # -- UT-1/UT-3: the string-table binding ---------------------------------

    def _strings_doc(self):
        return (self._session.strings_doc or {}) if self._session else {}

    def _current_spec(self):
        return (self._current_screen_defaults()
                .get("widgets", {}).get(self._current_widget) or {})

    def _effective_text_id(self, spec, override):
        """The string id this widget currently draws through: the doc's
        `text_id` override if the designer re-pointed it, else the one the
        exporter recorded off the game's own holder."""
        return override.get("text_id") or spec.get("text_id")

    def _current_text_id(self):
        if self._current_widget is None or self._session is None:
            return None
        override = (self._session.doc or {}).get("widgets", {}).get(
            self._current_widget, {})
        return self._effective_text_id(self._current_spec(), override)

    def _refresh_text_id_combo(self, text_id):
        """Every id in the table, so a widget can be re-pointed at an existing
        string. The editor never INVENTS an id: the table is a closed set
        (`additionalProperties: false`, every key required), so adding one is a
        schema change — i.e. a code change (plan D3)."""
        combo = self.text_id_combo
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("(none)", None)
        for sid in sorted(self._strings_doc()):
            combo.addItem(sid, sid)
        combo.setCurrentIndex(max(0, combo.findData(text_id)))
        combo.blockSignals(False)

    def _refresh_sample(self, spec, text_id):
        """The grey line under the template: what it renders as, and how many
        other widgets share it — because editing a template here changes the
        text everywhere that id is used, which is not obvious from the row."""
        if not text_id:
            self.sample_label.setText("")
            return
        sample = spec.get("sample")
        shown = f"→ {sample}" if sample else "→ filled in at runtime"
        users = self._text_id_users(text_id)
        if users > 1:
            shown += f"   ·   used by {users} widgets"
        self.sample_label.setText(shown)

    def _text_id_users(self, text_id):
        """How many widgets across EVERY screen and view resolve `text_id`."""
        count = 0
        for entry in (self._all_defaults or {}).values():
            groups = [entry.get("widgets", {})]
            groups += [v.get("widgets", {})
                       for v in (entry.get("views") or {}).values()]
            for widgets_map in groups:
                count += sum(1 for spec in widgets_map.values()
                             if spec.get("text_id") == text_id)
        return count

    def _on_text_id_changed(self):
        if self._current_widget is None or self._populating:
            return
        new_id = self.text_id_combo.currentData()
        if new_id == self._text_id_baseline:
            return
        self._session.push_field(
            self._current_widget, "text_id", self._text_id_baseline, new_id)
        self._text_id_baseline = new_id
        self._refresh_widget_form()

    def _on_visible_toggled(self, checked):
        if self._current_widget is None or self._populating:
            return
        # True (the default) means "no override needed"; only an explicit
        # False is ever stored, matching push_*'s "None = absent" contract.
        new_value = None if checked else False
        old_value = self._visible_baseline
        if new_value == old_value:
            return
        self._session.push_field(
            self._current_widget, "visible", old_value, new_value)
        self._visible_baseline = new_value

    def _on_reset_field(self, field_key):
        """Per-field reset (brief §1d MEDIUM fix): clears ONLY `field_key` on
        the selected widget, leaving every other override intact — e.g.
        resetting the rect while keeping an assigned skin. Same push_field(
        ..., None) + pruning contract as "Reset ALL", just scoped to one
        key."""
        if self._current_widget is None or self._session is None:
            return
        widget_id = self._current_widget
        override = self._session.doc.get("widgets", {}).get(widget_id, {})
        if field_key not in override:
            return
        # `parent` is the one key whose stored override can be a JSON null (an
        # explicit re-root, D3); read through the ONE accessor that maps that
        # to `NO_PARENT`, or the push would compare None == None and no-op.
        old_value = (parent_override(override)
                     if field_key == widget_tree.PARENT_KEY
                     else override[field_key])
        self._session.push_field(widget_id, field_key, old_value, None)
        if field_key == widget_tree.PARENT_KEY:
            self._refresh_widget_list()
            self.select_widget(widget_id)
            return
        self._refresh_widget_form()

    def _on_reset_clicked(self):
        """"Reset ALL": clears EVERY override on the selected widget, one
        undoable push_field per field — the last one pops the (now-empty)
        widget entry out of the doc entirely via _DocFieldCommand's
        pruning. The per-field "↺" buttons above do the same thing scoped
        to one key."""
        if self._current_widget is None or self._session is None:
            return
        widget_id = self._current_widget
        override = dict(self._session.doc.get("widgets", {}).get(widget_id, {}))
        for field_key, old_value in override.items():
            if field_key == widget_tree.PARENT_KEY:
                old_value = parent_override(override)   # JSON null -> NO_PARENT
            self._session.push_field(widget_id, field_key, old_value, None)
        if widget_tree.PARENT_KEY in override:
            self._refresh_widget_list()
            self.select_widget(widget_id)
            return
        self._refresh_widget_form()

    # -- screen-level: background ---------------------------------------------

    def _refresh_background(self):
        if self._session is None or self._session.doc is None:
            self.background_combo.setCurrentIndex(0)
            self.background_reset_button.setEnabled(False)
            return
        background = self._session.doc.get("background") or {}
        self.background_combo.blockSignals(True)
        idx = self.background_combo.findData(background.get("slot"))
        self.background_combo.setCurrentIndex(max(0, idx))
        self.background_combo.blockSignals(False)
        self.background_reset_button.setEnabled(
            self._session.doc.get("background") is not None)

    def _on_background_combo_activated(self, index):
        slot = self.background_combo.itemData(index)
        self._session.push_background({"slot": slot} if slot else None)
        self._refresh_background()

    def _on_background_color_clicked(self):
        current = (self._session.doc.get("background") or {}).get("color")
        new_color = self._pick_color(current)
        if new_color is None:
            return
        self._session.push_background({"color": new_color})
        self._refresh_background()

    def _on_reset_background(self):
        """Background is ONE key (`{slot}` or `{color}`) — a single reset
        clears it regardless of which shape it currently holds."""
        if self._session is None or self._session.doc is None:
            return
        old = self._session.doc.get("background")
        if old is None:
            return
        self._session.push_background(None)
        self._refresh_background()

    # -- screen-level: defaults -------------------------------------------------

    def _refresh_defaults_section(self):
        if self._session is None or self._session.doc is None:
            for combo in (self.button_skin_combo, self.panel_skin_combo,
                         self.default_font_combo):
                combo.setCurrentIndex(0)
            for btn in (self.button_skin_reset_button,
                       self.panel_skin_reset_button,
                       self.default_font_reset_button,
                       self.default_text_color_reset_button):
                btn.setEnabled(False)
            return
        style = self._session.doc.get("defaults", {})
        self.button_skin_combo.blockSignals(True)
        self.button_skin_combo.setCurrentIndex(
            max(0, self.button_skin_combo.findData(style.get("button_skin"))))
        self.button_skin_combo.blockSignals(False)
        self.panel_skin_combo.blockSignals(True)
        self.panel_skin_combo.setCurrentIndex(
            max(0, self.panel_skin_combo.findData(style.get("panel_skin"))))
        self.panel_skin_combo.blockSignals(False)
        self.default_font_combo.blockSignals(True)
        self.default_font_combo.setCurrentIndex(
            max(0, self.default_font_combo.findData(style.get("font"))))
        self.default_font_combo.blockSignals(False)
        self.button_skin_reset_button.setEnabled("button_skin" in style)
        self.panel_skin_reset_button.setEnabled("panel_skin" in style)
        self.default_font_reset_button.setEnabled("font" in style)
        self.default_text_color_reset_button.setEnabled("text_color" in style)

    def _on_default_combo_changed(self, field_key, combo):
        style = self._session.doc.get("defaults", {})
        old_value = style.get(field_key)
        new_value = combo.itemData(combo.currentIndex())
        if old_value == new_value:
            return
        self._session.push_default_field(field_key, old_value, new_value)
        self._refresh_defaults_section()
        self._refresh_widget_form()

    def _on_reset_default_field(self, field_key):
        if self._session is None or self._session.doc is None:
            return
        style = self._session.doc.get("defaults", {})
        if field_key not in style:
            return
        old_value = style[field_key]
        self._session.push_default_field(field_key, old_value, None)
        self._refresh_defaults_section()
        self._refresh_widget_form()

    def _on_default_text_color_clicked(self):
        style = self._session.doc.get("defaults", {})
        old_value = style.get("text_color")
        new_value = self._pick_color(old_value)
        if new_value is None or new_value == old_value:
            return
        self._session.push_default_field("text_color", old_value, new_value)
        self._refresh_defaults_section()

    # -- save --------------------------------------------------------------

    def _refresh_dirty(self):
        try:
            dirty = self._session.dirty if self._session is not None else False
        except RuntimeError:
            return   # undo stack mid-destruction (window teardown)
        self._dirty_label.setText("● unsaved changes" if dirty else "saved")
        self.save_button.setEnabled(dirty)

    def _on_save(self):
        if self._session is not None and self._session.doc is not None:
            self._session.save()
        self._refresh_dirty()
