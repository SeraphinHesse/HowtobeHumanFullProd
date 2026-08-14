"""Regenerate the schema enums that mirror data/slots.json.

    py tools/gen_sprite_slot_enum.py [--data-dir PATH]

TWO schemas carry a generated slot enum:

* core.schema.json's `enemy_intro_entry`. Its `sprite_slot` field references
  ANY slot across EVERY category in data/slots.json (not just the `enemies`
  category), and its `animation` field is a union of every category's
  animation vocabulary.
* vfx.schema.json's `trigger_row.sprite_slot` (VfxAuthoringPLAN D2). It
  references the `vfx` category only, plus "" for "no sprite -- run the
  procedural fallback". It was hand-typed until VA-1 and had already drifted
  to six keys against thirteen real slots, which fails in the direction that
  matters: a valid binding rejected, or a dangling one accepted. Add, remove
  and rename (VA-6) each break a hand-typed list silently.

`trigger_row.procedural` is deliberately NOT generated. Its values name
game-code kinds -- `game/ui/effects.py::_run_procedural`'s if/elif ladder --
not `procedural.*` balancing keys: `spark_place`/`spark_level`/`spark_tier`
are spark PRESETS with no key of their own, and several `procedural.*` blocks
(floaters, projectile, drummer_aura, ...) are not one-shot kinds at all.
Generating it from the balancing doc would rewrite it into something the
shipped trigger rows fail against. The event/kind vocabulary is code-owned
(D9); the slot list is data.

`tools/tests/test_schema_slot_sync.py` fails CI if someone forgets to re-run
this after touching slots.json.

Headless + deterministic + idempotent: reads the registry, rewrites the enums
in place, and re-serializes each schema through
engine.data_io.dumps_deterministic (sorted keys, 2-space indent) -- running it
twice with no slots.json change produces byte-identical files.
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


def compute_vfx_slot_enum(data_dir):
    """vfx.schema.json's trigger_row.sprite_slot enum: "" (no sprite -- run
    the procedural fallback) followed by every `vfx` category slot key,
    sorted. Sorted rather than document order so a reordered slots.json
    group does not churn the schema."""
    registry = load_registry(data_dir)
    return [""] + sorted(registry.group_slots("vfx"))


def apply(schema_path, data_dir):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    entry = schema["$defs"]["enemy_intro_entry"]
    slot_keys, animations = compute_enums(data_dir)
    entry["properties"]["sprite_slot"]["enum"] = slot_keys
    entry["properties"]["animation"]["enum"] = animations
    schema_path.write_text(data_io.dumps_deterministic(schema), encoding="utf-8")
    return len(slot_keys), len(animations)


def apply_vfx(schema_path, data_dir):
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    slot_enum = compute_vfx_slot_enum(data_dir)
    schema["$defs"]["trigger_row"]["properties"]["sprite_slot"]["enum"] = slot_enum
    schema_path.write_text(data_io.dumps_deterministic(schema), encoding="utf-8")
    return len(slot_enum)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO / "data")
    args = parser.parse_args(argv)

    schema_path = args.data_dir / "schemas" / "core.schema.json"
    num_slots, num_animations = apply(schema_path, args.data_dir)
    print(f"sprite_slot: {num_slots} slots, animation: {num_animations} names "
          f"-> {schema_path}")

    vfx_path = args.data_dir / "schemas" / "vfx.schema.json"
    num_vfx = apply_vfx(vfx_path, args.data_dir)
    print(f"trigger_row.sprite_slot: {num_vfx} values -> {vfx_path}")


if __name__ == "__main__":
    main()
