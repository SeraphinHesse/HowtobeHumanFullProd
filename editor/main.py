"""How To Be Human editor — Qt shell (ED-1). Phase 3 scope: viewport spike
only.

    py editor/main.py

Proves the engine's render surface can live inside a PySide6 window at
60fps (Phase 3, PLAN §7 — the riskiest integration, done early on purpose).
No docking layout, no panels beyond the viewport, no selector, no data
editing — those land in Phase 4+.

main(max_frames=None) lets the window be driven headlessly under
QT_QPA_PLATFORM=offscreen (mirrors game/main.py's max_frames convention for
tools/smoke.py). Frames are driven by a QTimer — no busy-spin.
"""
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from editor.panels.viewport import ViewportPanel

FRAME_INTERVAL_MS = 16  # ~60fps tick, timer-driven (no busy-spin)


class MainWindow(QMainWindow):
    def __init__(self, max_frames=None):
        super().__init__()
        self.setWindowTitle("How To Be Human — editor")
        self.resize(1280, 720)
        self.viewport = ViewportPanel()
        self.setCentralWidget(self.viewport)

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
