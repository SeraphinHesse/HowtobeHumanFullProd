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

A ui button FAMILY (`add_button_family`) is the ui-category analogue of a deco
prop type: a new leaf child group under Buttons, ready for its own variants.
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


def set_slot_frame_size(data_dir, slot_key, frame_w, frame_h):
    """Set (or clear) ONE slot's per-slot frame-size override in data/slots.json.

    Frame size is a CATEGORY property; ER-1 added an optional per-slot override so
    one enemy can be sliced 128x128 while the rest of `enemies` stays 64x96. A
    slots[] entry is therefore either a bare key string (inherit the category) or
    `{key, frame_w, frame_h}`.

    Passing the owning category's OWN size writes the bare string back — that is
    how "reset to the category default" is expressed, and it keeps slots.json free
    of overrides that override nothing. Returns True when an override is now in
    place, False when the slot inherits.

    Raises KeyError for an unknown slot.
    """
    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    schema_path = data_dir / "schemas" / "slots.schema.json"
    doc = data_io.load_json(slots_path)
    frame_w, frame_h = int(frame_w), int(frame_h)

    for category in doc["categories"]:
        inherits = (frame_w == category["frame_w"]
                    and frame_h == category["frame_h"])
        entry = {"key": slot_key, "frame_w": frame_w, "frame_h": frame_h}

        def walk(node):
            slots = node.get("slots")
            if slots is None:
                return any(walk(child) for child in node.get("children", ()))
            for i, existing in enumerate(slots):
                if _slot_key(existing) == slot_key:
                    slots[i] = slot_key if inherits else dict(entry)
                    return True
            return False

        if any(walk(group) for group in category["groups"]):
            data_io.write_validated(doc, slots_path, schema_path)
            return not inherits

    raise KeyError(f"no slot {slot_key!r} in the registry")


def _slot_entry_from_template(new_key, template):
    """The slots[] entry for a freshly added variant, inheriting the family's
    template slot (``child["slots"][0]``, the stem) frame-size override when
    it carries one.

    ``template`` is a bare key string or an override dict (``{key, frame_w,
    frame_h}``). A dict template yields a new dict with the SAME frame_w/
    frame_h so the variant is sliced identically to the slot it was copied
    from (``ui_bg_main_menu`` at 480x270 -> ``ui_bg_main_menu_v2`` also at
    480x270); a bare-string template yields a bare new entry, unchanged
    (enemies/deco families, which carry no override)."""
    if isinstance(template, dict):
        return {"key": new_key, "frame_w": template["frame_w"],
                "frame_h": template["frame_h"]}
    return new_key


def add_variant(data_dir, category_key, group_path, subcat_label):
    """Append a fresh variant slot to one era subgroup of data/slots.json and
    return the new slot key.

    ``group_path`` is the label path to the era's PARENT group (e.g.
    ``("Walker",)``); ``subcat_label`` is the era child's label (``"Era 2"``).
    The new variant INHERITS the family stem's (``child["slots"][0]``)
    per-slot frame-size override when the stem carries one — a dict-form stem
    like ``{"key": "ui_bg_main_menu", "frame_w": 480, "frame_h": 270}`` yields
    a new variant at the same 480x270, not the category default; a bare-string
    stem (the common case — enemies, deco) yields a bare variant, as before.
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
    template = child["slots"][0]
    child["slots"].append(_slot_entry_from_template(new_key, template))
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


_SLUG_COLLAPSE = re.compile(r"[^a-z0-9]+")


def button_family_slot(name):
    """Derive the slot key for a new ui button family from a human name.

    Slug = lowercased, every non-``[a-z0-9]`` run collapsed to one ``"_"``,
    trimmed. Prefix ``"ui_button_"`` is added unless the slug already starts
    with ``"ui_button"`` (typing the key itself must not double-prefix).
    Raises ``ValueError`` when nothing slug-like survives."""
    slug = _SLUG_COLLAPSE.sub("_", (name or "").strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"no valid slot key derivable from {name!r}")
    if slug.startswith("ui_button"):
        return slug
    return f"ui_button_{slug}"


def add_button_family(data_dir, name):
    """Append a new leaf child group ``{label, slots: [key]}`` under
    ui -> Buttons — a new button FAMILY, the ui-category analogue of
    ``add_deco_prop``. ``label`` is ``name.strip()``; ``key`` is
    ``button_family_slot(name)``.

    Raises ``ValueError`` (BEFORE any write) when the key collides with any
    slot already in the registry (``_all_slots``) or the label collides with
    an existing Buttons child label; ``KeyError`` for structural path
    problems (no 'ui' category / no 'Buttons' group). Returns
    ``(label, slot_key)``, like ``add_deco_prop``."""
    data_dir = Path(data_dir)
    doc = data_io.load_json(data_dir / "slots.json")
    slot = button_family_slot(name)
    label = name.strip()

    category = next(
        (c for c in doc["categories"] if c["key"] == "ui"), None)
    if category is None:
        raise KeyError("no category 'ui'")
    buttons_group = _find_group(category["groups"], ("Buttons",))
    existing_labels = {child["label"]
                       for child in buttons_group.get("children", ())}
    if label in existing_labels:
        raise ValueError(f"a Buttons family named {label!r} already exists")
    if slot in _all_slots(doc):
        raise ValueError(f"slot {slot!r} already exists in the registry")

    _append_child_group(data_dir, "ui", ("Buttons",), label, slot)
    return label, slot
