"""The exit gate, collapsed to one line an agent can read without reasoning.

    py tools/testgate.py check                 # the gate. This is the one you want.
    py tools/testgate.py check --affected      # only the blast radius of your diff
    py tools/testgate.py check --stream        # same gate, output echoed LIVE
    py tools/testgate.py snapshot              # record today's failures as tolerated

Output is the whole point:

    GATE PASS  2245 ran | 0 known | 0 new | 0 fixed | 0 unexpected skips

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
   prototype-parity trap, where a whole class skipped inside a worktree and the
   gate went green having proved nothing. (That suite is now deleted outright —
   the migration is complete — but the rule is what stops the next one.)

Rule 4 has a sibling learned the same way: A SUBTEST FAILURE IS A FAILURE. See
_SUBFAILED below — pytest reports those in a shape the FAILED pattern does not
match, and for a while the gate printed PASS over five red tests.

And a THIRD sibling, found 2026-07-14: COLOR IS A FAILURE SHAPE TOO. Agent
shells export FORCE_COLOR, pytest obeys it even when piped, and a colored
summary line starts with an escape code — so `^FAILED` matched nothing while
the tally regex still counted, and the gate printed PASS over two red tests
for a whole working session. The suite's OUTPUT is an interface; every way it
can be re-dressed (skip, subtest, ANSI) has now bitten once. run_suite both
disables color in the child and strips escapes before parsing.
"""
from __future__ import annotations

import argparse
import json
import os
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
# pytest-subtests reports a failing SUBTEST in a THIRD shape — outcome first,
# its parameters in parentheses, and the node-id trailing:
#   SUBFAILED(file="'x.json'", key="'K'") tools/tests/test_a.py::T::test_x
# Matching only FAILED/ERROR made these invisible: the gate printed GATE PASS
# with five red tests in the suite, because every one of them was a subtest. The
# params are part of the key — one test can fail N subtests independently, and
# collapsing them would let four of five vanish from the baseline.
_SUBFAILED = re.compile(
    r"^SUB(?P<outcome>FAILED|ERROR)(?P<params>\(.*\))?\s+(?P<nodeid>\S+?)"
    r"(?:\s+-\s+.*)?$")
# A skip is keyed by FILE + REASON, deliberately NOT by line number. pytest
# reports "SKIPPED [1] path/to/test.py:45: some reason", and keying on the line
# means adding an import to that file shifts it — the same sanctioned skip then
# reads as a brand-new unexpected one and the gate fails for nothing. The reason
# is the stable identity of a skip; the line is an implementation detail.
_SKIPPED = re.compile(r"^SKIPPED\s+\[\d+\]\s+(?P<file>[^\s:]+):\d+:\s*(?P<reason>.*)$")
# Summed, not first-match: pytest's tally line reads "5 failed, 1170 passed, …",
# and a `.search` grabs the 5 — the gate then announced "5 ran" for a full suite.
# "subtests passed" is deliberately NOT counted (the digits there are followed by
# "subtests", not "passed"), so the number stays a count of TESTS.
_TOTAL = re.compile(r"(\d+) (?:passed|failed)")


def git(*args: str) -> str:
    return subprocess.run(("git", *args), cwd=REPO, capture_output=True,
                          text=True).stdout.strip()


def in_worktree() -> bool:
    """A linked worktree has a .git FILE, not a directory."""
    return (REPO / ".git").is_file()


#: ANSI SGR escapes. Stripped before parsing — see the module docstring's
#: third sibling: a `\x1b[31mFAILED` line is invisible to `^FAILED`.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _stream_child(cmd: list[str], env: dict[str, str]) -> str:
    """Run the child line-buffered, ECHOING each line as it arrives, and return
    the whole output anyway.

    This exists for exactly one caller: the editor's test panel (TestRunnerPLAN
    TR-3/TR-5), which needs per-file progress WHILE the gate runs and the gate's
    own authoritative verdict at the end. Capturing everything and printing
    nothing until exit (the default path below) cannot give it the first; a
    second, separate pytest run cannot give it the second without forking the
    verdict logic, which is the one thing D2 forbids. So the stream is a
    passthrough and NOTHING about parsing or the verdict changes — see
    run_suite: both paths hand the same text to the same loop.
    """
    proc = subprocess.Popen(cmd, cwd=REPO, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, bufsize=1,
                            env=env)
    chunks: list[str] = []
    if proc.stdout is not None:
        for line in proc.stdout:
            chunks.append(line)
            sys.stdout.write(line)
            sys.stdout.flush()
    proc.wait()
    return "".join(chunks)


