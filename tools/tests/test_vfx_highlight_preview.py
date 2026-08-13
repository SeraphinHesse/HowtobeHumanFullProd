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


class TestThePreviewFollowsTheBinding(_Case):
    """Regression: designer imported art onto vfx_tile_selected, bound it to
    the tile_selected trigger, and the preview kept drawing the diamond.

    Two independent causes, both fixed:
      1. the preview resolved `vfx_<name>` by CONVENTION instead of reading
         the bound `sprite_slot`, so it was looking at a different slot than
         the game;
      2. the panel's own AssetStore was never refreshed after an import made
         through the TREE's importer (editor/main.py::_on_manifest_changed).

    A preview that does not follow the binding is worse than no preview — it
    actively misreports what the game will do.
    """

    class _Assets:
        def __init__(self, with_art=()):
            self.with_art = set(with_art)

        def animation_total_ms(self, slot, animation):
            return 2505 if slot in self.with_art else None

    def test_it_resolves_the_BOUND_slot_not_the_conventional_one(self):
        self.doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_hit"
        self.select_highlights("tile_selected")
        self.assertEqual(self.panel._highlight_slot(), "vfx_hit")

    def test_it_falls_back_to_the_convention_when_nothing_is_bound(self):
        self.doc["triggers"]["tile_selected"]["sprite_slot"] = ""
        self.select_highlights("tile_selected")
        self.assertEqual(self.panel._highlight_slot(), "vfx_tile_selected")

    def test_a_bound_slot_WITH_art_draws_the_sprite_not_the_diamond(self):
        from engine.render import RenderItem, WorldFill
        self.doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        self.panel._assets = self._Assets({"vfx_tile_selected"})
        self.select_highlights("tile_selected")
        items = self.submitted()
        self.assertTrue(any(isinstance(i, RenderItem) for i in items))
        self.assertFalse(any(isinstance(i, WorldFill) for i in items),
                         "the diamond must not also draw")

    def test_a_bound_slot_WITHOUT_art_still_draws_the_diamond(self):
        from engine.render import RenderItem, WorldFill
        self.doc["triggers"]["tile_selected"]["sprite_slot"] = "vfx_tile_selected"
        self.panel._assets = self._Assets()          # nothing imported
        self.select_highlights("tile_selected")
        items = self.submitted()
        self.assertTrue(any(isinstance(i, WorldFill) for i in items))
        self.assertFalse(any(isinstance(i, RenderItem) for i in items))


class TestImportTargetsTheRoster(_Case):
    """Regression: an effect added through the roster had a slot and NO way
    to import art onto it — the Import buttons followed the family combo,
    which only projectile/crater/beam/highlights resolve a slot for."""

    def test_a_roster_selection_is_the_import_target(self):
        self.panel._set_family("spark")          # no fixed slot of its own
        self.panel._on_add_effect(name="Shockwave")
        self.assertEqual(self.panel.current_slot(), "vfx_shockwave")
        self.assertEqual(self.panel._current_import_slot(), "vfx_shockwave")

    def test_the_import_button_is_offered_for_it(self):
        self.panel._set_family("spark")
        self.panel._on_add_effect(name="Shockwave")
        self.assertFalse(self.panel._import_btn.isHidden())

    def test_a_family_with_a_FIXED_slot_still_wins(self):
        """projectile/shell, crater and beam are unchanged — their art is
        bound to the family, not chosen in the roster."""
        from editor.panels.vfx_preview import _CRATER_FAMILY
        self.panel._effect_combo.setCurrentText("Hit")   # roster says vfx_hit
        self.panel._set_family(_CRATER_FAMILY)
        self.assertEqual(self.panel._current_import_slot(), "vfx_crater")


class TestTheShellRefreshesThePreviewsAssets(unittest.TestCase):
    def test_on_manifest_changed_reloads_the_vfx_preview(self):
        """The line whose absence made an import through the TREE invisible
        to the preview. Asserted on the source, because building a whole
        MainWindow here would cost minutes for one wiring line."""
        from pathlib import Path
        src = (Path(__file__).resolve().parents[2]
               / "editor" / "main.py").read_text(encoding="utf-8")
        body = src.split("def _on_manifest_changed", 1)[1]
        body = body.split("\n    def ", 1)[0]
        self.assertIn("self.vfx_preview.reload_assets()", body)


if __name__ == "__main__":
    unittest.main()
