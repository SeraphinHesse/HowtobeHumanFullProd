"""Phase 9B: engine.audio must never crash — every call is a best-effort
no-op when audio is unavailable (SDL dummy, no device, missing file, mixer
not initialised)."""
import os
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from engine import audio

REPO = Path(__file__).resolve().parents[2]
MUSIC = REPO / "data" / "audio" / "Bass_and_drum_Duo.wav"


class TestAudioGraceful(unittest.TestCase):
    def setUp(self):
        pygame.init()

    def test_play_missing_file_no_raise(self):
        # returns silently even though the path does not exist
        self.assertIsNone(audio.play_music(REPO / "no_such_music.wav"))

    def test_play_real_file_no_raise(self):
        # under SDL dummy audio this either plays silently or no-ops — never raises
        self.assertIsNone(audio.play_music(MUSIC))
        self.assertIsNone(audio.play_music(MUSIC, loop=False, volume=0.5))

    def test_stop_and_set_volume_no_raise(self):
        self.assertIsNone(audio.stop_music())
        self.assertIsNone(audio.set_volume(0.3))

    def test_no_raise_when_mixer_uninitialised(self):
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        # mixer torn down — calls must still swallow and no-op
        audio.play_music(MUSIC)
        audio.set_volume(0.5)
        audio.stop_music()


if __name__ == "__main__":
    unittest.main()
