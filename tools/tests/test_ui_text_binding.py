"""UT-1 — the `text_id` widget<->string binding.

Two layers, mirroring `test_screen_honest_controls.py`: pure game-side tests
for `widgets.submit_label` / `ScreenSkinning.apply` (no Qt), then a Qt test
for `UIScreenSession.push_string` against a TempDataCase copy of the tree.
"""
from pathlib import Path

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP

import unittest

from engine import data_io
from game.ui import widgets
from game.ui.skinning import ScreenSkinning
from editor.ui_screen_session import UIScreenSession
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]


class _RecordingRenderer:
    def __init__(self):
        self.items = []

    def submit_hud(self, item):
        self.items.append(item)


class TestSubmitLabel(unittest.TestCase):
    def test_text_id_resolves_through_the_string_table(self):
        r = _RecordingRenderer()
        h = widgets.label_holder((10, 20, 0, 0), text_id="hud.lives")
        widgets.submit_label(r, h, count=3)
        self.assertEqual(len(r.items), 1)
        self.assertEqual(r.items[0].text, "LIVES 3")
        self.assertEqual(r.items[0].pos, (10, 20))

    def test_static_label_when_no_text_id(self):
        r = _RecordingRenderer()
        widgets.submit_label(r, widgets.label_holder((1, 2, 0, 0), label="HP"))
        self.assertEqual(r.items[0].text, "HP")

    def test_invisible_and_empty_draw_nothing(self):
        r = _RecordingRenderer()
        widgets.submit_label(r, widgets.label_holder(label="HP", visible=False))
        widgets.submit_label(r, widgets.label_holder(label=""))
        self.assertEqual(r.items, [])

    def test_text_color_override_wins_over_the_computed_color(self):
        r = _RecordingRenderer()
        h = widgets.label_holder(label="HP")
        widgets.submit_label(r, h, color=(1, 2, 3))
        h.text_color = (9, 9, 9)
        widgets.submit_label(r, h, color=(1, 2, 3))
        self.assertEqual([i.color for i in r.items], [(1, 2, 3), (9, 9, 9)])

    def test_align_comes_off_the_holder_unless_the_call_site_overrides(self):
        r = _RecordingRenderer()
        h = widgets.label_holder(label="HP", align="right")
        widgets.submit_label(r, h)
        widgets.submit_label(r, h, align="center")
        self.assertEqual([i.align for i in r.items], ["right", "center"])


class TestSkinningThreadsTextId(unittest.TestCase):
    """`apply()`'s generic setattr loop needs no `_SPEC_TO_ATTR` entry for
    `text_id` — the same free ride `skin`/`tint` get."""

    def test_text_id_override_repoints_a_holder(self):
        sk = ScreenSkinning.empty()
        sk._overrides = {"hud": {"widgets": {"lives_text":
                                             {"text_id": "hud.round"}}}}
        h = widgets.label_holder(text_id="hud.lives")
        sk.apply("hud", {"lives_text": ("label", h)})
        self.assertEqual(h.text_id, "hud.round")

        r = _RecordingRenderer()
        widgets.submit_label(r, h, n=7)
        self.assertEqual(r.items[0].text, "ROUND 7")


class TestPushString(TempDataCase):
    def _session(self):
        s = UIScreenSession(data_dir=self.data_dir)
        s.open("hud")
        return s

    def test_edit_is_undoable_and_tracks_dirty_by_value(self):
        s = self._session()
        old = s.strings_doc["hud.lives"]
        self.assertFalse(s.strings_dirty)

        s.push_string("hud.lives", old, "LEVEN {count}")
        self.assertEqual(s.strings_doc["hud.lives"], "LEVEN {count}")
        self.assertTrue(s.strings_dirty)
        self.assertTrue(s.dirty)

        s.undo_stack.undo()
        self.assertEqual(s.strings_doc["hud.lives"], old)
        self.assertFalse(s.strings_dirty)

    def test_save_writes_the_table_only_when_it_changed(self):
        path = Path(self.data_dir) / "ui" / "strings.json"
        before = path.read_bytes()

        s = self._session()
        s.save()
        self.assertEqual(path.read_bytes(), before)

        s.push_string("hud.lives", s.strings_doc["hud.lives"], "LEVEN {count}")
        s.save()
        self.assertEqual(
            data_io.load_json(path)["hud.lives"], "LEVEN {count}")
        self.assertFalse(s.strings_dirty)

    def test_unknown_id_is_refused(self):
        s = self._session()
        s.push_string("not.a.real.id", None, "nope")
        self.assertNotIn("not.a.real.id", s.strings_doc)
        self.assertFalse(s.strings_dirty)

class TestTextTemplateForm(TempDataCase):
    """UT-6: a widget bound to a string id shows an EDITABLE template row,
    not the old "edit it in game code, not here" disablement."""

    def _panel(self, screen_id="building_panel", view="upgrade",
               widget_id="stat_hp_label"):
        from editor.panels.screen_details import ScreenDetailsPanel

        # The session is PARENTED to the panel: the panel connects to its
        # undo stack, and a stack outliving a destroyed panel emits into a
        # dead C++ object at teardown.
        panel = self.track(ScreenDetailsPanel(data_dir=self.data_dir))
        session = UIScreenSession(data_dir=self.data_dir, parent=panel)
        session.open(screen_id)
        session.set_view(view)
        panel.set_session(session)
        panel.set_defaults(data_io.load_json(
            Path(self.data_dir) / "ui" / "screen_defaults.json"))
        panel.select_widget(widget_id)
        return panel, session

    def test_bound_widget_shows_its_template_editable(self):
        panel, _ = self._panel()
        self.assertTrue(panel.label_edit.isEnabled())
        self.assertEqual(panel.label_row_label.text(), "Text template")
        self.assertEqual(panel.label_edit.text(), "HP")
        self.assertIn("HP", panel.sample_label.text())

    def test_editing_the_template_writes_the_string_table(self):
        panel, session = self._panel()
        panel.label_edit.setText("Health")
        panel._on_label_edited()
        self.assertEqual(session.strings_doc["building.stat.hp"], "Health")
        self.assertTrue(session.strings_dirty)
        # and it is one undoable step, across both docs
        session.undo_stack.undo()
        self.assertEqual(session.strings_doc["building.stat.hp"], "HP")

    def test_unbound_widget_keeps_the_per_widget_label(self):
        panel, session = self._panel(screen_id="main_menu", view=None,
                                     widget_id="title")
        self.assertEqual(panel.label_row_label.text(), "Label")
        panel.label_edit.setText("HELLO")
        panel._on_label_edited()
        self.assertEqual(
            session.doc["widgets"]["title"]["label"], "HELLO")
        self.assertFalse(session.strings_dirty)

    def test_shared_template_warns_how_many_widgets_use_it(self):
        panel, _ = self._panel(widget_id="stat_hp_value")
        # every stat VALUE cell shares building.stat.value
        self.assertIn("used by", panel.sample_label.text())


if __name__ == "__main__":
    unittest.main()
