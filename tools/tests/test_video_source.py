"""Phase 9B: engine.video.VideoSource — graceful skip is the contract.

Missing file / absent cv2 / unopenable capture => disabled + done
immediately, no crash. When cv2 and the real cutscene are present the
enabled path yields pygame surfaces and releases cleanly.
"""
import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.video import VideoSource

REPO = Path(__file__).resolve().parents[2]
CUTSCENE = REPO / "data" / "video" / "cutscene.mp4"


def _has_cv2():
    try:
        import cv2  # noqa: F401
        return True
    except ImportError:
        return False


class TestGracefulSkip(unittest.TestCase):
    def test_missing_file_done_immediately(self):
        vs = VideoSource(REPO / "no_such_video.mp4", length=44.2)
        self.assertFalse(vs.enabled)
        self.assertTrue(vs.done)

    def test_missing_file_update_and_frame_no_crash(self):
        vs = VideoSource(REPO / "no_such_video.mp4", length=44.2)
        vs.update(0.016)  # no-op, must not raise
        self.assertIsNone(vs.frame_surface())
        vs.skip()
        vs.release()  # idempotent
        self.assertTrue(vs.done)

    def test_empty_path_done(self):
        vs = VideoSource("", length=44.2)
        self.assertTrue(vs.done)
        self.assertFalse(vs.enabled)


@unittest.skipUnless(_has_cv2() and CUTSCENE.exists(),
                     "cv2 and data/video/cutscene.mp4 required")
class TestEnabledPlayback(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def test_opens_and_reads_frames(self):
        vs = VideoSource(CUTSCENE, length=44.2, target_size=(64, 48))
        self.assertTrue(vs.enabled)
        self.assertFalse(vs.done)
        vs.update(0.033)
        surf = vs.frame_surface()
        self.assertIsInstance(surf, pygame.Surface)
        self.assertEqual(surf.get_size(), (64, 48))
        vs.release()

    def test_skip_marks_done(self):
        vs = VideoSource(CUTSCENE, length=44.2)
        vs.update(0.033)
        vs.skip()
        self.assertTrue(vs.done)
        vs.update(0.033)  # further updates are inert
        vs.release()

    def test_length_cap_ends_playback(self):
        vs = VideoSource(CUTSCENE, length=0.05)
        vs.update(1.0)  # exceeds the 0.05 s cap
        self.assertTrue(vs.done)
        vs.release()


if __name__ == "__main__":
    unittest.main()
