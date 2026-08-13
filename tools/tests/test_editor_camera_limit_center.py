"""The tilemap editor's "Camera Limit Center" brush — a single-tile marker
brush structurally identical to Camera Start (place / move / drag / erase, one
undoable command each) that the camera does NOT start on: it only anchors the
core-balancing Camera.max_offset_tiles_x/_y travel limit.

Two things separate it from Camera Start and are what these tests pin: it draws
as a BLUE OUTLINE through the E-24 overlay primitive rather than a sprite (the
tutorial-marker idiom, never engine/tilemap.py's emitters), and it shares the
`camera` layer eye with Camera Start rather than owning one.

Own file (test_editor_map_mode.py is already large); harness mirrors
MapModeCase from test_editor_tutorial_paint.py.
"""
from pathlib import Path

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP
from tools.tests.temp_data import TempDataCase

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from editor.main import MainWindow
from engine import data_io, tilemap
from engine.render import DrawCall, HudText, OverlayLines, Renderer

STARTER = "first_light"
SLOT = "camera_limit_centerpoint"


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def __call__(self, target, draw_calls):
        self.calls = list(draw_calls)


class MapModeCase(TempDataCase):
    """MainWindow against a temp data/ copy, starter map selected."""

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

    def arm_limit_center(self):
        self.window.palette.set_mode("gametiles")
        self.window.palette.arm_camera_limit_center(SLOT)
        self.window.palette.set_tool("paint")

    def record_frame(self):
        backend = RecordingBackend()
        self.viewport._renderer = Renderer(
            self.viewport._coords, self.viewport._assets, backend=backend)
        self.viewport.render_frame()
        return backend.calls


class TestCameraLimitCenterBrush(MapModeCase):
    def test_click_places_marker_and_is_undoable(self):
        doc = self.open_map()
        self.assertIsNone(doc.camera_limit_center)
        self.arm_limit_center()
        self.click_cell(5, 6)
        self.assertEqual(doc.camera_limit_center,
                         {"col": 5, "row": 6, "slot": SLOT})
        self.assertEqual(self.session.undo_stack.count(), 1)
        self.session.undo_stack.undo()
        self.assertIsNone(doc.camera_limit_center)
        self.session.undo_stack.redo()
        self.assertEqual(doc.camera_limit_center["col"], 5)

    def test_second_click_elsewhere_moves_it(self):
        doc = self.open_map()
        self.arm_limit_center()
        self.click_cell(5, 6)
        self.click_cell(9, 3)
        self.assertEqual(doc.camera_limit_center,
                         {"col": 9, "row": 3, "slot": SLOT})
        # still ONE marker, not two — moved, not added
        self.assertEqual(self.session.undo_stack.count(), 2)

    def test_erase_removes(self):
        doc = self.open_map()
        self.arm_limit_center()
        self.click_cell(5, 6)
        self.window.palette.set_tool("erase")
        self.click_cell(10, 10)   # erase targets the single object, any cell
        self.assertIsNone(doc.camera_limit_center)
        self.session.undo_stack.undo()
        self.assertEqual(doc.camera_limit_center["col"], 5)

    def test_save_round_trips_to_disk(self):
        self.open_map()
        self.arm_limit_center()
        self.click_cell(2, 2)
        self.session.save()
        loaded = tilemap.load_map(
            tilemap.map_path(self.data_dir, STARTER),
            tilemap.map_schema_path(self.data_dir))
        self.assertEqual(loaded.camera_limit_center,
                         {"col": 2, "row": 2, "slot": SLOT})

    def test_drag_moves_the_placed_marker(self):
        doc = self.open_map()
        doc.camera_limit_center = {"col": 4, "row": 4, "slot": SLOT}
        self.window.palette.set_tool("none")   # no brush armed — the drag path
        QTest.mousePress(self.viewport, Qt.MouseButton.LeftButton,
                         pos=self.cell_pos(4, 4))
        self.assertTrue(self.viewport._camera_limit_center_drag)
        QTest.mouseRelease(self.viewport, Qt.MouseButton.LeftButton,
                           pos=self.cell_pos(7, 8))
        self.assertEqual(doc.camera_limit_center,
                         {"col": 7, "row": 8, "slot": SLOT})
        self.assertFalse(self.viewport._camera_limit_center_drag)

    def test_arming_it_disarms_camera_start(self):
        self.open_map()
        self.window.palette.set_mode("gametiles")
        self.window.palette.arm_camera("camera_startpoint")
        self.assertIsNotNone(self.viewport._armed_camera)
        self.arm_limit_center()
        self.assertIsNone(self.viewport._armed_camera)
        self.assertEqual(self.viewport._armed_camera_limit_center, SLOT)
        # ...and back the other way
        self.window.palette.arm_camera("camera_startpoint")
        self.assertIsNone(self.viewport._armed_camera_limit_center)

    def test_brush_sits_immediately_after_camera_start(self):
        self.open_map()
        kinds = [key[0]
                 for key, _ in self.window.palette._gametiles_brush_order()]
        self.assertEqual(kinds[kinds.index("camera") + 1],
                         "camera_limit_center")


class TestRenderPath(MapModeCase):
    """ED-22: the placed marker emits exactly one OverlayLines (closed, 4
    points, world min corner) + one HudText caption, gated by the CAMERA eye
    it shares with Camera Start — mirrors test_editor_tutorial_paint's
    TestRenderPath."""

    def test_outline_and_caption_through_render_path(self):
        doc = self.open_map()
        doc.camera_limit_center = {"col": 3, "row": 3, "slot": SLOT}
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
        self.assertEqual(texts[0].text, "Camera Limit Center")

        # shares the camera eye with Camera Start — no eye of its own
        self.viewport.set_eye("camera", False)
        calls = self.record_frame()
        self.assertFalse(any(isinstance(c, OverlayLines) for c in calls))
        self.assertFalse(any(isinstance(c, HudText) for c in calls))

    def test_never_a_sprite(self):
        # The marker never adds a DrawCall — engine/tilemap.py's emitters
        # deliberately never touch camera_limit_center (unlike camera_start),
        # and the editor draws only the outline + caption.
        doc = self.open_map()
        without = len(
            [c for c in self.record_frame() if isinstance(c, DrawCall)])
        doc.camera_limit_center = {"col": 3, "row": 3, "slot": SLOT}
        with_marker = len(
            [c for c in self.record_frame() if isinstance(c, DrawCall)])
        self.assertEqual(with_marker, without)
