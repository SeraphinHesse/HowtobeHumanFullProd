"""engine.audio.music — pygame.mixer.music: one streaming track at a time,
push/pop stack for temporary tracks (the cutscene case), "already playing =
no-op" (SD-2).

Reads the bus/master volume registry from `sfx.py` (the module that owns
`init()` and the channel pool) rather than keeping its own copy — see
`engine/audio/__init__.py`'s module docstring for the fan-out shape. Calls
pygame through the module attribute (`pygame.mixer.music....`) so a test can
patch it, same seam as `sfx.py`.
"""
import pygame

from . import bank
from . import sfx

_audio_root = None
_current_clip = None
_current_loop = True
_stack = []  # list[(clip | None, loop)]


def init(audio_root):
    global _audio_root
    _audio_root = audio_root
    return sfx.is_ready()


def _same_file(a, b):
    if not a or not b:
        return False
    return a.get("file") == b.get("file")


def play(clip, *, loop=True, force=False):
    """No-op returning True when `clip`'s file is already the current track
    and `force` is False."""
    global _current_clip, _current_loop
    if not clip or not clip.get("file"):
        return False
    if not force and _same_file(_current_clip, clip):
        return True
    if not sfx.is_ready():
        return False
    path = bank.clip_path(_audio_root, clip)
    if path is None:
        return False
    try:
        pygame.mixer.music.load(str(path))
        start_secs, _end_secs = bank.trim_bounds(clip)
        volume = bank.effective_volume(clip, sfx.bus_volume("music"), sfx.master_volume())
        try:
            pygame.mixer.music.set_volume(volume)
        except Exception:
            pass
        try:
            pygame.mixer.music.play(-1 if loop else 0, start_secs)
        except TypeError:
            pygame.mixer.music.play(-1 if loop else 0)
        _current_clip = clip
        _current_loop = loop
        return True
    except Exception:
        return False


def play_slot(slot, *, rng=None, loop=None):
    clip = bank.pick_clip(slot, rng)
    if clip is None:
        return False
    effective_loop = (slot or {}).get("loop", False) if loop is None else loop
    return play(clip, loop=effective_loop)


def stop():
    global _current_clip
    try:
        pygame.mixer.music.stop()
    except Exception:
        pass
    _current_clip = None


def current():
    """The playing clip dict, or None."""
    return _current_clip


def push(clip, *, loop=False):
    """Save the current clip on a stack and play `clip` instead."""
    _stack.append((_current_clip, _current_loop))
    return play(clip, loop=loop, force=True)


def pop():
    """Resume the top saved clip; stop() when the stack is empty. Never
    raises on an unbalanced pop."""
    if not _stack:
        stop()
        return True
    clip, loop = _stack.pop()
    if clip is None:
        stop()
        return True
    return play(clip, loop=loop, force=True)


def refresh_volume():
    """Re-apply master*bus to the live track."""
    if not _current_clip:
        return
    try:
        volume = bank.effective_volume(_current_clip, sfx.bus_volume("music"), sfx.master_volume())
        pygame.mixer.music.set_volume(volume)
    except Exception:
        pass
