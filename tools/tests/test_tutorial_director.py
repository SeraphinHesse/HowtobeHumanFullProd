"""``game.tutorial.director.TutorialDirector`` tests (Phase TU-6) — fake
events driven through the real ``data/tutorial/tutorial.json`` shipped
content, read through the pinned FIXTURE_DATA snapshot (never live data/, the
test_tutorial_data.py convention). Headless, pure Python — no pygame.

TU-7 extends this module with the round-2 stone-thrower chain, the scripted
first-loss waiver and the tutorial-end state (``TestRoundTwoChain``,
``TestScriptedLossWaiver`` below).

TU-8 extends it further with the panel-close revert (Fix 1) and the
close-panel-hint step (Fix 2) — ``TestPanelClosedRevert``,
``TestClosePanelHintStep`` below. ``_walk_round_one`` now also drives the new
``on_panel_closed()`` call the close-panel-hint step needs to reach End Turn.
"""
import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from engine import tilemap
from game.tutorial.director import TutorialDirector
from tools.tests.fixture_data import FIXTURE_DATA, fixture_copy

_FLUTE = {"col": 2, "row": 3}
_STONE = {"col": 4, "row": 1}  # TU-7

MSG_LIVES_INTRO = (
    "Once the humans reach our hole the round is lost. You have only 3 "
    "lives. If economy buildings get destroyed during the human attack "
    "they don't yield resources. To defend your base you need to build "
    "defense buildings")


def _map_doc(flute=_FLUTE, stone=_STONE):
    return tilemap.TileMapDoc(
        map_id="synth", display_name="Synth", cols=6, rows=6,
        legend={}, terrain=[list("bbbbbb") for _ in range(6)],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
        tutorial_flute=flute, tutorial_stone=stone)


def _director(flute=_FLUTE, stone=_STONE, required=1, data_dir=FIXTURE_DATA):
    return TutorialDirector(data_dir, _map_doc(flute, stone),
                            {"economy_buildings_required": required})


MSG_CLOSE_PANEL_HINT = "right click anywhere to close"


def _walk_round_one(d):
    """Drives the real fake-event sequence game/main.py feeds for the round-1
    flute chain (TestGuidedChain.test_full_chain, condensed) so round-2 tests
    can start from "round 1 just ended". TU-8: includes the close-panel-hint
    step's ``on_panel_closed()`` between placement and End Turn."""
    d.on_message_dismissed()
    d.on_tile_clicked(_FLUTE["col"], _FLUTE["row"])
    d.on_card_selected("economic")
    d.on_building_placed("economic")
    d.on_panel_closed()  # TU-8: advances past the close-panel-hint step
    d.on_end_turn()


class FakePanel:
    """Minimal card_rect/confirm_rect/close_rect stand-in for
    ui_highlight_rects()."""

    def __init__(self, card_rects=None, confirm=None, close=None):
        self._cards = card_rects or {}
        self._confirm = confirm
        self._close = close

    def card_rect(self, building_type):
        return self._cards.get(building_type)

    def confirm_rect(self):
        return self._confirm

    def close_rect(self):  # TU-8
        return self._close


class TestAutoSkip(unittest.TestCase):
    def test_no_flute_marker_auto_skips_with_one_warning(self):
        with self.assertLogs("game.tutorial.director", level="WARNING") as cm:
            d = _director(flute=None)
        self.assertEqual(len(cm.output), 1)
        self.assertFalse(d.active)
        self.assertTrue(d.sequencer.finished)
        self.assertTrue(d.finished)
        self.assertFalse(d.message_visible)
        self.assertTrue(d.allows_end_turn())
        self.assertTrue(d.allows(("tile", 0, 0)))

    def test_missing_script_auto_skips_never_raises(self):
        with self.assertLogs("game.tutorial.director", level="WARNING"):
            d = TutorialDirector(
                FIXTURE_DATA / "does_not_exist", _map_doc(),
                {"economy_buildings_required": 1})
        self.assertFalse(d.active)
        self.assertTrue(d.finished)

    def test_auto_skipped_director_never_crashes_on_any_call(self):
        d = _director(flute=None)
        d.on_tile_clicked(0, 0)
        d.on_card_selected("economic")
        d.on_building_placed("economic")
        d.on_building_placed("defence")  # TU-7
        d.on_message_dismissed()
        d.on_end_turn()
        d.on_round_end(1)  # TU-7
        d.on_panel_closed()  # TU-8
        d.skip()  # no-op, already finished
        self.assertEqual(d.highlight_targets(), ())
        self.assertEqual(d.tile_highlight_targets(), [])
        self.assertEqual(d.ui_highlight_rects(FakePanel(), SimpleNamespace(
            end_turn=SimpleNamespace(rect=(0, 0, 0, 0)))), [])
        self.assertTrue(d.charges_life_on_base_hit(1))  # TU-7 zero-overhead
        self.assertIsNone(d.banner_text())  # TU-8 zero-overhead


