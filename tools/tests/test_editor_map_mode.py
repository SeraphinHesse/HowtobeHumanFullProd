"""Phase 6 acceptance tests: the tilemap editor (ED-10/ED-20/ED-23/ED-24,
D-21/D-22) — Maps tree branch + active ●, mode switching, QTest
click-to-paint through screen_to_world (E-3), per-stroke undo coalescing,
base drag, deco place/remove, layer eyes + grid lines through the one
render path, save / set-active through the validating writer.

Same headless conventions as the other editor tests: QT_QPA_PLATFORM=
offscreen + SDL dummy drivers before any Qt/pygame import, one
QApplication per process, tempfile COPY of data/ so nothing touches the
repo's files.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from editor.main import MainWindow
from engine import data_io, tilemap
from engine.render import DrawCall, OverlayLines
from editor.panels import palette as palette_module

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)

STARTER = "first_light"


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls = list(draw_calls)


class MapModeCase(unittest.TestCase):
    """MainWindow against a temp data/ copy, starter map selected."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        self.window = MainWindow(data_dir=self.data_dir)
        self.addCleanup(self.window.close)
        self.window.resize(1280, 720)
        self.window.show()
        self.viewport = self.window.viewport
        self.session = self.window.map_session

    def open_map(self, map_id=STARTER):
        self.window.selector.select_map(map_id)
        return self.session.doc

    def cell_pos(self, col, row):
        """Widget point at a cell's diamond centre, via coords only (E-3)."""
        px, py = self.viewport._coords.world_to_screen(col + 0.5, row + 0.5)
        return QPoint(round(px), round(py))

    def click_cell(self, col, row, button=Qt.MouseButton.LeftButton):
        QTest.mouseClick(self.viewport, button, pos=self.cell_pos(col, row))

    def drag_cells(self, cells, button=Qt.MouseButton.LeftButton):
        QTest.mousePress(self.viewport, button, pos=self.cell_pos(*cells[0]))
        for cell in cells[1:]:
            QTest.mouseMove(self.viewport, self.cell_pos(*cell))
        QTest.mouseRelease(self.viewport, button, pos=self.cell_pos(*cells[-1]))


class TestMapsBranch(MapModeCase):
    def test_maps_branch_lists_files_with_active_marker(self):
        selector = self.window.selector
        self.assertIn(STARTER, selector.map_ids())
        selector.select_map(STARTER)
        item = selector.selectedItems()[0]
        self.assertTrue(item.text(0).startswith("● "))   # committed active map

    def test_mode_switches_with_selection(self):
        self.assertFalse(self.viewport.in_map_mode())
        self.open_map()
        self.assertTrue(self.viewport.in_map_mode())
        self.assertTrue(self.window.palette.isVisibleTo(self.window))
        self.assertIs(self.window.right_stack.currentWidget(),
                      self.window.map_details)
        # back to an entity node → entity preview untouched by Phase 6
        self.window.selector.select_node("buildings", ("Defender",))
        self.assertFalse(self.viewport.in_map_mode())
        self.assertFalse(self.window.palette.isVisibleTo(self.window))
        self.assertIs(self.window.right_stack.currentWidget(),
                      self.window.details)
        self.assertIsNotNone(self.viewport.preview_slot)

    def test_map_selection_drives_map_balancing_domain(self):
        self.open_map()
        self.assertEqual(self.window.balancing.domain, "map")

    def test_coords_take_map_dims(self):
        doc = self.open_map()
        g = self.viewport._coords.geometry
        self.assertEqual((g.map_cols, g.map_rows), (doc.cols, doc.rows))


