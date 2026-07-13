"""Slot-registry edits the editor makes to data/slots.json (the LevelBar
"+ Variant" button). Pure — engine.data_io only, no Qt/pygame — so it writes
through the validating writer exactly like an agent would, and stays in
`test_editor_viewport.TestPurity`.

A "variant" is one more interchangeable sprite slot inside a leaf subgroup —
an enemy era (Walker/Era 2, …) or a deco prop TYPE (Props/Rock, …). For enemies
the game already rolls a random variant per spawn across ALL of an era's slots
(`game/enemies/enemy.py:variant_slot`); for deco the map painter arms one
variant explicitly and the map file stores that concrete slot. Either way
adding a slot here needs no game change — only art imported onto it.

Background tiles have no variant dimension: one legend code per slot, so
"another background variant" IS "another background type"
(`add_background_slot`).
"""
import re
from pathlib import Path

from engine import data_io

_TRAILING_VARIANT = re.compile(r"^(?P<stem>.+)_v(?P<n>\d+)$")


def _slot_key(entry):
    """A slots[] entry is a bare key string, or {key, frame_w, frame_h} (a
    per-slot frame-size override). Kept local: this module stays pure
    engine.data_io, with no engine.assets coupling."""
    return entry if isinstance(entry, str) else entry["key"]


def _stem(slot_key):
    """slot_key with a trailing ``_v<N>`` stripped — the base name a family of
    variants shares (``enemy_stage_1_v2`` -> ``enemy_stage_1``; a slot with no
    ``_v`` suffix is its own stem)."""
    match = _TRAILING_VARIANT.match(slot_key)
    return match.group("stem") if match else slot_key


def next_variant_key(existing_slots, taken):
    """Lowest ``<stem>_v<k>`` (k >= 2) that collides with neither the era's
    ``existing_slots`` (bare keys or override objects) nor any ``taken`` key
    elsewhere in the registry. The stem comes from the era's first slot; a bare
    (suffix-less) slot is treated as v1, so the first added variant is ``_v2``."""
    keys = [_slot_key(s) for s in existing_slots]
    stem = _stem(keys[0])
    blocked = set(keys) | set(taken)
    k = 2
    while f"{stem}_v{k}" in blocked:
        k += 1
    return f"{stem}_v{k}"


def _all_slots(doc):
    out = set()

    def walk(node):
        out.update(_slot_key(s) for s in node.get("slots", ()))
        for child in node.get("children", ()):
            walk(child)

    for category in doc["categories"]:
        for group in category["groups"]:
            walk(group)
    return out


def _find_group(groups, path):
    nodes = groups
    node = None
    for label in path:
        node = next((n for n in nodes if n["label"] == label), None)
        if node is None:
            raise KeyError(f"no group at path segment {label!r}")
        nodes = node.get("children", ())
    if node is None:
        raise KeyError("empty group path")
    return node


def add_variant(data_dir, category_key, group_path, subcat_label):
    """Append a fresh variant slot to one era subgroup of data/slots.json and
    return the new slot key.

    ``group_path`` is the label path to the era's PARENT group (e.g.
    ``("Walker",)``); ``subcat_label`` is the era child's label (``"Era 2"``).
    The write goes through the schema-validating writer (D-2). Raises
    ``KeyError`` when the path/era doesn't resolve or the era is not a leaf
    (``slots``) subgroup.
    """
    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    schema_path = data_dir / "schemas" / "slots.schema.json"
    doc = data_io.load_json(slots_path)

    category = next(
        (c for c in doc["categories"] if c["key"] == category_key), None)
    if category is None:
        raise KeyError(f"no category {category_key!r}")
    group = _find_group(category["groups"], group_path)
    child = next(
        (c for c in group.get("children", ()) if c["label"] == subcat_label),
        None)
    if child is None:
        raise KeyError(f"no subgroup {subcat_label!r} under {group_path}")
    if "slots" not in child:
        raise KeyError(f"{subcat_label!r} has no slots list to extend")

    new_key = next_variant_key(child["slots"], _all_slots(doc))
    child["slots"].append(new_key)
    data_io.write_validated(doc, slots_path, schema_path)
    return new_key


