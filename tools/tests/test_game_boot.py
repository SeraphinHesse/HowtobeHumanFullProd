"""E-37: a corrupt or missing asset manifest must never crash game boot —
the game logs and falls back to grey-X placeholders. Phase 6 adds the
OPPOSITE contract for MAP data (D-2/D-21): the game loads the active map
and fails LOUD on invalid map structure — tolerance is for art only.
Headless via SDL dummy drivers; runs against a tempfile copy of data/
(repo data never touched).
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import jsonschema  # noqa: E402

from engine import data_io, tilemap  # noqa: E402
from game.main import main as game_main  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


class TempDataBoot(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        self.manifest_path = self.data_dir / "sprites" / "asset_manifest.json"


class TestCorruptManifestBoot(TempDataBoot):
    def test_corrupt_manifest_boots_and_logs(self):
        self.manifest_path.write_text("{this is not json", encoding="utf-8")
        with self.assertLogs("engine.assets.manifest", level="WARNING"):
            frames = game_main(max_frames=2, data_dir=self.data_dir,
                               autostart=True)
        self.assertEqual(frames, 2)

    def test_missing_manifest_boots_clean(self):
        self.manifest_path.unlink()
        self.assertEqual(
            game_main(max_frames=2, data_dir=self.data_dir, autostart=True), 2)

    def test_default_data_dir_still_boots(self):
        # default shell path: real data has the cutscene -> boots in CUTSCENE.
        self.assertEqual(game_main(max_frames=1), 1)

    def test_shell_boots_to_menu_without_cutscene(self):
        # 9H: remove the video -> VideoSource disables -> boot lands on
        # MAIN_MENU and renders the null-world menu path headlessly.
        (self.data_dir / "video" / "cutscene.mp4").unlink()
        self.assertEqual(game_main(max_frames=2, data_dir=self.data_dir), 2)


class TestActiveMapBoot(TempDataBoot):
    """Phase 6 (D-20/D-21): the game renders the ACTIVE map's painted grid."""

    def test_boots_on_a_freshly_painted_map(self):
        doc = tilemap.new_doc("painted", "Painted", 10, 8,
                              tilemap.map_schema_path(self.data_dir))
        doc.terrain[2][3] = "s"
        doc.deco.append({"col": 5, "row": 5, "slot": "deco_tree"})
        tilemap.save_map(doc, tilemap.map_path(self.data_dir, "painted"),
                         tilemap.map_schema_path(self.data_dir))
        data_io.write_validated(
            {"active": "painted"},
            tilemap.active_map_path(self.data_dir),
            tilemap.active_map_schema_path(self.data_dir))
        self.assertEqual(
            game_main(max_frames=2, data_dir=self.data_dir, autostart=True), 2)

    def test_missing_active_pointer_fails_loud(self):
        tilemap.active_map_path(self.data_dir).unlink()
        with self.assertRaises(FileNotFoundError):
            game_main(max_frames=1, data_dir=self.data_dir)

    def _active_map_path(self):
        active = data_io.load_json(
            tilemap.active_map_path(self.data_dir))["active"]
        return tilemap.map_path(self.data_dir, active)

    def test_schema_invalid_map_fails_loud(self):
        path = self._active_map_path()
        doc = data_io.load_json(path)
        del doc["base"]
        path.write_text(data_io.dumps_deterministic(doc), encoding="utf-8")
        with self.assertRaises(jsonschema.ValidationError):
            game_main(max_frames=1, data_dir=self.data_dir)

    def test_dims_inconsistent_map_fails_loud(self):
        path = self._active_map_path()
        doc = data_io.load_json(path)
        doc["terrain"] = doc["terrain"][:-1]   # schema-valid, dims broken
        path.write_text(data_io.dumps_deterministic(doc), encoding="utf-8")
        with self.assertRaises(ValueError):
            game_main(max_frames=1, data_dir=self.data_dir)


if __name__ == "__main__":
    unittest.main()
