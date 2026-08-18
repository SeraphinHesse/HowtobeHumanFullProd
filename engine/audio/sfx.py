"""engine.audio.sfx — pygame.mixer.Sound bus: clip cache, channel pool,
per-key cooldown/concurrency cap, bus+master volume registry (SD-2).

Every mixer-touching call swallows ALL exceptions and degrades to a falsy
no-op — no audio device, mixer not initialised, missing file, unsupported
codec, ``SDL_AUDIODRIVER=dummy``. Calls pygame through the **module
attribute** (``pygame.mixer.Sound(...)``, never ``from pygame.mixer import
Sound``) so a test can ``unittest.mock.patch.object(sfx, "pygame",
FakeMixer())``.

Start-trim (``clip["start"] > 0``) feature-detects numpy — it is only a
transitive optional dependency via opencv-python — and falls back to
end-only trim via ``Sound.play(maxtime=...)`` when numpy is absent
(mirrors the lazy-cv2 pattern in ``engine/video.py``).
"""
import time
from pathlib import Path

import pygame

from . import bank

DEFAULT_CHANNELS = 24
DEFAULT_COOLDOWN_S = 0.05
DEFAULT_MAX_CONCURRENT = 4

_ready = False
_audio_root = None
_master = 1.0
_bus = {"music": 1.0, "sfx": 1.0}
_cache = {}  # (path, start, end) -> None (failed) | (Sound, maxtime_ms)
_last_play = {}  # key -> monotonic timestamp
_active = {}  # key -> list[Channel]

_numpy_checked = False
_numpy_module = None


def _numpy():
    global _numpy_checked, _numpy_module
    if not _numpy_checked:
        try:
            import numpy as np

            _numpy_module = np
        except ImportError:
            _numpy_module = None
        _numpy_checked = True
    return _numpy_module


def start_trim_available():
    """numpy feature-detect result — True if start-trim (needs a sliced
    sndarray buffer) is available on this host."""
    return _numpy() is not None


def init(audio_root, *, channels=DEFAULT_CHANNELS):
    """Idempotent. Returns False (never raises) when the mixer is
    unavailable; every later call then no-ops."""
    global _ready, _audio_root
    _audio_root = Path(audio_root) if audio_root is not None else None
    try:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.set_num_channels(channels)
        _ready = True
        return True
    except Exception:
        _ready = False
        return False


def is_ready():
    try:
        return bool(_ready and pygame.mixer.get_init())
    except Exception:
        return False


def _round_key(path, clip):
    try:
        start = round(float(clip.get("start", 0.0) or 0.0), 3)
    except (TypeError, ValueError):
        start = 0.0
    try:
        end = round(float(clip.get("end", 0.0) or 0.0), 3)
    except (TypeError, ValueError):
        end = 0.0
    return (str(path), start, end)


def _load_sound(path, start, end):
    """Returns (Sound|None, maxtime_ms). Bakes the start-trim into the
    sound's own samples via numpy when available and start > 0; otherwise
    leaves start unapplied and reports an end-only maxtime for the caller
    to pass to `Channel.play`."""
    try:
        if start and start > 0.0 and start_trim_available():
            np = _numpy()
            base = pygame.mixer.Sound(str(path))
            arr = pygame.sndarray.array(base)
            init_info = pygame.mixer.get_init()
            freq = init_info[0] if init_info else 44100
            start_idx = max(0, int(start * freq))
            if end is not None:
                end_idx = max(start_idx, int(end * freq))
            else:
                end_idx = len(arr)
            end_idx = min(end_idx, len(arr))
            sliced = np.ascontiguousarray(arr[start_idx:end_idx])
            sound = pygame.sndarray.make_sound(sliced)
            return sound, 0
        sound = pygame.mixer.Sound(str(path))
        if end is None:
            return sound, 0
        maxtime_ms = max(0, int((end - (start or 0.0)) * 1000))
        return sound, maxtime_ms
    except Exception:
        return None, 0


def _get_sound(clip):
    if not clip:
        return None, 0
    path = bank.clip_path(_audio_root, clip)
    if path is None:
        return None, 0
    cache_key = _round_key(path, clip)
    if cache_key in _cache:
        cached = _cache[cache_key]
        if cached is None:
            return None, 0
        return cached
    start_secs, end_secs = bank.trim_bounds(clip)
    sound, maxtime_ms = _load_sound(path, start_secs, end_secs)
    if sound is None:
        _cache[cache_key] = None
        return None, 0
    _cache[cache_key] = (sound, maxtime_ms)
    return sound, maxtime_ms


def _prune(key):
    channels = _active.get(key)
    if not channels:
        return []
    alive = []
    for ch in channels:
        try:
            if ch.get_busy():
                alive.append(ch)
        except Exception:
            pass
    _active[key] = alive
    return alive


def active_count(key=None):
    """Live channels, all or per key."""
    try:
        if key is not None:
            return len(_prune(key))
        total = 0
        for k in list(_active.keys()):
            total += len(_prune(k))
        return total
    except Exception:
        return 0


def play(clip, *, key=None, loop=False, cooldown=DEFAULT_COOLDOWN_S,
         max_concurrent=DEFAULT_MAX_CONCURRENT, now=None):
    if not is_ready() or not clip:
        return False
    try:
        moment = time.monotonic() if now is None else now
        if key is not None:
            last = _last_play.get(key)
            if last is not None and (moment - last) < cooldown:
                return False
            if len(_prune(key)) >= max_concurrent:
                return False

        sound, maxtime_ms = _get_sound(clip)
        if sound is None:
            return False

        channel = pygame.mixer.find_channel()
        if channel is None:
            return False

        volume = bank.effective_volume(clip, bus_volume("sfx"), master_volume())
        try:
            sound.set_volume(volume)
        except Exception:
            pass

        channel.play(sound, loops=-1 if loop else 0, maxtime=maxtime_ms)

        if key is not None:
            _last_play[key] = moment
            _active.setdefault(key, []).append(channel)
        return True
    except Exception:
        return False


def play_slot(slot, *, key=None, rng=None, loop=None, now=None):
    clip = bank.pick_clip(slot, rng)
    if clip is None:
        return False
    effective_loop = (slot or {}).get("loop", False) if loop is None else loop
    return play(clip, key=key, loop=effective_loop, now=now)


def set_bus_volume(bus, v):
    if bus not in bank.BUSES:
        return
    try:
        v = float(v)
    except (TypeError, ValueError):
        return
    _bus[bus] = max(0.0, min(1.0, v))


def bus_volume(bus):
    return _bus.get(bus, 1.0)


def set_master_volume(v):
    global _master
    try:
        v = float(v)
    except (TypeError, ValueError):
        return
    _master = max(0.0, min(1.0, v))


def master_volume():
    return _master


def stop_all():
    try:
        for k in list(_active.keys()):
            for ch in _active.get(k, []):
                try:
                    ch.stop()
                except Exception:
                    pass
        _active.clear()
        try:
            pygame.mixer.stop()
        except Exception:
            pass
    except Exception:
        pass


def clear_cache():
    """Test/teardown hook."""
    _cache.clear()
    _last_play.clear()
    _active.clear()
