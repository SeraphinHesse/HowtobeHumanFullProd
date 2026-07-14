"""The exit gate, collapsed to one line an agent can read without reasoning.

    py tools/testgate.py check                 # the gate. This is the one you want.
    py tools/testgate.py check --affected      # only the blast radius of your diff
    py tools/testgate.py snapshot              # record today's failures as tolerated

Output is the whole point:

    GATE PASS  1122 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips

    GATE FAIL  1 problem(s)
      NEW FAILURE   tools/tests/test_boss.py::TestBoss::test_dead_goal_repaths

The suite is GREEN (TestGatePLAN TG-2), so the baseline is empty and `check`
is simply "is it still zero". The baseline machinery still earns its keep: it
means any failure someone DOES decide to tolerate has to be written down, in a
file, with a SHA — instead of living in a paragraph of a command doc that
drifts. That is what went wrong before: the tolerated set was prose, three
different docs quoted three different numbers, and agents re-ran the whole suite
in a clean worktree just to find out what was already broken.

Four design rules, and none of them is decorative:

1. KEY ON NODE-IDS, NOT COUNTS. Counts are exactly what drifted — a memory note
   in this repo recorded 980 tests; the real number was 1107. A set of node-IDs
   is exact and survives adding tests.
2. STAMP THE BASELINE with the git SHA and whether it was taken in a worktree. A
   stale baseline must announce itself rather than quietly lie.
3. REPORT NEWLY-FIXED TESTS. If an agent accidentally repairs a tolerated
   failure and nobody notices, the baseline is silently wrong from then on.
4. AN UNEXPECTED SKIP IS A FAILURE. This is what permanently kills the
   test_balancing_parity trap, where a whole class skipped inside a worktree and
   the gate went green having proved nothing.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / ".test-baseline.json"

# The short-report lines pytest emits with -rfEsX. Failures and skips are NOT
# formatted the same, which is a trap worth spelling out:
#   FAILED tools/tests/test_a.py::T::test_x - AssertionError: ...
#   SKIPPED [1] tools/tests/test_a.py:120: a build already exists
# Parsing both with one pattern silently captures "[1]" as the skip's node-id —
# every skip then collides under the same key and the baseline records a skip
# that can never be matched again.
_FAILED = re.compile(r"^(?P<outcome>FAILED|ERROR)\s+(?P<nodeid>\S+?)(?:\s+-\s+.*)?$")
# A skip is keyed by FILE + REASON, deliberately NOT by line number. pytest
# reports "SKIPPED [1] path/to/test.py:45: some reason", and keying on the line
# means adding an import to that file shifts it — the same sanctioned skip then
# reads as a brand-new unexpected one and the gate fails for nothing. The reason
# is the stable identity of a skip; the line is an implementation detail.
_SKIPPED = re.compile(r"^SKIPPED\s+\[\d+\]\s+(?P<file>[^\s:]+):\d+:\s*(?P<reason>.*)$")
_TOTAL = re.compile(r"(\d+) (?:passed|failed)")


def git(*args: str) -> str:
    return subprocess.run(("git", *args), cwd=REPO, capture_output=True,
                          text=True).stdout.strip()


def in_worktree() -> bool:
    """A linked worktree has a .git FILE, not a directory."""
    return (REPO / ".git").is_file()


def run_suite(extra: list[str] | None = None) -> tuple[dict[str, str], int]:
    """Run pytest; return ({node-id: outcome} for everything that did not pass,
    total tests that ran)."""
    cmd = [sys.executable, "-m", "pytest", "-q", "--no-header", "-rfEsX",
           *(extra or [])]
    proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    results: dict[str, str] = {}
    total = 0
    for line in (proc.stdout + proc.stderr).splitlines():
        line = line.strip()
        if m := _SKIPPED.match(line):
            results[f'{posix(m["file"])}: {m["reason"].strip()}'] = "SKIPPED"
        elif m := _FAILED.match(line):
            results[posix(m["nodeid"])] = m["outcome"]
        elif m := _TOTAL.search(line):
            total = max(total, int(m.group(1)))
    return results, total


def posix(nodeid: str) -> str:
    """Normalise separators. pytest reports skip locations with the platform's
    separator, so a baseline taken on Windows would not match a single node-id
    on the Linux runner — the whole tolerated set would read as 'new'."""
    return nodeid.replace("\\", "/")


def load_baseline() -> dict:
    if not BASELINE.exists():
        return {"sha": None, "worktree": False, "failures": [], "skips": []}
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def cmd_snapshot(args) -> int:
    results, _total = run_suite(args.pytest_args)
    doc = {
        "sha": git("rev-parse", "HEAD"),
        "worktree": in_worktree(),
        "failures": sorted(n for n, o in results.items()
                           if o in ("FAILED", "ERROR")),
        "skips": sorted(n for n, o in results.items() if o == "SKIPPED"),
    }
    BASELINE.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(f"baseline written: {len(doc['failures'])} tolerated failure(s), "
          f"{len(doc['skips'])} expected skip(s) @ {doc['sha'][:9]}")
    if doc["failures"]:
        print("NOTE: a NON-EMPTY baseline means you are tolerating red tests.")
        print("      The suite is supposed to be green. Justify each one.")
    return 0


def cmd_check(args) -> int:
    base = load_baseline()
    extra = list(args.pytest_args)

    if args.affected:
        selected = affected_modules(args.base_ref)
        if selected is None:
            print("GATE INFO  --affected could not narrow the set; "
                  "running everything")
        else:
            extra += selected
            print(f"GATE INFO  --affected selected {len(selected)} module(s) "
                  f"(+ the core tier)")

    results, total = run_suite(extra)

    known = set(base["failures"])
    expected_skips = set(base["skips"])
    failures = {n for n, o in results.items() if o in ("FAILED", "ERROR")}
    skips = {n for n, o in results.items() if o == "SKIPPED"}

    new = sorted(failures - known)
    fixed = sorted(known - failures) if not args.affected else []
    # Rule 4: a skip nobody signed off on is a failure. A test that quietly
    # stops running is indistinguishable from one that passes.
    surprise_skips = sorted(skips - expected_skips)

    if not new and not surprise_skips:
        print(f"GATE PASS  {total} ran | {len(known & failures)} known | "
              f"0 new | {len(fixed)} fixed | 0 unexpected skips")
        if fixed:
            print(f"  {len(fixed)} newly FIXED — re-run `snapshot` to record it:")
            for nodeid in fixed:
                print(f"    {nodeid}")
        return 0

    problems = len(new) + len(surprise_skips)
    print(f"GATE FAIL  {problems} problem(s)")
    for nodeid in new:
        print(f"  NEW FAILURE   {nodeid}")
    for nodeid in surprise_skips:
        print(f"  UNEXPECTED SKIP {nodeid}")
        print("     a skip nobody signed off on: the test did not run, and a "
              "test that does not run cannot be green")
    if known & failures:
        print(f"  ({len(known & failures)} known baseline failure(s) suppressed)")
    if fixed:
        print(f"  ({len(fixed)} newly FIXED: {', '.join(fixed)})")
    if base["sha"] and base["sha"] != git("rev-parse", "HEAD"):
        print(f"  NOTE: baseline was taken at {base['sha'][:9]}, HEAD is "
              f"{git('rev-parse', 'HEAD')[:9]} — it may be stale.")
    return 1


def affected_modules(base_ref: str) -> list[str] | None:
    """Changed files -> Graphify blast radius -> the test modules in it.

    Always UNION'd with the core tier, which costs ~40s and is cheap insurance
    against a blast radius that missed something. If anything about the
    selection is uncertain, we return None and the caller runs everything —
    a gate that under-selects is worse than a slow one.
    """
    changed = [f for f in git("diff", "--name-only", f"{base_ref}...HEAD").splitlines()
               if f.endswith(".py")]
    if not changed:
        return None

    # A change to the test scaffolding itself invalidates any narrowing.
    if any(f in ("conftest.py", "pytest.ini") or f.startswith("tools/tests/qt_harness")
           for f in changed):
        return None

    tests = {f for f in changed if f.startswith("tools/tests/")}
    sources = [f for f in changed if not f.startswith("tools/tests/")]

    for src in sources:
        stem = Path(src).stem
        out = subprocess.run(["graphify", "affected", stem],
                             cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            return None   # graph unavailable or stale -> do not narrow
        for line in out.stdout.splitlines():
            m = re.search(r"(tools/tests/test_\w+\.py)", line)
            if m:
                tests.add(m.group(1))

    if not tests:
        return None
    return ["-m", "core", *sorted(tests)]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="testgate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    snap = sub.add_parser("snapshot", help="record today's failures as tolerated")
    snap.add_argument("pytest_args", nargs="*", default=[])
    snap.set_defaults(func=cmd_snapshot)

    chk = sub.add_parser("check", help="run and diff against the baseline")
    chk.add_argument("--affected", action="store_true",
                     help="only the blast radius of the diff (+ the core tier)")
    chk.add_argument("--base-ref", default="Development")
    chk.add_argument("pytest_args", nargs="*", default=[])
    chk.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
