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
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from editor import master_sheet_import
from editor.panels import details
from editor.panels.balancing import _NoWheelSpinBox
from editor.panels.details import DetailsPanel, RowEditor
from editor.panels.level_bar import LevelBar
from editor.panels.sheet_picker import SheetPickerDialog
from editor.panels.sheet_preview import SheetPreview
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
        # Pin the entry AND its sheet instead of inheriting whatever the artist
        # last imported. The subject here is "manifest state loads into the
        # editors", so the test supplies that state — twice over now: 380ab4a
        # re-imported this sheet and reset its hidden flags, then cff77c7
        # ("Stonethrower all eras") grew it from 2 rows to 6. Row EDITORS are
        # built from the sheet's height, so pinning the entry alone was not
        # enough; pin_slot_rows writes a matching synthetic PNG.
        self.pin_slot_rows("stone_thrower_t1_lvl1", ("idle", "attack"),
                           fps=6, hidden=(3,))

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


class TestFrameNumbers(DetailsCase):
    """Every cell is captioned with its COLUMN index — the number the hide
    checkboxes, the static radios and the manifest's `hidden` all speak."""

    UNASSIGN = ("painter_t1_lvl1",)

    def preview(self, width, height):
        src = make_png(self.png_dir / "art.png", 4 * 64, 2 * 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        preview = self.panel._preview
        preview.resize(width, height)
        return preview

    def test_caption_sits_at_the_bottom_of_its_own_cell(self):
        preview = self.preview(4 * 64, 2 * 96)          # scale 1.0
        self.assertTrue(preview.labels_visible())
        metrics = QFontMetrics(preview._label_font())
        for row, col in ((0, 0), (1, 3)):
            cell = preview._cell_rect(row, col)
            plate = preview._label_rect(cell, metrics, str(col))
            self.assertTrue(cell.contains(plate))
            self.assertEqual(plate.bottom(), cell.bottom())

    def test_captions_are_dropped_when_a_cell_is_too_small_to_hold_one(self):
        preview = self.preview(40, 30)                  # cells ~10px across
        self.assertFalse(preview.labels_visible())


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


class TestMasterSheetWindow(DetailsCase):
    """M4 — "Use Master Spritesheet…": the slot LINKS to one big shared PNG,
    inherits its grid (D3) and claims a contiguous row window in it (D2).

    The master registry ships EMPTY, so the fixture sheet is imported by the
    test — never borrowed from live `data/`."""

    UNASSIGN = ("painter_t1_lvl1", "painter_t1_lvl2")

    SLOT = "painter_t1_lvl1"
    OTHER = "painter_t1_lvl2"
    #: Deliberately NOT the painter category's 64x96: proving the grid is
    #: inherited needs the two to disagree.
    FRAME = (32, 48)
    COLS, ROWS = 4, 6

    def setUp(self):
        super().setUp()
        src = make_png(self.png_dir / "master.png",
                       self.COLS * self.FRAME[0], self.ROWS * self.FRAME[1])
        self.sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, src, "Village Folk", *self.FRAME, self.COLS)
        self.ref = f"master/{self.sheet_id}.png"
        self.master_png = self.data_dir / "sprites" / self.ref
        self.slots_json = self.data_dir / "slots.json"

    def link(self, slot=None, row_start=None, row_count=None):
        self.panel.set_slot(slot or self.SLOT)
        return self.panel.use_master_sheet(self.sheet_id, row_start, row_count)

    def test_linking_inherits_the_grid_and_locks_the_frame_spins(self):
        slots_before = self.slots_json.read_bytes()
        self.assertEqual(self.link(), (self.COLS, self.ROWS, True))

        self.assertEqual(self.panel._sheet_ref, self.ref)
        self.assertEqual(self.panel._row_frame_size, self.FRAME)
        self.assertFalse(self.panel._frame_w.isEnabled())
        self.assertFalse(self.panel._frame_h.isEnabled())
        self.assertIn("master", self.panel._frame_w.toolTip().lower())

        self.panel.save()
        entry = self.manifest_doc()["entries"][self.SLOT]
        self.assertEqual(entry["sheet"], self.ref)
        self.assertEqual((entry["frame_w"], entry["frame_h"]), self.FRAME)
        # D3: the grid came from the registry, so the per-slot slots.json
        # override path (_on_frame_size_changed) must not have run.
        self.assertEqual(self.slots_json.read_bytes(), slots_before)
        self.assertFalse(self.data_dir.joinpath(
            "sprites", "imported", f"{self.SLOT}.png").exists())

    def test_the_row_window_shows_only_for_a_master_sheet(self):
        self.panel.set_slot(self.SLOT)
        self.panel.import_sheet(make_png(self.png_dir / "own.png", 64, 2 * 96))
        self.assertTrue(self.panel._master_row.isHidden())
        self.link()
        self.assertFalse(self.panel._master_row.isHidden())

    def test_the_window_rebuilds_the_rows_and_narrows_the_preview(self):
        self.link(row_start=2, row_count=3)
        self.assertEqual(len(self.panel._row_editors), 3)
        self.assertEqual(self.panel._preview.row_window(), (2, 3))
        # The spins say what the window says, and a > b is unrepresentable.
        self.assertEqual((self.panel._row_from.value(),
                          self.panel._row_to.value()), (2, 4))
        self.assertEqual(self.panel._row_to.minimum(), 2)

        self.panel._row_from.setValue(1)
        self.panel._row_to.setValue(2)
        self.panel._on_row_window_changed()
        self.assertEqual(len(self.panel._row_editors), 2)
        self.assertEqual(self.panel._preview.row_window(), (1, 2))

    def test_a_click_on_the_first_visible_row_routes_to_row_editor_zero(self):
        self.link(row_start=2, row_count=3)
        preview = self.panel._preview
        preview.resize(self.COLS * self.FRAME[0], 3 * self.FRAME[1])
        # A real hit-test on the top-left cell of the WINDOW: the preview
        # speaks entry-relative rows, so no offset arithmetic anywhere.
        self.assertEqual(preview.cell_at(preview._cell_rect(0, 1).center()),
                         (0, 1))
        self.panel._on_frame_clicked(0, 1)
        self.assertTrue(self.panel._row_editors[0].hide_boxes[1].isChecked())

    def test_save_writes_row_start_and_omits_it_at_zero(self):
        self.link(row_start=3, row_count=2)
        self.panel.save()
        entry = self.manifest_doc()["entries"][self.SLOT]
        self.assertEqual(entry["row_start"], 3)
        self.assertEqual(len(entry["rows"]), 2)      # the "til" blank, derived

        self.panel.set_slot(None)
        self.panel.set_slot(self.SLOT)               # re-read from disk
        self.assertEqual((self.panel._row_start, len(self.panel._row_editors)),
                         (3, 2))

        self.link(row_start=0, row_count=2)
        self.panel.save()
        self.assertNotIn("row_start", self.manifest_doc()["entries"][self.SLOT])

    def test_clearing_one_user_never_unlinks_a_master_sheet_others_cut(self):
        self.link(self.SLOT, row_start=0, row_count=2)
        self.panel.save()
        self.link(self.OTHER, row_start=2, row_count=2)
        self.panel.save()

        self.panel.set_slot(self.OTHER)
        self.panel.clear_entry(confirm=False)

        self.assertTrue(self.master_png.exists())
        entries = self.manifest_doc()["entries"]
        self.assertNotIn(self.OTHER, entries)
        self.assertEqual(entries[self.SLOT]["sheet"], self.ref)


