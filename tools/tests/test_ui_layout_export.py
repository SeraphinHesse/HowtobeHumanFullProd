"""Staleness gate for the committed ``data/ui/screen_defaults.json`` (Phase
10L-B, B3).

``test_committed_defaults_are_fresh`` regenerates the file into a tempdir and
asserts it matches the committed version byte-for-byte — a screen whose
DEFAULT geometry changed without re-running ``tools/export_ui_layouts.py``
fails the suite. ``test_export_is_deterministic`` pins §1.5 directly: two
independent regenerations (no data changes between them) must be
byte-identical to EACH OTHER, not just to the committed file.

Headless: the exporter sets its own SDL dummy drivers before any pygame-pulling
import, so nothing here needs to.
"""
import tempfile
import unittest
from pathlib import Path

from tools.export_ui_layouts import main as export_main

REPO = Path(__file__).resolve().parents[2]


class TestUILayoutExportStaleness(unittest.TestCase):
    def test_committed_defaults_are_fresh(self):
        """Regenerate screen_defaults.json in a tempdir and assert it matches
        the committed version byte-for-byte."""
        live_path = REPO / "data" / "ui" / "screen_defaults.json"
        live_bytes = live_path.read_bytes()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            export_main(data_root=REPO / "data", output_dir=tmpdir)
            temp_path = tmpdir / "ui" / "screen_defaults.json"
            temp_bytes = temp_path.read_bytes()

        self.assertEqual(
            temp_bytes, live_bytes,
            "committed screen_defaults.json is stale; run "
            "`py tools/export_ui_layouts.py`")

    def test_export_is_deterministic(self):
        """Two independent regenerations (no data changes between them) are
        byte-identical (§1.5) — pinned directly, rather than only via the
        committed file's staleness."""
        with tempfile.TemporaryDirectory() as tmpdir_a, \
                tempfile.TemporaryDirectory() as tmpdir_b:
            tmpdir_a, tmpdir_b = Path(tmpdir_a), Path(tmpdir_b)
            export_main(data_root=REPO / "data", output_dir=tmpdir_a)
            export_main(data_root=REPO / "data", output_dir=tmpdir_b)
            bytes_a = (tmpdir_a / "ui" / "screen_defaults.json").read_bytes()
            bytes_b = (tmpdir_b / "ui" / "screen_defaults.json").read_bytes()

        self.assertEqual(bytes_a, bytes_b)


class TestBuildingPanelViews(unittest.TestCase):
    """UH-1: ``building_panel`` gains a five-key ``views`` object mirroring
    the game's mode dispatch (building_ui.py hover/click branches). Regenerate
    into a tempdir every time — never assert against live ``data/`` content
    (the house rule; a fixture pin would go stale the moment a mock changes)."""

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            export_main(data_root=REPO / "data", output_dir=tmpdir)
            import json
            cls.defaults = json.loads(
                (tmpdir / "ui" / "screen_defaults.json").read_text(
                    encoding="utf-8"))

    def test_five_view_keys(self):
        views = self.defaults["building_panel"]["views"]
        self.assertEqual(
            set(views.keys()),
            {"unlock", "construct", "upgrade", "base_info", "preview"})

    def test_action_btn_differs_between_unlock_and_upgrade(self):
        views = self.defaults["building_panel"]["views"]
        unlock_rect = views["unlock"]["widgets"]["action_btn"]["rect"]
        upgrade_rect = views["upgrade"]["widgets"]["action_btn"]["rect"]
        self.assertIn("action_btn", views["unlock"]["widgets"])
        self.assertIn("action_btn", views["upgrade"]["widgets"])
        self.assertNotEqual(unlock_rect, upgrade_rect)

    def test_rename_dice_btn_only_in_upgrade(self):
        views = self.defaults["building_panel"]["views"]
        for name, view in views.items():
            if name == "upgrade":
                self.assertIn("rename_dice_btn", view["widgets"])
            else:
                self.assertNotIn("rename_dice_btn", view["widgets"])

    def test_preview_ids_only_in_preview(self):
        views = self.defaults["building_panel"]["views"]
        for name, view in views.items():
            preview_ids = [k for k in view["widgets"] if k.startswith("preview_")]
            if name == "preview":
                self.assertTrue(preview_ids)
            else:
                self.assertEqual(preview_ids, [])

    def test_panel_and_close_btn_in_four_panel_views(self):
        views = self.defaults["building_panel"]["views"]
        for name in ("unlock", "construct", "upgrade", "base_info"):
            self.assertIn("panel", views[name]["widgets"])
            self.assertIn("close_btn", views[name]["widgets"])

    def test_top_level_widgets_is_union_of_view_keysets(self):
        bp = self.defaults["building_panel"]
        expected = set()
        for view in bp["views"].values():
            expected |= set(view["widgets"].keys())
        self.assertEqual(set(bp["widgets"].keys()), expected)

    def test_no_other_screen_carries_views(self):
        for screen_id, entry in self.defaults.items():
            if screen_id == "building_panel":
                continue
            self.assertNotIn(
                "views", entry,
                f"{screen_id!r} unexpectedly carries a 'views' key")


