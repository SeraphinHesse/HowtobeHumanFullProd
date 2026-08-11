"""editor/widget_tree.py — the pure parent resolver (UiEditorParentingPLAN
P-1).

Bare-minimum unit coverage of the four contracts the rest of the plan leans
on: which of the two `parent` sources wins, that a dangling/cyclic chain
degrades to ROOT instead of raising (D5), that `descendants` is the stable
depth-first subtree a viewport move cascades over (P-3), and that
`would_cycle` refuses exactly the drops the tree and the Parent combo must
both refuse (P-4).

No Qt, no pygame, no `data/` — every fixture is a literal dict.
"""
import unittest

from editor import widget_tree as wt


def _spec(parent=None):
    entry = {"rect": [0, 0, 10, 10], "kind": "label", "label": ""}
    if parent is not None:
        entry["parent"] = parent
    return entry


# hud's real shape, cut down: a panel with two readouts, a button with its
# label, and one genuinely parentless widget.
DEFAULTS = {
    "btn_end_turn": _spec(),
    "icon_love": _spec("love_panel"),
    "love_panel": _spec(),
    "love_text": _spec("love_panel"),
    "phase_label": _spec(),
    "round_label": _spec("btn_end_turn"),
}


class TestResolveParent(unittest.TestCase):
    def test_default_parent_is_used_when_no_override(self):
        self.assertEqual(
            wt.resolve_parent("love_text", _spec("love_panel"), {}),
            "love_panel")

    def test_absent_everywhere_is_root(self):
        self.assertIs(wt.resolve_parent("love_panel", _spec(), {}), wt.ROOT)

    def test_override_wins_over_default(self):
        self.assertEqual(
            wt.resolve_parent("round_label", _spec("btn_end_turn"),
                              {"parent": "love_panel"}),
            "love_panel")

    def test_explicit_null_override_re_roots(self):
        """D3: `parent: null` is the designer REJECTING the default parent —
        distinct from the key being absent, which keeps it."""
        self.assertIs(
            wt.resolve_parent("round_label", _spec("btn_end_turn"),
                              {"parent": None}),
            wt.ROOT)

    def test_self_parent_is_root(self):
        self.assertIs(
            wt.resolve_parent("love_panel", _spec("love_panel"), {}), wt.ROOT)


class TestParentMap(unittest.TestCase):
    def test_every_widget_resolves(self):
        parents = wt.parent_map(DEFAULTS)
        self.assertEqual(parents, {
            "btn_end_turn": wt.ROOT,
            "icon_love": "love_panel",
            "love_panel": wt.ROOT,
            "love_text": "love_panel",
            "phase_label": wt.ROOT,
            "round_label": "btn_end_turn",
        })

    def test_dangling_parent_degrades_to_root(self):
        """A `building_panel` view legitimately shows only some ids, so a
        parent that is not in THIS widgets map is authoring noise, not an
        error (D5)."""
        parents = wt.parent_map({"a": _spec("nobody_here")})
        self.assertIs(parents["a"], wt.ROOT)

    def test_cycle_degrades_to_root_and_never_hangs(self):
        parents = wt.parent_map({"a": _spec("b"), "b": _spec("c"),
                                 "c": _spec("a")})
        self.assertIn(wt.ROOT, parents.values())
        # No id may still reach itself by walking up.
        for widget_id in parents:
            self.assertNotIn(widget_id, wt.ancestors(parents, widget_id))

    def test_override_can_introduce_a_cycle_and_is_still_survivable(self):
        parents = wt.parent_map(DEFAULTS,
                                {"love_panel": {"parent": "love_text"}})
        for widget_id in parents:
            self.assertNotIn(widget_id, wt.ancestors(parents, widget_id))


class TestBuildTree(unittest.TestCase):
    def test_adjacency_and_stable_order(self):
        tree = wt.build_tree(DEFAULTS)
        self.assertEqual(tree[wt.ROOT],
                         ["btn_end_turn", "love_panel", "phase_label"])
        self.assertEqual(tree["love_panel"], ["icon_love", "love_text"])
        self.assertEqual(tree["btn_end_turn"], ["round_label"])
        self.assertNotIn("phase_label", tree)   # childless ids carry no key

    def test_every_widget_appears_exactly_once_as_a_child(self):
        tree = wt.build_tree(DEFAULTS)
        seen = [wid for kids in tree.values() for wid in kids]
        self.assertEqual(sorted(seen), sorted(DEFAULTS))


class TestDescendants(unittest.TestCase):
    def test_subtree_is_depth_first_in_child_order(self):
        tree = {wt.ROOT: ["a"], "a": ["b", "c"], "b": ["d"]}
        self.assertEqual(wt.descendants(tree, "a"), ["b", "d", "c"])

    def test_leaf_has_none(self):
        self.assertEqual(wt.descendants(wt.build_tree(DEFAULTS), "love_text"), [])

    def test_hand_built_cycle_terminates(self):
        """`parent_map` already breaks cycles, but this function also takes
        hand-assembled trees — an infinite loop in a Qt paint handler is
        exactly what D5 exists to prevent."""
        self.assertEqual(wt.descendants({"a": ["b"], "b": ["a"]}, "a"), ["b"])


class TestWouldCycle(unittest.TestCase):
    def setUp(self):
        self.tree = wt.build_tree(DEFAULTS)

    def test_dropping_onto_own_descendant_is_refused(self):
        self.assertTrue(wt.would_cycle(self.tree, "love_panel", "love_text"))

    def test_dropping_onto_self_is_refused(self):
        self.assertTrue(wt.would_cycle(self.tree, "love_panel", "love_panel"))

    def test_dropping_onto_an_unrelated_widget_is_allowed(self):
        self.assertFalse(wt.would_cycle(self.tree, "round_label", "love_panel"))

    def test_dropping_onto_root_is_always_allowed(self):
        self.assertFalse(wt.would_cycle(self.tree, "love_panel", wt.ROOT))


class TestLegalParents(unittest.TestCase):
    def test_excludes_self_and_descendants_only(self):
        self.assertEqual(
            wt.legal_parents(DEFAULTS, {}, "love_panel"),
            ["btn_end_turn", "phase_label", "round_label"])

    def test_a_leaf_may_go_anywhere_else(self):
        legal = wt.legal_parents(DEFAULTS, {}, "love_text")
        self.assertNotIn("love_text", legal)
        self.assertIn("love_panel", legal)
        self.assertIn("btn_end_turn", legal)


if __name__ == "__main__":
    unittest.main()
