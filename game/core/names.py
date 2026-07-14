"""Runtime append of a building nameplate name (Phase 9H add-name menu).

The ONE runtime data write in the game (prototype ``balancing.add_random_name``):
the add-name shell screen types a name, this appends it to
``data/balancing/buildings.json`` -> ``BuildingsGlobal.random_names`` through the
validating writer, so it survives relaunch and stays schema-canonical. Pure
Python (no pygame); disk I/O lives HERE, out of the pygame-pure ``game/ui``.
"""
from pathlib import Path

from engine import data_io


def _buildings_paths(data_dir):
    data_dir = Path(data_dir)
    return (data_dir / "balancing" / "buildings.json",
            data_dir / "schemas" / "buildings.schema.json")


def append_random_name(data_dir, name):
    """Append ``name`` to the building random-name pool, persisting to disk.

    Returns ``True`` if the name was added, ``False`` if it was blank or already
    in the pool (prototype ``add_random_name`` semantics). Surrounding whitespace
    is trimmed; the write goes through ``write_validated`` so every other key
    survives and the file stays schema-canonical (D-3).
    """
    name = name.strip()
    if not name:
        return False
    data_path, schema_path = _buildings_paths(data_dir)
    doc = data_io.load_validated(data_path, schema_path)
    names = doc["BuildingsGlobal"]["random_names"]
    if name in names:
        return False
    names.append(name)
    data_io.write_validated(doc, data_path, schema_path)
    return True
