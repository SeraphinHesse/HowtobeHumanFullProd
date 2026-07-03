"""E-38 migration: prototype sprite_manifest.json (v1) + imported/ PNGs →
manifest v2 + copied sheets. Pure fixture-driven — these tests never touch
the real prototype repo; the one real run happens during Phase 5
verification and its output is committed.
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from engine import data_io
from tools.migrate_prototype_assets import migrate_manifest, run

REPO = Path(__file__).resolve().parents[2]

V1_DOC = {
    "version": 1,
    "frame_w": 64,
    "frame_h": 96,
    "entries": {
        # mirrors the real v1 first entry: rides the top-level globals and
        # has no offset or loop fields
        "bare": {
            "sheet": "imported/bare.png",
            "rows": [
                {"animation": "idle", "frames": 11, "fps": 12, "hidden": []},
                {"animation": "attack", "frames": 11, "fps": 6,
                 "hidden": [3, 4, 5]},
            ],
        },
        # fully-specified entry
        "full": {
            "sheet": "imported/full.png",
            "frame_w": 64, "frame_h": 96,
            "offset_x": 0, "offset_y": 8,
            "rows": [
                {"animation": "idle", "frames": 10, "fps": 8,
                 "hidden": [0, 1], "loop_start": 0, "loop_end": 0,
                 "loop_count": 1},
                {"animation": "attack", "frames": 10, "fps": 6,
                 "hidden": [3], "loop_start": 1, "loop_end": 2,
                 "loop_count": 3},
            ],
        },
        # sheet PNG will be missing -> entry must be skipped
        "orphan": {
            "sheet": "imported/orphan.png",
            "rows": [{"animation": "idle", "frames": 2, "fps": 8,
                      "hidden": []}],
        },
    },
}


class TestMigrateManifestPure(unittest.TestCase):
    def test_defaults_filled_from_globals(self):
        v2 = migrate_manifest(V1_DOC)
        bare = v2["entries"]["bare"]
        self.assertEqual(v2["version"], 2)
        self.assertEqual((bare["frame_w"], bare["frame_h"]), (64, 96))
        self.assertEqual((bare["offset_x"], bare["offset_y"]), (0, 0))
        row0 = bare["rows"][0]
        self.assertEqual(row0["animation"], "idle")
        self.assertEqual(row0["frames"], 11)
        self.assertEqual(row0["fps"], 12)
        self.assertEqual((row0["loop_start"], row0["loop_end"],
                          row0["loop_count"]), (0, 0, 1))

    def test_specified_values_preserved(self):
        full = migrate_manifest(V1_DOC)["entries"]["full"]
        self.assertEqual(full["offset_y"], 8)
        attack = full["rows"][1]
        self.assertEqual(attack["hidden"], [3])
        self.assertEqual((attack["loop_start"], attack["loop_end"],
                          attack["loop_count"]), (1, 2, 3))


class TestRun(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # synthetic prototype layout
        self.src = root / "proto"
        imported = self.src / "assets" / "sprites" / "imported"
        imported.mkdir(parents=True)
        (self.src / "assets" / "sprites" / "sprite_manifest.json").write_text(
            json.dumps(V1_DOC), encoding="utf-8")
        (imported / "bare.png").write_bytes(b"png-bytes-bare")
        (imported / "full.png").write_bytes(b"png-bytes-full")
        # dst = tempfile copy of the repo's data/ (real schema, empty manifest)
        self.dst = root / "data"
        shutil.copytree(REPO / "data", self.dst)
        self.manifest_path = self.dst / "sprites" / "asset_manifest.json"

    def test_output_validates_and_copies_sheets(self):
        copied = run(self.src, self.dst)
        self.assertEqual(sorted(copied), ["bare", "full"])
        doc = data_io.load_validated(
            self.manifest_path,
            self.dst / "schemas" / "asset_manifest.schema.json")
        self.assertEqual(sorted(doc["entries"]), ["bare", "full"])
        self.assertNotIn("orphan", doc["entries"])
        self.assertEqual(
            (self.dst / "sprites" / "imported" / "bare.png").read_bytes(),
            b"png-bytes-bare")

    def test_idempotent_rerun_is_byte_identical(self):
        run(self.src, self.dst)
        first = self.manifest_path.read_bytes()
        run(self.src, self.dst)
        self.assertEqual(self.manifest_path.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
