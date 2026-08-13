"""VfxAuthoringPLAN VA-7: the VFX panel's roster + binding strip.

Every op has a model half taking its answer as an argument, so no test here
`exec()`s a modal (`main.py::_on_add_button_type`'s seam). Widgets are built
against a TEMPDIR copy of the pinned fixture and tracked through `QtCase`, so
nothing leaks and live `data/` is never touched.

The two contracts this module is really pinning:
* registry edits (add/remove/rename/variant) write `slots.json` immediately;
* everything else STAGES through the balancing panel — this panel must never
  become a second writer of `vfx.json`.
"""
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine import data_io
from tools.tests.fixture_data import fixture_copy
from tools.tests.qt_harness import QtCase


class _FakeBalancing:
    """The balancing panel's staging surface, and nothing else — the panel
    only ever reads `domain`/`staged_value` and calls `stage_value`."""

    def __init__(self, doc, domain="vfx"):
        self.domain = domain
        self._doc = doc
        self.staged = []

    def staged_value(self, path):
        node = self._doc
        for part in path.split("/"):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node

    def stage_value(self, path, value):
        self.staged.append((path, value))
        node = self._doc
        parts = path.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value


class _PanelCase(QtCase):
    def setUp(self):
        super().setUp()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.data = fixture_copy(tmp)
        (self.data / "sprites" / "imported").mkdir(parents=True, exist_ok=True)
        from editor.panels.vfx_preview import VfxPreviewPanel
        self.panel = self.track(VfxPreviewPanel(data_dir=self.data))
        self.balancing = _FakeBalancing(
            data_io.load_json(self.data / "balancing" / "vfx.json"))
        self.panel.set_balancing_panel(self.balancing)
        self.panel.refresh_events()

    def slots_doc(self):
        return data_io.load_json(self.data / "slots.json")

    def select_event(self, event):
        self.panel._event_combo.setCurrentText(event)


class TestRosterReadsTheRegistry(_PanelCase):
    def test_it_lists_every_effect(self):
        labels = self.panel._effect_labels()
        self.assertIn("Hit", labels)
        self.assertIn("Crater", labels)
        self.assertEqual(self.panel._effect_combo.count(), len(labels))

    def test_selecting_an_effect_lists_its_variants(self):
        self.panel._effect_combo.setCurrentText("Crater")
        self.assertEqual(self.panel.current_slot(), "vfx_crater")

    def test_the_event_combo_comes_from_the_schema(self):
        """Read from the SCHEMA, not the staged doc, so the list is complete
        before a designer has touched anything."""
        events = self.panel._trigger_events()
        self.assertIn("defender_fire", events)
        self.assertIn("tile_selected", events)


class TestAddEffect(_PanelCase):
    def test_it_writes_slots_json_and_selects_the_new_effect(self):
        result = self.panel._on_add_effect(name="Shockwave")
        self.assertEqual(result, ("Shockwave", "vfx_shockwave"))
        self.assertEqual(self.panel.current_effect(), "Shockwave")
        self.assertEqual(self.panel.current_slot(), "vfx_shockwave")
        self.assertIn("Shockwave", self.panel._effect_labels())

    def test_it_is_a_registry_write_not_a_staged_value(self):
        """Structural, so it lands on disk immediately — unlike a binding."""
        self.panel._on_add_effect(name="Shockwave")
        self.assertEqual(self.balancing.staged, [])
        keys = str(self.slots_doc())
        self.assertIn("vfx_shockwave", keys)

    def test_it_emits_registry_changed(self):
        seen = []
        self.panel.registry_changed.connect(lambda: seen.append(1))
        self.panel._on_add_effect(name="Shockwave")
        self.assertEqual(len(seen), 1)

    def test_a_duplicate_name_reports_and_writes_nothing(self):
        before = (self.data / "slots.json").read_bytes()
        self.assertIsNone(self.panel._on_add_effect(name="Hit"))
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_a_nameless_add_reports_and_writes_nothing(self):
        before = (self.data / "slots.json").read_bytes()
        self.assertIsNone(self.panel._on_add_effect(name="!!!"))
        self.assertEqual((self.data / "slots.json").read_bytes(), before)


