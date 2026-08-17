"""``engine.ui_layers`` pure resolver tests (UiLayeredWidgetsPLAN UL-3). Pure
Python -- no pygame, no data/ I/O; the schema-validation half of this phase
(every existing ``data/ui/screens/*.json`` still validates with no ``layers``
key present) is covered by ``tools/smoke.py::validate_data``, already part of
the exit gate, so it is not duplicated here. Purity (no pygame leak) is
covered by ``tools/tests/test_render.py::TestPurity`` (this module was added
to its subprocess-import line), not duplicated here either."""
import copy
import unittest

from engine.ui_layers import hit, ordered, resolve, validate_offsets


class TestResolve(unittest.TestCase):
    def test_offset_applied_to_owner_rect(self):
        layer = {"offset": [5, -3, 20, 40]}
        out = resolve(layer, (100, 200, 50, 60))
        self.assertEqual(out["rect"], (105, 197, 20, 40))

    def test_zero_w_and_h_inherit_owner_size_independently(self):
        owner = (10, 10, 30, 45)
        out_w = resolve({"offset": [0, 0, 0, 12]}, owner)
        self.assertEqual(out_w["rect"], (10, 10, 30, 12))
        out_h = resolve({"offset": [0, 0, 15, 0]}, owner)
        self.assertEqual(out_h["rect"], (10, 10, 15, 45))

    def test_zero_w_and_h_inherit_owner_size_together(self):
        owner = (1, 2, 33, 44)
        out = resolve({"offset": [0, 0, 0, 0]}, owner)
        self.assertEqual(out["rect"], (1, 2, 33, 44))

    def test_absent_offset_degrades_to_owner_rect(self):
        owner = (7, 8, 9, 10)
        out = resolve({}, owner)
        self.assertEqual(out["rect"], owner)

    def test_appearance_keys_default_to_none_or_true(self):
        out = resolve({}, (0, 0, 1, 1))
        self.assertIsNone(out["slot"])
        self.assertIsNone(out["text_id"])
        self.assertIsNone(out["label"])
        self.assertIsNone(out["font"])
        self.assertIsNone(out["align"])
        self.assertIsNone(out["color"])
        self.assertIsNone(out["text_color"])
        self.assertIsNone(out["tint"])
        self.assertTrue(out["visible"])

    def test_fully_populated_entry_returns_all_keys_verbatim(self):
        layer = {
            "offset": [1, 2, 3, 4],
            "slot": "vfx_slot",
            "text_id": "some_text",
            "label": "Some Label",
            "font": "main",
            "align": "center",
            "color": [1, 2, 3, 4],
            "text_color": [5, 6, 7],
            "tint": [8, 9, 10, 11],
            "visible": False,
        }
        out = resolve(layer, (0, 0, 10, 10))
        self.assertEqual(out["slot"], "vfx_slot")
        self.assertEqual(out["text_id"], "some_text")
        self.assertEqual(out["label"], "Some Label")
        self.assertEqual(out["font"], "main")
        self.assertEqual(out["align"], "center")
        self.assertEqual(out["color"], (1, 2, 3, 4))
        self.assertEqual(out["text_color"], (5, 6, 7))
        self.assertEqual(out["tint"], (8, 9, 10, 11))
        self.assertFalse(out["visible"])

    def test_state_parameter_is_a_no_op(self):
        layer = {"offset": [1, 1, 2, 2], "label": "x"}
        owner = (0, 0, 5, 5)
        self.assertEqual(resolve(layer, owner, state="idle"),
                          resolve(layer, owner, state="pressed"))


class TestOrdered(unittest.TestCase):
    def test_band_filtering(self):
        layers = [
            {"id": "a", "band": "under"},
            {"id": "b", "band": "over"},
        ]
        over = ordered(layers, "over")
        under = ordered(layers, "under")
        self.assertEqual([e["id"] for e in over], ["b"])
        self.assertEqual([e["id"] for e in under], ["a"])

    def test_missing_band_defaults_to_over(self):
        layers = [{"id": "a"}]
        self.assertEqual([e["id"] for e in ordered(layers, "over")], ["a"])
        self.assertEqual([e["id"] for e in ordered(layers, "under")], [])

    def test_z_ordering_ascending_with_stable_ties(self):
        layers = [
            {"id": "a", "z": 5},
            {"id": "b", "z": 1},
            {"id": "c"},  # missing z defaults to 0
            {"id": "d", "z": 1},
        ]
        out = [e["id"] for e in ordered(layers, "over")]
        self.assertEqual(out, ["c", "b", "d", "a"])

    def test_duplicate_id_keeps_first_occurrence(self):
        layers = [
            {"id": "dup", "z": 0},
            {"id": "dup", "z": 5},
        ]
        out = ordered(layers, "over")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["z"], 0)

    def test_id_less_or_empty_id_entries_never_dedupe(self):
        layers = [
            {"z": 0},
            {"z": 1},
            {"id": "", "z": 2},
            {"id": "", "z": 3},
        ]
        out = ordered(layers, "over")
        self.assertEqual(len(out), 4)

    def test_does_not_mutate_input_list(self):
        layers = [{"id": "a", "z": 5}, {"id": "b", "z": 1}]
        original = list(layers)
        ordered(layers, "over")
        self.assertEqual(layers, original)


