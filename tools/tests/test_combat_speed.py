"""Phase 10F: combat speed (1x / 1.5x / 2x / pause) + the P quick-skip.

Pure-Python, headless — a synth ``TileMapDoc`` -> ``TileMap`` fixture + real
balancing via ``load_balance``, exactly like the 9E/9F enemy/round-loop tests.

The multiplier is `Session` state; the HOST decides where it applies (the
ENEMY-phase sim only). ``host_frame`` below mirrors ``game/main.py``'s frame so
the "2x really doubles the wave" and "pause really freezes it" claims are tested
against the same wiring the game runs, not a private one. The 1x/1.5x/2x/pause
BUTTONS are 10L — 10F ships the mechanic + the keyboard shortcuts.
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.core.session import COMBAT_SPEEDS, PAUSE_SPEED_IDX
from game.enemies import Spawner, resolve_combat
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

PHASE = CORE["PhaseLoop"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_session(rows=("bbbs",)):
    tm = synth(list(rows))
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ)
    return session, scene, tm


def host_frame(session, scene, tm, dt):
    """One frame, wired exactly like ``game/main.py``: the ENEMY phase runs on
    the combat-speed-scaled dt; every other phase runs on real time."""
    sim_dt = (dt * session.combat_speed
              if session.state.phase == GamePhase.ENEMY else dt)
    session.pre_sim(sim_dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(sim_dt)
        resolve_combat(scene, tm, sim_dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death)
        session.post_sim(scene)


def end_turn_past_any_intro(session):
    """end_turn(), then drain any enemy-intro entry queued on this round
    (feature-enemy-intro-dialogue) — round 1 carries one in the fixture data,
    and this module's tests build sessions starting on round 1."""
    session.end_turn()
    while session.state.phase == GamePhase.ENEMY_INTRO:
        session.resolve_enemy_intro()


class TestSpeedSelection(unittest.TestCase):
    def test_starts_at_1x(self):
        session, _s, _t = build_session()
        self.assertEqual(session.combat_speed_idx, 0)
        self.assertEqual(session.combat_speed, 1.0)

    def test_1_5x_and_2x_are_round_gated(self):
        session, _s, _t = build_session()
        session.state.round_num = 1
        session.set_combat_speed(1)
        self.assertEqual(session.combat_speed, 1.0)  # locked -> no-op
        session.set_combat_speed(2)
        self.assertEqual(session.combat_speed, 1.0)

        session.state.round_num = PHASE["speed_1_5x_min_round"]
        session.set_combat_speed(1)
        self.assertEqual(session.combat_speed, 1.5)
        session.set_combat_speed(2)
        self.assertEqual(session.combat_speed, 1.5)  # 2x still locked

        session.state.round_num = PHASE["speed_2x_min_round"]
        session.set_combat_speed(2)
        self.assertEqual(session.combat_speed, 2.0)

    def test_1x_and_pause_never_gated(self):
        session, _s, _t = build_session()
        session.state.round_num = 1
        session.set_combat_speed(PAUSE_SPEED_IDX)
        self.assertEqual(session.combat_speed, 0.0)
        session.set_combat_speed(0)
        self.assertEqual(session.combat_speed, 1.0)

    def test_out_of_range_index_is_a_noop(self):
        session, _s, _t = build_session()
        for idx in (-1, len(COMBAT_SPEEDS), 99):
            session.set_combat_speed(idx)
            self.assertEqual(session.combat_speed_idx, 0)

    def test_pause_toggle_restores_the_last_real_speed(self):
        session, _s, _t = build_session()
        session.state.round_num = PHASE["speed_2x_min_round"]
        session.set_combat_speed(2)                    # 2x
        session.toggle_pause()
        self.assertEqual(session.combat_speed, 0.0)
        session.toggle_pause()
        self.assertEqual(session.combat_speed, 2.0)   # back to 2x, not 1x


