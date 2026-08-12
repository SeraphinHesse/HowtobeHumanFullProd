"""The CI shard table covers every test module exactly once — enforced.

Sharding CI trades one legible job for six, and buys back the wall clock that
was killing the run. The cost is a new way to be silently wrong: a module that
no shard selects simply never runs, and a green matrix says so with total
confidence. That is the same failure mode ``test_tiers`` exists to prevent, one
layer up, so it gets the same treatment — a hard error naming the offender.

These tests read ``tools/ci_shards.py``'s table and ``conftest.TIERS``; they do
not run pytest. Selection is computed from the two tables, which is the point:
if the tables disagree with each other, that IS the bug.
"""
import unittest
from pathlib import Path

from conftest import TIERS
from tools import ci_shards

TESTS_DIR = Path(ci_shards.TESTS_DIR)


def _modules():
    """Every collectable test module stem, from disk."""
    return {p.stem for p in TESTS_DIR.glob("test_*.py")}


def _selected_by(shard):
    """The module stems a shard's pytest args would collect.

    Mirrors the two selection mechanisms the table actually uses — an explicit
    file list, or `-m <tier>` minus any `--ignore`d files. Anything else in
    `args` would make this untrue, which is why test_shard_args_stay_simple
    forbids it.
    """
    tokens = shard["args"].split()
    explicit = {Path(t).stem for t in tokens if t.startswith("tools/tests/")}
    if explicit:
        return explicit
    tier = tokens[tokens.index("-m") + 1]
    ignored = {Path(t.split("=", 1)[1]).stem
               for t in tokens if t.startswith("--ignore=")}
    return {stem for stem, t in TIERS.items() if t == tier} - ignored


class TestEveryModuleRunsExactlyOnce(unittest.TestCase):
    def test_every_module_is_selected_by_exactly_one_shard(self):
        counts = {stem: 0 for stem in _modules()}
        for shard in ci_shards.shards():
            for stem in _selected_by(shard):
                self.assertIn(stem, counts,
                              f"shard {shard['name']} selects {stem}, which is "
                              "not a test module on disk")
                counts[stem] += 1

        never = sorted(s for s, n in counts.items() if n == 0)
        twice = sorted(s for s, n in counts.items() if n > 1)
        self.assertEqual(
            never, [],
            "these modules are in no CI shard, so CI would never run them "
            f"and would still go green: {never}")
        self.assertEqual(
            twice, [],
            "these modules are in more than one CI shard, so CI pays for them "
            f"twice: {twice}")

    def test_shard_names_are_unique(self):
        names = [s["name"] for s in ci_shards.shards()]
        self.assertEqual(sorted(names), sorted(set(names)),
                         f"duplicate shard names: {names}")


class TestHeavyEditorFiles(unittest.TestCase):
    def test_heavy_files_exist(self):
        missing = [f for f in ci_shards.HEAVY_EDITOR_FILES
                   if not (TESTS_DIR / f).exists()]
        self.assertEqual(missing, [],
                         f"HEAVY_EDITOR_FILES names files that are gone: "
                         f"{missing}")

    def test_heavy_files_are_editor_tier(self):
        wrong = {f: TIERS.get(Path(f).stem)
                 for f in ci_shards.HEAVY_EDITOR_FILES
                 if TIERS.get(Path(f).stem) != "editor"}
        self.assertEqual(
            wrong, {},
            "a heavy file that is not editor tier would be double-run: "
            "editor-rest only --ignores it from `-m editor`, so its own tier "
            f"shard picks it up as well. {wrong}")

    def test_editor_rest_ignores_exactly_the_heavy_union(self):
        """The --ignore set must equal the union of the heavy groups.

        Adding a heavy shard without ignoring its file double-runs it; ignoring
        a file without giving it a shard drops it entirely. Pin both directions.
        """
        grouped = [f for _name, files in ci_shards.HEAVY_GROUPS for f in files]
        self.assertEqual(sorted(grouped), sorted(ci_shards.HEAVY_EDITOR_FILES))

        rest = next(s for s in ci_shards.shards() if s["name"] == "editor-rest")
        ignored = sorted(t.split("=", 1)[1].removeprefix("tools/tests/")
                         for t in rest["args"].split()
                         if t.startswith("--ignore="))
        self.assertEqual(ignored, sorted(ci_shards.HEAVY_EDITOR_FILES))

    def test_no_file_is_in_two_heavy_groups(self):
        grouped = [f for _name, files in ci_shards.HEAVY_GROUPS for f in files]
        self.assertEqual(sorted(grouped), sorted(set(grouped)),
                         f"a file appears in two heavy groups: {grouped}")


class TestTheTablesPremises(unittest.TestCase):
    def test_dist_loadfile_is_still_pinned(self):
        """The whole shard table rests on 'a FILE is the atomic unit'.

        Drop --dist loadfile and per-file shards stop making sense (and the Qt
        suites start fighting over one QApplication). Pin the premise.
        """
        ini = (Path(ci_shards.REPO) / "pytest.ini").read_text(encoding="utf-8")
        self.assertIn("--dist loadfile", ini)

    def test_shard_args_stay_simple(self):
        """No -k slicing, and no splitting a file across shards.

        Two processes on one module re-introduces the shared-QApplication
        contention --dist loadfile exists to prevent. This also keeps
        _selected_by() an honest model of what the args do.
        """
        for shard in ci_shards.shards():
            tokens = shard["args"].split()
            self.assertNotIn("-k", tokens,
                             f"shard {shard['name']} slices with -k")
            explicit = [t for t in tokens if t.startswith("tools/tests/")]
            if explicit:
                self.assertNotIn("-m", tokens,
                                 f"shard {shard['name']} mixes an explicit "
                                 "file list with a marker selection")

    def test_matrix_is_json_serialisable(self):
        """CI feeds this straight to fromJSON; a non-serialisable value is a
        red matrix with a confusing message."""
        import json
        json.loads(json.dumps(ci_shards.matrix()))
        self.assertEqual(list(ci_shards.matrix()), ["include"])
