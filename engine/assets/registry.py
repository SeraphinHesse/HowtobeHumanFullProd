"""Slot registry — data-driven slot declarations (E-34/D-32). Pure Python.

Loads data/slots.json (schema-validated, FAIL LOUD — the registry is
infrastructure like geometry.json; E-37's log-and-placeholder tolerance is
for art, not for this file). No game-specific names live in this code:
slot keys, categories, and grouping labels are all data.
"""
from dataclasses import dataclass, field

from engine import data_io


@dataclass(frozen=True)
class GroupNode:
    """One editor-tree group: label + either leaf slot keys or children."""
    label: str
    slots: tuple = ()
    children: tuple = ()


@dataclass(frozen=True)
class Category:
    key: str
    display_name: str
    frame_w: int
    frame_h: int
    animations: tuple
    groups: tuple = field(default=())


def _slot_key(entry):
    """A slots[] entry is a bare key string, or an object form
    ``{key, frame_w?, frame_h?, display_name?}``."""
    return entry if isinstance(entry, str) else entry["key"]


def _slot_frame_override(entry):
    """The entry's per-slot frame size, or None when it inherits the category's.

    The object form carries frame_w/frame_h as a PAIR or not at all (the
    schema's `dependentRequired`), so an object entry that exists only to name
    a slot still inherits its category's size."""
    if isinstance(entry, str) or "frame_w" not in entry:
        return None
    return (int(entry["frame_w"]), int(entry["frame_h"]))


def _slot_display_name(entry):
    """The entry's designer-facing name, or "" when it has none."""
    return "" if isinstance(entry, str) else entry.get("display_name", "")


def _parse_group(raw):
    # The object form is normalised away HERE: GroupNode.slots is a tuple of
    # key strings everywhere downstream (editor tree, game variant rolls).
    return GroupNode(
        label=raw["label"],
        slots=tuple(_slot_key(s) for s in raw.get("slots", ())),
        children=tuple(_parse_group(c) for c in raw.get("children", ())),
    )


def _walk_slots(node):
    yield from node.slots
    for child in node.children:
        yield from _walk_slots(child)


def _walk_raw_slots(raw):
    """Every raw slots[] entry under a raw group node, document order."""
    yield from raw.get("slots", ())
    for child in raw.get("children", ()):
        yield from _walk_raw_slots(child)


class SlotRegistry:
    """Parsed registry with slot -> category lookups.

    The same slot key may appear under several groups of ONE category
    (shared art); a key in two categories is a data error (frame size and
    vocabulary would be ambiguous) and raises ValueError. A repeated key must
    also agree with itself on frame size — the schema cannot express that
    (uniqueItems compares whole values, so a bare key and an object form of it
    are two distinct items), so the loader enforces it.
    """

    def __init__(self, doc):
        self._categories = {}
        self._slot_category = {}   # slot_key -> Category, first-seen order
        self._slot_frame = {}      # slot_key -> (frame_w, frame_h) override
        self._slot_names = {}      # slot_key -> display_name (editor-only)
        declared = {}              # slot_key -> its override, None = inherit
        for raw in doc["categories"]:
            category = Category(
                key=raw["key"],
                display_name=raw["display_name"],
                frame_w=int(raw["frame_w"]),
                frame_h=int(raw["frame_h"]),
                animations=tuple(raw["animations"]),
                groups=tuple(_parse_group(g) for g in raw["groups"]),
            )
            if category.key in self._categories:
                raise ValueError(f"duplicate category key: {category.key}")
            self._categories[category.key] = category
            for group in raw["groups"]:
                for entry in _walk_raw_slots(group):
                    slot_key = _slot_key(entry)
                    owner = self._slot_category.get(slot_key)
                    if owner is not None and owner.key != category.key:
                        raise ValueError(
                            f"slot {slot_key!r} declared in two categories: "
                            f"{owner.key!r} and {category.key!r}")
                    override = _slot_frame_override(entry)
                    if slot_key in declared and declared[slot_key] != override:
                        raise ValueError(
                            f"slot {slot_key!r} declared with conflicting frame "
                            f"sizes: {declared[slot_key]} and {override}")
                    declared[slot_key] = override
                    if override is not None:
                        self._slot_frame[slot_key] = override
                    # A repeated key (shared art under two groups of one
                    # category) keeps the FIRST name it was given: unlike frame
                    # size, two labels for one slot are cosmetic, not a data
                    # error, so this does not raise.
                    name = _slot_display_name(entry)
                    if name and slot_key not in self._slot_names:
                        self._slot_names[slot_key] = name
                    self._slot_category.setdefault(slot_key, category)

    def categories(self):
        return tuple(self._categories.values())

    def category(self, key):
        return self._categories[key]

    def group(self, category_key, path):
        """GroupNode at a label path inside a category (KeyError if absent)."""
        nodes = self._categories[category_key].groups
        node = None
        for label in path:
            match = next((n for n in nodes if n.label == label), None)
            if match is None:
                raise KeyError(f"{category_key}: no group at path {tuple(path)!r}")
            node = match
            nodes = node.children
        if node is None:
            raise KeyError(f"{category_key}: empty group path")
        return node

    def group_slots(self, category_key, path=()):
        """All slot keys under a group path, depth-first document order;
        path () means the whole category. KeyError on unknown path."""
        if path:
            nodes = (self.group(category_key, path),)
        else:
            nodes = self._categories[category_key].groups
        out = []
        for node in nodes:
            out.extend(_walk_slots(node))
        return tuple(out)

    def slot_keys(self):
        return tuple(self._slot_category)

    def category_of(self, slot_key):
        return self._slot_category[slot_key]

    def frame_size(self, slot_key):
        """The slot's per-slot override if it declared one, else its owning
        category's size (E-34). How the SHEET is sliced — not how big the
        thing draws (that is the renderer's fit)."""
        category = self._slot_category[slot_key]
        return self._slot_frame.get(
            slot_key, (category.frame_w, category.frame_h))

    def display_name(self, slot_key):
        """The slot's designer-facing name, or "" when it has none (the key is
        then its own label).

        EDITOR-ONLY: nothing in `game/` reads this. It is what the slot
        editor's Name field writes and what the UI screen editor's skin
        pickers show beside the key. An unknown key answers "" rather than
        raising, so a caller can safely label a stale slot ref."""
        return self._slot_names.get(slot_key, "")

    def animations(self, slot_key):
        return self._slot_category[slot_key].animations


def load_registry(data_dir):
    """Read data/slots.json validated against its schema (fail loud)."""
    return SlotRegistry(data_io.load_validated(
        data_dir / "slots.json",
        data_dir / "schemas" / "slots.schema.json"))
