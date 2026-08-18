"""editor.registry_ops — appending enemy sprite variants to data/slots.json.

Pure (no Qt/pygame): the name generator is table-tested, and add_variant is
exercised against a tempfile copy of the real data/ tree (TempDataCase), then
re-loaded to prove the write validates and the game-side variant pool grows.
"""
import unittest

from editor import registry_ops, selection
from engine import data_io
from engine.assets import load_registry
from game.enemies.enemy import variant_slot
from tools.tests.test_editor_panels import TempDataCase


class TestNextVariantKey(unittest.TestCase):
    def test_bare_slot_becomes_v2(self):
        self.assertEqual(
            registry_ops.next_variant_key(["enemy_stage_2"], set()),
            "enemy_stage_2_v2")

    def test_existing_variants_take_the_next_number(self):
        self.assertEqual(
            registry_ops.next_variant_key(
                ["enemy_stage_1_v1", "enemy_stage_1_v2"], set()),
            "enemy_stage_1_v3")

    def test_stem_stripped_from_first_slot_only(self):
        # a tier-suffixed stem (siege) keeps the _t2; only a trailing _v<N> goes
        self.assertEqual(
            registry_ops.next_variant_key(["siege_cannon_t2"], set()),
            "siege_cannon_t2_v2")

    def test_taken_keys_elsewhere_are_skipped(self):
        self.assertEqual(
            registry_ops.next_variant_key(
                ["enemy_stage_2"], {"enemy_stage_2_v2"}),
            "enemy_stage_2_v3")


