"""ESV-2 acceptance tests: anchor handles in the viewport + the AnchorsPanel
authoring form (phase-esv-2-anchor-handles.md §4.2).

Same headless conventions as test_editor_viewport.py/test_editor_panels.py:
QT_QPA_PLATFORM=offscreen + SDL dummy drivers before any Qt/pygame import
(via qt_harness), one QApplication per process, every test against a
TempDataCase tempdir copy of data/ so writes never touch the repo.
"""
import unittest
from pathlib import Path
from unittest import mock

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6/pygame, which read those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from editor import anchor_ops, asset_import
from editor.panels.anchors_panel import AnchorsPanel
from editor.panels.details import DetailsPanel
from editor.panels.viewport import ViewportPanel
from engine import data_io
from engine.assets.manifest import ANCHOR_NAMES
from tools.tests.test_editor_panels import TempDataCase


def write_entry(data_dir, slot_key, frame_w=64, frame_h=64, anchors=None,
                offset_x=0, offset_y=0):
    """A minimal manifest v2 entry for `slot_key` — no PNG required, since
    frame_size/anchor lookups resolve from the entry's own metadata before
    pygame ever touches a sheet (AssetStore.frame_size/anchor)."""
    doc = asset_import.load_manifest_doc(data_dir)
    entry = {
        "sheet": f"imported/{slot_key}.png",
        "frame_w": frame_w,
        "frame_h": frame_h,
        "offset_x": offset_x,
        "offset_y": offset_y,
        "rows": [{
            "animation": "idle", "frames": 1, "fps": 8, "hidden": [],
            "loop_start": 0, "loop_end": 0, "loop_count": 1,
        }],
    }
    if anchors is not None:
        entry["anchors"] = {name: list(xy) for name, xy in anchors.items()}
    doc["entries"][slot_key] = entry
    asset_import.write_manifest_doc(data_dir, doc)
    return entry


def record_overlay(panel):
    calls = []
    original = panel._renderer.submit_overlay_lines

    def wrapper(points, color, width=1, closed=False):
        calls.append((points, color, width, closed))
        return original(points, color, width=width, closed=closed)

    panel._renderer.submit_overlay_lines = wrapper
    return calls


# ---------------------------------------------------------------------------
# 1. Pure round-trip (no Qt)
# ---------------------------------------------------------------------------
class TestPureConversions(unittest.TestCase):
    def test_screen_point_frame_px_round_trip(self):
        origin = (400.0, 300.0)
        for s, zoom in ((1.0, 1.0), (0.5, 1.0), (1.0, 2.0), (0.73, 0.5), (2.0, 2.0)):
            for ax, ay in ((0, 0), (18, -40), (-4096, 4096), (4096, -4096), (7, 13)):
                sx, sy = anchor_ops.screen_point(origin, ax, ay, s, zoom)
                rax, ray = anchor_ops.frame_px(origin, sx, sy, s, zoom)
                self.assertEqual((rax, ray), (ax, ay), msg=(s, zoom, ax, ay))


# ---------------------------------------------------------------------------
# Shared Qt fixture helpers
# ---------------------------------------------------------------------------
class AnchorsTestCase(TempDataCase):
    def make_viewport(self, w=800, h=600):
        panel = self.track(ViewportPanel(data_dir=self.data_dir))
        panel.resize(w, h)
        panel.show()
        _APP.processEvents()
        return panel

    def make_panel(self):
        panel = self.track(AnchorsPanel(data_dir=self.data_dir))
        panel.show()
        _APP.processEvents()
        return panel

    def wire(self, viewport, panel):
        """Mirrors editor/main.py's ESV-2 signal-wiring block exactly."""
        panel.mapping_changed.connect(viewport.set_anchors)
        panel.anchor_selected.connect(viewport.set_selected_anchor)
        viewport.anchor_selected.connect(panel.select_anchor)
        viewport.anchor_dragged.connect(panel.on_anchor_dragged)
        viewport.anchor_drag_finished.connect(panel.on_anchor_drag_finished)