def run_suite(extra: list[str] | None = None,
              stream: bool = False) -> tuple[dict[str, str], int]:
    """Run pytest; return ({node-id: outcome} for everything that did not pass,
    total tests that ran).

    `stream=True` is strictly additive: the child is run line-buffered through
    _stream_child and its output is echoed live, with `-v` instead of `-q` so
    each finished test emits a node-id the reader can attribute. Everything
    after that — the parse loop, the caller's baseline diff, the GATE line, the
    exit code — is byte-identical to the default path.
    """
    cmd = [sys.executable, "-m", "pytest", "-v" if stream else "-q",
           "--no-header", "-rfEsX", *(extra or [])]
    # Color OFF in the child, whatever this shell exports (FORCE_COLOR wins
    # over piped output in pytest) — and strip escapes anyway below, because
    # the next color-forcing knob will not be one we have heard of.
    env = {k: v for k, v in os.environ.items()
           if k not in ("FORCE_COLOR", "CLICOLOR_FORCE")}
    env["NO_COLOR"] = "1"
    env["PY_COLORS"] = "0"
    if stream:
        # Python block-buffers stdout off a tty; without this the "live" mode
        # would deliver the whole run in one lump at the end.
        env["PYTHONUNBUFFERED"] = "1"
        output = _stream_child(cmd, env)
    else:
        proc = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True,
                              env=env)
        output = proc.stdout + proc.stderr
    results: dict[str, str] = {}
    total = 0
    for line in output.splitlines():
        line = _ANSI.sub("", line).strip()
        if m := _SKIPPED.match(line):
            results[f'{posix(m["file"])}: {m["reason"].strip()}'] = "SKIPPED"
        elif m := _FAILED.match(line):
            results[posix(m["nodeid"])] = m["outcome"]
        elif m := _SUBFAILED.match(line):
            key = posix(m["nodeid"]) + (m["params"] or "")
            results[key] = m["outcome"]
        elif counts := _TOTAL.findall(line):
            total = max(total, sum(int(n) for n in counts))
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
    stream = bool(getattr(args, "stream", False))

    if args.affected:
        selected, safety, note = affected_modules(args.base_ref)
        print(f"GATE INFO  --affected: {note}")
        if safety is None:
            # It could not narrow. REFUSE, rather than quietly running the
            # whole suite behind a flag whose entire promise is "only the
            # blast radius". A tool that silently does the expensive thing is
            # why the "don't re-run the suite" rule kept getting broken: the
            # agent asked for a narrow run, got a full one, and had no way to
            # tell. Exit non-zero and say what to do instead.
            print("GATE ABORT  --affected cannot narrow this diff.")
            print("  Run the specific test files you touched instead:")
            print("    py -m pytest tools/tests/test_<area>.py -x -q")
            print("  Or, if you are the MAIN SESSION at handoff and you "
                  "genuinely want the whole suite, ask for it explicitly:")
            print("    py tools/testgate.py check")
            return 2
        if not selected:
            # "no .py changed" — safety is the core tier, which IS a narrowing.
            results, total = run_suite(extra + safety, stream=stream)
        else:
            # Pass 1: the affected modules IN FULL — no marker filter, so an
            # `editor`-marked test in an affected file is not silently dropped.
            results, total = run_suite(extra + selected, stream=stream)
            # Pass 2: the core tier, as the insurance the docstring always
            # promised and the single-invocation form could never deliver.
            core_results, core_total = run_suite(extra + safety, stream=stream)
            results.update(core_results)
            # Tests in BOTH passes are counted twice here. The number is a
            # progress read-out, never a gate input — the verdict below keys on
            # node-ids (design rule 1), which de-duplicate correctly.
            total += core_total
    else:
        results, total = run_suite(extra, stream=stream)

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


