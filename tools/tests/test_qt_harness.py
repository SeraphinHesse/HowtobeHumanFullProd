"""Guards the fix that made the suite linear again (TestGatePLAN TG-1).

The bug this locks down: ``close()`` hides a Qt window, it does not destroy
it. Every MainWindow the editor tests built with a bare ``addCleanup(w.close)``
leaked its whole widget tree, and each new MainWindow got slower to build —
so the combined suite was quadratic in the number of editor tests.

If someone reintroduces the bare-``close()`` idiom, the leak comes back
silently and the suite just gets slow again. That is exactly the failure mode
this repo has already been bitten by, so it gets a test rather than a comment.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.tests.qt_harness import APP, QtCase, destroy, live_widgets
from tools.tests.temp_data import TempDataCase

import shiboken6
from PySide6.QtCore import QObject
from PySide6.QtWidgets import QWidget

REPO = Path(__file__).resolve().parents[2]


class TestDestroy(unittest.TestCase):
    def test_destroy_frees_the_widget_and_its_children(self):
        before = live_widgets()
        parent = QWidget()
        for _ in range(5):
            QWidget(parent)
        self.assertGreaterEqual(live_widgets(), before + 6)

        destroy(parent)
        self.assertEqual(live_widgets(), before)

    def test_destroy_is_idempotent_and_tolerates_none(self):
        widget = QWidget()
        destroy(widget)
        destroy(widget)  # already dead — must not raise
        destroy(None)

    def test_destroy_accepts_a_plain_qobject(self):
        """Not everything tracked is a widget: RunControls is a bare QObject
        with no close(). destroy() must not assume the widget API."""
        obj = QObject()
        destroy(obj)
        self.assertFalse(shiboken6.isValid(obj))

    def test_close_alone_does_not_free(self):
        """The bug, pinned. If this ever fails, Qt changed and destroy() can
        be simplified."""
        before = live_widgets()
        widget = QWidget()
        widget.close()
        APP.processEvents()
        self.assertEqual(live_widgets(), before + 1)  # still alive!
        destroy(widget)
        self.assertEqual(live_widgets(), before)


class TestNoLeakAcrossTests(TempDataCase):
    """A tracked MainWindow leaves no widgets behind — run repeatedly, the
    count must not climb. This is the quadratic, caught in miniature.

    Uses TempDataCase rather than its own copytree: this module's job is to
    exercise the copy machinery, so it should be driving the real thing."""

    def test_repeated_mainwindow_construction_does_not_accumulate(self):
        from editor.main import MainWindow

        baseline = live_widgets()
        counts = []
        for _ in range(3):
            window = MainWindow(data_dir=self.data_dir)
            destroy(window)
            counts.append(live_widgets())

        self.assertEqual(
            counts,
            [baseline] * 3,
            f"MainWindow leaked widgets: {baseline} -> {counts}",
        )
