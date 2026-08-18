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

The whole body sits in a QScrollArea (balancing.py's pattern) — it is ~2k
lines of controls deep — with the dirty label pinned above it and Save pinned
below it, outside the scroll. That is also why every value control here must
stay a `_NoWheel*`: they ignore wheelEvent, so a scroll over a spinbox reaches
the scroll area instead of nudging the value.

The rect spinboxes and combo boxes are imported FROM editor.panels.balancing
(their home — never copied, never moved; the root router's rule for the
_NoWheel* widgets).
"""
import copy
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
    QScrollArea,
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
from editor.ui_screen_session import NO_PARENT, ordered_views, parent_override
from editor.panels._screen_rules import (
    TOOLTIP_COLOR_CODE_OWNED,
    TOOLTIP_LABEL_CODE_OWNED,
    color_is_code_owned,
    custom_color_is_code_owned,
    custom_label_is_code_owned,
    custom_widgets_for_view,
    custom_tint_applies,
    is_custom,
    label_is_code_owned,
    merge_custom_widgets,
    resolved_skin,
)
from engine.assets import load_registry
from engine.ui_layers import ordered as ordered_layers

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

# P-5/D4: shown on the Visible row when an ANCESTOR is hidden. The preview
# draws nothing for such a widget, and saying so beats silently drawing
# nothing — but its own `visible` override is untouched, and so is what the
# game does with it.
TOOLTIP_HIDDEN_BY_PARENT = (
    "Not drawn in the preview because its parent \"{name}\" is hidden. "
    "Visibility inherits in the EDITOR only — this widget's own Visible flag "
    "is unchanged, and the game still resolves each widget's flag on its own.")

# UL-8/D4: the band control's HONEST label. `under` does not mean "behind my
# own widget" — it means behind everything the screen draws, which is the one
# consequence of D4 a designer cannot discover from the two-word combo. It has
# to be met in the editor, not in a bug report.
TOOLTIP_LAYER_BAND = (
    "Under layers sit behind EVERYTHING on this screen, not just behind "
    "their owner widget. Use Over for backgrounds between stacked panels.")

# UL-13: the same geometry on a custom widget's own Band control, but the
# DEFAULT is the other way round — a custom widget is decoration, so it is
# created Under and never hides the screen's own readouts until a designer
# deliberately says Over. Spelled out here because the two-word combo cannot.
TOOLTIP_CUSTOM_BAND = (
    "Under (the default) draws this widget behind EVERYTHING on the screen, "
    "so it can never cover the screen's own text or buttons. Over draws it "
    "in front of everything — use it only for decoration meant to sit on top.")

# UL-14: the same control on a CODE-OWNED widget, where the stakes are
# different in both directions — the default is "leave it where the game
# draws it", and banding it costs the widget its clicks.
TOOLTIP_CODE_OWNED_BAND = (
    "Not banded (the default) leaves this widget exactly where the game "
    "draws it. Under moves it behind EVERYTHING on the screen and Over in "
    "front of everything — in either band it sits among the custom widgets "
    "and Z decides which of them is in front. A banded widget stops being "
    "clickable, so only panels, images and text can be banded.")

#: The widget kinds a `band` may relocate — a hand-kept mirror of
#: `game/ui/skinning.py::_BANDABLE_KINDS` (editor/ may never import game/,
#: the same accepted drift `_screen_primitives`/`custom_widgets_in_band`
#: already record).
_BANDABLE_KINDS = ("panel", "backdrop", "label")

# UL-13: widget ids are GLOBAL to a screen (D2) and the runtime has no notion
# of building_panel's editor-only views, so a custom widget authored while one
# view is showing is drawn in every one of them. Stated inline on that screen,
# where it is the only place the surprise can bite.
CUSTOM_EVERY_VIEW_NOTE = (
    "A custom widget you add here belongs to the view that was open when "
    "you added it, and the game draws it only in that view. Set View to "
    "\"Every view\" if you want it on all of them — but note that widget "
    "ids are still shared across views, so two views cannot both own an id.")

#: Item text for the unscoped choice in the View combo — the `view` key
#: ABSENT, which is what a single-view screen means and what every widget
#: authored before the key existed still means.
CUSTOM_EVERY_VIEW_ITEM = "Every view"

TOOLTIP_CUSTOM_VIEW = (
    "Which view of this screen draws this widget. A screen id is shared by "
    "every mode of its panel and by the modals that declare it, so an "
    "unscoped custom widget appears in all of them at once — including on "
    "top of an open preview. Naming a view is how you say which one it "
    "belongs to. Changing this moves the widget out of the view you are "
    "looking at.")

# UL-8 ruling 1: `ScreenSkinning.state_of` (game/ui/skinning.py) answers
# "idle" for anything that is not a `Button` — a panel/label/backdrop holder
# is a plain namespace with no state machine at all. Per-state values on such
# a layer are schema-valid and permanently unreachable, so the inspector greys
# the state selector rather than accepting them (ED-30: invalid input
# unrepresentable).
TOOLTIP_STATE_BUTTON_ONLY = (
    "Hover, Pressed, and Disabled states are only available for Button "
    "widgets; this holder always appears in the Idle state.")

# UL-8: a layer draws exactly ONE primitive, FIRST MATCH WINS
# (game/ui/skinning.py `_submit_one_layer`, each branch returning once it
# draws):
#     slot -> HudSprite   (reads `tint`; nothing else)
#     text -> HudText     (reads `text_id`/`label`, `font`, `align`,
#                          `text_color`; never `tint` or `color`)
#     color -> HudRect    (reads `color` alone)
# Every row belonging to a branch this layer cannot reach is disabled and says
# why — the same disabled-never-lying rule the widget form's Color row already
# follows (D3).
TOOLTIP_LAYER_COLOR_INERT = (
    "This layer draws its slot art, so Color is ignored. Clear the Slot to "
    "draw a flat colour instead.")
TOOLTIP_LAYER_SLOT_WINS = (
    "This layer draws its slot art, so its text is never drawn. Clear the "
    "Slot to draw text instead.")
TOOLTIP_LAYER_TEXT_WINS = (
    "This layer draws text, so Color is ignored — a flat colour is only "
    "drawn by a layer with no slot and no text.")
TOOLTIP_LAYER_TEXT_COLOR_NEEDS_TEXT = (
    "Nothing to colour: give this layer some Text first.")
TOOLTIP_LAYER_TINT_NEEDS_SLOT = (
    "Tint multiplies a sprite sheet, so it only applies to a layer with a "
    "Slot.")

# The four D9 states, in the order the state selector offers them. Populated
# from the registry's `ui` animations when that is available (the same
# data-driven list viewport.py's own state dropdown uses); this is the
# fallback for a registry with no `ui` category.
_LAYER_STATES = ("idle", "hover", "pressed", "disabled")

# UL-10: the three targets a clickable layer may name that are NOT a widget id
# in its own screen (D7 as amended). Restated here rather than imported from
# `game.ui.skinning.RESERVED_TARGETS` because `editor/` may never import
# `game/` (D5) — the game module's docstring names this file as the twin.
RESERVED_TARGETS = ("close_window", "back", "noop")

TOOLTIP_LAYER_CLICKABLE = (
    "Make this layer a click target. An ordinary decorative layer is "
    "transparent to clicks — the widget underneath it gets them.")

TOOLTIP_LAYER_TARGET = (
    "What clicking this layer does: another widget id in THIS screen (fires "
    "that widget's own action), or one of close_window / back / noop. "
    "Anything else still saves, but the click is swallowed — it never falls "
    "through to the widget underneath.")

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
        make it a root".

        UL-6: dropping ON a LAYER node targets that layer's OWNER widget —
        layers have no parent concept (they hang off exactly one widget by
        construction), so the nearest sensible parent is the widget they
        belong to rather than a refusal the designer has to decode."""
        item = self.itemAt(event.position().toPoint())
        if item is None:
            return None
        role = item.data(0, Qt.ItemDataRole.UserRole)
        return role[0] if isinstance(role, tuple) else role

    def startDrag(self, _supported_actions):
        item = self.currentItem()
        if item is None:
            return
        widget_id = item.data(0, Qt.ItemDataRole.UserRole)
        # UL-6: a layer node's role is a (widget_id, layer_id) TUPLE, and a
        # layer is not re-parentable — only widgets drag.
        if not widget_id or isinstance(widget_id, tuple):
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

# Floor for the outliner inside the scroll area (it would otherwise collapse
# to nothing under a QScrollArea with setWidgetResizable(True)).
_OUTLINER_MIN_HEIGHT = 220


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
        self._align_baseline = None     # UL-1
        self._color_baseline = None
        self._tint_baseline = None      # UH-6/D6: the Color row's OTHER key
        self._color_is_tint = False     # UH-6: which key the row is showing
        self._text_color_baseline = None
        self._label_baseline = None
        self._label_effective = None
        self._text_id_baseline = None    # UT-1/UT-3
        self._visible_baseline = None

        # The panel is ~2k lines of controls deep (outliner → per-widget form
        # → Layers → per-layer inspector → Background → Defaults), so the body
        # lives in a QScrollArea — the balancing.py pattern, verbatim. The
        # dirty label and Save stay OUTSIDE it, pinned top and bottom: a Save
        # you have to scroll to find is the same complaint in a new place.
        outer = QVBoxLayout(self)
        self._dirty_label = QLabel("", self)
        outer.addWidget(self._dirty_label)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._scroll_body = QWidget()
        layout = QVBoxLayout(self._scroll_body)

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
        # UL-6: (widget_id, layer_id) -> its item, the layer twin of
        # `_tree_items`. Layer nodes hang under their owner widget's item and
        # carry a TUPLE in UserRole (widgets keep a bare id string), which is
        # what tells the two node kinds apart everywhere they are read.
        self._layer_items = {}
        self._current_layer_id = None
        # Inside a resizable scroll area a tree happily shrinks to nothing;
        # the outliner needs a floor to stay usable.
        self.widget_list.setMinimumHeight(_OUTLINER_MIN_HEIGHT)
        layout.addWidget(self.widget_list)
        layout.addWidget(self._build_custom_widget_controls())

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

        # UL-1: which way the widget's text spreads from its stored anchor.
        # Unlike Skin/Font (open-ended, registry-driven, hence their
        # `_populate_*` methods) this is a fixed 3-value enum pinned by
        # `ui_screen.schema.json`, so it is filled once, here.
        self.align_combo = _NoWheelComboBox(self)
        self.align_combo.addItem("Left", "left")
        self.align_combo.addItem("Center", "center")
        self.align_combo.addItem("Right", "right")
        self.align_combo.activated.connect(self._on_align_changed)
        align_row, self.align_reset_button = self._field_row(
            (self.align_combo,), "align", lambda: self._on_reset_field("align"))
        form.addRow("Align", align_row)

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

        layout.addWidget(self._build_layer_controls())

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

        layout.addStretch(1)
        self._scroll.setWidget(self._scroll_body)
        outer.addWidget(self._scroll, 1)

        # Pinned below the scroll area, always reachable.
        self.save_button = QPushButton("Save", self)
        self.save_button.clicked.connect(self._on_save)
        outer.addWidget(self.save_button)

        self._populate_skin_combo(self.skin_combo)
        self._populate_skin_combo(self.button_skin_combo)
        self._populate_skin_combo(self.panel_skin_combo)
        self._populate_skin_combo(self.layer_slot_combo)   # UL-6
        self._populate_skin_combo(self.layer_field_slot_combo)   # UL-8
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

    def _slot_label(self, slot):
        """What a skin picker shows for a ui slot: its designer-given name with
        the key after it, or the bare key when it has no name (slot editor →
        Name). The item DATA stays the bare key — a rename in slots.json is a
        relabel here and never rewrites a screen override."""
        name = self._registry.display_name(slot)
        return f"{name}  ({slot})" if name else slot

    def _populate_skin_combo(self, combo):
        combo.blockSignals(True)
        combo.clear()
        combo.addItem("", None)
        for slot in self._registry.group_slots("ui"):
            combo.addItem(self._slot_label(slot), slot)
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
            combo.addItem(self._slot_label(slot), slot)
        combo.blockSignals(False)

    def reload_registry(self):
        """Re-read data/slots.json (a variant/background slot was added)."""
        self._registry = load_registry(self._data_dir)
        self._populate_skin_combo(self.skin_combo)
        self._populate_skin_combo(self.button_skin_combo)
        self._populate_skin_combo(self.panel_skin_combo)
        self._populate_skin_combo(self.layer_slot_combo)   # UL-6
        self._populate_skin_combo(self.layer_field_slot_combo)   # UL-8
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
        # UL-6: an undone/redone layer op changes the tree's shape too, and
        # the layer selection is restored with the widget one when the layer
        # still exists (an undone ADD legitimately takes it away).
        selected_layer = self._current_layer_id
        self._refresh_widget_list()
        if selected is not None:
            self.select_widget(selected)
            if (selected, selected_layer) in self._layer_items:
                self.select_layer(selected, selected_layer)
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
            entry = views[view]
        customs = self._custom_widgets()
        if not customs:
            return entry
        merged = dict(entry)
        merged["widgets"] = merge_custom_widgets(entry.get("widgets", {}),
                                                 customs)
        return merged

    # -- UL-13: designer-authored custom widgets ----------------------------
    # The doc's `custom_widgets` table is folded into the code-owned defaults
    # by the ONE merge above (`_screen_rules.merge_custom_widgets`, shared
    # with the viewport), so the outliner, the per-field form, its reset
    # buttons, `widget_tree` parenting and the whole Layers section already
    # work on a custom widget with no code of their own. What is left is this
    # section: creating one, deleting one, and the two AUTHORING keys that
    # live in `custom_widgets/<id>` rather than in `widgets/<id>` (band, z).

    def _custom_widgets(self):
        """The open doc's `custom_widgets` table (a copy — the session hands
        one out), filtered to the ACTIVE VIEW; `{}` when the screen authors
        none.

        The same filter the viewport applies, at the same one read, so the
        outliner and the canvas can never disagree about which custom widgets
        this view has. A widget scoped to another view is not hidden-but-
        selectable — it is simply not part of this view, exactly as a
        code-owned widget of another view is not."""
        if self._session is None or self._session.doc is None:
            return {}
        return custom_widgets_for_view(self._session.custom_widgets(),
                                       self._session.view)

    def _is_custom(self, widget_id):
        return is_custom(widget_id, self._custom_widgets())

    def _code_owned_ids(self):
        """Every CODE-OWNED widget id on this screen — the union across ALL
        views, not just the active one. `add_custom_widget` refuses a
        collision with one, and an id is global to the screen (D2), so a
        custom `panel` created while the `unlock` view is showing must still
        be refused against `upgrade`'s ids."""
        entry = self._all_defaults.get(
            self._session.screen_id, {}) if self._session else {}
        ids = set(entry.get("widgets", {}))
        for view in (entry.get("views") or {}).values():
            ids |= set(view.get("widgets", {}))
        return ids

    def _on_screen_opened(self):
        self._current_widget = None
        self._current_layer_id = None
        self._set_widget_form_enabled(False)
        self._refresh_widget_list()
        self._refresh_custom_controls()   # UL-13
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
        self._layer_items = {}
        widgets = self._current_screen_defaults().get("widgets", {})
        customs = self._custom_widgets()
        tree = widget_tree.build_tree(widgets, self._doc_widgets())

        def add(parent_id, parent_item):
            for widget_id in tree.get(parent_id, ()):
                spec = widgets.get(widget_id) or {}
                name = widget_display_name(widget_id, spec)
                # UL-13: a designer-authored widget reads differently from an
                # exporter-owned one, so a designer can tell at a glance what
                # they own (and what Remove will act on). The UserRole stays
                # the BARE ID — the layer nodes' (widget_id, layer_id) tuple
                # contract, and `isinstance(role, tuple)`, are untouched.
                if widget_id in customs:
                    name = f"{name}  (custom)"
                item = QTreeWidgetItem([name])
                item.setToolTip(0, widget_id)
                item.setData(0, Qt.ItemDataRole.UserRole, widget_id)
                if parent_item is None:
                    self.widget_list.addTopLevelItem(item)
                else:
                    parent_item.addChild(item)
                self._tree_items[widget_id] = item
                add(widget_id, item)

        add(widget_tree.ROOT, None)

        # UL-6: a widget's LAYERS hang under it, in paint order (`under` band
        # by z, then `over` by z — `engine.ui_layers.ordered`, the same
        # ordering the game paints by, so the outliner cannot claim a stacking
        # the screen does not have). Layer nodes carry a
        # (widget_id, layer_id) TUPLE in UserRole; widget nodes keep a bare id
        # string, and `isinstance(role, tuple)` is what tells them apart.
        for widget_id, item in self._tree_items.items():
            for layer in self._ordered_layers(widget_id):
                layer_id = layer.get("id") or ""
                layer_item = QTreeWidgetItem([self._layer_node_text(layer)])
                layer_item.setToolTip(0, layer_id or "layer with no id")
                layer_item.setData(0, Qt.ItemDataRole.UserRole,
                                   (widget_id, layer_id))
                item.addChild(layer_item)
                if layer_id:
                    self._layer_items[(widget_id, layer_id)] = layer_item

        self.widget_list.expandAll()   # expanded by default (P-4)
        self.widget_list.blockSignals(False)
        # A rebuild can drop the layer the buttons were pointing at (an undone
        # add, a removed layer): forget it rather than leave Remove armed on
        # something that no longer exists.
        if (self._current_widget, self._current_layer_id) not in self._layer_items:
            self._current_layer_id = None
        self._refresh_layer_buttons()

    def _on_widget_list_selected(self, current, _previous=None):
        if current is None:
            return
        role = current.data(0, Qt.ItemDataRole.UserRole)
        # UL-6: a layer node carries (widget_id, layer_id). Selecting one
        # still selects its OWNER widget everywhere else — the form keeps
        # showing the widget's controls and the viewport still follows the
        # widget (per-layer inspection is UL-8) — only the layer buttons and
        # the "Selected layer:" line change.
        if isinstance(role, tuple):
            widget_id, layer_id = role
            self._current_layer_id = layer_id or None
        else:
            widget_id = role
            self._current_layer_id = None
        self._populate_widget_form(widget_id)
        self._refresh_layer_buttons()
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
        self._current_layer_id = None   # UL-6: a WIDGET is selected now
        if widget_id:
            self._populate_widget_form(widget_id)
        else:
            self._flush_live_rect()
            self._current_widget = None
            self._set_widget_form_enabled(False)
        self._refresh_layer_buttons()

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

    # -- UL-6: layers -------------------------------------------------------
    # A layer is EXTRA art (or text) drawn under or over one widget, stored as
    # an entry in that widget's `layers` array in the open screen doc. The
    # outliner shows them as children of their owner; these controls add /
    # remove / reorder them. Every one of them goes through a single undoable
    # `UIScreenSession.*_layer*` call — this panel never touches the array
    # itself, exactly as it never writes a rect or a skin directly.
    #
    # Enabled-state contract:
    #   Add        — whenever a WIDGET is selected (a layer node counts: its
    #                owner is the widget the new layer lands on).
    #   Remove/Up/Down — only while a LAYER node is selected in the tree.

    def _build_custom_widget_controls(self):
        """The "Custom widgets" strip under the outliner: three Add buttons,
        Remove, and the two AUTHORING keys a custom widget owns.

        Built like `_build_layer_controls` (its neighbour in the same panel):
        every value control is a `_NoWheel*` imported from
        `editor.panels.balancing` (the panel lives in a QScrollArea — a plain
        spinbox would eat the scroll), and Remove's `clicked` is
        LAMBDA-WRAPPED so an unchecked button's `clicked(False)` cannot land
        in a keyword argument (the `details.clear_entry` footgun).

        Enabled-state contract: the three Add buttons whenever a screen is
        open; Remove, Band and Z only while the selection is a CUSTOM widget
        — a code-owned widget belongs to the exporter and can never be
        deleted or re-banded from here.
        """
        box = QWidget(self)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.addWidget(QLabel("Custom widgets", self))

        button_row = QWidget(self)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.custom_add_panel_button = QPushButton("+ Panel", self)
        self.custom_add_panel_button.setToolTip(
            "A box: its skin (or the screen's panel skin) if you assign one, "
            "else its colour — with a centred caption when you give it text.")
        self.custom_add_panel_button.clicked.connect(
            lambda _checked=False: self._on_add_custom_widget("panel"))
        button_layout.addWidget(self.custom_add_panel_button)
        self.custom_add_text_button = QPushButton("+ Text", self)
        self.custom_add_text_button.setToolTip("Text only — no box.")
        self.custom_add_text_button.clicked.connect(
            lambda _checked=False: self._on_add_custom_widget("label"))
        button_layout.addWidget(self.custom_add_text_button)
        self.custom_add_image_button = QPushButton("+ Image", self)
        self.custom_add_image_button.setToolTip(
            "A box with no text: its own skin if you assign one, else its "
            "colour. Unlike a panel it never picks up the screen's default "
            "panel skin.")
        self.custom_add_image_button.clicked.connect(
            lambda _checked=False: self._on_add_custom_widget("backdrop"))
        button_layout.addWidget(self.custom_add_image_button)
        self.custom_remove_button = QPushButton("Remove", self)
        self.custom_remove_button.setToolTip(
            "Delete the selected custom widget, its overrides and its layers "
            "(one undo step). Only your own widgets can be removed.")
        self.custom_remove_button.clicked.connect(
            lambda _checked=False: self._on_remove_custom_widget())
        button_layout.addWidget(self.custom_remove_button)
        box_layout.addWidget(button_row)

        # UH-2's views are an EDITOR-only split; the runtime has none.
        self.custom_view_note = QLabel(CUSTOM_EVERY_VIEW_NOTE, self)
        self.custom_view_note.setWordWrap(True)
        self.custom_view_note.setStyleSheet("color: #888;")
        self.custom_view_note.setVisible(False)
        box_layout.addWidget(self.custom_view_note)

        form = QFormLayout()
        # View sits above Band/Z: all three are authoring metadata living in
        # `custom_widgets/<id>`, and this one decides whether the widget is
        # on this screen at all before the other two decide where in it.
        self.custom_view_combo = _NoWheelComboBox(self)
        self.custom_view_combo.setToolTip(TOOLTIP_CUSTOM_VIEW)
        self.custom_view_combo.activated.connect(self._on_custom_view_changed)
        self.custom_view_row_label = QLabel("View", self)
        form.addRow(self.custom_view_row_label, self.custom_view_combo)
        self.custom_band_combo = _NoWheelComboBox(self)
        # "Under" FIRST — it is the default a new custom widget is created
        # with, and index 0 is also the fallback `_refresh_custom_controls`
        # lands on when `findData` misses.
        self.custom_band_combo.addItem("Under", "under")
        self.custom_band_combo.addItem("Over", "over")
        self.custom_band_combo.setToolTip(TOOLTIP_CUSTOM_BAND)
        self.custom_band_combo.activated.connect(self._on_custom_band_changed)
        self.custom_band_row_label = QLabel("Band", self)
        form.addRow(self.custom_band_row_label, self.custom_band_combo)
        self.custom_z_spin = _NoWheelSpinBox(self)
        self.custom_z_spin.setRange(-999, 999)
        self.custom_z_spin.setToolTip(
            "Paint order within this widget's band, ascending — against the "
            "custom widgets AND any of the screen's own widgets you have "
            "banded. A widget that is not in a band ignores Z; the band "
            "alone decides where it sits against everything else.")
        self.custom_z_spin.editingFinished.connect(self._on_custom_z_changed)
        self.custom_z_row_label = QLabel("Z", self)
        form.addRow(self.custom_z_row_label, self.custom_z_spin)
        box_layout.addLayout(form)
        return box

    def _on_add_custom_widget(self, kind):
        """Create one custom widget and select it. The session generates the
        id (first free index) and writes the starter appearance override that
        makes it visible in the game as well as here."""
        if self._session is None or self._session.doc is None:
            return
        # Stamped with the view that is OPEN, so a decoration a designer
        # draws on the build list belongs to the build list — not to every
        # mode of the panel and every modal that shares its screen id.
        widget_id = self._session.add_custom_widget(
            kind, code_owned_ids=self._code_owned_ids(),
            view=self._session.view if self._screen_view_ids() else None)
        if widget_id is None:
            return
        self._refresh_widget_list()
        self.select_widget(widget_id)
        self.widget_selected.emit(widget_id)

    def _on_remove_custom_widget(self):
        if self._session is None or not self._is_custom(self._current_widget):
            return
        self._session.remove_custom_widget(self._current_widget)
        self._current_widget = None
        self._current_layer_id = None
        self._refresh_widget_list()
        self.select_widget(None)

    def _rebuild_band_items(self, custom_widget):
        """Repopulate the Band combo for whichever kind of widget is selected.

        Called with signals already blocked by `_refresh_custom_controls`;
        it rebuilds only when the item set actually differs, so merely moving
        the selection between two custom widgets touches nothing."""
        wanted = [("Under", "under"), ("Over", "over")] if custom_widget \
            else [("Not banded", None), ("Under", "under"), ("Over", "over")]
        current = [(self.custom_band_combo.itemText(i),
                    self.custom_band_combo.itemData(i))
                   for i in range(self.custom_band_combo.count())]
        if current == wanted:
            return
        self.custom_band_combo.clear()
        for text, data in wanted:
            self.custom_band_combo.addItem(text, data)

    def _band_entry(self):
        """Where the selected widget's `band`/`z` live: its `custom_widgets`
        geometry entry when it is custom, its `widgets/<id>` override when it
        is code-owned (UL-14). `{}` when nothing bandable is selected."""
        widget_id = self._current_widget
        if widget_id is None:
            return {}
        if self._is_custom(widget_id):
            return self._custom_widgets().get(widget_id, {})
        return self._doc_widgets().get(widget_id, {})

    def _band_target_kind(self):
        """The kind of the selected widget IF it may carry a band, else None.

        A custom widget always may — its three kinds are the bandable three.
        A CODE-OWNED widget may only when its kind has a generic draw
        (`game/ui/skinning.py::_BANDABLE_KINDS`): banding relocates it into a
        layer pass and makes it INERT, which would silently kill a `button`'s
        clicks and has nothing to draw for a `bar`/`field`."""
        if self._session is None or self._session.doc is None:
            return None
        if self._current_widget is None:
            return None
        kind = self._current_spec().get("kind")
        if self._is_custom(self._current_widget):
            return kind
        return kind if kind in _BANDABLE_KINDS else None

    def _screen_view_ids(self):
        """This screen's view ids in game-mode order, `()` when it has none.

        Read off `screen_defaults.json` rather than off the doc: the views
        are what the EXPORTER recorded, so a designer can only scope a widget
        to a view the game actually has."""
        if self._session is None:
            return ()
        entry = self._all_defaults.get(self._session.screen_id, {}) or {}
        return ordered_views(entry.get("views") or {})

    def _rebuild_view_items(self):
        """Repopulate the View combo for the open screen. Rebuilds only when
        the item set actually differs, so moving the selection between two
        custom widgets of the same screen touches nothing."""
        wanted = [(CUSTOM_EVERY_VIEW_ITEM, None)]
        wanted += [(view.replace("_", " ").capitalize(), view)
                   for view in self._screen_view_ids()]
        current = [(self.custom_view_combo.itemText(i),
                    self.custom_view_combo.itemData(i))
                   for i in range(self.custom_view_combo.count())]
        if current == wanted:
            return
        self.custom_view_combo.clear()
        for text, data in wanted:
            self.custom_view_combo.addItem(text, data)

    def _on_custom_view_changed(self, index):
        """Move the selected custom widget to another view (or to none).

        Deselects afterwards when the widget left the view being looked at —
        it is no longer part of this screen's content, so leaving it selected
        would leave the form editing something the canvas does not draw."""
        if self._populating or self._session is None:
            return
        widget_id = self._current_widget
        if widget_id is None or not self._is_custom(widget_id):
            return
        entry = self._custom_widgets().get(widget_id, {})
        new_view = self.custom_view_combo.itemData(index)
        self._session.set_custom_field(widget_id, "view",
                                       entry.get("view"), new_view)
        self._refresh_widget_list()
        still_here = widget_id in self._custom_widgets()
        self.select_widget(widget_id if still_here else None)
        if not still_here:
            self._current_widget = None
            self.widget_selected.emit(None)
        self._refresh_custom_controls()

    def _on_custom_band_changed(self, index):
        if self._populating or self._band_target_kind() is None:
            return
        entry = self._band_entry()
        self._session.set_band_field(
            self._current_widget, "band", entry.get("band"),
            self.custom_band_combo.itemData(index))
        self._refresh_custom_controls()

    def _on_custom_z_changed(self):
        if self._populating or self._band_target_kind() is None:
            return
        entry = self._band_entry()
        value = self.custom_z_spin.value()
        self._session.set_band_field(
            self._current_widget, "z", entry.get("z"),
            value if value else None)
        self._refresh_custom_controls()

    def _refresh_custom_controls(self):
        """Add follows the open SCREEN; Remove/Band/Z follow a CUSTOM
        selection. Populating the two value controls blocks their signals —
        merely looking at a widget must never dirty the doc."""
        open_screen = (self._session is not None
                       and self._session.doc is not None)
        for button in (self.custom_add_panel_button,
                       self.custom_add_text_button,
                       self.custom_add_image_button):
            button.setEnabled(open_screen)
        self.custom_view_note.setVisible(
            open_screen and bool((self._all_defaults.get(
                self._session.screen_id, {}) or {}).get("views")))
        custom = open_screen and self._is_custom(self._current_widget)
        self.custom_remove_button.setEnabled(bool(custom))
        # View is CUSTOM-only and only meaningful on a screen that HAS views:
        # a code-owned widget is already view-scoped by construction (its
        # mode is what put it in `ids`), and a single-view screen has nothing
        # to choose between.
        has_views = bool(self._screen_view_ids())
        self.custom_view_row_label.setVisible(has_views)
        self.custom_view_combo.setVisible(has_views)
        self.custom_view_combo.setEnabled(bool(custom) and has_views)
        self.custom_view_combo.blockSignals(True)
        self._rebuild_view_items()
        self.custom_view_combo.setCurrentIndex(
            max(0, self.custom_view_combo.findData(
                (self._custom_widgets().get(self._current_widget) or {})
                .get("view") if custom else None)))
        self.custom_view_combo.blockSignals(False)
        # UL-14: Band/Z follow anything BANDABLE now, not just a custom
        # widget — a code-owned panel/backdrop/label may be relocated into a
        # band so a custom widget can sort in front of it by z. Remove stays
        # custom-only: a code-owned widget belongs to the exporter.
        bandable = open_screen and self._band_target_kind() is not None
        self.custom_band_combo.setEnabled(bool(bandable))
        self.custom_z_spin.setEnabled(bool(bandable))
        entry = self._band_entry() if bandable else {}
        self.custom_band_combo.blockSignals(True)
        # A CUSTOM widget is always in one band or the other (absent means
        # Under). A CODE-OWNED one is normally in NEITHER — it is drawn by
        # its own screen — so it gets the extra "Not banded" choice, which is
        # both its default and the way back out.
        self._rebuild_band_items(custom_widget=bool(custom))
        self.custom_band_combo.setToolTip(
            TOOLTIP_CUSTOM_BAND if custom else TOOLTIP_CODE_OWNED_BAND)
        self.custom_band_combo.setCurrentIndex(
            max(0, self.custom_band_combo.findData(
                entry.get("band") or ("under" if custom else None))))
        self.custom_band_combo.blockSignals(False)
        self.custom_z_spin.blockSignals(True)
        self.custom_z_spin.setValue(entry.get("z") or 0)
        self.custom_z_spin.blockSignals(False)

    def _build_layer_controls(self):
        """The "Layers" section: slot + band pickers, Add, Remove, Up/Down.

        The slot picker is an inline combo rather than a modal chooser opened
        by Add: it is the same registry-driven `ui` slot list the Skin row
        already offers, and keeping it inline means the whole add gesture is
        one click on a visible choice (and is drivable from a test, which a
        modal dialog is not).
        """
        box = QWidget(self)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.addWidget(QLabel("Layers", self))

        picker_row = QWidget(self)
        picker_layout = QHBoxLayout(picker_row)
        picker_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_slot_combo = _NoWheelComboBox(self)
        self.layer_slot_combo.setToolTip(
            "Art for the new layer (a `ui` slot). Leave blank for a layer "
            "you will give text or a colour instead.")
        picker_layout.addWidget(self.layer_slot_combo, 1)
        self.layer_band_combo = _NoWheelComboBox(self)
        self.layer_band_combo.addItem("Over", "over")
        self.layer_band_combo.addItem("Under", "under")
        # UL-8/D4: the same wording as the per-layer Band row below, so the
        # band's real reach is stated wherever a band is chosen.
        self.layer_band_combo.setToolTip(TOOLTIP_LAYER_BAND)
        picker_layout.addWidget(self.layer_band_combo)
        box_layout.addWidget(picker_row)

        button_row = QWidget(self)
        button_layout = QHBoxLayout(button_row)
        button_layout.setContentsMargins(0, 0, 0, 0)
        self.layer_add_button = QPushButton("Add Layer", self)
        self.layer_add_button.clicked.connect(self._on_add_layer)
        button_layout.addWidget(self.layer_add_button, 1)
        self.layer_remove_button = QPushButton("Remove Layer", self)
        self.layer_remove_button.clicked.connect(self._on_remove_layer)
        button_layout.addWidget(self.layer_remove_button, 1)
        self.layer_up_button = QToolButton(self)
        self.layer_up_button.setText("▲")
        self.layer_up_button.setToolTip("Draw this layer earlier in its band")
        self.layer_up_button.clicked.connect(
            lambda _checked=False: self._on_move_layer(-1))
        button_layout.addWidget(self.layer_up_button)
        self.layer_down_button = QToolButton(self)
        self.layer_down_button.setText("▼")
        self.layer_down_button.setToolTip("Draw this layer later in its band")
        self.layer_down_button.clicked.connect(
            lambda _checked=False: self._on_move_layer(1))
        button_layout.addWidget(self.layer_down_button)
        box_layout.addWidget(button_row)

        # Read-only "which layer is selected" line. The FORM above stays the
        # WIDGET's (per-layer inspection is UL-8's job), so without this the
        # tree selection would be the only sign of what Remove would remove.
        self.layer_selected_label = QLabel("", self)
        self.layer_selected_label.setStyleSheet("color: #888;")
        box_layout.addWidget(self.layer_selected_label)

        # UL-8: the per-layer inspector hangs BELOW the layer-ops controls, as
        # the second subsection of the same "Layers" box.
        box_layout.addWidget(self._build_layer_inspector())
        return box

    def _widget_layers(self, widget_id):
        """The selected widget's layer array straight from the doc (`[]` when
        it has none) — the ONE read behind both the tree and the buttons."""
        if self._session is None or widget_id is None:
            return []
        return self._session.layers(widget_id)

    def _ordered_layers(self, widget_id):
        """The widget's layers in PAINT order: the `under` band (by z) then
        the `over` band (by z), which is the order the outliner lists them
        and the order Up/Down move within."""
        layers = self._widget_layers(widget_id)
        return (list(ordered_layers(layers, "under"))
                + list(ordered_layers(layers, "over")))

    def _next_layer_id(self, widget_id):
        """`layer_1`, `layer_2`, … — the first index this widget is not
        already using. Deterministic rather than a uuid so the id a designer
        sees in the outliner is readable, and so a test can name it."""
        used = {entry.get("id") for entry in self._widget_layers(widget_id)}
        index = 1
        while f"layer_{index}" in used:
            index += 1
        return f"layer_{index}"

    def _layer_node_text(self, layer):
        layer_id = layer.get("id") or ""
        slot = layer.get("slot")
        name = layer_id or "(unnamed layer)"
        return f"{name} — {slot}" if slot else name

    def _on_add_layer(self):
        """Add one layer to the selected widget (its OWNER when a layer node
        is what is selected), then re-select the new layer so Remove/Up/Down
        act on what was just created."""
        if self._current_widget is None or self._session is None:
            return
        widget_id = self._current_widget
        layer_id = self._next_layer_id(widget_id)
        spec = {"offset": [0, 0, 0, 0], "z": 0,
                "band": self.layer_band_combo.currentData() or "over"}
        slot = self.layer_slot_combo.currentData()
        if slot:
            spec["slot"] = slot
        self._session.add_layer(widget_id, layer_id, spec)
        self._refresh_widget_list()
        self.select_layer(widget_id, layer_id)

    def _on_remove_layer(self):
        if (self._current_widget is None or self._current_layer_id is None
                or self._session is None):
            return
        widget_id = self._current_widget
        self._session.remove_layer(widget_id, self._current_layer_id)
        self._current_layer_id = None
        self._refresh_widget_list()
        self.select_widget(widget_id)

    def _on_move_layer(self, delta):
        """Move the selected layer one step within its own band by rewriting
        ONLY its `z` (the session's `reorder_layer`).

        The new z is the neighbour's z ∓ 1, never the neighbour's z itself:
        `ordered()` sorts stably, so an equal z would leave the pair in
        source order and the button would do nothing visible.
        """
        if (self._current_widget is None or self._current_layer_id is None
                or self._session is None):
            return
        widget_id, layer_id = self._current_widget, self._current_layer_id
        layers = self._widget_layers(widget_id)
        band = next((e.get("band", "over") for e in layers
                     if e.get("id") == layer_id), None)
        if band is None:
            return
        siblings = list(ordered_layers(layers, band))
        index = next((i for i, e in enumerate(siblings)
                      if e.get("id") == layer_id), None)
        if index is None:
            return
        target = index + delta
        if not 0 <= target < len(siblings):
            return
        neighbour_z = siblings[target].get("z", 0)
        self._session.reorder_layer(widget_id, layer_id,
                                    neighbour_z - 1 if delta < 0
                                    else neighbour_z + 1)
        self._refresh_widget_list()
        self.select_layer(widget_id, layer_id)

    def select_layer(self, widget_id, layer_id):
        """Select a LAYER node in the outliner (the layer twin of
        `select_widget`): the widget form keeps showing the owner widget —
        per-layer inspection is UL-8 — and only the layer buttons change."""
        item = self._layer_items.get((widget_id, layer_id))
        self.widget_list.blockSignals(True)
        self.widget_list.setCurrentItem(item)
        self.widget_list.blockSignals(False)
        self._current_layer_id = layer_id if item is not None else None
        if item is not None:
            self._populate_widget_form(widget_id)
        self._refresh_layer_buttons()

    def _refresh_layer_buttons(self):
        """Add follows the WIDGET selection; Remove/Up/Down follow the LAYER
        selection. Up/Down additionally go dead at the ends of the band —
        a click that cannot move anything should not be offered."""
        has_widget = self._current_widget is not None
        self.layer_add_button.setEnabled(has_widget)
        self.layer_slot_combo.setEnabled(has_widget)
        self.layer_band_combo.setEnabled(has_widget)
        layer_id = self._current_layer_id
        has_layer = has_widget and bool(layer_id)
        self.layer_remove_button.setEnabled(has_layer)
        up = down = False
        if has_layer:
            layers = self._widget_layers(self._current_widget)
            band = next((e.get("band", "over") for e in layers
                         if e.get("id") == layer_id), None)
            siblings = (list(ordered_layers(layers, band))
                        if band is not None else [])
            index = next((i for i, e in enumerate(siblings)
                          if e.get("id") == layer_id), None)
            if index is not None:
                up = index > 0
                down = index < len(siblings) - 1
        self.layer_up_button.setEnabled(up)
        self.layer_down_button.setEnabled(down)
        self.layer_selected_label.setText(
            f"Selected layer: {layer_id}" if has_layer else "")
        self._refresh_layer_inspector()   # UL-8
        self._refresh_custom_controls()   # UL-13

    # -- UL-8: the per-layer, per-state inspector ---------------------------
    # The form the selected LAYER's own values are edited in, one row per doc
    # key, following B4's per-field immediate-undoable-push convention
    # (`_field_row` + `_make_reset_button`) exactly as the widget form above —
    # never balancing.py's staged edits.
    #
    # SCOPE of a row, which the state selector decides:
    #   "idle"                      -> the layer entry itself (`layers[i][key]`)
    #   "hover"/"pressed"/"disabled"-> `layers[i].states[<state>][key]`, leaving
    #                                  every other state's patch untouched
    # so a per-state edit is additive and a per-state reset removes exactly one
    # key. Emptying a state's patch removes the state key itself rather than
    # leaving `{}` behind: `{}` is PRESENT and therefore means "this state
    # looks like the base" (engine.ui_layers._state_patch — presence drives the
    # fallback, not truthiness), which is not what "reset" was asked for.
    #
    # `z` and `band` are deliberately NOT per-state: neither is a state-patch
    # key in the schema, so both rows always write the base entry whatever the
    # selector says.
    #
    # KNOWN GAP (deliberate): a hand-authored `states.idle` patch is legal and
    # this form never writes one — the Idle rows edit the base entry. Such a
    # doc's Idle rows therefore show the base values, not the patch.

    def _build_layer_inspector(self):
        box = QWidget(self)
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)

        state_row = QWidget(self)
        state_layout = QHBoxLayout(state_row)
        state_layout.setContentsMargins(0, 0, 0, 0)
        state_layout.addWidget(QLabel("State", self))
        self.layer_state_combo = _NoWheelComboBox(self)
        for state in self._state_names():
            self.layer_state_combo.addItem(state.capitalize(), state)
        self.layer_state_combo.activated.connect(
            lambda _i: self._refresh_layer_inspector())
        state_layout.addWidget(self.layer_state_combo, 1)
        box_layout.addWidget(state_row)

        self.layer_state_note = QLabel("", self)
        self.layer_state_note.setWordWrap(True)
        self.layer_state_note.setStyleSheet("color: #888;")
        box_layout.addWidget(self.layer_state_note)

        form = QFormLayout()

        self.layer_off_x = _NoWheelSpinBox(self)
        self.layer_off_y = _NoWheelSpinBox(self)
        self.layer_off_w = _NoWheelSpinBox(self)
        self.layer_off_h = _NoWheelSpinBox(self)
        for spin in (self.layer_off_x, self.layer_off_y,
                     self.layer_off_w, self.layer_off_h):
            spin.setRange(_RECT_MIN, _RECT_MAX)
            spin.valueChanged.connect(self._on_layer_offset_changed)
        self.layer_off_w.setToolTip("0 inherits the owner widget's width")
        self.layer_off_h.setToolTip("0 inherits the owner widget's height")
        offset_row, self.layer_offset_reset_button = self._field_row(
            (self.layer_off_x, self.layer_off_y,
             self.layer_off_w, self.layer_off_h),
            "offset", lambda: self._on_reset_layer_field("offset"))
        form.addRow("Offset (dX dY W H)", offset_row)

        self.layer_field_slot_combo = _NoWheelComboBox(self)
        self.layer_field_slot_combo.activated.connect(
            lambda _i: self._push_layer_field(
                "slot", self.layer_field_slot_combo.currentData()))
        slot_row, self.layer_slot_reset_button = self._field_row(
            (self.layer_field_slot_combo,), "slot",
            lambda: self._on_reset_layer_field("slot"))
        form.addRow("Slot", slot_row)

        self.layer_label_edit = QLineEdit(self)
        self.layer_label_edit.editingFinished.connect(self._on_layer_label_edited)
        label_row, self.layer_label_reset_button = self._field_row(
            (self.layer_label_edit,), "label",
            lambda: self._on_reset_layer_field("label"))
        form.addRow("Text", label_row)

        self.layer_color_button = QPushButton("Color…", self)
        self.layer_color_button.clicked.connect(
            lambda: self._on_layer_color_clicked("color"))
        color_row, self.layer_color_reset_button = self._field_row(
            (self.layer_color_button,), "color",
            lambda: self._on_reset_layer_field("color"))
        form.addRow("Color", color_row)

        self.layer_tint_button = QPushButton("Tint…", self)
        self.layer_tint_button.setToolTip(TOOLTIP_TINT_SKINNED)
        self.layer_tint_button.clicked.connect(
            lambda: self._on_layer_color_clicked("tint"))
        tint_row, self.layer_tint_reset_button = self._field_row(
            (self.layer_tint_button,), "tint",
            lambda: self._on_reset_layer_field("tint"))
        form.addRow("Tint", tint_row)

        self.layer_text_color_button = QPushButton("Text Color…", self)
        self.layer_text_color_button.clicked.connect(
            lambda: self._on_layer_color_clicked("text_color"))
        text_color_row, self.layer_text_color_reset_button = self._field_row(
            (self.layer_text_color_button,), "text_color",
            lambda: self._on_reset_layer_field("text_color"))
        form.addRow("Text Color", text_color_row)

        self.layer_visible_check = QCheckBox("Visible", self)
        self.layer_visible_check.toggled.connect(self._on_layer_visible_toggled)
        visible_row, self.layer_visible_reset_button = self._field_row(
            (self.layer_visible_check,), "visible",
            lambda: self._on_reset_layer_field("visible"))
        form.addRow("", visible_row)

        # Base-only rows (not state-patch keys — see the section comment).
        self.layer_z_spin = _NoWheelSpinBox(self)
        self.layer_z_spin.setRange(_RECT_MIN, _RECT_MAX)
        self.layer_z_spin.setToolTip(
            "Paint order WITHIN this layer's band. The same in every state.")
        self.layer_z_spin.valueChanged.connect(self._on_layer_z_changed)
        z_row, self.layer_z_reset_button = self._field_row(
            (self.layer_z_spin,), "z",
            lambda: self._on_reset_layer_base_field("z"))
        form.addRow("Z", z_row)

        self.layer_field_band_combo = _NoWheelComboBox(self)
        self.layer_field_band_combo.addItem("Over", "over")
        self.layer_field_band_combo.addItem("Under", "under")
        self.layer_field_band_combo.setToolTip(TOOLTIP_LAYER_BAND)
        self.layer_field_band_combo.activated.connect(
            lambda _i: self._on_layer_band_changed())
        band_row, self.layer_band_reset_button = self._field_row(
            (self.layer_field_band_combo,), "band",
            lambda: self._on_reset_layer_base_field("band"))
        form.addRow("Band", band_row)

        # UL-10: clickable + target. BASE-ONLY like Z/Band — neither is a
        # state-patch key in the schema, and a layer that is a click target in
        # one state but not another is not a thing the resolver expresses.
        self.layer_clickable_check = QCheckBox("Clickable", self)
        self.layer_clickable_check.setToolTip(TOOLTIP_LAYER_CLICKABLE)
        self.layer_clickable_check.toggled.connect(
            self._on_layer_clickable_toggled)
        clickable_row, self.layer_clickable_reset_button = self._field_row(
            (self.layer_clickable_check,), "clickable",
            lambda: self._on_reset_layer_base_field("clickable"))
        form.addRow("", clickable_row)

        # Editable: D7 as amended allows an id-shaped target naming neither a
        # widget in this screen nor a reserved token. It SAVES; it warns.
        self.layer_target_combo = _NoWheelComboBox(self)
        self.layer_target_combo.setEditable(True)
        self.layer_target_combo.setToolTip(TOOLTIP_LAYER_TARGET)
        self.layer_target_combo.activated.connect(
            lambda _i: self._on_layer_target_changed())
        self.layer_target_combo.editTextChanged.connect(
            self._on_layer_target_edited)
        # Free text commits on focus-out/Enter, the `label_edit` rule — an
        # unroutable id must still be SAVABLE (D7 amended), not just typeable.
        self.layer_target_combo.lineEdit().editingFinished.connect(
            self._on_layer_target_changed)
        target_row, self.layer_target_reset_button = self._field_row(
            (self.layer_target_combo,), "target",
            lambda: self._on_reset_layer_base_field("target"))
        form.addRow("Target", target_row)

        self.layer_target_warning = QLabel("", self)
        self.layer_target_warning.setWordWrap(True)
        self.layer_target_warning.setStyleSheet("color: #d08820;")
        form.addRow("", self.layer_target_warning)

        box_layout.addLayout(form)
        return box

    # -- UL-10: clickable / target -------------------------------------------

    def _target_choices(self):
        """Every value the target picker offers: the widget ids of the OPEN
        screen (the same source `_refresh_parent_combo` reads) followed by the
        three reserved tokens. The combo is EDITABLE, so this is a
        convenience list, never a closed enum."""
        widgets = self._current_screen_defaults().get("widgets", {})
        return list(widgets) + list(RESERVED_TARGETS)

    def _target_is_routable(self, target):
        """Whether `target` names something `game.ui.skinning.hit_layer` can
        actually route: a widget id in THIS screen, or a reserved token. An
        empty target is not "unroutable" — it is simply unset, so it gets no
        warning (it swallows the click at runtime, which is `noop`)."""
        if not target:
            return True
        return (target in RESERVED_TARGETS
                or target in self._current_screen_defaults().get("widgets", {}))

    def _refresh_target_warning(self, target):
        """D7 amended's REQUIRED visible warning. Never gates the write —
        an unroutable target still saves, by design."""
        self.layer_target_warning.setText(
            "" if self._target_is_routable(target)
            else f"“{target}” names no widget in this screen and is not a "
                 "reserved token — clicking this layer will do nothing "
                 "(the click is swallowed, not passed through).")

    def _on_layer_clickable_toggled(self, checked):
        if self._populating:
            return
        # False is the schema default, so only an explicit True is stored.
        self._push_layer_base_field("clickable", True if checked else None)

    def _on_layer_target_changed(self):
        text = self.layer_target_combo.currentText().strip()
        self._refresh_target_warning(text)
        if self._populating:
            return
        self._push_layer_base_field("target", text or None)

    def _on_layer_target_edited(self, text):
        """Live warning as the designer types. Deliberately does NOT write —
        the value commits on `activated` (a picked item) or on the line
        edit's own `editingFinished`, matching `label_edit`'s rule."""
        self._refresh_target_warning((text or "").strip())

    def sync_layer_state(self, name):
        """Follow the VIEWPORT's preview-state dropdown (UL-10). Sets the
        combo with signals blocked and re-reads the inspector, so the rows
        show the state the viewport is drawing. A name this combo does not
        carry is ignored rather than snapping the selector to Idle."""
        index = self.layer_state_combo.findData(name)
        if index < 0:
            return
        self.layer_state_combo.blockSignals(True)
        self.layer_state_combo.setCurrentIndex(index)
        self.layer_state_combo.blockSignals(False)
        self._refresh_layer_inspector()

    def _state_names(self):
        """The state vocabulary, from the registry's `ui` category (the same
        data-driven list viewport.py's own state dropdown reads), falling back
        to the four D9 names when there is no `ui` category."""
        try:
            animations = tuple(self._registry.category("ui").animations)
        except (KeyError, AttributeError):
            animations = ()
        return animations or _LAYER_STATES

    # -- UL-8: reading the selected layer ------------------------------------

    def _selected_layer_entry(self):
        """A COPY of the selected layer's entry, or None when no layer node is
        selected (the session hands back a deep copy, so mutating what this
        returns cannot reach the doc)."""
        if self._current_widget is None or not self._current_layer_id:
            return None
        for entry in self._widget_layers(self._current_widget):
            if entry.get("id") == self._current_layer_id:
                return entry
        return None

    def _owner_is_button(self):
        """Whether the selected layer's OWNER is a Button — the one widget
        kind `state_of` ever resolves to something other than "idle"."""
        return self._current_spec().get("kind") == "button"

    def _layer_state(self):
        """The state the inspector's rows currently edit: the selector's value
        on a Button-owned layer, always "idle" otherwise (ruling 1)."""
        if not self._owner_is_button():
            return "idle"
        return self.layer_state_combo.currentData() or "idle"

    def _layer_state_patch(self, entry, state):
        """`entry`'s patch for `state` — engine.ui_layers._state_patch's rule,
        restated here so the form shows what the game would draw: a PRESENT
        key wins (an explicit `{}` means "looks like the base"), an absent one
        falls back to `idle`, and no `states` at all means no patch."""
        states = entry.get("states") or {}
        if not isinstance(states, dict):
            return {}
        if state in states:
            return states[state] or {}
        return states.get("idle") or {}

    def _layer_raw_value(self, entry, state, key):
        """What THIS row would reset: the value stored in the row's own scope,
        `None` when the key is absent there (push_field's sentinel)."""
        if state == "idle":
            return entry.get(key)
        patch = (entry.get("states") or {}).get(state)
        return patch.get(key) if isinstance(patch, dict) else None

    def _layer_effective_value(self, entry, state, key, default=None):
        """What the game would draw for `key` in `state` — the patch's value
        when it sets one, else the layer's own."""
        if state != "idle":
            patch = self._layer_state_patch(entry, state)
            if key in patch:
                value = patch[key]
                return default if value is None else value
        value = entry.get(key)
        return default if value is None else value

    # -- UL-8: writing (one immediate undoable push per field) ---------------

    def _push_layer_field(self, key, new_value):
        """Set (or clear, with `new_value=None`) ONE per-state key on the
        selected layer, in the scope the state selector names."""
        entry = self._selected_layer_entry()
        if entry is None or self._populating or self._session is None:
            return
        widget_id, layer_id = self._current_widget, self._current_layer_id
        state = self._layer_state()
        if self._layer_raw_value(entry, state, key) == new_value:
            return
        if state == "idle":
            self._session.set_layer_field(
                widget_id, layer_id, key,
                entry.get(key), new_value)
        else:
            old_states = entry.get("states") or None
            states = copy.deepcopy(old_states) or {}
            patch = dict(states.get(state) or {})
            if new_value is None:
                patch.pop(key, None)
            else:
                patch[key] = new_value
            if patch:
                states[state] = patch
            else:
                # An emptied patch is REMOVED, not left as `{}` — `{}` is
                # present and would pin the state to the base appearance
                # instead of restoring the idle fallback.
                states.pop(state, None)
            self._session.set_layer_field(
                widget_id, layer_id, "states", old_states, states or None,
                text=f"edit layer {layer_id}.{state}.{key}")
        self._after_layer_edit(widget_id, layer_id)

    def _push_layer_base_field(self, key, new_value):
        """`z`/`band`: always the base entry, never a state patch."""
        entry = self._selected_layer_entry()
        if entry is None or self._populating or self._session is None:
            return
        widget_id, layer_id = self._current_widget, self._current_layer_id
        self._session.set_layer_field(widget_id, layer_id, key,
                                      entry.get(key), new_value)
        self._after_layer_edit(widget_id, layer_id)

    def _after_layer_edit(self, widget_id, layer_id):
        """Redraw the outliner (a slot/z/band edit changes a node's text or
        its place in paint order) and keep the edited layer selected."""
        self._refresh_widget_list()
        self.select_layer(widget_id, layer_id)

    def _on_reset_layer_field(self, key):
        self._push_layer_field(key, None)

    def _on_reset_layer_base_field(self, key):
        entry = self._selected_layer_entry()
        if entry is None or key not in entry:
            return
        self._push_layer_base_field(key, None)

    def _on_layer_offset_changed(self, _value=None):
        self._push_layer_field("offset", [
            self.layer_off_x.value(), self.layer_off_y.value(),
            self.layer_off_w.value(), self.layer_off_h.value()])

    def _on_layer_label_edited(self):
        text = self.layer_label_edit.text()
        self._push_layer_field("label", text or None)

    def _on_layer_color_clicked(self, key):
        entry = self._selected_layer_entry()
        if entry is None:
            return
        current = self._layer_effective_value(entry, self._layer_state(), key)
        new_color = self._pick_color(list(current) if current else None)
        if new_color is None:
            return
        self._push_layer_field(key, new_color)

    def _on_layer_visible_toggled(self, checked):
        entry = self._selected_layer_entry()
        if entry is None or self._populating:
            return
        state = self._layer_state()
        if state == "idle":
            # True is the schema default, so only an explicit False is stored.
            self._push_layer_field("visible", None if checked else False)
        else:
            # In a state patch an explicit True is meaningful (a layer hidden
            # at rest can still show on hover), so the value is stored unless
            # it agrees with the base, in which case the key is cleared.
            base = entry.get("visible", True)
            self._push_layer_field("visible",
                                   None if checked == base else checked)

    def _on_layer_z_changed(self, value):
        self._push_layer_base_field("z", value)

    def _on_layer_band_changed(self):
        self._push_layer_base_field(
            "band", self.layer_field_band_combo.currentData())

    # -- UL-8: refresh -------------------------------------------------------

    def _layer_inspector_controls(self):
        return (self.layer_off_x, self.layer_off_y, self.layer_off_w,
                self.layer_off_h, self.layer_field_slot_combo,
                self.layer_label_edit, self.layer_color_button,
                self.layer_tint_button, self.layer_text_color_button,
                self.layer_visible_check, self.layer_z_spin,
                self.layer_field_band_combo,
                self.layer_clickable_check, self.layer_target_combo)

    def _layer_reset_buttons(self):
        return {"offset": self.layer_offset_reset_button,
                "slot": self.layer_slot_reset_button,
                "label": self.layer_label_reset_button,
                "color": self.layer_color_reset_button,
                "tint": self.layer_tint_reset_button,
                "text_color": self.layer_text_color_reset_button,
                "visible": self.layer_visible_reset_button,
                "z": self.layer_z_reset_button,
                "band": self.layer_band_reset_button,
                "clickable": self.layer_clickable_reset_button,
                "target": self.layer_target_reset_button}

    def _set_honest(self, control, live, dead_tooltip, live_tooltip=""):
        """Enable `control` iff the draw path actually reads its key, and give
        it the reason as a tooltip when it does not (D3)."""
        control.setEnabled(live)
        control.setToolTip(live_tooltip if live else dead_tooltip)

    def _refresh_layer_inspector(self):
        """Repopulate every inspector row from the selected layer, in the
        selected state. Called from `_refresh_layer_buttons`, i.e. after every
        selection change, tree rebuild and undo/redo."""
        entry = self._selected_layer_entry()
        has_layer = entry is not None
        is_button = has_layer and self._owner_is_button()

        # Ruling 1: hover/pressed/disabled are unreachable on a non-Button
        # holder, so the selector is greyed and pinned to Idle there rather
        # than accepting values the game will never read.
        self.layer_state_combo.setEnabled(has_layer and is_button)
        self.layer_state_combo.setToolTip(
            "" if not has_layer or is_button else TOOLTIP_STATE_BUTTON_ONLY)
        # Pinned to Idle only when a NON-Button layer is actually selected —
        # with no selection the combo keeps whatever the designer last chose
        # (a tree rebuild runs this on every edit, and stealing the state back
        # to Idle mid-gesture would send the NEXT edit to the wrong scope).
        if has_layer and not is_button:
            self.layer_state_combo.blockSignals(True)
            self.layer_state_combo.setCurrentIndex(
                max(0, self.layer_state_combo.findData("idle")))
            self.layer_state_combo.blockSignals(False)

        for control in self._layer_inspector_controls():
            control.setEnabled(has_layer)
        if not has_layer:
            self.layer_state_note.setText("")
            self.layer_target_warning.setText("")   # UL-10
            for button in self._layer_reset_buttons().values():
                button.setEnabled(False)
            return

        state = self._layer_state()
        if not is_button:
            self.layer_state_note.setText(TOOLTIP_STATE_BUTTON_ONLY)
        elif state != "idle":
            self.layer_state_note.setText(
                f"Editing the {state} state. A row you never touch falls "
                "back to Idle.")
        else:
            self.layer_state_note.setText("")

        was_populating = self._populating
        self._populating = True
        offset = self._layer_effective_value(entry, state, "offset",
                                             [0, 0, 0, 0])
        if not isinstance(offset, (list, tuple)) or len(offset) not in (2, 4):
            offset = [0, 0, 0, 0]
        if len(offset) == 2:   # the [dx, dy] patch form keeps the base's w/h
            base = entry.get("offset") or [0, 0, 0, 0]
            offset = [offset[0], offset[1], base[2], base[3]]
        for spin, value in zip((self.layer_off_x, self.layer_off_y,
                                self.layer_off_w, self.layer_off_h), offset):
            spin.setValue(int(value))
        slot = self._layer_effective_value(entry, state, "slot")
        self.layer_field_slot_combo.setCurrentIndex(
            max(0, self.layer_field_slot_combo.findData(slot)))
        self.layer_label_edit.setText(
            self._layer_effective_value(entry, state, "label", ""))
        self.layer_visible_check.setChecked(
            bool(self._layer_effective_value(entry, state, "visible", True)))
        self.layer_z_spin.setValue(int(entry.get("z", 0) or 0))
        self.layer_field_band_combo.setCurrentIndex(
            max(0, self.layer_field_band_combo.findData(
                entry.get("band", "over"))))
        # UL-10: base-only, like z/band. The picker is repopulated here (the
        # open screen's widget ids can change under an undo/rebuild) and the
        # warning recomputed from the stored value.
        self.layer_clickable_check.setChecked(bool(entry.get("clickable")))
        target = entry.get("target") or ""
        self.layer_target_combo.clear()
        self.layer_target_combo.addItems(self._target_choices())
        self.layer_target_combo.setCurrentText(target)
        self._refresh_target_warning(target)
        self._populating = was_populating

        # D3/honest controls, the FULL precedence chain (see the tooltip block
        # at the top of this module): `_submit_one_layer` draws ONE primitive,
        # first match wins — slot, else text, else colour. Whichever branch
        # this layer's effective values land in, the rows of the OTHER two are
        # dead, so they are disabled with the reason rather than silently
        # accepting a value the game will never read.
        has_slot = bool(self._layer_effective_value(entry, state, "slot"))
        has_text = bool(self._layer_effective_value(entry, state, "text_id")
                        or self._layer_effective_value(entry, state, "label"))
        # Tint rides the HudSprite call and nothing else.
        self._set_honest(self.layer_tint_button, has_slot,
                         TOOLTIP_LAYER_TINT_NEEDS_SLOT, TOOLTIP_TINT_SKINNED)
        # Text is unreachable behind a slot. With no slot and no text it stays
        # EDITABLE — typing in it is how the text branch gets created.
        self._set_honest(self.layer_label_edit, not has_slot,
                         TOOLTIP_LAYER_SLOT_WINS)
        # Text colour lives inside the text branch only.
        self._set_honest(
            self.layer_text_color_button, not has_slot and has_text,
            TOOLTIP_LAYER_SLOT_WINS if has_slot
            else TOOLTIP_LAYER_TEXT_COLOR_NEEDS_TEXT)
        # Colour is the LAST branch: it loses to a slot and to text alike.
        self._set_honest(
            self.layer_color_button, not has_slot and not has_text,
            TOOLTIP_LAYER_COLOR_INERT if has_slot else TOOLTIP_LAYER_TEXT_WINS)

        buttons = self._layer_reset_buttons()
        for key in ("offset", "slot", "label", "color", "tint", "text_color",
                    "visible"):
            buttons[key].setEnabled(
                self._layer_raw_value(entry, state, key) is not None)
        buttons["z"].setEnabled("z" in entry)
        buttons["band"].setEnabled("band" in entry)
        buttons["clickable"].setEnabled("clickable" in entry)   # UL-10
        buttons["target"].setEnabled("target" in entry)

    # -- per-widget form ---------------------------------------------------

    def _set_widget_form_enabled(self, enabled):
        for w in (self.x_spin, self.y_spin, self.w_spin, self.h_spin,
                  self.parent_combo,
                  self.skin_combo, self.font_combo, self.align_combo,
                  self.color_button,
                  self.text_color_button, self.label_edit,
                  self.text_id_combo,
                  self.visible_check, self.reset_button,
                  # UL-6: adding a layer needs only a selected widget.
                  self.layer_add_button, self.layer_slot_combo,
                  self.layer_band_combo):
            w.setEnabled(enabled)
        if not enabled:
            # UL-6: Remove/Up/Down need a selected LAYER, which there cannot
            # be without a widget.
            self._current_layer_id = None
            for btn in (self.layer_remove_button, self.layer_up_button,
                        self.layer_down_button):
                btn.setEnabled(False)
            self.layer_selected_label.setText("")
            # UL-8: and with no layer there is nothing to inspect either.
            self._refresh_layer_inspector()
            # Per-field reset buttons get their REAL enabled state (does an
            # override exist for THIS key?) from _refresh_reset_buttons,
            # called at the end of _populate_widget_form — but with no
            # widget selected there is nothing to reset, full stop.
            for btn in (self.rect_reset_button, self.parent_reset_button,
                       self.skin_reset_button,
                       self.font_reset_button, self.align_reset_button,
                       self.color_reset_button,
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
        self.align_reset_button.setEnabled("align" in override)
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
        # UL-13: a CUSTOM widget has no game-code draw site to cite, so the
        # two "is this control dead?" questions get their own (much smaller)
        # answers, straight off `skinning._submit_custom_widget`'s fixed
        # precedence: a panel/backdrop falls back to `color` whenever no skin
        # resolves, a label draws no box; a panel/label draw text, a backdrop
        # never does.
        custom = self._is_custom(self._current_widget)
        code_owned_fill = (custom_color_is_code_owned(kind) if custom
                           else color_is_code_owned(kind))
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
        tintable = skinned and (custom_tint_applies(kind) if custom
                                else kind in ("button", "panel"))
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
        code_owned = (custom_label_is_code_owned(kind) if custom
                      else label_is_code_owned(screen_id, self._current_widget,
                                               kind, text_id))
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

        # P-5/D4: the Visible row says WHY the preview shows nothing when an
        # ancestor is hidden. The checkbox stays enabled and its own override
        # is untouched — inheritance is an editor-preview rule, not data.
        hider = self._hiding_ancestor(self._current_widget)
        if hider is None:
            self.visible_check.setText("Visible")
            self.visible_check.setToolTip("")
        else:
            widgets = self._current_screen_defaults().get("widgets", {})
            name = widget_display_name(hider, widgets.get(hider))
            self.visible_check.setText(f'Visible  (hidden by parent "{name}")')
            self.visible_check.setToolTip(
                TOOLTIP_HIDDEN_BY_PARENT.format(name=name))

    def _hiding_ancestor(self, widget_id):
        """The nearest ancestor of `widget_id` carrying `visible: False`, or
        None — the same rule `viewport._hidden_subtrees` draws by, expressed
        for one widget because this panel only ever asks about the selected
        one."""
        if widget_id is None:
            return None
        overrides = self._doc_widgets()
        parents = widget_tree.parent_map(
            self._current_screen_defaults().get("widgets", {}), overrides)
        for ancestor in widget_tree.ancestors(parents, widget_id):
            if overrides.get(ancestor, {}).get("visible") is False:
                return ancestor
        return None

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

        # UL-1: baseline is the RAW override (None = absent), but the combo
        # shows the EFFECTIVE value — an unoverridden widget reads "Left",
        # which is what `submit_label` actually draws.
        align = override.get("align")
        self._align_baseline = align
        self.align_combo.setCurrentIndex(
            max(0, self.align_combo.findData(align or "left")))

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

    def _on_align_changed(self, index):
        """UL-1. Mirrors `_on_font_changed`: one key, no dependent UI, so no
        `_refresh_widget_form()` (unlike skin, which flips the honest-controls
        Color row). `push_field` is generic by key — `align` needs no
        session-side change."""
        if self._current_widget is None:
            return
        new_align = self.align_combo.itemData(index)
        old_align = self._align_baseline
        if new_align == old_align:
            return
        self._session.push_field(self._current_widget, "align",
                                 old_align, new_align)
        self._align_baseline = new_align

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
