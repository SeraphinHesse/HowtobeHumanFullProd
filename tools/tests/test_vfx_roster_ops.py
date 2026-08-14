"""VfxAuthoringPLAN VA-6: add / remove / rename a VFX effect.

The first DESTRUCTIVE registry ops in the repo, so most of what is asserted
here is what they REFUSE to do — a remove that silently orphaned a trigger
binding, or a rename that moved three of its four files, would each leave the
designer with a roster that looks fine and does not work.

Every test drives a tempdir copy of the pinned fixture, never live `data/`.
"""
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from editor import asset_import, registry_ops
from engine import data_io
from engine.assets.registry import load_registry
from tools.tests.fixture_data import fixture_copy


class _Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        self.data = fixture_copy(tmp)
        (self.data / "sprites" / "imported").mkdir(parents=True, exist_ok=True)

    # -- helpers ---------------------------------------------------------
    def slots(self):
        return data_io.load_json(self.data / "slots.json")

    def effects(self):
        category = next(c for c in self.slots()["categories"]
                        if c["key"] == "vfx")
        return next(g for g in category["groups"] if g["label"] == "Effects")

    def manifest(self):
        return asset_import.load_manifest_doc(self.data)

    def give_art(self, slot, sheet=None):
        """Register `slot` in the manifest with a real PNG on disk."""
        ref = sheet or asset_import.sheet_ref(slot)
        png = self.data / "sprites" / ref
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(b"not really a png, but a real file")
        doc = self.manifest()
        doc["entries"][slot] = {
            "sheet": ref, "frame_w": 64, "frame_h": 64,
            "offset_x": 0, "offset_y": 0,
            "rows": [{"animation": "idle", "fps": 8, "frames": 1,
                      "hidden": [], "loop_count": 1, "loop_end": 0,
                      "loop_start": 0}],
        }
        asset_import.write_manifest_doc(self.data, doc)
        return ref

    def bind(self, event, slot):
        path = self.data / "balancing" / "vfx.json"
        doc = data_io.load_json(path)
        doc["triggers"][event]["sprite_slot"] = slot
        data_io.write_validated(doc, path,
                                self.data / "schemas" / "vfx.schema.json")

    def binding(self, event):
        doc = data_io.load_json(self.data / "balancing" / "vfx.json")
        return doc["triggers"][event]["sprite_slot"]


