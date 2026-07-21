"""VfxPreviewPanel (ESV-4) — headless.

Same conventions as test_editor_panels.py: offscreen Qt + SDL dummy env, one
QApplication, TempDataCase tempfile copy of data/. Tests assert the PARAMS
handed to the emitter, never pixels (phase-esv-4-vfx-preview.md §2.6) — a
pixel assertion would pin the renderer, not this panel.
"""
import copy
import unittest
from unittest.mock import patch

# Sets the headless env vars and owns the one QApplication — import it before
# PySide6, which reads those vars at import time.
from tools.tests.qt_harness import APP as _APP, QtCase

from PySide6.QtGui import QColor

from editor.panels import vfx_preview
from editor.panels.balancing import BalancingPanel
from editor.panels.vfx_preview import VfxPreviewPanel
from engine import data_io
from tools.tests.test_editor_panels import TempDataCase, read_domain


class _SpyVfxSystem:
    """Records the params `VfxPreviewPanel._emit()` builds + which emit_*
    call it made, without touching the real emitter — so a test can assert
    "the panel constructed THESE params" without ever rendering a pixel."""

    instances = []

    def __init__(self, params, *, rng):
        self.params = params
        self.rng = rng
        self.calls = []
        _SpyVfxSystem.instances.append(self)

    def emit_burst(self, kind_params, wx, wy):
        self.calls.append(("emit_burst", kind_params, wx, wy))

    def emit_shards(self, wx, wy):
        self.calls.append(("emit_shards", wx, wy))

    def emit_muzzle(self, wx, wy, strong=False):
        self.calls.append(("emit_muzzle", wx, wy, strong))

    def emit_slash(self, wx, wy, large=False):
        self.calls.append(("emit_slash", wx, wy, large))

    def emit_gold(self, col, row):
        self.calls.append(("emit_gold", col, row))

    def add_splatters(self, points):
        self.calls.append(("add_splatters", points))

    def update(self, dt):
        pass

    def submit_splatters(self, renderer, cs):
        pass

    def submit_gold_highlights(self, renderer):
        pass

    def submit_hud(self, renderer, cs):
        pass


class VfxPreviewCase(TempDataCase):
    """A wired-up BalancingPanel (domain "vfx") + VfxPreviewPanel pair, the
    same two-panel setup `editor/main.py`'s ESV-4 wiring block builds."""

    def make_pair(self):
        balancing = self.track(BalancingPanel(data_dir=self.data_dir))
        balancing.set_domain("vfx")
        preview = self.track(VfxPreviewPanel(data_dir=self.data_dir))
        preview.set_balancing_panel(balancing)
        balancing.value_staged.connect(preview.on_balancing_value_staged)
        return balancing, preview


class TestLeverStagingAndSave(VfxPreviewCase):
    def test_lever_and_ramp_edit_stage_and_save_pins_exact_diff(self):
        """A lever edit + a ramp colour pick each stage into the ONE
        BalancingPanel doc, mirror into the generic form's own widgets, and
        Save writes a vfx.json that differs from the baseline in exactly
        those two leaves (§4 test 1 — the "we didn't restructure ESV-3b's
        file" pin)."""
        balancing, preview = self.make_pair()
        preview._family_combo.setCurrentText("muzzle")
        baseline = read_domain(self.data_dir, "vfx")

        count_widget = preview._lever_widgets["procedural/muzzle/count"]
        new_count = count_widget.value() + 5
        count_widget.setValue(new_count)

        stop0_path = "procedural/muzzle/ramp/stop_0"
        button = preview._color_buttons[stop0_path]
        with patch.object(vfx_preview.QColorDialog, "getColor",
                           return_value=QColor(10, 20, 30)):
            preview._on_color_clicked(stop0_path, button)

        self.assertTrue(balancing._save_btn.isEnabled())
        # the twin row in the generic form shows the same staged values
        self.assertEqual(
            balancing._widgets["procedural/muzzle/count"].value(), new_count)
        self.assertEqual(
            [balancing._widgets[f"{stop0_path}/{i}"].value() for i in range(3)],
            [10, 20, 30])

        balancing.save_changes("esv-4 preview test")

        on_disk = read_domain(self.data_dir, "vfx")
        expected = copy.deepcopy(baseline)
        expected["procedural"]["muzzle"]["count"] = new_count
        expected["procedural"]["muzzle"]["ramp"]["stop_0"] = [10, 20, 30]
        self.assertEqual(on_disk, expected)

        # re-validates cleanly against the schema (Save already calls
        # write_validated; this just re-confirms the on-disk file round-trips)
        data_io.load_validated(
            self.data_dir / "balancing" / "vfx.json",
            self.data_dir / "schemas" / "vfx.schema.json")