class TestPaintTools(MapModeCase):
    def test_click_paints_armed_code_on_the_right_cell(self):
        doc = self.open_map()
        self.window.palette.arm_code("c")
        self.window.palette.set_tool("paint")
        target = (15, 15)   # forest in the starter map, away from the base
        self.assertEqual(doc.terrain[15][15], "f")
        self.click_cell(*target)
        self.assertEqual(doc.terrain[15][15], "c")
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_stroke_coalesces_to_one_undo_command(self):
        doc = self.open_map()
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("paint")
        cells = [(14, 15), (15, 15), (16, 15), (17, 15)]
        self.drag_cells(cells)
        for col, row in cells:
            self.assertEqual(doc.terrain[row][col], "b")
        self.assertEqual(self.session.undo_stack.count(), 1)   # ED-24
        self.session.undo_stack.undo()
        for col, row in cells:
            self.assertEqual(doc.terrain[row][col], "f")
        self.session.undo_stack.redo()
        self.assertEqual(doc.terrain[15][14], "b")

    def test_rect_fill_via_drag(self):
        doc = self.open_map()
        self.window.palette.arm_code("s")
        self.window.palette.set_tool("rect")
        self.drag_cells([(15, 15), (17, 17)])
        for row in (15, 16, 17):
            self.assertEqual(doc.terrain[row][15:18], ["s"] * 3)
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_bucket_fill_via_click(self):
        doc = self.open_map()
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("bucket")
        self.click_cell(16, 16)   # inside the big forest region
        self.assertEqual(doc.terrain[16][16], "b")
        self.assertEqual(doc.terrain[19][19], "b")   # same region
        self.assertEqual(doc.terrain[1][1], "b")     # other zone untouched...
        self.assertEqual(doc.terrain[5][5], "c")     # ...combat stays combat
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_erase_paints_default_background(self):
        doc = self.open_map()
        self.window.palette.set_tool("erase")
        self.assertEqual(doc.terrain[5][5], "c")
        self.click_cell(5, 5)
        self.assertEqual(doc.terrain[5][5], "f")

    def test_picker_rearms_palette_and_viewport(self):
        self.open_map()
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("picker")
        self.click_cell(11, 11)   # spawning zone in the starter map
        self.assertEqual(self.window.palette.armed_code(), "s")
        self.assertEqual(self.viewport._armed_code, "s")


class TestBaseAndDeco(MapModeCase):
    def test_base_drag_is_one_undoable_move(self):
        doc = self.open_map()
        self.assertEqual((doc.base["col"], doc.base["row"]), (1, 1))
        self.drag_cells([(1, 1), (4, 4)])
        self.assertEqual((doc.base["col"], doc.base["row"]), (4, 4))
        self.assertEqual(self.session.undo_stack.count(), 1)
        self.session.undo_stack.undo()
        self.assertEqual((doc.base["col"], doc.base["row"]), (1, 1))

    def test_base_eye_off_paints_under_base(self):
        doc = self.open_map()
        self.window.palette.arm_code("c")
        self.window.palette.set_tool("paint")
        self.window.palette._eye_boxes["base"].setChecked(False)
        self.click_cell(1, 1)
        self.assertEqual(doc.terrain[1][1], "c")
        self.assertEqual((doc.base["col"], doc.base["row"]), (1, 1))

    def test_deco_place_and_erase_undoable(self):
        doc = self.open_map()
        before = len(doc.deco)
        self.window.palette.arm_deco("deco_tree")
        self.window.palette.set_tool("paint")
        self.click_cell(15, 15)
        self.assertEqual(len(doc.deco), before + 1)
        self.assertEqual(doc.deco[-1],
                         {"col": 15, "row": 15, "slot": "deco_tree"})
        self.window.palette.set_tool("erase")
        self.click_cell(15, 15)
        self.assertEqual(len(doc.deco), before)
        self.assertEqual(self.session.undo_stack.count(), 2)
        self.session.undo_stack.undo()   # un-remove
        self.assertEqual(len(doc.deco), before + 1)
        self.session.undo_stack.undo()   # un-place
        self.assertEqual(len(doc.deco), before)


