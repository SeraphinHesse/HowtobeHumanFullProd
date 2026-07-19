"""Phase 10L wave 3 ("bake UI assets"): ``tools/bake_ui_sheets.py``.

Runs the baker into a tempdir COPY of ``data/`` (never live ``data/`` — the
``TempDataCase`` pattern, ``tools/tests/test_editor_panels.py``): asserts the
merged manifest validates against its schema, every expected ``ui_*`` slot
has an entry, the baked PNGs exist at the right sheet dimensions (64 wide x
64*rows tall; ``ui_bg_main_menu`` is the one 480x270 shared-sheet exception
and writes NO new PNG of its own), and a second run is byte-identical to the
first (idempotency, mirrors ``test_ui_layout_export.py``'s determinism pin).

Headless: the baker sets its own SDL dummy drivers before any pygame-pulling
import, so nothing here needs to.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from engine import data_io
from tools.bake_ui_sheets import bake

REPO = Path(__file__).resolve().parents[2]

# slot -> number of animation rows baked (drives the expected sheet height).
# Wave-3 Fix 2 (USER DECISION): one slot PER BUTTON TYPE, each owning its own
# PNG (no shared ``sheet`` path between button types) — plus ``ui_choice_box``,
# the 8th Buttons-family leaf, which bakes the ui_panel_stone idle+hover look.
_EXPECTED_ROWS = {
    "ui_button": 4,
    "ui_button_end_turn": 4,
    "ui_button_pause": 4,
    "ui_button_panel": 4,
    "ui_button_card": 4,
    "ui_button_cheat": 4,
    "ui_button_pill": 4,
    "ui_choice_box": 2,
    "ui_panel": 1,
    "ui_panel_stone": 2,
    "ui_icon_love": 1,
    "ui_icon_xp": 1,
    "ui_icon_lives": 1,
}
_BUTTON_TYPE_SLOTS = (
    "ui_button", "ui_button_end_turn", "ui_button_pause", "ui_button_panel",
    "ui_button_card", "ui_button_cheat", "ui_button_pill",
)
_FRAME = 64


class TestBakeUISheets(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        history_dir = self.data_dir / "balancing_history"
        if history_dir.exists():
            shutil.rmtree(history_dir)

    def _manifest(self):
        return data_io.load_json(
            self.data_dir / "sprites" / "asset_manifest.json")

    def test_manifest_validates_and_covers_every_slot(self):
        written = bake(self.data_dir)

        expected_slots = set(_EXPECTED_ROWS) | {"ui_bg_main_menu"}
        self.assertEqual(set(written), expected_slots)

        doc = data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")
        for slot in expected_slots:
            self.assertIn(slot, doc["entries"], f"missing manifest entry: {slot}")
            self.assertEqual(doc["entries"][slot]["rows"][0]["animation"], "idle")

    def test_ui_bg_main_menu_points_at_shared_sheet_no_copy(self):
        bake(self.data_dir)
        entry = self._manifest()["entries"]["ui_bg_main_menu"]
        self.assertEqual(entry["sheet"], "imported/main_menu_bg.png")
        self.assertEqual((entry["frame_w"], entry["frame_h"]), (480, 270))
        self.assertNotIn("slice", entry)
        # No byte owned by this slot — it must not have written its own PNG.
        self.assertFalse(
            (self.data_dir / "sprites" / "imported" / "ui_bg_main_menu.png")
            .exists())

    def test_buttons_and_panels_carry_slice_icons_do_not(self):
        bake(self.data_dir)
        entries = self._manifest()["entries"]
        for slot in (*_BUTTON_TYPE_SLOTS, "ui_choice_box", "ui_panel",
                     "ui_panel_stone"):
            self.assertEqual(entries[slot].get("slice"), [4, 4, 4, 4], slot)
        for slot in ("ui_icon_love", "ui_icon_xp", "ui_icon_lives"):
            self.assertNotIn("slice", entries[slot], slot)

    def test_each_button_type_owns_its_own_sheet_no_sharing(self):
        """USER DECISION: 8 leaf slots (7 button types + ui_choice_box), each
        with its OWN ``sheet`` path — no two button types point at the same
        PNG, even though they currently bake identical pixels."""
        bake(self.data_dir)
        entries = self._manifest()["entries"]
        button_family = (*_BUTTON_TYPE_SLOTS, "ui_choice_box")
        sheets = [entries[slot]["sheet"] for slot in button_family]
        self.assertEqual(len(sheets), len(set(sheets)),
                          "two button-family slots share a sheet path")
        for slot in button_family:
            self.assertEqual(entries[slot]["sheet"], f"imported/{slot}.png")
            self.assertTrue(
                (self.data_dir / "sprites" / "imported" / f"{slot}.png")
                .is_file(), f"missing own PNG for {slot}")

    def test_png_dimensions_match_frame_and_row_count(self):
        bake(self.data_dir)
        imported = self.data_dir / "sprites" / "imported"
        for slot, rows in _EXPECTED_ROWS.items():
            path = imported / f"{slot}.png"
            self.assertTrue(path.is_file(), f"missing PNG: {slot}")
            with Image.open(path) as image:
                self.assertEqual(image.size, (_FRAME, _FRAME * rows), slot)

    def test_idempotent_second_run_is_byte_identical(self):
        bake(self.data_dir)
        imported = self.data_dir / "sprites" / "imported"
        before = {
            slot: (imported / f"{slot}.png").read_bytes()
            for slot in _EXPECTED_ROWS
        }
        manifest_before = (
            self.data_dir / "sprites" / "asset_manifest.json").read_bytes()

        bake(self.data_dir)

        for slot, data in before.items():
            self.assertEqual(
                (imported / f"{slot}.png").read_bytes(), data,
                f"{slot}.png changed on re-run")
        manifest_after = (
            self.data_dir / "sprites" / "asset_manifest.json").read_bytes()
        self.assertEqual(manifest_after, manifest_before)

    def test_preserves_existing_non_ui_manifest_entries(self):
        doc_before = self._manifest()
        non_ui_count_before = sum(
            1 for k in doc_before["entries"] if not k.startswith("ui_"))

        bake(self.data_dir)

        doc_after = self._manifest()
        non_ui_count_after = sum(
            1 for k in doc_after["entries"] if not k.startswith("ui_"))
        self.assertEqual(non_ui_count_before, non_ui_count_after)
        # A pre-existing, unrelated entry (main_menu_bg, 10K art) survives
        # untouched — the ui_bg_main_menu entry shares its sheet, never its
        # bytes or its own manifest row.
        self.assertIn("main_menu_bg", doc_after["entries"])
        self.assertEqual(
            doc_after["entries"]["main_menu_bg"],
            doc_before["entries"]["main_menu_bg"])


if __name__ == "__main__":
    unittest.main()
