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

    def test_lightning_btn_only_in_base_info(self):
        views = self.defaults["building_panel"]["views"]
        for name, view in views.items():
            if name == "base_info":
                self.assertIn("lightning_btn", view["widgets"])
            else:
                self.assertNotIn("lightning_btn", view["widgets"])

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


if __name__ == "__main__":
    unittest.main()