class TestSlug(unittest.TestCase):
    def test_it_slugs_like_button_family_slot(self):
        self.assertEqual(registry_ops.vfx_effect_slot("Shock Wave!"),
                         "vfx_shock_wave")
        self.assertEqual(registry_ops.vfx_effect_slot("  Ripple  "),
                         "vfx_ripple")

    def test_typing_the_key_does_not_double_prefix(self):
        self.assertEqual(registry_ops.vfx_effect_slot("vfx_ripple"),
                         "vfx_ripple")

    def test_a_name_with_nothing_sluggable_raises(self):
        for name in ("", "   ", "!!!", None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    registry_ops.vfx_effect_slot(name)


class TestAdd(_Case):
    def test_it_appends_a_leaf_child_group(self):
        label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.assertEqual((label, slot), ("Shockwave", "vfx_shockwave"))
        children = {c["label"]: c["slots"] for c in self.effects()["children"]}
        self.assertEqual(children["Shockwave"], ["vfx_shockwave"])

    def test_the_new_slot_resolves_through_the_registry(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry = load_registry(self.data)
        self.assertIn(slot, registry.group_slots("vfx"))
        self.assertEqual(registry.frame_size(slot), (64, 64))

    def test_it_is_a_reachable_variant_target(self):
        """The whole point of VA-1's restructure: a fresh effect can take
        variants immediately."""
        from editor import selection
        registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry = load_registry(self.data)
        labels = selection.subcategories(registry, "vfx", ("Effects",))
        idx = labels.index("Shockwave")
        self.assertEqual(
            selection.variant_target(registry, "vfx", ("Effects",), idx),
            "Shockwave")

    def test_a_variant_can_then_be_added(self):
        registry_ops.add_vfx_effect(self.data, "Shockwave")
        key = registry_ops.add_variant(self.data, "vfx", ("Effects",),
                                       "Shockwave")
        self.assertEqual(key, "vfx_shockwave_v2")
        self.assertIn(key, load_registry(self.data).group_slots("vfx"))

    def test_a_duplicate_label_raises_before_writing(self):
        before = (self.data / "slots.json").read_bytes()
        with self.assertRaises(ValueError):
            registry_ops.add_vfx_effect(self.data, "Hit")
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_a_colliding_key_raises_before_writing(self):
        before = (self.data / "slots.json").read_bytes()
        with self.assertRaises(ValueError):
            registry_ops.add_vfx_effect(self.data, "vfx_hit")
        self.assertEqual((self.data / "slots.json").read_bytes(), before)


class TestRemove(_Case):
    def test_it_drops_the_slot_and_its_now_empty_group(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        removed_group, removed_png = registry_ops.remove_slot(self.data, slot)
        self.assertTrue(removed_group)
        self.assertIsNone(removed_png)
        self.assertNotIn(slot, load_registry(self.data).group_slots("vfx"))
        self.assertNotIn("Shockwave",
                         {c["label"] for c in self.effects()["children"]})

    def test_removing_a_variant_keeps_the_group(self):
        registry_ops.add_vfx_effect(self.data, "Shockwave")
        variant = registry_ops.add_variant(self.data, "vfx", ("Effects",),
                                           "Shockwave")
        removed_group, _png = registry_ops.remove_slot(self.data, variant)
        self.assertFalse(removed_group)
        slots = load_registry(self.data).group_slots("vfx")
        self.assertNotIn(variant, slots)
        self.assertIn("vfx_shockwave", slots)

    def test_it_refuses_while_the_slot_is_bound(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.bind("defender_fire", slot)
        with self.assertRaises(ValueError) as ctx:
            registry_ops.remove_slot(self.data, slot)
        self.assertIn("defender_fire", str(ctx.exception))
        self.assertIn(slot, load_registry(self.data).group_slots("vfx"))

    def test_unbinding_then_removing_works(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.bind("defender_fire", slot)
        self.bind("defender_fire", "")
        registry_ops.remove_slot(self.data, slot)
        self.assertNotIn(slot, load_registry(self.data).group_slots("vfx"))

    def test_it_drops_the_manifest_entry_and_the_owned_png(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        ref = self.give_art(slot)
        _group, removed_png = registry_ops.remove_slot(self.data, slot)
        self.assertEqual(removed_png, ref)
        self.assertFalse((self.data / "sprites" / ref).exists())
        self.assertNotIn(slot, self.manifest()["entries"])

    def test_a_shared_png_survives(self):
        """A slot LINKED to another slot's art must not delete art the owner
        still needs — asset_import.unreferenced_sheets is the refcount."""
        _l, owner = registry_ops.add_vfx_effect(self.data, "Owner")
        _l, linker = registry_ops.add_vfx_effect(self.data, "Linker")
        ref = self.give_art(owner)
        self.give_art(linker, sheet=ref)          # links, does not copy
        _group, removed_png = registry_ops.remove_slot(self.data, linker)
        self.assertIsNone(removed_png)
        self.assertTrue((self.data / "sprites" / ref).exists())
        self.assertIn(owner, self.manifest()["entries"])

    def test_an_unknown_slot_raises(self):
        with self.assertRaises(KeyError):
            registry_ops.remove_slot(self.data, "vfx_not_a_slot")

    def test_the_result_still_validates(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry_ops.remove_slot(self.data, slot)
        data_io.load_validated(self.data / "slots.json",
                               self.data / "schemas" / "slots.schema.json")


class TestRename(_Case):
    def test_it_renames_the_key_in_slots_json(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry_ops.rename_slot(self.data, slot, "vfx_ripple")
        slots = load_registry(self.data).group_slots("vfx")
        self.assertIn("vfx_ripple", slots)
        self.assertNotIn(slot, slots)

    def test_it_preserves_a_frame_size_override(self):
        """vfx_crater carries {key, frame_w, frame_h}; a rename must move the
        key WITHIN the object, not flatten it to a bare string."""
        registry_ops.rename_slot(self.data, "vfx_crater", "vfx_scorch")
        registry = load_registry(self.data)
        self.assertEqual(registry.frame_size("vfx_scorch"), (64, 96))

    def test_it_rekeys_the_manifest_and_renames_owned_art(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.give_art(slot)
        _rebound, png_renamed = registry_ops.rename_slot(
            self.data, slot, "vfx_ripple")
        self.assertTrue(png_renamed)
        entries = self.manifest()["entries"]
        self.assertNotIn(slot, entries)
        self.assertEqual(entries["vfx_ripple"]["sheet"],
                         "imported/vfx_ripple.png")
        self.assertTrue(
            (self.data / "sprites" / "imported" / "vfx_ripple.png").exists())
        self.assertFalse(
            (self.data / "sprites" / "imported" / "vfx_shockwave.png").exists())

    def test_a_linked_sheet_is_left_alone(self):
        _l, owner = registry_ops.add_vfx_effect(self.data, "Owner")
        _l, linker = registry_ops.add_vfx_effect(self.data, "Linker")
        ref = self.give_art(owner)
        self.give_art(linker, sheet=ref)
        _rebound, png_renamed = registry_ops.rename_slot(
            self.data, linker, "vfx_ripple")
        self.assertFalse(png_renamed)
        self.assertEqual(self.manifest()["entries"]["vfx_ripple"]["sheet"], ref)
        self.assertTrue((self.data / "sprites" / ref).exists())

    def test_it_rewrites_every_trigger_binding(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.bind("defender_fire", slot)
        self.bind("projectile_hit", slot)
        rebound, _png = registry_ops.rename_slot(self.data, slot, "vfx_ripple")
        self.assertEqual(rebound, ("defender_fire", "projectile_hit"))
        self.assertEqual(self.binding("defender_fire"), "vfx_ripple")
        self.assertEqual(self.binding("projectile_hit"), "vfx_ripple")

    def test_an_unbound_unimported_slot_renames_cleanly(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        rebound, png_renamed = registry_ops.rename_slot(
            self.data, slot, "vfx_ripple")
        self.assertEqual(rebound, ())
        self.assertFalse(png_renamed)

    def test_renaming_to_itself_is_a_no_op(self):
        before = (self.data / "slots.json").read_bytes()
        self.assertEqual(
            registry_ops.rename_slot(self.data, "vfx_hit", "vfx_hit"),
            ((), False))
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_a_colliding_new_key_raises_before_writing(self):
        before = (self.data / "slots.json").read_bytes()
        with self.assertRaises(ValueError):
            registry_ops.rename_slot(self.data, "vfx_hit", "vfx_muzzle")
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_a_malformed_new_key_raises_before_writing(self):
        before = (self.data / "slots.json").read_bytes()
        for bad in ("Vfx_Ripple", "2fast", "has space", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    registry_ops.rename_slot(self.data, "vfx_hit", bad)
        self.assertEqual((self.data / "slots.json").read_bytes(), before)

    def test_an_unknown_old_key_raises(self):
        with self.assertRaises(KeyError):
            registry_ops.rename_slot(self.data, "vfx_nope", "vfx_ripple")

    def test_a_non_vfx_slot_is_refused(self):
        """This op only knows how to migrate the vfx category's references."""
        with self.assertRaises(KeyError):
            registry_ops.rename_slot(self.data, "tile_buildable",
                                     "tile_renamed")

    def test_the_result_still_validates(self):
        registry_ops.rename_slot(self.data, "vfx_hit", "vfx_impact")
        data_io.load_validated(self.data / "slots.json",
                               self.data / "schemas" / "slots.schema.json")


class TestTriggerBindings(_Case):
    def test_it_finds_every_event_naming_a_slot(self):
        self.bind("defender_fire", "vfx_muzzle")
        self.assertIn("defender_fire",
                      registry_ops.trigger_bindings(self.data, "vfx_muzzle"))

    def test_a_missing_balancing_file_reads_as_no_bindings(self):
        (self.data / "balancing" / "vfx.json").unlink()
        self.assertEqual(
            registry_ops.trigger_bindings(self.data, "vfx_muzzle"), ())


class TestBothSlotEnumsStayInSync(_Case):
    """Regression, caught by the exit gate.

    Two schemas carry a GENERATED slot enum: vfx.schema.json's
    trigger_row.sprite_slot (the vfx category only) and core.schema.json's
    enemy_intro_entry.sprite_slot (EVERY slot in EVERY category). The roster
    ops first resynced only the vfx one, so adding an effect through the
    editor left core.schema.json stale and test_schema_slot_sync red. The
    designer who clicked "+ Effect" had no reason to connect that click to a
    schema in another domain.
    """

    def core_enum(self):
        doc = data_io.load_json(self.data / "schemas" / "core.schema.json")
        return doc["$defs"]["enemy_intro_entry"]["properties"]["sprite_slot"]["enum"]

    def vfx_enum(self):
        doc = data_io.load_json(self.data / "schemas" / "vfx.schema.json")
        return doc["$defs"]["trigger_row"]["properties"]["sprite_slot"]["enum"]

    def assert_both_match_the_registry(self):
        slots = set(load_registry(self.data).slot_keys())
        self.assertEqual(set(self.core_enum()), slots)
        vfx_slots = set(load_registry(self.data).group_slots("vfx"))
        self.assertEqual(set(self.vfx_enum()) - {""}, vfx_slots)

    def test_add_resyncs_both(self):
        registry_ops.add_vfx_effect(self.data, "Shockwave")
        self.assertIn("vfx_shockwave", self.core_enum())
        self.assertIn("vfx_shockwave", self.vfx_enum())
        self.assert_both_match_the_registry()

    def test_remove_resyncs_both(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry_ops.remove_slot(self.data, slot)
        self.assertNotIn(slot, self.core_enum())
        self.assertNotIn(slot, self.vfx_enum())
        self.assert_both_match_the_registry()

    def test_rename_resyncs_both(self):
        _label, slot = registry_ops.add_vfx_effect(self.data, "Shockwave")
        registry_ops.rename_slot(self.data, slot, "vfx_ripple")
        for enum in (self.core_enum(), self.vfx_enum()):
            self.assertIn("vfx_ripple", enum)
            self.assertNotIn(slot, enum)
        self.assert_both_match_the_registry()

    def test_a_variant_reaches_the_registry_and_the_vfx_enum(self):
        """KNOWN GAP, deliberately not fixed here: `add_variant` does NOT
        resync `core.schema.json`.

        It is the GENERIC variant op — enemies, deco, ui and conditions all
        use it — so the gap predates this branch and affects every category
        equally: adding an enemy variant in the editor has always left that
        enum stale. The exit gate surfaced the `add_vfx_effect` half, which is
        fixed; widening a handoff fix into the shared op (and into
        `_append_slot`/`add_background_slot`/`add_deco_prop`/
        `add_button_family`, which have the same shape) is a change that wants
        its own branch and its own test run.

        Asserting only what is true today, so this test does not quietly go
        green on a half-fix."""
        registry_ops.add_vfx_effect(self.data, "Shockwave")
        key = registry_ops.add_variant(self.data, "vfx", ("Effects",),
                                       "Shockwave")
        self.assertIn(key, load_registry(self.data).group_slots("vfx"))
        self.assertNotIn(key, self.core_enum(),
                         "if this now passes, the generic add_variant gap was "
                         "fixed — update this test and its note")


class TestVariantTargetsIncludesVfx(unittest.TestCase):
    def test_vfx_is_a_variant_target_category(self):
        """Without this the "+ Variant" button stays disabled for vfx however
        well-shaped the registry is — it is the shell's product decision."""
        from editor.main import MainWindow
        self.assertIn("vfx", MainWindow._VARIANT_TARGETS)
        self.assertIsNone(MainWindow._VARIANT_TARGETS["vfx"],
                          "no label whitelist: every effect takes variants")


if __name__ == "__main__":
    unittest.main()
