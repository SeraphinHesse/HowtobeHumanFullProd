"""``editor/panels/timeline.py`` tests (TimelinePLAN T5, Qt tier).

Uses ``TempDataCase`` (copies ``data/`` into a tempdir, so writes never touch
the repo) and drives the panel's own methods directly for most coverage —
plus ONE synthetic ``QDropEvent`` test exercising the real Qt drop path, so a
wiring bug between the drag gesture and ``editor.timeline_ops`` cannot hide
behind method-level tests alone. Real OS-level drag gestures cannot be
synthesized reliably under an offscreen QApplication; a constructed
``QMimeData`` + a direct ``dropEvent`` call is the standard Qt-test
workaround for that gap.
"""
from PySide6.QtCore import QMimeData, QPointF
from PySide6.QtGui import QDropEvent
from PySide6.QtCore import Qt

from editor.panels.timeline import TimelinePanel, _MIME_TYPE, _encode_card
from tools.tests.test_editor_panels import TempDataCase


def _drop_event(mime):
    # QDropEvent(pos, actions, mimeData, buttons, modifiers[, type])
    return QDropEvent(
        QPointF(0, 0), Qt.DropAction.CopyAction, mime,
        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)


class TestTimelinePanel(TempDataCase):
    def setUp(self):
        """Start every test from an EMPTY Timeline, and say so.

        PIN, don't assume (`data/CLAUDE.md`). Every test below is written
        against "the seeded empty doc" — it adds village level 1, drops a card
        on it, saves. That only worked because the fixture's
        `balancing/progression.json` happened to ship an empty
        `Timeline.levels`; when the fixture was re-synced from live data it
        arrived with 7 levels and all 36 `(building_type, tier_index)` pairs
        already placed, and the module broke three different ways at once:
        `add_level(1)` collided with an existing level 1, assigning
        `("blocker", 0)` tripped `validate_uniqueness`, and the resulting
        `_on_save` error path put up a MODAL `QMessageBox` that blocks
        forever under an offscreen QApplication — so the suite HUNG rather
        than failed (caught only because `pytest-timeout` is now installed).

        Emptying it here is a write into `TempDataCase`'s throwaway copy of
        `data/`, never the repo, and it makes the premise independent of
        whatever the designer's live timeline holds.
        """
        super().setUp()
        from editor import timeline_ops
        doc = timeline_ops.load_progression(self.data_dir)
        doc["Timeline"]["levels"] = []
        timeline_ops.save_progression(doc, self.data_dir)

    def _panel(self):
        panel = self.track(TimelinePanel(data_dir=self.data_dir))
        panel.set_icon_provider(lambda slot_key: None)  # no viewport in this test
        # PIN THE FIXTURE. These tests count rows and slots, so they must not
        # read whatever schedule the shipped Timeline happens to carry today
        # (data/CLAUDE.md: never assert against live data/ content). Emptying
        # the staged doc here is the fixture; the panel's own Save is what
        # would write it, and no test below saves without re-authoring first.
        panel._doc["Timeline"]["levels"] = []
        panel._rebuild_rows()
        panel._dirty = False
        panel.save_button.setEnabled(False)
        return panel

    def test_starts_with_no_rows_on_an_empty_schedule(self):
        panel = self._panel()
        self.assertEqual(panel._row_widgets, {})

    def test_add_level_creates_an_empty_row(self):
        panel = self._panel()
        panel.add_level(3)
        self.assertIn(3, panel._row_widgets)
        self.assertTrue(panel._dirty)
        self.assertTrue(panel.save_button.isEnabled())

    def test_add_and_remove_slot_updates_the_row(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        panel.add_slot(1)
        self.assertEqual(len(panel._row_widgets[1]._slot_widgets), 2)
        panel.remove_last_slot(1)
        self.assertEqual(len(panel._row_widgets[1]._slot_widgets), 1)

    def test_assign_slot_via_panel_method_updates_widget_and_greys_browse_card(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        panel.assign_slot(1, 0, "unlock", "blocker", 0)

        slot_widget = panel._row_widgets[1]._slot_widgets[0]
        self.assertEqual(
            slot_widget._assignment,
            {"kind": "unlock", "building_type": "blocker", "tier_index": 0})

        matching_cards = [
            c for c in panel._browse_cards
            if c.building_type == "blocker" and c.tier_index == 0]
        self.assertTrue(matching_cards)
        for card in matching_cards:
            self.assertFalse(card.isEnabled())  # placed -> not a drag source

    def test_assign_slot_replaces_an_occupied_slot(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        panel.assign_slot(1, 0, "unlock", "blocker", 0)
        panel.assign_slot(1, 0, "unlock", "wall_builder", 0)
        slot_widget = panel._row_widgets[1]._slot_widgets[0]
        self.assertEqual(slot_widget._assignment["building_type"], "wall_builder")

    def test_clear_slot_via_clear_button_empties_it(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        panel.assign_slot(1, 0, "unlock", "blocker", 0)
        # set_level() REBUILDS the row's slot widgets on every mutation (the
        # balancing.py "the form rebuilds" convention) — click the button on
        # the widget that's actually live, then re-fetch it afterward, since
        # the click's own handler swaps it out for a fresh instance.
        panel._row_widgets[1]._slot_widgets[0]._clear_btn.click()
        slot_widget = panel._row_widgets[1]._slot_widgets[0]
        self.assertIsNone(slot_widget._assignment)

    def test_remove_level_drops_the_row(self):
        panel = self._panel()
        panel.add_level(2)
        panel.remove_level(2)
        self.assertNotIn(2, panel._row_widgets)

    def test_drop_event_on_slot_widget_assigns_via_real_qt_path(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        slot_widget = panel._row_widgets[1]._slot_widgets[0]

        mime = QMimeData()
        mime.setData(_MIME_TYPE, _encode_card("unlock", "blocker", 0))
        slot_widget.dropEvent(_drop_event(mime))

        # the drop's own handler (panel.assign_slot) rebuilds the row's
        # widgets, so re-fetch rather than trust the pre-drop reference.
        rebuilt_widget = panel._row_widgets[1]._slot_widgets[0]
        self.assertEqual(
            rebuilt_widget._assignment,
            {"kind": "unlock", "building_type": "blocker", "tier_index": 0})
        self.assertTrue(panel._dirty)

    def test_save_writes_valid_progression_json(self):
        panel = self._panel()
        panel.add_level(1)
        panel.add_slot(1)
        panel.assign_slot(1, 0, "unlock", "blocker", 0)
        panel._on_save()

        self.assertFalse(panel._dirty)
        self.assertFalse(panel.save_button.isEnabled())

        from editor import timeline_ops
        on_disk = timeline_ops.load_progression(self.data_dir)
        self.assertEqual(
            on_disk["Timeline"]["levels"],
            [{"village_level": 1,
              "round": panel.round_for_level(1) or 0,
              "offer_slots": [{"assignment": {
                  "kind": "unlock", "building_type": "blocker", "tier_index": 0}}]}])


class TestScriptedLevelingSwitches(TempDataCase):
    """The two toolbar checkboxes: what each one changes in the panel."""

    def _panel(self):
        panel = self.track(TimelinePanel(data_dir=self.data_dir))
        panel.set_icon_provider(lambda slot_key: None)
        # Pinned fixture — two authored levels, nothing from live data/.
        panel._doc["Timeline"]["levels"] = []
        panel._rebuild_rows()
        panel.add_level(1)
        panel.add_level(2)
        panel._dirty = False
        panel.save_button.setEnabled(False)
        return panel

    def test_both_flags_start_unchecked_on_the_shipped_doc(self):
        panel = self._panel()
        self.assertFalse(panel.scripted_check.isChecked())
        self.assertFalse(panel.exact_check.isChecked())
        self.assertFalse(panel.scripted_leveling())
        self.assertFalse(panel.exact_offer_slots())

    def test_scripted_checkbox_stages_the_flag_and_marks_dirty(self):
        panel = self._panel()
        panel.scripted_check.setChecked(True)
        self.assertTrue(panel.scripted_leveling())
        self.assertTrue(panel._dirty)
        self.assertTrue(panel.save_button.isEnabled())

    def test_exact_checkbox_stages_the_flag_and_marks_dirty(self):
        panel = self._panel()
        panel.exact_check.setChecked(True)
        self.assertTrue(panel.exact_offer_slots())
        self.assertTrue(panel._dirty)
        self.assertTrue(panel.save_button.isEnabled())

    def test_round_spinbox_appears_only_in_scripted_mode(self):
        # isHidden(), not isVisible(): a widget whose window was never shown
        # is never "visible" to Qt, so isVisible() would read False either way.
        panel = self._panel()
        self.assertTrue(panel._row_widgets[2].round_spin.isHidden())
        panel.scripted_check.setChecked(True)
        self.assertFalse(panel._row_widgets[2].round_spin.isHidden())
        panel.scripted_check.setChecked(False)
        self.assertTrue(panel._row_widgets[2].round_spin.isHidden())

    def test_level_1_never_shows_a_round_spinbox(self):
        panel = self._panel()
        panel.scripted_check.setChecked(True)
        self.assertTrue(panel._row_widgets[1].round_spin.isHidden())

    def test_editing_the_spinbox_stages_the_round(self):
        panel = self._panel()
        panel.scripted_check.setChecked(True)
        panel._row_widgets[2].round_spin.setValue(7)
        self.assertEqual(panel.authored_round(2), 7)

    def test_populating_the_spinbox_does_not_dirty_the_doc(self):
        panel = self._panel()
        panel._doc["Timeline"]["scripted_leveling"] = True
        panel._rebuild_rows()
        self.assertFalse(panel._dirty)

    def test_exact_mode_stops_greying_a_placed_browse_card(self):
        panel = self._panel()
        panel.add_slot(1)
        panel.assign_slot(1, 0, "unlock", "blocker", 0)
        placed = [c for c in panel._browse_cards
                  if c.building_type == "blocker" and c.tier_index == 0]
        self.assertTrue(placed)
        self.assertFalse(placed[0].isEnabled())

        panel.exact_check.setChecked(True)
        self.assertTrue(placed[0].isEnabled())

    def test_a_bad_schedule_warns_without_disabling_save(self):
        panel = self._panel()
        panel.scripted_check.setChecked(True)
        panel.add_level(3)
        panel._row_widgets[2].round_spin.setValue(9)
        panel._row_widgets[3].round_spin.setValue(4)
        self.assertTrue(panel.warnings_label.text())
        self.assertFalse(panel.warnings_label.isHidden())
        self.assertTrue(panel.save_button.isEnabled())

    def test_the_graph_ticks_the_authored_rounds_in_scripted_mode(self):
        panel = self._panel()
        panel.scripted_check.setChecked(True)
        panel._row_widgets[2].round_spin.setValue(3)
        self.assertEqual(panel._tick_rounds()[2], 3)

        panel.scripted_check.setChecked(False)
        self.assertEqual(panel._tick_rounds(), panel._level_to_round)

    def test_round_for_level_matches_editor_timeline_curve(self):
        panel = self._panel()
        from editor import timeline_curve
        core, enemies = timeline_curve.load_curve_balance(self.data_dir)
        _cumulative, expected = timeline_curve.best_case_curve(
            core, enemies, 0, 50, max_levels=5)
        for level in range(1, 6):
            self.assertEqual(panel.round_for_level(level), expected[level])
