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
    """Stem-pairing rule (data/foo.json ↔ schemas/foo.schema.json) with FOUR
    directory exceptions: every data/maps/*.json EXCEPT active_map.json is a
    D-20 map file with an arbitrary stem and validates against
    map_file.schema.json (the stem 'map' belongs to the balancing domain);
    every data/balancing_history/*.json is named after its domain (colliding
    with that domain's own schema stem) and validates against
    balancing_history.schema.json instead; every data/agent_forms/*.json is an
    agent-dispatch form spec with an arbitrary stem and validates against
    agent_form.schema.json; every data/ui/screens/*.json is a per-screen
    override with an arbitrary stem (the screen id) and validates against
    ui_screen.schema.json, the exact parallel to map_file.schema.json for
    maps/*.json (the generated data/ui/screen_defaults.json snapshot pairs
    normally by stem to screen_defaults.schema.json).
    data_root parameter exists so tests can run this rule on a temp tree."""
    from engine import data_io

    data_root = Path(data_root) if data_root is not None else REPO / "data"
    schema_dir = data_root / "schemas"
    maps_dir = data_root / "maps"
    history_dir = data_root / "balancing_history"
    forms_dir = data_root / "agent_forms"
    screens_dir = data_root / "ui" / "screens"
    checked = 0
    for path in sorted(data_root.rglob("*.json")):
        if schema_dir in path.parents:
            continue  # schemas validate data, not themselves
        if maps_dir in path.parents and path.name != "active_map.json":
            schema = schema_dir / "map_file.schema.json"
        elif history_dir in path.parents:
            schema = schema_dir / "balancing_history.schema.json"
        elif forms_dir in path.parents:
            schema = schema_dir / "agent_form.schema.json"
        elif screens_dir in path.parents:
            schema = schema_dir / "ui_screen.schema.json"
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

        # autostart -> straight into GAMEPLAY so the sim/combat/payday path and
        # the full _World/Session construction are exercised (the 9H shell would
        # otherwise defer them until START NEW GAME).
        frames = game_main(max_frames=FRAMES, autostart=True)
        print(f"smoke: game ran {frames} headless gameplay frame(s)")
        # also boot the default shell path (cutscene/menu, no world) once.
        game_main(max_frames=2)
        print("smoke: shell boot OK")
    except Exception:
        traceback.print_exc()
        print("smoke: FAILED")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