class TestEmitParams(VfxPreviewCase):
    """§4 test 2: the preview requests the engine emitter with the EDITED
    params — a spy over VfxSystem, never a pixel assertion."""

    def setUp(self):
        super().setUp()
        _SpyVfxSystem.instances = []

    def test_muzzle_emit_carries_edited_params(self):
        balancing, preview = self.make_pair()
        preview._family_combo.setCurrentText("muzzle")

        with patch.object(vfx_preview, "VfxSystem", _SpyVfxSystem):
            preview._lever_widgets["procedural/muzzle/count"].setValue(99)
            preview._lever_widgets["procedural/muzzle/life"].setValue(1.5)

            spy = _SpyVfxSystem.instances[-1]
            self.assertEqual(spy.params.muzzle.count, 99)
            self.assertEqual(spy.params.muzzle.life, 1.5)
            self.assertEqual(spy.calls[-1][0], "emit_muzzle")

    def test_death_burst_family_switch_emits_with_edited_params(self):
        """Covers a second family so the family SWITCH is exercised too,
        not just repeated edits within one family."""
        balancing, preview = self.make_pair()

        with patch.object(vfx_preview, "VfxSystem", _SpyVfxSystem):
            preview._family_combo.setCurrentText("death_burst")
            preview._lever_widgets["procedural/death_burst/life"].setValue(2.0)

            spy = _SpyVfxSystem.instances[-1]
            self.assertEqual(spy.params.death_burst.life, 2.0)
            self.assertEqual(spy.calls[-1][0], "emit_shards")


class TestRampRoundTrip(VfxPreviewCase):
    def test_named_stop_ramp_round_trip(self):
        """§4 test 3: the staged doc keeps the three named stop keys, in a
        dict, unreordered, with only the edited stop changed; the emitter
        receives the engine's 3-tuple-of-colour-tuples shape."""
        balancing, preview = self.make_pair()
        preview._family_combo.setCurrentText("spark")

        stop1_path = "procedural/spark/ramp/stop_1"
        initial = balancing.staged_value(stop1_path)
        initial_stop0 = balancing.staged_value("procedural/spark/ramp/stop_0")
        self.assertIn(
            f"rgb({initial[0]},{initial[1]},{initial[2]})",
            preview._color_buttons[stop1_path].styleSheet())

        with patch.object(vfx_preview.QColorDialog, "getColor",
                           return_value=QColor(9, 99, 199)):
            preview._on_color_clicked(
                stop1_path, preview._color_buttons[stop1_path])

        ramp_doc = balancing.staged_value("procedural/spark/ramp")
        self.assertEqual(list(ramp_doc.keys()), ["stop_0", "stop_1", "stop_2"])
        self.assertEqual(ramp_doc["stop_1"], [9, 99, 199])
        self.assertEqual(ramp_doc["stop_0"], initial_stop0)
        self.assertIn(
            "rgb(9,99,199)", preview._color_buttons[stop1_path].styleSheet())

        with patch.object(vfx_preview, "VfxSystem", _SpyVfxSystem):
            _SpyVfxSystem.instances = []
            preview._emit()
            spy = _SpyVfxSystem.instances[-1]
            self.assertEqual(spy.calls[-1][0], "emit_burst")
            burst_params = spy.calls[-1][1]
            self.assertIsInstance(burst_params.ramp, tuple)
            self.assertTrue(all(isinstance(c, tuple) for c in burst_params.ramp))
            self.assertEqual(burst_params.ramp[1], (9, 99, 199))


class TestDeterministicEmit(VfxPreviewCase):
    def test_two_emits_same_seed_are_identical(self):
        """§4 test 4: two Emits with the same seed and the same params
        produce identical particle counts and per-particle params — the
        guard that makes the param-spy tests stable, and proof the injected
        RNG seam is actually used (not the stdlib `random` module)."""
        balancing, preview = self.make_pair()
        preview._family_combo.setCurrentText("death_burst")

        preview._emit()
        first = [(p.vx, p.vy, p.life, p.gravity, p.ramp, p.size, p.wx, p.wy)
                 for p in preview._system._particles]

        preview._emit()
        second = [(p.vx, p.vy, p.life, p.gravity, p.ramp, p.size, p.wx, p.wy)
                  for p in preview._system._particles]

        self.assertTrue(len(first) > 0)
        self.assertEqual(first, second)


class TestGracefulDegrade(VfxPreviewCase):
    def test_floaters_has_no_emitter_binding(self):
        """§4 test 5: a family with no emitter binding shows a placeholder
        and never calls into VfxSystem — a selection change must never be
        able to kill the editor."""
        balancing, preview = self.make_pair()

        preview._family_combo.setCurrentText("floaters")
        self.assertFalse(preview._degrade_label.isHidden())
        self.assertIsNone(preview._system)

        preview.render_frame()   # must not raise
        self.assertIsNone(preview._system)


if __name__ == "__main__":
    unittest.main()
