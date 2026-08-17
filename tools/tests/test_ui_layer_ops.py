"""UL-6: layer ops on the open screen doc, and layers in the outliner.

Two layers, both Qt (the session owns a `QUndoStack`, the panel is a real
`ScreenDetailsPanel`), following `test_screen_honest_controls`' conventions:
`TempDataCase` copies `data/` into a tempdir so nothing here can write into
the repo, screens are PINNED to `{}` with `empty_screens`, defaults are a
hand-authored fixture rather than the live `screen_defaults.json`, and every
widget is `self.track`ed.

The one architectural fact these tests pin: a widget's `layers` is an ARRAY,
so every layer op is ONE `_DocFieldCommand` carrying the FULL old and new
ARRAY at `("widgets", <id>, "layers")` — not a per-layer path, which would
write an object where the schema demands an array. One op, one undo step, and
the doc validates after each (asserted by round-tripping through
`session.save()`, i.e. `engine.data_io.write_validated`).

EXPLICIT INSERTION POINTS FOR FUTURE PHASES:
- UL-7 will add class TestLayerViewportGeometry (append to this file, do not
  edit TestLayerOps)
- UL-8 will add class TestLayerStateInspector (append to this file, do not
  edit TestLayerOps)
"""
# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP  # noqa: F401

from PySide6.QtCore import Qt

from editor.panels.screen_details import ScreenDetailsPanel
from editor.ui_screen_session import UIScreenSession
from tools.tests.test_editor_panels import TempDataCase

FIXTURE_DEFAULTS = {
    "hud": {
        "widgets": {
            "love_panel": {"rect": [20, 10, 200, 40], "kind": "panel",
                           "label": ""},
            "love_text": {"rect": [40, 19, 0, 0], "kind": "label",
                          "label": "", "parent": "love_panel"},
        },
        "mock_note": "test fixture",
    },
}


class _LayerCase(TempDataCase):
    def setUp(self):
        super().setUp()
        self.empty_screens("hud")
        self.session = self.track(UIScreenSession(data_dir=self.data_dir))
        self.session.open("hud")

    def doc_layers(self, widget_id="love_text"):
        """The RAW array in the doc (not the session's defensive copy)."""
        return self.session.doc.get("widgets", {}).get(widget_id, {}).get(
            "layers")

    def assert_doc_validates(self):
        """Round-trip through write_validated + load_validated: an op that
        left the doc schema-invalid raises here."""
        self.session.save()
        reopened = self.track(UIScreenSession(data_dir=self.data_dir))
        return reopened.open("hud")


