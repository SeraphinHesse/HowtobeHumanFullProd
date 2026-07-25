"""Phase TU-5: game.ui.cutscene_player — registry-driven cutscene playback.

Headless (SDL dummy), mirrors tools/tests/test_video_source.py's shape:
registry load, missing-video graceful skip, start()/skip() audio calls are
no-ops under SDL dummy. Reads through the pinned FIXTURE_DATA snapshot
(tools/tests/fixture_data.py), never live data/ (test_tutorial_data.py's
convention) — a designer edit must never turn this gate red.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame

from game.ui.cutscene_player import CutscenePlayer, load_cutscene_registry
from tools.tests.fixture_data import FIXTURE_DATA


class TestLoadCutsceneRegistry(unittest.TestCase):
    def test_returns_known_ids_with_expected_keys(self):
        registry = load_cutscene_registry(FIXTURE_DATA)
        self.assertIn("intro", registry)
        self.assertIn("first_end_turn", registry)
        for entry in registry.values():
            self.assertIn("video", entry)
            self.assertIn("audio", entry)
            self.assertIn("length", entry)
            self.assertIn("trigger", entry)

    def test_intro_entry_matches_fixture(self):
        registry = load_cutscene_registry(FIXTURE_DATA)
        self.assertEqual(registry["intro"]["video"], "cutscene.mp4")
        self.assertEqual(registry["intro"]["length"], 44.2)


class TestCutscenePlayerGracefulSkip(unittest.TestCase):
    """No actual video files ship in the fixture dir, so every fixture entry
    exercises VideoSource's graceful-skip path — exactly the "missing video"
    contract this phase inherits, never reimplements."""

    def setUp(self):
        pygame.init()
        self.registry = load_cutscene_registry(FIXTURE_DATA)

    def test_missing_video_disabled_and_done_immediately(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["intro"])
        self.assertFalse(player.enabled)
        self.assertTrue(player.done)

    def test_missing_video_update_and_frame_no_crash(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["first_end_turn"])
        player.update(0.016)  # no-op, must not raise
        self.assertIsNone(player.frame_surface())
        player.release()  # idempotent


class TestCutscenePlayerAudio(unittest.TestCase):
    """start()/skip() route through engine.audio, which swallows every
    failure under SDL dummy — this just proves TU-5's wiring doesn't bypass
    that contract (e.g. by touching pygame.mixer.music directly)."""

    def setUp(self):
        pygame.init()
        pygame.mixer.init()
        self.registry = load_cutscene_registry(FIXTURE_DATA)

    def test_start_does_not_raise_with_no_companion_audio(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["intro"])
        player.start()  # audio is null in the fixture entry -> no-op

    def test_start_does_not_raise_with_companion_audio_entry(self):
        entry = dict(self.registry["first_end_turn"])
        entry["audio"] = "no_such_track.wav"
        player = CutscenePlayer(FIXTURE_DATA, entry)
        player.start()  # missing file -> engine.audio swallows it

    def test_skip_does_not_raise(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["intro"])
        player.start()
        player.skip()
        self.assertTrue(player.done)

    def test_release_is_idempotent(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["intro"])
        player.release()
        player.release()


if __name__ == "__main__":
    unittest.main()
