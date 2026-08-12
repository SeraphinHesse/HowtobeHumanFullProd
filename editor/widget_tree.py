"""Widget parenting for screen mode (UiEditorParentingPLAN P-1) — pure.

The editor's UI-screen widgets used to be a flat list of independent records:
``hud.love_text`` sits inside ``hud.love_panel`` only because their numbers
happen to agree. This module is the ONE place that turns
``screen_defaults.json``'s optional ``parent`` key (plus the open override
doc's own ``parent``, D3) into a real hierarchy the viewport and the details
panel can both read.

**Parenting is an AUTHORING relationship, not a runtime one** (plan D2). The
game's own ``layout()`` still recomputes every widget's default each frame
with no cascade, and the saved rects stay ABSOLUTE — the editor cascades a
move at EDIT time and writes the result. Nothing in ``game/`` reads
``parent``.

Contract for the two ``parent`` values (plan D1/D3):
  * absent from both the default spec and the override -> the widget is a ROOT
  * a string in either -> that widget id, the override winning
  * an explicit ``None`` (JSON ``null``) IN THE OVERRIDE -> re-rooted; the
    designer rejected the default parent. This is why every accessor here
    tests ``"parent" in override`` rather than ``override.get("parent")``:
    "no override" and "override says root" are different states.

D5 — a cycle is unrepresentable, never an exception. ``would_cycle`` gates
the re-parent action, and ``parent_map`` additionally resolves a cyclic or
dangling chain to ROOT rather than raising: a hand-edited
``screen_defaults.json`` must never be able to hang a Qt paint handler.

Qt-free, pygame-free, stdlib only (``TestPurity``).
"""

# The key both docs store the relationship under, and the sentinel this
# module returns for "this widget has no parent".
PARENT_KEY = "parent"
ROOT = None


def resolve_parent(widget_id, spec, override):
    """The parent id this ONE widget declares, before any tree-wide
    sanitising: the override's own ``parent`` when the key is present (a
    string, or ``None`` meaning the designer re-rooted it), else the
    exporter-authored default, else ``ROOT``.

    ``widget_id`` is accepted (and used only to refuse self-parenting) so the
    signature reads the same as every other accessor in screen mode.
    """
    override = override or {}
    spec = spec or {}
    if PARENT_KEY in override:
        parent = override[PARENT_KEY]
    else:
        parent = spec.get(PARENT_KEY)
    if not parent or parent == widget_id:
        return ROOT
    return parent


def parent_map(defaults_widgets, doc_widgets=None):
    """``{widget_id: parent_id | ROOT}`` for every id in ``defaults_widgets``,
    sanitised so the result is always a forest:

      * a parent naming an id that is not in this screen+view is dropped to
        ROOT (a dangling parent is authoring noise, not an error — a
        ``building_panel`` view legitimately shows only some of the ids)
      * a widget whose parent chain loops back onto itself is dropped to ROOT
        (D5)

    Insertion order follows ``defaults_widgets``, which is the JSON key order
    of the file — sorted, because ``data/`` is written deterministically. That
    is what makes every derived order in this module stable.
    """
    doc_widgets = doc_widgets or {}
    parents = {}
    for widget_id, spec in defaults_widgets.items():
        parent = resolve_parent(widget_id, spec,
                                doc_widgets.get(widget_id) or {})
        if parent not in defaults_widgets:
            parent = ROOT
        parents[widget_id] = parent
    for widget_id in parents:
        seen = {widget_id}
        cursor = parents[widget_id]
        while cursor is not ROOT:
            if cursor in seen:
                parents[widget_id] = ROOT
                break
            seen.add(cursor)
            cursor = parents.get(cursor, ROOT)
    return parents


def build_tree(defaults_widgets, doc_widgets=None):
    """``{parent_id: [child_id, ...]}`` adjacency, with the screen's ROOT
    widgets under the ``ROOT`` (``None``) key.

    Every id in ``defaults_widgets`` appears exactly once as somebody's child;
    ids with no children simply carry no key of their own. Child order is
    ``defaults_widgets`` order (stable, see ``parent_map``).
    """
    tree = {ROOT: []}
    for widget_id, parent in parent_map(defaults_widgets, doc_widgets).items():
        tree.setdefault(parent, []).append(widget_id)
    return tree


def children(tree, widget_id):
    """Direct children of ``widget_id`` (``ROOT`` for the top level)."""
    return list(tree.get(widget_id, ()))


def descendants(tree, widget_id):
    """Every widget under ``widget_id``, depth-first in child order — the set
    a viewport move cascades over (P-3). Never includes ``widget_id`` itself.

    The walk carries its own ``seen`` set even though ``parent_map`` already
    broke every cycle: this function also takes hand-built trees (tests, and
    any future caller that assembles adjacency itself), and an infinite loop
    inside a Qt paint handler is exactly the failure D5 exists to prevent.
    """
    out, seen = [], {widget_id}
    stack = list(reversed(children(tree, widget_id)))
    while stack:
        node = stack.pop()
        if node in seen:
            continue
        seen.add(node)
        out.append(node)
        stack.extend(reversed(children(tree, node)))
    return out


def ancestors(parents, widget_id):
    """The chain from ``widget_id``'s parent up to its root, nearest first,
    read off a ``parent_map``. Empty for a root widget."""
    out, seen = [], {widget_id}
    cursor = parents.get(widget_id, ROOT)
    while cursor is not ROOT and cursor not in seen:
        out.append(cursor)
        seen.add(cursor)
        cursor = parents.get(cursor, ROOT)
    return out


def would_cycle(tree, child, new_parent):
    """True when re-parenting ``child`` onto ``new_parent`` would make a
    widget its own ancestor — the drop the tree must REFUSE (D5, ED-30's
    "invalid input unrepresentable"). Dropping onto ``ROOT`` is always legal.
    """
    if new_parent is ROOT:
        return False
    if new_parent == child:
        return True
    return new_parent in descendants(tree, child)


def legal_parents(defaults_widgets, doc_widgets, widget_id):
    """Every id in this screen+view that ``widget_id`` may legally be parented
    to, in ``defaults_widgets`` order — i.e. everything except itself and its
    own descendants. Feeds the details panel's Parent combo (P-4), which is
    the keyboard-accessible twin of the tree drag, so the two must refuse
    exactly the same drops."""
    tree = build_tree(defaults_widgets, doc_widgets)
    return [wid for wid in defaults_widgets
            if not would_cycle(tree, widget_id, wid)]
