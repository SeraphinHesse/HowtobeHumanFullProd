"""tools/build.py's argv construction (T-4) — pure, no real PyInstaller run
(a real build is multi-minute with large output; that's a live-only step,
see PLAN.md phase 7)."""
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools.build import build_command


class TestBuildCommand(unittest.TestCase):
    def test_uses_module_invocation(self):
        cmd = build_command(repo=REPO)
        self.assertEqual(cmd[:3], [sys.executable, "-m", "PyInstaller"])

    def test_entry_point_is_game_main(self):
        cmd = build_command(repo=REPO)
        self.assertIn(str(REPO / "game" / "main.py"), cmd)

    def test_name_is_howtobehuman(self):
        cmd = build_command(repo=REPO)
        self.assertIn("--name", cmd)
        self.assertEqual(cmd[cmd.index("--name") + 1], "HowToBeHuman")

    def test_onedir_and_noconfirm(self):
        cmd = build_command(repo=REPO)
        self.assertIn("--onedir", cmd)
        self.assertIn("--noconfirm", cmd)

    def test_add_data_uses_os_pathsep(self):
        cmd = build_command(data_dir=Path("D"), repo=REPO)
        self.assertIn("--add-data", cmd)
        value = cmd[cmd.index("--add-data") + 1]
        self.assertEqual(value, f"D{os.pathsep}data")

    def test_distpath_defaults_under_repo(self):
        cmd = build_command(repo=REPO)
        self.assertIn("--distpath", cmd)
        self.assertEqual(cmd[cmd.index("--distpath") + 1], str(REPO / "dist"))

    def test_custom_dist_dir(self):
        cmd = build_command(dist_dir=Path("X"), repo=REPO)
        self.assertEqual(cmd[cmd.index("--distpath") + 1], "X")

    def test_bundles_cv2_for_cutscene(self):
        # OpenCV (engine/video.py) is bundled so the frozen exe can play the
        # cutscene; without these flags PyInstaller misses the lazy import.
        cmd = build_command(repo=REPO)
        self.assertIn("--collect-all", cmd)
        self.assertEqual(cmd[cmd.index("--collect-all") + 1], "cv2")
        self.assertIn("--hidden-import", cmd)
        self.assertEqual(cmd[cmd.index("--hidden-import") + 1], "cv2")


if __name__ == "__main__":
    unittest.main()
