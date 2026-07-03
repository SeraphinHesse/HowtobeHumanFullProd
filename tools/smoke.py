"""Headless smoke test (T-2 minimal, G-8) — the universal exit gate.

    py tools/smoke.py

1. SDL dummy drivers (no window, CI-safe).
2. Validate every data/**/*.json against data/schemas/<name>.schema.json
   (naming convention; a data file without a schema fails loud, D-2).
3. Construct and run the game headlessly for a few frames.
4. Print OK. Any failure: traceback + non-zero exit.
"""
import os
import sys
import traceback
from pathlib import Path

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

FRAMES = 5


def validate_data(data_root=None):
    """Stem-pairing rule (data/foo.json ↔ schemas/foo.schema.json) with ONE
    directory exception: every data/maps/*.json EXCEPT active_map.json is a
    D-20 map file with an arbitrary stem and validates against
    map_file.schema.json (the stem 'map' belongs to the balancing domain).
    data_root parameter exists so tests can run this rule on a temp tree."""
    from engine import data_io

    data_root = Path(data_root) if data_root is not None else REPO / "data"
    schema_dir = data_root / "schemas"
    maps_dir = data_root / "maps"
    checked = 0
    for path in sorted(data_root.rglob("*.json")):
        if schema_dir in path.parents:
            continue  # schemas validate data, not themselves
        if maps_dir in path.parents and path.name != "active_map.json":
            schema = schema_dir / "map_file.schema.json"
        else:
            schema = schema_dir / f"{path.stem}.schema.json"
        if not schema.exists():
            raise FileNotFoundError(
                f"{path.relative_to(data_root.parent)} has no schema {schema.name}")
        data_io.load_validated(path, schema)
        checked += 1
    print(f"smoke: {checked} data file(s) schema-valid")
    return checked


def main():
    try:
        validate_data()
        from game.main import main as game_main

        frames = game_main(max_frames=FRAMES)
        print(f"smoke: game ran {frames} headless frame(s)")
    except Exception:
        traceback.print_exc()
        print("smoke: FAILED")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