class TestAddVariant(TempDataCase):
    def test_appends_and_validates_and_grows_the_pool(self):
        new_key = registry_ops.add_variant(
            self.data_dir, "enemies", ("Walker",), "Era 2")
        self.assertEqual(new_key, "enemy_stage_2_v2")

        # write validated + the new slot is now in the era's slot list
        reg = load_registry(self.data_dir)
        self.assertEqual(
            reg.group_slots("enemies", ("Walker", "Era 2")),
            ("enemy_stage_2", "enemy_stage_2_v2"))

        # and the game's per-spawn variant roll can now pick it (tier 1 -> Era 2)
        class Roll:
            def choice(self, seq):
                return seq[-1]

        self.assertEqual(
            variant_slot(reg, "Walker", 1, rng=Roll()), "enemy_stage_2_v2")

    def test_works_for_any_enemy_of_any_stage(self):
        # Siege era (tier-based) and Boss era both accept a variant
        siege = registry_ops.add_variant(
            self.data_dir, "enemies", ("Siege Cannon",), "Era 3")
        boss = registry_ops.add_variant(
            self.data_dir, "enemies", ("Boss",), "Era 0")
        self.assertEqual(siege, "siege_cannon_t3_v2")
        self.assertEqual(boss, "boss_era_0_v2")
        reg = load_registry(self.data_dir)
        self.assertIn("siege_cannon_t3_v2",
                      reg.group_slots("enemies", ("Siege Cannon", "Era 3")))
        self.assertIn("boss_era_0_v2",
                      reg.group_slots("enemies", ("Boss", "Era 0")))

    def test_two_adds_give_distinct_keys(self):
        first = registry_ops.add_variant(
            self.data_dir, "enemies", ("Raider",), "Era 1")
        second = registry_ops.add_variant(
            self.data_dir, "enemies", ("Raider",), "Era 1")
        self.assertEqual([first, second],
                         ["raider_stage_1_v2", "raider_stage_1_v3"])

    def test_unknown_era_raises(self):
        with self.assertRaises(KeyError):
            registry_ops.add_variant(
                self.data_dir, "enemies", ("Walker",), "Era 9")

    def test_ui_skin_variant(self):
        """10L-A: a ui leaf subcategory is a SKIN family, so "+ Variant" adds
        another skin. This only works because the ui groups are nested parents
        with leaf children — a flat `slots` group would make variant_target()
        return None (dead button) and add_variant() raise.

        The Button family is pinned back to its bare slot first: `add_variant`
        numbers from what already exists, so asserting "_v2" without pinning is
        really asserting that nobody has ever added a button skin — which stops
        being true the moment someone does (or, as it happened, the moment the
        suite corrupts the repo's real slots.json)."""
        self.drop_slot_variants("ui_button")

        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Buttons",), "Menu Button")
        self.assertEqual(new_key, "ui_button_v2")

        reg = load_registry(self.data_dir)      # proves the write validated
        self.assertEqual(reg.group_slots("ui", ("Buttons", "Menu Button")),
                         ("ui_button", "ui_button_v2"))

        # the structural claim: the nested shape is what makes "+ Variant" live
        self.assertEqual(
            selection.variant_target(reg, "ui", ("Buttons",), 0),
            "Menu Button")

    def test_object_form_entries_do_not_break_the_variant_walk(self):
        """D1 lets a slots[] entry be {key, frame_w, frame_h}. registry_ops
        must read the KEY out of it (a dict in a set / through the stem regex
        would crash) without crashing, AND (A7) the new variant now INHERITS
        the override's frame size rather than staying bare."""
        doc = data_io.load_json(self.data_dir / "slots.json")
        enemies = next(c for c in doc["categories"] if c["key"] == "enemies")
        walker = next(g for g in enemies["groups"] if g["label"] == "Walker")
        era2 = next(c for c in walker["children"] if c["label"] == "Era 2")
        era2["slots"] = [{"key": "enemy_stage_2", "frame_w": 128,
                          "frame_h": 128}]
        data_io.write_validated(
            doc, self.data_dir / "slots.json",
            self.data_dir / "schemas" / "slots.schema.json")

        new_key = registry_ops.add_variant(
            self.data_dir, "enemies", ("Walker",), "Era 2")
        self.assertEqual(new_key, "enemy_stage_2_v2")

        reg = load_registry(self.data_dir)
        self.assertEqual(reg.group_slots("enemies", ("Walker", "Era 2")),
                         ("enemy_stage_2", "enemy_stage_2_v2"))
        # the override survives the write, and the appended variant now
        # inherits it (A7) instead of falling back to the category default.
        self.assertEqual(reg.frame_size("enemy_stage_2"), (128, 128))
        self.assertEqual(reg.frame_size("enemy_stage_2_v2"), (128, 128))

    def test_ui_frame_size_override_propagates_to_variant(self):
        # ui_bg_main_menu carries a per-slot frame-size OVERRIDE (the ui
        # category default is 64x64). "+ Variant" yields a variant that
        # inherits that same size, whatever it currently is: the literal is
        # read from the tree rather than pinned here, because it is live art
        # a designer re-cuts (it went 480x270 -> 640x360 once already).
        stem_size = load_registry(self.data_dir).frame_size("ui_bg_main_menu")
        self.assertNotEqual(stem_size, (64, 64),
                            "stem must be an override, not the ui default")

        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Backgrounds",), "Main Menu")
        # e.g., ui_bg_main_menu_v2

        reg = load_registry(self.data_dir)
        # The variant inherits the stem's override.
        self.assertEqual(reg.frame_size(new_key), stem_size)
        self.assertEqual(reg.frame_size("ui_bg_main_menu"), stem_size)

    def test_bare_stem_yields_bare_variant(self):
        # Walker -> Era 2 has enemy_stage_2 (no override; inherits enemies'
        # 64x96). "+ Variant" on era 2 -> enemy_stage_2_v2 is BARE, inheriting
        # 64x96.
        self.drop_slot_variants("enemy_stage_2")

        new_key = registry_ops.add_variant(
            self.data_dir, "enemies", ("Walker",), "Era 2")

        reg = load_registry(self.data_dir)
        # Both inherit the category default (64x96).
        self.assertEqual(reg.frame_size("enemy_stage_2"), (64, 96))
        self.assertEqual(reg.frame_size(new_key), (64, 96))
        # The entry in the registry is bare (not an override dict).
        # (This is an implementation detail, but verifying it pins the
        # regression -- bare slots must stay bare.)
        slots_doc = data_io.load_json(self.data_dir / "slots.json")
        enemies = next(c for c in slots_doc["categories"]
                       if c["key"] == "enemies")
        walker = next(g for g in enemies["groups"] if g["label"] == "Walker")
        era2 = next(c for c in walker["children"] if c["label"] == "Era 2")
        self.assertIsInstance(era2["slots"][-1], str)  # the appended variant

    def test_variant_is_independently_resizable(self):
        # Create a ui_bg_main_menu variant at the stem's inherited size (a
        # live override -- read, not pinned; see the test above).
        stem_size = load_registry(self.data_dir).frame_size("ui_bg_main_menu")
        self.assertNotEqual(stem_size, (240, 135),
                            "the resize below must change something")

        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Backgrounds",), "Main Menu")

        reg = load_registry(self.data_dir)
        self.assertEqual(reg.frame_size(new_key), stem_size)

        # Now resize the variant to 240x135 via the existing API.
        registry_ops.set_slot_frame_size(self.data_dir, new_key, 240, 135)

        # Reload and verify: variant is 240x135, stem is untouched.
        reg = load_registry(self.data_dir)
        self.assertEqual(reg.frame_size(new_key), (240, 135))
        self.assertEqual(reg.frame_size("ui_bg_main_menu"), stem_size)

    def test_written_doc_reloads_without_frame_size_agreement_error(self):
        # ui_bg_main_menu carries a size override; "+ Variant" yields
        # ui_bg_main_menu_v2 at the same size (same key form: both dicts
        # with agreed size).
        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Backgrounds",), "Main Menu")

        # Reload the registry -- if there is a frame-size agreement bug,
        # the loader will raise ValueError here.
        reg = load_registry(self.data_dir)

        # Both are present and agree.
        self.assertIn("ui_bg_main_menu", reg.group_slots("ui", ("Backgrounds",)))
        self.assertIn(new_key, reg.group_slots("ui", ("Backgrounds",)))
        self.assertEqual(reg.frame_size("ui_bg_main_menu"),
                         reg.frame_size(new_key))


