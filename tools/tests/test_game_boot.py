"""E-37: a corrupt or missing asset manifest must never crash game boot —
the game logs and falls back to grey-X placeholders. Headless via SDL dummy
drivers; runs against a tempfile copy of data/ (repo data never touched).
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

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
            frames = game_main(max_frames=2, data_dir=self.data_dir)
        self.assertEqual(frames, 2)

    def test_missing_manifest_boots_clean(self):
        self.manifest_path.unlink()
        self.assertEqual(game_main(max_frames=2, data_dir=self.data_dir), 2)

    def test_default_data_dir_still_boots(self):
        self.assertEqual(game_main(max_frames=1), 1)


if __name__ == "__main__":
    unittest.main()
