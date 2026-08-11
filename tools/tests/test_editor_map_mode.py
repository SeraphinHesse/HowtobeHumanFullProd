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
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog

from editor.main import MainWindow
from engine import data_io, tilemap
from engine.render import DrawCall, OverlayLines
from editor.panels import palette as palette_module

REPO = Path(__file__).resolve().parents[2]

STARTER = "first_light"


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls = list(draw_calls)


class MapModeCase(QtCase):
    """MainWindow against a temp data/ copy, starter map selected.

    The temp copy's ACTIVE map is pinned to STARTER before the window is
    built. It used to be inherited from the repo, i.e. from whichever map a
    designer last hit "set active" on — which is live data, not a fixture.
    When that became `summertest2`,
    test_maps_branch_lists_files_with_active_marker went red for a reason that
    had nothing to do with the editor."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        self.set_active_map(STARTER)
        self.window = self.track(MainWindow(data_dir=self.data_dir))
        self.window.resize(1280, 720)
        self.window.show()
        self.viewport = self.window.viewport
        self.session = self.window.map_session

    def set_active_map(self, map_id):
        """Pin the temp copy's active map. Goes through the same validating
        writer the editor uses, so the fixture can't drift from the format."""
        data_io.write_validated(
            {"active": map_id},
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))

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
        # ESV-2: index 0 is now a small container holding details + anchors
        self.assertIs(self.window.right_stack.currentWidget(),
                      self.window.details_pane)
        self.assertIsNotNone(self.viewport.preview_slot)

    def test_map_selection_drives_map_balancing_domain(self):
        self.open_map()
        self.assertEqual(self.window.balancing.domain, "map")

    def test_coords_take_map_dims(self):
        doc = self.open_map()
        g = self.viewport._coords.geometry
        self.assertEqual((g.map_cols, g.map_rows), (doc.cols, doc.rows))

    def test_camera_opens_centred_on_camera_start(self):
        doc = self.open_map()   # first_light: camera_start at (6, 6), off-centre
        w, h = self.viewport.width(), self.viewport.height()
        coords = self.viewport._coords
        # Reference: an identical coord system, but pan reset then centred
        # via the coords API directly (mirrors _center_on_camera_start).
        expected_pan_x, expected_pan_y = coords.camera.pan_x, coords.camera.pan_y
        coords.camera.pan_x = coords.camera.pan_y = 0.0
        coords.center_on(doc.camera_start["col"], doc.camera_start["row"], w, h)
        self.assertAlmostEqual(coords.camera.pan_x, expected_pan_x, delta=1)
        self.assertAlmostEqual(coords.camera.pan_y, expected_pan_y, delta=1)

    def test_camera_falls_back_to_clamp_without_camera_start(self):
        self.session.create("nocam", "No Camera", 8, 8)
        doc = self.session.doc
        self.assertIsNone(doc.camera_start)   # new_doc starts with no startpoint
        w, h = self.viewport.width(), self.viewport.height()
        coords = self.viewport._coords
        expected_pan_x, expected_pan_y = coords.camera.pan_x, coords.camera.pan_y
        coords.clamp(w, h)   # already clamped by set_map_mode; idempotent
        self.assertAlmostEqual(coords.camera.pan_x, expected_pan_x, delta=1)
        self.assertAlmostEqual(coords.camera.pan_y, expected_pan_y, delta=1)


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


