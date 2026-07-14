"""Phase 9H: game.core.names.append_random_name — the one runtime data write.

Runs against a tempfile copy of data/ (repo data never touched). Pure logic:
no pygame, no SDL. Asserts the prototype add_random_name semantics (append,
reject blank + duplicate) plus schema-canonical persistence with unrelated
keys intact.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from engine import data_io
from game.core import append_random_name

REPO = Path(__file__).resolve().parents[2]


class TestAppendRandomName(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)
        self.buildings = self.data_dir / "balancing" / "buildings.json"
        self.schema = self.data_dir / "schemas" / "buildings.schema.json"

    def _names(self):
        return data_io.load_validated(self.buildings, self.schema)[
            "BuildingsGlobal"]["random_names"]

    def test_append_new_name_persists(self):
        before = self._names()
        self.assertNotIn("Zaphod", before)
        self.assertTrue(append_random_name(self.data_dir, "Zaphod"))
        after = self._names()
        self.assertEqual(after, before + ["Zaphod"])  # appended at the end

    def test_whitespace_is_trimmed(self):
        self.assertTrue(append_random_name(self.data_dir, "  Trillian  "))
        self.assertIn("Trillian", self._names())

    def test_blank_rejected(self):
        before = self._names()
        self.assertFalse(append_random_name(self.data_dir, "   "))
        self.assertEqual(self._names(), before)  # nothing written

    def test_duplicate_rejected(self):
        existing = self._names()[0]
        self.assertFalse(append_random_name(self.data_dir, existing))
        self.assertEqual(self._names().count(existing), 1)

    def test_other_keys_preserved(self):
        raw_before = data_io.load_json(self.buildings)
        append_random_name(self.data_dir, "Marvin")
        raw_after = data_io.load_json(self.buildings)
        # only random_names changed — every sibling key survives the write
        raw_after["BuildingsGlobal"]["random_names"] = raw_before[
            "BuildingsGlobal"]["random_names"]
        self.assertEqual(raw_after, raw_before)

    def test_file_stays_schema_canonical(self):
        append_random_name(self.data_dir, "Ford")
        on_disk = self.buildings.read_text(encoding="utf-8")
        canonical = data_io.dumps_deterministic(data_io.load_json(self.buildings))
        self.assertEqual(on_disk, canonical)


if __name__ == "__main__":
    unittest.main()
