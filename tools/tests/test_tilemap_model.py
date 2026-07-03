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

from engine import data_io, tilemap

SCHEMA = REPO / "data" / "schemas" / "map_file.schema.json"
ACTIVE_SCHEMA = REPO / "data" / "schemas" / "active_map.schema.json"


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
        shutil.copytree(REPO / "data" / "schemas", self.data_dir / "schemas")

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
