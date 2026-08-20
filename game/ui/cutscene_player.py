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
    ``first_end_turn``.

    **Fade in/out (feature: cutscene-fade-in-out)** — ``fade_in``/
    ``fade_out`` (seconds, ``data/balancing/core.json``'s ``Cutscene``
    group) hold the screen frozen on the video's first/last decoded frame
    while a caller-drawn black overlay ramps opaque->transparent /
    transparent->opaque. The fade is ADDED on top of the video's own
    length, never overlapped with it: the video itself plays its full,
    unmodified length only during the middle "playing" phase. Both default
    to 0.0, which makes the whole feature an exact no-op — ``_phase`` never
    leaves ``"playing"`` and every accessor (``done``/``frame_surface``)
    delegates straight to the wrapped ``VideoSource``, byte-identical to
    before this feature existed.

    This class draws nothing itself (``game/ui`` stays pygame-free) — the
    host reads ``fade_alpha`` each frame and composites its own black
    overlay on top of ``frame_surface()``."""

    def __init__(self, data_dir, entry, target_size=None,
                 fade_in=0.0, fade_out=0.0):
        self._data_dir = data_dir
        self._entry = entry
        self._target_size = target_size
        self._fade_in = float(fade_in)
        self._fade_out = float(fade_out)
        self._video = self._open_video()
        audio_name = entry.get("audio")
        self._audio_path = data_dir / "video" / audio_name if audio_name \
            else None
        self._skip_hold = 0.0
        self._skipped = False
        self._last_frame = None  # held for the fade-out phase (the video's
        # own ``_bgr`` is cleared at EOF, see VideoSource._mark_source_ended)
        self._phase = "fade_in" if self._fade_in > 0 else "playing"
        self._phase_t = 0.0
        if self._phase == "fade_in":
            self._video.prime()

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
        """True once the WHOLE cutscene (fade-in, video, fade-out) has
        finished playing, or the player skipped it early. Computed live
        off ``_phase``/``_video.done`` rather than a stored terminal flag,
        so a caller/test that pokes ``_video.done`` directly (a long-
        standing test pattern in this suite) is still read correctly
        without needing a matching ``update()`` call first. With both
        fades disabled (the default) this reduces to exactly
        ``self._video.done``, byte-identical to before this feature."""
        if self._skipped:
            return True
        if self._phase == "fade_in":
            return False
        if self._phase == "fade_out":
            return self._phase_t >= self._fade_out
        return self._video.done and self._fade_out <= 0

    @property
    def fade_alpha(self):
        """0 (fully revealed) .. 255 (fully black) — the black overlay
        alpha the HOST draws on top of ``frame_surface()`` this frame.
        Always 0 outside a fade phase, so an unconfigured cutscene
        (``fade_in == fade_out == 0``) never leaves ``_phase != "playing"``
        and this is a permanent no-op."""
        if self._phase == "fade_in" and self._fade_in > 0:
            frac = 1.0 - min(1.0, self._phase_t / self._fade_in)
            return int(round(255 * frac))
        if self._phase == "fade_out" and self._fade_out > 0:
            frac = min(1.0, self._phase_t / self._fade_out)
            return int(round(255 * frac))
        return 0

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
        self._skipped = False
        self._last_frame = None
        self._phase = "fade_in" if self._fade_in > 0 else "playing"
        self._phase_t = 0.0
        if self._phase == "fade_in":
            self._video.prime()
        if self._audio_path is not None:
            play_music(self._audio_path, loop=False)

    def update(self, dt):
        """Advances whichever phase is current. With both fades disabled
        (the default) this reduces to exactly ``self._video.update(dt)`` —
        byte-identical to before this feature (feature: cutscene-fade-in-
        out)."""
        if self.done:
            return
        if self._phase == "fade_in":
            self._phase_t += dt
            if self._phase_t >= self._fade_in:
                self._phase = "playing"
            return
        if self._phase == "playing":
            self._video.update(dt)
            if self._fade_out > 0:
                # Cache the latest decoded frame each tick so the fade-out
                # always has one to hold. `VideoSource.update` re-holds the
                # true final frame at natural EOF (engine/video.py), so the
                # read AFTER update() is the real last frame even when the
                # clip ends inside a multi-frame catch-up burst; this cache
                # then also survives a `release()` on the way out.
                surf = self._video.frame_surface()
                if surf is not None:
                    self._last_frame = surf
                if self._video.done:
                    self._phase = "fade_out"
                    self._phase_t = 0.0
            return
        # fade_out
        self._phase_t += dt

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
        """During ``fade_out`` the underlying ``VideoSource`` has already
        hit EOF and been released (see ``update()``), so this returns the
        cached ``_last_frame`` instead; every other phase
        delegates straight to ``VideoSource.frame_surface()`` — with
        ``fade_out`` disabled ``_phase`` never becomes ``"fade_out"``, so
        this is byte-identical to before this feature."""
        if self._phase == "fade_out":
            return self._last_frame
        return self._video.frame_surface()

    def skip(self):
        """Click/key skip — mirrors ``VideoSource.skip()`` + stops the
        companion track. Ends the WHOLE cutscene immediately, fade-out
        included (feature: cutscene-fade-in-out) — a skip means "get me
        out of this cutscene now", not "skip to the fade-out and make me
        wait through that too".

        Only stops the bus when this cutscene HAS a companion track. It used
        to stop unconditionally, which killed the background music of every
        music-less cutscene — the exact track the host is holding for us."""
        self._video.skip()
        if self._audio_path is not None:
            stop_music()
        self._skipped = True

    def release(self):
        """Mirrors ``VideoSource.release()``; also stops the companion track
        defensively (idempotent, like the video release it mirrors) — but
        only when there IS one, for the same reason as ``skip()``."""
        self._video.release()
        if self._audio_path is not None:
            stop_music()
