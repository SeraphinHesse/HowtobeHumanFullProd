"""Phase 9B: engine.video.VideoSource — graceful skip is the contract.

Missing file / absent cv2 / unopenable capture => disabled + done
immediately, no crash. When cv2 and the real cutscene are present the
enabled path yields pygame surfaces and releases cleanly.
"""
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

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
        # dt comfortably exceeds one source-fps frame interval (paced
        # playback -- see engine/video.py's module docstring) so a frame is
        # guaranteed to be due regardless of the clip's actual fps.
        vs.update(0.1)
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


class _FakeCapture:
    """Minimal cv2.VideoCapture stand-in: fixed fps, optionally a finite
    frame count (None = never runs out). No real cv2/video file needed, so
    these tests stay fast and don't depend on OpenCV being installed."""

    def __init__(self, fps, frame_count=None):
        self.fps = fps
        self._frame_count = frame_count
        self._n = 0

    def isOpened(self):
        return True

    def get(self, _prop):
        return self.fps

    def read(self):
        if self._frame_count is not None and self._n >= self._frame_count:
            return False, None
        self._n += 1
        return True, self._n

    def release(self):
        pass


def _fake_cv2(fps, frame_count=None):
    cap = _FakeCapture(fps, frame_count)
    module = types.SimpleNamespace(CAP_PROP_FPS=5,
                                    VideoCapture=lambda path: cap)
    return module, cap


class TestFakeCapturePacing(unittest.TestCase):
    """Pacing (E-12 speed fix) + the length-cap-is-no-longer-authoritative
    contract, exercised through a fake capture (see engine/CLAUDE.md)."""

    def test_paces_frames_by_source_fps_not_one_per_update(self):
        module, cap = _fake_cv2(fps=25.0)  # never runs out of frames
        with mock.patch.dict(sys.modules, {"cv2": module}):
            vs = VideoSource(__file__, length=None)
        self.assertEqual(vs._frame_interval, 1.0 / 25.0)
        for _ in range(60):  # 1 simulated second at a 60fps host
            vs.update(1.0 / 60.0)
        self.assertAlmostEqual(cap._n, 25, delta=1)  # ~25, not 60
        self.assertFalse(vs.done)
        vs.release()

    def test_length_shorter_than_true_duration_does_not_end_playback(self):
        module, cap = _fake_cv2(fps=25.0)  # never runs out of frames
        with mock.patch.dict(sys.modules, {"cv2": module}):
            vs = VideoSource(__file__, length=0.05)  # far short of reality
        vs.update(1.0)  # would have exceeded the old 0.05s length cap
        self.assertFalse(vs.done)
        vs.release()

    def test_eof_still_ends_playback(self):
        module, cap = _fake_cv2(fps=25.0, frame_count=3)
        with mock.patch.dict(sys.modules, {"cv2": module}):
            vs = VideoSource(__file__, length=None)
        for _ in range(10):
            vs.update(1.0 / 25.0)
        self.assertTrue(vs.done)


if __name__ == "__main__":
    unittest.main()
