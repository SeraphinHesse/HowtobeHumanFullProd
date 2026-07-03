"""Pure tree-node -> slot resolver shared by the editor shell (no Qt).

The editor's slot selection is composite (user-confirmed Phase 5 layout):
the TREE selects a group node (building type, tile family), the Details
panel's dropdown selects the SUBCATEGORY (tier, or a concrete slot), and
the level bar selects among a tier's slots (levels). These helpers answer,
from registry data only, what each widget should offer and which slot key
the trio resolves to.

Rules (all data-driven — no game names in code):
- A tree node whose children are ALL leaf groups (e.g. "Defender" with its
  tier children) exposes those children as subcategories; each child's
  slots list is its level list.
- A tree node with direct slots (e.g. "Blocker", "Walker") exposes the
  slots themselves as subcategories; there is no level dimension.
- Category roots and nodes the tree recursed through have no slot context.
"""


def _node(registry, category_key, path):
    if not path:
        return None
    try:
        return registry.group(category_key, path)
    except KeyError:
        return None


def _is_dropdown_node(group):
    """True when the tree stops at this group and its children (or slots)
    belong in the Details dropdown."""
    if group is None:
        return False
    if group.slots:
        return True
    return bool(group.children) and not any(c.children for c in group.children)


def subcategories(registry, category_key, path):
    """Dropdown labels for a tree node; () when the node has no slot context."""
    group = _node(registry, category_key, path)
    if not _is_dropdown_node(group):
        return ()
    if group.children:
        return tuple(c.label for c in group.children)
    return group.slots


def level_slots(registry, category_key, path, subcat_idx):
    """Slot keys the level bar switches between for one subcategory; a
    1-tuple when the subcategory is a single slot (level bar hidden);
    () on an invalid index."""
    group = _node(registry, category_key, path)
    if not _is_dropdown_node(group) or subcat_idx < 0:
        return ()
    if group.children:
        if subcat_idx >= len(group.children):
            return ()
        return group.children[subcat_idx].slots
    if subcat_idx >= len(group.slots):
        return ()
    return (group.slots[subcat_idx],)


def resolve_slot(registry, category_key, path, subcat_idx, level_idx):
    """The slot key a (tree node, subcategory, level) trio points at, or
    None when the selection has no slot context / indices are stale."""
    slots = level_slots(registry, category_key, path, subcat_idx)
    if not slots or not 0 <= level_idx < len(slots):
        return None
    return slots[level_idx]