class TestGuidedChain(unittest.TestCase):
    """Walks the real round-1 script end to end via fake events, exactly the
    events game/main.py feeds in response to real clicks."""

    def test_full_chain(self):
        d = _director()
        # -- step 1: the message box --
        self.assertTrue(d.message_visible)
        self.assertTrue(d.skippable())
        self.assertEqual(
            d.message_text(),
            "You need love to create. In order for you to gain Love, you "
            "need economy buildings")
        # everything is rejected while the message is up
        self.assertFalse(d.allows(("tile", 2, 3)))
        self.assertFalse(d.allows_end_turn())
        d.on_message_dismissed()
        self.assertFalse(d.message_visible)

        # -- step 2: highlight the flute tile --
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_flute",))
        self.assertEqual(d.tile_highlight_targets(), [(2, 3)])
        self.assertFalse(d.allows(("tile", 0, 0)))
        self.assertTrue(d.allows(("tile", 2, 3)))
        d.on_tile_clicked(0, 0)  # wrong tile: no-op
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_flute",))
        d.on_tile_clicked(2, 3)  # the bound marker: advances

        # -- step 3: highlight the economic (Musician) card --
        self.assertEqual(d.highlight_targets(), ("card:economic",))
        self.assertTrue(d.allows(("card", "economic")))
        self.assertFalse(d.allows(("card", "defence")))
        d.on_card_selected("defence")  # wrong card: no-op
        self.assertEqual(d.highlight_targets(), ("card:economic",))
        d.on_card_selected("economic")

        # -- step 4: highlight Confirm --
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        self.assertTrue(d.allows(("confirm",)))
        self.assertFalse(d.allows_end_turn())
        d.on_building_placed("economic")

        # -- step 4.5 (TU-8, Fix 2): highlight the panel's own Close button +
        # the non-modal banner hint; End Turn stays gated until it closes --
        self.assertEqual(d.highlight_targets(), ("button:close",))
        self.assertEqual(d.banner_text(), MSG_CLOSE_PANEL_HINT)
        self.assertFalse(d.allows_end_turn())
        d.on_end_turn()  # blocked: not the gated action on this step
        self.assertEqual(d.highlight_targets(), ("button:close",))
        d.on_panel_closed()
        self.assertIsNone(d.banner_text())

        # -- step 5: highlight End Turn --
        self.assertEqual(d.highlight_targets(), ("button:end_turn",))
        self.assertTrue(d.allows_end_turn())
        self.assertFalse(d.allows(("tile", 2, 3)))  # everything else still gated
        d.on_end_turn()

        # -- round 1 is NOT the end of the chain: TU-7's round-2 steps follow
        # seamlessly in the same script (the "wait for the scripted loss"
        # step) — see TestRoundTwoChain for the rest of the walk.
        self.assertFalse(d.finished)
        self.assertEqual(d.highlight_targets(), ())
        self.assertIsNone(d.message_text())

    def test_economy_buildings_required_counter(self):
        d = _director(required=2)
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        d.on_card_selected("economic")
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        d.on_building_placed("defence")  # never counts
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        d.on_building_placed("economic")  # 1 of 2 required
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        self.assertFalse(d.allows_end_turn())
        d.on_building_placed("economic")  # 2 of 2: unlocks the close-panel hint
        self.assertEqual(d.highlight_targets(), ("button:close",))
        self.assertFalse(d.allows_end_turn())
        d.on_panel_closed()  # TU-8: closing the panel unlocks End Turn
        self.assertEqual(d.highlight_targets(), ("button:end_turn",))
        self.assertTrue(d.allows_end_turn())

    def test_skip_ends_everything_immediately(self):
        d = _director()
        self.assertTrue(d.message_visible)
        d.skip()
        self.assertTrue(d.finished)
        self.assertFalse(d.message_visible)
        self.assertTrue(d.allows_end_turn())
        self.assertTrue(d.allows(("tile", 0, 0)))
        self.assertEqual(d.highlight_targets(), ())


