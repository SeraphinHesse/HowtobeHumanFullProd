"""editor.asset_import (Phase 6 follow-up) — the pure single-frame-
vocabulary import helper shared by the palette's "Import Spritesheet…"
button and the tile migration tool. No Qt, no pygame — plain Pillow +
engine.data_io, tested headlessly with a tempfile copy of data/.
"""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from editor.asset_import import (
    import_idle_sheet,
    imported_sheets,
    sheet_ref,
    sheet_users,
    unreferenced_sheets,
)
from engine import data_io
from engine.assets import load_registry
from tools.tests.test_editor_panels import TempDataCase


def make_png(path, w, h, colour=(80, 160, 80, 255)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (w, h), colour).save(path)
    return path


class AssetImportCase(TempDataCase):
    def setUp(self):
        super().setUp()
        self.registry = load_registry(self.data_dir)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.png_dir = Path(tmp.name)

    def manifest_doc(self):
        return data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")


class TestImportIdleSheet(AssetImportCase):
    def test_single_frame_sheet_writes_one_idle_row(self):
        src = make_png(self.png_dir / "tile.png", 64, 32)
        cols, rows = import_idle_sheet(
            self.data_dir, self.registry, "tile_buildable", src)
        self.assertEqual((cols, rows), (1, 1))
        copied = self.data_dir / "sprites" / "imported" / "tile_buildable.png"
        self.assertTrue(copied.exists())
        entry = self.manifest_doc()["entries"]["tile_buildable"]
        self.assertEqual(entry["sheet"], "imported/tile_buildable.png")
        self.assertEqual((entry["frame_w"], entry["frame_h"]), (64, 32))
        self.assertEqual(len(entry["rows"]), 1)
        self.assertEqual(entry["rows"][0]["animation"], "idle")
        self.assertEqual(entry["rows"][0]["frames"], 1)

    def test_multi_column_sheet_detects_frame_count(self):
        src = make_png(self.png_dir / "deco.png", 3 * 64, 96)
        cols, rows = import_idle_sheet(
            self.data_dir, self.registry, "deco_rock", src)
        self.assertEqual((cols, rows), (3, 1))
        entry = self.manifest_doc()["entries"]["deco_rock"]
        self.assertEqual(entry["rows"][0]["frames"], 3)

    def test_off_grid_sheet_crops_via_floor_division(self):
        # tile_bg_forest.png in the prototype is 72x36 vs the 64x32 tile
        # frame — still imports, one frame detected.
        src = make_png(self.png_dir / "forest.png", 72, 36)
        cols, rows = import_idle_sheet(
            self.data_dir, self.registry, "tile_forest", src)
        self.assertEqual((cols, rows), (1, 1))

    def test_sub_frame_art_is_padded_and_centred_not_rejected(self):
        """ED-40 (ER-1): undersized art imports — padded onto a transparent
        frame-sized canvas, centred, never upscaled."""
        src = make_png(self.png_dir / "tiny.png", 16, 16)
        cols, rows = import_idle_sheet(
            self.data_dir, self.registry, "enemy_stage_1_v1", src)
        self.assertEqual((cols, rows), (1, 1))
        copied = self.data_dir / "sprites" / "imported" / "enemy_stage_1_v1.png"
        with Image.open(copied) as image:
            self.assertEqual(image.size, (64, 96))       # one whole frame
            self.assertEqual(image.getbbox(), (24, 40, 40, 56))  # centred 16x16

    def test_padding_is_per_axis(self):
        """A wide short strip pads only vertically and keeps its columns."""
        src = make_png(self.png_dir / "strip.png", 128, 16)
        cols, rows = import_idle_sheet(
            self.data_dir, self.registry, "enemy_stage_1_v1", src)
        self.assertEqual((cols, rows), (2, 1))
        copied = self.data_dir / "sprites" / "imported" / "enemy_stage_1_v1.png"
        with Image.open(copied) as image:
            self.assertEqual(image.size, (128, 96))

    def test_big_enough_sheet_is_copied_byte_identically(self):
        """The shutil.copyfile path stays untouched — migrate_prototype_assets
        is idempotent only because an already-big-enough sheet is not re-encoded."""
        src = make_png(self.png_dir / "tile.png", 64, 32)
        import_idle_sheet(self.data_dir, self.registry, "tile_ocean", src)
        copied = self.data_dir / "sprites" / "imported" / "tile_ocean.png"
        self.assertEqual(copied.read_bytes(), src.read_bytes())

    def test_reimport_overwrites_existing_entry(self):
        src = make_png(self.png_dir / "a.png", 64, 32)
        import_idle_sheet(self.data_dir, self.registry, "tile_cliff", src)
        src2 = make_png(self.png_dir / "b.png", 2 * 64, 32)
        cols, _rows = import_idle_sheet(
            self.data_dir, self.registry, "tile_cliff", src2)
        self.assertEqual(cols, 2)
        self.assertEqual(
            self.manifest_doc()["entries"]["tile_cliff"]["rows"][0]["frames"], 2)

    def test_preserves_other_entries(self):
        src = make_png(self.png_dir / "a.png", 64, 32)
        import_idle_sheet(self.data_dir, self.registry, "tile_ocean", src)
        src2 = make_png(self.png_dir / "b.png", 64, 32)
        import_idle_sheet(self.data_dir, self.registry, "tile_cliff", src2)
        entries = self.manifest_doc()["entries"]
        self.assertIn("tile_ocean", entries)
        self.assertIn("tile_cliff", entries)


