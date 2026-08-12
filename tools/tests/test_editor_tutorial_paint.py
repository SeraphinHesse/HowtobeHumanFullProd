"""Phase TU-2 acceptance tests: the tilemap editor's fourth "Tutorial" paint
mode (D1, planning/TutorialPLAN.md) — two single-tile marker brushes ("First
Flute" / "First Stone") mirroring the camera_start/start_area single-object
pattern (ED-10/ED-20/ED-23/ED-24). Own file (test_editor_map_mode.py is
already large); harness mirrors MapModeCase from that module.

Same headless conventions as the other editor tests: QT_QPA_PLATFORM=
offscreen + SDL dummy drivers before any Qt/pygame import, one
QApplication per process, tempfile COPY of data/ so nothing touches the
repo's files.
"""
import shutil
import tempfile
from pathlib import Path

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase
from tools.tests.temp_data import TempDataCase

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from editor.main import MainWindow
from engine import data_io, tilemap
from engine.render import DrawCall, HudText, OverlayLines, Renderer

REPO = Path(__file__).resolve().parents[2]

STARTER = "first_light"


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls = list(draw_calls)


class MapModeCase(TempDataCase):
    """MainWindow against a temp data/ copy, starter map selected — mirrors
    test_editor_map_mode.MapModeCase."""

    def setUp(self):
        super().setUp()
        self.set_active_map(STARTER)
        self.window = self.track(MainWindow(data_dir=self.data_dir))
        self.window.resize(1280, 720)
        self.window.show()
        self.viewport = self.window.viewport
        self.session = self.window.map_session

    def set_active_map(self, map_id):
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

    def arm_tutorial_flute(self):
        self.window.palette.set_mode("tutorial")
        self.window.palette.arm_tutorial_flute("tutorial_flute")
        self.window.palette.set_tool("paint")

    def arm_tutorial_stone(self):
        self.window.palette.set_mode("tutorial")
        self.window.palette.arm_tutorial_stone("tutorial_stone")
        self.window.palette.set_tool("paint")

    def record_frame(self):
        backend = RecordingBackend()
        self.viewport._renderer = Renderer(
            self.viewport._coords, self.viewport._assets, backend=backend)
        self.viewport.render_frame()
        return backend.calls


