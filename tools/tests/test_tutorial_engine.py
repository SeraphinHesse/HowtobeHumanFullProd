"""``engine.tutorial`` step-sequencer tests (Phase TU-6). Pure Python — no
pygame, no game vocabulary; every id below is an opaque placeholder string,
mirroring how the real game-side director's ids are shaped (D2)."""
import unittest

from engine.tutorial import Step, TutorialSequencer


def _steps():
    return [
        Step(id="a", message="msg_a", highlight=("tile:x",),
             advance_on="event:a", allow=("action:a",)),
        Step(id="b", message=None, highlight=("card:y",),
             advance_on="event:b", allow=("action:b",)),
        Step(id="c", message=None, highlight=("button:confirm",),
             advance_on="event:c", allow=("action:c",)),
    ]


class TestStep(unittest.TestCase):
    def test_defaults(self):
        s = Step(id="only")
        self.assertIsNone(s.message)
        self.assertEqual(s.highlight, ())
        self.assertIsNone(s.advance_on)
        self.assertEqual(s.allow, ())
        self.assertEqual(s.flags, {})
        self.assertIsNone(s.revert_on)  # TU-8
        self.assertIsNone(s.revert_to)  # TU-8

    def test_is_frozen(self):
        s = Step(id="only")
        with self.assertRaises(Exception):
            s.id = "other"


class TestSequencerBasics(unittest.TestCase):
    def test_starts_on_first_step_active_not_finished(self):
        seq = TutorialSequencer(_steps())
        self.assertTrue(seq.active)
        self.assertFalse(seq.finished)
        self.assertEqual(seq.current.id, "a")
        self.assertTrue(seq.skippable)

    def test_empty_step_list_is_immediately_finished(self):
        seq = TutorialSequencer(())
        self.assertTrue(seq.finished)
        self.assertFalse(seq.active)
        self.assertIsNone(seq.current)

    def test_message_id_and_highlight_ids_and_flags(self):
        seq = TutorialSequencer(_steps())
        self.assertEqual(seq.message_id(), "msg_a")
        self.assertEqual(seq.highlight_ids(), ("tile:x",))
        self.assertEqual(seq.flags(), {})

    def test_flags_returns_a_copy(self):
        steps = [Step(id="a", advance_on="e", flags={"k": 1})]
        seq = TutorialSequencer(steps)
        got = seq.flags()
        got["k"] = 999
        self.assertEqual(seq.flags(), {"k": 1})  # the sequencer's own dict unharmed


class TestAdvance(unittest.TestCase):
    def test_unrelated_event_is_a_noop(self):
        seq = TutorialSequencer(_steps())
        self.assertFalse(seq.advance("event:b"))  # wrong id for step "a"
        self.assertEqual(seq.current.id, "a")

    def test_matching_event_advances_exactly_one_step(self):
        seq = TutorialSequencer(_steps())
        self.assertTrue(seq.advance("event:a"))
        self.assertEqual(seq.current.id, "b")
        self.assertFalse(seq.finished)

    def test_advancing_past_the_last_step_finishes(self):
        seq = TutorialSequencer(_steps())
        seq.advance("event:a")
        seq.advance("event:b")
        self.assertTrue(seq.advance("event:c"))
        self.assertTrue(seq.finished)
        self.assertIsNone(seq.current)

    def test_advance_is_a_noop_once_finished(self):
        seq = TutorialSequencer(())
        self.assertFalse(seq.advance("event:a"))

    def test_advance_on_none_never_advances(self):
        seq = TutorialSequencer([Step(id="only", advance_on=None)])
        self.assertFalse(seq.advance("only"))
        self.assertFalse(seq.advance(None))
        self.assertFalse(seq.finished)


class TestSkip(unittest.TestCase):
    def test_skip_when_skippable_finishes_immediately(self):
        seq = TutorialSequencer(_steps(), skippable=True)
        seq.skip()
        self.assertTrue(seq.finished)
        self.assertIsNone(seq.current)
        self.assertIsNone(seq.message_id())
        self.assertEqual(seq.highlight_ids(), ())
        self.assertEqual(seq.flags(), {})

    def test_skip_is_a_noop_when_not_skippable(self):
        seq = TutorialSequencer(_steps(), skippable=False)
        seq.skip()
        self.assertFalse(seq.finished)
        self.assertEqual(seq.current.id, "a")


class TestRevert(unittest.TestCase):
    """``TutorialSequencer.revert`` (TU-8) — the generic backward mirror of
    ``advance``, driving Fix 1's "closing the panel un-sticks the player"
    behavior."""

    def _steps_with_revert(self):
        return [
            Step(id="tile", advance_on="event:tile", allow=("tile",)),
            Step(id="card", advance_on="event:card", allow=("card",),
                 revert_on="closed", revert_to="tile"),
            Step(id="confirm", advance_on="event:confirm", allow=("confirm",),
                 revert_on="closed", revert_to="tile"),
        ]

    def test_revert_lands_on_the_named_step(self):
        seq = TutorialSequencer(self._steps_with_revert())
        seq.advance("event:tile")
        self.assertEqual(seq.current.id, "card")
        self.assertTrue(seq.revert("closed"))
        self.assertEqual(seq.current.id, "tile")

    def test_revert_from_a_later_step_also_lands_on_the_named_step(self):
        seq = TutorialSequencer(self._steps_with_revert())
        seq.advance("event:tile")
        seq.advance("event:card")
        self.assertEqual(seq.current.id, "confirm")
        self.assertTrue(seq.revert("closed"))
        self.assertEqual(seq.current.id, "tile")

    def test_unmatched_event_never_reverts(self):
        seq = TutorialSequencer(self._steps_with_revert())
        seq.advance("event:tile")
        self.assertFalse(seq.revert("something_else"))
        self.assertEqual(seq.current.id, "card")

    def test_revert_on_none_never_reverts(self):
        seq = TutorialSequencer(self._steps_with_revert())
        # current step "tile" has revert_on=None
        self.assertFalse(seq.revert("closed"))
        self.assertEqual(seq.current.id, "tile")

    def test_revert_to_an_unknown_step_is_a_safe_noop(self):
        steps = [Step(id="only", advance_on="e", revert_on="closed",
                       revert_to="does_not_exist")]
        seq = TutorialSequencer(steps)
        self.assertFalse(seq.revert("closed"))
        self.assertEqual(seq.current.id, "only")

    def test_revert_is_a_noop_once_finished(self):
        seq = TutorialSequencer(())
        self.assertFalse(seq.revert("closed"))

    def test_revert_is_a_noop_when_skipped(self):
        steps = [Step(id="a", advance_on="e", revert_on="closed",
                       revert_to="a")]
        seq = TutorialSequencer(steps, skippable=True)
        seq.skip()
        self.assertFalse(seq.revert("closed"))


class TestAllows(unittest.TestCase):
    def test_allowed_action_true_disallowed_false(self):
        seq = TutorialSequencer(_steps())
        self.assertTrue(seq.allows("action:a"))
        self.assertFalse(seq.allows("action:b"))
        self.assertFalse(seq.allows("anything_else"))

    def test_allows_is_always_true_once_finished(self):
        seq = TutorialSequencer(())
        self.assertTrue(seq.allows("action:a"))
        self.assertTrue(seq.allows("literally_anything"))

    def test_allows_true_after_skip(self):
        seq = TutorialSequencer(_steps(), skippable=True)
        self.assertFalse(seq.allows("action:z"))
        seq.skip()
        self.assertTrue(seq.allows("action:z"))


if __name__ == "__main__":
    unittest.main()