# ---------------------------------------------------------------------------
# 2. A synthetic drag writes the expected frame-px and the JSON validates
# ---------------------------------------------------------------------------
class TestSyntheticDrag(AnchorsTestCase):
    def test_drag_writes_expected_frame_px_and_validates_once(self):
        slot = "esv2_muzzle_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)})
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        origin, s, zoom = viewport._anchor_draw_params()
        target_ax, target_ay = 18, -40
        target_sx, target_sy = anchor_ops.screen_point(
            origin, target_ax, target_ay, s, zoom)

        with mock.patch.object(anchor_ops, "set_anchor",
                               wraps=anchor_ops.set_anchor) as spy:
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                             pos=QPoint(round(origin[0]), round(origin[1])))
            mid = QPoint(round((origin[0] + target_sx) / 2),
                        round((origin[1] + target_sy) / 2))
            QTest.mouseMove(viewport, mid)
            QTest.mouseMove(viewport, QPoint(round(target_sx), round(target_sy)))
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                               pos=QPoint(round(target_sx), round(target_sy)))
            self.assertEqual(spy.call_count, 1)   # ONE write, on release only

        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"]["muzzle"],
                         [target_ax, target_ay])
        data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")

    def test_click_with_no_movement_writes_nothing_but_selects(self):
        slot = "esv2_click_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)})
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        origin, _s, _zoom = viewport._anchor_draw_params()
        pos = QPoint(round(origin[0]), round(origin[1]))
        with mock.patch.object(anchor_ops, "set_anchor",
                               wraps=anchor_ops.set_anchor) as spy:
            QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=pos)
            QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=pos)
            self.assertEqual(spy.call_count, 0)
        self.assertEqual(viewport._anchor_selected, "muzzle")
        self.assertEqual(panel._selected, "muzzle")


# ---------------------------------------------------------------------------
# 3. Zoom invariance of the drag
# ---------------------------------------------------------------------------
class TestZoomInvariance(AnchorsTestCase):
    def _drag_to(self, viewport, ax, ay):
        origin, s, zoom = viewport._anchor_draw_params()
        sx, sy = anchor_ops.screen_point(origin, ax, ay, s, zoom)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(origin[0]), round(origin[1])))
        QTest.mouseMove(viewport, QPoint(round(sx), round(sy)))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           pos=QPoint(round(sx), round(sy)))

    def test_same_target_at_two_zoom_levels_authors_the_same_value(self):
        results = {}
        for zoom in (1.0, 2.0):
            slot = "esv2_zoom_slot_" + str(zoom).replace(".", "_")
            write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)})
            viewport = self.make_viewport()
            panel = self.make_panel()
            self.wire(viewport, panel)
            viewport.set_preview_slot(slot)
            panel.set_slot(slot)
            _APP.processEvents()
            viewport._coords.set_zoom(zoom)
            viewport._center_on_preview(viewport.width(), viewport.height())
            self._drag_to(viewport, 24, -30)
            doc = asset_import.load_manifest_doc(self.data_dir)
            results[zoom] = tuple(doc["entries"][slot]["anchors"]["muzzle"])
        self.assertEqual(results[1.0], (24, -30))
        self.assertEqual(results[2.0], (24, -30))


# ---------------------------------------------------------------------------
# 4. Panel <-> handle agree in BOTH directions
# ---------------------------------------------------------------------------
class TestBidirectionalSync(AnchorsTestCase):
    def test_drag_then_panel_matches_handle(self):
        slot = "esv2_sync_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)})
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        origin, s, zoom = viewport._anchor_draw_params()
        sx, sy = anchor_ops.screen_point(origin, 10, -15, s, zoom)
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(origin[0]), round(origin[1])))
        QTest.mouseMove(viewport, QPoint(round(sx), round(sy)))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           pos=QPoint(round(sx), round(sy)))

        self.assertEqual(viewport._anchors["muzzle"], (10, -15))
        self.assertEqual(panel._spin_x["muzzle"].value(), 10)
        self.assertEqual(panel._spin_y["muzzle"].value(), -15)

    def test_external_value_change_moves_the_handle(self):
        slot = "esv2_sync_slot_2"
        write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)})
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        panel._spin_x["muzzle"].setValue(33)
        panel._spin_y["muzzle"].setValue(-12)
        panel._spin_x["muzzle"].editingFinished.emit()
        panel._spin_y["muzzle"].editingFinished.emit()

        self.assertEqual(viewport._anchors["muzzle"], (33, -12))
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"]["muzzle"], [33, -12])


