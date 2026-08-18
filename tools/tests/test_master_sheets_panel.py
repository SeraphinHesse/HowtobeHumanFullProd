"""MasterSheetColumnsPLAN E5 — editor/panels/master_sheets.py.

Bare minimum: what the panel lists, what it reports, the D10 lock, the two
write paths and the selector/right_stack routing. Every test seeds its OWN
registry into a temp `data/` copy after `pin_empty_registry` — never asserts
against live `data/` content (root CLAUDE.md).
"""
import unittest

from tools.tests.qt_harness import APP as _APP  # noqa: F401  (headless env first)

from editor import master_sheet_import
from editor.main import MainWindow
from editor.panels.master_sheets import MasterSheetsPanel
from engine import data_io
from tools.tests.temp_data import TempDataCase
from tools.tests.test_master_sheet_import import make_png, pin_empty_registry


class MasterSheetsPanelTest(TempDataCase):
    def setUp(self):
        super().setUp()
        pin_empty_registry(self.data_dir)
        self.source = make_png(self.data_dir / "incoming" / "a.png", 128, 192)
        self.sheet_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.source, "Village Folk", 32, 48, 2,
            columns=("red", "blue"))
        self.other = make_png(self.data_dir / "incoming" / "b.png", 64, 64,
                              colour=(9, 9, 9, 255))
        self.other_id = master_sheet_import.import_master_sheet(
            self.data_dir, self.other, "Alpha Crowd", 32, 32, 1)

    def make(self):
        return self.track(MasterSheetsPanel(data_dir=self.data_dir))

    def link_slots(self, *slots):
        path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(path)
        for slot in slots:
            doc["entries"][slot] = {
                "sheet": f"master/{self.sheet_id}.png",
                # The COPY of the registry's column_width that `details._save`
                # stamps at link time — what a column-width edit must re-stamp.
                "column_width": 2,
                "frame_w": 32, "frame_h": 48, "offset_x": 0, "offset_y": 0,
                "rows": [{"animation": "idle", "frames": 4, "fps": 8,
                          "hidden": [], "loop_start": 0, "loop_end": 0,
                          "loop_count": 1}]}
        data_io.write_validated(
            doc, path, self.data_dir / "schemas" / "asset_manifest.schema.json")

    def registry(self):
        return data_io.load_json(
            self.data_dir / "sprites" / "master_sheets.json")

    # -- listing + detail ----------------------------------------------------

    def test_lists_exactly_what_the_registry_holds(self):
        panel = self.make()
        self.assertEqual([s.sheet_id for s in panel.sheets()],
                         ["alpha_crowd", "village_folk"])  # by display name
        self.assertEqual(panel._list.count(), 2)

    def test_detail_reports_grid_column_width_columns_and_users(self):
        self.link_slots("painter_t1_lvl1")
        panel = self.make()
        self.assertTrue(panel.select_sheet(self.sheet_id))
        text = panel.detail_text()
        self.assertIn("4×4 frames at 32×48", text)   # 128x192 at 32x48
        self.assertIn("Column width 2", text)
        self.assertIn("red, blue", text)
        self.assertIn("Used by 1 slot(s)", text)
        self.assertIn("painter_t1_lvl1", text)

    # -- D10 lock ------------------------------------------------------------

    def test_frame_grid_locked_while_slots_link_but_column_width_is_not(self):
        self.link_slots("painter_t1_lvl1")
        panel = self.make()
        panel.select_sheet(self.sheet_id)
        self.assertFalse(panel._frame_w.isEnabled())
        self.assertFalse(panel._frame_h.isEnabled())
        self.assertIn("painter_t1_lvl1", panel._lock_label.text())
        # D10 locks the FRAME GRID only. Colour names re-cut nothing, and
        # column width is per-sheet metadata whose linking copies are
        # re-stamped on save — locking either made the value uncorrectable
        # once the first slot linked.
        self.assertTrue(panel._column_width.isEnabled())
        self.assertTrue(panel._colours.isEnabled())
        self.assertTrue(panel._save.isEnabled())

        panel.select_sheet(self.other_id)          # nothing links to this one
        self.assertTrue(panel._frame_w.isEnabled())
        self.assertTrue(panel._column_width.isEnabled())
        self.assertTrue(panel._save.isEnabled())

    def test_save_keeps_frame_grid_but_writes_colours_while_slots_link(self):
        self.link_slots("painter_t1_lvl1")
        panel = self.make()
        panel.select_sheet(self.sheet_id)
        panel._frame_w.setValue(64)                # locked: must not land
        panel._colours.setText("Pink, Red")        # free: must land
        self.assertEqual(panel.save_selected(), self.sheet_id)
        entry = self.registry()["entries"][self.sheet_id]
        self.assertEqual(entry["frame_w"], 32)
        self.assertEqual(entry["columns"], ["pink", "red"])

    def test_column_width_edit_in_use_restamps_linking_entries_and_signals(self):
        """The registry write alone is a NO-OP for a linked slot: `store`
        slices from the manifest's own copy and never opens the registry."""
        self.link_slots("painter_t1_lvl1", "mortar_t1_lvl1")
        panel = self.make()
        panel.select_sheet(self.sheet_id)
        seen = []
        panel.manifest_changed.connect(seen.append)

        panel._column_width.setValue(4)
        self.assertEqual(panel.save_selected(), self.sheet_id)

        self.assertEqual(self.registry()["entries"][self.sheet_id]
                         ["column_width"], 4)
        entries = data_io.load_json(
            self.data_dir / "sprites" / "asset_manifest.json")["entries"]
        self.assertEqual(entries["painter_t1_lvl1"]["column_width"], 4)
        self.assertEqual(entries["mortar_t1_lvl1"]["column_width"], 4)
        self.assertEqual(seen, [""])   # ED-42 reload fires exactly once

    def test_column_width_save_that_changes_nothing_emits_nothing(self):
        self.link_slots("painter_t1_lvl1")
        panel = self.make()
        panel.select_sheet(self.sheet_id)
        seen = []
        panel.manifest_changed.connect(seen.append)
        self.assertEqual(panel.save_selected(), self.sheet_id)   # width stays 2
        self.assertEqual(seen, [])

    # -- writes --------------------------------------------------------------

    def test_save_selected_writes_the_registry(self):
        panel = self.make()
        panel.select_sheet(self.sheet_id)
        panel._column_width.setValue(4)
        panel._colours.setText("Green, Gold")
        self.assertEqual(panel.save_selected(), self.sheet_id)
        # write_registry_doc goes through write_validated, so a re-load that
        # carries the new values is the validity assertion.
        entry = self.registry()["entries"][self.sheet_id]
        self.assertEqual(entry["column_width"], 4)
        self.assertEqual(entry["columns"], ["green", "gold"])
        self.assertEqual(panel.selected_sheet().column_width, 4)

    def test_reimport_with_DIFFERENT_bytes_keeps_the_id_and_the_links(self):
        """The whole point of `import_master_sheet(sheet_id=...)`: identical
        bytes would pass through `resolve_sheet_id` too and prove nothing —
        genuinely different art is what used to mint `village_folk_2` and
        strand every linking slot on the stale sheet."""
        self.link_slots("painter_t1_lvl1")
        replacement = make_png(self.data_dir / "incoming" / "new.png",
                               128, 192, colour=(200, 10, 10, 255))
        png = self.data_dir / "sprites" / "master" / f"{self.sheet_id}.png"
        self.assertNotEqual(png.read_bytes(), replacement.read_bytes())

        panel = self.make()
        panel.select_sheet(self.sheet_id)
        self.assertEqual(panel.reimport_selected(replacement), self.sheet_id)

        self.assertEqual(png.read_bytes(), replacement.read_bytes())
        self.assertEqual(sorted(self.registry()["entries"]),
                         sorted([self.sheet_id, self.other_id]))  # no `_2`
        self.assertEqual(panel.selected_sheet().users, ("painter_t1_lvl1",))

    def test_reimport_at_a_changed_grid_while_in_use_is_refused(self):
        self.link_slots("painter_t1_lvl1")
        replacement = make_png(self.data_dir / "incoming" / "new.png",
                               128, 192, colour=(200, 10, 10, 255))
        png = self.data_dir / "sprites" / "master" / f"{self.sheet_id}.png"
        before = png.read_bytes()

        panel = self.make()
        panel.select_sheet(self.sheet_id)
        with self.assertRaises(master_sheet_import.GridInUseError) as caught:
            panel.reimport_selected(replacement, frame_w=64)
        self.assertIn("painter_t1_lvl1", str(caught.exception))
        self.assertEqual(png.read_bytes(), before)   # refused before the copy

    # -- routing -------------------------------------------------------------

    def test_selecting_the_item_routes_the_right_stack_to_the_panel(self):
        window = self.track(MainWindow(data_dir=self.data_dir))
        window.selector.select_master_sheets()
        self.assertIs(window.right_stack.currentWidget(), window.master_sheets)
        self.assertEqual([s.sheet_id for s in window.master_sheets.sheets()],
                         ["alpha_crowd", "village_folk"])


if __name__ == "__main__":
    unittest.main()
