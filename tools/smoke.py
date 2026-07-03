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


def validate_data():
    from engine import data_io

    schema_dir = REPO / "data" / "schemas"
    checked = 0
    for path in sorted((REPO / "data").rglob("*.json")):
        if schema_dir in path.parents:
            continue  # schemas validate data, not themselves
        schema = schema_dir / f"{path.stem}.schema.json"
        if not schema.exists():
            raise FileNotFoundError(f"{path.relative_to(REPO)} has no schema {schema.name}")
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