class TestSheetPreviewRowWindow(QtCase):
    """The window is OPT-IN: three-argument callers (the sheet picker, the
    master-sheet dialog's read-only previews, every non-master slot) paint the
    whole sheet exactly as before."""

    FRAME = (16, 24)

    def preview(self, tmp):
        png = make_png(Path(tmp) / "sheet.png", 3 * 16, 5 * 24)
        widget = self.track(SheetPreview(interactive=True))
        widget.resize(3 * 16, 5 * 24)
        return widget, png

    def test_default_arguments_show_the_whole_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME)
            self.assertEqual(widget.row_window(), (0, 5))
            full_height = widget.heightForWidth(3 * 16)

            widget.set_sheet(png, *self.FRAME, row_start=1, row_count=2)
            self.assertEqual(widget.row_window(), (1, 2))
            self.assertLess(widget.heightForWidth(3 * 16), full_height)

            widget.set_sheet(png, *self.FRAME)      # a 3-arg call RESETS it
            self.assertEqual(widget.row_window(), (0, 5))
            self.assertEqual(widget.heightForWidth(3 * 16), full_height)

    def test_a_window_past_the_bottom_is_clamped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME, row_start=4, row_count=99)
            self.assertEqual(widget.row_window(), (4, 1))


class TestSheetPreviewColumnWindow(QtCase):
    """The column window is the row window's twin: equally OPT-IN, applied in
    the SAME source rectangle, and WINDOW-RELATIVE — the first visible column
    is column 0 for the captions and for `frame_clicked`."""

    FRAME = (16, 24)
    #: One flat colour per SHEET column, so a rendered pixel says which source
    #: column the paintEvent actually sampled.
    COLOURS = ((200, 60, 60), (60, 200, 60), (60, 60, 200))

    def preview(self, tmp):
        """A 3x5-frame sheet whose columns are individually identifiable."""
        path = Path(tmp) / "striped.png"
        image = Image.new("RGBA", (3 * 16, 5 * 24))
        for col, colour in enumerate(self.COLOURS):
            for x in range(col * 16, (col + 1) * 16):
                for y in range(5 * 24):
                    image.putpixel((x, y), colour + (255,))
        image.save(path)
        widget = self.track(SheetPreview(interactive=True))
        widget.resize(3 * 16, 5 * 24)
        return widget, path

    def test_a_column_window_narrows_the_grid_and_the_source_rect(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME)
            full_width = widget._grid_rect().width()

            widget.set_sheet(png, *self.FRAME, col_start=1, col_count=1)
            self.assertEqual(widget.column_window(), (1, 1))
            self.assertLess(widget._grid_rect().width(), full_width)
            # The one application point really moved: the single visible cell
            # is painted from SHEET column 1, not from column 0.
            centre = widget._cell_rect(0, 0).center()
            painted = widget.grab().toImage().pixelColor(centre).getRgb()[:3]
            self.assertEqual(painted, self.COLOURS[1])

    def test_the_first_visible_column_is_column_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME, col_start=1, col_count=2)
            # cell_at IS the frame_clicked payload (mousePressEvent re-emits it
            # verbatim), so asserting it pins the signal's vocabulary.
            self.assertEqual(widget.cell_at(widget._cell_rect(0, 0).center()),
                             (0, 0))
            self.assertIsNone(widget.cell_at(widget._cell_rect(0, 2).center()))

    def test_a_window_past_the_right_edge_is_clamped_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME, col_start=2, col_count=99)
            self.assertEqual(widget.column_window(), (2, 1))

    def test_default_arguments_show_the_whole_sheet(self):
        with tempfile.TemporaryDirectory() as tmp:
            widget, png = self.preview(tmp)
            widget.set_sheet(png, *self.FRAME)
            self.assertEqual(widget.column_window(), (0, 3))
            before = widget.grab().toImage()

            widget.set_sheet(png, *self.FRAME, col_start=1, col_count=1)
            self.assertEqual(widget.column_window(), (1, 1))

            widget.set_sheet(png, *self.FRAME)      # a 3-arg call RESETS it
            self.assertEqual(widget.column_window(), (0, 3))
            self.assertEqual(widget.grab().toImage(), before)


