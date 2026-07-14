"""Phase 3 acceptance tests for the Qt viewport spike (ED-2/ED-22/ED-23).

QApplication is a per-process singleton under Qt; QT_QPA_PLATFORM=offscreen
is set before PySide6 is imported so the whole module runs headlessly,
mirroring the SDL dummy-driver convention used for pygame elsewhere in
tools/tests/.
"""
import subprocess
import sys
import unittest
from pathlib import Path

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6/pygame, which read those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

import pygame
from PySide6.QtWidgets import QApplication

from editor.panels.viewport import ViewportPanel, surface_to_qimage
from engine import data_io
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]


class TestSurfaceToQImage(unittest.TestCase):
    """Pure conversion, pixel-exact on a known 2x2-quadrant pattern."""

    def test_pixel_equality(self):
        pygame.init()
        surface = pygame.Surface((4, 4))
        colors = {
            (0, 0): (255, 0, 0),
            (2, 0): (0, 255, 0),
            (0, 2): (0, 0, 255),
            (2, 2): (255, 255, 0),
        }
        for (x, y), color in colors.items():
            surface.fill(color, pygame.Rect(x, y, 2, 2))

        image = surface_to_qimage(surface)
        self.assertEqual((image.width(), image.height()), (4, 4))
        for (x, y), color in colors.items():
            got = image.pixelColor(x, y)
            self.assertEqual((got.red(), got.green(), got.blue()), color)


class TestHeadlessViewportPaint(QtCase):
    """Full pipeline: grid renders through engine/render and reaches pixels."""

    def test_grid_paints_nonbackground_pixels(self):
        panel = self.track(ViewportPanel(data_dir=REPO / "data"))
        panel.resize(256, 256)
        panel.render_frame()
        pixmap = panel.grab()
        image = pixmap.toImage()
        background = (24, 20, 32)
        touched = 0
        for x in range(0, image.width(), 8):
            for y in range(0, image.height(), 8):
                c = image.pixelColor(x, y)
                if (c.red(), c.green(), c.blue()) != background:
                    touched += 1
        self.assertGreater(touched, 0)

    def test_resize_recreates_surface_to_match_widget(self):
        panel = self.track(ViewportPanel(data_dir=REPO / "data"))
        panel.show()
        panel.resize(320, 200)
        _APP.processEvents()
        panel.render_frame()
        self.assertEqual(panel._surface.get_size(), (320, 200))
        panel.resize(150, 400)
        _APP.processEvents()
        panel.render_frame()
        self.assertEqual(panel._surface.get_size(), (150, 400))


class TestZoomStep(QtCase):
    """ED-23 wheel zoom moves only through data-driven zoom levels."""

    def test_zoom_step_stays_within_data_driven_levels(self):
        panel = self.track(ViewportPanel(data_dir=REPO / "data"))
        panel.resize(200, 200)
        levels = sorted(panel._coords.geometry.zoom_levels)
        self.assertIn(panel._coords.camera.zoom, levels)
        panel._step_zoom(1)
        self.assertIn(panel._coords.camera.zoom, levels)
        # stepping past the top level is a no-op, not an error
        for _ in range(len(levels) + 2):
            panel._step_zoom(1)
        self.assertEqual(panel._coords.camera.zoom, levels[-1])


def paint_bytes(panel):
    panel.render_frame()
    return pygame.image.tobytes(panel._surface, "RGB")


DRAFT_ENTRY = {
    "sheet": "imported/painter_t1_lvl1.png",
    "frame_w": 64, "frame_h": 96, "offset_x": 0, "offset_y": 0,
    "rows": [
        {"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
         "loop_start": 0, "loop_end": 0, "loop_count": 1},
        {"animation": "attack", "frames": 1, "fps": 8, "hidden": [],
         "loop_start": 0, "loop_end": 0, "loop_count": 1},
    ],
}