class TestAddVariant(_PanelCase):
    def test_it_appends_a_v2_and_selects_it(self):
        self.panel._effect_combo.setCurrentText("Hit")
        key = self.panel._on_add_variant()
        self.assertEqual(key, "vfx_hit_v2")
        self.assertEqual(self.panel.current_slot(), "vfx_hit_v2")

    def test_both_variants_stay_listed(self):
        self.panel._effect_combo.setCurrentText("Hit")
        self.panel._on_add_variant()
        self.assertEqual(self.panel._effect_slots("Hit"),
                         ["vfx_hit", "vfx_hit_v2"])


class TestRename(_PanelCase):
    def test_it_renames_and_reselects(self):
        self.panel._effect_combo.setCurrentText("Hit")
        self.assertEqual(self.panel._on_rename(new_key="vfx_impact"),
                         "vfx_impact")
        self.assertEqual(self.panel.current_slot(), "vfx_impact")
        self.assertIn("vfx_impact", str(self.slots_doc()))

    def test_a_colliding_key_reports_and_writes_nothing(self):
        self.panel._effect_combo.setCurrentText("Hit")
        before = (self.data / "slots.json").read_bytes()
        self.assertIsNone(self.panel._on_rename(new_key="vfx_muzzle"))
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_a_malformed_key_reports_and_writes_nothing(self):
        self.panel._effect_combo.setCurrentText("Hit")
        before = (self.data / "slots.json").read_bytes()
        self.assertIsNone(self.panel._on_rename(new_key="Not A Key"))
        self.assertEqual((self.data / "slots.json").read_bytes(), before)


class TestRemove(_PanelCase):
    def test_it_removes_without_a_dialog_when_confirm_is_false(self):
        self.panel._on_add_effect(name="Shockwave")
        self.assertTrue(self.panel._on_remove(confirm=False))
        self.assertNotIn("Shockwave", self.panel._effect_labels())

    def test_it_refuses_a_bound_slot_and_says_why(self):
        self.panel._on_add_effect(name="Shockwave")
        # Bind it on disk, which is what registry_ops reads.
        path = self.data / "balancing" / "vfx.json"
        doc = data_io.load_json(path)
        doc["triggers"]["defender_fire"]["sprite_slot"] = "vfx_shockwave"
        data_io.write_validated(doc, path,
                                self.data / "schemas" / "vfx.schema.json")
        self.assertFalse(self.panel._on_remove(confirm=False))
        self.assertIn("Shockwave", self.panel._effect_labels())

    def test_the_delete_button_wraps_its_connect_in_a_lambda(self):
        """A bare `clicked.connect(self._on_remove)` would put Qt's
        `clicked(bool)` into `confirm` — and an UNCHECKED button emits
        `clicked(False)`, so the confirmation would be silently skipped. That
        is the footgun the panels doc records biting map_details' Delete.

        Proven by stubbing the dialog rather than answering one: if the wrap
        were missing, `confirm` would arrive False and `QMessageBox.question`
        would never be reached. Asserting it WAS called is therefore exactly
        the assertion that the wrap is there — and no modal ever opens, which
        is the harness rule that made the first version of this test crash a
        worker."""
        from PySide6.QtWidgets import QMessageBox

        self.panel._on_add_effect(name="Shockwave")
        asked = []
        original = QMessageBox.question

        def fake_question(*args, **kwargs):
            asked.append(args)
            return QMessageBox.No

        QMessageBox.question = staticmethod(fake_question)
        self.addCleanup(setattr, QMessageBox, "question", original)

        before = set(self.panel._effect_labels())
        self.panel._remove_btn.click()
        self.assertEqual(len(asked), 1, "the confirmation was skipped")
        self.assertEqual(set(self.panel._effect_labels()), before,
                         "answering No must not delete")


