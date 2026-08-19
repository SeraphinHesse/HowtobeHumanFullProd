"""Schema-validating JSON load/write for data/ (D-2, D-3).

The single code path for reading and writing data/ files: every load and
every write validates against a schema from data/schemas/ and fails loud
(jsonschema.ValidationError) on mismatch. Writes are deterministic —
sorted keys, 2-space indent, trailing newline — so diffs stay minimal.

Pure Python: no pygame here, ever.
"""
import json
import os
from pathlib import Path

import jsonschema
from jsonschema.exceptions import best_match


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


#: (schema path, mtime_ns, size) -> compiled validator.
#:
#: `jsonschema.validate(data, load_json(schema_path))` re-read the schema from
#: disk AND re-ran check_schema against the draft metaschema on EVERY call. The
#: schemas are big (enemies 76 KB, buildings 73 KB, core 36 KB) and this sits
#: on the critical path of everything: one MainWindow.__init__ builds 17 panels
#: and makes ~10 load_registry calls, the editor test tier builds ~450 of them,
#: and the same constant taxes smoke.py and real game boot.
#:
#: Keyed by (mtime_ns, size), never by path alone. Several tests write a schema
#: and immediately re-validate against it; a path-keyed cache would serve them
#: the pre-edit schema and pass a test that should fail. Cheap to check — one
#: stat() per validation, against a parse + metaschema check.
_VALIDATORS = {}


def _validator_for(schema_path):
    """The compiled validator for a schema, built at most once per version."""
    stat = os.stat(schema_path)
    key = (str(schema_path), stat.st_mtime_ns, stat.st_size)
    validator = _VALIDATORS.get(key)
    if validator is None:
        schema = load_json(schema_path)
        cls = jsonschema.validators.validator_for(schema)
        # Once per schema version, not once per call — this is the expensive
        # half. A malformed schema must still fail loud, so it is not skipped.
        cls.check_schema(schema)
        validator = cls(schema)
        _VALIDATORS[key] = validator
    return validator


def validate(data, schema_path):
    """Validate `data` against the schema at `schema_path` (fail loud).

    Raises the SAME error jsonschema.validate() would. That is the whole
    reason for best_match(iter_errors(...)) rather than validator.validate():
    validate() raises the FIRST error it happens to hit, while the module-level
    jsonschema.validate() raises best_match(...) — the most relevant one. Every
    existing assertRaises(ValidationError) site keeps its exact message.
    """
    error = best_match(_validator_for(schema_path).iter_errors(data))
    if error is not None:
        raise error


def load_validated(data_path, schema_path):
    """Load a data JSON file and validate it against its schema (fail loud)."""
    data = load_json(data_path)
    validate(data, schema_path)
    return data


def dumps_deterministic(data):
    """D-3 canonical form: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_validated(data, data_path, schema_path):
    """Validate against the schema, then write in canonical form, atomically.

    Validation errors raise before anything touches disk.

    The write goes to a sibling `.tmp` and is then os.replace()d into place.
    Path.write_text() truncates the target before it streams, so an interrupt,
    a full disk, or a OneDrive sync lock mid-write would leave a zero-length or
    half-written file where good content used to be — irreversible, and this is
    the single writer behind every editor save, every agent write, keybindings
    and highscores. os.replace() is atomic on POSIX and on Windows, so a reader
    sees either the old file or the new one, never a partial one.
    """
    validate(data, schema_path)
    data_path = Path(data_path)
    tmp_path = data_path.with_name(data_path.name + ".tmp")
    try:
        tmp_path.write_text(dumps_deterministic(data), encoding="utf-8")
        os.replace(tmp_path, data_path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
