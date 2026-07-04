"""OpenCV video frame source (prototype src/cutscene.py), Phase 9B.

Reads a video one frame at a time and hands pygame surfaces to the host so
the game can play the opening cutscene. GRACEFUL SKIP is the whole point: if
cv2 is not installed, the file is missing, or the capture won't open, the
source is `disabled` and reports `done` immediately — never a crash, never a
hang, headless-safe under SDL dummy.

Timing (elapsed vs length, source-ended) is delegated to the pure
`engine.video_playback` clock (the parallel 9B half) so the state machine is
unit-testable without cv2. If that module is absent this composes an
equivalent in-file fallback clock, so the source works standalone too.

pygame is allowed here (like the render backend / asset store / audio) —
surfarray.make_surface is the only pygame touch; cv2 is imported lazily so
importing this module never requires OpenCV.
"""
import os

import pygame

CUTSCENE_LENGTH = 44.2  # prototype cutscene.py — seconds (the game passes this)


class _FallbackClock:
    """Stand-in for engine.video_playback's clock, matching its contract:
    elapsed / length / enabled / done + advance / skip / finish /
    mark_source_ended. Used only when the pure half is not present."""

    def __init__(self, length):
        self.length = length
        self.elapsed = 0.0
        self.enabled = False
        self.done = False

    def advance(self, dt):
        if self.done or not self.enabled:
            return
        self.elapsed += dt
        if self.length is not None and self.elapsed >= self.length:
            self.done = True

    def skip(self):
        self.done = True

    def finish(self):
        self.done = True

    def mark_source_ended(self):
        self.done = True


def _make_clock(length):
    """Compose the pure timing clock; fall back to the in-file equivalent."""
    try:
        from engine.video_playback import VideoPlayback  # cross-half symbol
    except Exception:
        return _FallbackClock(length)
    try:
        return VideoPlayback(length)
    except Exception:
        return _FallbackClock(length)


class VideoSource:
    def __init__(self, path, length, target_size=None):
        self.enabled = False
        self.done = False
        self._path = path
        self._target_size = target_size
        self._cv2 = None
        self._cap = None
        self._bgr = None  # last raw frame read (BGR ndarray), or None
        self._clock = _make_clock(length)

        try:
            import cv2
        except ImportError:
            cv2 = None

        norm = os.path.normpath(str(path)) if path else ""
        if cv2 is not None and norm and os.path.exists(norm):
            cap = cv2.VideoCapture(norm)
            if cap.isOpened():
                self._cv2 = cv2
                self._cap = cap
                self.enabled = True
                self._set_clock_enabled(True)
            else:
                cap.release()

        if not self.enabled:
            self.done = True  # graceful skip
            self._finish_clock()

    # -- clock plumbing (tolerant of the exact cross-half API) --------------

    def _set_clock_enabled(self, value):
        try:
            self._clock.enabled = value
        except Exception:
            pass

    def _finish_clock(self):
        for name in ("finish", "skip"):
            fn = getattr(self._clock, name, None)
            if fn is not None:
                try:
                    fn()
                except Exception:
                    pass
                return

    @property
    def elapsed(self):
        return getattr(self._clock, "elapsed", 0.0)

    # -- playback ----------------------------------------------------------

    def update(self, dt):
        """Advance the clock and read the next frame. Marks `done` at the
        length cap or when the stream ends; never raises."""
        if self.done or not self.enabled:
            return
        self._clock.advance(dt)
        if getattr(self._clock, "done", False):
            self.done = True
            self.release()
            return
        ret, bgr = self._cap.read()
        if not ret:
            try:
                self._clock.mark_source_ended()
            except Exception:
                pass
            self.done = True
            self._bgr = None
            self.release()
            return
        self._bgr = bgr

    def frame_surface(self):
        """Convert the last-read frame to a pygame Surface (BGR→RGB, optional
        resize to target_size). None if no frame has been read."""
        if self._bgr is None or self._cv2 is None:
            return None
        rgb = self._cv2.cvtColor(self._bgr, self._cv2.COLOR_BGR2RGB)
        if self._target_size is not None:
            rgb = self._cv2.resize(rgb, self._target_size)
        return pygame.surfarray.make_surface(rgb.swapaxes(0, 1))

    def skip(self):
        """Skip the rest of the video (key/click). Idempotent."""
        self.done = True
        self._finish_clock()
        self.release()

    def release(self):
        """Free the capture. Idempotent."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
