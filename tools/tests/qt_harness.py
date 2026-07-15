"""Shared Qt harness for the editor tests: the headless env, the one
QApplication, and the one widget-destruction idiom.

Qt's ``close()`` *hides* a window — it does not destroy it. A ``MainWindow``
left to ``close()`` keeps its ~2,972 child widgets alive for the rest of the
process, and constructing the next one gets slower as they pile up. That is
why the combined suite was quadratic: the 70 modules run *separately* cost
~406s, but a single ``unittest discover`` run cost ~1162s.

``destroy()`` frees the C++ object for real, so widget count returns to zero
between tests and construction time stays flat.

Import this *before* PySide6 — it sets the headless env vars that Qt and SDL
read at import time.
"""
import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import shiboken6  # ships with PySide6
from PySide6.QtWidgets import QApplication

# QApplication is a per-process singleton under Qt.
APP = QApplication.instance() or QApplication(sys.argv)


def destroy(obj) -> None:
    """Close a Qt object and free it.

    Takes any QObject, not just QWidget — RunControls is a bare QObject with
    no close(), so the close step is conditional. Safe to call twice, or on an
    already-dead object (Qt may have reaped it as a child of something
    destroyed first)."""
    if obj is None or not shiboken6.isValid(obj):
        return
    close = getattr(obj, "close", None)
    if callable(close):
        close()
    shiboken6.delete(obj)
    APP.processEvents()  # let Qt actually reap it


def live_widgets() -> int:
    """Widgets currently alive. A leak-free test leaves this where it found
    it; see tools/tests/test_qt_harness.py."""
    return len(APP.allWidgets())


class QtCase(unittest.TestCase):
    """TestCase whose Qt objects die with the test.

    Wrap every widget/QObject you construct in ``self.track(...)``. Cleanups
    run LIFO, so children tracked after their parent are destroyed first.
    """

    def track(self, obj):
        self.addCleanup(destroy, obj)
        return obj