class TestRenderPath(MapModeCase):
    """ED-22: eyes/tints/grid observed at the engine backend, not via Qt."""

    def record_frame(self):
        from engine.render import Renderer

        backend = RecordingBackend()
        self.viewport._renderer = Renderer(
            self.viewport._coords, self.viewport._assets, backend=backend)
        self.viewport.render_frame()
        return backend.calls

    def test_layer_eyes_filter_submitted_items(self):
        doc = self.open_map()
        full = len([c for c in self.record_frame() if isinstance(c, DrawCall)])
        self.assertEqual(full, doc.cols * doc.rows + 1 + len(doc.deco))
        self.viewport.set_eye("terrain", False)
        no_terrain = len([c for c in self.record_frame()
                          if isinstance(c, DrawCall)])
        self.assertEqual(no_terrain, 1 + len(doc.deco))
        self.viewport.set_eye("base", False)
        self.viewport.set_eye("deco", False)
        self.assertEqual(len([c for c in self.record_frame()
                              if isinstance(c, DrawCall)]), 0)

    def test_zone_tint_eye_tints_zone_tiles_only(self):
        self.open_map()
        calls = [c for c in self.record_frame() if isinstance(c, DrawCall)]
        self.assertTrue(any(c.tint is not None for c in calls))
        self.viewport.set_eye("tint", False)
        calls = [c for c in self.record_frame() if isinstance(c, DrawCall)]
        self.assertTrue(all(c.tint is None for c in calls))

    def test_grid_lines_through_overlay_primitive(self):
        doc = self.open_map()
        self.assertFalse(any(isinstance(c, OverlayLines)
                             for c in self.record_frame()))
        self.viewport.set_grid_lines(True)
        lines = [c for c in self.record_frame() if isinstance(c, OverlayLines)]
        self.assertEqual(len(lines), (doc.rows + 1) + (doc.cols + 1))


class TestLifecycle(MapModeCase):
    def test_save_round_trips_to_disk(self):
        doc = self.open_map()
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("paint")
        self.click_cell(15, 15)
        self.assertTrue(self.session.dirty)
        self.session.save()
        self.assertFalse(self.session.dirty)
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded, doc)
        self.assertEqual(loaded.terrain[15][15], "b")

    def test_set_active_writes_d21_and_marks_tree(self):
        self.open_map()
        self.session.create("second", "Second", 8, 8)
        self.session.set_active()
        pointer = data_io.load_validated(
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))
        self.assertEqual(pointer["active"], "second")
        selector = self.window.selector
        selector.select_map("second")
        self.assertTrue(selector.selectedItems()[0].text(0).startswith("● "))
        selector.select_map(STARTER)
        self.assertFalse(selector.selectedItems()[0].text(0).startswith("● "))

    def test_create_and_duplicate_update_tree_and_disk(self):
        self.open_map()
        self.session.create("fresh", "Fresh", 6, 6)
        self.assertIn("fresh", self.window.selector.map_ids())
        self.assertTrue(tilemap.map_path(self.data_dir, "fresh").exists())
        self.assertTrue(self.viewport.in_map_mode())
        self.assertEqual(self.session.doc.map_id, "fresh")
        self.session.duplicate("fresh_copy", "Fresh Copy")
        self.assertIn("fresh_copy", self.window.selector.map_ids())
        self.assertEqual(self.session.doc.map_id, "fresh_copy")
        self.assertEqual(self.session.doc.terrain,
                         tilemap.load_map(
                             tilemap.map_path(self.data_dir, "fresh"),
                             tilemap.map_schema_path(self.data_dir)).terrain)

    def test_rename_is_undoable(self):
        doc = self.open_map()
        old = doc.display_name
        self.session.push_rename("Renamed Map")
        self.assertEqual(doc.display_name, "Renamed Map")
        self.session.undo_stack.undo()
        self.assertEqual(doc.display_name, old)

    def test_dirty_policy_discard_allows_switching(self):
        doc = self.open_map()
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("paint")
        self.click_cell(15, 15)
        self.window.dirty_policy = "discard"
        self.session.create("other", "Other", 6, 6)   # prompts resolved by policy
        self.window.selector.select_map(STARTER)      # reopens from disk
        self.assertEqual(self.session.doc.map_id, STARTER)
        self.assertEqual(self.session.doc.terrain[15][15], "f")   # discarded