class TestSheetPicker(DetailsCase):
    """The picker lists PNGs in data/sprites/imported/ and filters them by the
    target slot's frame size.

    Both fixture sheets are WRITTEN BY THE TEST, not borrowed from `data/`.
    These tests used to name `tile_buildable.png` as their "64x32 sheet" and
    `stone_thrower_t1_lvl1.png` as their "64x96 sheet"; cff77c7 re-linked
    tile_buildable to the forest sheet, which correctly refcount-deleted its
    PNG, and two tests went red over an art decision they were not testing.
    Orphan PNGs (no manifest entry) are listed on purpose — see ImportedSheet —
    so no entry is needed to pin these."""

    UNASSIGN = ("painter_t1_lvl1",)
    TALL = "imported/fixture_tall.png"    # 2x2 frames at 64x96 -> fits
    FLAT = "imported/fixture_flat.png"    # 2x2 frames at 64x32 -> does not

    def setUp(self):
        super().setUp()
        imported = self.data_dir / "sprites" / "imported"
        make_png(imported / "fixture_tall.png", 2 * 64, 2 * 96)
        make_png(imported / "fixture_flat.png", 2 * 64, 2 * 32)

    def dialog(self, slot="painter_t1_lvl1", frame=(64, 96)):
        return self.track(SheetPickerDialog(self.data_dir, slot, *frame))

    def test_defaults_to_sheets_that_fit_the_slots_frame_size(self):
        dialog = self.dialog()
        refs = {sheet.ref for sheet in dialog.visible_sheets()}
        # 64x96 sheets are offered; a 64x32 tile sheet is not.
        self.assertIn(self.TALL, refs)
        self.assertNotIn(self.FLAT, refs)

    def test_show_all_sizes_escapes_the_filter(self):
        dialog = self.dialog()
        dialog._all_sizes.setChecked(True)
        refs = {sheet.ref for sheet in dialog.visible_sheets()}
        self.assertIn(self.FLAT, refs)

    def test_name_filter_narrows_the_list(self):
        dialog = self.dialog()
        dialog._filter.setText("fixture_tall")
        names = [sheet.name for sheet in dialog.visible_sheets()]
        self.assertEqual(names, ["fixture_tall"])

    def test_selecting_a_sheet_previews_it_and_reports_the_choice(self):
        dialog = self.dialog()
        self.assertTrue(dialog.select_sheet(self.TALL))
        self.assertEqual(dialog.chosen().ref, self.TALL)
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