# ---------------------------------------------------------------------------
# 5. A slot with no anchors can gain one, and lose it cleanly
# ---------------------------------------------------------------------------
class TestAuthorFromNothing(AnchorsTestCase):
    def test_tick_creates_zero_untick_removes_and_is_byte_identical(self):
        slot = "esv2_fresh_slot"
        write_entry(self.data_dir, slot)   # no anchors key at all
        manifest_path = self.data_dir / "sprites" / "asset_manifest.json"
        original_bytes = manifest_path.read_bytes()

        panel = self.make_panel()
        panel.set_slot(slot)
        self.assertTrue(panel._has_entry)
        for name in ANCHOR_NAMES:
            self.assertFalse(panel._checks[name].isChecked())

        panel._checks["muzzle"].setChecked(True)
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"], {"muzzle": [0, 0]})
        data_io.load_validated(
            manifest_path, self.data_dir / "schemas" / "asset_manifest.schema.json")

        panel._spin_x["muzzle"].setValue(12)
        panel._spin_x["muzzle"].editingFinished.emit()
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"]["muzzle"], [12, 0])

        panel._checks["muzzle"].setChecked(False)
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertNotIn("anchors", doc["entries"][slot])
        self.assertEqual(manifest_path.read_bytes(), original_bytes)

    def test_removing_one_of_two_keeps_the_block(self):
        slot = "esv2_two_slot"
        write_entry(self.data_dir, slot)
        panel = self.make_panel()
        panel.set_slot(slot)
        panel._checks["muzzle"].setChecked(True)
        panel._checks["impact"].setChecked(True)
        panel._checks["muzzle"].setChecked(False)
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"], {"impact": [0, 0]})


# ---------------------------------------------------------------------------
# 6. A DetailsPanel save does not erase anchors (the draft_entry() regression)
# ---------------------------------------------------------------------------
class TestDetailsSavePreservesAnchors(AnchorsTestCase):
    def test_second_save_keeps_the_anchor(self):
        slot = "base_hole"   # a real registry slot (core category, 64x96)
        self.unassign_slot(slot)
        png_path = Path(self.data_dir) / "_fixture_base_hole.png"
        Image.new("RGBA", (64, 96), (0, 0, 0, 0)).save(png_path)

        details = self.track(DetailsPanel(data_dir=self.data_dir))
        details.set_slot(slot)
        details.import_sheet(str(png_path))
        details.save()   # base entry, no anchors

        ok = anchor_ops.set_anchor(self.data_dir, slot, "muzzle", (5, -7))
        self.assertTrue(ok)

        details.save()   # THE regression pin: must not erase the anchor
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot].get("anchors"),
                         {"muzzle": [5, -7]})


# ---------------------------------------------------------------------------
# 7. No entry => no write, no raise
# ---------------------------------------------------------------------------
class TestNoEntryNoWrite(AnchorsTestCase):
    def test_missing_entry_direct_call_returns_false_and_writes_nothing(self):
        slot = "esv2_ghost_slot"
        self.assertFalse(anchor_ops.set_anchor(self.data_dir, slot, "muzzle", (1, 2)))
        self.assertFalse(anchor_ops.clear_anchor(self.data_dir, slot, "muzzle"))
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertNotIn(slot, doc["entries"])

    def test_panel_disables_rows_for_a_slot_with_no_entry(self):
        slot = "esv2_ghost_slot_2"
        panel = self.make_panel()
        panel.set_slot(slot)
        self.assertFalse(panel._has_entry)
        self.assertTrue(panel._guidance.isVisible())
        for name in ANCHOR_NAMES:
            self.assertFalse(panel._checks[name].isEnabled())
        # a programmatic tick on a disabled row must still not write or raise
        panel._checks["muzzle"].setChecked(True)
        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertNotIn(slot, doc["entries"])


