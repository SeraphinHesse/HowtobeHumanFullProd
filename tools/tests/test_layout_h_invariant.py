"""Invariant: layout math must never read a live font measurement (Fix 1,
phase-10L wave3 bake-ui-assets).

CI runs Linux, dev runs Windows; ``pygame.font.SysFont(...).size()`` measures
glyph heights ±1px differently per platform. Six ``game/ui`` call sites (plus
every skinned ``widgets.Button`` label) used to derive LAYOUT POSITIONS —
stored holder rects, id'd anchors, the ``test_ui_skinning.py`` golden parity
stream, ``data/ui/screen_defaults.json`` — straight from
``engine.render.fonts.TextMetrics.size()``, so those committed artifacts
(captured on Windows) diverged from what Linux CI regenerated. The fix routes
every such call through ``engine.render.fonts.layout_h`` instead, a PINNED
constant table (see that module's docstring).

This module pins the rule forever: even if the live font measurement drifts
by +1px (simulated here via a monkeypatch — stands in for the cross-platform
±1px difference without needing a second OS), both the golden parity stream
AND the exporter's ``screen_defaults.json`` output must stay byte-identical.
If either changes, a call site regressed back to a live measurement.
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from engine.render.fonts import TextMetrics
from tools.export_ui_layouts import main as export_main
from tools.tests.test_ui_skinning import _BASELINE, _screen_captures

REPO = Path(__file__).resolve().parents[2]


_ORIGINAL_SIZE = TextMetrics.size


def _patched_size(self, text, font_key, family=None):
    """Stands in for a platform whose font backend measures 1px taller —
    only the height (index 1) moves, so word-wrap line counts (which read
    only the width) stay unaffected and this isolates the height invariant.

    Takes `family` (UH-Font-B) because the real `TextMetrics.size` does: a
    stand-in that drops the second font axis stops being a drop-in the
    moment any draw path passes one."""
    w, h = _ORIGINAL_SIZE(self, text, font_key, family)
    return (w, h + 1)


class TestLayoutHInvariant(unittest.TestCase):
    """Monkeypatches the underlying font measurement +1px and asserts every
    layout-derived, captured artifact is unaffected."""

    def test_golden_parity_stream_unaffected_by_live_measurement_drift(self):
        unpatched = _screen_captures()
        with mock.patch.object(TextMetrics, "size", _patched_size):
            patched = _screen_captures()
        self.assertEqual(patched, unpatched)
        # Tie directly to the pinned baseline too — not just self-consistency.
        for screen_id, items in patched.items():
            self.assertEqual(items, _BASELINE[screen_id],
                             f"{screen_id} drifted under a +1px font patch")

    def test_exporter_output_unaffected_by_live_measurement_drift(self):
        with tempfile.TemporaryDirectory() as tmpdir_a, \
                tempfile.TemporaryDirectory() as tmpdir_b:
            tmpdir_a, tmpdir_b = Path(tmpdir_a), Path(tmpdir_b)
            export_main(data_root=REPO / "data", output_dir=tmpdir_a)
            with mock.patch.object(TextMetrics, "size", _patched_size):
                export_main(data_root=REPO / "data", output_dir=tmpdir_b)
            bytes_a = (tmpdir_a / "ui" / "screen_defaults.json").read_bytes()
            bytes_b = (tmpdir_b / "ui" / "screen_defaults.json").read_bytes()
        self.assertEqual(bytes_a, bytes_b)


if __name__ == "__main__":
    unittest.main()