class TestStartArea(MapModeCase):
    """The 2×2 starting-area marker: brush place/erase (undoable), 4-cell drag
    grab, edge clamping, and disk round-trip. Outline rendering is covered in
    TestRenderPath (backend-observed, ED-22)."""

    def arm_start_area(self):
        self.window.palette.arm_start_area("start_area")
        self.window.palette.set_tool("paint")

    def test_click_places_min_corner_and_is_undoable(self):
        doc = self.open_map()
        self.assertIsNone(doc.start_area)
        self.arm_start_area()
        self.click_cell(5, 6)
        self.assertEqual(doc.start_area,
                         {"col": 5, "row": 6, "slot": "start_area"})
        self.assertEqual(self.session.undo_stack.count(), 1)
        self.session.undo_stack.undo()
        self.assertIsNone(doc.start_area)
        self.session.undo_stack.redo()
        self.assertEqual(doc.start_area["col"], 5)

    def test_erase_removes(self):
        doc = self.open_map()
        self.arm_start_area()
        self.click_cell(5, 6)
        self.window.palette.set_tool("erase")
        self.click_cell(10, 10)   # erase targets the single object, any cell
        self.assertIsNone(doc.start_area)
        self.session.undo_stack.undo()
        self.assertEqual(doc.start_area["col"], 5)

    def test_edge_click_clamps_to_fit(self):
        doc = self.open_map()
        self.arm_start_area()
        self.click_cell(doc.cols - 1, doc.rows - 1)
        self.assertEqual((doc.start_area["col"], doc.start_area["row"]),
                         (doc.cols - 2, doc.rows - 2))

    def test_any_covered_cell_drags_the_area(self):
        doc = self.open_map()
        self.arm_start_area()
        self.click_cell(5, 6)
        # disarm the marker brush (an armed single-object brush intercepts the
        # press) — dragging works with any tile brush + the "none" tool, like
        # the base
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("none")
        # grab by the BOTTOM-RIGHT covered cell (6,7), drop at (10,10) — the
        # release cell becomes the new min corner; ONE more undo command
        self.drag_cells([(6, 7), (10, 10)])
        self.assertEqual((doc.start_area["col"], doc.start_area["row"]),
                         (10, 10))
        self.assertEqual(self.session.undo_stack.count(), 2)
        self.session.undo_stack.undo()
        self.assertEqual((doc.start_area["col"], doc.start_area["row"]), (5, 6))

    def test_save_round_trips_to_disk(self):
        doc = self.open_map()
        self.arm_start_area()
        self.click_cell(2, 2)
        self.session.save()
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded.start_area,
                         {"col": 2, "row": 2, "slot": "start_area"})


class TestSpawnReserve(MapModeCase):
    """The spawnable-background brush: ONE undo command per stroke, and undo
    restores exactly the marks that were there before."""

    def test_reserve_stroke_undo_restores_previous_marks(self):
        doc = self.open_map()
        doc.spawnable_background[(14, 15)] = 7   # a pre-existing mark
        before = dict(doc.spawnable_background)
        self.window.palette.set_mode("spawn_reserve")
        self.window.palette.set_reserve_number(3)
        self.window.palette.set_tool("paint")
        cells = [(14, 15), (15, 15), (16, 15)]
        self.drag_cells(cells)
        for cell in cells:
            self.assertEqual(doc.spawnable_background[cell], 3)
        self.assertEqual(self.session.undo_stack.count(), 1)   # ED-24
        self.session.undo_stack.undo()
        self.assertEqual(doc.spawnable_background, before)


class TestDespawnableSpawn(MapModeCase):
    """The despawnable-spawn brush: ONE undo command per stroke, and undo
    restores exactly the marks that were there before."""

    def test_despawn_stroke_undo_restores_previous_marks(self):
        doc = self.open_map()
        doc.despawnable_spawn[(14, 15)] = 7   # a pre-existing mark
        before = dict(doc.despawnable_spawn)
        self.window.palette.set_mode("despawnable_spawn")
        self.window.palette.set_despawn_number(3)
        self.window.palette.set_tool("paint")
        cells = [(14, 15), (15, 15), (16, 15)]
        self.drag_cells(cells)
        for cell in cells:
            self.assertEqual(doc.despawnable_spawn[cell], 3)
        self.assertEqual(self.session.undo_stack.count(), 1)   # ED-24
        self.session.undo_stack.undo()
        self.assertEqual(doc.despawnable_spawn, before)


class TestStageZones(MapModeCase):
    """The stage-zone brush: ONE undo command per stroke, and undo restores
    exactly the marks that were there before."""

    def test_stage_stroke_undo_restores_previous_marks(self):
        doc = self.open_map()
        doc.stage_zones[(14, 15)] = 7   # a pre-existing mark
        before = dict(doc.stage_zones)
        self.window.palette.set_mode("stage_zones")
        self.window.palette.set_stage_number(3)
        self.window.palette.set_tool("paint")
        cells = [(14, 15), (15, 15), (16, 15)]
        self.drag_cells(cells)
        for cell in cells:
            self.assertEqual(doc.stage_zones[cell], 3)
        self.assertEqual(self.session.undo_stack.count(), 1)   # ED-24
        self.session.undo_stack.undo()
        self.assertEqual(doc.stage_zones, before)


