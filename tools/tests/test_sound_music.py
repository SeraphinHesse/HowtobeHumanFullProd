"""SD-7 — `game/music_director.py`: the music arbitration + the game stings.

Fakes only. The fixture below is PINNED — nothing here reads live `data/`, so
seeding or emptying a real slot can never turn this file red.
"""
import unittest

from game.core.phases import GamePhase, GameState
from game.music_director import (MusicDirector, resolve_music_key,
                                 round_outcome)


def _slot(*files, loop=False):
    return {"clips": [{"file": f, "volume": 1.0, "start": 0.0, "end": 0.0}
                      for f in files],
            "loop": loop, "pick": "random"}


def _balance(*, default=("default.wav",), menu=("menu.wav",),
             cutscene=("cutscene.wav",), building=("building.wav",),
             combat=("combat.wav",)):
    """A pinned `core.json`-shaped balancing dict (`Sounds` subtree only)."""
    return {"Sounds": {
        "Ambient": {"default": _slot("ambient.wav", loop=True)},
        "Game": {name: _slot(name + ".wav")
                 for name in ("game_start", "round_start", "round_win",
                              "round_loss", "game_over", "level_up")},
        "Music": {"default": _slot(*default, loop=True),
                  "menu": _slot(*menu, loop=True),
                  "cutscene": _slot(*cutscene, loop=True),
                  "building_phase": _slot(*building, loop=True),
                  "combat_phase": _slot(*combat, loop=True)},
    }}


class FakeMusic:
    def __init__(self):
        self.calls = []          # ("play_slot"|"stop"|"push"|"pop", payload)

    def play_slot(self, slot, *, rng=None, loop=None):
        self.calls.append(("play_slot", _first_file(slot)))
        return True

    def stop(self):
        self.calls.append(("stop", None))

    def push(self, clip, *, loop=False):
        self.calls.append(("push", (clip or {}).get("file")))
        return True

    def pop(self):
        self.calls.append(("pop", None))
        return True


class FakeSfx:
    def __init__(self):
        self.calls = []          # (file, loop)

    def play_slot(self, slot, *, loop=False):
        self.calls.append((_first_file(slot), loop))
        return True

    @property
    def names(self):
        """The fired slot names — the fixture files are `<name>.wav`."""
        return [f.rsplit(".", 1)[0] for f, _loop in self.calls]


def _first_file(slot):
    clips = (slot or {}).get("clips") or []
    return clips[0]["file"] if clips else None


def _director(balance=None, **kw):
    music, sfx = FakeMusic(), FakeSfx()
    d = MusicDirector(_balance() if balance is None else balance,
                      enabled=kw.pop("enabled", True), music=music, sfx=sfx,
                      **kw)
    return d, music, sfx


class TestResolveMusicKey(unittest.TestCase):
    def test_menu_state(self):
        self.assertEqual(
            resolve_music_key(GameState.MAIN_MENU, None), "menu")

    def test_paused_and_game_over_hold(self):
        self.assertIsNone(
            resolve_music_key(GameState.PAUSED, GamePhase.ENEMY))
        self.assertIsNone(
            resolve_music_key(GameState.GAME_OVER, GamePhase.ENEMY))

    def test_gameplay_phases(self):
        self.assertEqual(
            resolve_music_key(GameState.GAMEPLAY, GamePhase.BUILDING),
            "building_phase")
        self.assertEqual(
            resolve_music_key(GameState.GAMEPLAY, GamePhase.ENEMY),
            "combat_phase")

    def test_cutscene_outranks_everything(self):
        self.assertEqual(resolve_music_key(GameState.CUTSCENE, None),
                         "cutscene")
        self.assertEqual(
            resolve_music_key(GameState.GAMEPLAY, GamePhase.ENEMY,
                              cutscene_active=True), "cutscene")


class TestMusicTick(unittest.TestCase):
    def test_phase_transition_plays_the_other_track(self):
        d, music, _sfx = _director()
        d.tick(GameState.GAMEPLAY, GamePhase.BUILDING)
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY)
        self.assertEqual(music.calls, [("play_slot", "building.wav"),
                                       ("play_slot", "combat.wav")])

    def test_empty_override_falls_back_to_default(self):
        d, music, _sfx = _director(_balance(combat=()))
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY)
        self.assertEqual(music.calls, [("play_slot", "default.wav")])

    def test_empty_default_too_is_silence(self):
        d, music, _sfx = _director(_balance(combat=(), default=()))
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY)
        self.assertEqual(music.calls, [("stop", None)])

    def test_hold_states_touch_nothing(self):
        d, music, _sfx = _director()
        d.tick(GameState.PAUSED, GamePhase.ENEMY)
        d.tick(GameState.GAME_OVER, GamePhase.ENEMY)
        self.assertEqual(music.calls, [])


