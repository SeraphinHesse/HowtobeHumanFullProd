"""UH-3 (plan decision D3): a control that cannot take effect in the game is
disabled with an explanatory tooltip — never silently accepted.

Two layers: pure matrix tests for `editor.panels._screen_rules` (no Qt
needed) and Qt tests wiring `ScreenDetailsPanel` to a real `UIScreenSession`,
mirroring `test_editor_viewport.TestScreenDetailsPanel`'s conventions
(TempDataCase copies data/ into a tempdir; every widget is `self.track`ed).
"""
from pathlib import Path

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

import unittest

from editor.panels._screen_rules import (
    TOOLTIP_COLOR_CODE_OWNED,
    TOOLTIP_COLOR_SKINNED,
    TOOLTIP_LABEL_CODE_OWNED,
    color_is_code_owned,
    label_is_code_owned,
    resolved_skin,
)
from editor.panels.screen_details import ScreenDetailsPanel
from editor.ui_screen_session import UIScreenSession
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]

# B4-shape fixture ({screen_id: {widgets, mock_note}}) — hand-authored,
# never the live data/ui/screen_defaults.json (same "pin, don't inherit"
# rule as every other screen-mode test in this suite).
FIXTURE_DEFAULTS = {
    "main_menu": {
        "widgets": {
            "title": {"rect": [640, 100, 400, 80], "kind": "label",
                     "label": "MAIN MENU"},
        },
        "mock_note": "test fixture",
    },
    "hud": {
        "widgets": {
            "love_text": {"rect": [40, 19, 0, 0], "kind": "label",
                          "label": ""},
        },
        "mock_note": "test fixture",
    },
    "screen_a": {
        "widgets": {
            "btn": {"rect": [0, 0, 100, 30], "kind": "button", "label": "OK"},
            "panel_a": {"rect": [0, 0, 200, 100], "kind": "panel",
                       "label": ""},
            "field_a": {"rect": [0, 0, 100, 24], "kind": "field", "label": ""},
            "backdrop_a": {"rect": [0, 0, 1280, 720], "kind": "backdrop",
                          "label": ""},
            "bar_a": {"rect": [0, 0, 200, 20], "kind": "bar", "label": ""},
        },
        "mock_note": "test fixture",
    },
}


class TestLabelIsCodeOwned(unittest.TestCase):
    """Pure matrix: all six schema kinds x static-title hit/miss. No Qt."""

    def test_button_always_editable(self):
        self.assertFalse(label_is_code_owned("hud", "anything", "button"))
        self.assertFalse(label_is_code_owned("main_menu", "title", "button"))

    def test_label_kind_editable_only_for_pinned_static_titles(self):
        for screen_id, widget_id in (
            ("main_menu", "title"), ("main_menu", "subtitle"),
            ("pause", "title"), ("settings", "title"),
            ("credits", "title"), ("game_over", "title"),
            ("add_name", "title"),
        ):
            self.assertFalse(
                label_is_code_owned(screen_id, widget_id, "label"),
                msg=f"{screen_id}/{widget_id} should be the sanctioned "
                    f"static-title exception")

    def test_label_kind_code_owned_when_not_a_pinned_title(self):
        self.assertTrue(label_is_code_owned("hud", "love_text", "label"))
        self.assertTrue(label_is_code_owned("main_menu", "some_other", "label"))
        # Same widget id, different screen: the pin is per (screen, id).
        self.assertTrue(label_is_code_owned("pause", "subtitle", "label"))

    def test_non_button_non_label_kinds_always_code_owned(self):
        for kind in ("panel", "backdrop", "bar", "field"):
            self.assertTrue(label_is_code_owned("main_menu", "title", kind))


