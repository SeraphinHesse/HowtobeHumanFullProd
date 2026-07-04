"""Pure video-playback clock / state machine (E-12) — NO cv2, NO pygame.

The other agent's OpenCV ``VideoSource`` composes this for timing and
end-of-clip logic, keeping the decode side thin and this side headless-
testable. Tracks elapsed time against a length cap, a done flag, and a
graceful-disable path (when cv2 or the file is missing the source is created
disabled → immediately done, so the host skips it without special-casing).

The prototype's cutscene cap is 44.2 s, but `length` is a constructor
parameter so the engine stays game-agnostic.
"""


class VideoPlayback:
    def __init__(self, length, enabled=True):
        """length: seconds until the clip is considered finished (None = no
        time cap; only the decoder running out or an explicit skip ends it).
        enabled: False means the video is unavailable (missing cv2/file) — it
        starts already done so callers skip it gracefully."""
        self.length = length
        self.enabled = bool(enabled)
        self.elapsed = 0.0
        self.done = not self.enabled

    def advance(self, dt):
        """Accumulate `dt` (seconds); mark done once elapsed reaches the length
        cap. No-op once disabled or done. Returns the current `done` flag."""
        if self.done or not self.enabled:
            return self.done
        self.elapsed += dt
        if self.length is not None and self.elapsed >= self.length:
            self.done = True
        return self.done

    def finish(self):
        """Force completion (natural end reached)."""
        self.done = True

    def skip(self):
        """User skipped the clip (e.g. pressed a key)."""
        self.done = True

    def mark_source_ended(self):
        """The decoder ran out of frames before the length cap."""
        self.done = True

    @property
    def active(self):
        """True while the clip should still be drawn/decoded."""
        return self.enabled and not self.done

    @property
    def progress(self):
        """0.0..1.0 fraction of the length cap elapsed (0.0 if no cap)."""
        if not self.length:
            return 0.0
        return max(0.0, min(1.0, self.elapsed / self.length))
