"""editor.asset_import (Phase 6 follow-up) — the pure single-frame-
vocabulary import helper shared by the palette's "Import Spritesheet…"
button and the tile migration tool. No Qt, no pygame — plain Pillow +
engine.data_io, tested headlessly with a tempfile copy of data/.
"""
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from editor.asset_import import import_idle_sheet
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


if __name__ == "__main__":
    unittest.main()