class TestSpeedAppliesToCombatOnly(unittest.TestCase):
    def _spawned_after(self, speed_idx, round_num, frames=40, dt=0.05):
        # Seed the spawner's RNG. It defaults to the bare `random` module, so
        # the wave's spawn jitter differed between the 1x and 2x runs and the
        # comparison was only USUALLY true — the test failed roughly one run in
        # ten, for no reason connected to combat speed. Same seed on both sides
        # makes the jitter identical and the speed the only variable, which is
        # what the test claims to measure.
        random.seed(20260714)
        session, scene, tm = build_session()
        session.state.round_num = round_num
        session.set_combat_speed(speed_idx)
        session.end_turn()                       # -> ENEMY, wave queued
        for _ in range(frames):
            host_frame(session, scene, tm, dt)
            if session.state.phase != GamePhase.ENEMY:
                break
        return session, scene

    def test_2x_spawns_the_wave_faster_than_1x(self):
        r = PHASE["speed_2x_min_round"]
        slow, _slow_scene = self._spawned_after(0, r)
        fast, _fast_scene = self._spawned_after(2, r)
        # Same round -> same wave size, but after the same number of wall-clock
        # frames the 2x run has drained MORE of the queue (fewer left pending).
        self.assertLess(len(fast.spawner.pending()),
                        len(slow.spawner.pending()))

    def test_pause_freezes_the_wave(self):
        session, scene, tm = build_session()
        session.state.round_num = 1
        end_turn_past_any_intro(session)
        queued = len(session.spawner.pending())
        self.assertGreater(queued, 0)
        session.set_combat_speed(PAUSE_SPEED_IDX)
        for _ in range(60):
            host_frame(session, scene, tm, 0.05)
        # Nothing spawned, nothing moved, and the round never advanced.
        self.assertEqual(len(session.spawner.pending()), queued)
        self.assertEqual(scene.by_tag("enemy"), [])
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

    def test_speed_does_not_scale_the_round_end_timer(self):
        # A no-spawn map ends the wave immediately; the ROUND_END timer must
        # then run on REAL time even with 2x selected (prototype scales only
        # the enemy tick).
        session, scene, tm = build_session(rows=("bbb",))  # no spawn tile
        session.state.round_num = PHASE["speed_2x_min_round"]
        session.set_combat_speed(2)
        session.end_turn()
        host_frame(session, scene, tm, 0.01)              # wave clears at once
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)
        timer0 = session.state.phase_timer
        host_frame(session, scene, tm, 0.1)
        self.assertAlmostEqual(session.state.phase_timer, timer0 - 0.1)


class TestQuickSkip(unittest.TestCase):
    def test_p_skip_clears_the_wave_and_ends_the_round(self):
        session, scene, tm = build_session()
        end_turn_past_any_intro(session)
        for _ in range(20):                       # let a few enemies spawn
            host_frame(session, scene, tm, 0.1)
        self.assertTrue(scene.by_tag("enemy"))

        session.quick_skip_combat(scene)
        scene.update(0.0)                         # apply the despawns
        self.assertEqual(scene.by_tag("enemy"), [])
        self.assertEqual(session.spawner.pending(), [])
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)
        self.assertAlmostEqual(session.state.phase_timer,
                               PHASE["round_end_delay"])

    def test_quick_skip_pays_no_xp(self):
        # Unlike a lives-breach wipe (which pays the QUEUED enemies), the
        # prototype's P-skip awards nothing at all.
        session, scene, tm = build_session()
        session.end_turn()
        for _ in range(20):
            host_frame(session, scene, tm, 0.1)
        xp0 = session.state.player_xp
        session.quick_skip_combat(scene)
        self.assertEqual(session.state.player_xp, xp0)

    def test_quick_skip_outside_the_enemy_phase_is_a_noop(self):
        session, scene, tm = build_session()
        self.assertEqual(session.state.phase, GamePhase.BUILDING)
        session.quick_skip_combat(scene)
        self.assertEqual(session.state.phase, GamePhase.BUILDING)

    def test_quick_skip_frozen_on_game_over(self):
        session, scene, tm = build_session()
        end_turn_past_any_intro(session)
        session.state.state = GameState.GAME_OVER
        session.quick_skip_combat(scene)
        self.assertEqual(session.state.phase, GamePhase.ENEMY)  # untouched


if __name__ == "__main__":
    unittest.main()