class TestBinding(_PanelCase):
    def test_bind_stages_the_selected_slot(self):
        self.panel._effect_combo.setCurrentText("Hit")
        self.select_event("defender_fire")
        self.assertTrue(self.panel._on_bind())
        self.assertIn(("triggers/defender_fire/sprite_slot", "vfx_hit"),
                      self.balancing.staged)

    def test_unbind_stages_the_empty_string(self):
        self.select_event("defender_fire")
        self.assertTrue(self.panel._on_unbind())
        self.assertIn(("triggers/defender_fire/sprite_slot", ""),
                      self.balancing.staged)

    def test_binding_never_writes_vfx_json(self):
        """The no-second-writer contract: Save stays the balancing panel's
        one button."""
        before = (self.data / "balancing" / "vfx.json").read_bytes()
        self.panel._effect_combo.setCurrentText("Hit")
        self.select_event("defender_fire")
        self.panel._on_bind()
        self.assertEqual((self.data / "balancing" / "vfx.json").read_bytes(),
                         before)

    def test_the_bound_label_follows_the_staged_row(self):
        self.panel._effect_combo.setCurrentText("Hit")
        self.select_event("defender_fire")
        self.panel._on_bind()
        self.assertIn("vfx_hit", self.panel._bound_label.text())
        self.panel._on_unbind()
        self.assertIn("procedural", self.panel._bound_label.text())


class TestVariantSelectControls(_PanelCase):
    def test_the_mode_combo_stages(self):
        self.select_event("defender_fire")
        self.panel._mode_combo.setCurrentText("level")
        self.assertIn(("triggers/defender_fire/variant_select/mode", "level"),
                      self.balancing.staged)

    def test_the_misc_key_field_only_shows_for_misc_mode(self):
        self.select_event("defender_fire")
        self.panel._mode_combo.setCurrentText("level")
        self.assertFalse(self.panel._misc_key_edit.isVisible())
        self.panel._mode_combo.setCurrentText("misc")
        self.assertIn(("triggers/defender_fire/variant_select/mode", "misc"),
                      self.balancing.staged)

    def test_the_misc_key_stages_on_commit(self):
        self.select_event("defender_fire")
        self.panel._misc_key_edit.setText("weather")
        self.panel._on_misc_key_edited()
        self.assertIn(
            ("triggers/defender_fire/variant_select/misc_key", "weather"),
            self.balancing.staged)

    def test_the_layering_bool_stages(self):
        self.select_event("defender_fire")
        self.panel._front_check.setChecked(False)
        self.assertIn(("triggers/defender_fire/draw_in_front", False),
                      self.balancing.staged)

    def test_merely_selecting_an_event_stages_nothing(self):
        """Signals are blocked while the row is populated — otherwise just
        LOOKING at an event would dirty the document."""
        for event in ("defender_fire", "enemy_death", "tile_selected"):
            self.select_event(event)
        self.assertEqual(self.balancing.staged, [])


class TestDegradesWithoutTheVfxDomain(_PanelCase):
    def test_the_binding_controls_disable_off_domain(self):
        self.balancing.domain = "buildings"
        self.panel._refresh_binding_row()
        self.assertFalse(self.panel._bind_btn.isEnabled())
        self.assertFalse(self.panel._mode_combo.isEnabled())

    def test_staging_off_domain_is_refused_not_crashed(self):
        self.balancing.domain = "buildings"
        self.select_event("defender_fire")
        self.assertFalse(self.panel._on_bind())
        self.assertEqual(self.balancing.staged, [])


class TestModeVocabularyMatchesTheGame(unittest.TestCase):
    def test_the_editor_mirror_equals_the_game_side_tuple(self):
        """`editor/` may never import `game/`, so the mode names are
        duplicated — the editor/vfx_params.py precedent. Pin them equal."""
        from editor.panels import vfx_preview
        from game import vfx_variants
        self.assertEqual(vfx_preview.VARIANT_MODES, vfx_variants.MODES)


if __name__ == "__main__":
    unittest.main()
