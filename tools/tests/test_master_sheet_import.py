"""GpuAndMasterSheetsPLAN M3 — editor/master_sheet_import.py + the picker.

The registry ships EMPTY (`data/sprites/master_sheets.json`), so every test
here writes its OWN entries and never asserts a count against live `data/`.
Writes land in a temp `data/` copy (`DataDirCase`/`TempDataCase`) — the whole
tree copy already carries `sprites/master_sheets.json` and `sprites/master/`,
so the helper needed no extension.
"""
import unittest

from PIL import Image

from editor import master_sheet_import
from engine import data_io
from tools.tests.temp_data import DataDirCase, TempDataCase


def make_png(path, width, height, colour=(30, 90, 200, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (width, height), colour).save(path)
    return path


class MasterSheetImportTest(DataDirCase):
    """The pure module: no Qt."""

    def setUp(self):
        super().setUp()
        self.source = make_png(self.data_dir / "incoming" / "raw.png", 128, 192)

    def registry(self):
        return data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json")

    def test_import_writes_png_and_schema_valid_entry(self):
        sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48)
        self.assertEqual(sheet_id, "village_folk")
        png = self.data_dir / "sprites" / "master" / "village_folk.png"
        self.assertTrue(png.is_file())
        # write_registry_doc goes through write_validated, so a re-load that
        # carries exactly the four required keys is the validity assertion.
        self.assertEqual(
            self.registry()["entries"]["village_folk"],
            {"file": "master/village_folk.png", "display_name": "Village Folk",
             "frame_w": 32, "frame_h": 48})

    def test_reimport_same_bytes_leaves_the_file_untouched(self):
        sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48)
        png = self.data_dir / "sprites" / "master" / f"{sheet_id}.png"
        before, mtime = png.read_bytes(), png.stat().st_mtime_ns

        again = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 64)

        self.assertEqual(again, sheet_id)
        self.assertEqual(png.read_bytes(), before)
        self.assertEqual(png.stat().st_mtime_ns, mtime)
        # …but the ENTRY is rewritten, so a wrong grid is correctable (M3 rule).
        self.assertEqual(self.registry()["entries"][sheet_id]["frame_h"], 64)

    def test_slugify_and_collision_never_overwrites(self):
        first = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk!! v1", 32, 48)
        self.assertEqual(first, "village_folk_v1")
        digits = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "d.png", 8, 8),
            "2nd batch", 8, 8)
        self.assertEqual(digits, "sheet_2nd_batch")

        other = make_png(self.data_dir / "incoming" / "other.png", 64, 64,
                         colour=(200, 30, 30, 255))
        second = master_sheet_import.import_master_sheet(
            self.data_dir, other, "Village Folk!! v1", 16, 16)

        self.assertEqual(second, "village_folk_v1_2")
        entries = self.registry()["entries"]
        self.assertEqual(entries[first]["frame_w"], 32)      # not clobbered
        self.assertEqual(entries[second]["file"],
                         "master/village_folk_v1_2.png")

    def test_master_sheets_lists_users_orphans_and_sorts_by_display_name(self):
        shared = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "zebra crowd", 32, 48)
        orphan = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "o.png", 8, 8),
            "Alpha spare", 8, 8)

        path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(path)
        for slot in ("painter_t1_lvl1", "flute_player_t1_lvl1"):
            doc["entries"][slot] = {
                "sheet": f"master/{shared}.png", "frame_w": 32, "frame_h": 48,
                "offset_x": 0, "offset_y": 0,
                "rows": [{"animation": "idle", "frames": 4, "fps": 8,
                          "hidden": [], "loop_start": 0, "loop_end": 0,
                          "loop_count": 1}]}
        data_io.write_validated(
            doc, path, self.data_dir / "schemas" / "asset_manifest.schema.json")

        sheets = master_sheet_import.master_sheets(self.data_dir)
        by_id = {sheet.sheet_id: sheet for sheet in sheets}
        self.assertEqual(by_id[shared].users,
                         ("flute_player_t1_lvl1", "painter_t1_lvl1"))
        self.assertEqual(by_id[shared].grid(), (4, 4))
        self.assertEqual(by_id[orphan].users, ())       # listed anyway (§9)
        # "Alpha spare" before "zebra crowd" — display_name, case-insensitive.
        self.assertEqual([sheet.sheet_id for sheet in sheets],
                         [orphan, shared])


class MasterSheetDialogTest(TempDataCase):
    """The Qt half: constructs, lists, selects — never exec()s a modal."""

    def test_dialog_lists_registry_and_returns_the_selected_id(self):
        from editor.panels.master_sheet_dialog import MasterSheetDialog

        source = make_png(self.data_dir / "incoming" / "raw.png", 64, 64)
        first = master_sheet_import.import_master_sheet(
            self.data_dir, source, "Alpha crowd", 32, 32)
        second = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "b.png", 16, 8),
            "Beta crowd", 8, 8)

        dialog = self.track(MasterSheetDialog(data_dir=self.data_dir))
        self.assertEqual([s.sheet_id for s in dialog.visible_sheets()],
                         [first, second])
        self.assertTrue(dialog.select_sheet(second))
        self.assertEqual(dialog.chosen(), second)

        # The import branch, without QFileDialog.
        dialog.set_import_source(
            make_png(self.data_dir / "incoming" / "c.png", 24, 24))
        dialog._name.setText("Gamma crowd")
        dialog._frame_w.setValue(12)
        dialog._frame_h.setValue(12)
        imported = dialog.perform_import()
        self.assertEqual(imported, "gamma_crowd")
        self.assertEqual(dialog.chosen(), "gamma_crowd")
        self.assertIn("gamma_crowd",
                      [s.sheet_id for s in dialog.visible_sheets()])


if __name__ == "__main__":
    unittest.main()
