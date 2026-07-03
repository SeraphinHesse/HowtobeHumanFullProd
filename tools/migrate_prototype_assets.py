"""E-38 one-off migration: prototype sprite manifest (v1) + imported sheets
→ manifest v2 (D-30) + PNGs copied to data/sprites/imported/ (D-31).

    py tools/migrate_prototype_assets.py [--src <prototype repo>] [--dst <data dir>]

Reads <src>/assets/sprites/sprite_manifest.json and its imported/ PNGs
(the prototype repo is READ-ONLY); writes <dst>/sprites/asset_manifest.json
through the validating writer and copies each entry's sheet. Entries whose
PNG is missing are skipped with a warning. Re-running is idempotent
(overwrites with identical output).
"""
import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import data_io  # noqa: E402

DEFAULT_SRC = REPO.parent / "HowToBeHuman" / "ClaudePrototype" / "HowToBeHuman"
DEFAULT_DST = REPO / "data"


def migrate_row(row):
    """v1 row → fully-specified v2 row (fps 8, hidden [], loop 0/0/1 defaults)."""
    return {
        "animation": str(row.get("animation", "idle")),
        "frames": int(row["frames"]),
        "fps": row.get("fps", 8) or 8,
        "hidden": sorted(int(i) for i in row.get("hidden", [])),
        "loop_start": int(row.get("loop_start", 0)),
        "loop_end": int(row.get("loop_end", 0)),
        "loop_count": max(1, int(row.get("loop_count", 1))),
    }


def migrate_manifest(v1):
    """Pure v1 doc → v2 doc. Per-entry frame size defaults come from the v1
    top-level globals; offsets default to 0; sheet paths are normalized to
    the D-31 invariant imported/<slot>.png."""
    global_w = int(v1.get("frame_w", 64))
    global_h = int(v1.get("frame_h", 96))
    entries = {}
    for slot_key, entry in v1.get("entries", {}).items():
        entries[slot_key] = {
            "sheet": f"imported/{slot_key}.png",
            "frame_w": int(entry.get("frame_w", global_w)),
            "frame_h": int(entry.get("frame_h", global_h)),
            "offset_x": int(entry.get("offset_x", 0)),
            "offset_y": int(entry.get("offset_y", 0)),
            "rows": [migrate_row(r) for r in entry.get("rows", [])],
        }
    return {"version": 2, "entries": entries}


def run(src, dst_data):
    """Migrate + copy. Returns the list of migrated slot keys."""
    src, dst_data = Path(src), Path(dst_data)
    v1 = data_io.load_json(src / "assets" / "sprites" / "sprite_manifest.json")
    v2 = migrate_manifest(v1)

    copied = []
    for slot_key in list(v2["entries"]):
        src_png = src / "assets" / "sprites" / "imported" / f"{slot_key}.png"
        if not src_png.exists():
            print(f"warning: {slot_key}: {src_png.name} not found — entry skipped")
            del v2["entries"][slot_key]
            continue
        dst_png = dst_data / "sprites" / "imported" / f"{slot_key}.png"
        dst_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src_png, dst_png)
        copied.append(slot_key)

    data_io.write_validated(
        v2,
        dst_data / "sprites" / "asset_manifest.json",
        dst_data / "schemas" / "asset_manifest.schema.json",
    )
    print(f"migrated {len(copied)} entries -> {dst_data / 'sprites'}")
    return copied


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC,
                        help="prototype repo root (read-only)")
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST,
                        help="target data/ directory")
    args = parser.parse_args(argv)
    run(args.src, args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