class TestRowEditorDefaults(QtCase):
    """A fresh row's FPS default and the no-mousewheel rule (root CLAUDE.md
    Editor no-mousewheel convention, editor/panels/CLAUDE.md)."""

    def test_fps_defaults_to_six_and_ignores_the_wheel(self):
        row = self.track(RowEditor(0, 3, ("idle",)))
        self.assertEqual(row.fps_spin.value(), 6)
        self.assertIsInstance(row.fps_spin, _NoWheelSpinBox)


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


class TestFrameSizeOverride(DetailsCase):
    """ER-5: the per-slot frame size — the one property of a slot the editor could
    not express. Frame size is a CATEGORY value; a slot may override it (ER-1's
    object form in slots.json).

    `enemy_stage_1_v1` is an `enemies` slot, so it inherits the category's 64x96.
    """

    SLOT = "enemy_stage_1_v1"
    UNASSIGN = (SLOT,)

    def slots_entry(self):
        """The raw slots.json entry for SLOT: a bare string (inherits) or the
        {key, frame_w, frame_h} override object."""
        doc = data_io.load_json(self.data_dir / "slots.json")
        for category in doc["categories"]:
            found = self._walk(category["groups"])
            if found is not None:
                return found
        self.fail(f"{self.SLOT} not in slots.json")

    def _walk(self, groups):
        for node in groups:
            for entry in node.get("slots", ()):
                key = entry if isinstance(entry, str) else entry["key"]
                if key == self.SLOT:
                    return entry
            found = self._walk(node.get("children", ()))
            if found is not None:
                return found
        return None

    def set_frame_size(self, w, h):
        self.panel._frame_w.setValue(w)
        self.panel._frame_h.setValue(h)
        self.panel._on_frame_size_changed()

    def test_the_spinboxes_show_the_slots_effective_frame_size(self):
        self.panel.set_slot(self.SLOT)
        self.assertEqual(
            (self.panel._frame_w.value(), self.panel._frame_h.value()), (64, 96))
        self.assertIsInstance(self.slots_entry(), str)   # inherits, no override yet

    def test_writing_an_override_needs_no_sheet(self):
        """Declaring the frame size BEFORE importing is the point — it is what the
        importer slices and pads against."""
        self.panel.set_slot(self.SLOT)
        self.set_frame_size(128, 128)
        self.assertEqual(self.slots_entry(),
                         {"key": self.SLOT, "frame_w": 128, "frame_h": 128})
        self.assertEqual(self.panel.registry.frame_size(self.SLOT), (128, 128))

    def test_the_category_size_removes_the_override(self):
        """Writing the category's own size back is how 'reset to default' is
        expressed — the entry returns to the bare-string form rather than carrying
        an override that overrides nothing."""
        self.panel.set_slot(self.SLOT)
        self.set_frame_size(128, 128)
        self.assertIsInstance(self.slots_entry(), dict)
        self.set_frame_size(64, 96)
        self.assertEqual(self.slots_entry(), self.SLOT)

    def test_an_imported_sheet_is_resliced_and_the_manifest_follows(self):
        """THE trap: AssetStore.frame_size resolves manifest entry > registry, so
        an imported slot carries its own frame_w/frame_h. Change the override and
        forget to re-slice, and the entry keeps shadowing the registry — the slot
        renders at the OLD size and the two files disagree on disk."""
        src = make_png(self.png_dir / "art.png", 128, 128)   # 2x1 at 64x96... 1x1 at 128
        self.panel.set_slot(self.SLOT)
        self.panel.import_sheet(src)
        self.panel.save()
        self.assertEqual(self.manifest_doc()["entries"][self.SLOT]["frame_w"], 64)

        self.set_frame_size(128, 128)

        entry = self.manifest_doc()["entries"][self.SLOT]
        self.assertEqual((entry["frame_w"], entry["frame_h"]), (128, 128))
        self.assertEqual(self.panel.registry.frame_size(self.SLOT), (128, 128))
        # Re-cut: the 128x128 sheet is now ONE 128x128 frame, not 2 cols x 1 row
        # of 64x96 (with a cropped remainder).
        self.assertEqual(len(self.panel._row_editors), 1)
        self.assertEqual(self.panel._row_editors[0].num_cols, 1)

    def test_the_shell_is_told_to_reload_its_registries(self):
        seen = []
        self.panel.registry_changed.connect(seen.append)
        self.panel.set_slot(self.SLOT)
        self.set_frame_size(128, 128)
        self.assertEqual(seen, [self.SLOT])

    def test_no_write_when_the_size_is_unchanged(self):
        self.panel.set_slot(self.SLOT)
        before = (self.data_dir / "slots.json").read_text(encoding="utf-8")
        self.set_frame_size(64, 96)          # already the effective size
        self.assertEqual((self.data_dir / "slots.json").read_text(encoding="utf-8"),
                         before)


