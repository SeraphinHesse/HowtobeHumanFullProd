"""The CI shard table — one greppable table, in Python, not in YAML.

Same doctrine as ``conftest.TIERS``: the thing that decides what runs where
lives in a file you can import, diff and TEST, rather than being spread across
a workflow's matrix literal where nothing can check it. ``.github/workflows/
tests.yml`` calls ``--matrix`` here and feeds the result to ``fromJSON``, so
adding a shard is a one-line edit to SHARDS and CI picks it up.

Why shard at all. The suite was one job on a 2-core runner with
``timeout-minutes: 20``, and it stopped finishing — GitHub reported that as
*cancelled*, which reads like "superseded by a newer push" rather than
"broken", and ~10 branches merged into Development on the strength of it.

Why marker sharding alone is NOT enough. The ``editor`` tier is only 18 files
but dominates wall time, and ``pytest.ini`` pins ``--dist loadfile`` — a FILE
is the atomic unit of parallelism, so the critical path of the editor tier is
its single slowest FILE (``test_editor_map_mode.py``, which builds a MainWindow
in setUp for all 63 of its tests). No worker count fixes that. The heavy files
therefore get their own runners.

Two rules this table must keep, both enforced by tools/tests/test_ci_shards.py:

1. **Never split a single file across shards.** No ``-k`` slicing, no
   test-level splitting. Two processes on one module re-introduces exactly the
   shared-QApplication contention ``--dist loadfile`` exists to prevent.
2. **Every test module is selected by EXACTLY one shard.** Zero shards means a
   module silently stops running (the ``test_tiers`` failure mode); two means
   it runs twice and the slow tier gets slower for nothing.
"""
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TESTS_DIR = REPO / "tools" / "tests"

#: Editor modules heavy enough to own a runner, rather than queue behind one
#: another inside the editor tier. Under --dist loadfile these are each a
#: single indivisible unit of work, so the tier's wall clock is the worst one.
#: `editor-rest` --ignore's exactly this set; test_ci_shards.py pins that
#: equality, so adding a shard here without ignoring it is a hard error rather
#: than a silent double-run.
HEAVY_EDITOR_FILES = (
    "test_editor_map_mode.py",
    "test_editor_panels.py",
    "test_editor_viewport.py",
    "test_details_panel.py",
)

#: How the heavy files are grouped onto runners. A group is a list because two
#: cheap-ish heavies can share a runner; a file appears in exactly one group.
HEAVY_GROUPS = (
    ("editor-map-mode", ["test_editor_map_mode.py"]),
    ("editor-panels", ["test_editor_panels.py"]),
    ("editor-viewport", ["test_editor_viewport.py", "test_details_panel.py"]),
)


def _heavy_shards():
    for name, files in HEAVY_GROUPS:
        yield {
            "name": name,
            # -n0: xdist buys nothing when loadfile hands a whole file to one
            # worker anyway, and it keeps pytest-timeout's stack dumps
            # readable (a dump from inside a worker is far harder to read).
            "args": "-n0 " + " ".join(f"tools/tests/{f}" for f in files),
        }


def _editor_rest():
    ignores = " ".join(f"--ignore=tools/tests/{f}" for f in HEAVY_EDITOR_FILES)
    return {"name": "editor-rest", "args": f"-n auto -m editor {ignores}"}


def shards():
    """The full shard list, in the order CI should display them."""
    return [
        {"name": "core", "args": "-n auto -m core"},
        {"name": "meta", "args": "-n auto -m meta"},
        _editor_rest(),
        *_heavy_shards(),
    ]


def matrix():
    """The GitHub Actions matrix `include` list."""
    return {"include": shards()}


def _main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--matrix", action="store_true",
                    help="print the GitHub Actions matrix as JSON")
    args = ap.parse_args()
    if args.matrix:
        print(json.dumps(matrix()))
    else:
        for shard in shards():
            print(f"{shard['name']:<18} {shard['args']}")


if __name__ == "__main__":
    _main()