class TestResolvedSkin(unittest.TestCase):
    """Pure matrix: override wins, else kind-matched default, else None."""

    def test_per_widget_override_wins(self):
        spec = {"kind": "button"}
        override = {"skin": "ui_button_panel"}
        style = {"button_skin": "ui_button_card"}
        self.assertEqual(resolved_skin(spec, override, style), "ui_button_panel")

    def test_button_default_used_when_no_override(self):
        spec = {"kind": "button"}
        self.assertEqual(
            resolved_skin(spec, {}, {"button_skin": "ui_button_card"}),
            "ui_button_card")

    def test_panel_default_used_when_no_override(self):
        spec = {"kind": "panel"}
        self.assertEqual(
            resolved_skin(spec, {}, {"panel_skin": "ui_panel"}), "ui_panel")

    def test_button_default_does_not_leak_into_panel_kind(self):
        spec = {"kind": "panel"}
        self.assertIsNone(resolved_skin(spec, {}, {"button_skin": "ui_button"}))

    def test_none_when_nothing_resolves(self):
        self.assertIsNone(resolved_skin({"kind": "label"}, {}, {}))
        self.assertIsNone(resolved_skin({"kind": "button"}, {}, {}))


class TestColorIsCodeOwned(unittest.TestCase):
    """Pure matrix: which kinds never read `.color` at all, regardless of
    skin state (review finding — the brief's premise that unskinned panel/
    field fills read `.color` was false; grounded in real call sites, see
    `_screen_rules._COLOR_DEAD_KINDS`)."""

    def test_panel_and_field_are_code_owned(self):
        self.assertTrue(color_is_code_owned("panel"))
        self.assertTrue(color_is_code_owned("field"))

    def test_backdrop_and_bar_are_genuinely_live_not_code_owned(self):
        # backdrop.color -> HudRect(self._backdrop.rect, self._backdrop.color)
        # bar.color -> submit_bar(..., bg=self._xp_bar.color, ...)
        self.assertFalse(color_is_code_owned("backdrop"))
        self.assertFalse(color_is_code_owned("bar"))

    def test_button_is_not_code_owned_here_gated_by_skin_instead(self):
        # Button.submit's `fill = color or ...` reads `.color` whenever
        # unskinned; only a skin makes it dead, which resolved_skin (not
        # this predicate) already catches.
        self.assertFalse(color_is_code_owned("button"))

    def test_label_kind_is_also_code_owned(self):
        # Every label-kind widget renders through submit_centered(...,
        # text_color) only — text_color is live, but no label-kind widget's
        # `.color` is ever read anywhere (no box to fill on either side).
        # Final split, all six kinds accounted for: dead = panel/field/
        # label, live = button/backdrop/bar.
        self.assertTrue(color_is_code_owned("label"))


