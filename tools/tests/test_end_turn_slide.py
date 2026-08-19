"""The End Turn button rides off the bottom edge for the combat half of the
round and rides back up at PAYDAY (``GamePhase.INCOME``).

Pure + headless — it reuses ``test_life_counters.py``'s synth-board fixture
(a real ``Session`` + a real ``Hud``) rather than standing up a second one.
Only the BUTTON moves: the round + phase labels stacked above it are anchored
off its HOME rect, so they must stay put through the whole ride.
"""
import unittest

from game.core.phases import GamePhase
from game.ui.hud import _END_TURN_SLIDE_SEC

from tools.tests.test_life_counters import DT, VIEW_H, VIEW_W, _Recorder, build


def settle(hud, session, panel, phase, seconds):
    session.state.phase = phase
    for _ in range(int(seconds / DT) + 2):
        hud.update(DT, 0, 0, session, panel)
    hud.submit(_Recorder(), session, VIEW_W, VIEW_H)


class TestEndTurnSlide(unittest.TestCase):
    def test_home_in_building_and_gone_in_combat(self):
        session, panel, hud = build()
        settle(hud, session, panel, GamePhase.BUILDING, _END_TURN_SLIDE_SEC)
        home = hud.end_turn.rect
        self.assertEqual(home[1] + home[3], VIEW_H - 8)  # the 8px bottom margin

        settle(hud, session, panel, GamePhase.ENEMY, _END_TURN_SLIDE_SEC)
        self.assertGreaterEqual(hud.end_turn.rect[1], VIEW_H)
        self.assertEqual(hud.end_turn.rect[0], home[0])  # straight down only

    def test_payday_brings_it_back(self):
        session, panel, hud = build()
        settle(hud, session, panel, GamePhase.BUILDING, _END_TURN_SLIDE_SEC)
        home = hud.end_turn.rect
        settle(hud, session, panel, GamePhase.ENEMY, _END_TURN_SLIDE_SEC)
        settle(hud, session, panel, GamePhase.INCOME, _END_TURN_SLIDE_SEC)
        self.assertEqual(hud.end_turn.rect, home)

    def test_it_is_mid_ride_halfway_through(self):
        session, panel, hud = build()
        settle(hud, session, panel, GamePhase.BUILDING, _END_TURN_SLIDE_SEC)
        home_y = hud.end_turn.rect[1]
        settle(hud, session, panel, GamePhase.ENEMY, _END_TURN_SLIDE_SEC / 2)
        y = hud.end_turn.rect[1]
        self.assertGreater(y, home_y)
        self.assertLess(y, VIEW_H)

    def test_the_labels_above_it_never_move(self):
        session, panel, hud = build()
        settle(hud, session, panel, GamePhase.BUILDING, _END_TURN_SLIDE_SEC)
        anchors = (hud._round_label.rect, hud._phase_label.rect)
        settle(hud, session, panel, GamePhase.ENEMY, _END_TURN_SLIDE_SEC)
        self.assertEqual((hud._round_label.rect, hud._phase_label.rect), anchors)