class TestWidgetDisplayNames(unittest.TestCase):
    """UH-4: an OPTIONAL cosmetic ``display_name`` per widget (D4 — the code
    id stays the on-disk contract everywhere). Regenerate into a tempdir every
    time — never assert against live ``data/`` content."""

    _BUILDING_PANEL_NAMES = {
        "panel": "Building panel",
        "close_btn": "Close button",
        "action_btn": "Unlock / Build / Upgrade button",
        "boss_btn": "Boss history button",
        "boss_close_btn": "Boss history close button",
        "rename_dice_btn": "Rename dice button",
        "preview_panel": "Construct preview window",
        "preview_confirm_btn": "Construct confirm button",
        "preview_cancel_btn": "Construct cancel button",
        "preview_close_btn": "Construct preview close button",
        "preview_dice_btn": "Construct preview dice button",
    }

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            export_main(data_root=REPO / "data", output_dir=tmpdir)
            import json
            cls.defaults = json.loads(
                (tmpdir / "ui" / "screen_defaults.json").read_text(
                    encoding="utf-8"))

    def test_building_panel_top_level_fully_mapped(self):
        """Full coverage gate (orchestrator ruling #2): every top-level
        ``building_panel`` widget id carries the mapped ``display_name``."""
        widgets = self.defaults["building_panel"]["widgets"]
        self.assertEqual(set(widgets.keys()),
                         set(self._BUILDING_PANEL_NAMES.keys()))
        for widget_id, expected_name in self._BUILDING_PANEL_NAMES.items():
            self.assertEqual(
                widgets[widget_id].get("display_name"), expected_name,
                f"{widget_id!r} display_name mismatch")

    def test_action_btn_spot_check(self):
        widgets = self.defaults["building_panel"]["widgets"]
        self.assertEqual(
            widgets["action_btn"]["display_name"],
            "Unlock / Build / Upgrade button")

    def test_building_panel_views_carry_display_names_too(self):
        """R1: the post-pass walks EVERY ``widgets`` mapping — the flat top
        level AND inside each per-mode view — so a widget id shared across
        modes (e.g. panel/close_btn) carries the SAME name in every view
        (D2's "override ids stay global to the screen")."""
        views = self.defaults["building_panel"]["views"]
        for view in views.values():
            for widget_id, spec in view["widgets"].items():
                expected = self._BUILDING_PANEL_NAMES.get(widget_id)
                if expected is not None:
                    self.assertEqual(spec.get("display_name"), expected)

    def test_unmapped_id_carries_no_display_name_key(self):
        """An id absent from ``_DISPLAY_NAMES`` gets NO ``display_name`` key
        at all (the file stays minimal; fallback is the reader's job) — hud's
        second-pass readouts (``love_text``, ``lvl_label``, ...) are real,
        always-present ids that are NOT in ``_DISPLAY_NAMES["hud"]``."""
        hud_widgets = self.defaults["hud"]["widgets"]
        self.assertIn("love_text", hud_widgets)
        self.assertNotIn("display_name", hud_widgets["love_text"])


if __name__ == "__main__":
    unittest.main()
