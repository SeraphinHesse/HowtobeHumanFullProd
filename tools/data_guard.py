"""Guard: running the tests must never modify the repo's data/.

Why this exists. Before TestGatePLAN TG-1, a full `unittest discover` run
CORRUPTED the repo: it painted two deco_rock tiles into
data/maps/summertest2.json, created a whole new data/maps/uitestexample.json,
and appended `ui_button_v2` to data/slots.json. Nobody noticed, because nothing
was watching — and the damage was self-concealing: the extra `ui_button_v2`
made test_ui_skin_variant compute `ui_button_v3`, so the test failed for a
reason that looked like a code bug and was actually the suite eating its own
fixture. Every subsequent run ratcheted the number again.

The tests all copy data/ into a tempdir precisely so this cannot happen. The
leak was the loophole: widgets that outlived their test (see
tools/tests/qt_harness.py) kept firing after their tempdir was gone.

So: this is the tripwire. Cheap, boring, and it fails loudly.

    py tools/data_guard.py snapshot > before.json
    <run the suite>
    py tools/data_guard.py verify before.json
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"


def snapshot(data_dir: Path = DATA) -> dict[str, str]:
    """sha256 of every file under data/, keyed by repo-relative posix path.

    Hashes CONTENT, not mtime: a test that rewrites a file byte-identically is
    not corruption, and we don't want to cry wolf about it.
    """
    out: dict[str, str] = {}
    for path in sorted(data_dir.rglob("*")):
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            out[path.relative_to(data_dir).as_posix()] = digest
    return out


def diff(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Human-readable list of what the suite did to data/. Empty == clean."""
    problems = []
    for name in sorted(set(after) - set(before)):
        problems.append(f"CREATED  data/{name}")
    for name in sorted(set(before) - set(after)):
        problems.append(f"DELETED  data/{name}")
    for name in sorted(set(before) & set(after)):
        if before[name] != after[name]:
            problems.append(f"MODIFIED data/{name}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) >= 1 and argv[0] == "snapshot":
        json.dump(snapshot(), sys.stdout, indent=2, sort_keys=True)
        return 0
    if len(argv) == 2 and argv[0] == "verify":
        before = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        problems = diff(before, snapshot())
        if not problems:
            print(f"DATA CLEAN  {len(before)} file(s) untouched by the suite")
            return 0
        print(f"DATA DIRTY  the test suite modified {len(problems)} file(s):")
        for line in problems:
            print(f"  {line}")
        print("\nA test wrote into the repo instead of its tempdir copy.")
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
