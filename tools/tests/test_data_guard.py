"""tools/data_guard.py — the tripwire for "the suite corrupted data/".

Fixture-driven: builds its own little tree rather than hashing the real data/,
so it is fast and says nothing about the repo's current state.
"""
import tempfile
import unittest
from pathlib import Path

from tools import data_guard


class GuardCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "sub").mkdir()
        (self.root / "a.json").write_text('{"x": 1}', encoding="utf-8")
        (self.root / "sub" / "b.json").write_text('{"y": 2}', encoding="utf-8")

    def snap(self):
        return data_guard.snapshot(self.root)


class TestSnapshot(GuardCase):
    def test_hashes_every_file_by_relative_posix_path(self):
        snap = self.snap()
        self.assertEqual(sorted(snap), ["a.json", "sub/b.json"])

    def test_unchanged_tree_is_clean(self):
        self.assertEqual(data_guard.diff(self.snap(), self.snap()), [])

    def test_rewriting_identical_bytes_is_not_corruption(self):
        """Content, not mtime — a byte-identical rewrite must not cry wolf."""
        before = self.snap()
        (self.root / "a.json").write_text('{"x": 1}', encoding="utf-8")
        self.assertEqual(data_guard.diff(before, self.snap()), [])


class TestDiff(GuardCase):
    def test_detects_a_modified_file(self):
        before = self.snap()
        (self.root / "a.json").write_text('{"x": 999}', encoding="utf-8")
        self.assertEqual(data_guard.diff(before, self.snap()),
                         ["MODIFIED data/a.json"])

    def test_detects_a_created_file(self):
        """The real incident: the suite invented data/maps/uitestexample.json."""
        before = self.snap()
        (self.root / "sub" / "new.json").write_text("{}", encoding="utf-8")
        self.assertEqual(data_guard.diff(before, self.snap()),
                         ["CREATED  data/sub/new.json"])

    def test_detects_a_deleted_file(self):
        before = self.snap()
        (self.root / "a.json").unlink()
        self.assertEqual(data_guard.diff(before, self.snap()),
                         ["DELETED  data/a.json"])

    def test_reports_every_problem_not_just_the_first(self):
        before = self.snap()
        (self.root / "a.json").write_text("{}", encoding="utf-8")
        (self.root / "sub" / "b.json").unlink()
        (self.root / "c.json").write_text("{}", encoding="utf-8")
        self.assertEqual(
            data_guard.diff(before, self.snap()),
            ["CREATED  data/c.json",
             "DELETED  data/sub/b.json",
             "MODIFIED data/a.json"])
