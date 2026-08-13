"""VfxAuthoringPLAN VA-8: the new families preview live.

VA-4's respawn needed no preview path at all — it is a fourth spark PRESET, so
it rides the existing spark family (D11). That leaves `highlights`, which is
ONE `procedural` key holding SEVEN blocks, so it gets a sub-combo the way
`spark` has one and its own small draw path.

Assertions are over the SUBMITTED primitives, never pixels — the rule the
existing preview tests already follow.
"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine import data_io
from tools.tests.fixture_data import fixture_copy
from tools.tests.qt_harness import QtCase


class _FakeBalancing:
    def __init__(self, doc, domain="vfx"):
        self.domain = domain
        self._doc = doc

    def staged_value(self, path):
        node = self._doc
        for part in path.split("/"):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def stage_value(self, path, value):
        node = self._doc
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


class _Case(QtCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.data = fixture_copy(tmp)
        from editor.panels.vfx_preview import VfxPreviewPanel
        self.panel = self.track(VfxPreviewPanel(data_dir=self.data))
        self.doc = data_io.load_json(self.data / "balancing" / "vfx.json")
        self.panel.set_balancing_panel(_FakeBalancing(self.doc))
        self.panel.refresh_families()

    def select_highlights(self, name="tile_selected"):
        from editor.panels.vfx_preview import _HIGHLIGHT_FAMILY
        self.panel._set_family(_HIGHLIGHT_FAMILY)
        self.panel._highlight_combo.setCurrentText(name)

    def submitted(self):
        """Drive one preview submit and return the renderer's queue."""
        self.panel._renderer._queue.clear()
        self.panel._submit_highlight_preview(0.016)
        return list(self.panel._renderer._queue)


class TestTheFamilyIsSupported(_Case):
    def test_highlights_appears_in_the_family_combo(self):
        """It is data-driven off `procedural.*`, so VA-5 adding the block is
        what puts it there."""
        families = [self.panel._family_combo.itemText(i)
                    for i in range(self.panel._family_combo.count())]
        self.assertIn("highlights", families)

    def test_it_does_not_show_the_no_preview_placeholder(self):
        """The whole point of this phase: it used to degrade to
        "no preview for 'highlights' yet".

        `isHidden()`, not `isVisible()` — a widget whose window was never
        shown reports isVisible() False whatever its own flag says, so
        isVisible() here would pass even if the placeholder were up."""
        self.select_highlights()
        self.assertTrue(self.panel._degrade_label.isHidden())
        self.assertEqual(self.panel._degrade_label.text(), "")

    def test_the_sub_combo_lists_all_seven_and_only_shows_here(self):
        self.select_highlights()
        names = [self.panel._highlight_combo.itemText(i)
                 for i in range(self.panel._highlight_combo.count())]
        self.assertEqual(len(names), 7)
        self.assertIn("tile_selected", names)
        self.assertIn("wall_edge", names)
        self.panel._set_family("spark")
        self.assertTrue(self.panel._highlight_combo.isHidden())

    def test_respawn_is_a_spark_preset_not_a_family(self):
        """VA-4/D11: no new preview path was needed for the respawn effect."""
        from editor.panels.vfx_preview import _PRESET_KEYS
        self.assertIn("respawn", _PRESET_KEYS)
        families = [self.panel._family_combo.itemText(i)
                    for i in range(self.panel._family_combo.count())]
        self.assertNotIn("respawn", families)


class TestTheDraw(_Case):
    def test_it_submits_a_depth_sorted_world_fill(self):
        from engine.render import WorldFill
        self.select_highlights()
        fills = [i for i in self.submitted() if isinstance(i, WorldFill)]
        self.assertEqual(len(fills), 1)

    def test_it_draws_the_staged_colour_and_width(self):
        from engine.render import WorldFill
        self.doc["procedural"]["highlights"]["tile_selected"] = {
            "color": [1, 2, 3], "border_width": 5, "fill_alpha": 0}
        self.select_highlights()
        fill = next(i for i in self.submitted() if isinstance(i, WorldFill))
        self.assertEqual(fill.border, (1, 2, 3))
        self.assertEqual(fill.border_width, 5)
        self.assertIsNone(fill.color, "fill_alpha 0 = outline only")

    def test_a_non_zero_fill_alpha_fills(self):
        from engine.render import WorldFill
        self.doc["procedural"]["highlights"]["tile_selected"] = {
            "color": [1, 2, 3], "border_width": 2, "fill_alpha": 90}
        self.select_highlights()
        fill = next(i for i in self.submitted() if isinstance(i, WorldFill))
        self.assertEqual(fill.color, (1, 2, 3, 90))

    def test_switching_the_sub_combo_switches_what_is_drawn(self):
        from engine.render import WorldFill
        self.doc["procedural"]["highlights"]["wall_edge"]["color"] = [9, 9, 9]
        self.select_highlights("wall_edge")
        fill = next(i for i in self.submitted() if isinstance(i, WorldFill))
        self.assertEqual(fill.border, (9, 9, 9))

    def test_no_selection_draws_nothing_rather_than_raising(self):
        """`clear()`, not `setCurrentText("")` — a non-editable combo ignores
        a value it has no item for, so the first version of this test was
        silently still asserting against `tile_selected`."""
        self.select_highlights()
        self.panel._highlight_combo.clear()
        self.assertIsNone(self.panel.current_highlight())
        self.assertEqual(self.submitted(), [])

    def test_a_highlight_with_no_params_draws_nothing(self):
        self.select_highlights()
        del self.doc["procedural"]["highlights"]["tile_selected"]
        self.assertEqual(self.submitted(), [])


class TestImportTargetsThisHighlight(_Case):
    def test_the_import_slot_follows_the_sub_combo(self):
        """VA-5 gave every highlight its own vfx_<name> slot, so this family
        DOES resolve to a fixed slot — it just depends on the sub-combo."""
        self.select_highlights("tile_selected")
        self.assertEqual(self.panel._current_import_slot(), "vfx_tile_selected")
        self.panel._highlight_combo.setCurrentText("move_target")
        self.assertEqual(self.panel._current_import_slot(), "vfx_move_target")

    def test_the_import_button_is_offered(self):
        self.select_highlights()
        self.assertFalse(self.panel._import_btn.isHidden())


if __name__ == "__main__":
    unittest.main()
