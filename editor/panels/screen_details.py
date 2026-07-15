"""ScreenDetailsPanel (B4, R3) — the right-pane form shown while a UI-screen
leaf is selected (screen mode's sibling of MapDetailsPanel/DetailsPanel in
the right_stack QStackedWidget).

Structure: a widget-id list (from the loaded screen_defaults, B3) driving a
per-widget form (rect spinboxes, skin/font/color, label, visible, a
"Reset to default" button that clears every override on that widget), then a
screen-level section (background picker, and the `defaults` collapsible:
button_skin/panel_skin/font/text_color), then Save.

Every edit is an IMMEDIATE undoable command through the open
UIScreenSession (never staged like balancing.py) — push_move/push_field/
push_skin_assign/push_background/push_default_field. Save just calls
session.save() (engine.data_io.write_validated under the hood).

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
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from editor.panels.balancing import (
    CollapsibleSection,
    _NoWheelComboBox,
    _NoWheelSpinBox,
)
from engine.assets import load_registry

REPO = Path(__file__).resolve().parents[2]

# Mirrors engine/render/fonts.py's _FONT_SPECS keys (private to that module —
# duplicated here rather than reaching across the module boundary for a
# leading-underscore name; keep in sync if fonts.py's key set changes).
_FONT_KEYS = ("sm", "md", "lg", "xl", "xxl", "hud_phase", "hud_lvl")

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
        self._text_color_baseline = None
        self._label_baseline = None
        self._label_effective = None
        self._visible_baseline = None

        layout = QVBoxLayout(self)
        self._dirty_label = QLabel("", self)
        layout.addWidget(self._dirty_label)

        layout.addWidget(QLabel("Widgets", self))
        self.widget_list = QListWidget(self)
        self.widget_list.currentTextChanged.connect(self._on_widget_list_selected)
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
        form.addRow("X", self.x_spin)
        form.addRow("Y", self.y_spin)
        form.addRow("W", self.w_spin)
        form.addRow("H", self.h_spin)

        self.skin_combo = _NoWheelComboBox(self)
        self.skin_combo.activated.connect(self._on_skin_changed)
        form.addRow("Skin", self.skin_combo)

        self.font_combo = _NoWheelComboBox(self)
        self.font_combo.activated.connect(self._on_font_changed)
        form.addRow("Font", self.font_combo)

        self.color_button = QPushButton("Color…", self)
        self.color_button.clicked.connect(self._on_color_clicked)
        form.addRow("Color", self.color_button)

        self.text_color_button = QPushButton("Text Color…", self)
        self.text_color_button.clicked.connect(self._on_text_color_clicked)
        form.addRow("Text Color", self.text_color_button)

        self.label_edit = QLineEdit(self)
        self.label_edit.editingFinished.connect(self._on_label_edited)
        form.addRow("Label", self.label_edit)

        self.visible_check = QCheckBox("Visible", self)
        self.visible_check.toggled.connect(self._on_visible_toggled)
        form.addRow("", self.visible_check)

        layout.addLayout(form)

        self.reset_button = QPushButton("Reset to default", self)
        self.reset_button.clicked.connect(self._on_reset_clicked)
        layout.addWidget(self.reset_button)

        # -- screen-level section --------------------------------------------
        layout.addWidget(QLabel("Background", self))
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
        defaults_form.addRow("Button skin", self.button_skin_combo)
        self.panel_skin_combo = _NoWheelComboBox(self)
        self.panel_skin_combo.activated.connect(
            lambda i: self._on_default_combo_changed("panel_skin", self.panel_skin_combo))
        defaults_form.addRow("Panel skin", self.panel_skin_combo)
        self.default_font_combo = _NoWheelComboBox(self)
        self.default_font_combo.activated.connect(
            lambda i: self._on_default_combo_changed("font", self.default_font_combo))
        defaults_form.addRow("Font", self.default_font_combo)
        self.default_text_color_button = QPushButton("Text Color…", self)
        self.default_text_color_button.clicked.connect(
            self._on_default_text_color_clicked)
        defaults_form.addRow("Text color", self.default_text_color_button)
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
        for key in _FONT_KEYS:
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
        if self._session is None or self._session.doc is None:
            return {}
        return self._all_defaults.get(self._session.screen_id, {})

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
        for widget_id in self._current_screen_defaults().get("widgets", {}):
            self.widget_list.addItem(widget_id)
        self.widget_list.blockSignals(False)

    def _on_widget_list_selected(self, widget_id):
        if not widget_id:
            return
        self._populate_widget_form(widget_id)
        self.widget_selected.emit(widget_id)

    def select_widget(self, widget_id):
        """External sync (the viewport tells us a widget was clicked/
        dragged there) — populates the form WITHOUT re-emitting
        widget_selected (avoids a viewport<->panel selection feedback loop)."""
        items = self.widget_list.findItems(
            widget_id or "", Qt.MatchFlag.MatchExactly)
        self.widget_list.blockSignals(True)
        if items:
            self.widget_list.setCurrentItem(items[0])
        else:
            self.widget_list.setCurrentRow(-1)
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
        if self._current_widget is None:
            return
        new_color = self._pick_color(self._color_baseline)
        if new_color is None or new_color == self._color_baseline:
            return
        self._session.push_field(
            self._current_widget, "color", self._color_baseline, new_color)
        self._color_baseline = new_color

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

    def _on_reset_clicked(self):
        """Clears EVERY override on the selected widget, one undoable
        push_field per field — the last one pops the (now-empty) widget
        entry out of the doc entirely via _DocFieldCommand's pruning."""
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
            return
        background = self._session.doc.get("background") or {}
        self.background_combo.blockSignals(True)
        idx = self.background_combo.findData(background.get("slot"))
        self.background_combo.setCurrentIndex(max(0, idx))
        self.background_combo.blockSignals(False)

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

    # -- screen-level: defaults -------------------------------------------------

    def _refresh_defaults_section(self):
        if self._session is None or self._session.doc is None:
            for combo in (self.button_skin_combo, self.panel_skin_combo,
                         self.default_font_combo):
                combo.setCurrentIndex(0)
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

    def _on_default_combo_changed(self, field_key, combo):
        style = self._session.doc.get("defaults", {})
        old_value = style.get(field_key)
        new_value = combo.itemData(combo.currentIndex())
        if old_value == new_value:
            return
        self._session.push_default_field(field_key, old_value, new_value)
        self._refresh_defaults_section()

    def _on_default_text_color_clicked(self):
        style = self._session.doc.get("defaults", {})
        old_value = style.get("text_color")
        new_value = self._pick_color(old_value)
        if new_value is None or new_value == old_value:
            return
        self._session.push_default_field("text_color", old_value, new_value)

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