class TestSliceMargins(DetailsCase):
    """Nine-slice margins (10L-A): a `ui`-only, optional manifest field. All
    four spins are the manifest's own [l, t, r, b] order; all-zero omits the
    key entirely (a slot with no nine-slice keeps a byte-identical entry, and
    zeroing un-slices a previously-sliced one on the next save)."""

    UNASSIGN = ("ui_button", "painter_t1_lvl1")

    def import_ui_button_sheet(self):
        src = make_png(self.png_dir / "ui.png", 2 * 64, 4 * 64)
        self.panel.set_context("ui", ("Buttons",))
        self.panel.set_slot("ui_button")
        self.panel.import_sheet(src)

    def test_ui_context_shows_the_slice_row_and_others_hide_it(self):
        self.panel.set_context("ui", ("Buttons",))
        self.assertFalse(self.panel._slice_row.isHidden())
        self.panel.set_context("buildings", ("Defender",))
        self.assertTrue(self.panel._slice_row.isHidden())

    def test_slice_spin_bounds_come_from_the_frame_size(self):
        self.panel.set_slot("ui_button")
        for spin in self.panel._slice_spins:
            self.assertEqual(spin.minimum(), 0)
        self.assertEqual(self.panel._slice_l.maximum(), 64)
        self.assertEqual(self.panel._slice_r.maximum(), 64)
        self.assertEqual(self.panel._slice_t.maximum(), 64)
        self.assertEqual(self.panel._slice_b.maximum(), 64)
        # A 64x96 buildings slot would cap T/B at 96 -- proves the axis
        # mapping, even though the row stays hidden on this category.
        self.panel.set_slot("stone_thrower_t1_lvl1")
        self.assertEqual(self.panel._slice_l.maximum(), 64)
        self.assertEqual(self.panel._slice_r.maximum(), 64)
        self.assertEqual(self.panel._slice_t.maximum(), 96)
        self.assertEqual(self.panel._slice_b.maximum(), 96)

    def test_slice_round_trips_through_save_and_reload(self):
        self.import_ui_button_sheet()
        for spin, value in zip(self.panel._slice_spins, (8, 6, 8, 6)):
            spin.setValue(value)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["ui_button"]
        self.assertEqual(entry["slice"], [8, 6, 8, 6])
        self.panel.set_slot(None)
        self.panel.set_slot("ui_button")            # re-read from disk
        self.assertEqual(
            tuple(spin.value() for spin in self.panel._slice_spins),
            (8, 6, 8, 6))

    def test_all_zero_margins_omit_the_slice_key(self):
        self.import_ui_button_sheet()
        self.panel.save()
        entry = self.manifest_doc()["entries"]["ui_button"]
        self.assertNotIn("slice", entry)
        self.assertNotIn("slice", self.panel.draft_entry())

    def test_zeroing_margins_removes_the_key_on_resave(self):
        self.import_ui_button_sheet()
        for spin, value in zip(self.panel._slice_spins, (8, 6, 8, 6)):
            spin.setValue(value)
        self.panel.save()
        for spin in self.panel._slice_spins:
            spin.setValue(0)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["ui_button"]
        self.assertNotIn("slice", entry)

    def test_non_ui_category_never_emits_slice(self):
        self.panel.set_context("buildings", ("Defender",))
        src = make_png(self.png_dir / "painter.png", 64, 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        self.panel._slice_l.setValue(9)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["painter_t1_lvl1"]
        self.assertNotIn("slice", entry)
        self.assertNotIn("slice", self.panel.draft_entry())

    def test_slice_edit_emits_a_draft(self):
        self.import_ui_button_sheet()
        drafts = []
        self.panel.draft_changed.connect(lambda slot, e: drafts.append(e))
        self.panel._slice_l.setValue(5)
        self.assertEqual(drafts[-1]["slice"], [5, 0, 0, 0])

    def test_four_row_button_sheet_offers_the_ui_vocabulary(self):
        """1b verification: the ui vocab's 4-row importer path."""
        self.import_ui_button_sheet()
        self.assertEqual(len(self.panel._row_editors), 4)
        row0 = self.panel._row_editors[0]
        self.assertEqual(
            [row0.anim_combo.itemText(i) for i in range(row0.anim_combo.count())],
            ["idle"])
        self.assertFalse(row0.anim_combo.isEnabled())
        for row, default in zip(self.panel._row_editors[1:],
                                 ("hover", "pressed", "disabled")):
            self.assertEqual(
                [row.anim_combo.itemText(i) for i in range(row.anim_combo.count())],
                ["idle", "hover", "pressed", "disabled"])
            self.assertEqual(row.anim_combo.currentText(), default)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["ui_button"]
        self.assertEqual([r["animation"] for r in entry["rows"]],
                         ["idle", "hover", "pressed", "disabled"])


class TestConditionTintCheckbox(DetailsCase):
    """The `conditions` category's tint fallback toggle. The game draws a flat
    colour diamond per non-grass tile; that is a FALLBACK, so a slot with no
    art forces it on (checked + disabled — there is no entry to write it to),
    and once art exists the designer chooses. `tint_overlay` is optional in the
    manifest: unchecked omits it entirely."""

    UNASSIGN = ("cond_mountain_buildable", "painter_t1_lvl1")
    CONTEXT = ("conditions", ("Mountain", "Buildable"))

    def import_condition_sheet(self):
        src = make_png(self.png_dir / "mountain.png", 64, 96)
        self.panel.set_context(*self.CONTEXT)
        self.panel.set_slot("cond_mountain_buildable")
        self.panel.import_sheet(src)

    def test_conditions_context_shows_the_row_and_others_hide_it(self):
        self.panel.set_context(*self.CONTEXT)
        self.assertFalse(self.panel._tint_row.isHidden())
        self.panel.set_context("ui", ("Buttons",))
        self.assertTrue(self.panel._tint_row.isHidden())

    def test_no_art_forces_the_tint_on_and_locks_it(self):
        self.panel.set_context(*self.CONTEXT)
        self.panel.set_slot("cond_mountain_buildable")
        self.assertTrue(self.panel._tint_check.isChecked())
        self.assertFalse(self.panel._tint_check.isEnabled())

    def test_importing_art_unlocks_the_choice(self):
        """The gate is the LIVE rows, not the on-disk entry — so the box is
        editable before the first save."""
        self.import_condition_sheet()
        self.assertTrue(self.panel._tint_check.isEnabled())

    def test_unchecked_omits_the_key(self):
        self.import_condition_sheet()
        self.panel._tint_check.setChecked(False)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["cond_mountain_buildable"]
        self.assertNotIn("tint_overlay", entry)
        self.assertNotIn("tint_overlay", self.panel.draft_entry())

    def test_checked_round_trips_through_save_and_reload(self):
        self.import_condition_sheet()
        self.panel._tint_check.setChecked(True)
        self.panel.save()
        self.assertIs(
            self.manifest_doc()["entries"]["cond_mountain_buildable"]["tint_overlay"],
            True)
        self.panel.set_slot(None)
        self.panel.set_slot("cond_mountain_buildable")        # re-read from disk
        self.assertTrue(self.panel._tint_check.isChecked())
        self.assertTrue(self.panel._tint_check.isEnabled())

    def test_unticking_removes_the_key_on_resave(self):
        self.import_condition_sheet()
        self.panel._tint_check.setChecked(True)
        self.panel.save()
        self.panel._tint_check.setChecked(False)
        self.panel.save()
        self.assertNotIn("tint_overlay",
                         self.manifest_doc()["entries"]["cond_mountain_buildable"])

    def test_clearing_the_entry_forces_the_tint_back_on(self):
        self.import_condition_sheet()
        self.panel._tint_check.setChecked(True)
        self.panel.save()
        self.panel.clear_entry(confirm=False)
        self.assertTrue(self.panel._tint_check.isChecked())
        self.assertFalse(self.panel._tint_check.isEnabled())

    def test_other_categories_never_emit_the_key(self):
        self.panel.set_context("buildings", ("Defender",))
        src = make_png(self.png_dir / "painter.png", 64, 96)
        self.panel.set_slot("painter_t1_lvl1")
        self.panel.import_sheet(src)
        self.panel._tint_check.setChecked(True)
        self.panel.save()
        entry = self.manifest_doc()["entries"]["painter_t1_lvl1"]
        self.assertNotIn("tint_overlay", entry)
        self.assertNotIn("tint_overlay", self.panel.draft_entry())

    def test_toggling_emits_a_draft(self):
        self.import_condition_sheet()
        drafts = []
        self.panel.draft_changed.connect(lambda slot, e: drafts.append(e))
        self.panel._tint_check.setChecked(True)
        self.assertIs(drafts[-1]["tint_overlay"], True)


class TestMasterSheetColumns(DetailsCase):
    """E3 — the COLUMN row: the row window's horizontal twin. The column is
    ENTRY state (saved by Save, never written on edit), the width is INHERITED
    from the sheet's registry entry, and an off-sheet column is unrepresentable
    rather than a save-time error.

    The master registry ships EMPTY, so the fixture sheet is imported here —
    never borrowed from live `data/`."""

    UNASSIGN = ("painter_t1_lvl1",)

    SLOT = "painter_t1_lvl1"
    #: Deliberately not the painter category's own 64×96 (the grid is inherited).
    FRAME = (32, 48)
    #: 8 frame-columns at 2 per master column ⇒ 4 master columns, last = 3.
    COLS, ROWS, WIDTH = 8, 3, 2

    def setUp(self):
        super().setUp()
        src = make_png(self.png_dir / "master_cols.png",
                       self.COLS * self.FRAME[0], self.ROWS * self.FRAME[1])
        self.sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, src, "Column Folk", *self.FRAME, self.WIDTH)
        self.ref = f"master/{self.sheet_id}.png"
        self.manifest_json = (self.data_dir / "sprites" / "asset_manifest.json")
        self.slots_json = self.data_dir / "slots.json"

    def link(self):
        self.panel.set_slot(self.SLOT)
        return self.panel.use_master_sheet(self.sheet_id)

    def set_column(self, column, mode_label="Manual"):
        """Drive the widgets the way the designer does, then commit."""
        self.panel._column_spin.setValue(column)
        self.panel._column_mode_combo.setCurrentText(mode_label)
        self.panel._on_column_changed()

    def test_the_column_row_shows_only_for_a_master_sheet(self):
        self.panel.set_slot(self.SLOT)
        self.panel.import_sheet(make_png(self.png_dir / "own.png", 64, 2 * 96))
        self.assertTrue(self.panel._column_row.isHidden())
        self.link()
        self.assertFalse(self.panel._column_row.isHidden())
        # The width is inherited, so it is shown but never editable (D1).
        self.assertFalse(self.panel._column_width_display.isEnabled())
        self.assertEqual(self.panel._column_width_display.value(), self.WIDTH)

    def test_setting_the_column_recuts_the_preview_and_writes_nothing(self):
        self.link()
        self.assertEqual(self.panel._preview.column_window(), (0, self.WIDTH))
        manifest_before = self.manifest_json.read_bytes()
        slots_before = self.slots_json.read_bytes()

        self.set_column(2)

        self.assertEqual(self.panel._preview.column_window(),
                         (2 * self.WIDTH, self.WIDTH))
        # Entry state, saved by Save: no manifest write, and — unlike
        # _on_frame_size_changed — no slots.json override either.
        self.assertEqual(self.manifest_json.read_bytes(), manifest_before)
        self.assertEqual(self.slots_json.read_bytes(), slots_before)
        self.assertNotIn(self.SLOT, self.manifest_doc()["entries"])

    def test_save_writes_the_column_keys(self):
        self.link()
        self.set_column(2, "Season")
        self.panel.save()
        entry = self.manifest_doc()["entries"][self.SLOT]
        self.assertEqual(entry["column"], 2)
        self.assertEqual(entry["column_mode"], "season")
        self.assertEqual(entry["column_width"], self.WIDTH)

        self.panel.set_slot(None)
        self.panel.set_slot(self.SLOT)               # re-read from disk
        self.assertEqual((self.panel._column, self.panel._column_mode),
                         (2, "season"))

    def test_save_omits_each_column_key_at_its_default(self):
        self.link()
        self.set_column(0, "Manual")
        self.assertNotIn("column", self.panel.draft_entry())
        self.assertNotIn("column_mode", self.panel.draft_entry())
        # 0 is the absent-key in-memory default, never an authored width.
        self.panel._column_width = 0
        self.assertNotIn("column_width", self.panel.draft_entry())

    def test_a_path_that_does_not_author_columns_preserves_them(self):
        self.link()
        self.set_column(3, "Building colour")
        self.panel.save()

        # A plain per-slot import never shows the column row — and must not
        # erase what the master link saved (the `anchors` rule in reverse).
        self.panel.set_slot(self.SLOT)
        self.panel.import_sheet(make_png(self.png_dir / "own.png", 64, 2 * 96))
        self.panel.save()
        entry = self.manifest_doc()["entries"][self.SLOT]
        self.assertEqual(entry["column"], 3)
        self.assertEqual(entry["column_mode"], "building_color")
        self.assertEqual(entry["column_width"], self.WIDTH)

    def test_linking_adopts_the_sheets_column_width(self):
        from engine.assets import master_registry

        self.link()
        self.assertEqual(
            self.panel._column_width,
            master_registry.column_width_for(
                master_sheet_import.load_registry_doc(self.data_dir), self.ref))

    def test_the_column_spin_ceiling_is_the_sheets_last_column(self):
        self.link()
        self.assertEqual(self.panel._column_spin.maximum(),
                         self.COLS // self.WIDTH - 1)

    def test_an_entry_saved_before_columns_falls_back_to_the_registry(self):
        self.link()
        self.panel.save()
        doc = self.panel._read_doc()
        del doc["entries"][self.SLOT]["column_width"]   # a pre-E3 entry
        self.panel._write_doc(doc)

        self.panel.set_slot(None)
        self.panel.set_slot(self.SLOT)
        self.assertEqual(self.panel._column_width, self.WIDTH)
        self.assertEqual(self.panel._column_spin.maximum(),
                         self.COLS // self.WIDTH - 1)


if __name__ == "__main__":
    unittest.main()
