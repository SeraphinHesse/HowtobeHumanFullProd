"""GpuAndMasterSheetsPLAN M3 — editor/master_sheet_import.py + the picker.

Every test here writes its OWN entries and asserts against those alone.
Writes land in a temp `data/` copy (`DataDirCase`/`TempDataCase`) — the whole
tree copy already carries `sprites/master_sheets.json` and `sprites/master/`,
so the helper needed no extension.

**Any test that asserts the FULL contents of the registry must call
`pin_empty_registry(self.data_dir)` first.** This file originally said "the
registry ships EMPTY, so every test here … never asserts a count against live
`data/`" — but shipping empty is a fact about today's `data/`, not a property
of the fixture, and three tests quietly depended on it. The first real master
sheet landed on 2026-08-13 and turned all three red at once: they were asserting
against live `data/` content while believing they were not. That is the exact
breakage the root `CLAUDE.md` names ("Tests that assumed 'this slot has no art'
… is what put 18 tests permanently in the red"). Pin the fixture; never assume
the project owns no art.
"""
import json
import unittest

from PIL import Image

from editor import master_sheet_import
from engine import data_io
from tools.tests.temp_data import DataDirCase, TempDataCase


def make_png(path, width, height, colour=(30, 90, 200, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (width, height), colour).save(path)
    return path


def pin_empty_registry(data_dir):
    """Empty this test's copy of the master-sheet registry, so a whole-registry
    assertion sees only what the test itself imports.

    `fresh_data_dir` copies the LIVE tree, real art included. Going through
    `write_registry_doc` keeps the file schema-valid (it is the one write path,
    ED-31). Leaving stray PNGs in `sprites/master/` is harmless: `master_sheets`
    treats the REGISTRY as authoritative, so a PNG with no entry is not a sheet.
    """
    master_sheet_import.write_registry_doc(
        data_dir, {"version": 1, "entries": {}})


class MasterSheetImportTest(DataDirCase):
    """The pure module: no Qt."""

    def setUp(self):
        super().setUp()
        pin_empty_registry(self.data_dir)
        self.source = make_png(self.data_dir / "incoming" / "raw.png", 128, 192)

    def registry(self):
        return data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json")

    def test_import_writes_png_and_schema_valid_entry(self):
        sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 2,
            columns=("red", "blue"))
        self.assertEqual(sheet_id, "village_folk")
        png = self.data_dir / "sprites" / "master" / "village_folk.png"
        self.assertTrue(png.is_file())
        # write_registry_doc goes through write_validated, so a re-load that
        # carries the required keys is the validity assertion. `column_width`
        # is the DESIGNER'S value now (E1), not derived from the PNG's width.
        self.assertEqual(
            self.registry()["entries"]["village_folk"],
            {"file": "master/village_folk.png", "display_name": "Village Folk",
             "frame_w": 32, "frame_h": 48, "column_width": 2,
             "columns": ["red", "blue"]})

    def test_no_colour_names_omits_the_columns_key(self):
        """Omit-at-default: an unnamed sheet carries no `columns` at all."""
        master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 4)
        self.assertNotIn("columns", self.registry()["entries"]["village_folk"])

    def test_reimport_same_bytes_leaves_the_file_untouched(self):
        sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 4)
        png = self.data_dir / "sprites" / "master" / f"{sheet_id}.png"
        before, mtime = png.read_bytes(), png.stat().st_mtime_ns

        again = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 64, 4)

        self.assertEqual(again, sheet_id)
        self.assertEqual(png.read_bytes(), before)
        self.assertEqual(png.stat().st_mtime_ns, mtime)
        # …but the ENTRY is rewritten, so a wrong grid is correctable (M3 rule).
        self.assertEqual(self.registry()["entries"][sheet_id]["frame_h"], 64)

    def test_slugify_and_collision_never_overwrites(self):
        first = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk!! v1", 32, 48, 4)
        self.assertEqual(first, "village_folk_v1")
        digits = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "d.png", 8, 8),
            "2nd batch", 8, 8, 1)
        self.assertEqual(digits, "sheet_2nd_batch")

        other = make_png(self.data_dir / "incoming" / "other.png", 64, 64,
                         colour=(200, 30, 30, 255))
        second = master_sheet_import.import_master_sheet(
            self.data_dir, other, "Village Folk!! v1", 16, 16, 4)

        self.assertEqual(second, "village_folk_v1_2")
        entries = self.registry()["entries"]
        self.assertEqual(entries[first]["frame_w"], 32)      # not clobbered
        self.assertEqual(entries[second]["file"],
                         "master/village_folk_v1_2.png")

    def test_master_sheets_lists_users_orphans_and_sorts_by_display_name(self):
        shared = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "zebra crowd", 32, 48, 2)
        orphan = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "o.png", 8, 8),
            "Alpha spare", 8, 8, 1)

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
        # grid() counts FRAME columns; column_count() counts MASTER columns at
        # the sheet's own column_width: 128px // (2 frames * 32px) == 2.
        self.assertEqual(by_id[shared].column_count(), 2)
        self.assertEqual(by_id[orphan].users, ())       # listed anyway (§9)
        # "Alpha spare" before "zebra crowd" — display_name, case-insensitive.
        self.assertEqual([sheet.sheet_id for sheet in sheets],
                         [orphan, shared])