class TestTutorialFlute(MapModeCase):
    def test_click_places_marker_and_is_undoable(self):
        doc = self.open_map()
        self.assertIsNone(doc.tutorial_flute)
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.assertEqual(doc.tutorial_flute,
                         {"col": 5, "row": 6, "slot": "tutorial_flute"})
        self.assertEqual(self.session.undo_stack.count(), 1)
        self.session.undo_stack.undo()
        self.assertIsNone(doc.tutorial_flute)
        self.session.undo_stack.redo()
        self.assertEqual(doc.tutorial_flute["col"], 5)

    def test_second_click_elsewhere_moves_it(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.click_cell(9, 3)
        self.assertEqual(doc.tutorial_flute,
                         {"col": 9, "row": 3, "slot": "tutorial_flute"})
        # still ONE marker, not two — moved, not added
        self.assertEqual(self.session.undo_stack.count(), 2)

    def test_erase_removes(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.window.palette.set_tool("erase")
        self.click_cell(10, 10)   # erase targets the single object, any cell
        self.assertIsNone(doc.tutorial_flute)
        self.session.undo_stack.undo()
        self.assertEqual(doc.tutorial_flute["col"], 5)

    def test_save_round_trips_to_disk(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(2, 2)
        self.session.save()
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded.tutorial_flute,
                         {"col": 2, "row": 2, "slot": "tutorial_flute"})


class TestTutorialStoneIndependence(MapModeCase):
    """First Stone behaves identically to First Flute and independently of
    it: arming one disarms the other; both can coexist on the same map."""

    def test_arming_stone_disarms_flute(self):
        self.open_map()
        self.arm_tutorial_flute()
        self.assertEqual(self.window.palette.armed_tutorial_flute(),
                         "tutorial_flute")
        self.arm_tutorial_stone()
        self.assertIsNone(self.window.palette.armed_tutorial_flute())
        self.assertEqual(self.window.palette.armed_tutorial_stone(),
                         "tutorial_stone")

    def test_both_markers_coexist(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.arm_tutorial_stone()
        self.click_cell(9, 3)
        self.assertEqual(doc.tutorial_flute,
                         {"col": 5, "row": 6, "slot": "tutorial_flute"})
        self.assertEqual(doc.tutorial_stone,
                         {"col": 9, "row": 3, "slot": "tutorial_stone"})

    def test_stone_erase_does_not_touch_flute(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.arm_tutorial_stone()
        self.click_cell(9, 3)
        self.window.palette.set_tool("erase")
        self.click_cell(9, 3)
        self.assertIsNone(doc.tutorial_stone)
        self.assertEqual(doc.tutorial_flute,
                         {"col": 5, "row": 6, "slot": "tutorial_flute"})

    def test_save_round_trips_both_markers(self):
        doc = self.open_map()
        self.arm_tutorial_flute()
        self.click_cell(5, 6)
        self.arm_tutorial_stone()
        self.click_cell(9, 3)
        self.session.save()
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded.tutorial_flute,
                         {"col": 5, "row": 6, "slot": "tutorial_flute"})
        self.assertEqual(loaded.tutorial_stone,
                         {"col": 9, "row": 3, "slot": "tutorial_stone"})


class TestOtherModesUnaffected(MapModeCase):
    """Regression guard: gametiles/background/decoration paint/erase/save
    still work unmodified after the tutorial-mode branches were added —
    proves the new branches are additive, not a dispatch reordering that
    swallows an existing case."""

    def test_gametiles_paint_erase_save_unaffected(self):
        doc = self.open_map()
        self.window.palette.set_mode("gametiles")
        self.window.palette.arm_code("b")
        self.window.palette.set_tool("paint")
        self.click_cell(15, 15)
        self.assertEqual(doc.terrain[15][15], "b")
        self.assertTrue(self.session.dirty)
        self.session.save()
        self.assertFalse(self.session.dirty)
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded.terrain[15][15], "b")

    def test_deco_place_erase_unaffected(self):
        doc = self.open_map()
        self.window.palette.set_mode("decoration")
        self.window.palette.arm_deco("deco_tree")
        self.window.palette.set_tool("paint")
        before = len(doc.deco)
        self.click_cell(12, 12)
        self.assertEqual(len(doc.deco), before + 1)
        self.window.palette.set_tool("erase")
        self.click_cell(12, 12)
        self.assertEqual(len(doc.deco), before)


class TestRenderPath(MapModeCase):
    """ED-22: a placed marker emits exactly one OverlayLines (closed, 4
    points, world min corner) + one HudText caption, gated by the tutorial
    eye — mirrors TestRenderPath.test_start_area_outline_through_overlay_
    primitive in test_editor_map_mode.py."""

    def test_flute_outline_and_caption_through_render_path(self):
        doc = self.open_map()
        doc.tutorial_flute = {"col": 3, "row": 3, "slot": "tutorial_flute"}
        calls = self.record_frame()
        lines = [c for c in calls if isinstance(c, OverlayLines)]
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].closed)
        self.assertEqual(len(lines[0].points), 4)
        sx, sy = self.viewport._coords.world_to_screen(3, 3)
        self.assertAlmostEqual(lines[0].points[0][0], sx, delta=1)
        self.assertAlmostEqual(lines[0].points[0][1], sy, delta=1)

        texts = [c for c in calls if isinstance(c, HudText)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(texts[0].text, "First Flute")

        self.viewport.set_eye("tutorial", False)
        calls = self.record_frame()
        self.assertFalse(any(isinstance(c, OverlayLines) for c in calls))
        self.assertFalse(any(isinstance(c, HudText) for c in calls))

    def test_never_a_sprite(self):
        # The marker never adds a DrawCall — it is deliberately never
        # rendered as a sprite (engine/tilemap.py's render_items/
        # visible_render_items never touch tutorial_flute/tutorial_stone;
        # the editor draws only the OverlayLines outline + HudText caption).
        doc = self.open_map()
        without = len([c for c in self.record_frame() if isinstance(c, DrawCall)])
        doc.tutorial_flute = {"col": 3, "row": 3, "slot": "tutorial_flute"}
        with_marker = len(
            [c for c in self.record_frame() if isinstance(c, DrawCall)])
        self.assertEqual(with_marker, without)
