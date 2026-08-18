"""Stamp the canonical sound `$defs` into every balancing schema that has slots.

    py tools/gen_sound_slot_defs.py [--data-dir PATH]

FIVE schemas carry a sound slot: buildings, core, enemies, map, ui. They all
need the SAME two definitions -- `sound_clip` and `sound_slot` -- and JSON
Schema would express that with one shared file and a cross-file `$ref`. The
house style forbids exactly that (data/CLAUDE.md: local `#/$defs/` refs only,
never cross-file; `balancing/ui.json`'s Keybindings re-declares
keybindings.schema.json's property set by hand for the same reason). So the
block is DUPLICATED into all five schemas, and the duplication is made safe
the way the sprite-slot enums are: one generator owns the literal text, and
`tools/tests/test_sound_slots_data.py` fails CI if a committed schema drifts
from it.

The generator writes `$defs` ONLY. The `Sounds`/`sounds` subtrees, the slot
sites that `$ref` these defs, the `required` lists and the balancing documents
are hand-authored one-time structure, not a derived list.

`x-widget: "sound_slot"` lives INSIDE `$defs/sound_slot`, never beside a
`$ref`. editor/panels/balancing.py derefs a property BEFORE reading any `x-`
extension, replacing the node wholesale, so a sibling marker is silently
dropped and the composite widget never fires.

Headless + deterministic + idempotent: reads each schema, replaces the two
defs, re-serializes through engine.data_io.dumps_deterministic (sorted keys,
2-space indent) -- running it twice produces byte-identical files.
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from engine import data_io

#: The domains whose schemas carry sound slots.
DOMAINS = ("buildings", "core", "enemies", "map", "ui")

#: One entry in a slot's playlist. `end: 0.0` is the play-to-the-end SENTINEL
#: -- deliberately not null, because a type-less / union node crashes the
#: editor's balancing panel for the whole domain (data/CLAUDE.md).
SOUND_CLIP_DEF = {
    "type": "object",
    "additionalProperties": False,
    "description": (
        "One audio clip in a sound slot's playlist: a file plus its volume "
        "and trim window."
    ),
    "properties": {
        "file": {
            "type": "string",
            "description": (
                "Path relative to data/audio/ (e.g. "
                "'imported/building_death_a.ogg'). Empty string = no clip."
            ),
        },
        "volume": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
            "description": (
                "Clip gain as a fraction 0..1, multiplied by the bus volume "
                "and the master volume."
            ),
        },
        "start": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 3600.0,
            "description": (
                "Trim in-point in seconds; 0.0 plays from the beginning. "
                "Bounded at 3600 s (one hour), a deliberate approved "
                "deviation from the 0-60 s convention, which was written for "
                "VFX timings -- music tracks run minutes."
            ),
        },
        "end": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 3600.0,
            "description": (
                "Trim out-point in seconds. 0.0 is the SENTINEL for 'play to "
                "the end of the file' (never null -- a nullable/union node "
                "breaks the balancing panel). Bounded at 3600 s for the same "
                "reason as start."
            ),
        },
    },
    "required": ["end", "file", "start", "volume"],
}

#: One named sound event. `clips: []` on a GLOBAL default means silence; the
#: same empty list on an ELEMENT override means "inherit the default".
SOUND_SLOT_DEF = {
    "type": "object",
    "additionalProperties": False,
    "x-widget": "sound_slot",
    "description": (
        "A sound event: zero or more clips plus how to play them. Empty "
        "clips on a global default means silence; empty clips on a "
        "per-element override means inherit the global default."
    ),
    "properties": {
        "clips": {
            "type": "array",
            "minItems": 0,
            "description": (
                "The clips this event may play. Empty on a global default = "
                "silence; empty on a per-element override = inherit the "
                "global default."
            ),
            "items": {"$ref": "#/$defs/sound_clip"},
        },
        "loop": {
            "type": "boolean",
            "description": (
                "Repeat the chosen clip until stopped (music and ambience) "
                "rather than playing it once."
            ),
        },
        "pick": {
            "type": "string",
            "enum": ["random", "sequential"],
            "description": (
                "How the next clip is chosen when the slot holds more than "
                "one: 'random' picks any, 'sequential' cycles in order."
            ),
        },
    },
    "required": ["clips", "loop", "pick"],
}


def sound_slot_defs():
    """The two canonical `$defs`, as a fresh dict (callers may mutate)."""
    return json.loads(json.dumps({
        "sound_clip": SOUND_CLIP_DEF,
        "sound_slot": SOUND_SLOT_DEF,
    }))


def slot_site(description):
    """A slot reference site: `$ref` plus a human-facing description.

    The description documents the schema for a reader; the editor derefs the
    node and shows `$defs/sound_slot`'s own description instead.
    """
    return {"$ref": "#/$defs/sound_slot", "description": description}


def apply(schema_path):
    """Replace (or create) the two sound `$defs` in one schema."""
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    defs = schema.setdefault("$defs", {})  # ui/map have no $defs at all
    defs.update(sound_slot_defs())
    Path(schema_path).write_text(
        data_io.dumps_deterministic(schema), encoding="utf-8")
    return len(defs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=REPO / "data")
    args = parser.parse_args(argv)

    for domain in DOMAINS:
        schema_path = args.data_dir / "schemas" / f"{domain}.schema.json"
        total = apply(schema_path)
        print(f"sound_clip + sound_slot -> {schema_path} ({total} defs)")


if __name__ == "__main__":
    main()
