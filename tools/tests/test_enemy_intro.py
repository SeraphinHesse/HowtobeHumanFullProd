"""feature-enemy-intro-dialogue: the ENEMY_INTRO phase machine.

Pure-Python, headless — the ``test_lightning.py``/``test_boss.py`` fixture
style: a synth ``TileMapDoc`` -> ``TileMap`` board + real balancing via
``load_balance``. ``core.json``'s ``EnemyIntro.entries`` ships empty in the
fixture (as in live data), so each test that needs a match builds its own
deep-copied ``core_balance`` with entries injected — never mutates the
module-level fixture dict shared across tests.
"""
import copy
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
from game.enemies import Spawner
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")

_MOCK_ENTRY = {
    "enemy_label": "Test Enemy", "round": 1, "title": "Test title",
    "body": "Test body.", "sprite_slot": "enemy_stage_1_v1",
    "sprite_w": 96, "sprite_h": 96,
}


def _core_with_entries(*rounds):
    """A deep copy of the fixture's core balance with one EnemyIntro entry
    per given round number (never mutates the shared module-level CORE)."""
    core = copy.deepcopy(CORE)
    core["EnemyIntro"]["entries"] = [
        {**_MOCK_ENTRY, "round": r} for r in rounds]
    return core


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_session(core_balance, rng=None):
    tm = synth(["cccc"] * 4)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, core_balance),
                scene, occ)
    session = Session.create(Spawner(), tm, ENEM, core_balance, BUILD,
                             rng=rng or random.Random(1), occupancy=occ)
    return session, scene


class TestNoMatchingEntries(unittest.TestCase):
    """An empty entries list (schema minItems is 1, but never rely on that —
    pin the fixture explicitly rather than reading live/fixture content) is
    byte-identical to before the feature existed."""

    def test_end_turn_enters_enemy_directly(self):
        core = _core_with_entries()  # no rounds -> entries == []
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])
        self.assertFalse(session.frozen)


class TestOneMatchingEntry(unittest.TestCase):
    def setUp(self):
        self.core = _core_with_entries(1)  # RunState.from_balance starts round 1
        self.session, self.scene = build_session(self.core)

    def test_end_turn_queues_it_and_enters_enemy_intro(self):
        self.session.end_turn()
        st = self.session.state
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertEqual(st.pending_enemy_intros[0]["round"], 1)

    def test_frozen_covers_enemy_intro(self):
        self.session.end_turn()
        self.assertTrue(self.session.frozen)

    def test_pre_sim_does_not_drain_the_wave_while_frozen(self):
        """The wave is already queued by begin_round() (inside end_turn()),
        but pre_sim must not spawn anything onto the field until the phase
        actually reaches ENEMY."""
        self.session.end_turn()
        before = len(self.session.spawner.pending())
        for _ in range(5):
            self.session.pre_sim(0.5, self.scene)
        self.assertEqual(len(self.session.spawner.pending()), before)
        self.assertEqual(len(self.scene.by_tag("enemy")), 0)

    def test_resolve_enemy_intro_drains_the_queue_and_starts_the_round(self):
        self.session.end_turn()
        self.session.resolve_enemy_intro()
        st = self.session.state
        self.assertEqual(st.pending_enemy_intros, [])
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertFalse(self.session.frozen)


class TestQueuedEntries(unittest.TestCase):
    """Two entries sharing the same round both fire, one after another."""

    def test_both_entries_queue_on_the_same_round(self):
        core = _core_with_entries(1, 1)
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY_INTRO)
        self.assertEqual(len(session.state.pending_enemy_intros), 2)

    def test_resolve_enemy_intro_pops_one_at_a_time(self):
        core = _core_with_entries(1, 1)
        session, _scene = build_session(core)
        session.end_turn()
        session.resolve_enemy_intro()
        st = session.state
        self.assertEqual(len(st.pending_enemy_intros), 1)
        self.assertEqual(st.phase, GamePhase.ENEMY_INTRO)  # queue not drained yet
        session.resolve_enemy_intro()
        self.assertEqual(st.pending_enemy_intros, [])
        self.assertEqual(st.phase, GamePhase.ENEMY)

    def test_resolve_enemy_intro_is_a_safe_no_op_once_drained(self):
        core = _core_with_entries(1)
        session, _scene = build_session(core)
        session.end_turn()
        session.resolve_enemy_intro()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        session.resolve_enemy_intro()  # nothing queued — must not raise/misbehave
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])


class TestNonMatchingRound(unittest.TestCase):
    def test_entry_for_a_later_round_does_not_fire_on_round_one(self):
        core = _core_with_entries(2)  # round 1 is what end_turn() will see first
        session, _scene = build_session(core)
        session.end_turn()
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertEqual(session.state.pending_enemy_intros, [])


if __name__ == "__main__":
    unittest.main()
