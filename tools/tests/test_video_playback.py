"""VideoPlayback tests (E-12): timing cap, skip/finish, source-ended, and the
graceful-disable path. Pure Python — no cv2, no pygame."""
import unittest

from engine.video_playback import VideoPlayback


class TestTiming(unittest.TestCase):
    def test_advances_until_length_cap(self):
        vp = VideoPlayback(length=1.0)
        self.assertFalse(vp.done)
        self.assertFalse(vp.advance(0.4))
        self.assertFalse(vp.advance(0.4))
        self.assertAlmostEqual(vp.elapsed, 0.8)
        self.assertTrue(vp.advance(0.4))  # crosses the 1.0s cap
        self.assertTrue(vp.done)
        self.assertFalse(vp.active)

    def test_advance_is_noop_after_done(self):
        vp = VideoPlayback(length=1.0)
        vp.advance(2.0)
        self.assertTrue(vp.done)
        elapsed = vp.elapsed
        vp.advance(5.0)  # no further accumulation once done
        self.assertEqual(vp.elapsed, elapsed)

    def test_progress(self):
        vp = VideoPlayback(length=4.0)
        vp.advance(1.0)
        self.assertAlmostEqual(vp.progress, 0.25)
        vp.advance(10.0)
        self.assertAlmostEqual(vp.progress, 1.0)  # clamped to 1.0

    def test_no_length_cap_runs_open_ended(self):
        vp = VideoPlayback(length=None)
        self.assertFalse(vp.advance(100.0))
        self.assertFalse(vp.done)  # only skip / source-ended can end it
        self.assertEqual(vp.progress, 0.0)


class TestEndConditions(unittest.TestCase):
    def test_skip(self):
        vp = VideoPlayback(length=44.2)
        vp.skip()
        self.assertTrue(vp.done)
        self.assertFalse(vp.active)

    def test_finish(self):
        vp = VideoPlayback(length=44.2)
        vp.finish()
        self.assertTrue(vp.done)

    def test_source_ended_before_cap(self):
        vp = VideoPlayback(length=44.2)
        vp.advance(2.0)
        vp.mark_source_ended()  # decoder ran out early
        self.assertTrue(vp.done)


class TestGracefulDisable(unittest.TestCase):
    def test_disabled_starts_done(self):
        vp = VideoPlayback(length=44.2, enabled=False)
        self.assertTrue(vp.done)
        self.assertFalse(vp.active)
        self.assertTrue(vp.advance(1.0))  # stays done, no elapsed accrual
        self.assertEqual(vp.elapsed, 0.0)

    def test_enabled_is_active_until_done(self):
        vp = VideoPlayback(length=1.0, enabled=True)
        self.assertTrue(vp.active)
        vp.finish()
        self.assertFalse(vp.active)


if __name__ == "__main__":
    unittest.main()
