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

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from editor import theme_ops
from editor.panels._screen_primitives import widget_display_name
from editor.panels.balancing import (
    CollapsibleSection,
    _NoWheelComboBox,
    _NoWheelSpinBox,
)
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

_RECT_MIN, _RECT_MAX = -4096, 4096


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
        self._skin_baseline = None
        self._font_baseline = None
        self._color_baseline = None
        self._tint_baseline = None      # UH-6/D6: the Color row's OTHER key
        self._color_is_tint = False     # UH-6: which key the row is showing
        self._text_color_baseline = None
        self._label_baseline = None
        self._label_effective = None
        self._visible_baseline = None

        layout = QVBoxLayout(self)
        self._dirty_label = QLabel("", self)
        layout.addWidget(self._dirty_label)

        layout.addWidget(QLabel("Widgets", self))
        self.widget_list = QListWidget(self)
        self.widget_list.currentItemChanged.connect(self._on_widget_list_selected)
        layout.addWidget(self.widget_list)

        form = QFormLayout()
        self.x_spin = _NoWheelSpinBox(self)
        self.y_spin = _NoWheelSpinBox(self)
        self.w_spin = _NoWheelSpinBox(self)
        self.h_spin = _NoWheelSpinBox(self)
        for spin, (lo, hi) in ((self.x_spin, (_RECT_MIN, _RECT_MAX)),
                               (self.y_spin, (_RECT_MIN, _RECT_MAX)),
                               (self.w_spin, (1, _RECT_MAX)),
                               (self.h_spin, (1, _RECT_MAX))):
            spin.setRange(lo, hi)
            spin.editingFinished.connect(self._on_rect_edited)
        # ONE reset for the whole rect group — it's stored as a single
        # `rect` key, not four (brief §1d: per-KEY granularity, not per-spin).
        rect_row, self.rect_reset_button = self._field_row(
            (self.x_spin, self.y_spin, self.w_spin, self.h_spin),
            "rect", lambda: self._on_reset_field("rect"))
        form.addRow("Rect (X Y W H)", rect_row)

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
        form.addRow("Label", label_row)

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

    def _refresh_widget_list(self):
        self.widget_list.blockSignals(True)
        self.widget_list.clear()
        widgets = self._current_screen_defaults().get("widgets", {})
        for widget_id, spec in widgets.items():
            item = QListWidgetItem(widget_display_name(widget_id, spec))
            item.setToolTip(widget_id)
            item.setData(Qt.ItemDataRole.UserRole, widget_id)
            self.widget_list.addItem(item)
        self.widget_list.blockSignals(False)

    def _on_widget_list_selected(self, current, _previous=None):
        if current is None:
            return
        widget_id = current.data(Qt.ItemDataRole.UserRole)
        self._populate_widget_form(widget_id)
        self.widget_selected.emit(widget_id)

    def select_widget(self, widget_id):
        """External sync (the viewport tells us a widget was clicked/
        dragged there) — populates the form WITHOUT re-emitting
        widget_selected (avoids a viewport<->panel selection feedback loop).
        Matches on `Qt.ItemDataRole.UserRole` (the code id), never item TEXT
        — display names are not guaranteed unique, the id is (UH-4)."""
        target_row = -1
        for row in range(self.widget_list.count()):
            if self.widget_list.item(row).data(
                    Qt.ItemDataRole.UserRole) == widget_id:
                target_row = row
                break
        self.widget_list.blockSignals(True)
        self.widget_list.setCurrentRow(target_row)
        self.widget_list.blockSignals(False)
        if widget_id:
            self._populate_widget_form(widget_id)
        else:
            self._current_widget = None
            self._set_widget_form_enabled(False)

    # -- per-widget form ---------------------------------------------------

    def _set_widget_form_enabled(self, enabled):
        for w in (self.x_spin, self.y_spin, self.w_spin, self.h_spin,
                  self.skin_combo, self.font_combo, self.color_button,
                  self.text_color_button, self.label_edit,
                  self.visible_check, self.reset_button):
            w.setEnabled(enabled)
        if not enabled:
            # Per-field reset buttons get their REAL enabled state (does an
            # override exist for THIS key?) from _refresh_reset_buttons,
            # called at the end of _populate_widget_form — but with no
            # widget selected there is nothing to reset, full stop.
            for btn in (self.rect_reset_button, self.skin_reset_button,
                       self.font_reset_button, self.color_reset_button,
                       self.text_color_reset_button, self.label_reset_button,
                       self.visible_reset_button):
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
        self.skin_reset_button.setEnabled("skin" in override)
        self.font_reset_button.setEnabled("font" in override)
        self.color_reset_button.setEnabled(self._active_color_key() in override)
        self.text_color_reset_button.setEnabled("text_color" in override)
        self.label_reset_button.setEnabled("label" in override)
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
        # UH-6 (D6) repurposes the color row as Tint on a skinned widget: the
        # sheet IS drawn, so a per-widget multiply is live and honest. UH-3's
        # honest-controls rule otherwise disables Color for the kinds whose
        # fill the game hardcodes (panel/field/label). Skinned wins — a drawn
        # sheet can be tinted even for a code-owned-fill kind, so the row is
        # only ever disabled when unskinned AND code-owned.
        self._color_is_tint = skinned
        if skinned:
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

        code_owned = label_is_code_owned(screen_id, self._current_widget, kind)
        self.label_edit.setEnabled(not code_owned)
        self.label_edit.setToolTip(TOOLTIP_LABEL_CODE_OWNED if code_owned else "")

    def _populate_widget_form(self, widget_id):
        defaults = self._current_screen_defaults()
        spec = defaults.get("widgets", {}).get(widget_id)
        if spec is None or self._session is None or self._session.doc is None:
            return
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

        skin = override.get("skin")
        self._skin_baseline = skin
        self.skin_combo.setCurrentIndex(max(0, self.skin_combo.findData(skin)))

        font = override.get("font")
        self._font_baseline = font
        self.font_combo.setCurrentIndex(max(0, self.font_combo.findData(font)))

        self._color_baseline = override.get("color")
        self._tint_baseline = override.get("tint")   # UH-6/D6
        self._text_color_baseline = override.get("text_color")

        label = override.get("label", spec.get("label", ""))
        self.label_edit.setText(label)
        self._label_baseline = override.get("label")
        self._label_effective = label

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

    def _on_rect_edited(self):
        if self._current_widget is None or self._populating:
            return
        new_rect = [self.x_spin.value(), self.y_spin.value(),
                   self.w_spin.value(), self.h_spin.value()]
        if new_rect == self._rect_effective:
            return   # nothing actually changed from what's on screen
        self._session.push_move(self._current_widget, self._rect_baseline, new_rect)
        self._rect_baseline = new_rect
        self._rect_effective = new_rect

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
        self._session.push_field(
            self._current_widget, "label", self._label_baseline, new_label)
        self._label_baseline = new_label
        self._label_effective = new_label

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
        old_value = override[field_key]
        self._session.push_field(widget_id, field_key, old_value, None)
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
            self._session.push_field(widget_id, field_key, old_value, None)
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
