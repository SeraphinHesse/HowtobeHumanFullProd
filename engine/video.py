"""OpenCV video frame source (prototype src/cutscene.py), Phase 9B.

Reads a video and hands pygame surfaces to the host so the game can play the
opening cutscene. GRACEFUL SKIP is the whole point: if cv2 is not installed,
the file is missing, or the capture won't open, the source is `disabled` and
reports `done` immediately — never a crash, never a hang, headless-safe under
SDL dummy.

**Pacing (post-2.4x-speed-bug-fix)**: playback is paced by the SOURCE's own
fps (`cv2.CAP_PROP_FPS`, probed once at open time), not by "one frame per
host `update()` call" — the host may run at any frame rate (60fps here) and
the video plays at its authored speed regardless. `update(dt)` accumulates
`dt` against the frame interval and reads however many frames are due
(discarding all but the last so a game frame rate slower than the video's
doesn't fall behind); a single call reads at most `_MAX_FRAMES_PER_UPDATE`
frames so a huge dt spike (a debugger stall) can't spin through the whole
clip in one call — it just catches up over the next several calls instead.
An absent/zero/negative/NaN source fps (probe failure) falls back to the
pre-fix one-frame-per-`update()` behavior rather than dividing by zero or
hanging (mirrors `editor/cutscene_import.probe_length_seconds`'s graceful-
fallback rule).

**Termination is EOF- (or `skip()`-) authoritative, never `length`.** The
registry's `length` is an approximate/legacy hint the pure
`engine.video_playback` clock still tracks (`elapsed`/`progress` stay usable
standalone), but a real, open, readable capture is never cut off early by it
— only running out of frames or an explicit `skip()` ends playback, so the
full authored clip always plays to its true end.

Timing (elapsed vs length, source-ended) is delegated to the pure
`engine.video_playback` clock (the parallel 9B half) so the state machine is
unit-testable without cv2. If that module is absent this composes an
equivalent in-file fallback clock, so the source works standalone too.

pygame is allowed here (like the render backend / asset store / audio) —
surfarray.make_surface is the only pygame touch; cv2 is imported lazily so
importing this module never requires OpenCV.
"""
import math
import os

import pygame

CUTSCENE_LENGTH = 44.2  # prototype cutscene.py — seconds (the game passes this)

# Bound on frames a single update() call may decode-and-discard to catch up
# after a large dt (a debugger stall, a slow frame). 10 is generous headroom
# above any dt this game actually produces (60fps target => ~0.016s dt) while
# still being a cheap, hard cap — worst case it takes a handful of
# consecutive update() calls (a fraction of a real second at 60fps) to fully
# catch back up to the source's pace, never a single-frame spike through the
# whole clip.
_MAX_FRAMES_PER_UPDATE = 10


def _probe_frame_interval(cv2, cap):
    """Seconds-per-frame from the capture's own reported fps, so playback
    paces at the video's authored speed. Returns None (the "pace by one
    frame per update() call" fallback) for an absent/zero/negative/NaN fps
    or any read failure — mirrors
    ``editor.cutscene_import.probe_length_seconds``'s graceful-fallback
    rule; never raises, never divides by zero."""
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    except Exception:
        return None
    if math.isnan(fps) or fps <= 0:
        return None
    return 1.0 / fps


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
        self._frame_interval = None  # seconds/frame; None = 1 frame/update()
        self._frame_accum = 0.0  # dt owed toward the next paced frame read

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
                self._frame_interval = _probe_frame_interval(cv2, cap)
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
        """Advance playback by `dt` seconds at the source's own authored
        pace and read whatever frame(s) are due (see module docstring);
        never raises. Marks `done` only at end-of-stream — the `length` cap
        no longer ends a live capture, so the full clip always plays out."""
        if self.done or not self.enabled:
            return
        self._clock.advance(dt)  # elapsed/progress bookkeeping only
        for _ in range(self._frames_due(dt)):
            ret, bgr = self._cap.read()
            if not ret:
                self._mark_source_ended()
                return
            self._bgr = bgr

    def _frames_due(self, dt):
        """How many frames `update()` should read this call, paced by
        `_frame_interval` and capped at `_MAX_FRAMES_PER_UPDATE`. Falls back
        to exactly one frame/call when the source fps couldn't be probed
        (the pre-fix behavior)."""
        if self._frame_interval is None:
            return 1
        self._frame_accum += dt
        frames = int(self._frame_accum // self._frame_interval)
        if frames <= 0:
            return 0
        frames = min(frames, _MAX_FRAMES_PER_UPDATE)
        self._frame_accum -= frames * self._frame_interval
        return frames

    def _mark_source_ended(self):
        try:
            self._clock.mark_source_ended()
        except Exception:
            pass
        self.done = True
        self._bgr = None
        self.release()

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
