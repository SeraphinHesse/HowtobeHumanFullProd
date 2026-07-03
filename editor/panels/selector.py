"""SelectorPanel (ED-3, ED-10/11) — the tree the whole editor hangs off.

Phase 5 shape (user-confirmed): ONE merged tree built from the slot
registry — top-level nodes are the registry categories (the first five
double as the balancing domains; vfx/deco are asset-only), children are the
registry group nodes. The tree deliberately stops at the deepest group
whose children are all leaf groups (a building TYPE like "Defender"): tiers
and levels are picked in the Details panel / level bar, not here
(editor.selection owns that resolution). ● marks any node with at least one
assigned manifest slot in its subtree (ED-11).

Plain Qt widget; imports only the PURE half of engine.assets (registry +
manifest metadata — no pygame). Exactly one node selected at a time (ED-3);
selection is broadcast as node_selected(category, group_path) always, plus
domain_selected(str) when the category is a balancing domain — the Phase 4
contract the balancing panel still hangs off, now fired at any depth so
clicking a building type also shows the buildings form.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from editor import locks
from engine.assets import load_manifest, load_registry

REPO = Path(__file__).resolve().parents[2]

_PAYLOAD_ROLE = Qt.ItemDataRole.UserRole        # (category_key, group_path)
_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1      # clean label, no ● prefix


class SelectorPanel(QTreeWidget):
    domain_selected = Signal(str)
    node_selected = Signal(str, tuple)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.registry = load_registry(self._data_dir)
        self.setHeaderLabel("Project")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for category in self.registry.categories():
            if category.key in locks.DOMAINS and \
                    not locks.balancing_path(category.key, self._data_dir).exists():
                continue  # Phase 4 behavior: no balancing file, no domain node
            root = self._make_item(category.display_name, category.key, ())
            self.addTopLevelItem(root)
            for group in category.groups:
                self._add_group(root, category.key, group, ())
        self.refresh_markers()
        self.itemSelectionChanged.connect(self._emit_selection)

    # -- tree construction ---------------------------------------------------

    def _make_item(self, label, category_key, path):
        item = QTreeWidgetItem([label])
        item.setData(0, _PAYLOAD_ROLE, (category_key, path))
        item.setData(0, _LABEL_ROLE, label)
        return item

    def _add_group(self, parent, category_key, group, prefix):
        path = prefix + (group.label,)
        item = self._make_item(group.label, category_key, path)
        parent.addChild(item)
        # Recurse only while some child has children of its own; a group
        # whose children are all leaves is a Details-dropdown node and the
        # tree stops here (editor.selection._is_dropdown_node's mirror).
        if group.children and any(child.children for child in group.children):
            for child in group.children:
                self._add_group(item, category_key, child, path)

    # -- queries / programmatic selection -------------------------------------

    def domains(self):
        """Balancing-domain keys currently listed, in tree (D-10) order."""
        out = []
        for i in range(self.topLevelItemCount()):
            key, _path = self.topLevelItem(i).data(0, _PAYLOAD_ROLE)
            if key in locks.DOMAINS:
                out.append(key)
        return tuple(out)

    def select_domain(self, domain):
        """Programmatic selection of a domain root (initial selection, tests)."""
        if domain not in self.domains():
            raise KeyError(f"no domain node {domain!r}")
        self.select_node(domain, ())

    def select_node(self, category_key, path):
        """Programmatic selection of any tree node by registry payload."""
        item = self._find_item(category_key, path)
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()
        self.setCurrentItem(item)

    def _find_item(self, category_key, path):
        wanted = (category_key, tuple(path))
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, _PAYLOAD_ROLE) == wanted:
                return item
            stack.extend(item.child(i) for i in range(item.childCount()))
        raise KeyError(f"no tree node for {wanted!r}")

    # -- ● markers (ED-11) -----------------------------------------------------

    def refresh_markers(self):
        """Re-read the manifest (pure loader) and re-mark every node whose
        subtree holds at least one assigned slot. Call after import saves."""
        assigned = set(load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json").slots())
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            category_key, path = item.data(0, _PAYLOAD_ROLE)
            slots = self.registry.group_slots(category_key, path)
            label = item.data(0, _LABEL_ROLE)
            marked = any(slot in assigned for slot in slots)
            item.setText(0, ("● " + label) if marked else label)
            stack.extend(item.child(i) for i in range(item.childCount()))

    # -- selection broadcast ---------------------------------------------------

    def _emit_selection(self):
        items = self.selectedItems()
        if not items:
            return
        category_key, path = items[0].data(0, _PAYLOAD_ROLE)
        self.node_selected.emit(category_key, tuple(path))
        if category_key in locks.DOMAINS:
            self.domain_selected.emit(category_key)
