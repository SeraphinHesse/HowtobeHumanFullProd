"""DetailsPanel (ED-40/41) + LevelBar — importer parity, headless.

Conventions: offscreen Qt + SDL dummy env, one QApplication, TempDataCase
tempfile copy of data/ (the repo's migrated manifest + PNGs come along).
Synthetic sheets are authored with Pillow (the panel's own image dep).
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

from PIL import Image
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from editor.panels import details
from editor.panels.details import DetailsPanel
from editor.panels.level_bar import LevelBar
from editor.panels.sheet_picker import SheetPickerDialog
from engine import data_io
from tools.tests.test_editor_panels import TempDataCase


def make_png(path, w, h, colour=(200, 60, 60, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), colour).save(path)
    return path


class DetailsCase(TempDataCase):
    #: Slots a subclass needs to be genuinely EMPTY. Applied before the panel
    #: is built, so the panel reads the pinned manifest. Never assume a slot
    #: is unassigned — see TempDataCase.unassign_slot.
    UNASSIGN = ()

    def setUp(self):
        super().setUp()
        for slot in self.UNASSIGN:
            self.unassign_slot(slot)
        self.panel = self.track(DetailsPanel(data_dir=self.data_dir))
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.png_dir = Path(tmp.name)

    def manifest_doc(self):
        return data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")


class TestImportSheet(DetailsCase):
    def test_import_copies_png_and_builds_rows(self):
        src = make_png(self.png_dir / "art.png", 3 * 64, 1 * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.assertEqual(self.panel.import_sheet(src), (3, 1, True))
        copied = self.data_dir / "sprites" / "imported" / "painter_t1_lvl1.png"
        self.assertTrue(copied.exists())
        self.assertEqual(len(self.panel._row_editors), 1)
        row0 = self.panel._row_editors[0]
        # ED-40: row 0 = idle lives in the UI — locked combo, not a save error
        self.assertEqual([row0.anim_combo.itemText(i)
                          for i in range(row0.anim_combo.count())], ["idle"])
        self.assertFalse(row0.anim_combo.isEnabled())

    def test_other_rows_offer_the_category_vocabulary(self):
        src = make_png(self.png_dir / "art.png", 2 * 64, 2 * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        row1 = self.panel._row_editors[1]
        self.assertEqual(
            [row1.anim_combo.itemText(i) for i in range(row1.anim_combo.count())],
            ["idle", "attack", "death", "hurt", "place", "upgrade"])
        self.assertTrue(row1.anim_combo.isEnabled())
        self.assertEqual(row1.anim_combo.currentText(), "attack")  # prototype default

    def test_off_grid_sheet_warns_but_imports(self):
        src = make_png(self.png_dir / "art.png", 200, 100)   # not a 64x96 grid
        self.panel.set_slot("painter_t1_lvl1")
        self.assertEqual(self.panel.import_sheet(src), (3, 1, False))
        self.assertIn("cropped", self.panel._info.text())
        self.assertEqual(len(self.panel._row_editors), 1)

    def test_sub_frame_sheet_is_padded_and_centred(self):
        """ED-40 (ER-1): undersized art imports padded + centred instead of
        being rejected — a (cols, rows, clean) tuple, and no warning."""
        src = make_png(self.png_dir / "art.png", 16, 16)
        self.panel.set_slot("painter_t1_lvl1")
        self.assertEqual(self.panel.import_sheet(src), (1, 1, True))
        copied = self.data_dir / "sprites" / "imported" / "painter_t1_lvl1.png"
        self.assertTrue(copied.exists())
        with Image.open(copied) as image:
            self.assertEqual(image.size, (64, 96))
            self.assertEqual(image.getbbox(), (24, 40, 40, 56))
        self.assertNotIn("⚠", self.panel._info.text())
        self.assertIn("padded", self.panel._info.text())
        self.assertEqual(len(self.panel._row_editors), 1)

    def test_padded_off_grid_sheet_keeps_the_cropped_warning(self):
        """Padding vertically doesn't make the sheet a clean grid — a 100px-wide
        strip in a 64x96 frame still crops 36px, and the designer must be told."""
        src = make_png(self.png_dir / "art.png", 100, 16)
        self.panel.set_slot("painter_t1_lvl1")
        self.assertEqual(self.panel.import_sheet(src), (1, 1, False))
        info = self.panel._info.text()
        self.assertIn("⚠", info)         # the remainder-cropped warning survives
        self.assertIn("cropped", info)
        self.assertIn("padded", info)    # ...alongside the padding note

    def test_tiles_slot_uses_its_category_frame_size(self):
        """ED-41: same panel drives every category at its own frame size."""
        src = make_png(self.png_dir / "tile.png", 2 * 64, 1 * 32)
        self.panel.set_slot("tile_forest")
        self.assertEqual(self.panel.import_sheet(src), (2, 1, True))
        self.assertIn("64×32", self.panel._header.text())
        row0 = self.panel._row_editors[0]
        self.assertEqual([row0.anim_combo.itemText(i)
                          for i in range(row0.anim_combo.count())], ["idle"])


class TestDraftSaveClear(DetailsCase):
    def import_painter(self, cols=3, rows=2):
        src = make_png(self.png_dir / "art.png", cols * 64, rows * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)

    def test_edits_flow_into_draft_and_signal(self):
        self.import_painter()
        drafts = []
        self.panel.draft_changed.connect(lambda slot, e: drafts.append((slot, e)))
        row1 = self.panel._row_editors[1]
        row1.fps_spin.setValue(12)
        row1.hide_boxes[1].setChecked(True)
        row1.loop_start.setValue(0)
        row1.loop_end.setValue(1)
        row1.loop_count.setValue(3)
        self.panel._offset_y.setValue(8)
        draft = self.panel.draft_entry()
        self.assertEqual(draft["offset_y"], 8)
        self.assertEqual(draft["rows"][1]["fps"], 12)
        self.assertEqual(draft["rows"][1]["hidden"], [1])
        self.assertEqual(draft["rows"][1]["loop_count"], 3)
        self.assertEqual(drafts[-1][0], "painter_t1_lvl1")
        self.assertEqual(drafts[-1][1], draft)

    def test_save_writes_valid_manifest_entry(self):
        self.import_painter()
        saved = []
        self.panel.entry_saved.connect(saved.append)
        self.panel._row_editors[1].fps_spin.setValue(6)
        self.panel.save()
        self.assertEqual(saved, ["painter_t1_lvl1"])
        entry = self.manifest_doc()["entries"]["painter_t1_lvl1"]
        self.assertEqual(entry["sheet"], "imported/painter_t1_lvl1.png")
        self.assertEqual((entry["frame_w"], entry["frame_h"]), (64, 96))
        self.assertEqual(entry["rows"][0]["animation"], "idle")
        self.assertEqual(entry["rows"][1]["fps"], 6)

    def test_clear_removes_entry_and_png(self):
        self.import_painter()
        self.panel.save()
        cleared = []
        self.panel.entry_cleared.connect(cleared.append)
        self.panel.clear_entry(confirm=False)
        self.assertEqual(cleared, ["painter_t1_lvl1"])
        self.assertNotIn("painter_t1_lvl1", self.manifest_doc()["entries"])
        png = self.data_dir / "sprites" / "imported" / "painter_t1_lvl1.png"
        self.assertFalse(png.exists())
        self.assertEqual(self.panel._row_editors, [])

    def test_existing_migrated_entry_loads_into_editors(self):
        self.panel.set_slot("stone_thrower_t1_lvl1")
        self.assertEqual(len(self.panel._row_editors), 2)
        row1 = self.panel._row_editors[1]
        self.assertEqual(row1.anim_combo.currentText(), "attack")
        self.assertEqual(row1.fps_spin.value(), 6)
        self.assertTrue(row1.hide_boxes[3].isChecked())
        self.assertFalse(row1.hide_boxes[0].isChecked())


class TestStaticRow(DetailsCase):
    """"Don't animate — just show frame N". Static is DERIVED from the manifest's
    existing `hidden` array (hide every column but one), so it adds no schema key
    and no editor-only state: `playback_order` drops hidden frames after loop
    expansion, which makes a one-visible-frame row a still sprite."""

    UNASSIGN = ("painter_t1_lvl1",)

    def import_painter(self, cols=4, rows=2):
        src = make_png(self.png_dir / "art.png", cols * 64, rows * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        return self.panel._row_editors[1]

    def test_static_hides_every_frame_but_the_chosen_one(self):
        row = self.import_painter()
        row.static_check.setChecked(True)
        row.set_static_frame(2)
        self.assertEqual(row.to_dict()["hidden"], [0, 1, 3])
        self.assertEqual(row.static_frame(), 2)

    def test_static_defaults_to_the_first_still_visible_frame(self):
        row = self.import_painter()
        row.hide_boxes[0].setChecked(True)     # frame 0 already hidden
        row.static_check.setChecked(True)
        self.assertEqual(row.static_frame(), 1)   # not the frame we just hid

    def test_saved_static_row_reopens_as_static(self):
        row = self.import_painter()
        row.static_check.setChecked(True)
        row.set_static_frame(2)
        self.panel.save()
        self.panel.set_slot(None)
        self.panel.set_slot("painter_t1_lvl1")   # re-read from disk
        reloaded = self.panel._row_editors[1]
        self.assertTrue(reloaded.is_static())
        self.assertEqual(reloaded.static_frame(), 2)
        self.assertEqual(self.manifest_doc()["entries"]["painter_t1_lvl1"]
                         ["rows"][1]["hidden"], [0, 1, 3])

    def test_a_single_frame_row_is_not_auto_static(self):
        """A 1-frame row has no animation to disable; auto-ticking Static on every
        one-frame tile sheet would be noise, not information."""
        row = self.import_painter(cols=1)
        self.assertFalse(row.is_static())
        self.assertEqual(row.to_dict()["hidden"], [])

    def test_static_disables_the_loop_controls_without_rewriting_them(self):
        row = self.import_painter()
        row.loop_start.setValue(0)
        row.loop_end.setValue(2)
        row.loop_count.setValue(5)
        row.static_check.setChecked(True)
        self.assertFalse(row.loop_row.isEnabled())
        # The designer's numbers survive — a loop over a one-visible-frame row is
        # meaningless, not harmful (hidden frames drop after expansion).
        self.assertEqual(row.to_dict()["loop_count"], 5)

    def test_unticking_static_restores_the_previous_hide_state(self):
        row = self.import_painter()
        row.hide_boxes[3].setChecked(True)
        row.static_check.setChecked(True)
        self.assertEqual(row.to_dict()["hidden"], [1, 2, 3])   # all but frame 0
        row.static_check.setChecked(False)
        self.assertEqual(row.to_dict()["hidden"], [3])         # what we had


class TestSheetPreviewClicks(DetailsCase):
    """The preview is the frame picker: clicking a cell goes through that row's
    own widgets, so the checkboxes below can never disagree with the picture."""

    UNASSIGN = ("painter_t1_lvl1",)

    def import_painter(self):
        src = make_png(self.png_dir / "art.png", 4 * 64, 2 * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)

    def test_click_toggles_hidden_when_the_row_animates(self):
        self.import_painter()
        row = self.panel._row_editors[1]
        self.panel._on_frame_clicked(1, 2)
        self.assertTrue(row.hide_boxes[2].isChecked())
        self.assertEqual(row.to_dict()["hidden"], [2])
        self.panel._on_frame_clicked(1, 2)
        self.assertFalse(row.hide_boxes[2].isChecked())

    def test_click_picks_the_frame_when_the_row_is_static(self):
        self.import_painter()
        row = self.panel._row_editors[1]
        row.static_check.setChecked(True)
        self.panel._on_frame_clicked(1, 3)
        self.assertEqual(row.static_frame(), 3)
        self.assertEqual(row.to_dict()["hidden"], [0, 1, 2])

    def test_click_outside_the_row_editors_is_a_no_op(self):
        self.import_painter()
        self.panel._on_frame_clicked(9, 0)      # only 2 rows exist

    def test_preview_shows_the_sheet_and_mirrors_what_gets_saved(self):
        self.import_painter()
        row = self.panel._row_editors[1]
        row.static_check.setChecked(True)
        row.set_static_frame(1)
        self.assertTrue(self.panel._preview.has_sheet())
        state = self.panel._preview._row_state[1]
        self.assertEqual(state["static_frame"], 1)
        self.assertEqual(sorted(state["hidden"]), row.to_dict()["hidden"])

    def test_preview_cell_hit_test_round_trips(self):
        self.import_painter()
        preview = self.panel._preview
        preview.resize(4 * 64, 2 * 96)          # scale 1.0, no fitting
        rect = preview._cell_rect(1, 2)
        self.assertEqual(preview.cell_at(rect.center()), (1, 2))
        self.assertIsNone(preview.cell_at(rect.center() + QPoint(0, 10_000)))


class TestUseSheet(DetailsCase):
    """"Use Spritesheet…" LINKS: the entry points at another slot's PNG and no
    bytes are copied. The engine already resolves `sprites_dir / entry.sheet`
    verbatim, so one file can back many slots."""

    UNASSIGN = ("painter_t1_lvl1", "painter_t1_lvl2")

    SOURCE = "painter_t1_lvl1"
    TARGET = "painter_t1_lvl2"

    def setUp(self):
        super().setUp()
        # unassign_slot drops the manifest ENTRY; the repo also ships a real
        # painter_t1_lvl2.png. Pin the fixture all the way: a slot with no art of
        # its own is the whole reason you reach for someone else's sheet.
        self.png(self.TARGET).unlink(missing_ok=True)

    def png(self, slot):
        return self.data_dir / "sprites" / "imported" / f"{slot}.png"

    def import_source(self, cols=3, rows=2):
        src = make_png(self.png_dir / "art.png", cols * 64, rows * 96)
        self.panel.set_slot(self.SOURCE)
        self.panel.import_sheet(src)
        self.panel._row_editors[1].fps_spin.setValue(11)
        self.panel._row_editors[1].hide_boxes[2].setChecked(True)
        self.panel._offset_y.setValue(-7)
        self.panel.save()

    def test_use_sheet_links_without_copying_a_png(self):
        self.import_source()
        self.panel.set_slot(self.TARGET)
        self.assertEqual(self.panel.use_sheet("imported/painter_t1_lvl1.png"),
                         (3, 2, True))
        self.panel.save()
        entry = self.manifest_doc()["entries"][self.TARGET]
        self.assertEqual(entry["sheet"], "imported/painter_t1_lvl1.png")
        self.assertFalse(self.png(self.TARGET).exists())   # nothing was copied
        self.assertTrue(self.png(self.SOURCE).exists())

    def test_use_sheet_carries_the_source_row_settings_and_offsets(self):
        self.import_source()
        self.panel.set_slot(self.TARGET)
        self.panel.use_sheet("imported/painter_t1_lvl1.png")
        self.panel.save()
        entry = self.manifest_doc()["entries"][self.TARGET]
        self.assertEqual(entry["rows"][1]["fps"], 11)
        self.assertEqual(entry["rows"][1]["hidden"], [2])
        self.assertEqual(entry["offset_y"], -7)

    def test_a_linked_slot_reopens_on_its_linked_sheet(self):
        self.import_source()
        self.panel.set_slot(self.TARGET)
        self.panel.use_sheet("imported/painter_t1_lvl1.png")
        self.panel.save()
        self.panel.set_slot(None)
        self.panel.set_slot(self.TARGET)        # re-read from disk
        self.assertEqual(self.panel._sheet_ref, "imported/painter_t1_lvl1.png")
        self.assertEqual(len(self.panel._row_editors), 2)
        self.assertTrue(self.panel._preview.has_sheet())

    def test_a_fresh_import_re_owns_the_slots_own_png(self):
        """Linking is not a one-way door: importing a file again takes the slot
        back to imported/<slot>.png."""
        self.import_source()
        self.panel.set_slot(self.TARGET)
        self.panel.use_sheet("imported/painter_t1_lvl1.png")
        self.panel.save()
        own = make_png(self.png_dir / "own.png", 2 * 64, 96)
        self.panel.import_sheet(own)
        self.panel.save()
        self.assertEqual(self.manifest_doc()["entries"][self.TARGET]["sheet"],
                         "imported/painter_t1_lvl2.png")
        self.assertTrue(self.png(self.TARGET).exists())

    def test_use_sheet_on_a_missing_sheet_is_refused(self):
        self.panel.set_slot(self.TARGET)
        self.assertIsNone(self.panel.use_sheet("imported/not_here.png"))

    def test_relinking_the_same_sheet_keeps_this_slots_own_tuning(self):
        """Re-picking the sheet a slot ALREADY uses must not throw away the
        fps/hidden work done on it and re-seed from the source."""
        self.import_source()
        self.panel.set_slot(self.TARGET)
        self.panel.use_sheet("imported/painter_t1_lvl1.png")
        self.panel._row_editors[1].fps_spin.setValue(3)
        self.panel.save()
        self.panel.use_sheet("imported/painter_t1_lvl1.png")   # same sheet again
        self.assertEqual(self.panel._row_editors[1].fps_spin.value(), 3)


class TestClearSharedSheet(DetailsCase):
    """Clear refcounts before unlinking. Deleting a shared PNG would blank every
    other slot using it — the whole reason linking needed more than a `sheet` swap."""

    UNASSIGN = ("painter_t1_lvl1", "painter_t1_lvl2")

    SOURCE = "painter_t1_lvl1"
    TARGET = "painter_t1_lvl2"

    def setUp(self):
        super().setUp()
        src = make_png(self.png_dir / "art.png", 2 * 64, 96)
        self.panel.set_slot(self.SOURCE)
        self.panel.import_sheet(src)
        self.panel.save()
        self.panel.set_slot(self.TARGET)
        self.panel.use_sheet("imported/painter_t1_lvl1.png")
        self.panel.save()
        self.shared = self.data_dir / "sprites" / "imported" / "painter_t1_lvl1.png"

    def test_clearing_the_linker_keeps_the_shared_png(self):
        self.panel.set_slot(self.TARGET)
        self.panel.clear_entry(confirm=False)
        self.assertTrue(self.shared.exists())
        entries = self.manifest_doc()["entries"]
        self.assertNotIn(self.TARGET, entries)
        self.assertEqual(entries[self.SOURCE]["sheet"],
                         "imported/painter_t1_lvl1.png")

    def test_clearing_the_owner_keeps_the_png_the_linker_still_needs(self):
        """The hard direction: the slot whose NAME the file carries goes away, but
        another slot is still pointing at that file."""
        self.panel.set_slot(self.SOURCE)
        self.panel.clear_entry(confirm=False)
        self.assertTrue(self.shared.exists())
        entries = self.manifest_doc()["entries"]
        self.assertNotIn(self.SOURCE, entries)
        self.assertEqual(entries[self.TARGET]["sheet"],
                         "imported/painter_t1_lvl1.png")

    def test_clearing_the_last_user_finally_collects_the_png(self):
        self.panel.set_slot(self.SOURCE)
        self.panel.clear_entry(confirm=False)
        self.panel.set_slot(self.TARGET)
        self.panel.clear_entry(confirm=False)
        self.assertFalse(self.shared.exists())
        self.assertEqual(self.manifest_doc()["entries"].get(self.SOURCE), None)


class TestClearAsksFirst(DetailsCase):
    """Regression: `clicked` emits clicked(bool checked), which silently overrode
    clear_entry's `confirm=True` default to False — the Clear BUTTON deleted the
    entry and the PNG with no dialog at all. Wrap the connect in a lambda (the
    same footgun the panels doc records for map_details' Delete)."""

    UNASSIGN = ("painter_t1_lvl1",)

    def test_clear_button_asks_before_deleting_and_no_means_no(self):
        src = make_png(self.png_dir / "art.png", 2 * 64, 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        self.panel.save()
        with mock.patch.object(
                details.QMessageBox, "question",
                return_value=details.QMessageBox.StandardButton.No) as question:
            self.panel._clear_btn.click()
        question.assert_called_once()
        self.assertIn("painter_t1_lvl1", self.manifest_doc()["entries"])
        png = self.data_dir / "sprites" / "imported" / "painter_t1_lvl1.png"
        self.assertTrue(png.exists())


class TestSheetPicker(DetailsCase):
    UNASSIGN = ("painter_t1_lvl1",)

    def dialog(self, slot="painter_t1_lvl1", frame=(64, 96)):
        return self.track(SheetPickerDialog(self.data_dir, slot, *frame))

    def test_defaults_to_sheets_that_fit_the_slots_frame_size(self):
        dialog = self.dialog()
        refs = {sheet.ref for sheet in dialog.visible_sheets()}
        # 64x96 building sheets are offered; 64x32 map tiles are not.
        self.assertIn("imported/stone_thrower_t1_lvl1.png", refs)
        self.assertNotIn("imported/tile_buildable.png", refs)

    def test_show_all_sizes_escapes_the_filter(self):
        dialog = self.dialog()
        dialog._all_sizes.setChecked(True)
        refs = {sheet.ref for sheet in dialog.visible_sheets()}
        self.assertIn("imported/tile_buildable.png", refs)

    def test_name_filter_narrows_the_list(self):
        dialog = self.dialog()
        dialog._filter.setText("stone_thrower")
        names = [sheet.name for sheet in dialog.visible_sheets()]
        self.assertTrue(names)
        self.assertTrue(all("stone_thrower" in name for name in names))

    def test_selecting_a_sheet_previews_it_and_reports_the_choice(self):
        dialog = self.dialog()
        self.assertTrue(dialog.select_sheet("imported/stone_thrower_t1_lvl1.png"))
        self.assertEqual(dialog.chosen().ref,
                         "imported/stone_thrower_t1_lvl1.png")
        self.assertTrue(dialog._preview.has_sheet())


class TestSubcategoryDropdown(DetailsCase):
    """The ● tells a designer which subcategory already has art. Proving that
    needs one subcategory WITH art and two WITHOUT — so the two without are
    pinned empty rather than assumed empty (art landed on slinger/pistoleer in
    2512a84 and this test went red)."""

    UNASSIGN = ("slinger_t2_lvl1", "slinger_t2_lvl2", "slinger_t2_lvl3",
                "pistoleer_t3_lvl1", "pistoleer_t3_lvl2", "pistoleer_t3_lvl3")

    def test_context_populates_dropdown_with_markers(self):
        self.panel.set_context("buildings", ("Defender",))
        combo = self.panel._subcat_combo
        texts = [combo.itemText(i) for i in range(combo.count())]
        self.assertEqual(texts, ["● Stone Thrower", "Slinger", "Pistoleer"])
        seen = []
        self.panel.subcategory_changed.connect(seen.append)
        combo.setCurrentIndex(1)
        self.assertEqual(seen, [1])

    def test_context_without_slots_disables_panel(self):
        self.panel.set_context("buildings", ())
        self.assertEqual(self.panel._subcat_combo.count(), 0)
        self.assertIsNone(self.panel.slot_key)


class TestLevelBar(QtCase):
    def test_levels_and_signal(self):
        bar = self.track(LevelBar())
        bar.set_levels(("a_lvl1", "a_lvl2", "a_lvl3"), assigned={"a_lvl2"})
        self.assertEqual(bar.level(), 0)
        self.assertFalse(bar.isHidden())
        seen = []
        bar.level_changed.connect(seen.append)
        bar._buttons[2].click()
        self.assertEqual(seen, [2])
        self.assertEqual(bar.level(), 2)
        self.assertIn("●", bar._buttons[1].text())

    def test_single_slot_hides_the_bar(self):
        bar = self.track(LevelBar())
        bar.set_levels(("only",))
        self.assertTrue(bar.isHidden())
        self.assertEqual(bar.level(), 0)

    def test_can_add_keeps_single_slot_bar_and_button_visible(self):
        # an enemy era with ONE variant must still show the "+ Variant" button
        bar = self.track(LevelBar())
        requested = []
        bar.add_variant_requested.connect(lambda: requested.append(True))
        bar.set_levels(("enemy_stage_2",), can_add=True)
        self.assertFalse(bar.isHidden())
        self.assertFalse(bar._add_btn.isHidden())
        bar._add_btn.click()
        self.assertEqual(requested, [True])

    def test_add_button_hidden_without_can_add(self):
        bar = self.track(LevelBar())
        bar.set_levels(("a_lvl1", "a_lvl2", "a_lvl3"))
        self.assertTrue(bar._add_btn.isHidden())

    def test_select_last_reports_the_new_variant(self):
        bar = self.track(LevelBar())
        seen = []
        bar.level_changed.connect(seen.append)
        bar.set_levels(("v1", "v2"), can_add=True)
        bar.select_last()
        self.assertEqual(bar.level(), 1)
        self.assertEqual(seen, [1])


if __name__ == "__main__":
    unittest.main()