class TestTileConditions(MapModeCase):
    """The tile-condition brush: ONE undo command per stroke, undo restores
    exactly the marks that were there before, redo puts the stroke back. The
    brush value is a condition NAME (from the schema enum), not a number."""

    def test_condition_stroke_undo_redo(self):
        doc = self.open_map()
        doc.tile_conditions[(14, 15)] = "pond"   # a pre-existing mark
        before = dict(doc.tile_conditions)
        palette = self.window.palette
        palette.set_mode("tile_conditions")
        name = palette._condition_names()[1]     # schema order, not a literal
        palette.arm_tile_condition(name)
        palette.set_tool("paint")
        cells = [(14, 15), (15, 15), (16, 15)]
        self.drag_cells(cells)
        for cell in cells:
            self.assertEqual(doc.tile_conditions[cell], name)
        self.assertEqual(self.session.undo_stack.count(), 1)   # ED-24
        self.session.undo_stack.undo()
        self.assertEqual(doc.tile_conditions, before)
        self.session.undo_stack.redo()
        for cell in cells:
            self.assertEqual(doc.tile_conditions[cell], name)


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
        # Windowed culling means only the on-screen tile range is submitted, so
        # the assertion is on the eyes' filtering effect, not a full-map count.
        #
        # "Every layer off" is derived from the eye REGISTRY, not a hand-written
        # list. It used to name terrain/base/deco literally; the viewport then
        # grew `camera` and `start_area` eyes, the list was never updated, and
        # the test failed claiming "every layer off" while two layers were still
        # on. Enumerating the registry means a seventh layer cannot make this
        # test lie again.
        self.open_map()

        def sprite_count():
            return len([c for c in self.record_frame() if isinstance(c, DrawCall)])

        full = sprite_count()
        self.assertGreater(full, 0)             # some tiles are on screen
        self.viewport.set_eye("terrain", False)
        self.assertLess(sprite_count(), full)   # terrain eye dropped ground tiles

        for name in list(self.viewport._eyes):
            self.viewport.set_eye(name, False)
        self.assertEqual(sprite_count(), 0)     # every layer off → nothing drawn

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
        # grid goes through the E-24 overlay primitive; bounded to the visible
        # window (never more than the full-map line count).
        self.assertGreater(len(lines), 0)
        self.assertLessEqual(len(lines), (doc.rows + 1) + (doc.cols + 1))

    def test_start_area_outline_through_overlay_primitive(self):
        # The placed 2×2 marker draws as ONE closed overlay polygon (never a
        # sprite), gated by its eye — ED-22-clean, same primitive as the grid.
        doc = self.open_map()
        doc.start_area = {"col": 3, "row": 3, "slot": "start_area"}
        lines = [c for c in self.record_frame() if isinstance(c, OverlayLines)]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].closed)
        self.assertEqual(len(lines[0].points), 4)
        # the backend receives SCREEN-space points; corner 0 is the world
        # min corner (3,3) converted through the one coords authority
        sx, sy = self.viewport._coords.world_to_screen(3, 3)
        self.assertAlmostEqual(lines[0].points[0][0], sx, delta=1)
        self.assertAlmostEqual(lines[0].points[0][1], sy, delta=1)
        self.viewport.set_eye("start_area", False)
        self.assertFalse(any(isinstance(c, OverlayLines)
                             for c in self.record_frame()))


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

    def test_delete_removes_file_and_tree_entry(self):
        self.open_map()
        self.session.create("throwaway", "Throwaway", 6, 6)
        self.assertTrue(tilemap.map_path(self.data_dir, "throwaway").exists())
        self.window.map_details._on_delete(confirm=False)
        self.assertFalse(tilemap.map_path(self.data_dir, "throwaway").exists())
        self.assertNotIn("throwaway", self.window.selector.map_ids())
        self.assertFalse(self.viewport.in_map_mode())
        self.assertIsNone(self.session.doc)

    def test_delete_button_disabled_for_active_map(self):
        active_id = self.session.active_map_id()
        self.open_map(active_id)
        self.assertFalse(self.window.map_details.delete_button.isEnabled())

    def test_delete_button_enabled_for_non_active_map(self):
        self.open_map()
        self.session.create("throwaway", "Throwaway", 6, 6)
        self.assertTrue(self.window.map_details.delete_button.isEnabled())

    def test_session_delete_refuses_active_map(self):
        self.open_map()
        self.session.create("actmap", "Active Map", 6, 6)
        self.session.set_active()
        self.open_map(STARTER)   # re-open a different map so actmap isn't
                                 # also caught by the "currently open" guard
        with self.assertRaises(ValueError):
            self.session.delete("actmap")

    def test_session_delete_refuses_currently_open_map(self):
        self.open_map()
        self.session.create("throwaway", "Throwaway", 6, 6)
        with self.assertRaises(ValueError):
            self.session.delete("throwaway")   # still the open doc

    def test_delete_does_not_touch_active_map_pointer(self):
        self.open_map()
        self.session.create("throwaway", "Throwaway", 6, 6)
        before = data_io.load_validated(
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))
        self.window.map_details._on_delete(confirm=False)
        after = data_io.load_validated(
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))
        self.assertEqual(before, after)

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

    def test_deco_place_with_mirror_flip_armed(self):
        doc = self.open_map()
        self.window.palette.arm_deco("deco_tree")
        self.window.palette.set_tool("paint")
        self.window.palette._deco_flip_box.setChecked(True)
        self.click_cell(15, 15)
        self.assertEqual(doc.deco[-1],
                         {"col": 15, "row": 15, "slot": "deco_tree",
                          "flip": True})

        self.window.palette._deco_flip_box.setChecked(False)
        self.click_cell(16, 15)
        self.assertEqual(doc.deco[-1],
                         {"col": 16, "row": 15, "slot": "deco_tree"})

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

    def test_import_targets_armed_base_slot(self):
        self.open_map()
        self.window.palette.arm_base("base_hole")
        png = self.make_png(64, 96)
        with patch.object(QFileDialog, "getOpenFileName",
                          return_value=(str(png), "")):
            events = []
            self.window.palette.manifest_changed.connect(events.append)
            self.window.palette._on_import_clicked()
        self.assertEqual(events, ["base_hole"])
        entry = data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json",
        )["entries"]["base_hole"]
        self.assertEqual(entry["rows"][0]["animation"], "idle")
        self.assertTrue(
            (self.data_dir / "sprites" / "imported" / "base_hole.png").exists())

    def test_arming_base_does_not_affect_paint_tool_dispatch(self):
        # Arming the base is import-target-only: it must not become a
        # paintable brush (the base is moved by dragging, never painted).
        doc = self.open_map()
        self.window.palette.arm_base("base_hole")
        self.window.palette.set_tool("paint")
        before = doc.terrain[15][15]
        self.click_cell(15, 15)
        self.assertEqual(doc.terrain[15][15], before)

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


