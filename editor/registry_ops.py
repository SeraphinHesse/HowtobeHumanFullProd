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


def set_slot_display_name(data_dir, slot_key, display_name):
    """Set (or clear) ONE slot's designer-facing name in data/slots.json.

    The name is EDITOR-ONLY (nothing in `game/` reads it): it is how a designer
    tells `ui_panel_v3` apart from `ui_panel_v2` in the slot editor and in the
    UI screen editor's skin pickers, where the raw key is otherwise the only
    label. Storing it needs the object form of the slots[] entry, so a bare-key
    slot is promoted to `{key, display_name}`; an empty/blank name drops the
    key again and collapses the entry back to a bare string when it carried no
    frame-size override either (same "never store an override that overrides
    nothing" rule as `set_slot_frame_size`).

    A key may legally appear under several groups of ONE category (shared art);
    EVERY occurrence is updated, so the registry cannot end up with two labels
    for one slot. Returns True when a name is now stored, False when the slot
    is back to being labelled by its key.

    Raises KeyError for an unknown slot.
    """
    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    schema_path = data_dir / "schemas" / "slots.schema.json"
    doc = data_io.load_json(slots_path)
    name = (display_name or "").strip()

    def rewritten(existing):
        entry = {"key": slot_key} if isinstance(existing, str) else dict(existing)
        if name:
            entry["display_name"] = name
        else:
            entry.pop("display_name", None)
        # A {key}-only object says nothing a bare key does not.
        return entry if len(entry) > 1 else slot_key

    found = False

    def walk(node):
        nonlocal found
        slots = node.get("slots")
        if slots is None:
            for child in node.get("children", ()):
                walk(child)
            return
        for i, existing in enumerate(slots):
            if _slot_key(existing) == slot_key:
                slots[i] = rewritten(existing)
                found = True

    for category in doc["categories"]:
        for group in category["groups"]:
            walk(group)

    if not found:
        raise KeyError(f"no slot {slot_key!r} in the registry")
    data_io.write_validated(doc, slots_path, schema_path)
    return bool(name)


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


# ===========================================================================
# VFX roster: add / remove / rename (VfxAuthoringPLAN VA-6)
# ===========================================================================
# Until this phase this module could only APPEND. A designer could not delete
# an effect they added by mistake and could not rename one, so a roster grew
# monotonically and its keys were whatever they were first typed as.
#
# Remove and rename are the first DESTRUCTIVE registry ops in the repo, so both
# validate everything before touching disk (add_button_family's shape) and both
# refuse rather than guess. Rename in particular is a FOUR-FILE migration —
# slots.json, the manifest entry, the PNG on disk, and every triggers row
# naming the old key — and one that updated three of the four would leave
# either a dangling binding or art nobody can reach.


def _resync_slot_enums(data_dir):
    """Regenerate BOTH generated slot enums from the registry the caller just
    changed: ``vfx.schema.json``'s ``trigger_row.sprite_slot`` AND
    ``core.schema.json``'s ``enemy_intro_entry.sprite_slot``.

    Load-bearing, not housekeeping. That enum is GENERATED (VA-1/D2), so a
    freshly added slot is not a legal ``sprite_slot`` value until it is
    regenerated — which would mean "Add effect" handing the designer an effect
    they cannot BIND, and "Rename" writing a trigger row that fails its own
    schema on the way out. Found by ``test_vfx_roster_ops``, which could not
    bind a slot it had just created.

    BOTH, not just the vfx one. That was the bug the exit gate caught:
    ``core.schema.json``'s enum spans EVERY slot in EVERY category, so adding a
    vfx effect through the editor made it stale exactly as much as adding an
    enemy would have. Resyncing only the vfx enum left `test_schema_slot_sync
    .TestSpriteSlotEnumSync` red, and the designer who added the effect had no
    reason to connect their click to a schema in another domain.

    It CALLS the generators rather than reimplementing them:
    ``test_schema_slot_sync`` pins their output, and a second copy here would
    be precisely the drift a generated enum exists to prevent.
    ``editor -> tools`` is the established direction (``editor/main.py``
    imports ``tools.smoke``; ``editor/test_runner.py`` imports
    ``tools.test_domains``), and the generators are pure ``engine`` underneath
    so ``TestPurity`` is unaffected. Imported locally to keep this module's
    top-level import surface engine-only.

    KNOWN GAP, pre-existing and out of scope here: the other append ops
    (``add_variant``, ``_append_slot``, ``add_background_slot``,
    ``add_deco_prop``, ``add_button_family``) do NOT call this, so adding an
    enemy variant or a deco prop through the editor still leaves
    ``core.schema.json`` stale. That predates this branch and affects every
    category; ``test_vfx_roster_ops.TestBothSlotEnumsStayInSync`` pins the
    current behaviour so the gap is visible rather than silent."""
    from tools.gen_sprite_slot_enum import apply, apply_vfx

    data_dir = Path(data_dir)
    schemas = data_dir / "schemas"
    vfx_schema = schemas / "vfx.schema.json"
    if vfx_schema.exists():
        apply_vfx(vfx_schema, data_dir)
    core_schema = schemas / "core.schema.json"
    if core_schema.exists():
        apply(core_schema, data_dir)