class TestHonestControlsQt(TempDataCase):
    """Qt-level: the disabled state actually lands on the real widgets and
    recomputes on every path the brief pins (§1.4)."""

    def setUp(self):
        super().setUp()
        # Same "pin, don't inherit" rule as TestScreenDetailsPanel: a screen
        # a designer has since styled in the live repo must not silently
        # change what these tests start from.
        self.empty_screens("main_menu", "hud", "screen_a")

    def make(self, screen_id):
        panel = self.track(ScreenDetailsPanel(data_dir=self.data_dir))
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open(screen_id)
        panel.set_session(session, FIXTURE_DEFAULTS)
        return panel, session

    def test_color_disabled_with_tooltip_after_skin_assign_then_reenabled(self):
        panel, session = self.make("screen_a")
        panel._populate_widget_form("btn")
        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

        idx = panel.skin_combo.findData("ui_button")
        self.assertGreaterEqual(idx, 0)
        panel.skin_combo.setCurrentIndex(idx)
        panel.skin_combo.activated.emit(idx)   # _on_skin_changed

        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_SKINNED)
        # Text Color is never gated by skin (brief §1.2) — stays enabled.
        self.assertTrue(panel.text_color_button.isEnabled())

        none_idx = panel.skin_combo.findData(None)
        panel.skin_combo.setCurrentIndex(none_idx)
        panel.skin_combo.activated.emit(none_idx)   # clear the skin

        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

    def test_undo_of_skin_assign_reenables_color(self):
        panel, session = self.make("screen_a")
        panel._populate_widget_form("btn")
        idx = panel.skin_combo.findData("ui_button")
        panel.skin_combo.setCurrentIndex(idx)
        panel.skin_combo.activated.emit(idx)
        self.assertFalse(panel.color_button.isEnabled())

        session.undo_stack.undo()   # _refresh_after_undo -> _refresh_widget_form

        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

    def test_disabled_via_default_button_skin_alone(self):
        panel, session = self.make("screen_a")
        panel._populate_widget_form("btn")   # no per-widget override
        self.assertTrue(panel.color_button.isEnabled())

        idx = panel.button_skin_combo.findData("ui_button")
        self.assertGreaterEqual(idx, 0)
        panel.button_skin_combo.setCurrentIndex(idx)
        panel.button_skin_combo.activated.emit(idx)   # _on_default_combo_changed

        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_SKINNED)

        panel._on_reset_default_field("button_skin")

        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

    def test_dead_color_override_reset_button_stays_enabled_when_skinned(self):
        """A pre-existing dead `color` override on a now-skinned widget
        keeps its per-field "reset" enabled (brief §1.5) — honest both
        ways: you can't AUTHOR a new dead override, but you can still
        remove one that predates the skin assignment."""
        panel, session = self.make("screen_a")
        session.push_field("btn", "color", None, [255, 0, 255])
        session.push_skin_assign("btn", None, "ui_button")
        panel._populate_widget_form("btn")

        self.assertFalse(panel.color_button.isEnabled())        # honest: no new dead override
        self.assertTrue(panel.color_reset_button.isEnabled())   # honest: can still remove the old one

    def test_label_edit_disabled_on_hud_readout_enabled_on_static_title(self):
        panel, _session = self.make("hud")
        panel._populate_widget_form("love_text")
        self.assertFalse(panel.label_edit.isEnabled())
        self.assertEqual(panel.label_edit.toolTip(), TOOLTIP_LABEL_CODE_OWNED)

        panel2, _session2 = self.make("main_menu")
        panel2._populate_widget_form("title")
        self.assertTrue(panel2.label_edit.isEnabled())
        self.assertEqual(panel2.label_edit.toolTip(), "")

    def test_label_edit_enabled_on_button_regardless_of_skin(self):
        panel, session = self.make("screen_a")
        panel._populate_widget_form("btn")
        self.assertTrue(panel.label_edit.isEnabled())
        session.push_skin_assign("btn", None, "ui_button")
        panel._populate_widget_form("btn")
        self.assertTrue(panel.label_edit.isEnabled())

    def test_color_disabled_code_owned_tooltip_on_unskinned_panel(self):
        """Review finding 1 (HIGH): panel-kind Color is dead on arrival even
        with NO skin at all — every submit_panel() call site hardcodes
        `fill=`, and hud.py's love_panel bypasses submit_panel entirely."""
        panel, _session = self.make("screen_a")
        panel._populate_widget_form("panel_a")
        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_CODE_OWNED)

    def test_color_disabled_code_owned_tooltip_on_unskinned_field(self):
        """Review finding 2 (MEDIUM): field-kind Color (cheat_menu's
        round_field) is dead on arrival — hardcoded HudRect fill, no skin
        path exists for `field` at all."""
        panel, _session = self.make("screen_a")
        panel._populate_widget_form("field_a")
        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_CODE_OWNED)

    def test_color_still_enabled_on_unskinned_backdrop_and_bar(self):
        """Do not over-disable the kinds the reviewer verified ARE live."""
        panel, _session = self.make("screen_a")
        panel._populate_widget_form("backdrop_a")
        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

        panel._populate_widget_form("bar_a")
        self.assertTrue(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), "")

    def test_color_disabled_code_owned_tooltip_on_unskinned_label(self):
        """Third instance of the same defect (re-review finding): label-kind
        Color is dead on arrival too — labels render through
        submit_centered(..., text_color) only, `.color` is never read.
        `text_color` stays genuinely live and must stay enabled."""
        panel, _session = self.make("main_menu")
        panel._populate_widget_form("title")
        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_CODE_OWNED)
        self.assertTrue(panel.text_color_button.isEnabled())

    def test_panel_stays_color_disabled_even_when_also_skinned(self):
        """Assigning a skin to an already-code-owned kind must not change
        the tooltip to the sprite-sheet wording — it's still dead for the
        code-owned reason, not the skin reason."""
        panel, session = self.make("screen_a")
        session.push_skin_assign("panel_a", None, "ui_panel")
        panel._populate_widget_form("panel_a")
        self.assertFalse(panel.color_button.isEnabled())
        self.assertEqual(panel.color_button.toolTip(), TOOLTIP_COLOR_CODE_OWNED)


if __name__ == "__main__":
    unittest.main()