def add_deco_variant(data_dir, type_label):
    """Append a fresh variant slot to one deco prop TYPE (``Props`` → ``Rock``)
    and return the new slot key (``deco_rock_v2``, …)."""
    return add_variant(data_dir, "deco", ("Props",), type_label)


# -- new background types + deco props (the palette's '+ Level' / '+ Add Prop'
# buttons) — same validating-write pattern as add_variant --------------------

def _next_numbered_suffix(prefix, taken):
    """Lowest ``k`` (k >= 1) for which ``<prefix><k>`` is not already used
    anywhere in the registry."""
    k = 1
    while f"{prefix}{k}" in taken:
        k += 1
    return k


def _next_numbered_key(prefix, taken):
    """Lowest ``<prefix><k>`` (k >= 1) not already used anywhere in the
    registry."""
    return f"{prefix}{_next_numbered_suffix(prefix, taken)}"


def _append_slot(data_dir, category_key, group_path, prefix):
    """Append a fresh numbered slot to a leaf ``slots`` group of a category and
    return the new key. ``group_path`` is the label path to that leaf group
    (e.g. ``("Tiles", "Background")`` — a nested subgroup, exactly like
    ``add_variant`` walks an era). Raises ``KeyError`` if the category/path is
    missing or the target isn't a leaf (``slots``) group."""
    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    schema_path = data_dir / "schemas" / "slots.schema.json"
    doc = data_io.load_json(slots_path)

    category = next(
        (c for c in doc["categories"] if c["key"] == category_key), None)
    if category is None:
        raise KeyError(f"no category {category_key!r}")
    group = _find_group(category["groups"], group_path)
    if "slots" not in group:
        raise KeyError(f"group {group_path!r} has no slots list to extend")

    new_key = _next_numbered_key(prefix, _all_slots(doc))
    group["slots"].append(new_key)
    data_io.write_validated(doc, slots_path, schema_path)
    return new_key


def add_background_slot(data_dir):
    """Append a new background tile slot (``tile_background_<n>``) to the map
    category's 'Tiles' → 'Background' subgroup — the palette's '+ Level' button.
    Art is imported onto it afterwards (grey-X until then)."""
    return _append_slot(data_dir, "map", ("Tiles", "Background"),
                        "tile_background_")


def _append_child_group(data_dir, category_key, group_path, label, slot):
    """Append a fresh leaf subgroup ``{label, slots: [slot]}`` to a group that
    already holds ``children``. Raises ``KeyError`` if the category/path is
    missing or the target is a leaf (``slots``) group."""
    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    schema_path = data_dir / "schemas" / "slots.schema.json"
    doc = data_io.load_json(slots_path)

    category = next(
        (c for c in doc["categories"] if c["key"] == category_key), None)
    if category is None:
        raise KeyError(f"no category {category_key!r}")
    group = _find_group(category["groups"], group_path)
    if "children" not in group:
        raise KeyError(f"group {group_path!r} has no children list to extend")

    group["children"].append({"label": label, "slots": [slot]})
    data_io.write_validated(doc, slots_path, schema_path)


def add_deco_prop(data_dir):
    """Add a new deco prop TYPE — a leaf subgroup ``Prop <n>`` holding its
    first variant slot ``deco_prop_<n>`` — under the deco category's 'Props'
    group. The palette's '+ Add Prop' button. Returns ``(label, slot_key)``;
    art is imported onto the slot afterwards (grey-X until then)."""
    data_dir = Path(data_dir)
    doc = data_io.load_json(data_dir / "slots.json")
    n = _next_numbered_suffix("deco_prop_", _all_slots(doc))
    label, slot = f"Prop {n}", f"deco_prop_{n}"
    _append_child_group(data_dir, "deco", ("Props",), label, slot)
    return label, slot
