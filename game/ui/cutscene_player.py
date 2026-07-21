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
        video_name = entry.get("video")
        video_path = data_dir / "video" / video_name if video_name else ""
        self._video = VideoSource(video_path, entry.get("length"),
                                   target_size=target_size)
        audio_name = entry.get("audio")
        self._audio_path = data_dir / "video" / audio_name if audio_name \
            else None

    @property
    def enabled(self):
        """Graceful-skip mirror of ``VideoSource.enabled`` (missing cv2 /
        file / unopenable capture -> False)."""
        return self._video.enabled

    @property
    def done(self):
        return self._video.done

    def start(self):
        """Call once, when playback begins. Starts the companion track (if
        any) via ``engine.audio.play_music(path, loop=False)`` — a no-op
        under SDL dummy / no audio device (``engine/audio.py``'s
        exception-swallowing contract). NOTE: there is only ONE
        ``pygame.mixer.music`` channel, so this replaces whatever background
        music was already playing; nothing restores it afterward."""
        if self._audio_path is not None:
            play_music(self._audio_path, loop=False)

    def update(self, dt):
        self._video.update(dt)

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
