"""MasterSheetColumnsPLAN C3 — engine/assets/master_registry.py.

Pure: no pygame, no Qt. Every test PINS ITS OWN registry into a temp `data/`
copy (`DataDirCase`) and asserts against that alone — never against live
`data/`, whose master sheets change whenever an artist imports one.
"""
import json
import unittest

from jsonschema import ValidationError

from engine.assets import master_registry
from tools.tests.temp_data import DataDirCase

FIXTURE = {
    "version": 1,
    "entries": {
        "village_folk": {
            "file": "master/village_folk.png",
            "display_name": "Village Folk",
            "frame_w": 32,
            "frame_h": 48,
            "column_width": 6,
            "columns": ["red", "blue", "green"],
        },
        "unnamed_cols": {
            "file": "master/unnamed_cols.png",
            "display_name": "Unnamed",
            "frame_w": 16,
            "frame_h": 16,
            "column_width": 2,
        },
    },
}


class MasterRegistryLoadTest(DataDirCase):
    """`load_registry` is INFRASTRUCTURE: it fails loud, never degrades."""

    def pin(self, doc):
        path = master_registry.registry_path(self.data_dir)
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path

    def test_round_trips_a_pinned_registry(self):
        self.pin(FIXTURE)
        self.assertEqual(master_registry.load_registry(self.data_dir), FIXTURE)

    def test_raises_on_a_schema_invalid_registry(self):
        entry = dict(FIXTURE["entries"]["village_folk"])
        del entry["column_width"]
        self.pin({"version": 1, "entries": {"village_folk": entry}})
        with self.assertRaises(ValidationError):
            master_registry.load_registry(self.data_dir)

    def test_raises_on_an_absent_registry(self):
        with self.assertRaises(OSError):
            master_registry.load_registry(self.data_dir / "no_such_data")


class ColumnAccessorTest(unittest.TestCase):
    """`columns_for`/`column_width_for` are TOTAL — they never raise."""

    def test_resolve_a_known_master_ref(self):
        self.assertEqual(
            master_registry.columns_for(FIXTURE, "master/village_folk.png"),
            ("red", "blue", "green"))
        self.assertEqual(
            master_registry.column_width_for(FIXTURE, "master/village_folk.png"),
            6)
        # An entry with no `columns` is unnamed, not unresolved.
        self.assertEqual(
            master_registry.columns_for(FIXTURE, "master/unnamed_cols.png"), ())
        self.assertEqual(
            master_registry.column_width_for(FIXTURE, "master/unnamed_cols.png"),
            2)

    def test_unresolvable_refs_return_empty_values(self):
        for ref in ("imported/village_folk.png", "master/nobody.png", None, 7):
            self.assertEqual(master_registry.columns_for(FIXTURE, ref), ())
            self.assertEqual(master_registry.column_width_for(FIXTURE, ref), 0)


if __name__ == "__main__":
    unittest.main()
