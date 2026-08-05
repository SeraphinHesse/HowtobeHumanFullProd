"""Phase 6 acceptance tests for engine/tilemap (D-20/D-21) — the pure map
model shared by game and editor.

Pins the PROTOTYPE-EXACT checkerboard rule (src/map/tile.py): a checker
kind renders <slot>_b exactly when (col + row + 1) % 2 == 1, i.e. col+row
EVEN; background kinds never alternate. Spawning is a painted zone code —
the format has no spawn-point objects anywhere.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import data_io, tilemap

SCHEMA = FIXTURE_DATA / "schemas" / "map_file.schema.json"
ACTIVE_SCHEMA = FIXTURE_DATA / "schemas" / "active_map.schema.json"


def make_doc(cols=6, rows=5, fill="f"):
    legend, base_slot = tilemap.defaults_from_schema(data_io.load_json(SCHEMA))
    return tilemap.TileMapDoc(
        map_id="testmap",
        display_name="Test Map",
        cols=cols,
        rows=rows,
        legend=legend,
        terrain=[[fill] * cols for _ in range(rows)],
        base={"col": 1, "row": 1, "slot": base_slot},
        deco=[],
    )


class TestLegendAndDefaults(unittest.TestCase):
    def test_defaults_from_schema(self):
        legend, base_slot = tilemap.defaults_from_schema(data_io.load_json(SCHEMA))
        self.assertEqual(base_slot, "base_hole")
        self.assertEqual(
            sorted(legend), ["b", "c", "f", "l", "o", "s"])
        self.assertEqual(legend["b"], {"checker": True, "slot": "tile_buildable"})
        self.assertEqual(legend["s"], {"checker": True, "slot": "tile_spawning"})
        self.assertEqual(legend["f"], {"checker": False, "slot": "tile_forest"})

    def test_default_fill_code_is_first_non_checker(self):
        legend, _ = tilemap.defaults_from_schema(data_io.load_json(SCHEMA))
        self.assertEqual(tilemap.default_fill_code(legend), "f")


class TestCheckerboardParity(unittest.TestCase):
    """Wrinkle 7: the exact prototype rule, pinned."""

    def test_zone_kind_alternates_prototype_exact(self):
        doc = make_doc(fill="b")
        # prototype: checker = (col + row + 1) % 2; suffix _b when checker == 1
        self.assertEqual(tilemap.slot_for_cell(doc, 0, 0), "tile_buildable_b")
        self.assertEqual(tilemap.slot_for_cell(doc, 1, 0), "tile_buildable")
        self.assertEqual(tilemap.slot_for_cell(doc, 0, 1), "tile_buildable")
        self.assertEqual(tilemap.slot_for_cell(doc, 1, 1), "tile_buildable_b")
        self.assertEqual(tilemap.slot_for_cell(doc, 2, 4), "tile_buildable_b")

    def test_all_zone_kinds_alternate(self):
        for code, slot in (("b", "tile_buildable"), ("c", "tile_combat"),
                           ("s", "tile_spawning")):
            doc = make_doc(fill=code)
            self.assertEqual(tilemap.slot_for_cell(doc, 0, 0), slot + "_b")
            self.assertEqual(tilemap.slot_for_cell(doc, 1, 0), slot)

    def test_background_kinds_never_alternate(self):
        for code, slot in (("f", "tile_forest"), ("o", "tile_ocean"),
                           ("l", "tile_cliff")):
            doc = make_doc(fill=code)
            self.assertEqual(tilemap.slot_for_cell(doc, 0, 0), slot)
            self.assertEqual(tilemap.slot_for_cell(doc, 1, 0), slot)


class TestValidation(unittest.TestCase):
    def test_valid_doc_passes(self):
        tilemap.validate_doc(make_doc())  # must not raise

    def test_row_count_mismatch_fails_loud(self):
        doc = make_doc()
        doc.terrain.append(["f"] * doc.cols)
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_row_length_mismatch_fails_loud(self):
        doc = make_doc()
        doc.terrain[2] = ["f"] * (doc.cols - 1)
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_unknown_code_fails_loud(self):
        doc = make_doc()
        doc.terrain[0][0] = "x"
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_base_out_of_bounds_fails_loud(self):
        doc = make_doc()
        doc.base["col"] = doc.cols
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_deco_out_of_bounds_fails_loud(self):
        doc = make_doc()
        doc.deco.append({"col": 0, "row": doc.rows, "slot": "deco_tree"})
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)


class TestDiskRoundTrip(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def test_save_load_round_trip(self):
        doc = make_doc()
        doc.terrain[2][3] = "c"
        doc.deco.append({"col": 4, "row": 2, "slot": "deco_tree"})
        path = self.dir / "testmap.json"
        tilemap.save_map(doc, path, SCHEMA)
        loaded = tilemap.load_map(path, SCHEMA)
        self.assertEqual(loaded, doc)
        # D-3 canonical form on disk
        raw = path.read_text(encoding="utf-8")
        self.assertEqual(raw, data_io.dumps_deterministic(data_io.load_json(path)))

    def test_id_must_match_filename_stem(self):
        doc = make_doc()
        with self.assertRaises(ValueError):
            tilemap.save_map(doc, self.dir / "othername.json", SCHEMA)

    def test_load_cross_checks_fail_loud(self):
        # schema-valid but dims-inconsistent: declared 6 rows, shipped 5
        doc = make_doc()
        data = tilemap.to_dict(doc)
        data["rows"] = doc.rows + 1
        path = self.dir / "testmap.json"
        path.write_text(data_io.dumps_deterministic(data), encoding="utf-8")
        with self.assertRaises(ValueError):
            tilemap.load_map(path, SCHEMA)


class TestRenderItems(unittest.TestCase):
    def test_full_composition(self):
        doc = make_doc()
        doc.deco.append({"col": 3, "row": 1, "slot": "deco_tree"})
        items = tilemap.render_items(doc)
        ground = [i for i in items if i.layer == "ground"]
        entities = [i for i in items if i.layer == "entities"]
        deco = [i for i in items if i.layer == "deco"]
        self.assertEqual(len(ground), doc.cols * doc.rows)
        self.assertEqual(len(entities), 1)          # the base
        self.assertEqual(entities[0].slot_key, "base_hole")
        self.assertEqual(entities[0].world_pos, (1, 1))
        self.assertEqual(len(deco), 1)              # above entities (E-26)
        self.assertEqual(deco[0].slot_key, "deco_tree")

    def test_ground_slots_use_parity(self):
        doc = make_doc(fill="s")
        items = {i.world_pos: i for i in tilemap.render_items(
            doc, base=False, deco=False)}
        self.assertEqual(items[(0, 0)].slot_key, "tile_spawning_b")
        self.assertEqual(items[(1, 0)].slot_key, "tile_spawning")

    def test_layer_toggles(self):
        doc = make_doc()
        doc.deco.append({"col": 3, "row": 1, "slot": "deco_tree"})
        self.assertEqual(
            [i.layer for i in tilemap.render_items(
                doc, terrain=False, base=False)], ["deco"])
        self.assertEqual(tilemap.render_items(
            doc, terrain=False, base=False, deco=False), [])

    def test_zone_tint(self):
        doc = make_doc(fill="f")
        doc.terrain[0][0] = "b"
        tints = {"b": (150, 255, 150, 255)}
        items = {i.world_pos: i for i in tilemap.render_items(
            doc, base=False, deco=False, tint_for_code=tints)}
        self.assertEqual(items[(0, 0)].tint, (150, 255, 150, 255))
        self.assertIsNone(items[(1, 0)].tint)

    def test_deco_anim_time_ms_carries_deterministic_phase(self):
        doc = make_doc()
        doc.deco.append({"col": 3, "row": 1, "slot": "deco_tree"})
        expected_phase = (3 * 131 + 1 * 197) % 997
        deco = [i for i in tilemap.render_items(doc, anim_time_ms=1000)
                if i.layer == "deco"]
        self.assertEqual(deco[0].anim_time_ms, 1000 + expected_phase)

    def test_deco_flip_passes_through_to_render_item(self):
        doc = make_doc()
        doc.deco.append({"col": 3, "row": 1, "slot": "deco_tree", "flip": True})
        doc.deco.append({"col": 2, "row": 1, "slot": "deco_tree"})
        deco = {i.world_pos: i.flip
                for i in tilemap.render_items(doc) if i.layer == "deco"}
        self.assertTrue(deco[(3, 1)])
        self.assertFalse(deco[(2, 1)])   # no "flip" key -> defaults false


class TestVisibleRenderItems(unittest.TestCase):
    """Windowed culling emitter: identical to render_items for the covered
    cells, clamped to the map, base/deco gated by the tall-sprite margin."""

    def test_window_matches_full_render_over_the_same_cells(self):
        doc = make_doc(cols=10, rows=10, fill="s")  # checker kind → parity matters
        window = (2, 5, 3, 6)  # cols 2..5, rows 3..6 inclusive
        got = {i.world_pos: i.slot_key for i in tilemap.visible_render_items(
            doc, *window, base=False, deco=False)}
        full = {i.world_pos: i.slot_key for i in tilemap.render_items(
            doc, base=False, deco=False)}
        expected = {(c, r): full[(c, r)]
                    for r in range(3, 7) for c in range(2, 6)}
        self.assertEqual(got, expected)

    def test_window_clamps_to_map_bounds(self):
        doc = make_doc(cols=6, rows=5)
        items = tilemap.visible_render_items(
            doc, -100, 100, -100, 100, base=False, deco=False)
        self.assertEqual(len(items), doc.cols * doc.rows)  # whole map, no OOB

    def test_base_and_deco_gated_by_window(self):
        doc = make_doc(cols=40, rows=40)  # base at (1,1)
        doc.deco.append({"col": 30, "row": 30, "slot": "deco_tree"})
        # a window far from both, with the default tall_margin, excludes them
        items = tilemap.visible_render_items(doc, 10, 15, 10, 15)
        self.assertEqual([i for i in items if i.layer in ("entities", "deco")], [])
        # a window over the base includes it (entities layer)
        near = tilemap.visible_render_items(doc, 0, 3, 0, 3)
        self.assertEqual([i.slot_key for i in near if i.layer == "entities"],
                         ["base_hole"])

    def test_deco_anim_time_ms_carries_deterministic_phase(self):
        doc = make_doc(cols=40, rows=40)
        doc.deco.append({"col": 30, "row": 30, "slot": "deco_tree"})
        expected_phase = (30 * 131 + 30 * 197) % 997
        items = tilemap.visible_render_items(
            doc, 25, 35, 25, 35, anim_time_ms=500)
        deco = [i for i in items if i.layer == "deco"]
        self.assertEqual(deco[0].anim_time_ms, 500 + expected_phase)

    def test_deco_flip_passes_through_to_render_item(self):
        doc = make_doc(cols=40, rows=40)
        doc.deco.append({"col": 30, "row": 30, "slot": "deco_tree", "flip": True})
        items = tilemap.visible_render_items(doc, 25, 35, 25, 35)
        deco = [i for i in items if i.layer == "deco"]
        self.assertTrue(deco[0].flip)


class TestCameraStart(unittest.TestCase):
    """The camera-startpoint object mirrors the base: a single nullable movable
    map object. It centres the game camera at boot and is drawn only when the
    render `camera` toggle is on (default off)."""

    def test_defaults_to_none_and_round_trips(self):
        doc = make_doc()
        self.assertIsNone(doc.camera_start)  # absent by default (new maps too)
        # place one and round-trip through the serialized form
        doc.camera_start = {"col": 2, "row": 3, "slot": "camera_startpoint"}
        again = tilemap.from_dict(tilemap.to_dict(doc))
        self.assertEqual(again.camera_start,
                         {"col": 2, "row": 3, "slot": "camera_startpoint"})
        self.assertEqual(again, doc)

    def test_disk_round_trip_with_camera_start(self):
        doc = make_doc()
        doc.camera_start = {"col": 4, "row": 2, "slot": "camera_startpoint"}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "testmap.json"
        tilemap.save_map(doc, path, SCHEMA)
        self.assertEqual(tilemap.load_map(path, SCHEMA), doc)

    def test_slot_const_from_schema(self):
        schema = data_io.load_json(SCHEMA)
        self.assertEqual(
            tilemap.camera_start_slot_from_schema(schema), "camera_startpoint")

    def test_out_of_bounds_fails_loud(self):
        doc = make_doc()
        doc.camera_start = {"col": doc.cols, "row": 0, "slot": "camera_startpoint"}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_render_toggle_off_by_default(self):
        doc = make_doc()
        doc.camera_start = {"col": 2, "row": 2, "slot": "camera_startpoint"}
        # default camera=False → nothing emitted for it
        full = tilemap.render_items(doc)
        self.assertNotIn("camera_startpoint", [i.slot_key for i in full])
        # camera=True → the marker rides the entities layer
        on = tilemap.render_items(doc, camera=True)
        marker = [i for i in on if i.slot_key == "camera_startpoint"]
        self.assertEqual(len(marker), 1)
        self.assertEqual(marker[0].layer, "entities")
        self.assertEqual(marker[0].world_pos, (2, 2))

    def test_windowed_render_toggle_and_gating(self):
        doc = make_doc(cols=40, rows=40)
        doc.camera_start = {"col": 1, "row": 1, "slot": "camera_startpoint"}
        # a window over the startpoint, camera on → included
        near = tilemap.visible_render_items(doc, 0, 3, 0, 3, camera=True)
        self.assertIn("camera_startpoint", [i.slot_key for i in near])
        # same window, camera off (default) → excluded
        off = tilemap.visible_render_items(doc, 0, 3, 0, 3)
        self.assertNotIn("camera_startpoint", [i.slot_key for i in off])
        # a far window with camera on → still gated out by the tile window
        far = tilemap.visible_render_items(doc, 20, 25, 20, 25, camera=True)
        self.assertNotIn("camera_startpoint", [i.slot_key for i in far])


class TestStartArea(unittest.TestCase):
    """The 2×2 starting-area object: a single nullable movable map object whose
    {col,row} is the block's MIN corner (spans col..col+1 × row..row+1). It
    anchors the game's unlock-section grid; deliberately NOT emitted by the
    render emitters (the editor draws a pure outline instead)."""

    def test_defaults_to_none_and_round_trips(self):
        doc = make_doc()
        self.assertIsNone(doc.start_area)  # absent by default (new maps too)
        doc.start_area = {"col": 2, "row": 3, "slot": "start_area"}
        again = tilemap.from_dict(tilemap.to_dict(doc))
        self.assertEqual(again.start_area,
                         {"col": 2, "row": 3, "slot": "start_area"})
        self.assertEqual(again, doc)

    def test_disk_round_trip_with_start_area(self):
        doc = make_doc()
        doc.start_area = {"col": 3, "row": 2, "slot": "start_area"}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "testmap.json"
        tilemap.save_map(doc, path, SCHEMA)
        self.assertEqual(tilemap.load_map(path, SCHEMA), doc)

    def test_slot_const_from_schema(self):
        schema = data_io.load_json(SCHEMA)
        self.assertEqual(
            tilemap.start_area_slot_from_schema(schema), "start_area")

    def test_new_doc_has_no_start_area(self):
        doc = tilemap.new_doc("newmap", "New Map", 8, 8, SCHEMA)
        self.assertIsNone(doc.start_area)

    def test_2x2_bounds_fail_loud(self):
        # min corner at cols-1 leaves no room for the second column — invalid;
        # cols-2 is the last legal anchor.
        doc = make_doc()
        doc.start_area = {"col": doc.cols - 1, "row": 0, "slot": "start_area"}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)
        doc.start_area = {"col": 0, "row": doc.rows - 1, "slot": "start_area"}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)
        doc.start_area = {"col": doc.cols - 2, "row": doc.rows - 2,
                          "slot": "start_area"}
        tilemap.validate_doc(doc)  # last legal anchor passes

    def test_never_emitted_by_render_emitters(self):
        doc = make_doc()
        doc.start_area = {"col": 1, "row": 1, "slot": "start_area"}
        full = tilemap.render_items(doc, camera=True)
        self.assertNotIn("start_area", [i.slot_key for i in full])
        windowed = tilemap.visible_render_items(doc, 0, 5, 0, 4, camera=True)
        self.assertNotIn("start_area", [i.slot_key for i in windowed])


class TestTutorialMarkers(unittest.TestCase):
    """The tutorial-flute / tutorial-stone markers (D1, planning/
    TutorialPLAN.md): two single-tile nullable movable map objects mirroring
    camera_start; deliberately NOT emitted by the render emitters (the editor
    draws its own overlay, the game never draws them)."""

    def test_defaults_to_none_and_round_trips(self):
        doc = make_doc()
        self.assertIsNone(doc.tutorial_flute)  # absent by default
        self.assertIsNone(doc.tutorial_stone)
        doc.tutorial_flute = {"col": 2, "row": 3, "slot": "tutorial_flute"}
        doc.tutorial_stone = {"col": 3, "row": 4, "slot": "tutorial_stone"}
        again = tilemap.from_dict(tilemap.to_dict(doc))
        self.assertEqual(again.tutorial_flute,
                         {"col": 2, "row": 3, "slot": "tutorial_flute"})
        self.assertEqual(again.tutorial_stone,
                         {"col": 3, "row": 4, "slot": "tutorial_stone"})
        self.assertEqual(again, doc)

    def test_disk_round_trip_with_tutorial_markers(self):
        doc = make_doc()
        doc.tutorial_flute = {"col": 1, "row": 1, "slot": "tutorial_flute"}
        doc.tutorial_stone = {"col": 4, "row": 3, "slot": "tutorial_stone"}
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "testmap.json"
        tilemap.save_map(doc, path, SCHEMA)
        self.assertEqual(tilemap.load_map(path, SCHEMA), doc)

    def test_slot_const_from_schema(self):
        schema = data_io.load_json(SCHEMA)
        self.assertEqual(
            tilemap.tutorial_flute_slot_from_schema(schema), "tutorial_flute")
        self.assertEqual(
            tilemap.tutorial_stone_slot_from_schema(schema), "tutorial_stone")

    def test_new_doc_has_no_tutorial_markers(self):
        doc = tilemap.new_doc("newmap", "New Map", 8, 8, SCHEMA)
        self.assertIsNone(doc.tutorial_flute)
        self.assertIsNone(doc.tutorial_stone)

    def test_out_of_bounds_fails_loud(self):
        doc = make_doc()
        doc.tutorial_flute = {"col": doc.cols, "row": 0, "slot": "tutorial_flute"}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)
        doc = make_doc()
        doc.tutorial_stone = {"col": 0, "row": doc.rows, "slot": "tutorial_stone"}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)

    def test_never_emitted_by_render_emitters(self):
        doc = make_doc()
        doc.tutorial_flute = {"col": 1, "row": 1, "slot": "tutorial_flute"}
        doc.tutorial_stone = {"col": 2, "row": 1, "slot": "tutorial_stone"}
        full = tilemap.render_items(doc, camera=True)
        self.assertNotIn("tutorial_flute", [i.slot_key for i in full])
        self.assertNotIn("tutorial_stone", [i.slot_key for i in full])
        windowed = tilemap.visible_render_items(doc, 0, 5, 0, 4, camera=True)
        self.assertNotIn("tutorial_flute", [i.slot_key for i in windowed])
        self.assertNotIn("tutorial_stone", [i.slot_key for i in windowed])


class TestSpawnableBackground(unittest.TestCase):
    """The designer-painted spawn reserve: {(col,row): purchase} in memory, a
    list sorted by (row, col) on disk."""

    def test_round_trips_dict_to_sorted_list(self):
        doc = make_doc()
        self.assertEqual(doc.spawnable_background, {})  # empty by default
        doc.spawnable_background = {(3, 1): 2, (0, 1): 5, (4, 0): 1}
        data = tilemap.to_dict(doc)
        self.assertEqual(data["spawnable_background"], [
            {"col": 4, "row": 0, "purchase": 1},
            {"col": 0, "row": 1, "purchase": 5},
            {"col": 3, "row": 1, "purchase": 2},
        ])
        self.assertEqual(tilemap.from_dict(data), doc)

    def test_out_of_bounds_fails_loud(self):
        doc = make_doc()
        doc.spawnable_background = {(0, doc.rows): 1}
        with self.assertRaises(ValueError):
            tilemap.validate_doc(doc)


class TestBandRenderItems(unittest.TestCase):
    """Iso-diagonal ground emitter (d=col-row, s=col+row) for the ground cache's
    scroll strips: same tiles/slots as render_items over the covered cells, only
    ground, clamped to the map, correct s/d parity coupling."""

    def test_band_matches_full_render_over_covered_cells(self):
        doc = make_doc(cols=12, rows=12, fill="s")  # checker kind → parity matters
        d_min, d_max, s_min, s_max = -3, 3, 6, 14
        got = {i.world_pos: i.slot_key for i in tilemap.band_render_items(
            doc, d_min, d_max, s_min, s_max)}
        full = {i.world_pos: i.slot_key for i in tilemap.render_items(
            doc, base=False, deco=False)}
        expected = {
            (c, r): full[(c, r)]
            for r in range(doc.rows) for c in range(doc.cols)
            if d_min <= c - r <= d_max and s_min <= c + r <= s_max
        }
        self.assertEqual(got, expected)
        self.assertTrue(got, "band should cover some cells")

    def test_band_is_ground_only(self):
        doc = make_doc(cols=12, rows=12)
        items = tilemap.band_render_items(doc, -12, 12, 0, 24)
        self.assertTrue(all(i.layer == "ground" for i in items))
        self.assertEqual(len(items), doc.cols * doc.rows)  # whole map, clamped

    def test_band_clamps_and_respects_parity(self):
        doc = make_doc(cols=6, rows=6)
        # a wide-open band emits every cell exactly once (no OOB, no dupes)
        items = tilemap.band_render_items(doc, -100, 100, -100, 100)
        positions = [i.world_pos for i in items]
        self.assertEqual(len(positions), len(set(positions)))
        self.assertEqual(set(positions),
                         {(c, r) for r in range(6) for c in range(6)})

    def test_band_code_overrides(self):
        # A runtime caller (the game's unlock/recede) overrides single cells'
        # codes without touching doc.terrain; the overridden cell resolves via
        # the same legend/checker rule, everything else is byte-identical.
        doc = make_doc(cols=6, rows=6, fill="f")
        plain = {i.world_pos: i for i in tilemap.band_render_items(
            doc, -100, 100, -100, 100)}
        over = {i.world_pos: i for i in tilemap.band_render_items(
            doc, -100, 100, -100, 100,
            code_overrides={(2, 1): "b", (3, 1): "s"})}
        self.assertEqual(over[(2, 1)].slot_key,
                         tilemap.slot_for_code(doc.legend, "b", 2, 1))
        self.assertEqual(over[(3, 1)].slot_key,
                         tilemap.slot_for_code(doc.legend, "s", 3, 1))
        for pos, item in plain.items():
            if pos not in ((2, 1), (3, 1)):
                self.assertEqual(over[pos].slot_key, item.slot_key)
        self.assertEqual(doc.terrain[1][2], "f")   # doc untouched


class TestNewAndDuplicate(unittest.TestCase):
    def test_new_doc_is_schema_valid_and_filled(self):
        doc = tilemap.new_doc("fresh", "Fresh", 8, 6, SCHEMA)
        tilemap.validate_doc(doc)
        self.assertEqual(doc.terrain[0], ["f"] * 8)
        self.assertEqual(len(doc.terrain), 6)
        self.assertEqual(doc.base["slot"], "base_hole")
        # round-trips through the schema
        import jsonschema
        jsonschema.validate(tilemap.to_dict(doc), data_io.load_json(SCHEMA))

    def test_duplicate_is_deep(self):
        doc = make_doc()
        doc.deco.append({"col": 2, "row": 2, "slot": "deco_rock"})
        dup = tilemap.duplicate_doc(doc, "copy", "Copy")
        self.assertEqual(dup.map_id, "copy")
        dup.terrain[0][0] = "c"
        dup.deco[0]["col"] = 5
        dup.base["col"] = 3
        self.assertEqual(doc.terrain[0][0], "f")
        self.assertEqual(doc.deco[0]["col"], 2)
        self.assertEqual(doc.base["col"], 1)


class TestActiveMapHelpers(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        (self.data_dir / "maps").mkdir(parents=True)
        shutil.copytree(FIXTURE_DATA / "schemas", self.data_dir / "schemas")

    def test_list_load_and_pointer(self):
        doc = make_doc()
        tilemap.save_map(doc, tilemap.map_path(self.data_dir, "testmap"),
                         self.data_dir / "schemas" / "map_file.schema.json")
        data_io.write_validated(
            {"active": "testmap"},
            tilemap.active_map_path(self.data_dir),
            self.data_dir / "schemas" / "active_map.schema.json")
        self.assertEqual(tilemap.list_map_ids(self.data_dir), ["testmap"])
        loaded = tilemap.load_active_map(self.data_dir)
        self.assertEqual(loaded, doc)


if __name__ == "__main__":
    unittest.main()
