"""Schema-validating JSON load/write for data/ (D-2, D-3).

The single code path for reading and writing data/ files: every load and
every write validates against a schema from data/schemas/ and fails loud
(jsonschema.ValidationError) on mismatch. Writes are deterministic —
sorted keys, 2-space indent, trailing newline — so diffs stay minimal.

Pure Python: no pygame here, ever.
"""
import json
from pathlib import Path

import jsonschema


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_validated(data_path, schema_path):
    """Load a data JSON file and validate it against its schema (fail loud)."""
    data = load_json(data_path)
    jsonschema.validate(data, load_json(schema_path))
    return data


def dumps_deterministic(data):
    """D-3 canonical form: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_validated(data, data_path, schema_path):
    """Validate against the schema, then write in canonical form.

    Validation errors raise before anything touches disk.
    """
    jsonschema.validate(data, load_json(schema_path))
    Path(data_path).write_text(dumps_deterministic(data), encoding="utf-8")
