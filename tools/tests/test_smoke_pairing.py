"""Phase 6: tools/smoke.py's schema-pairing rule, including the ONE
directory exception (wrinkle 1). smoke.py is the universal exit gate, so
the rule itself is pinned by tests:

- data/maps/*.json (any stem) → map_file.schema.json
- data/maps/active_map.json   → active_map.schema.json (normal stem pairing)
- everything else             → <stem>.schema.json, missing schema fails loud
"""
import shutil
import tempfile
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]

from engine import data_io, tilemap
from tools import smoke


def make_map_dict(map_id="anyname"):
    doc = tilemap.new_doc(map_id, "Any Name", 6, 5,
                          REPO / "data" / "schemas" / "map_file.schema.json")
    return tilemap.to_dict(doc)


class TestPairingRule(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_root = Path(tmp.name) / "data"
        (self.data_root / "maps").mkdir(parents=True)
        shutil.copytree(REPO / "data" / "schemas", self.data_root / "schemas")

    def write(self, rel, data):
        path = self.data_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data_io.dumps_deterministic(data), encoding="utf-8")
        return path

    def test_map_file_with_arbitrary_stem_pairs_to_map_file_schema(self):
        self.write("maps/anyname.json", make_map_dict("anyname"))
        self.assertEqual(smoke.validate_data(self.data_root), 1)

    def test_invalid_map_file_fails(self):
        self.write("maps/anyname.json", {"not": "a map"})
        with self.assertRaises(jsonschema.ValidationError):
            smoke.validate_data(self.data_root)

    def test_active_map_keeps_stem_pairing(self):
        # valid against active_map.schema.json — would NOT validate against
        # map_file.schema.json, so passing proves the stem pairing was used
        self.write("maps/active_map.json", {"active": "anyname"})
        self.assertEqual(smoke.validate_data(self.data_root), 1)

    def test_invalid_active_map_fails(self):
        self.write("maps/active_map.json", {"active": "NOT-A-VALID-ID"})
        with self.assertRaises(jsonschema.ValidationError):
            smoke.validate_data(self.data_root)

    def test_mispaired_file_outside_maps_still_fails_loud(self):
        # the directory rule must not loosen the original convention
        self.write("no_such_schema_stem.json", {"anything": 1})
        with self.assertRaises(FileNotFoundError):
            smoke.validate_data(self.data_root)

    def test_ui_screen_file_with_arbitrary_stem_pairs_to_ui_screen_schema(self):
        self.write("ui/screens/main_menu.json", {})
        self.write("ui/screens/pause.json", {"widgets": {}})
        self.assertEqual(smoke.validate_data(self.data_root), 2)

    def test_invalid_ui_screen_file_fails(self):
        self.write("ui/screens/bad.json", {"widgets": {"w": "not-an-object"}})
        with self.assertRaises(jsonschema.ValidationError):
            smoke.validate_data(self.data_root)

    def test_repo_data_still_validates(self):
        # the exit gate itself, on the real committed data/
        self.assertGreater(smoke.validate_data(), 0)


if __name__ == "__main__":
    unittest.main()