class TestButtonFamilySlot(unittest.TestCase):
    def test_simple_name_gets_the_prefix(self):
        self.assertEqual(registry_ops.button_family_slot("Tab"), "ui_button_tab")

    def test_spaces_and_repeats_collapse_to_one_underscore(self):
        self.assertEqual(
            registry_ops.button_family_slot("Big Red  Button"),
            "ui_button_big_red_button")

    def test_typing_the_key_form_does_not_double_prefix(self):
        self.assertEqual(
            registry_ops.button_family_slot("ui_button_tab"), "ui_button_tab")

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            registry_ops.button_family_slot("")

    def test_unsluggable_name_raises(self):
        with self.assertRaises(ValueError):
            registry_ops.button_family_slot("###")


class TestAddButtonFamily(TempDataCase):
    def test_add_button_family_appends_validates_and_inherits_frame_size(self):
        label, slot = registry_ops.add_button_family(self.data_dir, "Tab")
        self.assertEqual((label, slot), ("Tab", "ui_button_tab"))

        # write validated + reload cross-checks (schema-valid result)
        reg = load_registry(self.data_dir)
        self.assertIn(
            "ui_button_tab", reg.group_slots("ui", ("Buttons", "Tab")))

        # the appended slots[] entry is a BARE string (the frame-size
        # default), not a {key, frame_w, frame_h} override
        doc = data_io.load_json(self.data_dir / "slots.json")
        ui_category = next(
            c for c in doc["categories"] if c["key"] == "ui")
        buttons_group = next(
            g for g in ui_category["groups"] if g["label"] == "Buttons")
        tab_child = next(
            c for c in buttons_group["children"] if c["label"] == "Tab")
        self.assertIsInstance(tab_child["slots"][0], str)

        # and it INHERITS the ui category's frame size rather than a
        # written-in-stone 64x64
        category = reg.category("ui")
        self.assertEqual(
            reg.frame_size("ui_button_tab"),
            (category.frame_w, category.frame_h))

    def test_name_collision_raises_and_writes_nothing(self):
        registry_ops.add_button_family(self.data_dir, "Tab")
        slots_path = self.data_dir / "slots.json"
        before = slots_path.read_bytes()

        with self.assertRaises(ValueError):
            registry_ops.add_button_family(self.data_dir, "Tab")
        self.assertEqual(slots_path.read_bytes(), before)

        # the key form ("ui_button_tab") collides on the derived slot too
        with self.assertRaises(ValueError):
            registry_ops.add_button_family(self.data_dir, "ui_button_tab")
        self.assertEqual(slots_path.read_bytes(), before)

    def test_new_family_is_variantable(self):
        registry_ops.add_button_family(self.data_dir, "Tab")
        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Buttons",), "Tab")
        self.assertEqual(new_key, "ui_button_tab_v2")

        reg = load_registry(self.data_dir)
        self.assertEqual(
            reg.group_slots("ui", ("Buttons", "Tab")),
            ("ui_button_tab", "ui_button_tab_v2"))


class TestSetSlotDisplayName(TempDataCase):
    """Naming a variant (the slot editor's Name field) — editor-only metadata
    that has to survive a reload and collapse cleanly when cleared."""

    def test_names_a_bare_slot_and_reloads(self):
        self.assertTrue(registry_ops.set_slot_display_name(
            self.data_dir, "ui_panel_v3", "  Wide stone panel  "))
        reg = load_registry(self.data_dir)
        self.assertEqual(reg.display_name("ui_panel_v3"), "Wide stone panel")
        self.assertEqual(reg.display_name("ui_panel"), "")

    def test_naming_leaves_the_frame_size_alone(self):
        before = load_registry(self.data_dir).frame_size("ui_panel_v2")
        registry_ops.set_slot_display_name(self.data_dir, "ui_panel_v2", "Tall")
        reg = load_registry(self.data_dir)
        self.assertEqual(reg.frame_size("ui_panel_v2"), before)
        self.assertEqual(reg.display_name("ui_panel_v2"), "Tall")

    def test_clearing_collapses_a_named_bare_slot_back_to_a_string(self):
        registry_ops.set_slot_display_name(self.data_dir, "ui_panel_v3", "X")
        self.assertFalse(registry_ops.set_slot_display_name(
            self.data_dir, "ui_panel_v3", "  "))
        doc = data_io.load_json(self.data_dir / "slots.json")
        ui = next(c for c in doc["categories"] if c["key"] == "ui")
        panels = next(g for g in ui["groups"] if g["label"] == "Panels")
        panel = next(c for c in panels["children"] if c["label"] == "Panel")
        self.assertIn("ui_panel_v3", panel["slots"])   # bare string again
        self.assertEqual(load_registry(self.data_dir).display_name("ui_panel_v3"), "")

    def test_unknown_slot_raises(self):
        with self.assertRaises(KeyError):
            registry_ops.set_slot_display_name(self.data_dir, "nope", "X")


if __name__ == "__main__":
    unittest.main()