class TestLayerOps(_LayerCase):
    """The session API: add / remove / set_layer_field / reorder."""

    def test_add_layer_appends_entry_and_forces_its_id(self):
        self.session.add_layer("love_text", "layer_1",
                               {"slot": "ui_panel", "offset": [1, 2, 0, 0],
                                "z": 0, "band": "under"})
        self.assertEqual(self.doc_layers(), [
            {"id": "layer_1", "slot": "ui_panel", "offset": [1, 2, 0, 0],
             "z": 0, "band": "under"}])
        self.assertEqual(self.assert_doc_validates()["widgets"]["love_text"]
                         ["layers"][0]["id"], "layer_1")

    def test_add_layer_is_exactly_one_undo_command(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_undo_of_an_add_prunes_the_widget_entry_again(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.undo_stack.undo()
        # "None = absent": the layers key AND the now-empty widget entry go.
        self.assertEqual(self.session.doc, {})
        self.session.undo_stack.redo()
        self.assertEqual(len(self.doc_layers()), 1)

    def test_add_layer_refuses_a_duplicate_id(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.add_layer("love_text", "layer_1", {"z": 5})
        self.assertEqual(len(self.doc_layers()), 1)
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_add_layer_refuses_an_empty_id(self):
        self.session.add_layer("love_text", "", {"z": 0})
        self.assertIsNone(self.doc_layers())
        self.assertEqual(self.session.undo_stack.count(), 0)

    def test_remove_layer_drops_only_that_entry(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.add_layer("love_text", "layer_2", {"z": 1})
        self.session.remove_layer("love_text", "layer_1")
        self.assertEqual([e["id"] for e in self.doc_layers()], ["layer_2"])
        self.assert_doc_validates()

    def test_removing_the_last_layer_prunes_the_array(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.remove_layer("love_text", "layer_1")
        self.assertEqual(self.session.doc, {})   # never a lingering []
        self.session.undo_stack.undo()
        self.assertEqual([e["id"] for e in self.doc_layers()], ["layer_1"])

    def test_remove_layer_leaves_other_overrides_alone(self):
        self.session.push_field("love_text", "visible", None, False)
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.remove_layer("love_text", "layer_1")
        self.assertEqual(self.session.doc["widgets"]["love_text"],
                         {"visible": False})

    def test_remove_layer_of_an_unknown_id_is_a_no_op(self):
        self.session.remove_layer("love_text", "nope")
        self.assertEqual(self.session.undo_stack.count(), 0)

    def test_set_layer_field_patches_one_key(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.set_layer_field("love_text", "layer_1", "slot",
                                     None, "ui_panel")
        self.assertEqual(self.doc_layers()[0],
                         {"id": "layer_1", "z": 0, "slot": "ui_panel"})
        self.assert_doc_validates()

    def test_set_layer_field_with_none_clears_the_key(self):
        self.session.add_layer("love_text", "layer_1",
                               {"z": 0, "slot": "ui_panel"})
        self.session.set_layer_field("love_text", "layer_1", "slot",
                                     "ui_panel", None)
        self.assertEqual(self.doc_layers()[0], {"id": "layer_1", "z": 0})

    def test_set_layer_field_refuses_a_no_op(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.set_layer_field("love_text", "layer_1", "z", 0, 0)
        self.assertEqual(self.session.undo_stack.count(), 1)   # the add only

    def test_reorder_layer_changes_only_z(self):
        self.session.add_layer("love_text", "layer_1",
                               {"z": 0, "band": "over", "slot": "ui_panel"})
        self.session.reorder_layer("love_text", "layer_1", 7)
        self.assertEqual(self.doc_layers()[0],
                         {"id": "layer_1", "z": 7, "band": "over",
                          "slot": "ui_panel"})
        self.assertEqual(self.session.undo_stack.count(), 2)
        self.session.undo_stack.undo()
        self.assertEqual(self.doc_layers()[0]["z"], 0)

    def test_layers_reader_hands_back_a_copy(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        read = self.session.layers("love_text")
        read[0]["z"] = 99
        read.append({"id": "sneaky"})
        self.assertEqual(self.doc_layers(), [{"id": "layer_1", "z": 0}])
        self.assertEqual(self.session.layers("nothing_here"), [])

    def test_ids_stay_unique_across_add_remove_add(self):
        self.session.add_layer("love_text", "layer_1", {"z": 0})
        self.session.add_layer("love_text", "layer_2", {"z": 1})
        self.session.remove_layer("love_text", "layer_1")
        self.session.add_layer("love_text", "layer_1", {"z": 2})
        ids = [e["id"] for e in self.doc_layers()]
        self.assertEqual(sorted(ids), ["layer_1", "layer_2"])
        self.assertEqual(len(set(ids)), len(ids))

    def test_d5_a_screen_with_no_layers_authored_stays_byte_identical(self):
        path = self.data_dir / "ui" / "screens" / "hud.json"
        before = path.read_bytes()
        self.session.save()
        self.assertEqual(path.read_bytes(), before)


class TestLayerOutliner(_LayerCase):
    """The panel: layer nodes in the tree + the Add/Remove/Up/Down controls."""

    def setUp(self):
        super().setUp()
        self.panel = self.track(ScreenDetailsPanel(data_dir=self.data_dir))
        self.panel.set_session(self.session, FIXTURE_DEFAULTS)

    def layer_items(self, widget_id="love_text"):
        item = self.panel._tree_items[widget_id]
        return [item.child(i) for i in range(item.childCount())]

    def role_of(self, item):
        return item.data(0, Qt.ItemDataRole.UserRole)

    def test_layer_nodes_hang_under_their_widget_with_a_tuple_role(self):
        self.session.add_layer("love_text", "layer_1",
                               {"z": 0, "slot": "ui_panel"})
        self.panel._refresh_widget_list()
        children = self.layer_items()
        self.assertEqual(len(children), 1)
        self.assertEqual(self.role_of(children[0]), ("love_text", "layer_1"))
        # Widget nodes keep the bare-id contract they have always had.
        self.assertEqual(self.role_of(self.panel._tree_items["love_text"]),
                         "love_text")
        self.assertIn("ui_panel", children[0].text(0))

    def test_layers_are_listed_under_band_first_then_over_by_z(self):
        for layer_id, band, z in (("layer_1", "over", 5),
                                  ("layer_2", "under", 1),
                                  ("layer_3", "over", 0)):
            self.session.add_layer("love_text", layer_id,
                                   {"band": band, "z": z})
        self.panel._refresh_widget_list()
        self.assertEqual([self.role_of(i)[1] for i in self.layer_items()],
                         ["layer_2", "layer_3", "layer_1"])

    def test_add_button_creates_a_layer_and_selects_it(self):
        self.panel.select_widget("love_text")
        idx = self.panel.layer_slot_combo.findData("ui_panel")
        self.assertGreaterEqual(idx, 0)
        self.panel.layer_slot_combo.setCurrentIndex(idx)
        self.panel.layer_add_button.click()

        self.assertEqual(self.doc_layers(), [
            {"id": "layer_1", "offset": [0, 0, 0, 0], "z": 0,
             "band": "over", "slot": "ui_panel"}])
        self.assertEqual(self.panel._current_layer_id, "layer_1")
        self.assertEqual(len(self.layer_items()), 1)
        self.assertTrue(self.panel.layer_remove_button.isEnabled())
        self.assert_doc_validates()

    def test_add_button_generates_a_fresh_id_each_time(self):
        self.panel.select_widget("love_text")
        self.panel.layer_add_button.click()
        self.panel.layer_add_button.click()
        self.assertEqual([e["id"] for e in self.doc_layers()],
                         ["layer_1", "layer_2"])

    def test_remove_button_removes_the_selected_layer_only(self):
        self.panel.select_widget("love_text")
        self.panel.layer_add_button.click()
        self.panel.layer_add_button.click()
        self.panel.select_layer("love_text", "layer_1")
        self.panel.layer_remove_button.click()
        self.assertEqual([e["id"] for e in self.doc_layers()], ["layer_2"])
        self.assertEqual(len(self.layer_items()), 1)
        self.assertIsNone(self.panel._current_layer_id)
        self.assertFalse(self.panel.layer_remove_button.isEnabled())

    def test_undo_puts_the_layer_node_back_in_the_tree(self):
        self.panel.select_widget("love_text")
        self.panel.layer_add_button.click()
        self.panel.layer_remove_button.click()
        self.assertEqual(self.layer_items(), [])

        self.session.undo_stack.undo()          # undo the remove
        self.assertEqual(len(self.layer_items()), 1)
        self.session.undo_stack.undo()          # undo the add
        self.assertEqual(self.layer_items(), [])
        self.assertEqual(self.session.doc, {})

    def test_selecting_a_layer_node_still_selects_its_owner_widget(self):
        seen = []
        self.panel.widget_selected.connect(seen.append)
        self.panel.select_widget("love_text")
        self.panel.layer_add_button.click()
        item = self.panel._layer_items[("love_text", "layer_1")]

        self.panel._on_widget_list_selected(item)

        self.assertEqual(seen[-1], "love_text")
        self.assertEqual(self.panel._current_widget, "love_text")
        self.assertEqual(self.panel._current_layer_id, "layer_1")
        # The FORM stays the widget's (per-layer inspection is UL-8).
        self.assertEqual(self.panel.x_spin.value(), 40)

    def test_up_and_down_reorder_within_the_band(self):
        self.panel.select_widget("love_text")
        self.panel.layer_add_button.click()     # layer_1, z 0
        self.panel.layer_add_button.click()     # layer_2, z 0 (after it)
        self.panel.select_layer("love_text", "layer_2")
        self.assertTrue(self.panel.layer_up_button.isEnabled())
        self.assertFalse(self.panel.layer_down_button.isEnabled())

        self.panel.layer_up_button.click()

        self.assertEqual([self.role_of(i)[1] for i in self.layer_items()],
                         ["layer_2", "layer_1"])
        self.assertEqual(self.panel._current_layer_id, "layer_2")
        self.assertFalse(self.panel.layer_up_button.isEnabled())
        self.assertTrue(self.panel.layer_down_button.isEnabled())

        self.panel.layer_down_button.click()
        self.assertEqual([self.role_of(i)[1] for i in self.layer_items()],
                         ["layer_1", "layer_2"])

    def test_layer_buttons_are_dead_with_no_widget_selected(self):
        self.panel.select_widget(None)
        self.assertFalse(self.panel.layer_add_button.isEnabled())
        self.assertFalse(self.panel.layer_remove_button.isEnabled())
        self.assertFalse(self.panel.layer_up_button.isEnabled())
        self.assertFalse(self.panel.layer_down_button.isEnabled())