class LoadRegistryDocDegradesTest(DataDirCase):
    """MasterSheetColumnsPLAN C3 — the READ now delegates to
    `engine.assets.master_registry.load_registry` (which fails loud), so the
    E-37 degrade-to-empty-doc wrapper is the thing that must still hold."""

    EMPTY = {"version": 1, "entries": {}}

    def test_missing_registry_reads_as_an_empty_doc(self):
        master_sheet_import.registry_path(self.data_dir).unlink()
        self.assertEqual(
            master_sheet_import.load_registry_doc(self.data_dir), self.EMPTY)

    def test_corrupt_registry_reads_as_an_empty_doc(self):
        master_sheet_import.registry_path(self.data_dir).write_text(
            "{not json at all", encoding="utf-8")
        self.assertEqual(
            master_sheet_import.load_registry_doc(self.data_dir), self.EMPTY)


class RegistryUnreadableTest(DataDirCase):
    """An import must REFUSE an existing-but-unreadable registry, never merge
    into the degraded empty doc and write every other sheet out of existence.
    C1 made `column_width` required, so every pre-C1 registry is schema-invalid
    by construction and would otherwise hit exactly this."""

    def test_schema_invalid_registry_refuses_the_import_and_touches_nothing(self):
        pin_empty_registry(self.data_dir)
        source = make_png(self.data_dir / "incoming" / "raw.png", 128, 192)
        master_sheet_import.import_master_sheet(
            self.data_dir, source, "Village Folk", 32, 48, 4)

        registry = master_sheet_import.registry_path(self.data_dir)
        doc = data_io.load_json(registry)
        # Strip the required key: schema-invalid, exactly like a pre-C1 file.
        for entry in doc["entries"].values():
            entry.pop("column_width", None)
        registry.write_text(json.dumps(doc), encoding="utf-8")
        before = registry.read_bytes()

        other = make_png(self.data_dir / "incoming" / "other.png", 64, 64)
        with self.assertRaises(master_sheet_import.RegistryUnreadableError):
            master_sheet_import.import_master_sheet(
                self.data_dir, other, "Other Sheet", 32, 32, 2)

        self.assertEqual(registry.read_bytes(), before)   # nothing overwritten
        self.assertFalse(                                 # no orphan PNG either
            (self.data_dir / "sprites" / "master" / "other_sheet.png").exists())

    def test_a_missing_registry_is_still_a_normal_import(self):
        master_sheet_import.registry_path(self.data_dir).unlink()
        source = make_png(self.data_dir / "incoming" / "raw.png", 128, 192)
        sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, source, "Village Folk", 32, 48, 4)
        self.assertIn(
            sheet_id,
            master_sheet_import.load_registry_doc(self.data_dir)["entries"])


