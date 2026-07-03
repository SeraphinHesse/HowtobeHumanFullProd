"""Phase 4 acceptance tests for the balancing data files (D-10/11/12).

Every domain's schema/content pair must load through engine.data_io
(fail-loud validation), sit on disk in canonical D-3 form, and start
UNLOCKED. Schemas must reject unknown keys, malformed _lock shapes, and
out-of-range numerics — and write_validated must raise BEFORE touching
disk on invalid input.
"""
import json
import tempfile
import unittest
from pathlib import Path

import jsonschema

from engine import data_io

REPO = Path(__file__).resolve().parents[2]
DOMAINS = ("buildings", "enemies", "map", "ui", "core")  # canonical D-10 order


def paths(domain):
    return (
        REPO / "data" / "balancing" / f"{domain}.json",
        REPO / "data" / "schemas" / f"{domain}.schema.json",
    )


class TestBalancingFiles(unittest.TestCase):
    def test_every_domain_pair_validates_and_starts_unlocked(self):
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            with self.subTest(domain=domain):
                data = data_io.load_validated(data_path, schema_path)
                self.assertEqual(data["_lock"], "UNLOCKED")

    def test_files_are_canonical_on_disk(self):
        """D-3: byte-identical to dumps_deterministic of their own content."""
        for domain in DOMAINS:
            data_path, _ = paths(domain)
            with self.subTest(domain=domain):
                text = data_path.read_text(encoding="utf-8")
                self.assertEqual(text, data_io.dumps_deterministic(json.loads(text)))

    def test_every_key_documents_units_in_description(self):
        """D-12: each tunable's schema entry carries a description."""
        for domain in DOMAINS:
            _, schema_path = paths(domain)
            schema = data_io.load_json(schema_path)
            for key, prop in schema["properties"].items():
                with self.subTest(domain=domain, key=key):
                    self.assertTrue(prop.get("description"))


class TestSchemaRejections(unittest.TestCase):
    def test_unknown_key_rejected(self):
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            data = data_io.load_validated(data_path, schema_path)
            data["not_a_real_key"] = 1
            with self.subTest(domain=domain):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(data, data_io.load_json(schema_path))

    def test_malformed_lock_rejected(self):
        data_path, schema_path = paths("buildings")
        schema = data_io.load_json(schema_path)
        for bad in ("unlocked", {"locked_by": "x"}, {"since": "2026-07-03"}, {}):
            data = data_io.load_validated(data_path, schema_path)
            data["_lock"] = bad
            with self.subTest(bad=bad):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(data, schema)

    def test_valid_locked_shape_accepted(self):
        """The locked shape ED-32 displays must itself be schema-legal."""
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            data = data_io.load_validated(data_path, schema_path)
            data["_lock"] = {"locked_by": "featureBuildings", "since": "2026-07-03"}
            with self.subTest(domain=domain):
                jsonschema.validate(data, data_io.load_json(schema_path))

    def test_out_of_range_numeric_rejected(self):
        """Every numeric tunable declares a maximum, and it is enforced."""
        checked = 0
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            schema = data_io.load_json(schema_path)
            for key, prop in schema["properties"].items():
                if "maximum" not in prop:
                    continue
                data = data_io.load_validated(data_path, schema_path)
                data[key] = prop["maximum"] + 1
                with self.subTest(domain=domain, key=key):
                    with self.assertRaises(jsonschema.ValidationError):
                        jsonschema.validate(data, schema)
                checked += 1
        self.assertGreater(checked, 0)

    def test_write_validated_raises_before_touching_disk(self):
        data_path, schema_path = paths("buildings")
        data = data_io.load_validated(data_path, schema_path)
        data["_lock"] = "not a lock"
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "buildings.json"
            with self.assertRaises(jsonschema.ValidationError):
                data_io.write_validated(data, target, schema_path)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
