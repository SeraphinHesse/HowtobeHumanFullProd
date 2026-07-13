"""Phase 9A parity gate: prototype live balancing JSON -> nested tree.

The committed mapping table (balancing_parity_map.json) is the exhaustive
spec: every non-underscore key in every prototype Balancing_*.json appears
exactly once, as a migrated path, a MERGED pointer, or a DROPPED entry with
a reason. This test asserts that coverage both ways and value equality for
every migrated/merged key, plus the _py_only expectations for the
prototype's live py-only BOSS_ERAS list (reshaped into Boss stats +
death_spawn/spawns).

Skips whole if the prototype checkout is absent (other machines / CI).
"""
import ast
import json
import unittest
from pathlib import Path

from engine import data_io

REPO = Path(__file__).resolve().parents[2]
PROTO = REPO.parent / "HowToBeHuman" / "ClaudePrototype" / "HowToBeHuman" / "balancing"
MAP_PATH = Path(__file__).resolve().parent / "balancing_parity_map.json"
DOMAINS = ("buildings", "enemies", "map", "ui", "core")


def resolve(docs, spec):
    """'<domain>:<a/b/0/c>' -> the value at that path in the new tree."""
    domain, _, path = spec.partition(":")
    node = docs[domain]
    for seg in path.split("/"):
        node = node[int(seg)] if seg.isdigit() else node[seg]
    return node


def strip_keys(value, drop_keys):
    """Drop `drop_keys` from every dict in a struct-list. Lets a mapping entry
    migrate a tier list while deliberately dropping one dead sub-key from it
    (10A lifted `era_unlock_round` off the tier dicts onto the group)."""
    return [{k: v for k, v in item.items() if k not in drop_keys}
            for item in value]


@unittest.skipUnless(PROTO.is_dir(), "prototype checkout not present")
class TestBalancingParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mapping = json.loads(MAP_PATH.read_text(encoding="utf-8"))
        cls.docs = {
            d: data_io.load_validated(
                REPO / "data" / "balancing" / f"{d}.json",
                REPO / "data" / "schemas" / f"{d}.schema.json",
            )
            for d in DOMAINS
        }
        cls.proto = {}
        for fname in cls.mapping:
            if not fname.startswith("_"):
                cls.proto[fname] = json.loads((PROTO / fname).read_text(encoding="utf-8"))

    def entries(self):
        for fname, table in self.mapping.items():
            if not fname.startswith("_"):
                for key, entry in table.items():
                    yield fname, key, entry

    def test_mapping_covers_every_prototype_key_exactly(self):
        """Both directions: no prototype key unmapped, no mapping entry stale."""
        for fname, proto_doc in self.proto.items():
            real = {k for k in proto_doc if not k.startswith("_")}
            mapped = set(self.mapping[fname])
            with self.subTest(file=fname):
                self.assertEqual(real, mapped)

    def test_migrated_values_equal_prototype_values(self):
        checked = 0
        for fname, key, entry in self.entries():
            proto_value = self.proto[fname][key]
            if isinstance(entry, dict):
                spec = entry["path"]
                if entry.get("transform") == "literal_eval":
                    proto_value = ast.literal_eval(proto_value)
                if "drop_keys" in entry:
                    proto_value = strip_keys(proto_value, entry["drop_keys"])
            elif entry.startswith("DROPPED:"):
                continue
            elif entry.startswith("MERGED:"):
                spec = entry.removeprefix("MERGED:")
            else:
                spec = entry
            with self.subTest(file=fname, key=key):
                self.assertEqual(resolve(self.docs, spec), proto_value)
            checked += 1
        self.assertGreater(checked, 100)

    def test_dropped_entries_carry_a_reason(self):
        for fname, key, entry in self.entries():
            if isinstance(entry, str) and entry.startswith("DROPPED:"):
                with self.subTest(file=fname, key=key):
                    self.assertTrue(entry.removeprefix("DROPPED:").strip())

    def test_py_only_boss_eras_expectations(self):
        """BOSS_ERAS lives only in balancing_enemies.py; the mapping commits
        its literal values so parity survives without importing the package."""
        py_only = self.mapping["_py_only"]
        self.assertGreater(len(py_only), 0)
        for label, entry in py_only.items():
            with self.subTest(entry=label):
                self.assertEqual(resolve(self.docs, entry["path"]), entry["expect"])


if __name__ == "__main__":
    unittest.main()
