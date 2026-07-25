"""Phase TU-5/TU-9: Session.end_turn()'s pending_cutscene request semantics.

Pure-Python, headless (no SDL) — mirrors tools/tests/test_phase_loop.py's
synth/build_board fixture pattern. TU-9 re-keyed the "exactly once" rule off
``RunState.first_end_turn_cutscene_requested`` (a one-shot latch) rather than
``round_num == 1`` directly, so the cutscene still fires on the FIRST
``end_turn()`` of a run whether that round is 0 (an active tutorial) or 1 (a
skipped run) — and never again after that, regardless of round number.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase
from game.enemies import Spawner
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows):
    tm = synth(rows)
    from engine.core import Scene
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def _session(rows=("bb",)):
    tm, scene, occ = build_board(list(rows))
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
    return session


class TestPendingCutsceneRequest(unittest.TestCase):
    def test_round_one_end_turn_requests_first_end_turn(self):
        """A skipped run continues at round 1 (a bare Session's default) —
        the cutscene still fires on its first End Turn."""
        session = _session()
        self.assertEqual(session.state.round_num, 1)
        self.assertIsNone(session.state.pending_cutscene)

        session.end_turn()

        self.assertEqual(session.state.pending_cutscene,
                         {"id": "first_end_turn"})
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        self.assertTrue(session.state.first_end_turn_cutscene_requested)

    def test_round_zero_end_turn_also_requests_first_end_turn(self):
        """TU-9: an active tutorial run's first End Turn is round 0's, not
        round 1's — the request must still fire there."""
        session = _session()
        session.state.round_num = 0
        self.assertIsNone(session.state.pending_cutscene)

        session.end_turn()

        self.assertEqual(session.state.pending_cutscene,
                         {"id": "first_end_turn"})
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

    def test_later_round_end_turn_never_requests_it(self):
        """Once the run's first End Turn has fired the request (here, round
        0's — the tutorial), a later round's End Turn never re-requests it,
        even though round_num no longer equals the round that fired it."""
        session = _session()
        session.state.round_num = 0
        session.end_turn()
        self.assertIsNotNone(session.state.pending_cutscene)
        session.state.pending_cutscene = None  # host "consumed" it

        session.state.phase = GamePhase.BUILDING
        session.state.round_num = 3
        session.end_turn()
        self.assertIsNone(session.state.pending_cutscene)

    def test_wave_still_begins_on_round_one(self):
        """The request is queued BEFORE spawner.begin_round(), which still
        runs unconditionally — the host visually withholds the wave by
        freezing, the wave itself is not skipped."""
        session = _session(("bs",))  # a spawn tile ('s') so the wave is non-empty
        session.end_turn()
        self.assertTrue(session.spawner.active)

    def test_end_turn_noop_outside_building_phase_leaves_request_unset(self):
        session = _session()
        session.state.phase = GamePhase.ENEMY
        session.end_turn()  # ignored — not in BUILDING
        self.assertIsNone(session.state.pending_cutscene)


if __name__ == "__main__":
    unittest.main()
