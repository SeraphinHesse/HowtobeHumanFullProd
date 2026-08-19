"""CutscenePlayer + the cutscene registry loader (Phase TU-5).

Generalizes the Phase 9B intro-cutscene loop (a single hardcoded
``VideoSource`` built from a balancing constant) into a reusable class driven
by ``data/video/cutscenes.json`` (TU-1): one ``CutscenePlayer`` per registry
entry, usable both for the pre-gameplay intro (the existing
``GameState.CUTSCENE`` shell state) and the in-gameplay ``first_end_turn``
overlay (``Session.end_turn()``'s ``pending_cutscene`` request, drained by the
host).

No pygame import here (game/ui purity, ``tools/tests/test_shell.py``'s
``TestPurity``) — ``engine.video.VideoSource`` and ``engine.audio`` are the
sanctioned pygame-touching modules this wraps.
"""
from engine import data_io
from engine.audio import play_music, stop_music
from engine.video import VideoSource

#: hold-to-skip threshold (left click / space / esc), shared by every
#: registry entry — a code constant, not a balancing value (mirrors other
#: UI-interaction constants like main.py's drag threshold).
SKIP_HOLD_SECONDS = 2.0


def load_cutscene_registry(data_dir):
    """Load + schema-validate ``data/video/cutscenes.json`` into an id-keyed
    dict (``{"intro": {...}, "first_end_turn": {...}}`` — TU-1's on-disk
    shape already matches this in-memory shape 1:1, so this is a thin
    validated-load wrapper; adjust HERE, not at call sites, if that ever
    changes)."""
    return data_io.load_validated(
        data_dir / "video" / "cutscenes.json",
        data_dir / "schemas" / "cutscenes.schema.json")


class CutscenePlayer:
    """Wraps a ``VideoSource`` + the entry's optional companion audio track.
    One instance per registry entry; reusable for both the intro slot and
    ``first_end_turn``."""

    def __init__(self, data_dir, entry, target_size=None):
        self._data_dir = data_dir
        self._entry = entry
        self._target_size = target_size
        self._video = self._open_video()
        audio_name = entry.get("audio")
        self._audio_path = data_dir / "video" / audio_name if audio_name \
            else None
        self._skip_hold = 0.0

    def _open_video(self):
        """A FRESH ``VideoSource`` for this entry — built at construction and
        again by ``start()`` whenever the previous one was consumed (see
        there for why)."""
        video_name = self._entry.get("video")
        video_path = (self._data_dir / "video" / video_name
                      if video_name else "")
        return VideoSource(video_path, self._entry.get("length"),
                           target_size=self._target_size)

    @property
    def enabled(self):
        """Graceful-skip mirror of ``VideoSource.enabled`` (missing cv2 /
        file / unopenable capture -> False)."""
        return self._video.enabled

    @property
    def done(self):
        return self._video.done

    def start(self):
        """Call when playback begins — once per PLAYBACK, not once per
        process. Starts the companion track (if any) via
        ``engine.audio.play_music(path, loop=False)`` — a no-op
        under SDL dummy / no audio device (``engine/audio.py``'s
        exception-swallowing contract). NOTE: there is only ONE
        ``pygame.mixer.music`` channel, so this replaces whatever background
        music was already playing — but it IS restored afterward now (SD-7):
        the host stacks the current track with
        ``MusicDirector.enter_cutscene()`` on the same edge that calls
        ``start()``, and pops it back in ``leave_cutscene()`` beside
        ``release()``. This class still owns only its own companion track.

        REPLAY: a ``VideoSource`` is one-shot — ``release()`` frees the cv2
        capture and ``done`` latches True — while the host builds ONE player
        per registry id for the whole PROCESS (``game/main.py``'s
        ``cutscenes`` dict). So a player that had already played stayed
        permanently ``done``: quitting to the main menu and starting a NEW
        run requested ``first_end_turn`` again, the host accepted it
        (``enabled`` is still True), and it ended on the same frame without
        showing a thing. Every playback therefore starts from a FRESH
        source — unconditionally, not just when the previous one ran to
        ``done``, since a run torn down mid-cutscene leaves a released
        capture behind that is neither done nor readable — and resets the
        hold-to-skip accumulator (a hold-skip leaves it past the
        threshold, which would otherwise insta-skip the next playback)."""
        self._video.release()   # idempotent; frees a half-played capture
        self._video = self._open_video()
        self._skip_hold = 0.0
        if self._audio_path is not None:
            play_music(self._audio_path, loop=False)

    def update(self, dt):
        self._video.update(dt)

    def update_skip_hold(self, dt, held):
        """Accumulates while ``held`` (left click/space/esc, host-decided)
        is down; calls ``skip()`` once ``SKIP_HOLD_SECONDS`` is reached.
        Releasing before the threshold resets the accumulator to 0 — a
        no-op once the video is already ``done`` (never re-fires ``skip()``
        the same frame the video ends naturally)."""
        if self.done:
            return
        if not held:
            self._skip_hold = 0.0
            return
        self._skip_hold += dt
        if self._skip_hold >= SKIP_HOLD_SECONDS:
            self.skip()

    @property
    def skip_progress(self):
        """Fraction [0, 1] of the hold threshold reached so far — the host
        draws this as a progress ring."""
        return min(1.0, self._skip_hold / SKIP_HOLD_SECONDS)

    def frame_surface(self):
        return self._video.frame_surface()

    def skip(self):
        """Click/key skip — mirrors ``VideoSource.skip()`` + stops the
        companion track."""
        self._video.skip()
        stop_music()

    def release(self):
        """Mirrors ``VideoSource.release()``; also stops the companion track
        defensively (idempotent, like the video release it mirrors)."""
        self._video.release()
        stop_music()
