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
from PIL import Image
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from editor.main import MainWindow
from editor.panels.screen_details import ScreenDetailsPanel
from editor.panels.selector import _PAYLOAD_ROLE, _SCREEN_ROLE, SelectorPanel
from editor.panels.viewport import SCREEN_H, SCREEN_W, ViewportPanel, surface_to_qimage
from editor.ui_screen_session import UIScreenSession
from engine import data_io
from engine.render import HudLines, HudRect, HudSprite, HudText
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

# B4 (R3): hand-authored fixture conforming to B1's ui_screen.schema.json /
# B3's screen_defaults.schema.json shape — {screen_id: {widgets, mock_note}},
# used instead of the (not-yet-landed on this branch) real
# data/ui/screen_defaults.json, exactly like the entity-preview tests use a
# hand-picked slot instead of live manifest content.
FIXTURE_DEFAULTS = {
    "main_menu": {
        "widgets": {
            "btn_new_game": {"rect": [640, 360, 120, 40], "kind": "button",
                             "label": "START"},
            "btn_settings": {"rect": [640, 420, 120, 40], "kind": "button",
                             "label": "SETTINGS"},
            "title": {"rect": [640, 100, 400, 80], "kind": "label",
                     "label": "MAIN MENU"},
        },
        "mock_note": "test fixture",
    }
}


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
        panel = self.track(ViewportPanel(data_dir=FIXTURE_DATA))
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
        panel = self.track(ViewportPanel(data_dir=FIXTURE_DATA))
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
        panel = self.track(ViewportPanel(data_dir=FIXTURE_DATA))
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


