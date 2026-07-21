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

B4 adds a "Screens" branch (R3) as the FIRST child of the "ui" category,
mirroring the Maps branch exactly: one leaf per data/ui/screens/*.json,
labelled by the filename stem (no display-name lookup — screen docs carry
no such field). Selecting a screen leaf emits screen_selected(screen_id) +
domain_selected("ui") — never node_selected, so entity-preview machinery
stays untouched (the _MAP_ROLE branch's exact pattern, applied to
_SCREEN_ROLE).

Balancing domains are DERIVED, never hardcoded (AD-6): `domains.domains()`
is slots.json's category order ∩ the categories carrying a
data/balancing/<key>.json, cached here as `self._domains` (re-derived on
reload_registry) because _emit_selection consults it on every click. A
category is *intended* as a domain iff it has a data/schemas/<key>.schema.json
(`domains.is_domain_category`) — an intended domain with no balancing file is
omitted from the tree WHOLE, which is what keeps "no balancing file, no
domain node" expressible now that the domain list is derived from those very
files.

AD-6 context menu: right-clicking a CATEGORY root (payload path == ()) pops
an "Add New X…" entry per form spec whose `selector_context` is that
category; right-clicking empty space offers "Add New Category…". Triggering
one emits add_requested(form_id); the shell opens the AgentFormDialog. Specs
are re-read on every menu open, so a newly written spec needs no restart.

Plain Qt widget; imports only the PURE half of engine.assets (registry +
manifest metadata — no pygame) and engine.tilemap. Exactly one node
selected at a time (ED-3); selection is broadcast as
node_selected(category, group_path) always, plus domain_selected(str)
when the category is a balancing domain — the Phase 4 contract the
balancing panel still hangs off, now fired at any depth so clicking a
building type also shows the buildings form.
"""
import sys
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)

from editor import agent_forms, domains
from engine import data_io, tilemap
from engine.assets import load_manifest, load_registry

REPO = Path(__file__).resolve().parents[2]

_PAYLOAD_ROLE = Qt.ItemDataRole.UserRole        # (category_key, group_path)
_LABEL_ROLE = Qt.ItemDataRole.UserRole + 1      # clean label, no ● prefix
_MAP_ROLE = Qt.ItemDataRole.UserRole + 2        # map_id (Maps-branch leaves)
_SCREEN_ROLE = Qt.ItemDataRole.UserRole + 3     # screen_id (Screens-branch leaves)

_MAPS_BRANCH_LABEL = "Maps"
_SCREENS_BRANCH_LABEL = "Screens"

# Registry categories shown as CHILDREN of the "map" node instead of their own
# top-level node — a tree-shape choice only (see the branch in __init__).
_NESTED_UNDER_MAP = ("deco", "conditions")

# The one form reachable from EMPTY tree space: it creates a category, so it
# belongs to no category node and carries no selector_context.
_ADD_CATEGORY_FORM_ID = "add-category"


class SelectorPanel(QTreeWidget):
    domain_selected = Signal(str)
    node_selected = Signal(str, tuple)
    map_selected = Signal(str)
    screen_selected = Signal(str)    # B4: a Screens-branch leaf was selected
    add_requested = Signal(str)      # form spec id (AD-6 context menu)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.registry = load_registry(self._data_dir)
        # reuse the registry we just loaded — domains.domains() would otherwise
        # re-parse AND re-validate slots.json
        self._domains = domains.domains(self._data_dir, self.registry)
        self.setHeaderLabel("Project")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._maps_branch = None
        self._screens_branch = None
        map_root = None
        for category in self.registry.categories():
            if domains.is_domain_category(category.key, self._data_dir) and \
                    not domains.balancing_path(category.key, self._data_dir).exists():
                # Intended as a domain (it has a schema) but its balancing file
                # is gone: omit the node WHOLE rather than degrade it to an
                # asset-only category — every leaf under a domain emits
                # domain_selected, which would drive the balancing panel into a
                # missing file (Phase 4 behavior, preserved).
                continue
            if category.key in _NESTED_UNDER_MAP and map_root is not None:
                # Deco and Tile Conditions live under the "Map" node in the
                # TREE only (user request: browsing/import feel like part of
                # map editing — deco is placed while painting a map, and
                # conditions are terrain) — the registry categories
                # themselves are untouched, so their own frame size (64x96,
                # distinct from map tiles' 64x32) still applies; category_key
                # stays "deco"/"conditions" everywhere else (selection.py,
                # DetailsPanel, palette) so nothing else changes.
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
            elif category.key == "ui":
                branch = self._make_item(
                    _SCREENS_BRANCH_LABEL, "ui", (_SCREENS_BRANCH_LABEL,))
                root.insertChild(0, branch)
                self._screens_branch = branch
        self.refresh_maps()
        self.refresh_screens()
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
            if key in self._domains:
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

    # -- Screens branch (R3, Phase B4) ------------------------------------------

    def _screen_ids_from_disk(self):
        d = self._data_dir / "ui" / "screens"
        if not d.exists():
            return ()
        return tuple(sorted(p.stem for p in d.glob("*.json")))

    def screen_ids(self):
        """Screen ids currently listed in the Screens branch, tree order."""
        if self._screens_branch is None:
            return ()
        return tuple(
            self._screens_branch.child(i).data(0, _SCREEN_ROLE)
            for i in range(self._screens_branch.childCount()))

    def select_screen(self, screen_id):
        """Programmatic selection of a Screens-branch leaf (tests, main.py's
        cancelled-dirty-prompt path)."""
        if self._screens_branch is None:
            raise KeyError("no Screens branch (no ui category in the registry)")
        for i in range(self._screens_branch.childCount()):
            item = self._screens_branch.child(i)
            if item.data(0, _SCREEN_ROLE) == screen_id:
                self._screens_branch.parent().setExpanded(True)
                self._screens_branch.setExpanded(True)
                self.setCurrentItem(item)
                return
        raise KeyError(f"no screen node {screen_id!r}")

    def refresh_screens(self):
        """Rebuild the Screens branch from data/ui/screens/ (call after B3's
        exporter runs — the file SET is static today, but a re-run is cheap
        and this keeps the branch honest if it ever isn't). Selection of a
        still-existing screen survives the rebuild (mirrors refresh_maps)."""
        if self._screens_branch is None:
            return
        selected = None
        items = self.selectedItems()
        if items:
            selected = items[0].data(0, _SCREEN_ROLE)
        self.blockSignals(True)
        self._screens_branch.takeChildren()
        for screen_id in self._screen_ids_from_disk():
            item = QTreeWidgetItem([screen_id])
            item.setData(0, _PAYLOAD_ROLE,
                        ("ui", (_SCREENS_BRANCH_LABEL, screen_id)))
            item.setData(0, _LABEL_ROLE, screen_id)
            item.setData(0, _SCREEN_ROLE, screen_id)
            self._screens_branch.addChild(item)
        self.blockSignals(False)
        if selected is not None and selected in self.screen_ids():
            self.select_screen(selected)

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

    def reload_registry(self):
        """Re-read data/slots.json after a registry edit (a new enemy variant).
        The tree STOPS above variant slots, so its shape is unchanged — only
        the cached registry the shell reads for level resolution is refreshed.
        The derived domain list is refreshed too: a registry edit can add a
        category, and a new category can be a balancing domain."""
        self.registry = load_registry(self._data_dir)
        self._domains = domains.domains(self._data_dir, self.registry)

    # -- selection broadcast ---------------------------------------------------

    def _emit_selection(self):
        items = self.selectedItems()
        if not items:
            return
        screen_id = items[0].data(0, _SCREEN_ROLE)
        if screen_id is not None:
            # screen node: screen mode + the "ui" balancing domain; no
            # node_selected — entity-preview machinery must not react
            # (exact _MAP_ROLE pattern above, applied to screens)
            self.screen_selected.emit(screen_id)
            if "ui" in self._domains:
                self.domain_selected.emit("ui")
            return
        map_id = items[0].data(0, _MAP_ROLE)
        if map_id is not None:
            # map node: tilemap mode + the 1:1 map balancing domain; no
            # node_selected — entity-preview machinery must not react
            self.map_selected.emit(map_id)
            # GATED like every other domain_selected: with neither
            # balancing/map.json nor schemas/map.schema.json on disk, "map" is
            # an asset-only category — the node is shown, but emitting here
            # would drive BalancingPanel.set_domain into a missing file
            # (FileNotFoundError out of a Qt slot).
            if "map" in self._domains:
                self.domain_selected.emit("map")
            return
        category_key, path = items[0].data(0, _PAYLOAD_ROLE)
        self.node_selected.emit(category_key, tuple(path))
        if category_key in self._domains:
            self.domain_selected.emit(category_key)

    # -- "Add new X…" context menu (AD-6) --------------------------------------

    def _add_entries(self, category_key):
        """[(label, form_id)] offered for a node. category_key=None → the
        empty-space menu (Add New Category). Specs are read FRESH so a spec an
        agent just wrote is offered without an editor restart; a broken spec
        must never kill a right-click, so load failures degrade to no menu."""
        try:
            specs = agent_forms.load_form_specs(self._data_dir)
        except Exception as exc:   # noqa: BLE001 - a bad spec must not raise
            print(f"selector: could not load form specs: {exc}", file=sys.stderr)
            return []
        if category_key is None:
            specs = [s for s in specs if s["id"] == _ADD_CATEGORY_FORM_ID]
        else:
            specs = [s for s in specs
                     if s.get("selector_context") == category_key]
        return [(f"{spec['title']}…", spec["id"]) for spec in specs]

    def _context_menu(self, item):
        """The QMenu for a right-clicked item (None = empty space), or None
        when nothing is on offer — never shows an empty popup, and never
        exec()s (the caller does), so tests can drive it headlessly."""
        if item is None:
            category_key = None
        else:
            category_key, path = item.data(0, _PAYLOAD_ROLE)
            if tuple(path) != ():
                return None   # only a category ROOT offers "Add new X…"
        entries = self._add_entries(category_key)
        if not entries:
            return None
        menu = QMenu(self)   # parented: dies with the panel
        for label, form_id in entries:
            action = QAction(label, menu)
            # bind form_id per action (late-binding closures) and absorb
            # triggered(checked: bool)
            action.triggered.connect(
                lambda _checked=False, fid=form_id: self.add_requested.emit(fid))
            menu.addAction(action)
        return menu

    def contextMenuEvent(self, event):
        menu = self._context_menu(self.itemAt(event.pos()))
        if menu is not None:
            menu.exec(event.globalPos())