def vfx_effect_slot(name):
    """The slot key for a new VFX effect, from a human name.

    ``button_family_slot``'s rule with the ``vfx_`` prefix: lowercase, every
    non-``[a-z0-9]`` run collapsed to one underscore, trimmed, and the prefix
    added unless the slug already carries it (typing the key itself must not
    double-prefix). ``ValueError`` when nothing slug-like survives."""
    slug = _SLUG_COLLAPSE.sub("_", (name or "").strip().lower()).strip("_")
    if not slug:
        raise ValueError(f"no valid slot key derivable from {name!r}")
    if slug.startswith("vfx"):
        return slug
    return f"vfx_{slug}"


def _vfx_effects_group(doc):
    """The vfx category's 'Effects' group node (raw dict), which must hold
    ``children``.

    VA-1 restructured this group from a flat ``slots`` list into one leaf CHILD
    group per effect precisely so it could host variants; every op below
    depends on that shape, so this raises loudly rather than degrading if it is
    ever flattened again."""
    category = next(
        (c for c in doc["categories"] if c["key"] == "vfx"), None)
    if category is None:
        raise KeyError("no category 'vfx'")
    group = _find_group(category["groups"], ("Effects",))
    if "children" not in group:
        raise KeyError(
            "vfx -> Effects is a flat slots group; VA-1's per-effect child "
            "groups are what make variants and this roster editable")
    return group


def add_vfx_effect(data_dir, name):
    """Add a VFX effect: a new leaf child group ``{label, slots: [key]}`` under
    vfx -> Effects, ready for its own ``_v<k>`` variants.

    ``add_button_family``'s exact stack, one category over. Returns
    ``(label, slot_key)``; art is imported onto the slot afterwards (grey-X
    until then), and the GENERATED ``sprite_slot`` enum (VA-1/D2) picks the key
    up on the next ``py tools/gen_sprite_slot_enum.py`` run, which is what
    makes it bindable to a trigger.

    Raises ``ValueError`` BEFORE any write on a duplicate label or on a key
    that collides anywhere in the registry."""
    data_dir = Path(data_dir)
    doc = data_io.load_json(data_dir / "slots.json")
    slot = vfx_effect_slot(name)
    label = name.strip()

    group = _vfx_effects_group(doc)
    if label in {child["label"] for child in group["children"]}:
        raise ValueError(f"a VFX effect named {label!r} already exists")
    if slot in _all_slots(doc):
        raise ValueError(f"slot {slot!r} already exists in the registry")

    _append_child_group(data_dir, "vfx", ("Effects",), label, slot)
    _resync_slot_enums(data_dir)
    return label, slot


def trigger_bindings(data_dir, slot_key):
    """Every ``triggers`` event whose ``sprite_slot`` names ``slot_key``.

    Read tolerantly: a missing or unreadable balancing file means "no
    bindings", never a crash — an editor op must not die because a data file
    happens to be mid-edit (E-37). Public because the panel wants the same
    answer to explain a refused delete."""
    path = Path(data_dir) / "balancing" / "vfx.json"
    try:
        doc = data_io.load_json(path)
    except (OSError, ValueError):
        return ()
    triggers = (doc or {}).get("triggers") or {}
    return tuple(sorted(
        event for event, row in triggers.items()
        if isinstance(row, dict) and row.get("sprite_slot") == slot_key))


