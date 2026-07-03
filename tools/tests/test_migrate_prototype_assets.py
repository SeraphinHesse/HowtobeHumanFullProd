"""tools/migrate_prototype_assets.py (E-38 + Phase 6 tile follow-up) —
entity migration untouched; the new migrate_tiles() bakes the prototype's
procedurally-tinted map tiles to static PNGs + manifest entries. Runs
against tempfile copies of both the prototype fixture tree (synthesized
here — the real prototype repo may not exist on CI) and data/, so nothing
touches either real tree.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PIL import Image

from engine import data_io
from tools.migrate_prototype_assets import (
    COMBAT_TINT,
    TILE_FILE_SLOTS,
    migrate_tiles,
)
from tools.tests.test_editor_panels import TempDataCase

REPO = Path(__file__).resolve().parents[2]


def _make_src_tiles(root):
    """A minimal fixture prototype tree: just the assets/sprites/tile_*.png
    files migrate_tiles reads, distinct solid colours per file so a
    combat-tint sanity check has something to compare against."""
    sprites = root / "assets" / "sprites"
    sprites.mkdir(parents=True)
    for filename in TILE_FILE_SLOTS:
        Image.new("RGBA", (64, 32), (60, 180, 60, 255)).save(sprites / filename)
    Image.new("RGBA", (64, 32), (60, 180, 60, 255)).save(sprites / "tile_grass.png")
    Image.new("RGBA", (64, 32), (60, 180, 60, 255)).save(sprites / "tile_grass_b.png")
    return root


class TestMigrateTiles(TempDataCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.src = _make_src_tiles(Path(tmp.name) / "prototype")

    def manifest_doc(self):
        return data_io.load_validated(
            self.data_dir / "sprites" / "asset_manifest.json",
            self.data_dir / "schemas" / "asset_manifest.schema.json")

    def test_all_nine_tile_slots_migrated(self):
        migrated = migrate_tiles(self.src, self.data_dir)
        expected = set(TILE_FILE_SLOTS.values()) | {
            "tile_combat", "tile_combat_b"}
        self.assertEqual(set(migrated), expected)
        entries = self.manifest_doc()["entries"]
        for slot in expected:
            self.assertIn(slot, entries)
            self.assertEqual(entries[slot]["rows"][0]["animation"], "idle")
            imported = self.data_dir / "sprites" / "imported" / f"{slot}.png"
            self.assertTrue(imported.exists())

    def test_combat_tiles_are_tinted_not_a_raw_copy(self):
        migrate_tiles(self.src, self.data_dir)
        source = Image.open(self.src / "assets" / "sprites" / "tile_grass.png")
        tinted = Image.open(
            self.data_dir / "sprites" / "imported" / "tile_combat.png")
        self.assertNotEqual(source.getpixel((0, 0))[:3],
                            tinted.getpixel((0, 0))[:3])
        # roughly in the tint's direction (muted, greenish-dark)
        tr, tg, tb = tinted.getpixel((0, 0))[:3]
        self.assertLessEqual(tr, COMBAT_TINT[0] + 5)
        self.assertLessEqual(tg, 255)
        self.assertLessEqual(tb, COMBAT_TINT[2] + 5)

    def test_rerun_is_idempotent(self):
        migrate_tiles(self.src, self.data_dir)
        first = self.manifest_doc()
        migrate_tiles(self.src, self.data_dir)
        second = self.manifest_doc()
        self.assertEqual(first, second)

    def test_missing_source_file_skips_with_warning(self):
        # data/'s manifest may already carry a real tile_cliff entry from a
        # prior migration run — clear it so "skip" is observable either way.
        manifest_path = self.data_dir / "sprites" / "asset_manifest.json"
        doc = data_io.load_json(manifest_path)
        doc["entries"].pop("tile_cliff", None)
        data_io.write_validated(
            doc, manifest_path,
            self.data_dir / "schemas" / "asset_manifest.schema.json")

        (self.src / "assets" / "sprites" / "tile_bg_cliff.png").unlink()
        migrated = migrate_tiles(self.src, self.data_dir)
        self.assertNotIn("tile_cliff", migrated)
        self.assertNotIn("tile_cliff", self.manifest_doc()["entries"])


if __name__ == "__main__":
    unittest.main()
