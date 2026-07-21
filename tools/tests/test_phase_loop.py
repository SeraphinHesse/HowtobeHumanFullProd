"""Phase 9F: round loop — phase machine + payday ordering + game over.

Pure-Python, headless (no SDL) — mirrors the 9C/9D/9E map/building/enemy tests:
a synth ``TileMapDoc`` -> ``TileMap`` fixture + real balancing via
``load_balance``. Two deterministic tricks keep the ledger tests free of enemy
timing: a map with NO spawn tile makes every wave empty (rounds still complete
BUILDING -> ENEMY -> ROUND_END -> INCOME -> BUILDING), and base-breach logic is
exercised through the same ``on_base_hit`` callback the combat sweep calls.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats
from game.core import RunState, Session, load_balance, run_payday
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.components import PathAgent
from game.map.tile_map import TileMap
from game.tutorial.director import TutorialDirector

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

HOLE = CORE["TheHole"]
PHASE = CORE["PhaseLoop"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows):
    """A synth board with the base attached; returns (tilemap, scene, occ)."""
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def host_frame(session, scene, tilemap_, dt):
    """One host frame — the EXACT call order + GAME_OVER gate game/main.py uses:
    the world sim (scene.update + combat) only runs while GAMEPLAY, so on
    GAME_OVER the world freezes instead of enemies walking into the hole. The
    ENEMY phase runs on the combat-speed-scaled dt (10F; 1× by default, so this
    is a no-op for every test that never touches the speed)."""
    sim_dt = (dt * session.combat_speed
              if session.state.phase == GamePhase.ENEMY else dt)
    session.pre_sim(sim_dt, scene)
    if session.state.state == GameState.GAMEPLAY:
        scene.update(sim_dt)
        resolve_combat(scene, tilemap_, sim_dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit)
        session.post_sim(scene)


def frame(session, scene, tilemap_, dt):
    """Like ``host_frame`` but ungated — used by GAMEPLAY-phase tests where the
    gate is a no-op (state is always GAMEPLAY there)."""
    session.pre_sim(dt, scene)
    scene.update(dt)
    resolve_combat(scene, tilemap_, dt, BUILD, VFX, on_base_hit=session.on_base_hit)
    session.post_sim(scene)


# ---------------------------------------------------------------------------
class TestRunState(unittest.TestCase):
    def test_seeded_from_core_balance(self):
        st = RunState.from_balance(CORE, BUILD)
        self.assertEqual(st.love, CORE["General"]["starting_currency"])
        self.assertEqual(st.base_lives, HOLE["base_lives"])
        self.assertEqual(st.round_num, 1)          # prototype inits round 1
        self.assertEqual(st.phase, GamePhase.BUILDING)
        self.assertEqual(st.state, GameState.GAMEPLAY)

    def test_love_clamps_at_zero(self):
        st = RunState.from_balance(CORE, BUILD)
        st.spend_love(st.love + 100)
        self.assertEqual(st.love, 0)
        st.add_love(7)
        self.assertEqual(st.love, 7)


# ---------------------------------------------------------------------------
# Payday ordering (prototype _begin_income_phase)
# ---------------------------------------------------------------------------
class TestPayday(unittest.TestCase):
    def _board(self):
        tm, scene, occ = build_board(["bbb"])  # base(0,0), (1,0)/(2,0) buildable
        musician, _ = place_building(tm, tm.get(1, 0), "economic", 9999,
                                     BUILD, scene, occ)
        defender, _ = place_building(tm, tm.get(2, 0), "defence", 9999,
                                     BUILD, scene, occ)
        return tm, musician, defender

    def test_income_yield_upkeep_and_round_advance(self):
        tm, musician, defender = self._board()
        st = RunState.from_balance(CORE, BUILD)
        love0 = st.love
        net = HOLE["base_income"] + musician.yield_amount() - defender.upkeep()

        run_payday(st, tm, CORE)

        self.assertEqual(st.love, love0 + net)
        self.assertEqual(st.round_num, 2)
        self.assertEqual(st.phase, GamePhase.INCOME)
        self.assertAlmostEqual(st.phase_timer, PHASE["income_phase_duration"])

    def test_roundstats_snapshot_rolls_over(self):
        tm, _musician, defender = self._board()
        defender.get_component(RoundStats).dmg_dealt_this_round = 37
        st = RunState.from_balance(CORE, BUILD)

        run_payday(st, tm, CORE)

        rs = defender.get_component(RoundStats)
        self.assertEqual(rs.dmg_dealt_last_round, 37)
        self.assertEqual(rs.dmg_dealt_this_round, 0)

    def test_dead_building_revives_and_pays_no_upkeep(self):
        tm, musician, defender = self._board()
        defender.get_component(Health).hp = 0
        self.assertFalse(defender.alive)
        st = RunState.from_balance(CORE, BUILD)
        love0 = st.love

        run_payday(st, tm, CORE)

        # Dead defender: no upkeep charged; revived to full HP by the sweep.
        self.assertEqual(st.love, love0 + HOLE["base_income"]
                         + musician.yield_amount())
        self.assertTrue(defender.alive)
        self.assertEqual(defender.get_component(Health).hp,
                         defender.get_component(Health).max_hp)

    def test_base_never_revives(self):
        tm, _m, _d = self._board()
        base = tm.get(tm.base_col, tm.base_row).occupant
        base.get_component(Health).hp = 0
        run_payday(RunState.from_balance(CORE, BUILD), tm, CORE)
        self.assertFalse(base.alive)  # base excluded from the revive sweep


# ---------------------------------------------------------------------------
# Phase machine + multi-round currency ledger (the phase Quick Test)
# ---------------------------------------------------------------------------
class TestPhaseMachine(unittest.TestCase):
    def _session(self, rows):
        # No 's' in the terrain -> no spawn tiles -> every wave is empty, so the
        # loop runs on pure timers with zero combat/timing flakiness.
        tm, scene, occ = build_board(rows)
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        return session, scene, tm, occ

    def test_end_turn_only_from_building(self):
        session, scene, tm, _ = self._session(["bb"])
        session.state.phase = GamePhase.ENEMY
        session.end_turn()  # ignored — not in BUILDING
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

    def test_full_round_cycles_back_to_building(self):
        session, scene, tm, _ = self._session(["bb"])
        self.assertEqual(session.state.phase, GamePhase.BUILDING)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        # Empty wave -> clears on the first post_sim.
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)
        # Ride the ROUND_END then INCOME timers back to BUILDING.
        for _ in range(60):
            frame(session, scene, tm, 0.1)
            if session.state.phase == GamePhase.BUILDING:
                break
        self.assertEqual(session.state.phase, GamePhase.BUILDING)
        self.assertEqual(session.state.round_num, 2)

    def test_three_round_currency_ledger(self):
        session, scene, tm, occ = self._session(["bbb"])
        musician, _ = place_building(tm, tm.get(1, 0), "economic", 9999,
                                     BUILD, scene, occ)
        defender, _ = place_building(tm, tm.get(2, 0), "defence", 9999,
                                     BUILD, scene, occ)
        love0 = session.state.love
        net = HOLE["base_income"] + musician.yield_amount() - defender.upkeep()

        for expected_round in (2, 3, 4):
            session.end_turn()
            for _ in range(80):  # >> round_end_delay + income_phase_duration
                frame(session, scene, tm, 0.1)
                if (session.state.phase == GamePhase.BUILDING
                        and session.state.round_num == expected_round):
                    break
            self.assertEqual(session.state.round_num, expected_round)
            self.assertEqual(session.state.phase, GamePhase.BUILDING)

        self.assertEqual(session.state.love, love0 + 3 * net)
        self.assertEqual(session.state.round_num, 4)


# ---------------------------------------------------------------------------
# Base breach: lives + game over + world freeze
# ---------------------------------------------------------------------------
class TestGameOverLives(unittest.TestCase):
    def _enemy(self, tm, scene, col, row):
        e = create_enemy("standard", col, row, ENEM, tm)
        scene.spawn(e)
        return e

    def test_life_lost_and_round_wiped_on_breach(self):
        # base(0,0), spawn(1,0) adjacent -> the enemy reaches the base fast.
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        session.state.phase = GamePhase.ENEMY   # pretend a wave is live
        lives0 = session.state.base_lives
        # Two enemies inbound; only ONE breach is processed, then the round wipes.
        self._enemy(tm, scene, 1, 0)
        self._enemy(tm, scene, 1, 0)

        for _ in range(200):
            frame(session, scene, tm, 0.1)
            if session.state.phase != GamePhase.ENEMY:
                break
        else:
            self.fail("enemy never breached the base")

        scene.update(0.0)  # flush the wipe's queued despawns
        self.assertEqual(session.state.base_lives, lives0 - 1)  # exactly one life
        self.assertEqual(scene.by_tag("enemy"), [])             # round wiped
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)
        self.assertEqual(session.state.state, GameState.GAMEPLAY)

    def test_game_over_at_zero_lives_freezes_world(self):
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        session.state.base_lives = 1
        session.state.phase = GamePhase.ENEMY

        class _Dummy:
            dmg = 5
        session.on_base_hit(_Dummy())   # last life -> game over

        self.assertEqual(session.state.base_lives, 0)
        self.assertEqual(session.state.state, GameState.GAME_OVER)

        # Frozen: end_turn + pre/post_sim do nothing, love/phase unchanged.
        love0, phase0 = session.state.love, session.state.phase
        session.end_turn()
        frame(session, scene, tm, 5.0)
        self.assertEqual(session.state.state, GameState.GAME_OVER)
        self.assertEqual(session.state.love, love0)
        self.assertEqual(session.state.phase, phase0)

    def test_world_frozen_after_game_over_live_loop(self):
        # Regression (live bug): with the real host loop, once GAME_OVER fires
        # the world must FREEZE — enemies stop, no more base hits, lives never
        # go negative. Before the main.py gate, scene.update + resolve_combat
        # ran every frame regardless of state, so queued enemies kept reaching
        # the hole and drove base_lives below 0.
        tm, scene, occ = build_board(["bss"])   # base(0,0), spawn(1,0)/(2,0)
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        session.state.base_lives = 1            # next breach ends the game
        session.state.phase = GamePhase.ENEMY
        # A crowd inbound: one breach ends the game; the rest must NOT keep
        # hitting the base afterward.
        for _ in range(4):
            self._enemy(tm, scene, 1, 0)
            self._enemy(tm, scene, 2, 0)

        for _ in range(200):
            host_frame(session, scene, tm, 0.1)
            if session.state.state == GameState.GAME_OVER:
                break
        else:
            self.fail("game never reached GAME_OVER")

        self.assertEqual(session.state.base_lives, 0)
        survivors = list(scene.by_tag("enemy"))
        positions = [e.transform.world_pos for e in survivors]
        # Keep driving frames — the frozen world must not move enemies, despawn
        # them, or take another life.
        for _ in range(50):
            host_frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.state, GameState.GAME_OVER)
        self.assertEqual(session.state.base_lives, 0)     # never negative
        self.assertEqual(len(scene.by_tag("enemy")), len(survivors))  # frozen
        self.assertEqual(
            [e.transform.world_pos for e in survivors], positions)

    def test_on_base_hit_guard_blocks_negative_lives(self):
        # Defense in depth: even if a stray arrival is fed to on_base_hit after
        # GAME_OVER (e.g. a caller without the gate), lives never go negative.
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        session.state.base_lives = 1
        session.state.phase = GamePhase.ENEMY

        class _Dummy:
            dmg = 5
        for _ in range(10):
            session.on_base_hit(_Dummy())
        self.assertEqual(session.state.state, GameState.GAME_OVER)
        self.assertEqual(session.state.base_lives, 0)   # clamped, never -9


class TestScriptedTutorialLoss(unittest.TestCase):
    """TU-7: ``Session.on_base_hit``'s free-loss waiver +
    ``_begin_round_end``'s ``on_round_end`` notification, driven against a
    real ``TutorialDirector`` walked to round 1's scripted-loss step via fake
    events (the test_tutorial_director.py convention). Reuses this module's
    ``build_board``/``frame`` harness rather than a new one."""

    _FLUTE = {"col": 2, "row": 3}
    _STONE = {"col": 4, "row": 1}

    def _map_doc(self):
        return tilemap.TileMapDoc(
            map_id="tut", display_name="Tut", cols=6, rows=6,
            legend={}, terrain=[list("bbbbbb") for _ in range(6)],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            tutorial_flute=self._FLUTE, tutorial_stone=self._STONE)

    def _director(self, data_dir=FIXTURE_DATA):
        return TutorialDirector(data_dir, self._map_doc(),
                                {"economy_buildings_required": 1})

    def _free_first_loss_data_dir(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = fixture_copy(Path(tmp.name))
        script_path = data_dir / "tutorial" / "tutorial.json"
        doc = json.loads(script_path.read_text(encoding="utf-8"))
        doc["first_loss_costs_life"] = False
        script_path.write_text(json.dumps(doc), encoding="utf-8")
        return data_dir

    def _walk_round_one(self, d):
        """Fake events for the round-1 flute chain, ending on round-2's
        "wait for the scripted loss" step."""
        d.on_message_dismissed()
        d.on_tile_clicked(self._FLUTE["col"], self._FLUTE["row"])
        d.on_card_selected("economic")
        d.on_building_placed("economic")
        d.on_end_turn()

    def _enemy(self, tm, scene, col, row):
        e = create_enemy("standard", col, row, ENEM, tm)
        scene.spawn(e)
        return e

    def _run_round_one_breach(self, director):
        # base(0,0), spawn(1,0) adjacent -> the enemy reaches the base fast.
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        session.tutorial_director = director
        self._walk_round_one(director)
        session.state.phase = GamePhase.ENEMY   # pretend a wave is live
        self._enemy(tm, scene, 1, 0)

        for _ in range(200):
            frame(session, scene, tm, 0.1)
            if session.state.phase != GamePhase.ENEMY:
                break
        else:
            self.fail("enemy never breached the base")
        scene.update(0.0)  # flush the wipe's queued despawns
        return session

    def test_first_loss_costs_life_true_ends_round_with_two_lives(self):
        director = self._director()
        session = self._run_round_one_breach(director)
        self.assertEqual(session.state.base_lives, 2)  # down from seeded 3
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)

    def test_first_loss_costs_life_false_keeps_three_lives(self):
        director = self._director(data_dir=self._free_first_loss_data_dir())
        session = self._run_round_one_breach(director)
        self.assertEqual(session.state.base_lives, 3)  # waived, unchanged
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)

    def test_message_box_two_appears_at_round_end_via_real_wiring(self):
        director = self._director()
        self._run_round_one_breach(director)
        self.assertTrue(director.message_visible)
        self.assertIn("You have only 3 lives", director.message_text())

    def test_a_repeated_round_end_notification_is_a_no_op(self):
        # Defense in depth: nothing in the real host loop calls
        # _begin_round_end twice for the same round, but the director must
        # never charge/advance twice if it somehow did.
        director = self._director()
        session = self._run_round_one_breach(director)
        lives_after = session.state.base_lives
        message_after = director.message_text()
        director.on_round_end(session.state.round_num)
        self.assertEqual(session.state.base_lives, lives_after)
        self.assertEqual(director.message_text(), message_after)

    def test_skipped_tutorial_never_shows_boxes_but_still_gets_cutscene(self):
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        director = self._director()
        director.skip()  # the player pressed Skip on message box #1
        session.tutorial_director = director
        self.assertFalse(director.message_visible)

        session.end_turn()  # round 1's End Turn: the TU-5 cutscene request
        self.assertEqual(session.state.pending_cutscene,
                         {"id": "first_end_turn"})

        session.state.phase = GamePhase.ENEMY
        self._enemy(tm, scene, 1, 0)
        for _ in range(200):
            frame(session, scene, tm, 0.1)
            if session.state.phase != GamePhase.ENEMY:
                break
        else:
            self.fail("enemy never breached the base")
        scene.update(0.0)
        # a skipped/finished director never shows message box #2 either, and
        # normal life rules apply (no waiver once finished).
        self.assertFalse(director.message_visible)
        self.assertEqual(session.state.base_lives, 2)


# ---------------------------------------------------------------------------
class TestPurity(unittest.TestCase):
    def test_game_core_imports_no_pygame(self):
        code = ("import sys; import game.core; "
                "assert 'pygame' not in sys.modules, 'pygame leaked into game.core'")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
