"""SD-2: engine.audio.sfx / .music must never raise, degrade to no-ops
without a device, and be fully testable via a patched fake `pygame` module
(the `patch.object(sfx, "pygame", Fake())` seam)."""
import os
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine.audio import music, sfx

REPO = Path(__file__).resolve().parents[2]
REAL_AUDIO_ROOT = REPO / "data" / "audio"


CLIP = {"file": "a.wav", "volume": 1.0, "start": 0.0, "end": 0.0}
SLOT = {"clips": [CLIP], "loop": False, "pick": "random"}


class FakeSound:
    def __init__(self, path):
        self.path = path
        self.volume = 1.0

    def set_volume(self, v):
        self.volume = v


class FakeChannel:
    def __init__(self):
        self.busy = True
        self.played = None
        self.maxtime = None
        self.loops = None

    def play(self, sound, loops=0, maxtime=0):
        self.played = sound
        self.loops = loops
        self.maxtime = maxtime
        self.busy = True

    def get_busy(self):
        return self.busy

    def stop(self):
        self.busy = False


class FakeMusic:
    def __init__(self):
        self.loaded = None
        self.playing = False
        self.volume = 1.0
        self.play_calls = []

    def load(self, path):
        self.loaded = path

    def play(self, loops=0, start=0.0):
        self.playing = True
        self.play_calls.append((loops, start))

    def stop(self):
        self.playing = False

    def set_volume(self, v):
        self.volume = v


class FakeMixer:
    def __init__(self):
        self.music = FakeMusic()
        self._init = True
        self.channels = []
        self.sounds_loaded = []

    def get_init(self):
        return (44100, -16, 2) if self._init else None

    def init(self):
        self._init = True

    def set_num_channels(self, n):
        self.num_channels = n

    def Sound(self, path):
        self.sounds_loaded.append(path)
        return FakeSound(path)

    def find_channel(self):
        ch = FakeChannel()
        self.channels.append(ch)
        return ch

    def stop(self):
        for ch in self.channels:
            ch.busy = False


class FakePygame:
    def __init__(self):
        self.mixer = FakeMixer()


class TestDegradation(unittest.TestCase):
    def setUp(self):
        pygame.init()
        sfx.clear_cache()
        sfx.init(REAL_AUDIO_ROOT)
        music.init(REAL_AUDIO_ROOT)

    def test_mixer_uninitialised_is_falsy_no_raise(self):
        # Torn down and never reinitialised — every call must degrade to a
        # falsy no-op rather than raise. (sfx.init() itself is exercised
        # separately: under the SDL dummy driver a *fresh* mixer.init() can
        # legitimately succeed, so this test asserts "never raises" for it
        # and asserts "falsy" for everything that plays through it.)
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        sfx.init(REAL_AUDIO_ROOT)  # never raises, regardless of return value
        self.assertFalse(sfx.play(CLIP))
        self.assertFalse(sfx.play_slot(SLOT))
        self.assertFalse(music.play(CLIP))
        self.assertFalse(music.push(CLIP))
        music.pop()  # never raises, regardless of return value
        sfx.stop_all()  # never raises

    def test_missing_file_is_falsy_no_raise(self):
        pygame.mixer.init()
        sfx.init(REAL_AUDIO_ROOT)
        missing = {"file": "no_such_file.wav", "volume": 1.0, "start": 0.0, "end": 0.0}
        self.assertFalse(sfx.play(missing))


class TestFakeMixerCacheCooldownCap(unittest.TestCase):
    def setUp(self):
        sfx.clear_cache()
        self.fake = FakePygame()
        self._sfx_patch = patch.object(sfx, "pygame", self.fake)
        self._sfx_patch.start()
        self.addCleanup(self._sfx_patch.stop)
        sfx.init(REAL_AUDIO_ROOT)
        sfx.set_master_volume(1.0)
        sfx.set_bus_volume("sfx", 1.0)

    def test_cache_loads_once_across_two_plays(self):
        sfx.play(CLIP, key=None)
        sfx.play(CLIP, key=None)
        self.assertEqual(len(self.fake.mixer.sounds_loaded), 1)

    def test_cooldown_drops_second_play_within_window(self):
        self.assertTrue(sfx.play(CLIP, key="k", cooldown=1.0, now=0.0))
        self.assertFalse(sfx.play(CLIP, key="k", cooldown=1.0, now=0.5))
        self.assertTrue(sfx.play(CLIP, key="k", cooldown=1.0, now=2.0))

    def test_max_concurrent_caps_burst(self):
        results = [sfx.play(CLIP, key="burst", max_concurrent=4, cooldown=0.0, now=float(i))
                   for i in range(10)]
        self.assertEqual(sum(1 for r in results if r), 4)
        self.assertEqual(sfx.active_count("burst"), 4)

    def test_volume_reaches_fake_sound(self):
        sfx.set_master_volume(0.5)
        sfx.set_bus_volume("sfx", 0.5)
        sfx.play(CLIP, key=None)
        channel = self.fake.mixer.channels[-1]
        self.assertAlmostEqual(channel.played.volume, 0.25)


class TestMusic(unittest.TestCase):
    def setUp(self):
        sfx.clear_cache()
        self.fake = FakePygame()
        self._sfx_patch = patch.object(sfx, "pygame", self.fake)
        self._music_patch = patch.object(music, "pygame", self.fake)
        self._sfx_patch.start()
        self._music_patch.start()
        self.addCleanup(self._sfx_patch.stop)
        self.addCleanup(self._music_patch.stop)
        sfx.init(REAL_AUDIO_ROOT)
        music.init(REAL_AUDIO_ROOT)

    def test_same_file_replay_is_noop(self):
        self.assertTrue(music.play(CLIP))
        loads_after_first = len(self.fake.mixer.music.play_calls)
        self.assertTrue(music.play(CLIP))
        self.assertEqual(len(self.fake.mixer.music.play_calls), loads_after_first)

    def test_push_then_pop_restores_previous(self):
        first = {"file": "first.wav", "volume": 1.0, "start": 0.0, "end": 0.0}
        second = {"file": "second.wav", "volume": 1.0, "start": 0.0, "end": 0.0}
        music.play(first)
        music.push(second)
        self.assertEqual(music.current()["file"], "second.wav")
        music.pop()
        self.assertEqual(music.current()["file"], "first.wav")


if __name__ == "__main__":
    unittest.main()
