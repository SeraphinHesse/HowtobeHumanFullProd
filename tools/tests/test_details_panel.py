"""DetailsPanel (ED-40/41) + LevelBar — importer parity, headless.

Conventions: offscreen Qt + SDL dummy env, one QApplication, TempDataCase
tempfile copy of data/ (the repo's migrated manifest + PNGs come along).
Synthetic sheets are authored with Pillow (the panel's own image dep).
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PIL import Image
from PySide6.QtWidgets import QApplication

from editor.panels.details import DetailsPanel
from editor.panels.level_bar import LevelBar
from engine import data_io
from tools.tests.test_editor_panels import TempDataCase

_APP = QApplication.instance() or QApplication(sys.argv)


def make_png(path, w, h, colour=(200, 60, 60, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), colour).save(path)
    return path


class DetailsCase(TempDataCase):
    def setUp(self):
        super().setUp()
        self.panel = DetailsPanel(data_dir=self.data_dir)
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


class TestSubcategoryDropdown(DetailsCase):
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


class TestLevelBar(unittest.TestCase):
    def test_levels_and_signal(self):
        bar = LevelBar()
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
        bar = LevelBar()
        bar.set_levels(("only",))
        self.assertTrue(bar.isHidden())
        self.assertEqual(bar.level(), 0)

    def test_can_add_keeps_single_slot_bar_and_button_visible(self):
        # an enemy era with ONE variant must still show the "+ Variant" button
        bar = LevelBar()
        requested = []
        bar.add_variant_requested.connect(lambda: requested.append(True))
        bar.set_levels(("enemy_stage_2",), can_add=True)
        self.assertFalse(bar.isHidden())
        self.assertFalse(bar._add_btn.isHidden())
        bar._add_btn.click()
        self.assertEqual(requested, [True])

    def test_add_button_hidden_without_can_add(self):
        bar = LevelBar()
        bar.set_levels(("a_lvl1", "a_lvl2", "a_lvl3"))
        self.assertTrue(bar._add_btn.isHidden())

    def test_select_last_reports_the_new_variant(self):
        bar = LevelBar()
        seen = []
        bar.level_changed.connect(seen.append)
        bar.set_levels(("v1", "v2"), can_add=True)
        bar.select_last()
        self.assertEqual(bar.level(), 1)
        self.assertEqual(seen, [1])


if __name__ == "__main__":
    unittest.main()
