"""SelectorPanel (ED-3, ED-10 subset) — the tree the whole editor hangs off.

Phase 4 scope: a flat list of the balancing domains that have a file in
data/balancing/, in canonical D-10 order. The Maps node, the Buildings
type->tier->level subtree, and the ● assigned-asset markers need the
Phase 5 slot registry / Phase 6 map format and are deliberately absent.

Plain Qt widget (no engine/render involvement — ED-22 concerns the
viewport only). Exactly one node can be selected (ED-3); the selection is
broadcast as domain_selected(str) and is the panel's ONLY coupling to the
rest of the shell.
"""
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget, QTreeWidgetItem

from editor import locks

REPO = Path(__file__).resolve().parents[2]

DISPLAY_NAMES = {
    "buildings": "Buildings",
    "enemies": "Enemies",
    "map": "Map",
    "ui": "UI",
    "core": "Core",
}


class SelectorPanel(QTreeWidget):
    domain_selected = Signal(str)

    def __init__(self, data_dir=None, parent=None):
        super().__init__(parent)
        self._data_dir = Path(data_dir) if data_dir is not None else REPO / "data"
        self.setHeaderLabel("Domains")
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        for domain in locks.DOMAINS:
            if locks.balancing_path(domain, self._data_dir).exists():
                item = QTreeWidgetItem([DISPLAY_NAMES[domain]])
                item.setData(0, Qt.ItemDataRole.UserRole, domain)
                self.addTopLevelItem(item)
        self.itemSelectionChanged.connect(self._emit_selection)

    def domains(self):
        """Domain keys currently listed, in tree order."""
        return tuple(
            self.topLevelItem(i).data(0, Qt.ItemDataRole.UserRole)
            for i in range(self.topLevelItemCount())
        )

    def select_domain(self, domain):
        """Programmatic selection (initial selection, tests)."""
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == domain:
                self.setCurrentItem(item)
                return
        raise KeyError(f"no domain node {domain!r}")

    def _emit_selection(self):
        items = self.selectedItems()
        if items:
            self.domain_selected.emit(items[0].data(0, Qt.ItemDataRole.UserRole))
