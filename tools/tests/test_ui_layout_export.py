"""Staleness gate for the committed ``data/ui/screen_defaults.json`` (Phase
10L-B, B3).

``test_committed_defaults_are_fresh`` regenerates the file into a tempdir and
asserts it matches the committed version byte-for-byte — a screen whose
DEFAULT geometry changed without re-running ``tools/export_ui_layouts.py``
fails the suite. ``test_export_is_deterministic`` pins §1.5 directly: two
independent regenerations (no data changes between them) must be
byte-identical to EACH OTHER, not just to the committed file.

Headless: the exporter sets its own SDL dummy drivers before any pygame-pulling
import, so nothing here needs to.
"""
import tempfile
import unittest
from pathlib import Path

from tools.export_ui_layouts import main as export_main

REPO = Path(__file__).resolve().parents[2]


class TestUILayoutExportStaleness(unittest.TestCase):
    def test_committed_defaults_are_fresh(self):
        """Regenerate screen_defaults.json in a tempdir and assert it matches
        the committed version byte-for-byte."""
        live_path = REPO / "data" / "ui" / "screen_defaults.json"
        live_bytes = live_path.read_bytes()

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            export_main(data_root=REPO / "data", output_dir=tmpdir)
            temp_path = tmpdir / "ui" / "screen_defaults.json"
            temp_bytes = temp_path.read_bytes()

        self.assertEqual(
            temp_bytes, live_bytes,
            "committed screen_defaults.json is stale; run "
            "`py tools/export_ui_layouts.py`")

    def test_export_is_deterministic(self):
        """Two independent regenerations (no data changes between them) are
        byte-identical (§1.5) — pinned directly, rather than only via the
        committed file's staleness."""
        with tempfile.TemporaryDirectory() as tmpdir_a, \
                tempfile.TemporaryDirectory() as tmpdir_b:
            tmpdir_a, tmpdir_b = Path(tmpdir_a), Path(tmpdir_b)
            export_main(data_root=REPO / "data", output_dir=tmpdir_a)
            export_main(data_root=REPO / "data", output_dir=tmpdir_b)
            bytes_a = (tmpdir_a / "ui" / "screen_defaults.json").read_bytes()
            bytes_b = (tmpdir_b / "ui" / "screen_defaults.json").read_bytes()

        self.assertEqual(bytes_a, bytes_b)


if __name__ == "__main__":
    unittest.main()