def remove_slot(data_dir, slot_key):
    """Remove ``slot_key`` from the vfx category, with its manifest entry and
    — only when nothing else needs it — its PNG.

    **Refuses while the slot is BOUND** to any trigger row rather than silently
    leaving a row pointing at a key that no longer exists. Unbinding first is
    one editor click, and it is a decision the designer should make
    consciously; ``ValueError`` names the events.

    The PNG is unlinked ONLY when ``asset_import.unreferenced_sheets`` says no
    remaining entry references it — a slot that LINKED to another slot's art
    must never delete art the owner still needs.

    A leaf group left with no slots is dropped along with it: a child group
    with an empty ``slots`` list fails the schema, and an effect with no slots
    is not an effect. Removing the LAST effect is refused for the same
    schema reason.

    Returns ``(removed_group, removed_png)`` so the caller can report what
    actually happened."""
    from editor import asset_import   # local: keeps this module's import
    # surface engine-only for every caller that never removes anything.

    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    doc = data_io.load_json(slots_path)

    bound = trigger_bindings(data_dir, slot_key)
    if bound:
        raise ValueError(
            f"slot {slot_key!r} is still bound to {', '.join(bound)} - "
            f"unbind it before removing it")

    group = _vfx_effects_group(doc)
    owner = next(
        (child for child in group["children"]
         if slot_key in [_slot_key(s) for s in child.get("slots", ())]), None)
    if owner is None:
        raise KeyError(f"no vfx slot {slot_key!r}")

    remaining = [s for s in owner["slots"] if _slot_key(s) != slot_key]
    removed_group = not remaining
    if removed_group and len(group["children"]) == 1:
        raise ValueError(
            "refusing to remove the last VFX effect - the Effects group needs "
            "at least one child to stay schema-valid")
    if removed_group:
        group["children"].remove(owner)
    else:
        owner["slots"] = remaining
    data_io.write_validated(doc, slots_path,
                            data_dir / "schemas" / "slots.schema.json")
    _resync_slot_enums(data_dir)

    manifest = asset_import.load_manifest_doc(data_dir)
    entry = manifest["entries"].pop(slot_key, None)
    removed_png = None
    if entry is not None:
        asset_import.write_manifest_doc(data_dir, manifest)
        ref = entry.get("sheet") or asset_import.sheet_ref(slot_key)
        for orphan in asset_import.unreferenced_sheets(manifest, (ref,)):
            png = data_dir / "sprites" / orphan
            if png.exists():
                png.unlink()
                removed_png = orphan
    return removed_group, removed_png


def rename_slot(data_dir, old_key, new_key):
    """Rename a vfx slot everywhere it is referenced.

    FOUR files move together, and that is the entire point of the op:

    1. ``slots.json`` — the key itself, in either the bare or the
       frame-size-override form.
    2. ``asset_manifest.json`` — the entry is re-keyed.
    3. ``data/sprites/imported/<old>.png`` — renamed, and the entry's ``sheet``
       rewritten, but ONLY when this slot OWNS that art. A slot linked to
       another slot's sheet keeps pointing at it.
    4. ``balancing/vfx.json`` — every ``triggers`` row naming the old key.

    Everything is validated first: an unknown ``old_key``, a malformed
    ``new_key``, or a ``new_key`` already anywhere in the registry raises
    before a single file is touched. Renaming a slot to itself is a no-op.

    The caller should re-run ``py tools/gen_sprite_slot_enum.py`` afterwards so
    the generated ``sprite_slot`` enum follows (VA-1/D2); until then the schema
    still lists the old key.

    Returns ``(events_rebound, png_renamed)``."""
    from editor import asset_import

    data_dir = Path(data_dir)
    slots_path = data_dir / "slots.json"
    doc = data_io.load_json(slots_path)

    if new_key == old_key:
        return (), False
    if not re.fullmatch(r"[a-z][a-z0-9_]*", new_key or ""):
        raise ValueError(f"{new_key!r} is not a valid slot key")
    existing = _all_slots(doc)
    if old_key not in existing:
        raise KeyError(f"no slot {old_key!r}")
    if new_key in existing:
        raise ValueError(f"slot {new_key!r} already exists in the registry")

    group = _vfx_effects_group(doc)
    found = False
    for child in group["children"]:
        for i, entry in enumerate(child.get("slots", ())):
            if _slot_key(entry) != old_key:
                continue
            child["slots"][i] = (new_key if isinstance(entry, str)
                                 else {**entry, "key": new_key})
            found = True
    if not found:
        raise KeyError(f"{old_key!r} is not a vfx slot")
    data_io.write_validated(doc, slots_path,
                            data_dir / "schemas" / "slots.schema.json")
    # BEFORE the trigger rewrite below: those rows validate against this enum.
    _resync_slot_enums(data_dir)

    png_renamed = False
    manifest = asset_import.load_manifest_doc(data_dir)
    entry = manifest["entries"].pop(old_key, None)
    if entry is not None:
        if entry.get("sheet") == asset_import.sheet_ref(old_key):
            src = data_dir / "sprites" / entry["sheet"]
            entry = {**entry, "sheet": asset_import.sheet_ref(new_key)}
            dst = data_dir / "sprites" / entry["sheet"]
            if src.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dst)
                png_renamed = True
        manifest["entries"][new_key] = entry
        asset_import.write_manifest_doc(data_dir, manifest)

    rebound = trigger_bindings(data_dir, old_key)
    if rebound:
        vfx_path = data_dir / "balancing" / "vfx.json"
        vfx_doc = data_io.load_json(vfx_path)
        for event in rebound:
            vfx_doc["triggers"][event]["sprite_slot"] = new_key
        data_io.write_validated(
            vfx_doc, vfx_path, data_dir / "schemas" / "vfx.schema.json")
    return rebound, png_renamed