class TestCutsceneStack(unittest.TestCase):
    def test_push_then_pop_exactly_once(self):
        d, music, _sfx = _director()
        d.enter_cutscene(None)
        d.enter_cutscene(None)          # per-frame branch: still one push
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY, cutscene_active=True)
        d.leave_cutscene()
        d.leave_cutscene()              # unmatched: no second pop
        self.assertEqual(music.calls, [("push", "cutscene.wav"),
                                       ("pop", None)])

    def test_skip_path_pops_too(self):
        # the SKIPPED path reaches the host's `done` / release() branch, which
        # is the same edge leave_cutscene() sits on.
        d, music, _sfx = _director()
        d.enter_cutscene({"audio": "intro.mp3"})
        d.leave_cutscene()
        self.assertEqual(music.calls, [("push", "../video/intro.mp3"),
                                       ("pop", None)])


    def test_music_less_cutscene_leaves_the_bus_alone(self):
        # No companion audio and an EMPTY `Music.cutscene` slot: the previous
        # track must keep playing, so neither push nor pop may fire. The
        # `Music.default` fallback must NOT be borrowed here — doing so
        # restarted the running track from zero on both edges.
        d, music, _sfx = _director(_balance(cutscene=()))
        d.enter_cutscene(None)
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY, cutscene_active=True)
        d.leave_cutscene()
        self.assertEqual(music.calls, [])

    def test_music_less_cutscene_still_unblocks_the_next_one(self):
        d, music, _sfx = _director(_balance(cutscene=()))
        d.enter_cutscene(None)
        d.leave_cutscene()
        d.enter_cutscene({"audio": "intro.mp3"})
        d.leave_cutscene()
        self.assertEqual(music.calls, [("push", "../video/intro.mp3"),
                                       ("pop", None)])

    def test_teardown_during_a_cutscene_does_not_strand_the_next_one(self):
        # quit-to-menu mid-cutscene never reaches the host's release() edge;
        # `teardown_gameplay()` balances the stack instead. Without that, the
        # director stays "in cutscene" forever: the NEXT cutscene's push is
        # silently skipped while its pop still fires.
        d, music, _sfx = _director()
        d.enter_cutscene(None)
        d.leave_cutscene()              # stands in for teardown_gameplay()
        d.enter_cutscene(None)          # the next legitimate cutscene
        d.leave_cutscene()
        self.assertEqual(music.calls, [("push", "cutscene.wav"),
                                       ("pop", None),
                                       ("push", "cutscene.wav"),
                                       ("pop", None)])


class TestGameEvents(unittest.TestCase):
    def test_round_outcome(self):
        self.assertEqual(round_outcome(3, 3), "win")
        self.assertEqual(round_outcome(3, 2), "loss")

    def test_round_win_and_loss_fire_once_each(self):
        d, _music, sfx = _director()
        d.play_game_event("round_" + round_outcome(3, 3))
        d.play_game_event("round_" + round_outcome(3, 2))
        self.assertEqual(sfx.names, ["round_win", "round_loss"])

    def test_fatal_breach_fires_game_over_alone(self):
        # §1.3: `game_over` is NOT accompanied by `round_loss` — the round
        # machine never reaches ROUND_END on the fatal frame.
        d, _music, sfx = _director()
        d.play_game_event("game_over")
        self.assertEqual(sfx.names, ["game_over"])

    def test_level_up_on_increase_only(self):
        d, _music, sfx = _director()
        prev, levels = 1, [1, 2, 2]
        for level in levels:
            if level > prev:
                d.play_game_event("level_up")
            prev = level
        self.assertEqual(sfx.names, ["level_up"])

    def test_ambient_is_a_looping_sfx_and_idempotent(self):
        d, music, sfx = _director()
        d.start_ambient()
        d.start_ambient()
        self.assertEqual(sfx.calls, [("ambient.wav", True)])
        self.assertEqual(music.calls, [])


class TestDisabledIsAllNoOps(unittest.TestCase):
    def test_headless_director_touches_nothing(self):
        d, music, sfx = _director(enabled=False)
        d.tick(GameState.GAMEPLAY, GamePhase.ENEMY)
        d.tick(GameState.MAIN_MENU, None)
        d.enter_cutscene(None)
        d.leave_cutscene()
        d.start_ambient()
        for name in ("game_start", "round_start", "round_win", "round_loss",
                     "game_over", "level_up"):
            d.play_game_event(name)
        self.assertEqual(music.calls, [])
        self.assertEqual(sfx.calls, [])


if __name__ == "__main__":
    unittest.main()
