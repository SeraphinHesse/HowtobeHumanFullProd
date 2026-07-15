"""The pinned data/ snapshot every value-asserting test reads from.

``FIXTURE_DATA`` is a JSON-only mirror of the repo's ``data/`` tree, frozen at
a known-good moment. Tests import it instead of ``REPO / "data"`` so that a
designer editing live data can never turn the gate red — the exact doctrine
``TempDataCase.unassign_slot`` states for writes ("pin the fixture instead of
inheriting it"), applied to readers. ``planning/TestFixturePinningPLAN.md``
records the plan; ``test_fixture_guard.py`` enforces it.

Deliberately NOT in the snapshot:
- ``data/balancing_history/`` — a runtime-populated log, not seed content
  (TempDataCase deletes it from its copies for the same reason).
- Binary assets (PNG/WAV/MP4) — no pinned-value test reads them; tests that
  exercise the real asset tree live on the FP-4 allowlist instead.

The snapshot is a PIN, not an authority: live ``data/`` + schemas remain the
source of truth. Refreshing is deliberate, never automatic::

    py tools/tests/fixture_data.py --refresh

re-mirrors live JSON and prints every file it changed — run it only when a
schema/content migration requires it, then run the full suite.
"""
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
LIVE_DATA = REPO / "data"
FIXTURE_DATA = Path(__file__).resolve().parent / "fixtures" / "data"

#: live subtrees the snapshot skips (see module docstring).
EXCLUDED = ("balancing_history",)


def fixture_copy(dest: Path) -> Path:
    """Copy the snapshot to ``dest / "data"`` and return that path.

    For tests that WRITE through the data layer: point the writer at the
    copy, never at FIXTURE_DATA itself (the snapshot must stay byte-stable
    within a run). Editor tests keep using TempDataCase, which needs the
    real asset tree; this is the lightweight JSON-only equivalent.
    """
    dest_data = Path(dest) / "data"
    shutil.copytree(FIXTURE_DATA, dest_data)
    return dest_data


def _live_json():
    for p in sorted(LIVE_DATA.rglob("*.json")):
        rel = p.relative_to(LIVE_DATA)
        if rel.parts[0] in EXCLUDED:
            continue
        yield rel


def refresh():
    """Re-mirror live JSON into the snapshot; return the changed rel-paths."""
    changed = []
    wanted = set(_live_json())
    for rel in wanted:
        src, dst = LIVE_DATA / rel, FIXTURE_DATA / rel
        new = src.read_bytes()
        if not dst.exists() or dst.read_bytes() != new:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(new)
            changed.append(("update", rel))
    if FIXTURE_DATA.exists():
        for p in sorted(FIXTURE_DATA.rglob("*.json")):
            rel = p.relative_to(FIXTURE_DATA)
            if rel not in wanted:
                p.unlink()
                changed.append(("delete", rel))
    return changed


if __name__ == "__main__":
    import sys

    if "--refresh" not in sys.argv:
        sys.exit("usage: py tools/tests/fixture_data.py --refresh")
    for action, rel in refresh() or [("no-op", "snapshot already matches live data/")]:
        print(f"{action:7} {rel}")
    print("Now run the full suite: py tools/testgate.py check")
