"""Top-down scenario runs: the game, played headlessly, behaves like the game.

FP-5 of ``planning/completed plans/TestFixturePinningPLAN.md``. Where the unit suites pin one
subsystem each, these boots RUN the product loop end to end — spawner, flow
field, movement, combat sweep, phase machine, payday — and assert only
INVARIANTS a designer must be free to retune around: enemies reach an
undefended hole, defenders kill things and XP flows, musicians net love, the
round loop survives all the way to game over. No tunable value is asserted;
everything reads the pinned fixture (never live ``data/``).

Machinery mirrors ``test_combat_speed``'s ``host_frame`` — the exact
``game/main.py`` wiring, including both combat callbacks — with a seeded rng
per the game-package rule ("seed the RNG in any test whose outcome depends on
it").
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, resolve_combat
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_session(rows):
    tm = synth(list(rows))
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD, occupancy=occ,
                             rng=random.Random(20260714))
    return session, scene, tm, occ


def host_frame(session, scene, tm, dt):
    """One frame, wired exactly like ``game/main.py``."""
    sim_dt = (dt * session.combat_speed
              if session.state.phase == GamePhase.ENEMY else dt)
    session.pre_sim(sim_dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(sim_dt)
        resolve_combat(scene, tm, sim_dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death)
        session.post_sim(scene)


def run_wave(session, scene, tm, budget=4000, dt=0.1):
    """end_turn, then frame until the wave resolves (or the budget proves it
    never did — a failure worth failing on, not hanging on). Resolves any
    modal (LEVELUP / BOSS_CUTSCENE) with its first option so multi-round
    scenarios can keep driving the loop like a player would."""
    session.end_turn()
    st = session.state
    for _ in range(budget):
        host_frame(session, scene, tm, dt)
        if st.phase == GamePhase.LEVELUP:
            session.resolve_levelup(st.levelup_options[0], scene)
        elif st.phase == GamePhase.BOSS_CUTSCENE:
            session.resolve_boss_cutscene("A", scene)
        elif st.state == GameState.GAME_OVER:
            return
        elif st.phase == GamePhase.BUILDING:
            return
    raise AssertionError(
        f"wave never resolved within {budget} frames: phase={st.phase}, "
        f"pending={len(session.spawner.pending())}, "
        f"live={sum(e.alive for e in scene.by_tag('enemy'))}")


class TestUndefendedHoleFalls(unittest.TestCase):
    """Spawn -> flow field -> movement -> base breach, with nothing in the way."""

    def test_enemies_cross_the_map_and_cost_a_life(self):
        session, scene, tm, _ = build_session(["bbs"])
        st = session.state
        session.end_turn()
        self.assertGreater(len(session.spawner.pending()), 0,
                           "precondition: round 1 must queue a wave")
        lives0 = st.base_lives
        for _ in range(4000):
            host_frame(session, scene, tm, 0.1)
            if st.base_lives < lives0 or st.state == GameState.GAME_OVER:
                break
        self.assertLess(st.base_lives, lives0,
                        "no enemy ever reached an undefended base")

    def test_lives_run_out_into_game_over_and_the_world_freezes(self):
        session, scene, tm, _ = build_session(["bbs"])
        st = session.state
        for _ in range(st.base_lives + 3):        # breaches end rounds early
            run_wave(session, scene, tm)
            if st.state == GameState.GAME_OVER:
                break
        self.assertEqual(st.state, GameState.GAME_OVER)
        self.assertEqual(st.base_lives, 0)
        # Frozen: no phase movement, no round movement, from here on.
        phase, round_num = st.phase, st.round_num
        for _ in range(20):
            host_frame(session, scene, tm, 1.0)
        self.assertEqual((st.phase, st.round_num), (phase, round_num))


class TestDefendedHoleFights(unittest.TestCase):
    """A gauntlet of defenders on a long corridor: enemies die, XP flows."""

    def _gauntlet(self):
        session, scene, tm, occ = build_session(
            ["bbbbbbbbbs",
             "bbbbbbbbbb"])
        for col in (1, 3, 5, 7):                  # towers beside the corridor
            place_building(tm, tm.get(col, 1), "defence", 10 ** 6, BUILD,
                           scene, occ)
        scene.update(0.0)                         # flush placement spawns
        return session, scene, tm

    def test_defenders_kill_and_xp_flows(self):
        session, scene, tm = self._gauntlet()
        st = session.state
        run_wave(session, scene, tm)
        self.assertGreater(st.enemies_killed, 0, "the gauntlet killed nothing")
        self.assertGreater(st.player_xp + (st.village_level - 1), 0,
                           "kills paid no XP (level-ups bank surplus)")

    def test_the_gauntlet_holds_the_first_wave(self):
        session, scene, tm = self._gauntlet()
        st = session.state
        lives0 = st.base_lives
        run_wave(session, scene, tm)
        self.assertEqual(st.base_lives, lives0,
                         "a round-1 wave broke through four towers")
        self.assertEqual(st.state, GameState.GAMEPLAY)


class TestEconomyFlows(unittest.TestCase):
    """Payday through the REAL loop: an empty-wave round still pays, and a
    musician leaves the village strictly richer than the same round without
    one — the product invariant, not the payday arithmetic (that is
    ``test_phase_loop``'s job)."""

    def _one_empty_round(self, with_musician):
        session, scene, tm, occ = build_session(["bbb"])   # no spawn tile
        if with_musician:
            place_building(tm, tm.get(1, 0), "economic", 10 ** 6, BUILD,
                           scene, occ)
            scene.update(0.0)
        love0 = session.state.love
        run_wave(session, scene, tm)
        self.assertEqual(session.state.round_num, 2)
        return session.state.love - love0

    def test_a_round_pays_the_village(self):
        self.assertGreater(self._one_empty_round(with_musician=False), 0)

    def test_a_musician_earns_its_keep(self):
        self.assertGreater(self._one_empty_round(with_musician=True),
                           self._one_empty_round(with_musician=False))


class TestTheLoopKeepsTurning(unittest.TestCase):
    """Three full rounds through the real machine — phases come back around,
    the round counter climbs, and the run stays alive."""

    def test_three_rounds_back_to_back(self):
        session, scene, tm = TestDefendedHoleFights._gauntlet(self)
        st = session.state
        for expected_round in (2, 3, 4):
            run_wave(session, scene, tm)
            self.assertEqual(st.state, GameState.GAMEPLAY)
            self.assertEqual(st.phase, GamePhase.BUILDING)
            self.assertEqual(st.round_num, expected_round)


if __name__ == "__main__":
    unittest.main()
