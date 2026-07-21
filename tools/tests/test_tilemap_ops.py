"""Phase 6: editor/tilemap_ops — the pure paint model (no Qt, no pygame).

Cheap to test headlessly by design; the Qt viewport only translates mouse
events into these ops.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from editor import tilemap_ops as ops
from engine import data_io, tilemap

SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"


def make_doc(cols=8, rows=6, fill="f"):
    doc = tilemap.new_doc("opsmap", "Ops Map", cols, rows, SCHEMA)
    for row in doc.terrain:
        row[:] = [fill] * cols
    return doc


class TestPaint(unittest.TestCase):
    def test_paint_records_change(self):
        doc = make_doc()
        self.assertEqual(ops.paint(doc, 2, 3, "b"), [(2, 3, "f", "b")])
        self.assertEqual(doc.terrain[3][2], "b")

    def test_noop_and_out_of_bounds_return_empty(self):
        doc = make_doc()
        self.assertEqual(ops.paint(doc, 2, 3, "f"), [])   # same code
        self.assertEqual(ops.paint(doc, -1, 0, "b"), [])
        self.assertEqual(ops.paint(doc, 8, 0, "b"), [])
        self.assertEqual(ops.paint(doc, 0, 6, "b"), [])


class TestLine(unittest.TestCase):
    def test_straight_and_diagonal(self):
        self.assertEqual(ops.line_cells(1, 1, 4, 1),
                         [(1, 1), (2, 1), (3, 1), (4, 1)])
        self.assertEqual(ops.line_cells(0, 0, 2, 2),
                         [(0, 0), (1, 1), (2, 2)])
        self.assertEqual(ops.line_cells(3, 3, 3, 3), [(3, 3)])

    def test_line_paints_and_clips(self):
        doc = make_doc()
        changes = ops.line(doc, 0, 2, 20, 2, "c")   # runs off the grid
        self.assertEqual(len(changes), doc.cols)     # clipped to 8 cells
        self.assertEqual(doc.terrain[2], ["c"] * doc.cols)


class TestRect(unittest.TestCase):
    def test_rect_fill_normalizes_corners(self):
        doc = make_doc()
        changes = ops.rect_fill(doc, 4, 3, 2, 1, "s")   # reversed corners
        self.assertEqual(len(changes), 9)                # 3x3
        for r in (1, 2, 3):
            self.assertEqual(doc.terrain[r][2:5], ["s"] * 3)
        self.assertEqual(doc.terrain[0][2], "f")


class TestBucket(unittest.TestCase):
    def test_fill_bounded_by_other_codes(self):
        doc = make_doc()
        ops.rect_fill(doc, 0, 0, 7, 5, "f")
        ops.line(doc, 3, 0, 3, 5, "c")     # vertical wall splits the grid
        changes = ops.bucket_fill(doc, 0, 0, "b")
        self.assertEqual(len(changes), 3 * doc.rows)   # cols 0..2 only
        self.assertEqual(doc.terrain[0][4], "f")        # right side untouched
        self.assertEqual(doc.terrain[0][3], "c")        # wall untouched

    def test_fill_same_code_is_noop(self):
        doc = make_doc()
        self.assertEqual(ops.bucket_fill(doc, 0, 0, "f"), [])


class TestPickAndApply(unittest.TestCase):
    def test_pick(self):
        doc = make_doc()
        doc.terrain[3][2] = "s"
        self.assertEqual(ops.pick(doc, 2, 3), "s")
        self.assertIsNone(ops.pick(doc, 99, 0))

    def test_apply_changes_round_trip(self):
        doc = make_doc()
        changes = ops.rect_fill(doc, 1, 1, 3, 3, "b")
        ops.apply_changes(doc, changes, reverse=True)    # undo
        self.assertEqual(doc.terrain[2][2], "f")
        ops.apply_changes(doc, changes)                  # redo
        self.assertEqual(doc.terrain[2][2], "b")
        tilemap.validate_doc(doc)


class TestDecoAndBase(unittest.TestCase):
    def test_place_and_remove_top_deco(self):
        doc = make_doc()
        a = ops.place_deco(doc, 2, 2, "deco_rock")
        b = ops.place_deco(doc, 2, 2, "deco_tree")
        self.assertEqual(doc.deco, [a, b])
        idx, removed = ops.remove_top_deco(doc, 2, 2)
        self.assertEqual((idx, removed), (1, b))         # LIFO on the cell
        self.assertIsNone(ops.remove_top_deco(doc, 5, 5))
        self.assertIsNone(ops.place_deco(doc, -1, 0, "deco_bush"))

    def test_place_deco_flip_omitted_when_false(self):
        doc = make_doc()
        flipped = ops.place_deco(doc, 3, 3, "deco_rock", flip=True)
        plain = ops.place_deco(doc, 4, 3, "deco_rock", flip=False)
        default = ops.place_deco(doc, 5, 3, "deco_rock")
        self.assertEqual(flipped, {"col": 3, "row": 3, "slot": "deco_rock",
                                    "flip": True})
        self.assertEqual(plain, {"col": 4, "row": 3, "slot": "deco_rock"})
        self.assertEqual(default, {"col": 5, "row": 3, "slot": "deco_rock"})
        self.assertNotIn("flip", plain)
        self.assertNotIn("flip", default)

    def test_move_base(self):
        doc = make_doc()
        old = (doc.base["col"], doc.base["row"])
        self.assertEqual(ops.move_base(doc, 6, 1), old)
        self.assertEqual((doc.base["col"], doc.base["row"]), (6, 1))
        self.assertIsNone(ops.move_base(doc, 6, 1))      # same cell: no-op
        self.assertIsNone(ops.move_base(doc, 99, 1))


class TestRequirementWarnings(unittest.TestCase):
    """The non-blocking Set-Active warnings: zone coverage, hole, camera
    startpoint, and the 2×2 starting area (present + sitting on buildable)."""

    @staticmethod
    def _playable_doc():
        """A doc that clears every zone warning: b/c/s painted, base set."""
        doc = make_doc()
        ops.paint(doc, 1, 1, "b")
        ops.paint(doc, 1, 2, "b")
        ops.paint(doc, 2, 1, "b")
        ops.paint(doc, 2, 2, "b")
        ops.paint(doc, 4, 1, "c")
        ops.paint(doc, 5, 1, "s")
        doc.camera_start = {"col": 3, "row": 3, "slot": "camera_startpoint"}
        return doc

    def test_missing_start_area_warns(self):
        doc = self._playable_doc()
        self.assertIn("starting area", ops.map_requirement_warnings(doc))

    def test_start_area_on_non_buildable_warns(self):
        doc = self._playable_doc()
        # min corner (4,1): covers the 'c' at (4,1) + forest — not all 'b'
        doc.start_area = {"col": 4, "row": 1, "slot": "start_area"}
        warnings = ops.map_requirement_warnings(doc)
        self.assertNotIn("starting area", warnings)
        self.assertIn("buildable tiles under starting area", warnings)

    def test_start_area_on_buildable_pocket_is_clean(self):
        doc = self._playable_doc()
        doc.start_area = {"col": 1, "row": 1, "slot": "start_area"}
        warnings = ops.map_requirement_warnings(doc)
        self.assertNotIn("starting area", warnings)
        self.assertNotIn("buildable tiles under starting area", warnings)
        self.assertEqual(warnings, [])   # nothing else missing either


if __name__ == "__main__":
    unittest.main()