class GridInUseTest(DataDirCase):
    """M4 §2.1 — a re-import may not re-cut a sheet slots already window into."""

    def setUp(self):
        super().setUp()
        pin_empty_registry(self.data_dir)
        self.source = make_png(self.data_dir / "incoming" / "raw.png", 128, 192)
        self.sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 2)

    def link_slots(self, *slots):
        path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(path)
        for slot in slots:
            doc["entries"][slot] = {
                "sheet": f"master/{self.sheet_id}.png",
                "frame_w": 32, "frame_h": 48, "offset_x": 0, "offset_y": 0,
                "rows": [{"animation": "idle", "frames": 4, "fps": 8,
                          "hidden": [], "loop_start": 0, "loop_end": 0,
                          "loop_count": 1}]}
        data_io.write_validated(
            doc, path, self.data_dir / "schemas" / "asset_manifest.schema.json")

    def test_changed_grid_with_users_is_refused_and_writes_nothing(self):
        self.link_slots("painter_t1_lvl1", "flute_player_t1_lvl1")
        png = self.data_dir / "sprites" / "master" / f"{self.sheet_id}.png"
        registry_path = self.data_dir / "sprites" / "master_sheets.json"
        before_png, before_registry = png.read_bytes(), registry_path.read_bytes()

        with self.assertRaises(master_sheet_import.GridInUseError) as caught:
            master_sheet_import.import_master_sheet(
                self.data_dir, self.source, "Village Folk", 64, 64, 2)

        message = str(caught.exception)
        self.assertIn("painter_t1_lvl1", message)      # names the users to fix
        self.assertIn("flute_player_t1_lvl1", message)
        # A ValueError subclass, so the dialog's existing except clause shows it.
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(png.read_bytes(), before_png)
        self.assertEqual(registry_path.read_bytes(), before_registry)

    def test_changed_grid_with_zero_users_still_rewrites_the_entry(self):
        again = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 64, 64, 2)
        self.assertEqual(again, self.sheet_id)
        entry = data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json")["entries"][again]
        self.assertEqual((entry["frame_w"], entry["frame_h"]), (64, 64))

    def test_changed_column_width_alone_with_users_is_refused(self):
        """D10 — the guard covers the COLUMN axis too: an unchanged frame size
        does not make a `column_width` change safe, it re-points every column
        window at different pixels."""
        self.link_slots("painter_t1_lvl1")
        with self.assertRaises(master_sheet_import.GridInUseError) as caught:
            master_sheet_import.import_master_sheet(
                self.data_dir, self.source, "Village Folk", 32, 48, 4)
        self.assertIn("painter_t1_lvl1", str(caught.exception))

    def test_changed_column_width_with_zero_users_rewrites_the_entry(self):
        again = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 4)
        self.assertEqual(again, self.sheet_id)
        entry = data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json")["entries"][again]
        self.assertEqual(entry["column_width"], 4)

    def test_reimporting_a_family_members_bytes_reuses_that_member(self):
        """M4 §2.2 — the byte-identity check scans the slug FAMILY, so
        re-importing `<slug>_2`'s own bytes must not mint `<slug>_3`."""
        other = make_png(self.data_dir / "incoming" / "other.png", 64, 64,
                         colour=(200, 30, 30, 255))
        second = master_sheet_import.import_master_sheet(
            self.data_dir, other, "Village Folk", 16, 16, 4)
        self.assertEqual(second, f"{self.sheet_id}_2")

        again = master_sheet_import.import_master_sheet(
            self.data_dir, other, "Village Folk", 16, 16, 4)

        self.assertEqual(again, second)
        self.assertEqual(
            sorted(data_io.load_json(
                self.data_dir / "sprites" / "master_sheets.json")["entries"]),
            [self.sheet_id, second])


class ParseColumnsTest(unittest.TestCase):
    """E1 — the Colours field's pure slugify+validate step. No filesystem: the
    schema bounds fall back to their own numbers when no data_dir is given."""

    def test_slugifies_and_drops_blanks(self):
        self.assertEqual(
            master_sheet_import.parse_columns(" Deep Red, , ANCIENT-blue "),
            ("deep_red", "ancient_blue"))

    def test_duplicate_slug_is_rejected(self):
        with self.assertRaises(ValueError):
            master_sheet_import.parse_columns("Red, red")


class MasterSheetDialogTest(TempDataCase):
    """The Qt half: constructs, lists, selects — never exec()s a modal."""

    def setUp(self):
        super().setUp()
        pin_empty_registry(self.data_dir)

    def test_dialog_lists_registry_and_returns_the_selected_id(self):
        from editor.panels.master_sheet_dialog import MasterSheetDialog

        source = make_png(self.data_dir / "incoming" / "raw.png", 64, 64)
        first = master_sheet_import.import_master_sheet(
            self.data_dir, source, "Alpha crowd", 32, 32, 2)
        second = master_sheet_import.import_master_sheet(
            self.data_dir, make_png(self.data_dir / "incoming" / "b.png", 16, 8),
            "Beta crowd", 8, 8, 2)

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
        dialog._column_width.setValue(2)
        dialog._colours.setText("Pink, Blue")
        imported = dialog.perform_import()
        self.assertEqual(imported, "gamma_crowd")
        self.assertEqual(dialog.chosen(), "gamma_crowd")
        self.assertIn("gamma_crowd",
                      [s.sheet_id for s in dialog.visible_sheets()])
        # E1 — the two new fields reach the registry, slugified.
        entry = data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json"
        )["entries"]["gamma_crowd"]
        self.assertEqual(entry["column_width"], 2)
        self.assertEqual(entry["columns"], ["pink", "blue"])


if __name__ == "__main__":
    unittest.main()
