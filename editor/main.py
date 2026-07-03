"""How To Be Human editor — Qt shell (ED-1). Phase 4 scope: selector +
viewport + balancing, selection-driven.

    py editor/main.py

Layout: selector tree (left) | viewport (center) over balancing form
(bottom), in plain QSplitters — full docking + .editor_prefs.json
persistence is ED-1's eventual shape and lands later. Selecting a domain
in the selector drives the balancing panel (ED-3). The viewport keeps
showing the Phase 3 grey-X grid regardless of selection — mode switching
(tilemap editor / entity preview) needs the Phase 5 slot registry and
Phase 6 map format.

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
from PySide6.QtWidgets import QApplication, QMainWindow, QSplitter

from editor.panels.balancing import BalancingPanel
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
        self.selector.domain_selected.connect(self.balancing.set_domain)

        center = QSplitter(Qt.Orientation.Vertical)
        center.addWidget(self.viewport)
        center.addWidget(self.balancing)
        center.setStretchFactor(0, 3)
        center.setStretchFactor(1, 1)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.selector)
        split.addWidget(center)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([220, 1060])
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