class TestEntityPreview(TempDataCase):
    """ED-21/ED-42: slot preview through the real engine pipeline, draft
    overrides without disk writes, reload without restart.

    Every test here needs a slot with NO manifest entry — that is what makes
    "grey X", "no dropdown" and "the draft is the only source" observable.
    UNASSIGNED is emptied in setUp rather than assumed empty: it used to be
    assumed, art landed on painter_t1_lvl1, and four of these tests went red
    for two months while testing nothing."""

    UNASSIGNED = "painter_t1_lvl1"

    def setUp(self):
        super().setUp()
        self.unassign_slot(self.UNASSIGNED)

    def make(self):
        panel = self.track(ViewportPanel(data_dir=self.data_dir))
        panel.resize(256, 256)
        return panel

    def test_grid_mode_is_default_and_preview_changes_pixels(self):
        panel = self.make()
        self.assertIsNone(panel.preview_slot)
        baseline = paint_bytes(panel)
        panel.set_preview_slot("painter_t1_lvl1")   # unassigned -> grey X 64x96
        self.assertNotEqual(paint_bytes(panel), baseline)
        panel.set_preview_slot("stone_thrower_t1_lvl1")   # migrated sheet
        self.assertNotEqual(paint_bytes(panel), baseline)
        panel.set_preview_slot(None)                # back to plain grid
        self.assertEqual(paint_bytes(panel), baseline)

    def test_preview_animations_and_dropdown_follow_the_slot(self):
        panel = self.make()
        panel.set_preview_slot("stone_thrower_t1_lvl1")
        self.assertEqual(panel.preview_animations(), ("idle", "attack"))
        self.assertEqual(panel.preview_animation, "idle")
        combo = panel._anim_combo
        self.assertFalse(combo.isHidden())
        self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                         ["idle", "attack"])
        panel.set_preview_animation("attack")
        self.assertEqual(panel.preview_animation, "attack")
        panel.render_frame()   # animating a non-idle row never raises
        panel.set_preview_slot("painter_t1_lvl1")   # no entry -> no dropdown
        self.assertEqual(panel.preview_animations(), ())
        self.assertTrue(combo.isHidden())

    def test_draft_override_never_touches_disk(self):
        panel = self.make()
        panel.set_preview_slot("painter_t1_lvl1")
        self.assertEqual(panel.preview_animations(), ())
        panel.set_preview_draft("painter_t1_lvl1", DRAFT_ENTRY)
        self.assertEqual(panel.preview_animations(), ("idle", "attack"))
        on_disk = data_io.load_json(
            self.data_dir / "sprites" / "asset_manifest.json")
        self.assertNotIn("painter_t1_lvl1", on_disk["entries"])
        panel.set_preview_draft("painter_t1_lvl1", None)   # draft dropped
        self.assertEqual(panel.preview_animations(), ())

    def test_unusable_draft_falls_back_instead_of_raising(self):
        panel = self.make()
        panel.set_preview_slot("painter_t1_lvl1")
        bad = dict(DRAFT_ENTRY, rows=[dict(DRAFT_ENTRY["rows"][0],
                                           hidden=[0])])   # every frame hidden
        panel.set_preview_draft("painter_t1_lvl1", bad)
        self.assertEqual(panel.preview_animations(), ())
        panel.render_frame()   # grey X, no crash (E-37)

    def test_reload_assets_sees_disk_change_and_keeps_camera(self):
        panel = self.make()
        panel.set_preview_slot("painter_t1_lvl1")
        panel._step_zoom(1)
        zoom = panel._coords.camera.zoom
        doc = data_io.load_json(self.data_dir / "sprites" / "asset_manifest.json")
        doc["entries"]["painter_t1_lvl1"] = DRAFT_ENTRY
        data_io.write_validated(
            doc, self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")
        self.assertEqual(panel.preview_animations(), ())   # not seen yet
        panel.reload_assets()                              # ED-42
        self.assertEqual(panel.preview_animations(), ("idle", "attack"))
        self.assertEqual(panel._coords.camera.zoom, zoom)  # Phase 3 feel kept


class TestPurity(unittest.TestCase):
    """Hard rule: editor/ never imports game/ (root CLAUDE.md layering rule)."""

    def test_editor_does_not_import_game(self):
        code = (
            "import sys; "
            "import editor.main, editor.domains, editor.selection, "
            "editor.tilemap_ops, editor.map_session, editor.asset_import, "
            "editor.registry_ops, editor.balancing_history, "
            "editor.run_controls, editor.spawnclaude, editor.theme, "
            "editor.agent_forms, editor.agent_form_dialog, editor.plans, "
            "editor.panels.selector, editor.panels.balancing, "
            "editor.panels.viewport, editor.panels.details, "
            "editor.panels.level_bar, editor.panels.palette, "
            "editor.panels.map_details, editor.panels.sheet_preview, "
            "editor.panels.sheet_picker; "
            "assert not any(m == 'game' or m.startswith('game.') for m in sys.modules), "
            "'editor imported game/'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