class TestSlicedDraftPreview(TempDataCase):
    """A4: a `slice`-carrying draft must take entry_from_dict's happy path in
    set_preview_draft, not its ValueError fallback (viewport.py) -- proven by
    the animations list resolving and render_frame not raising. The nine-slice
    geometry itself is a HUD-only concern (A5); the entity preview here is the
    world `RenderItem` path, which ignores `slice` on purpose."""

    UNASSIGNED = "ui_button"

    def setUp(self):
        super().setUp()
        self.unassign_slot(self.UNASSIGNED)
        # The draft is in-memory only, but AssetStore still resolves the
        # sheet PATH from disk -- write the PNG a fresh import would have.
        Image.new("RGBA", (64, 64), (200, 60, 60, 255)).save(
            self.data_dir / "sprites" / "imported" / "ui_button.png")

    def test_draft_with_slice_previews_and_never_touches_disk(self):
        panel = self.track(ViewportPanel(data_dir=self.data_dir))
        panel.resize(256, 256)
        draft = {
            "sheet": "imported/ui_button.png",
            "frame_w": 64, "frame_h": 64, "offset_x": 0, "offset_y": 0,
            "rows": [
                {"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                 "loop_start": 0, "loop_end": 0, "loop_count": 1},
                {"animation": "hover", "frames": 1, "fps": 8, "hidden": [],
                 "loop_start": 0, "loop_end": 0, "loop_count": 1},
            ],
            "slice": [8, 8, 8, 8],
        }
        panel.set_preview_slot("ui_button")
        panel.set_preview_draft("ui_button", draft)
        self.assertEqual(panel.preview_animations(), ("idle", "hover"))
        panel.render_frame()   # slice-carrying draft never raises
        on_disk = data_io.load_json(
            self.data_dir / "sprites" / "asset_manifest.json")
        self.assertNotIn("ui_button", on_disk["entries"])


class TestSelectorScreensBranch(TempDataCase):
    """B4 §1a: the "ui" category gains a Screens branch, mirroring Maps."""

    def test_selector_shows_screens_branch_above_slots(self):
        selector = self.track(SelectorPanel(data_dir=self.data_dir))
        ui_root = next(
            selector.topLevelItem(i) for i in range(selector.topLevelItemCount())
            if selector.topLevelItem(i).data(0, _PAYLOAD_ROLE) == ("ui", ()))
        self.assertGreater(ui_root.childCount(), 0)
        labels = [ui_root.child(i).text(0) for i in range(ui_root.childCount())]
        self.assertEqual(labels[0], "Screens")           # ABOVE the slot groups
        self.assertIn("Buttons", labels[1:])
        screens_branch = ui_root.child(0)
        self.assertEqual(screens_branch.childCount(), 12)   # B1: 12 screen files

    def test_screen_leaf_emits_screen_selected_not_node_selected(self):
        selector = self.track(SelectorPanel(data_dir=self.data_dir))
        screen_calls = []
        node_calls = []
        selector.screen_selected.connect(screen_calls.append)
        selector.node_selected.connect(lambda *a: node_calls.append(a))
        selector.select_screen("main_menu")
        self.assertEqual(screen_calls, ["main_menu"])
        self.assertEqual(node_calls, [])

    def test_selector_refresh_screens_preserves_selection(self):
        selector = self.track(SelectorPanel(data_dir=self.data_dir))
        selector.select_screen("main_menu")
        selector.refresh_screens()
        item = selector.selectedItems()[0]
        self.assertEqual(item.data(0, _SCREEN_ROLE), "main_menu")


class TestUIScreenSession(TempDataCase):
    """B4 §1b: UIScreenSession mirrors MapSession — open/save lifecycle,
    dirty tracking, undoable push_* commands storing full old/new values."""

    def test_screen_session_open_loads_and_validates(self):
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        doc = session.open("main_menu")
        self.assertEqual(doc, {})   # B1: every screen doc starts life empty
        self.assertFalse(session.dirty)

    def test_screen_session_push_move_undoable(self):
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open("main_menu")
        session.push_move("btn_new_game", None, [10, 10, 50, 20])
        self.assertEqual(session.undo_stack.count(), 1)
        self.assertEqual(
            session.doc["widgets"]["btn_new_game"]["rect"], [10, 10, 50, 20])
        session.undo_stack.undo()
        self.assertNotIn("btn_new_game", session.doc.get("widgets", {}))

    def test_screen_session_push_field_undoable(self):
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open("main_menu")
        session.push_field("title", "label", "OLD", "NEW")
        self.assertEqual(session.doc["widgets"]["title"]["label"], "NEW")
        session.undo_stack.undo()
        self.assertEqual(session.doc["widgets"]["title"]["label"], "OLD")

    def test_screen_session_dirty_after_push_clean_after_save(self):
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open("main_menu")
        session.push_field("title", "label", None, "NEW")
        self.assertTrue(session.dirty)
        session.save()
        self.assertFalse(session.dirty)
        on_disk = data_io.load_validated(
            self.data_dir / "ui" / "screens" / "main_menu.json",
            self.data_dir / "schemas" / "ui_screen.schema.json")
        self.assertEqual(on_disk["widgets"]["title"]["label"], "NEW")


class TestViewportScreenMode(TempDataCase):
    """B4 §1c: fixed 1280x720 canvas through submit_hud only, graceful
    degrade with no defaults, click/drag/nudge interaction."""

    def make_session(self, screen_id="main_menu"):
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open(screen_id)
        return session

    def make_viewport(self):
        panel = self.track(ViewportPanel(data_dir=self.data_dir))
        panel.resize(SCREEN_W, SCREEN_H)   # scale 1.0, offset 0 — trivial math
        panel.show()
        _APP.processEvents()
        return panel

    def record_hud(self, panel):
        calls = []
        original = panel._renderer.submit_hud

        def wrapper(item):
            calls.append(item)
            return original(item)

        panel._renderer.submit_hud = wrapper
        return calls

    def test_viewport_set_screen_mode_renders_without_defaults(self):
        panel = self.make_viewport()
        session = self.make_session()
        panel.set_screen_mode(session, {})
        calls = self.record_hud(panel)
        panel.render_frame()   # E-37: no raise
        self.assertTrue(any(
            isinstance(c, HudText) and "Refresh Layouts" in c.text for c in calls))

    def test_viewport_set_screen_mode_renders_with_defaults(self):
        panel = self.make_viewport()
        session = self.make_session()
        panel.set_screen_mode(session, FIXTURE_DEFAULTS)
        calls = self.record_hud(panel)
        panel.render_frame()
        rects = [c for c in calls if isinstance(c, HudRect)]
        texts = [c for c in calls if isinstance(c, HudText)]
        self.assertEqual(len(rects), 4)    # 2 unskinned buttons × (fill+border)
        self.assertEqual(len(texts), 3)    # START, SETTINGS, MAIN MENU

    def test_viewport_click_selects_topmost_widget(self):
        panel = self.make_viewport()
        session = self.make_session()
        panel.set_screen_mode(session, FIXTURE_DEFAULTS)
        QTest.mouseClick(panel, Qt.MouseButton.LeftButton, pos=QPoint(840, 140))
        self.assertEqual(panel._selected_widget, "title")
        calls = self.record_hud(panel)
        panel.render_frame()
        self.assertTrue(any(isinstance(c, HudLines) for c in calls))

    def test_viewport_drag_move_commits_undo_command(self):
        panel = self.make_viewport()
        session = self.make_session()
        panel.set_screen_mode(session, FIXTURE_DEFAULTS)
        before = session.undo_stack.count()
        start, end = QPoint(700, 380), QPoint(730, 380)
        QTest.mousePress(panel, Qt.MouseButton.LeftButton, pos=start)
        QTest.mouseMove(panel, end)
        QTest.mouseRelease(panel, Qt.MouseButton.LeftButton, pos=end)
        self.assertEqual(session.undo_stack.count(), before + 1)
        self.assertEqual(
            session.doc["widgets"]["btn_new_game"]["rect"], [670, 360, 120, 40])

    def test_viewport_arrow_key_nudges_selected_widget(self):
        panel = self.make_viewport()
        session = self.make_session()
        panel.set_screen_mode(session, FIXTURE_DEFAULTS)
        QTest.mouseClick(panel, Qt.MouseButton.LeftButton, pos=QPoint(700, 380))
        self.assertEqual(panel._selected_widget, "btn_new_game")
        before = session.undo_stack.count()
        QTest.keyClick(panel, Qt.Key.Key_Left)
        self.assertEqual(
            session.doc["widgets"]["btn_new_game"]["rect"], [639, 360, 120, 40])
        self.assertEqual(session.undo_stack.count(), before + 1)

    def test_viewport_state_dropdown_drives_anim_row(self):
        panel = self.make_viewport()
        session = self.make_session()
        session.push_skin_assign("btn_new_game", None, "ui_button")
        panel.set_screen_mode(session, FIXTURE_DEFAULTS)
        self.assertEqual(panel._screen_state, "idle")
        self.assertEqual(
            [panel._state_combo.itemText(i) for i in range(panel._state_combo.count())],
            ["idle", "hover", "pressed", "disabled"])   # from the registry, not literals
        panel.set_screen_state("hover")
        calls = self.record_hud(panel)
        panel.render_frame()
        sprites = [c for c in calls if isinstance(c, HudSprite)]
        self.assertEqual(len(sprites), 1)
        self.assertEqual(sprites[0].animation, "hover")


class TestScreenDetailsPanel(TempDataCase):
    """B4 §1d: widget list + per-widget form + screen-level sections, every
    edit an IMMEDIATE undoable push_* (never staged)."""

    def make(self):
        panel = self.track(ScreenDetailsPanel(data_dir=self.data_dir))
        session = self.track(UIScreenSession(data_dir=self.data_dir))
        session.open("main_menu")
        panel.set_session(session, FIXTURE_DEFAULTS)
        return panel, session

    def test_screen_details_widget_list_mirrors_defaults(self):
        panel, session = self.make()
        items = [panel.widget_list.item(i).text()
                for i in range(panel.widget_list.count())]
        self.assertEqual(set(items), {"btn_new_game", "btn_settings", "title"})
        selected = []
        panel.widget_selected.connect(selected.append)
        panel.widget_list.setCurrentRow(items.index("title"))
        self.assertEqual(selected, ["title"])
        self.assertEqual(panel._current_widget, "title")

    def test_screen_details_rect_spinboxes_push_move_on_change(self):
        panel, session = self.make()
        panel._populate_widget_form("btn_new_game")
        panel.x_spin.setValue(700)
        panel.x_spin.editingFinished.emit()
        self.assertEqual(session.doc["widgets"]["btn_new_game"]["rect"][0], 700)
        self.assertEqual(session.undo_stack.count(), 1)
        session.undo_stack.undo()
        self.assertNotIn("btn_new_game", session.doc.get("widgets", {}))

    def test_screen_details_skin_combo_push_skin_assign_on_change(self):
        panel, session = self.make()
        panel._populate_widget_form("btn_new_game")
        idx = panel.skin_combo.findData("ui_button")
        self.assertGreaterEqual(idx, 0)
        panel.skin_combo.setCurrentIndex(idx)
        panel.skin_combo.activated.emit(idx)
        self.assertEqual(session.doc["widgets"]["btn_new_game"]["skin"], "ui_button")
        session.undo_stack.undo()
        self.assertNotIn("btn_new_game", session.doc.get("widgets", {}))

    def test_screen_details_reset_to_default_removes_override(self):
        """Per-field reset (brief §1d MEDIUM fix): resetting ONE key leaves
        every other override on the widget intact, and undo restores it."""
        panel, session = self.make()
        session.push_move("btn_new_game", None, [10, 10, 50, 20])
        session.push_field("btn_new_game", "label", None, "X")
        panel._populate_widget_form("btn_new_game")
        self.assertTrue(panel.rect_reset_button.isEnabled())
        self.assertTrue(panel.label_reset_button.isEnabled())

        panel._on_reset_field("rect")   # reset ONLY the rect key

        override = session.doc["widgets"]["btn_new_game"]
        self.assertNotIn("rect", override)          # cleared
        self.assertEqual(override["label"], "X")    # the OTHER key survives
        self.assertFalse(panel.rect_reset_button.isEnabled())
        self.assertTrue(panel.label_reset_button.isEnabled())

        session.undo_stack.undo()
        self.assertEqual(
            session.doc["widgets"]["btn_new_game"]["rect"], [10, 10, 50, 20])
        self.assertEqual(session.doc["widgets"]["btn_new_game"]["label"], "X")

    def test_screen_details_reset_all_clears_every_override(self):
        """"Reset ALL" (kept alongside per-field reset) still clears every
        override on the widget, popping the entry out of the doc entirely."""
        panel, session = self.make()
        session.push_move("btn_new_game", None, [10, 10, 50, 20])
        session.push_field("btn_new_game", "label", None, "X")
        panel._populate_widget_form("btn_new_game")
        panel._on_reset_clicked()
        self.assertNotIn("btn_new_game", session.doc.get("widgets", {}))

    def test_screen_details_background_picker_combo_push_background(self):
        panel, session = self.make()
        idx = panel.background_combo.findData("ui_bg_main_menu")
        self.assertGreaterEqual(idx, 0)
        panel.background_combo.setCurrentIndex(idx)
        panel.background_combo.activated.emit(idx)
        self.assertEqual(session.doc["background"], {"slot": "ui_bg_main_menu"})


class TestMainWindowScreenMode(TempDataCase):
    """B4 §1e: selector → _on_screen_selected → dirty check → session.open →
    viewport.set_screen_mode → right_stack switch (exactly like maps)."""

    def test_main_window_on_screen_selected_enters_screen_mode(self):
        window = self.track(MainWindow(data_dir=self.data_dir))
        window.selector.select_screen("main_menu")
        self.assertTrue(window.viewport.in_screen_mode())
        self.assertIs(window.right_stack.currentWidget(), window.screen_details)

    def test_main_window_resolve_dirty_prompts_before_switching_screens(self):
        window = self.track(MainWindow(data_dir=self.data_dir))
        window.selector.select_screen("main_menu")
        window.screen_session.push_field("title", "label", None, "NEW TITLE")
        self.assertTrue(window.screen_session.dirty)
        window.dirty_policy = "save"   # bypass the modal Save/Discard/Cancel
        window.selector.select_screen("pause")
        self.assertEqual(window.screen_session.screen_id, "pause")
        on_disk = data_io.load_validated(
            self.data_dir / "ui" / "screens" / "main_menu.json",
            self.data_dir / "schemas" / "ui_screen.schema.json")
        self.assertEqual(on_disk["widgets"]["title"]["label"], "NEW TITLE")


class TestPurity(unittest.TestCase):
    """Hard rule: editor/ never imports game/ (root CLAUDE.md layering rule)."""

    def test_editor_does_not_import_game(self):
        code = (
            "import sys; "
            "import editor.main, editor.domains, editor.selection, "
            "editor.tilemap_ops, editor.map_session, editor.asset_import, "
            "editor.registry_ops, editor.balancing_history, "
            "editor.run_controls, editor.spawnclaude, editor.theme, "
            "editor.keybinds, editor.settings_dialog, "
            "editor.agent_forms, editor.agent_form_dialog, editor.plans, "
            "editor.ui_screen_session, "
            "editor.panels.selector, editor.panels.balancing, "
            "editor.panels.viewport, editor.panels.details, "
            "editor.panels.level_bar, editor.panels.palette, "
            "editor.panels.map_details, editor.panels.sheet_preview, "
            "editor.panels.sheet_picker, editor.panels.screen_details, "
            "editor.panels._screen_primitives, editor.thats_my_producer; "
            "assert not any(m == 'game' or m.startswith('game.') for m in sys.modules), "
            "'editor imported game/'"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
