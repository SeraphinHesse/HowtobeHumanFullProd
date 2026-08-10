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


class TestScreenPreviewExport(unittest.TestCase):
    """UT-2: the same staleness + determinism gates for the recorded draw
    list the editor's screen-mode preview replays."""

    def test_committed_previews_are_fresh(self):
        live_bytes = (REPO / "data" / "ui" / "screen_previews.json").read_bytes()
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            export_main(data_root=REPO / "data", output_dir=tmpdir)
            temp_bytes = (tmpdir / "ui" / "screen_previews.json").read_bytes()
        self.assertEqual(
            temp_bytes, live_bytes,
            "committed screen_previews.json is stale; run "
            "`py tools/export_ui_layouts.py`")

    def test_previews_are_deterministic(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            export_main(data_root=REPO / "data", output_dir=Path(a))
            export_main(data_root=REPO / "data", output_dir=Path(b))
            self.assertEqual(
                (Path(a) / "ui" / "screen_previews.json").read_bytes(),
                (Path(b) / "ui" / "screen_previews.json").read_bytes())

    def test_upgrade_view_records_the_real_stat_rows(self):
        """The motivating case: the editor must be able to show the Build/
        Upgrade panel as the player sees it, stat rows and all."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            export_main(data_root=REPO / "data", output_dir=Path(tmpdir))
            doc = json.loads(
                (Path(tmpdir) / "ui" / "screen_previews.json").read_text(
                    encoding="utf-8"))
        items = doc["building_panel"]["views"]["upgrade"]["items"]
        texts = [i["text"] for i in items if i["type"] == "text"]
        for expected in ("HP", "Damage", "Range"):
            self.assertIn(expected, texts)

    def test_overrides_move_the_recorded_widget(self):
        """`--overrides` is what lets the editor re-record an UNSAVED doc."""
        import json

        from tools import export_ui_layouts as export

        moved = {"main_menu": {"widgets": {"title": {"rect": [7, 9, 0, 0]}}}}
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "previews.json"
            view_w, view_h = export._logical_resolution(REPO / "data")
            export.write_previews(REPO / "data", Path(tmpdir), view_w, view_h,
                                  overrides=moved, output_path=out)
            doc = json.loads(out.read_text(encoding="utf-8"))
        positions = [tuple(i["pos"]) for i in doc["main_menu"]["items"]
                     if i["type"] == "text"]
        self.assertIn((7, 9), positions)


class TestHudItemRoundTrip(unittest.TestCase):
    """The JSON round-trip lives in `engine/render/hud.py` because BOTH the
    recorder (`tools/`) and the replay (`editor/`) need it and neither may
    import the other."""

    def test_every_primitive_round_trips(self):
        from engine.render import (
            HudLines, HudRect, HudSprite, HudText, hud_item_from_json,
            hud_item_to_json,
        )

        for item in (
            HudRect((1, 2, 3, 4), (5, 6, 7), border_radius=2, width=1),
            HudText("hi", (8, 9), "md", (1, 2, 3, 4), align="center"),
            HudSprite("ui_button", (1, 2), (3, 4), tint=(9, 9, 9),
                      flip=True, animation="hover", anim_time_ms=17),
            HudLines(((0, 0), (1, 1)), (2, 3, 4), width=3, closed=True),
        ):
            self.assertEqual(hud_item_from_json(hud_item_to_json(item)), item)


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
        "move_btn": "Move building button",
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
        """Coverage gate: every top-level ``building_panel`` widget id carries
        a ``display_name`` — the listed ones from ``_DISPLAY_NAMES``, and (UT-3)
        the ~40 stat/base-info row ids from the DERIVED rule, which reads a
        row's own resolved text so renaming a stat renames its widgets too."""
        widgets = self.defaults["building_panel"]["widgets"]
        self.assertTrue(
            set(self._BUILDING_PANEL_NAMES).issubset(set(widgets)))
        for widget_id, expected_name in self._BUILDING_PANEL_NAMES.items():
            self.assertEqual(
                widgets[widget_id].get("display_name"), expected_name,
                f"{widget_id!r} display_name mismatch")
        unnamed = [w for w, spec in widgets.items()
                   if not spec.get("display_name")]
        self.assertEqual(unnamed, [], "every widget needs a display name")

    def test_stat_rows_carry_derived_names_and_text_ids(self):
        """UT-3's motivating contract: each stat is TWO movable widgets, and
        each knows the string-table key it draws its text from."""
        widgets = self.defaults["building_panel"]["views"]["upgrade"]["widgets"]
        self.assertEqual(widgets["stat_hp_label"]["text_id"],
                         "building.stat.hp")
        self.assertEqual(widgets["stat_hp_label"]["display_name"], "HP label")
        self.assertEqual(widgets["stat_hp_value"]["text_id"],
                         "building.stat.value")
        self.assertEqual(widgets["stat_hp_value"]["display_name"], "HP value")
        # the two are independently placeable — different default anchors
        self.assertNotEqual(widgets["stat_hp_label"]["rect"],
                            widgets["stat_hp_value"]["rect"])

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