class TestNoneTool(MapModeCase):
    """Phase 6 follow-up: "None" is the default tool and never paints, so
    the map can be inspected/panned and the base grabbed without a stray
    brush stroke landing first."""

    def test_none_is_the_default_tool(self):
        self.open_map()
        self.assertEqual(self.window.palette.current_tool(), "none")
        self.assertEqual(self.viewport._tool, "none")

    def test_click_with_none_tool_does_not_paint(self):
        doc = self.open_map()
        self.window.palette.arm_code("c")
        before = doc.terrain[15][15]
        self.click_cell(15, 15)
        self.assertEqual(doc.terrain[15][15], before)
        self.assertEqual(self.session.undo_stack.count(), 0)

    def test_deco_armed_with_none_tool_does_not_place(self):
        doc = self.open_map()
        before = len(doc.deco)
        self.window.palette.arm_deco("deco_tree")
        self.click_cell(15, 15)
        self.assertEqual(len(doc.deco), before)

    def test_base_drag_still_works_with_none_tool(self):
        doc = self.open_map()
        self.assertEqual(self.viewport._tool, "none")
        self.drag_cells([(1, 1), (5, 5)])
        self.assertEqual((doc.base["col"], doc.base["row"]), (5, 5))
        self.assertEqual(self.session.undo_stack.count(), 1)

    def test_no_ghost_items_with_none_tool_armed(self):
        self.open_map()
        self.window.palette.arm_code("c")
        self.viewport._hover_cell = (5, 5)
        self.assertEqual(list(self.viewport._ghost_items(self.session.doc)), [])


class TestPaletteImport(MapModeCase):
    """Phase 6 follow-up: the map palette's "Import Spritesheet…" targets
    whichever brush is currently armed — the only import path reachable
    while the map palette has replaced the Details panel."""

    def make_png(self, w=64, h=32, colour=(10, 200, 10, 255)):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "art.png"
        Image.new("RGBA", (w, h), colour).save(path)
        return path

    def test_import_with_no_brush_armed_warns_and_does_nothing(self):
        # No map opened yet -> no tile code buttons exist and no deco is
        # armed, so nothing should be armed to import into. Patch the
        # message box too — it's modal and would hang a headless test.
        with patch.object(QFileDialog, "getOpenFileName") as dlg, \
                patch.object(palette_module.QMessageBox, "information") as info:
            self.window.palette._on_import_clicked()
            dlg.assert_not_called()
            info.assert_called_once()

    def test_import_targets_armed_deco_slot(self):
        self.open_map()
        self.window.palette.arm_deco("deco_rock")
        png = self.make_png(64, 96)
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=(str(png), "")):
            events = []
            self.window.palette.manifest_changed.connect(events.append)
            self.window.palette._on_import_clicked()
        self.assertEqual(events, ["deco_rock"])
        entry = data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json",
        )["entries"]["deco_rock"]
        self.assertEqual(entry["rows"][0]["animation"], "idle")
        self.assertTrue(
            (self.data_dir / "sprites" / "imported" / "deco_rock.png").exists())

    def test_import_targets_armed_tile_code(self):
        self.open_map()
        self.window.palette.arm_code("b")
        png = self.make_png(64, 32)
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=(str(png), "")):
            self.window.palette._on_import_clicked()
        entries = data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json",
        )["entries"]
        self.assertIn("tile_buildable", entries)

    def test_import_via_details_panel_refreshes_palette_icon(self):
        # Fix 1 regression: importing through the normal Details panel
        # while a DIFFERENT tree node is selected must still update the
        # map palette's brush icon, not just the viewport/selector.
        self.open_map()
        self.window.selector.select_node("deco", ("Props",))
        self.window.details.set_slot("deco_bush")
        png = self.make_png(64, 96)
        self.window.details.import_sheet(png)
        with patch.object(self.window.palette, "refresh_icons") as spy:
            self.window.details.save()
        spy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