class TestSheetSharing(AssetImportCase):
    """The refcount behind "Use Spritesheet…" — a manifest entry's `sheet` is a
    real path the engine resolves as-is, so two slots may share ONE PNG and
    deleting art has to ask who else is using it first."""

    def link(self, slot_key, ref):
        """Point a slot's entry at `ref` without copying anything — what
        DetailsPanel.use_sheet does on Save."""
        doc = data_io.load_json(
            self.data_dir / "sprites" / "asset_manifest.json")
        doc["entries"][slot_key] = {
            "sheet": ref, "frame_w": 64, "frame_h": 96,
            "offset_x": 0, "offset_y": 0,
            "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                      "loop_start": 0, "loop_end": 0, "loop_count": 1}],
        }
        data_io.write_validated(
            doc, self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")

    def test_sheet_users_finds_every_slot_pointing_at_one_sheet(self):
        src = make_png(self.png_dir / "art.png", 64, 96)
        import_idle_sheet(self.data_dir, self.registry, "deco_rock", src)
        self.link("deco_rock_v2", sheet_ref("deco_rock"))
        doc = self.manifest_doc()
        self.assertEqual(sheet_users(doc, sheet_ref("deco_rock")),
                         ("deco_rock", "deco_rock_v2"))

    def test_sheet_users_is_empty_for_an_unreferenced_png(self):
        self.assertEqual(sheet_users(self.manifest_doc(), "imported/nope.png"),
                         ())

    def test_unreferenced_sheets_keeps_shared_art_and_collects_the_rest(self):
        src = make_png(self.png_dir / "art.png", 64, 96)
        import_idle_sheet(self.data_dir, self.registry, "deco_rock", src)
        self.link("deco_rock_v2", sheet_ref("deco_rock"))
        doc = self.manifest_doc()
        # deco_rock's own PNG is still used (by BOTH slots); a made-up one isn't.
        self.assertEqual(
            unreferenced_sheets(doc, [sheet_ref("deco_rock"),
                                      "imported/orphan.png"]),
            ("imported/orphan.png",))

    def test_unreferenced_sheets_dedupes_its_candidates(self):
        ref = "imported/gone.png"
        self.assertEqual(unreferenced_sheets(self.manifest_doc(), [ref, ref]),
                         (ref,))

    def test_imported_sheets_annotates_each_png_with_its_users(self):
        src = make_png(self.png_dir / "art.png", 3 * 64, 96)
        import_idle_sheet(self.data_dir, self.registry, "deco_rock", src)
        self.link("deco_rock_v2", sheet_ref("deco_rock"))
        found = {s.ref: s for s in imported_sheets(self.data_dir)}
        sheet = found[sheet_ref("deco_rock")]
        self.assertEqual((sheet.width, sheet.height), (192, 96))
        self.assertEqual(sheet.users, ("deco_rock", "deco_rock_v2"))
        self.assertEqual(sheet.grid(64, 96), (3, 1))
        self.assertTrue(sheet.fits(64, 96))

    def test_imported_sheets_lists_orphans_so_the_art_is_recoverable(self):
        """A PNG no entry references still shows in the picker — re-linking a
        slot away from art it owned must not make that art unreachable."""
        orphan = self.data_dir / "sprites" / "imported" / "zz_orphan.png"
        make_png(orphan, 64, 96)
        found = {s.ref: s for s in imported_sheets(self.data_dir)}
        self.assertIn("imported/zz_orphan.png", found)
        self.assertEqual(found["imported/zz_orphan.png"].users, ())

    def test_fits_rejects_a_sheet_that_does_not_divide_into_whole_frames(self):
        """The picker's default filter: a 64x32 tile sheet is not offered for a
        64x96 building slot (it still LINKS if you ask — it just re-slices)."""
        tile = self.data_dir / "sprites" / "imported" / "zz_tile.png"
        make_png(tile, 64, 32)
        sheet = {s.ref: s for s in imported_sheets(self.data_dir)}[
            "imported/zz_tile.png"]
        self.assertTrue(sheet.fits(64, 32))
        self.assertFalse(sheet.fits(64, 96))    # 32 < one 96px frame
        self.assertEqual(sheet.grid(64, 96), (1, 0))


if __name__ == "__main__":
    unittest.main()
