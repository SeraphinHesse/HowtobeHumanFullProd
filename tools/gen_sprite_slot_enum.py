"""Regenerate core.schema.json's enemy_intro_entry sprite_slot/animation enums.

    py tools/gen_sprite_slot_enum.py [--data-dir PATH]

The enemy-intro dialogue's `sprite_slot` field references ANY slot across
EVERY category in data/slots.json (not just the `enemies` category), and its
`animation` field is a union of every category's animation vocabulary. Both
are schema enums, so a slot/animation added to slots.json needs the enum
regenerated -- this script is that regeneration, not a one-shot migration.
`tools/tests/test_schema_slot_sync.py` fails CI if someone forgets to re-run
it after touching slots.json.

Headless + deterministic + idempotent: reads the registry, rewrites the two
enums in place, and re-serializes the whole schema through
engine.data_io.dumps_deterministic (sorted keys, 2-space indent) -- running it
twice with no slots.json change produces a byte-identical file.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import data_io
from engine.assets.registry import load_registry


def compute_enums(data_dir):
    registry = load_registry(data_dir)
    slot_keys = sorted(registry.slot_keys())
    animations = set()
    for category in registry.categories():
        animations.update(category.animations)
    return slot_keys, sorted(animations)


def apply(schema_path, data_dir):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    entry = schema["$defs"]["enemy_intro_entry"]
    slot_keys, animations = compute_enums(data_dir)
    entry["properties"]["sprite_slot"]["enum"] = slot_keys
    entry["properties"]["animation"]["enum"] = animations
    schema_path.write_text(data_io.dumps_deterministic(schema), encoding="utf-8")
    return len(slot_keys), len(animations)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO / "data")
    args = parser.parse_args(argv)

    schema_path = args.data_dir / "schemas" / "core.schema.json"
    num_slots, num_animations = apply(schema_path, args.data_dir)
    print(f"sprite_slot: {num_slots} slots, animation: {num_animations} names "
          f"-> {schema_path}")


if __name__ == "__main__":
    main()
