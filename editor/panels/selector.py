"""SelectorPanel (ED-3, ED-10/11) — the tree the whole editor hangs off.

Phase 5 shape (user-confirmed): ONE merged tree built from the slot
registry — top-level nodes are the registry categories (the first five
double as the balancing domains; vfx/deco are asset-only), children are the
registry group nodes. The tree deliberately stops at the deepest group
whose children are all leaf groups (a building TYPE like "Defender"): tiers
and levels are picked in the Details panel / level bar, not here
(editor.selection owns that resolution). ● marks any node with at least one
assigned manifest slot in its subtree (ED-11).

Phase 6 adds the "Maps" branch (ED-10) as the FIRST child of the "map"
category: one node per data/maps/*.json (pointer excluded), labelled with
the map's display name, ● prefix on the ACTIVE map (refresh_maps owns
these markers; refresh_markers skips map nodes). Selecting a map node
emits map_selected(map_id) + domain_selected("map") — never
node_selected, so the entity-preview machinery stays untouched.

Phase 6 follow-up: the "deco" registry category is nested as a CHILD of
the "map" top-level node instead of its own top-level node (deco is
browsed/imported while painting a map, so it reads as part of map editing)
— a tree-construction-only change. The registry category itself, its own
frame size (64x96, distinct from map tiles' 64x32), and its category_key
("deco") are untouched everywhere else (editor.selection, DetailsPanel,
the map palette's Deco section) — only where its root QTreeWidgetItem gets
parented changes.

Plain Qt widget; imports only the PURE half of engine.assets (registry +
manifest metadata — no pygame) and engine.tilemap. Exactly one node
selected at a time (ED-3); selection is broadcast as
node_selected(category, group_path) always, plus domain_selected(str)
when the category is a balancing domain — the Phase 4 contract the
balancing panel still hangs off, now fired at any depth so clicking a
building type also shows the buildings form.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from editor import locks
from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry

REPO = Path(__file__).resolve().parents[2]

_PAYLOAD_ROLE = Qt.ItemDataRole.UserRole        # (category_key, group_path)
_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1      # clean label, no ● prefix
_MAP_ROLE = Qt.ItemDataRole.UserRole + 2        # map_id (Maps-branch leaves)

_MAPS_BRANCH_LABEL = "Maps"


class SelectorPanel(QTreeWidget):
    domain_selected = Signal(str)
    node_selected = Signal(str, tuple)
    map_selected = Signal(str)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.registry = load_registry(self._data_dir)
        self.setHeaderLabel("Project")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._maps_branch = None
        map_root = None
        for category in self.registry.categories():
            if category.key in locks.DOMAINS and \
                    not locks.balancing_path(category.key, self._data_dir).exists():
                continue  # Phase 4 behavior: no balancing file, no domain node
            if category.key == "deco" and map_root is not None:
                # Deco lives under the "Map" node in the TREE only (user
                # request: browsing/import feel like part of map editing,
                # since deco is placed while painting a map) — the
                # registry category itself is untouched, so its own frame
                # size (64x96, distinct from map tiles' 64x32) still
                # applies; category_key stays "deco" everywhere else
                # (selection.py, DetailsPanel, palette) so nothing else
                # changes.
                root = self._make_item(category.display_name, category.key, ())
                map_root.addChild(root)
                for group in category.groups:
                    self._add_group(root, category.key, group, ())
                continue
            root = self._make_item(category.display_name, category.key, ())
            self.addTopLevelItem(root)
            for group in category.groups:
                self._add_group(root, category.key, group, ())
            if category.key == "map":
                map_root = root
                branch = self._make_item(
                    _MAPS_BRANCH_LABEL, "map", (_MAPS_BRANCH_LABEL,))
                root.insertChild(0, branch)
                self._maps_branch = branch
        self.refresh_maps()
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

    # -- Maps branch (ED-10, Phase 6) ------------------------------------------

    def map_ids(self):
        """Map ids currently listed in the Maps branch, tree order."""
        if self._maps_branch is None:
            return ()
        return tuple(
            self._maps_branch.child(i).data(0, _MAP_ROLE)
            for i in range(self._maps_branch.childCount()))

    def select_map(self, map_id):
        """Programmatic selection of a Maps-branch leaf (tests, post-create)."""
        if self._maps_branch is None:
            raise KeyError("no Maps branch (no map category in the registry)")
        for i in range(self._maps_branch.childCount()):
            item = self._maps_branch.child(i)
            if item.data(0, _MAP_ROLE) == map_id:
                self._maps_branch.parent().setExpanded(True)
                self._maps_branch.setExpanded(True)
                self.setCurrentItem(item)
                return
        raise KeyError(f"no map node {map_id!r}")

    def refresh_maps(self):
        """Rebuild the Maps branch from data/maps/ and re-mark the ACTIVE
        map (●). Call after create / duplicate / set-active. Selection of a
        still-existing map survives the rebuild."""
        if self._maps_branch is None:
            return
        selected = None
        items = self.selectedItems()
        if items:
            selected = items[0].data(0, _MAP_ROLE)
        active = self._active_map_id()
        self.blockSignals(True)
        self._maps_branch.takeChildren()
        for map_id in tilemap.list_map_ids(self._data_dir):
            try:
                label = data_io.load_json(
                    tilemap.map_path(self._data_dir, map_id)
                ).get("display_name") or map_id
            except (OSError, ValueError):
                label = map_id   # unreadable file still gets a node
            item = QTreeWidgetItem(
                [("● " + label) if map_id == active else label])
            item.setData(0, _PAYLOAD_ROLE, ("map", (_MAPS_BRANCH_LABEL, map_id)))
            item.setData(0, _LABEL_ROLE, label)
            item.setData(0, _MAP_ROLE, map_id)
            self._maps_branch.addChild(item)
        self.blockSignals(False)
        if selected is not None and selected in self.map_ids():
            self.select_map(selected)

    def _active_map_id(self):
        path = tilemap.active_map_path(self._data_dir)
        if not path.exists():
            return None   # legal pre-first-set-active state
        return data_io.load_json(path).get("active")

    # -- ● markers (ED-11) -----------------------------------------------------

    def refresh_markers(self):
        """Re-read the manifest (pure loader) and re-mark every node whose
        subtree holds at least one assigned slot. Call after import saves."""
        assigned = set(load_manifest(
            self._data_dir / "sprites" / "asset_manifest.json").slots())
        stack = [self.topLevelItem(i) for i in range(self.topLevelItemCount())]
        while stack:
            item = stack.pop()
            stack.extend(item.child(i) for i in range(item.childCount()))
            category_key, path = item.data(0, _PAYLOAD_ROLE)
            try:
                slots = self.registry.group_slots(category_key, path)
            except KeyError:
                continue   # Maps branch: ● means ACTIVE there (refresh_maps)
            label = item.data(0, _LABEL_ROLE)
            marked = any(slot in assigned for slot in slots)
            item.setText(0, ("● " + label) if marked else label)

    # -- selection broadcast ---------------------------------------------------

    def _emit_selection(self):
        items = self.selectedItems()
        if not items:
            return
        map_id = items[0].data(0, _MAP_ROLE)
        if map_id is not None:
            # map node: tilemap mode + the 1:1 map balancing domain; no
            # node_selected — entity-preview machinery must not react
            self.map_selected.emit(map_id)
            self.domain_selected.emit("map")
            return
        category_key, path = items[0].data(0, _PAYLOAD_ROLE)
        self.node_selected.emit(category_key, tuple(path))
        if category_key in locks.DOMAINS:
            self.domain_selected.emit(category_key)
