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


class TestLayerStateInspector(_LayerCase):
    """UL-8: the per-layer, per-state inspector (state selector + the rows
    below it). The two rulings this phase carries are pinned here:

    1. hover/pressed/disabled are greyed on a NON-Button holder — `state_of`
       resolves such a widget to "idle" forever, so per-state values on it
       would be unreachable.
    2. `z`/`band` are NOT state-patch keys, so those rows always write the
       base entry whatever the selector says.
    """

    # Its OWN fixture (UL-6's has no `button`, and ruling 1 turns on the
    # widget KIND) — never a mutation of the shared FIXTURE_DEFAULTS above.
    DEFAULTS = {
        "hud": {
            "widgets": {
                "love_text": {"rect": [40, 19, 0, 0], "kind": "label",
                              "label": ""},
                "btn_go": {"rect": [10, 60, 90, 30], "kind": "button",
                           "label": "Go"},
            },
            "mock_note": "UL-8 fixture",
        },
    }

    def setUp(self):
        super().setUp()
        self.panel = self.track(ScreenDetailsPanel(data_dir=self.data_dir))
        self.panel.set_session(self.session, self.DEFAULTS)

    def select_state(self, state):
        combo = self.panel.layer_state_combo
        combo.setCurrentIndex(combo.findData(state))
        self.panel._refresh_layer_inspector()

    def add_layer_on(self, widget_id="btn_go", **spec):
        self.panel.select_widget(widget_id)
        self.session.add_layer(widget_id, "layer_1", spec or {"z": 0})
        self.panel._refresh_widget_list()
        self.panel.select_layer(widget_id, "layer_1")

    def entry(self, widget_id="btn_go"):
        return self.doc_layers(widget_id)[0]

    # -- per-state writes ---------------------------------------------------

    def test_a_hover_edit_lands_under_states_and_leaves_the_base_alone(self):
        self.add_layer_on(offset=[1, 2, 0, 0], z=0)
        self.select_state("hover")
        self.panel._push_layer_field("offset", [5, 6, 0, 0])
        self.assertEqual(self.entry(), {
            "id": "layer_1", "offset": [1, 2, 0, 0], "z": 0,
            "states": {"hover": {"offset": [5, 6, 0, 0]}}})
        self.assert_doc_validates()

    def test_an_idle_edit_writes_the_base_entry(self):
        self.add_layer_on(z=0)
        self.select_state("idle")
        self.panel._push_layer_field("offset", [3, 4, 0, 0])
        self.assertEqual(self.entry(),
                         {"id": "layer_1", "z": 0, "offset": [3, 4, 0, 0]})

    def test_a_second_state_does_not_disturb_the_first(self):
        self.add_layer_on(z=0)
        self.select_state("hover")
        self.panel._push_layer_field("text_color", [1, 2, 3])
        self.select_state("pressed")
        self.panel._push_layer_field("offset", [0, 1, 0, 0])
        self.assertEqual(self.entry()["states"],
                         {"hover": {"text_color": [1, 2, 3]},
                          "pressed": {"offset": [0, 1, 0, 0]}})

    def test_each_per_state_edit_is_exactly_one_undo_command(self):
        self.add_layer_on(z=0)
        self.select_state("hover")
        before = self.session.undo_stack.count()
        self.panel._push_layer_field("offset", [5, 0, 0, 0])
        self.assertEqual(self.session.undo_stack.count(), before + 1)
        self.session.undo_stack.undo()
        self.assertNotIn("states", self.entry())

    # -- per-state resets ---------------------------------------------------

    def test_reset_clears_only_that_key_of_that_state(self):
        self.add_layer_on(z=0)
        self.select_state("hover")
        self.panel._push_layer_field("offset", [5, 0, 0, 0])
        self.panel._push_layer_field("tint", [9, 9, 9])
        self.panel._on_reset_layer_field("offset")
        self.assertEqual(self.entry()["states"], {"hover": {"tint": [9, 9, 9]}})

    def test_resetting_the_last_key_removes_the_state_not_leaves_it_empty(self):
        # An explicit `{}` is PRESENT and would pin hover to the base
        # appearance (engine.ui_layers._state_patch) — not what reset means.
        self.add_layer_on(z=0)
        self.select_state("hover")
        self.panel._push_layer_field("offset", [5, 0, 0, 0])
        self.panel._on_reset_layer_field("offset")
        self.assertEqual(self.entry(), {"id": "layer_1", "z": 0})

    def test_a_reset_button_is_dead_when_that_state_has_no_such_key(self):
        self.add_layer_on(offset=[1, 2, 0, 0], z=0)
        self.select_state("hover")
        # The base HAS an offset; the hover patch does not, so hover's own
        # reset has nothing to clear.
        self.assertFalse(self.panel.layer_offset_reset_button.isEnabled())
        self.select_state("idle")
        self.assertTrue(self.panel.layer_offset_reset_button.isEnabled())

    # -- what the rows SHOW -------------------------------------------------

    def test_a_state_with_no_patch_shows_the_base_values(self):
        self.add_layer_on(offset=[7, 8, 0, 0], z=0)
        self.select_state("hover")
        self.assertEqual(self.panel.layer_off_x.value(), 7)
        self.panel._push_layer_field("offset", [1, 1, 0, 0])
        self.assertEqual(self.panel.layer_off_x.value(), 1)
        self.select_state("idle")
        self.assertEqual(self.panel.layer_off_x.value(), 7)

    # -- ruling 1: non-Button holders ---------------------------------------

    def test_state_selector_is_greyed_and_pinned_to_idle_on_a_non_button(self):
        self.add_layer_on("love_text", z=0)
        self.assertFalse(self.panel.layer_state_combo.isEnabled())
        self.assertIn("only available for Button",
                      self.panel.layer_state_combo.toolTip())
        self.assertIn("only available for Button",
                      self.panel.layer_state_note.text())
        # Even asked for hover, the edit lands on the BASE entry — the state a
        # label holder is forever in.
        self.select_state("hover")
        self.panel._push_layer_field("offset", [4, 0, 0, 0])
        self.assertEqual(self.entry("love_text"),
                         {"id": "layer_1", "z": 0, "offset": [4, 0, 0, 0]})

    def test_state_selector_is_live_on_a_button(self):
        self.add_layer_on("btn_go", z=0)
        self.assertTrue(self.panel.layer_state_combo.isEnabled())
        self.assertEqual(self.panel.layer_state_combo.toolTip(), "")

    # -- ruling 2's neighbours: z/band are base-only, and the D4 tooltip ------

    def test_z_and_band_write_the_base_entry_even_in_a_state(self):
        self.add_layer_on(z=0)
        self.select_state("hover")
        self.panel.layer_z_spin.setValue(3)
        self.assertEqual(self.entry()["z"], 3)
        self.assertNotIn("states", self.entry())

    def test_band_rows_carry_the_d4_warning(self):
        from editor.panels.screen_details import TOOLTIP_LAYER_BAND
        self.assertIn("behind EVERYTHING on this screen", TOOLTIP_LAYER_BAND)
        self.assertEqual(self.panel.layer_field_band_combo.toolTip(),
                         TOOLTIP_LAYER_BAND)
        self.assertEqual(self.panel.layer_band_combo.toolTip(),
                         TOOLTIP_LAYER_BAND)

    # -- enabled state -------------------------------------------------------

    def test_inspector_is_dead_with_no_layer_selected(self):
        self.panel.select_widget("love_text")
        self.assertFalse(self.panel.layer_off_x.isEnabled())
        self.assertFalse(self.panel.layer_field_slot_combo.isEnabled())
        self.assertFalse(self.panel.layer_offset_reset_button.isEnabled())

    def test_a_slotted_layer_says_color_is_ignored(self):
        self.add_layer_on(slot="ui_panel", z=0)
        self.assertFalse(self.panel.layer_color_button.isEnabled())
        self.assertIn("Color is ignored",
                      self.panel.layer_color_button.toolTip())
