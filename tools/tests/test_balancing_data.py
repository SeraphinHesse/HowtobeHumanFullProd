"""Acceptance tests for the balancing data files (D-10/12, Phase 9A tree).

Every domain's schema/content pair must load through engine.data_io
(fail-loud validation) and sit on disk in canonical D-3 form. Since Phase
9A the domains are nested REPLAN trees, so the D-12 walks (description on
every leaf, minimum/maximum on every numeric) recurse through properties,
array items, and in-file $defs. Schemas must reject unknown keys at any
depth and out-of-range numerics - and write_validated must raise BEFORE
touching disk on invalid input.
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


def deref(schema, node):
    """Resolve local #/$defs/ refs (the only kind the house style allows)."""
    while "$ref" in node:
        ref = node["$ref"]
        assert ref.startswith("#/$defs/"), ref
        node = schema["$defs"][ref.removeprefix("#/$defs/")]
    return node


def schema_leaves(schema):
    """Yield (path, subschema) for every typed leaf."""
    def walk(node, path):
        node = deref(schema, node)
        if node.get("type") == "object":
            for key, prop in node.get("properties", {}).items():
                yield from walk(prop, path + (key,))
        elif node.get("type") == "array":
            yield from walk(node["items"], path + ("<items>",))
        else:
            yield path, node
    yield from walk(schema, ())


def doc_schema_pairs(doc, schema):
    """Yield (path, value, subschema) for every leaf value in the data doc."""
    def walk(value, node, path):
        node = deref(schema, node)
        if isinstance(value, dict):
            for key, sub in value.items():
                yield from walk(sub, node["properties"][key], path + (key,))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                yield from walk(item, node["items"], path + (i,))
        else:
            yield path, value, node
    for key, sub in doc.items():
        yield from walk(sub, schema["properties"][key], (key,))


def set_at(doc, path, value):
    node = doc
    for seg in path[:-1]:
        node = node[seg]
    node[path[-1]] = value


class TestBalancingFiles(unittest.TestCase):
    def test_every_domain_pair_validates(self):
        """Every domain's data/schema pair loads through the fail-loud
        validator."""
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            with self.subTest(domain=domain):
                data_io.load_validated(data_path, schema_path)

    def test_files_are_canonical_on_disk(self):
        """D-3: byte-identical to dumps_deterministic of their own content."""
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            for target in (data_path, schema_path):
                with self.subTest(file=target.name):
                    text = target.read_text(encoding="utf-8")
                    self.assertEqual(
                        text, data_io.dumps_deterministic(json.loads(text))
                    )

    def test_every_leaf_documents_units_in_description(self):
        """D-12: every typed leaf at ANY depth carries a description."""
        for domain in DOMAINS:
            _, schema_path = paths(domain)
            schema = data_io.load_json(schema_path)
            count = 0
            for path, prop in schema_leaves(schema):
                with self.subTest(domain=domain, path="/".join(map(str, path))):
                    self.assertTrue(prop.get("description"))
                count += 1
            self.assertGreater(count, 0)

    def test_every_numeric_leaf_declares_bounds(self):
        """D-12: every integer/number leaf has minimum AND maximum (the
        editor derives spinbox ranges from them, ED-30)."""
        for domain in DOMAINS:
            _, schema_path = paths(domain)
            schema = data_io.load_json(schema_path)
            for path, prop in schema_leaves(schema):
                if prop.get("type") in ("integer", "number"):
                    with self.subTest(domain=domain, path="/".join(map(str, path))):
                        self.assertIn("minimum", prop)
                        self.assertIn("maximum", prop)


class TestSchemaRejections(unittest.TestCase):
    def test_unknown_key_rejected_at_top_level(self):
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            data = data_io.load_validated(data_path, schema_path)
            data["not_a_real_key"] = 1
            with self.subTest(domain=domain):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(data, data_io.load_json(schema_path))

    def test_unknown_key_rejected_in_nested_objects(self):
        """additionalProperties:false holds at every depth of the tree."""
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            data = data_io.load_validated(data_path, schema_path)
            group = next(k for k in sorted(data) if isinstance(data[k], dict))
            data[group]["not_a_real_key"] = 1
            with self.subTest(domain=domain, group=group):
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(data, data_io.load_json(schema_path))

    def test_out_of_range_numeric_rejected(self):
        """Every domain has enforced bounds: violating the first numeric
        leaf's maximum (including one nested inside a tier array) fails."""
        checked = 0
        for domain in DOMAINS:
            data_path, schema_path = paths(domain)
            schema = data_io.load_json(schema_path)
            data = data_io.load_validated(data_path, schema_path)
            for path, _value, prop in doc_schema_pairs(data, schema):
                if prop.get("type") not in ("integer", "number"):
                    continue
                set_at(data, path, prop["maximum"] + 1)
                with self.subTest(domain=domain, path="/".join(map(str, path))):
                    with self.assertRaises(jsonschema.ValidationError):
                        jsonschema.validate(data, schema)
                checked += 1
                break
        self.assertEqual(checked, len(DOMAINS))

    def test_write_validated_raises_before_touching_disk(self):
        data_path, schema_path = paths("buildings")
        data = data_io.load_validated(data_path, schema_path)
        data["not_a_real_key"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "buildings.json"
            with self.assertRaises(jsonschema.ValidationError):
                data_io.write_validated(data, target, schema_path)
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
