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

from game.ui.cutscene_player import (
    SKIP_HOLD_SECONDS, CutscenePlayer, load_cutscene_registry)
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


class TestCutscenePlayerReplay(unittest.TestCase):
    """A run torn down at the main menu leaves the PLAYER alive (one per
    registry id for the whole process) while its VideoSource is spent —
    release() frees the capture and done latches True. start() must
    therefore open a fresh source for every playback, or the next run's
    cutscene ends on the frame it was requested. The fixture ships no video
    files, so this asserts the swap itself, not decoded frames."""

    def setUp(self):
        pygame.init()
        self.registry = load_cutscene_registry(FIXTURE_DATA)

    def test_start_opens_a_fresh_source_after_a_finished_playback(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["first_end_turn"])
        player.start()
        spent = player._video
        player.skip()          # run 1 ends (timer or manual close)
        player.release()
        player.start()         # run 2's first End Turn
        self.assertIsNot(player._video, spent)

    def test_start_opens_a_fresh_source_after_a_mid_playback_quit(self):
        # Quit-to-menu releases the capture WITHOUT marking it done — the
        # case a "rewind only when done" guard would miss.
        player = CutscenePlayer(FIXTURE_DATA, self.registry["first_end_turn"])
        player.start()
        player._video.done = False
        abandoned = player._video
        player.release()
        player.start()
        self.assertIsNot(player._video, abandoned)

    def test_start_resets_the_hold_to_skip_accumulator(self):
        player = CutscenePlayer(FIXTURE_DATA, self.registry["intro"])
        player._video.done = False
        player.update_skip_hold(SKIP_HOLD_SECONDS - 0.1, True)
        self.assertGreater(player.skip_progress, 0.0)
        player.start()
        self.assertEqual(player.skip_progress, 0.0)


class TestCutscenePlayerSkipHold(unittest.TestCase):
    """cutscene-hold-to-skip: the 2s hold timer lives on CutscenePlayer
    itself, so it's exercised directly rather than through main.py's event
    loop. Fixture entries have no real video file, so a freshly-constructed
    player is already `done` (VideoSource's graceful-skip path) — tests that
    need an in-progress video force `player._video.done = False` (a plain
    public attribute on VideoSource) to isolate the hold-timer logic from
    video availability."""

    def setUp(self):
        pygame.init()
        registry = load_cutscene_registry(FIXTURE_DATA)
        self.player = CutscenePlayer(FIXTURE_DATA, registry["intro"])
        self.player._video.done = False  # simulate an in-progress video

    def test_hold_below_threshold_does_not_skip(self):
        self.player.update_skip_hold(SKIP_HOLD_SECONDS - 0.5, True)
        self.assertFalse(self.player.done)
        self.assertLess(self.player.skip_progress, 1.0)
        self.assertGreater(self.player.skip_progress, 0.0)

    def test_hold_reaching_threshold_skips(self):
        self.player.update_skip_hold(SKIP_HOLD_SECONDS, True)
        self.assertTrue(self.player.done)
        self.assertEqual(self.player.skip_progress, 1.0)

    def test_release_before_threshold_resets_progress(self):
        self.player.update_skip_hold(SKIP_HOLD_SECONDS - 0.1, True)
        self.assertGreater(self.player.skip_progress, 0.0)
        self.player.update_skip_hold(0.016, False)
        self.assertFalse(self.player.done)
        self.assertEqual(self.player.skip_progress, 0.0)
        # a fresh hold afterward starts from zero, not where it left off
        self.player.update_skip_hold(SKIP_HOLD_SECONDS - 0.5, True)
        self.assertFalse(self.player.done)

    def test_never_held_never_skips(self):
        for _ in range(10):
            self.player.update_skip_hold(1.0, False)
        self.assertFalse(self.player.done)
        self.assertEqual(self.player.skip_progress, 0.0)

    def test_no_op_once_already_done(self):
        registry = load_cutscene_registry(FIXTURE_DATA)
        player = CutscenePlayer(FIXTURE_DATA, registry["intro"])
        self.assertTrue(player.done)  # missing video -> already done
        player.update_skip_hold(SKIP_HOLD_SECONDS, True)  # must not raise
        self.assertTrue(player.done)


if __name__ == "__main__":
    unittest.main()
