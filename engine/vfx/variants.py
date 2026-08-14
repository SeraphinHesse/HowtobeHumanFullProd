"""variants — resolving one VFX slot's interchangeable art (VfxAuthoringPLAN
VA-2).

A "variant" here is what it is everywhere else in this repo: one more
interchangeable slot sharing a leaf group in ``data/slots.json``, keyed
``<stem>_v<k>`` (``editor/registry_ops.py``). This module answers only the two
questions that are pure registry mechanics:

* ``variant_slots`` — which slots are interchangeable with this one.
* ``slot_at`` — pick one by index, clamped.

**It deliberately knows nothing about HOW the index was chosen.** The
``"random"``/``"level"``/``"misc"`` mode names in
``data/balancing/vfx.json``'s ``variant_select`` are vocabulary, and D5 keeps
vocabulary out of ``engine/`` exactly as it keeps JSON key names out —
``params.py``'s docstring makes the same call for spark presets ("the engine
only ever sees the resolved dataclass"). ``game/vfx_variants.py`` maps a mode
to an index and calls in here; ``editor/`` mirrors that mapping for its
preview, the sanctioned duplication ``editor/vfx_params.py`` already is.

Pure Python: no pygame, no ``data/`` access, and it never reads a file.
(That last clause is deliberately worded around the builtin's name — the
package purity scan in ``tools/tests/test_vfx.py`` is a literal text sweep, so
naming it even in prose reads as a violation.)
"""


def _leaf_with(node, slot_key):
    """The leaf group node holding ``slot_key``, depth-first document order,
    or None. A key may legally repeat across groups of ONE category (shared
    art), in which case the FIRST leaf wins — the same document-order rule
    ``SlotRegistry`` uses when it maps a key to its category."""
    if slot_key in node.slots:
        return node
    for child in node.children:
        found = _leaf_with(child, slot_key)
        if found is not None:
            return found
    return None


def variant_slots(registry, slot_key):
    """Every slot interchangeable with ``slot_key``, in document order,
    ALWAYS including ``slot_key`` itself.

    Resolved through the registry's group structure rather than by matching
    the ``_v<k>`` suffix, for the same reason ``game/enemies/enemy.py``'s
    era roll reads ``group_slots(...)``: the grouping is the authored truth,
    and a rename (VA-6) moves a slot's group with it while a suffix match
    would silently stop finding its family.

    Degrades to ``(slot_key,)`` for a slot the registry does not know or
    cannot place in a leaf — never raises, so an un-imported or half-renamed
    slot plays its own art instead of nothing (E-37).
    """
    try:
        category = registry.category_of(slot_key)
    except KeyError:
        return (slot_key,)
    for group in category.groups:
        leaf = _leaf_with(group, slot_key)
        if leaf is not None:
            return tuple(leaf.slots)
    return (slot_key,)


def slot_at(variants, index):
    """``variants[index]`` with ``index`` CLAMPED to the ends, or None when
    there are no variants at all.

    Clamped rather than wrapped: a building tier or enemy era past the last
    authored variant should keep showing the last one (``game/enemies/
    enemy.py``'s ``min(max(era, 0), len - 1)`` era pick), not cycle back to
    the first. A non-integer or None index reads as 0.
    """
    if not variants:
        return None
    try:
        i = int(index)
    except (TypeError, ValueError):
        i = 0
    return variants[max(0, min(i, len(variants) - 1))]