class TestValidateOffsets(unittest.TestCase):
    def test_valid_offset_passes_through_unchanged(self):
        entry = {"offset": [1, 2, 3, 4]}
        out = validate_offsets([entry])
        self.assertEqual(out[0]["offset"], [1, 2, 3, 4])

    def test_absent_offset_passes_through_unchanged(self):
        entry = {"label": "no offset here"}
        out = validate_offsets([entry])
        self.assertEqual(out[0], entry)
        self.assertNotIn("offset", out[0])

    def test_malformed_offset_wrong_length_replaced(self):
        entry = {"offset": [1, 2, 3]}
        out = validate_offsets([entry])
        self.assertEqual(out[0]["offset"], (0, 0, 0, 0))
        self.assertEqual(entry["offset"], [1, 2, 3])  # input not mutated

    def test_malformed_offset_non_int_element_replaced(self):
        entry = {"offset": [1, 2, 3, "4"]}
        out = validate_offsets([entry])
        self.assertEqual(out[0]["offset"], (0, 0, 0, 0))

    def test_malformed_offset_non_sequence_replaced(self):
        entry = {"offset": 42}
        out = validate_offsets([entry])
        self.assertEqual(out[0]["offset"], (0, 0, 0, 0))

    def test_malformed_offset_bool_element_replaced(self):
        entry = {"offset": [1, 2, 3, True]}
        out = validate_offsets([entry])
        self.assertEqual(out[0]["offset"], (0, 0, 0, 0))

    def test_input_not_mutated_on_malformed_offset(self):
        entry = {"offset": [1, 2, 3]}
        original = dict(entry)
        validate_offsets([entry])
        self.assertEqual(entry, original)

    def test_non_dict_entry_skipped_unchanged(self):
        out = validate_offsets(["not a dict", 5, None])
        self.assertEqual(out, ["not a dict", 5, None])


class TestHit(unittest.TestCase):
    OWNER = (100, 100, 50, 50)

    def test_topmost_wins_within_a_band(self):
        layers = [
            {"id": "low", "z": 1, "clickable": True, "target": "a",
             "offset": [0, 0, 40, 40]},
            {"id": "high", "z": 9, "clickable": True, "target": "b",
             "offset": [0, 0, 40, 40]},
        ]
        out = hit(layers, self.OWNER, 110, 110)
        self.assertEqual(out, {"kind": "layer", "id": "high", "target": "b"})

    def test_over_layer_beats_the_owner(self):
        layers = [{"id": "top", "band": "over", "clickable": True,
                   "target": "close_window", "offset": [0, 0, 0, 0]}]
        out = hit(layers, self.OWNER, 110, 110)
        self.assertEqual(
            out, {"kind": "layer", "id": "top", "target": "close_window"})

    def test_non_clickable_layer_is_transparent(self):
        layers = [
            {"id": "decor", "offset": [0, 0, 0, 0]},           # no clickable
            {"id": "decor2", "clickable": False, "offset": [0, 0, 0, 0]},
        ]
        self.assertEqual(hit(layers, self.OWNER, 110, 110), {"kind": "owner"})

    def test_invisible_clickable_layer_is_skipped(self):
        layers = [{"id": "ghost", "clickable": True, "target": "a",
                   "visible": False, "offset": [0, 0, 0, 0]}]
        self.assertEqual(hit(layers, self.OWNER, 110, 110), {"kind": "owner"})

    def test_out_of_bounds_returns_none(self):
        layers = [{"id": "a", "clickable": True, "offset": [0, 0, 10, 10]}]
        self.assertIsNone(hit(layers, self.OWNER, 900, 900))

    def test_under_layer_hit_outside_the_owner_rect(self):
        layers = [{"id": "wing", "band": "under", "clickable": True,
                   "target": "back", "offset": [-30, 0, 20, 20]}]
        out = hit(layers, self.OWNER, 75, 105)
        self.assertEqual(out, {"kind": "layer", "id": "wing", "target": "back"})

    def test_missing_id_and_target_return_none_fields(self):
        layers = [{"clickable": True, "offset": [0, 0, 0, 0]}]
        out = hit(layers, self.OWNER, 110, 110)
        self.assertEqual(out, {"kind": "layer", "id": None, "target": None})

    def test_pure_twice_same_result_and_no_mutation(self):
        layers = [
            {"id": "a", "z": 1, "clickable": True, "target": "x",
             "offset": [0, 0, 20, 20],
             "states": {"pressed": {"offset": [5, 5]}}},
            {"id": "b", "band": "under", "offset": [0, 0, 0, 0]},
        ]
        before = copy.deepcopy(layers)
        first = hit(layers, self.OWNER, 110, 110, state="pressed")
        second = hit(layers, self.OWNER, 110, 110, state="pressed")
        self.assertEqual(first, second)
        self.assertEqual(layers, before)
        miss = hit(layers, self.OWNER, 900, 900)
        self.assertEqual(miss, hit(layers, self.OWNER, 900, 900))
        self.assertEqual(layers, before)


if __name__ == "__main__":
    unittest.main()