# ---------------------------------------------------------------------------
# 8. fix-anchor-offset-and-bullet-sprites Fix 1: origin composes offset_x/y,
#    and the drag round-trips through the SHIFTED origin unchanged (proof
#    screen_point/frame_px stayed exact inverses after the origin moved).
# ---------------------------------------------------------------------------
class TestOffsetComposedOrigin(AnchorsTestCase):
    def test_origin_shifts_by_the_entrys_offset(self):
        """`_anchor_draw_params`'s origin moves by exactly the entry's
        offset (scaled by s * zoom) relative to the same slot with no
        offset — the renderer already draws the art there."""
        plain_slot = "esv_offset_plain_slot"
        nudged_slot = "esv_offset_nudged_slot"
        write_entry(self.data_dir, plain_slot, anchors={"muzzle": (0, 0)})
        write_entry(self.data_dir, nudged_slot, anchors={"muzzle": (0, 0)},
                   offset_x=0, offset_y=8)

        viewport = self.make_viewport()
        viewport.set_preview_slot(plain_slot)
        _APP.processEvents()
        plain_origin, s, zoom = viewport._anchor_draw_params()

        viewport.set_preview_slot(nudged_slot)
        _APP.processEvents()
        nudged_origin, s2, zoom2 = viewport._anchor_draw_params()

        self.assertEqual((s, zoom), (s2, zoom2))
        self.assertAlmostEqual(nudged_origin[0], plain_origin[0])
        self.assertAlmostEqual(nudged_origin[1],
                               plain_origin[1] + 8 * s * zoom)

    def test_drag_on_a_nudged_slot_writes_expected_frame_px_and_redraws_there(self):
        """A synthetic drag on a NUDGED slot writes the frame-px the
        designer sees, and re-seeding the panel (a fresh `_anchor_draw_
        params()` call, as happens on reload/re-select) redraws the handle
        at the exact same screen point — the pin that `screen_point`/
        `frame_px` stayed exact inverses over the shifted origin."""
        slot = "esv_offset_drag_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (0, 0)},
                   offset_x=0, offset_y=8)
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        origin, s, zoom = viewport._anchor_draw_params()
        target_ax, target_ay = 18, -40
        target_sx, target_sy = anchor_ops.screen_point(
            origin, target_ax, target_ay, s, zoom)

        QTest.mousePress(viewport, Qt.MouseButton.LeftButton,
                         pos=QPoint(round(origin[0]), round(origin[1])))
        QTest.mouseMove(viewport, QPoint(round(target_sx), round(target_sy)))
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton,
                           pos=QPoint(round(target_sx), round(target_sy)))

        doc = asset_import.load_manifest_doc(self.data_dir)
        self.assertEqual(doc["entries"][slot]["anchors"]["muzzle"],
                         [target_ax, target_ay])

        # Re-seed (fresh origin computation) and confirm the handle redraws
        # at the SAME screen point the drag ended on.
        origin2, s2, zoom2 = viewport._anchor_draw_params()
        self.assertEqual((origin2, s2, zoom2), (origin, s, zoom))
        redraw_sx, redraw_sy = anchor_ops.screen_point(
            origin2, target_ax, target_ay, s2, zoom2)
        self.assertAlmostEqual(redraw_sx, target_sx)
        self.assertAlmostEqual(redraw_sy, target_sy)


# ---------------------------------------------------------------------------
# 9. No QPainter regression — the handle reaches the ONE render path (ED-22)
# ---------------------------------------------------------------------------
class TestRenderPathIsOverlayOnly(AnchorsTestCase):
    def test_render_frame_submits_overlay_lines_for_an_anchor(self):
        slot = "esv2_render_slot"
        write_entry(self.data_dir, slot, anchors={"muzzle": (10, -10)})
        viewport = self.make_viewport()
        panel = self.make_panel()
        self.wire(viewport, panel)
        viewport.set_preview_slot(slot)
        panel.set_slot(slot)
        _APP.processEvents()

        calls = record_overlay(viewport)
        viewport.render_frame()
        # one closed outline + a 2-line crosshair, both through submit_overlay_lines
        self.assertEqual(len(calls), 3)


if __name__ == "__main__":
    unittest.main()