class TestUiHighlightRects(unittest.TestCase):
    def test_resolves_card_confirm_close_and_end_turn(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        panel = FakePanel(card_rects={"economic": (1, 2, 3, 4)})
        hud = SimpleNamespace(end_turn=SimpleNamespace(rect=(9, 9, 9, 9)))
        self.assertEqual(d.ui_highlight_rects(panel, hud), [(1, 2, 3, 4)])

        d.on_card_selected("economic")
        panel2 = FakePanel(confirm=(5, 6, 7, 8))
        self.assertEqual(d.ui_highlight_rects(panel2, hud), [(5, 6, 7, 8)])

        d.on_building_placed("economic")
        # TU-8: the close-panel-hint step highlights button:close, not
        # button:end_turn yet
        panel3 = FakePanel(close=(2, 4, 6, 8))
        self.assertEqual(d.ui_highlight_rects(panel3, hud), [(2, 4, 6, 8)])

        d.on_panel_closed()
        self.assertEqual(d.ui_highlight_rects(panel3, hud), [(9, 9, 9, 9)])

    def test_unresolvable_target_is_skipped_not_crashed(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        panel = FakePanel(card_rects={})  # "economic" not in the panel's cards
        hud = SimpleNamespace(end_turn=SimpleNamespace(rect=(0, 0, 0, 0)))
        self.assertEqual(d.ui_highlight_rects(panel, hud), [])


class TestPanelClosedRevert(unittest.TestCase):
    """TU-8 Fix 1: ``on_panel_closed()`` un-sticks the player by reverting
    the card/Confirm steps of BOTH chains back to their own tile step."""

    def test_closing_at_the_card_step_reverts_to_the_tile_step(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        self.assertEqual(d.highlight_targets(), ("card:economic",))
        d.on_panel_closed()
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_flute",))
        self.assertTrue(d.allows(("tile", 2, 3)))
        # the tile click works again exactly like a fresh walk
        d.on_tile_clicked(2, 3)
        self.assertEqual(d.highlight_targets(), ("card:economic",))

    def test_closing_at_the_confirm_step_reverts_to_the_tile_step(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        d.on_card_selected("economic")
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        d.on_panel_closed()
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_flute",))
        self.assertTrue(d.allows(("tile", 2, 3)))

    def test_successful_placement_does_not_revert(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        d.on_card_selected("economic")
        d.on_building_placed("economic")  # a REAL placement, not a close
        # lands on the close-panel-hint step, never reverted to the tile
        self.assertEqual(d.highlight_targets(), ("button:close",))

    def test_a_panel_closed_event_outside_any_gated_step_is_a_noop(self):
        d = _director()
        d.on_message_dismissed()
        # still on the tile step, which has no revert_on -- a stray
        # panel_closed here must not move the sequencer at all
        d.on_panel_closed()
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_flute",))

    def test_stone_chain_reverts_the_same_way(self):
        d = _director()
        _walk_round_one(d)
        d.on_round_end(1)
        d.on_message_dismissed()
        d.on_tile_clicked(4, 1)
        d.on_card_selected("defence")
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        d.on_panel_closed()
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_stone",))
        self.assertTrue(d.allows(("tile", 4, 1)))
        # re-drive the chain from the reverted tile step to confirm it still
        # completes normally
        d.on_tile_clicked(4, 1)
        d.on_card_selected("defence")
        d.on_building_placed("defence")
        self.assertTrue(d.finished)


class TestClosePanelHintStep(unittest.TestCase):
    """TU-8 Fix 2: the close-panel-hint step (flute chain only) gates End
    Turn until the panel is actually closed, and its banner text resolves
    from the script's ``messages`` map."""

    def test_gates_end_turn_until_closed_and_banner_resolves(self):
        d = _director()
        d.on_message_dismissed()
        d.on_tile_clicked(2, 3)
        d.on_card_selected("economic")
        d.on_building_placed("economic")
        self.assertEqual(d.highlight_targets(), ("button:close",))
        self.assertFalse(d.allows_end_turn())
        self.assertEqual(d.banner_text(), MSG_CLOSE_PANEL_HINT)
        d.on_end_turn()  # blocked: End Turn isn't this step's gated action
        self.assertEqual(d.highlight_targets(), ("button:close",))
        d.on_panel_closed()
        self.assertEqual(d.highlight_targets(), ("button:end_turn",))
        self.assertTrue(d.allows_end_turn())
        self.assertIsNone(d.banner_text())

    def test_round_two_defence_placement_carries_no_close_panel_step(self):
        """Deliberately NOT mirrored after the round-2 defence placement —
        the tutorial ends there and input is released."""
        d = _director()
        _walk_round_one(d)
        d.on_round_end(1)
        d.on_message_dismissed()
        d.on_tile_clicked(4, 1)
        d.on_card_selected("defence")
        d.on_building_placed("defence")
        self.assertTrue(d.finished)
        self.assertIsNone(d.banner_text())


class TestRoundTwoChain(unittest.TestCase):
    """TU-7: the round-1 chain flows straight into the scripted loss, message
    box #2, and the stone-thrower chain — driven with the same fake events
    game/main.py feeds in response to real clicks/round-ends."""

    def test_scripted_loss_wait_step_gates_everything_and_no_highlight(self):
        d = _director()
        _walk_round_one(d)
        self.assertFalse(d.finished)
        self.assertEqual(d.highlight_targets(), ())
        self.assertFalse(d.allows(("tile", 4, 1)))
        self.assertFalse(d.allows_end_turn())
        # a round-end that ISN'T round 0's scripted loss (shouldn't happen in
        # practice, but the sequencer only cares about the id match) still
        # only advances this exact step once
        self.assertTrue(d.charges_life_on_base_hit(0))

    def test_full_round_two_chain_reaches_finished(self):
        d = _director()
        _walk_round_one(d)
        d.on_round_end(1)  # the scripted loss lands

        # -- message box #2 --
        self.assertTrue(d.message_visible)
        self.assertEqual(d.message_text(), MSG_LIVES_INTRO)
        self.assertFalse(d.allows(("tile", 4, 1)))  # still gated under the box
        d.on_message_dismissed()
        self.assertFalse(d.message_visible)

        # -- tile highlight: the stone marker, not the flute --
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_stone",))
        self.assertEqual(d.tile_highlight_targets(), [(4, 1)])
        self.assertFalse(d.allows(("tile", 2, 3)))   # the flute tile: no longer
        self.assertTrue(d.allows(("tile", 4, 1)))
        d.on_tile_clicked(2, 3)  # wrong tile: no-op
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_stone",))
        d.on_tile_clicked(4, 1)

        # -- card highlight: only "defence" is selectable --
        self.assertEqual(d.highlight_targets(), ("card:defence",))
        self.assertTrue(d.allows(("card", "defence")))
        self.assertFalse(d.allows(("card", "economic")))
        d.on_card_selected("economic")  # wrong card: no-op
        self.assertEqual(d.highlight_targets(), ("card:defence",))
        d.on_card_selected("defence")

        # -- confirm highlight --
        self.assertEqual(d.highlight_targets(), ("button:confirm",))
        self.assertTrue(d.allows(("confirm",)))
        d.on_building_placed("defence")

        # -- finished: zero-overhead path, everything permissive again --
        self.assertTrue(d.finished)
        self.assertEqual(d.highlight_targets(), ())
        self.assertTrue(d.allows(("card", "economic")))
        self.assertTrue(d.allows(("tile", 9, 9)))
        self.assertTrue(d.allows_end_turn())
        self.assertTrue(d.charges_life_on_base_hit(0))
        self.assertTrue(d.charges_life_on_base_hit(1))

    def test_message_box_two_never_reappears_on_a_later_round_end(self):
        d = _director()
        _walk_round_one(d)
        d.on_round_end(1)
        self.assertTrue(d.message_visible)
        d.on_message_dismissed()
        self.assertFalse(d.message_visible)
        # subsequent round-ends (round 2, 3, ...) are no-ops on THIS step —
        # the sequencer has already moved past it.
        d.on_round_end(2)
        d.on_round_end(3)
        self.assertFalse(d.message_visible)
        self.assertEqual(d.highlight_targets(), ("tile:tutorial_stone",))


class TestScriptedLossWaiver(unittest.TestCase):
    """``charges_life_on_base_hit`` — the free-loss read TU-7 adds to
    ``Session.on_base_hit``. A pure query; never mutates the sequencer."""

    def _director_with_free_first_loss(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        data_dir = fixture_copy(Path(tmp.name))
        script_path = data_dir / "tutorial" / "tutorial.json"
        doc = json.loads(script_path.read_text(encoding="utf-8"))
        doc["first_loss_costs_life"] = False
        script_path.write_text(json.dumps(doc), encoding="utf-8")
        return _director(data_dir=data_dir)

    def test_default_script_charges_the_life(self):
        d = _director()
        _walk_round_one(d)
        self.assertTrue(d.charges_life_on_base_hit(0))

    def test_script_toggled_false_waives_the_life(self):
        d = self._director_with_free_first_loss()
        _walk_round_one(d)
        self.assertFalse(d.charges_life_on_base_hit(0))

    def test_waiver_only_applies_to_round_0(self):
        d = self._director_with_free_first_loss()
        _walk_round_one(d)
        # round_num != 0 (TU-9: the tutorial's scripted round is round 0):
        # always charges, even mid the scripted-loss step
        self.assertTrue(d.charges_life_on_base_hit(1))

    def test_waiver_does_not_apply_outside_the_scripted_loss_step(self):
        d = self._director_with_free_first_loss()
        # still on round-0's message box, not the scripted-loss step yet
        self.assertTrue(d.charges_life_on_base_hit(0))

    def test_finished_tutorial_always_charges(self):
        d = self._director_with_free_first_loss()
        d.skip()
        self.assertTrue(d.charges_life_on_base_hit(0))


if __name__ == "__main__":
    unittest.main()