class TestBackgroundBrushes(MapModeCase):
    """Every registry Background variant is a brush, even with no legend
    code in the open map (bug: the palette used to enumerate only the
    open map's legend, hiding un-bound registry variants). first_light's
    legend only binds forest/ocean/cliff — the registry's
    tile_background_1..9 slots are ALREADY unbound in it, no fixture
    mutation needed. Clicking an un-bound variant BINDS a legend code
    (undoable), reusing '+ Level's machinery."""

    UNBOUND_SLOT = "tile_background_1"

    def test_all_registry_background_slots_are_brushes(self):
        self.open_map()
        self.window.palette.set_mode("background")
        registry = self.window.selector.registry
        expected = len(registry.group_slots("map", ("Tiles", "Background")))
        background_keys = [k for k in self.window.palette._brush_buttons
                            if k[0] == "bgslot"
                            or (k[0] == "code"
                                and not self.session.doc.legend[k[1]]["checker"])]
        self.assertEqual(len(background_keys), expected)
        # the unbound slot shows up as a "bgslot" brush
        self.assertIn(("bgslot", self.UNBOUND_SLOT),
                       self.window.palette._brush_buttons)

    def test_arming_unbound_slot_binds_a_new_legend_code(self):
        self.open_map()
        self.window.palette.set_mode("background")
        before_codes = set(self.session.doc.legend.keys())
        self.assertTrue(self.session.undo_stack.isClean())

        self.window.palette.arm_background_slot(self.UNBOUND_SLOT)

        after_codes = set(self.session.doc.legend.keys())
        self.assertEqual(len(after_codes), len(before_codes) + 1)
        new_code = next(iter(after_codes - before_codes))
        self.assertEqual(
            self.session.doc.legend[new_code]["slot"], self.UNBOUND_SLOT)
        self.assertFalse(self.session.undo_stack.isClean())
        self.assertEqual(self.window.palette.armed_code(), new_code)

        self.session.undo_stack.undo()
        self.assertEqual(set(self.session.doc.legend.keys()), before_codes)

    def test_arming_bound_slot_adds_no_new_code(self):
        self.open_map()
        self.window.palette.set_mode("background")
        before_codes = set(self.session.doc.legend.keys())

        self.window.palette.arm_code("f")   # tile_forest, already bound

        self.assertEqual(set(self.session.doc.legend.keys()), before_codes)
        self.assertEqual(self.window.palette.armed_code(), "f")

    def test_palette_content_is_scrollable(self):
        from PySide6.QtWidgets import QScrollArea
        self.assertIsNotNone(self.window.palette.findChild(QScrollArea))

    def test_two_codes_bound_to_same_slot_both_get_brushes(self):
        """Regression: a legend with TWO non-checker codes bound to the SAME
        background slot must produce a brush for EACH code — the old
        slot-keyed dict silently dropped all but one. Legacy/hand-edited map
        data can hit this; the palette must never drop a bound code."""
        self.open_map()
        legend = self.session.doc.legend
        # 'f' already binds tile_forest — add a second code to the same slot.
        legend["f2"] = {"checker": False, "slot": legend["f"]["slot"]}
        self.window.palette.set_legend(legend)
        self.window.palette.set_mode("background")

        self.assertIn(("code", "f"), self.window.palette._brush_buttons)
        self.assertIn(("code", "f2"), self.window.palette._brush_buttons)


