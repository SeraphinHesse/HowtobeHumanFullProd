"""E-38 one-off migration: prototype sprite manifest (v1) + imported sheets
→ manifest v2 (D-30) + PNGs copied to data/sprites/imported/ (D-31). ALSO
migrates the 9 map tile slots (D-20), which the prototype never stored in
its v1 manifest at all — it generated them procedurally in
src/core/sprite_gen.py from 7 raw PNGs under assets/sprites/ (not
assets/sprites/imported/). This is baked to static PNGs here (D-1/D-2: no
runtime art generation in this codebase).

    py tools/migrate_prototype_assets.py [--src <prototype repo>] [--dst <data dir>]

Reads <src>/assets/sprites/sprite_manifest.json + its imported/ PNGs, and
<src>/assets/sprites/tile_*.png (the prototype repo is READ-ONLY); writes
<dst>/sprites/asset_manifest.json through the validating writer and copies/
generates each entry's sheet. Entity entries whose PNG is missing are
skipped with a warning. Re-running is idempotent (overwrites with identical
output).
"""
import argparse
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import data_io  # noqa: E402
from editor.asset_import import import_idle_sheet  # noqa: E402

DEFAULT_SRC = REPO.parent / "HowToBeHuman" / "ClaudePrototype" / "HowToBeHuman"
DEFAULT_DST = REPO / "data"

# src/map/tile.py's _sprite_key: direct file -> slot mapping for the 7 raw
# tile PNGs (assets/sprites/, NOT imported/ — never went through the v1
# manifest). tile_combat[_b] have no source file (see migrate_tiles).
TILE_FILE_SLOTS = {
    "tile_grass.png": "tile_buildable",
    "tile_grass_b.png": "tile_buildable_b",
    "tile_earth.png": "tile_spawning",
    "tile_earth_b.png": "tile_spawning_b",
    "tile_bg_forest.png": "tile_forest",
    "tile_bg_ocean.png": "tile_ocean",
    "tile_bg_cliff.png": "tile_cliff",
}
# src/core/constants.py C_COMBAT_TINT: multiply tint for the derived combat
# tiles (sprite_gen.py's _combat_tile_png: grayscale then BLEND_RGBA_MULT).
COMBAT_TINT = (95, 150, 50)


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
        # Resolve the source PNG from the v1 entry's own sheet path (relative
        # to assets/sprites/) — the prototype filed many sheets under
        # imported/{buildings,enemies/*,hole}/ subfolders, so a flat
        # imported/<slot>.png guess misses ~90 of them. Dst still flattens to
        # imported/<slot>.png (D-31 invariant).
        v1_sheet = v1["entries"][slot_key].get("sheet", f"imported/{slot_key}.png")
        src_png = src / "assets" / "sprites" / Path(v1_sheet)
        if not src_png.exists():
            print(f"warning: {slot_key}: {v1_sheet} not found — entry skipped")
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


def _combat_tint(src_png, dst_png):
    """Reproduce sprite_gen.py's _combat_tile_png with Pillow: grayscale
    (alpha preserved) then multiply-tint by COMBAT_TINT — pygame's
    BLEND_RGBA_MULT equivalent is Image.multiply on an RGB tint layer of
    the same size, alpha channel carried through untouched."""
    from PIL import Image, ImageChops, ImageOps

    with Image.open(src_png) as source:
        source = source.convert("RGBA")
        r, g, b, a = source.split()
        grey = ImageOps.grayscale(Image.merge("RGB", (r, g, b)))
        grey_rgb = Image.merge("RGB", (grey, grey, grey))
        tint_layer = Image.new("RGB", source.size, COMBAT_TINT)
        tinted = ImageChops.multiply(grey_rgb, tint_layer)
        tr, tg, tb = tinted.split()
        Image.merge("RGBA", (tr, tg, tb, a)).save(dst_png)


def migrate_tiles(src, dst_data):
    """Bake the prototype's 9 map tile slots to static PNGs + manifest v2
    entries (D-20) — 7 are direct file copies (TILE_FILE_SLOTS), 2
    (tile_combat[_b]) are generated once via _combat_tint since the
    prototype only ever tinted them at runtime. Returns the list of
    migrated slot keys."""
    from engine.assets import load_registry

    src, dst_data = Path(src), Path(dst_data)
    registry = load_registry(dst_data)
    migrated = []

    for filename, slot_key in TILE_FILE_SLOTS.items():
        src_png = src / "assets" / "sprites" / filename
        if not src_png.exists():
            print(f"warning: {slot_key}: {filename} not found — entry skipped")
            continue
        import_idle_sheet(dst_data, registry, slot_key, src_png)
        migrated.append(slot_key)

    with tempfile.TemporaryDirectory() as tmp:
        for base_filename, combat_slot in (
            ("tile_grass.png", "tile_combat"),
            ("tile_grass_b.png", "tile_combat_b"),
        ):
            src_png = src / "assets" / "sprites" / base_filename
            if not src_png.exists():
                print(f"warning: {combat_slot}: {base_filename} not found "
                      "— entry skipped")
                continue
            tmp_png = Path(tmp) / f"{combat_slot}.png"
            _combat_tint(src_png, tmp_png)
            import_idle_sheet(dst_data, registry, combat_slot, tmp_png)
            migrated.append(combat_slot)

    print(f"migrated {len(migrated)} tile entries -> {dst_data / 'sprites'}")
    return migrated


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", type=Path, default=DEFAULT_SRC,
                        help="prototype repo root (read-only)")
    parser.add_argument("--dst", type=Path, default=DEFAULT_DST,
                        help="target data/ directory")
    args = parser.parse_args(argv)
    run(args.src, args.dst)
    migrate_tiles(args.src, args.dst)
    return 0


if __name__ == "__main__":
    sys.exit(main())