def changed_py_files(base_ref: str) -> list[str]:
    """Every .py the working tree differs by — committed AND uncommitted.

    Committed-only (`git diff base...HEAD`) was the original bug and it was a
    silent one: on `Development` itself, or on any branch whose work is not
    committed yet, that range is EMPTY, `--affected` concluded it could not
    narrow, and ran the WHOLE suite while printing that it was being selective.
    Agents then paid a full-suite wall-clock on every iteration. `base_ref` is
    resolved through merge-base so a stale `Development` does not drag in
    everything that landed on it since you branched.
    """
    ranges = []
    # git() swallows failure and returns "" — an unknown base_ref simply means
    # no committed range, and the working-tree ranges below still apply.
    merge_base = git("merge-base", "HEAD", base_ref)
    if merge_base:
        ranges.append(git("diff", "--name-only", merge_base, "HEAD"))
    ranges.append(git("diff", "--name-only", "HEAD"))          # unstaged
    ranges.append(git("diff", "--name-only", "--cached"))      # staged
    ranges.append(git("ls-files", "--others", "--exclude-standard"))  # untracked

    out: set[str] = set()
    for blob in ranges:
        out.update(f.strip() for f in blob.splitlines() if f.strip().endswith(".py"))
    return sorted(out)


def affected_modules(base_ref: str) -> tuple[list[str], list[str], str]:
    """Changed files -> Graphify blast radius -> the test modules in it.

    Returns (affected test files, extra pytest args for the safety tier, note).
    The caller runs the affected files IN FULL and the core tier as a SECOND
    pass, then merges — see cmd_check. Two passes because the union cannot be
    expressed in one pytest invocation: naming files on the command line
    overrides `testpaths`, so the old `["-m", "core", *tests]` collected ONLY
    those files and then DESELECTED every non-core test inside them. It never
    ran the core tier it documented, and it silently skipped the `editor`-marked
    tests of the very files it had selected. Under-selection is the failure mode
    this module's four design rules exist to prevent, so the union is now real.

    Nothing here returns "run everything" except a change to the test
    scaffolding, which genuinely can break any module.
    """
    changed = changed_py_files(base_ref)
    if not changed:
        return [], ["-m", "core"], "no .py changes; core tier only"

    # A change to the test scaffolding itself invalidates any narrowing: it can
    # alter collection or fixtures for every module in the suite.
    if any(f in ("conftest.py", "pytest.ini") or f.startswith("tools/tests/qt_harness")
           for f in changed):
        return [], None, "test scaffolding changed; CANNOT NARROW"

    tests = {f for f in changed if f.startswith("tools/tests/")}
    sources = [f for f in changed if not f.startswith("tools/tests/")]

    unresolved: list[str] = []
    for src in sources:
        stem = Path(src).stem
        out = subprocess.run(["graphify", "affected", stem],
                             cwd=REPO, capture_output=True, text=True)
        if out.returncode != 0:
            # Graph stale or unavailable for THIS file. Previously that meant
            # the whole suite; now the core tier below carries the insurance and
            # we say out loud which file we could not resolve.
            unresolved.append(src)
            continue
        for line in out.stdout.splitlines():
            m = re.search(r"(tools/tests/test_\w+\.py)", line)
            if m:
                tests.add(m.group(1))

    selected = sorted(t for t in tests if (REPO / t).exists())
    note = f"{len(selected)} test module(s) + the core tier"
    if unresolved:
        note += f"; graph miss on {', '.join(unresolved)} (core tier covers it)"
    return selected, ["-m", "core"], note


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
    chk.add_argument("--stream", action="store_true",
                     help="echo pytest's output live (-v) while still printing "
                          "the same GATE verdict at the end; for the editor's "
                          "test panel")
    chk.add_argument("pytest_args", nargs="*", default=[])
    chk.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