class TestKeybindShortcuts(MapModeCase):
    """ED settings panel: window-level QActions drive tool switching and
    Game-tiles brush arming; number-key brushes are positional
    (_gametiles_brush_order()) and Game-tiles-mode-only."""

    def test_default_tool_shortcuts_match_spec(self):
        expected = {"none": "P", "paint": "B", "erase": "N", "line": "L",
                    "rect": "M", "bucket": "G", "picker": "I"}
        for name, key in expected.items():
            self.assertEqual(
                self.window._tool_actions[name].shortcut().toString(), key)

    def test_default_brush_shortcuts_are_1_through_5(self):
        for i in range(5):
            self.assertEqual(
                self.window._brush_actions[i].shortcut().toString(), str(i + 1))

    def test_tool_action_switches_tool(self):
        self.open_map()
        self.window._tool_actions["bucket"].trigger()
        self.assertEqual(self.window.palette.current_tool(), "bucket")

    def test_brush_action_arms_the_right_brush_in_gametiles_mode(self):
        """first_light's zone codes sort to b(uildable)/c(ombat)/s(pawning)
        — brush indices 0/1/2 (keys 1/2/3)."""
        self.open_map()
        self.window.palette.set_mode("gametiles")
        self.window._brush_actions[1].trigger()   # key "2" -> Combat
        self.assertEqual(self.window.palette.armed_code(), "c")

    def test_brush_action_is_a_no_op_outside_gametiles_mode(self):
        self.open_map()
        self.window.palette.set_mode("background")
        before = self.window.palette.armed_code()
        self.window._brush_actions[0].trigger()
        self.assertEqual(self.window.palette.armed_code(), before)

    def test_out_of_range_brush_index_is_a_no_op(self):
        self.open_map()
        self.window.palette.set_mode("gametiles")
        self.window.palette.arm_gametiles_brush_by_index(99)   # no crash

    def test_labels_show_bound_keys(self):
        self.open_map()
        self.window.palette.set_mode("gametiles")
        buildable_btn = self.window.palette._brush_buttons[("code", "b")]
        self.assertEqual(buildable_btn.text(), "Buildable (1)")
        paint_btn = self.window.palette._tool_buttons["paint"]
        self.assertEqual(paint_btn.text(), "Paint (B)")


if __name__ == "__main__":
    unittest.main()
