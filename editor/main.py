"""How To Be Human editor — Qt shell (ED-1). Phase 5 scope: selector +
viewport + balancing + details (asset import), selection-driven.

    py editor/main.py

Layout (user-confirmed Phase 5 shape): selector tree (left) | viewport over
[level bar + balancing form] (center) | Details panel (right), in plain
QSplitters — full docking + .editor_prefs.json persistence is ED-1's
eventual shape and lands later.

Selection is composite (ED-3 stays: ONE tree node drives everything, the
dropdown/level bar refine it): the tree selects a category/group node,
which maps 1:1 to a balancing domain where one exists (vfx/deco keep the
last domain); the Details dropdown picks the subcategory (tier) and the
level bar the level; editor.selection resolves the trio to a slot key that
drives the viewport's entity preview and the import context. Import-panel
edits preview live as viewport drafts; a save reloads the viewport's assets
and refreshes the ● markers without a restart (ED-42).

main(max_frames=None) lets the window be driven headlessly under
QT_QPA_PLATFORM=offscreen (mirrors game/main.py's max_frames convention
for tools/smoke.py). Frames are driven by a QTimer — no busy-spin.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from editor import selection
from editor.panels.balancing import BalancingPanel
from editor.panels.details import DetailsPanel
from editor.panels.level_bar import LevelBar
from editor.panels.selector import SelectorPanel
from editor.panels.viewport import ViewportPanel

FRAME_INTERVAL_MS = 16  # ~60fps tick, timer-driven (no busy-spin)


class MainWindow(QMainWindow):
    def __init__(self, max_frames=None, data_dir=None):
        super().__init__()
        self.setWindowTitle("How To Be Human — editor")
        self.resize(1280, 720)

        self.viewport = ViewportPanel(data_dir=data_dir)
        self.selector = SelectorPanel(data_dir=data_dir)
        self.balancing = BalancingPanel(data_dir=data_dir)
        self.details = DetailsPanel(data_dir=data_dir)
        self.levelbar = LevelBar()
        self._node = None   # (category_key, group_path) of the tree selection

        self.selector.domain_selected.connect(self.balancing.set_domain)
        self.selector.node_selected.connect(self._on_node_selected)
        self.details.subcategory_changed.connect(self._on_subcategory_changed)
        self.levelbar.level_changed.connect(self._on_level_changed)
        self.details.draft_changed.connect(self.viewport.set_preview_draft)
        self.details.entry_saved.connect(self._on_manifest_changed)
        self.details.entry_cleared.connect(self._on_manifest_changed)

        bottom = QWidget()
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.levelbar)
        bottom_layout.addWidget(self.balancing, 1)

        center = QSplitter(Qt.Orientation.Vertical)
        center.addWidget(self.viewport)
        center.addWidget(bottom)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.selector)
        split.addWidget(center)
        split.addWidget(self.details)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setStretchFactor(2, 0)
        split.setSizes([220, 760, 300])
        self.setCentralWidget(split)

        domains = self.selector.domains()
        if domains:
            self.selector.select_domain(domains[0])

        self._max_frames = max_frames
        self.frames = 0
        self._fps_window = 0
        self._fps_elapsed = 0.0
        self._last_tick = time.perf_counter()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_INTERVAL_MS)

    # -- composite slot selection (tree node × subcategory × level) ---------

    def _on_node_selected(self, category_key, group_path):
        self._node = (category_key, tuple(group_path))
        self.details.set_context(category_key, group_path)
        self._refresh_levels()

    def _on_subcategory_changed(self, _index):
        self._refresh_levels()

    def _on_level_changed(self, _index):
        self._apply_slot()

    def _refresh_levels(self):
        category_key, group_path = self._node
        slots = selection.level_slots(
            self.selector.registry, category_key, group_path,
            self.details.subcategory_index())
        assigned = set(self.viewport.assigned_slots())
        self.levelbar.set_levels(slots, assigned)
        self._apply_slot()

    def _apply_slot(self):
        category_key, group_path = self._node
        slot = selection.resolve_slot(
            self.selector.registry, category_key, group_path,
            self.details.subcategory_index(), self.levelbar.level())
        self.viewport.set_preview_slot(slot)
        self.details.set_slot(slot)

    def _on_manifest_changed(self, _slot_key):
        """Import-panel save/clear: assets reload without a restart (ED-42)
        and the tree's ● markers follow (ED-11)."""
        self.viewport.reload_assets()
        self.selector.refresh_markers()

    # -- frame drive ---------------------------------------------------------

    def _tick(self):
        now = time.perf_counter()
        dt = now - self._last_tick
        self._last_tick = now

        self.viewport.render_frame()
        self.frames += 1
        self._fps_window += 1
        self._fps_elapsed += dt

        if self._fps_elapsed >= 1.0:
            fps = self._fps_window / self._fps_elapsed
            cost_ms = self.viewport.last_frame_ms
            self.setWindowTitle(
                f"How To Be Human — editor — {fps:.1f} fps ({cost_ms:.2f} ms/frame)"
            )
            print(f"editor fps: {fps:.1f}  frame_cost_ms: {cost_ms:.2f}")
            self._fps_window = 0
            self._fps_elapsed = 0.0

        if self._max_frames is not None and self.frames >= self._max_frames:
            QApplication.instance().quit()


def main(max_frames=None):
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(max_frames=max_frames)
    window.show()
    app.exec()
    return window.frames


if __name__ == "__main__":
    main()
