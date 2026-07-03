"""Phase 4 acceptance tests: selector + balancing panels + locks
(ED-3, ED-30/31/32).

Same headless conventions as test_editor_viewport.py: QT_QPA_PLATFORM=
offscreen + SDL dummy drivers before any Qt/pygame import, one
QApplication per process. Every test runs against a tempfile COPY of
data/ so panel writes never touch the repo's files — which is why all
editor modules take a data_dir parameter.
"""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QSpinBox,
)

from editor import locks
from editor.panels.balancing import BalancingPanel
from editor.panels.selector import SelectorPanel
from engine import data_io

REPO = Path(__file__).resolve().parents[2]

_APP = QApplication.instance() or QApplication(sys.argv)


def read_domain(data_dir, domain):
    return data_io.load_validated(
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


def lock_domain(data_dir, domain, owner_name="featureBuildings"):
    """Simulate /start-domain by another owner (through the validating
    writer — tests obey D-2 too)."""
    doc = read_domain(data_dir, domain)
    doc["_lock"] = {"locked_by": owner_name, "since": "2026-07-03"}
    data_io.write_validated(
        doc,
        data_dir / "balancing" / f"{domain}.json",
        data_dir / "schemas" / f"{domain}.schema.json",
    )


class TempDataCase(unittest.TestCase):
    """Copies data/ into a temp dir so writes never touch the repo."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        shutil.copytree(REPO / "data", self.data_dir)


class TestLocks(TempDataCase):
    def test_unlocked_domain(self):
        self.assertFalse(locks.is_locked("buildings", self.data_dir))
        self.assertIsNone(locks.owner("buildings", self.data_dir))

    def test_locked_domain(self):
        lock_domain(self.data_dir, "enemies", "featureEnemies")
        self.assertTrue(locks.is_locked("enemies", self.data_dir))
        self.assertEqual(locks.owner("enemies", self.data_dir), "featureEnemies")

    def test_no_force_unlock_api(self):
        """ED-32/T-1: the editor exposes no way to set or clear a lock."""
        for name in dir(locks):
            self.assertNotIn("unlock", name.lower())
            self.assertNotIn("release", name.lower())


class TestSelector(TempDataCase):
    def test_lists_domains_in_d10_order(self):
        panel = SelectorPanel(data_dir=self.data_dir)
        self.assertEqual(panel.domains(), locks.DOMAINS)

    def test_domain_without_file_is_omitted(self):
        (self.data_dir / "balancing" / "map.json").unlink()
        panel = SelectorPanel(data_dir=self.data_dir)
        self.assertEqual(panel.domains(), tuple(d for d in locks.DOMAINS if d != "map"))

    def test_selection_emits_domain_and_is_single(self):
        panel = SelectorPanel(data_dir=self.data_dir)
        seen = []
        panel.domain_selected.connect(seen.append)
        panel.select_domain("enemies")
        panel.select_domain("core")
        self.assertEqual(seen, ["enemies", "core"])
        self.assertEqual(len(panel.selectedItems()), 1)  # ED-3


class TestBalancingPanel(TempDataCase):
    def make_panel(self, domain):
        panel = BalancingPanel(data_dir=self.data_dir)
        panel.set_domain(domain)
        return panel

    def test_widgets_generated_from_schema(self):
        """ED-30: int -> spinbox, number -> double spinbox, enum -> combo,
        bool -> checkbox; _lock never appears as a field."""
        panel = self.make_panel("core")
        self.assertIsInstance(panel._widgets["base_hp"], QSpinBox)
        self.assertIsInstance(panel._widgets["combat_speed_default"], QComboBox)
        panel = self.make_panel("ui")
        self.assertIsInstance(panel._widgets["hud_scale"], QDoubleSpinBox)
        self.assertIsInstance(panel._widgets["show_fps"], QCheckBox)
        self.assertNotIn("_lock", panel._widgets)

    def test_selection_switches_panel_content(self):
        """ED-3: the selected tree node drives the form's content."""
        selector = SelectorPanel(data_dir=self.data_dir)
        panel = BalancingPanel(data_dir=self.data_dir)
        selector.domain_selected.connect(panel.set_domain)
        selector.select_domain("buildings")
        self.assertEqual(
            set(panel._widgets), {"cost_multiplier", "sell_refund_fraction"}
        )
        selector.select_domain("enemies")
        self.assertEqual(set(panel._widgets), {"hp_multiplier", "speed_multiplier"})

    def test_edit_writes_validated_canonical_file(self):
        """ED-31: widget change -> write_validated -> canonical JSON on disk."""
        panel = self.make_panel("buildings")
        panel._widgets["cost_multiplier"].setValue(2.5)
        on_disk = read_domain(self.data_dir, "buildings")
        self.assertEqual(on_disk["cost_multiplier"], 2.5)
        path = self.data_dir / "balancing" / "buildings.json"
        text = path.read_text(encoding="utf-8")
        self.assertEqual(text, data_io.dumps_deterministic(on_disk))

    def test_out_of_range_input_unrepresentable(self):
        """ED-30: the widget clamps to the schema's bounds — invalid values
        cannot even be entered, let alone written."""
        panel = self.make_panel("buildings")
        widget = panel._widgets["cost_multiplier"]
        widget.setValue(999.0)
        self.assertEqual(widget.value(), 10.0)  # schema maximum
        self.assertEqual(read_domain(self.data_dir, "buildings")["cost_multiplier"], 10.0)

    def test_checkbox_and_enum_write_typed_values(self):
        panel = self.make_panel("ui")
        panel._widgets["show_fps"].setChecked(True)
        self.assertIs(read_domain(self.data_dir, "ui")["show_fps"], True)

        panel = self.make_panel("core")
        combo = panel._widgets["combat_speed_default"]
        combo.setCurrentIndex(combo.findData(4))
        self.assertEqual(read_domain(self.data_dir, "core")["combat_speed_default"], 4)

    def test_locked_domain_readonly_with_owner_shown(self):
        """ED-32: locked -> every field disabled + owner in the banner."""
        lock_domain(self.data_dir, "buildings", "featureBuildings")
        panel = self.make_panel("buildings")
        for key, widget in panel._widgets.items():
            self.assertFalse(widget.isEnabled(), msg=key)
        self.assertIn("featureBuildings", panel._banner.text())
        self.assertFalse(panel._banner.isHidden())

    def test_unlocked_domain_editable_no_banner(self):
        panel = self.make_panel("buildings")
        for key, widget in panel._widgets.items():
            self.assertTrue(widget.isEnabled(), msg=key)
        self.assertTrue(panel._banner.isHidden())


class TestMainWindowWiring(TempDataCase):
    """End-to-end: shell wires selector -> balancing, initial selection set."""

    def test_select_and_edit_through_the_shell(self):
        from editor.main import MainWindow

        window = MainWindow(data_dir=self.data_dir)
        self.addCleanup(window.close)
        window._timer.stop()  # no frame drive needed here

        self.assertEqual(window.balancing.domain, locks.DOMAINS[0])
        window.selector.select_domain("ui")
        self.assertEqual(window.balancing.domain, "ui")
        window.balancing._widgets["hud_scale"].setValue(1.5)
        self.assertEqual(read_domain(self.data_dir, "ui")["hud_scale"], 1.5)


if __name__ == "__main__":
    unittest.main()
