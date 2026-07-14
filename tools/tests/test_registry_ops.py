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
        return None (dead button) and add_variant() raise."""
        new_key = registry_ops.add_variant(
            self.data_dir, "ui", ("Buttons",), "Button")
        self.assertEqual(new_key, "ui_button_v2")

        reg = load_registry(self.data_dir)      # proves the write validated
        self.assertEqual(reg.group_slots("ui", ("Buttons", "Button")),
                         ("ui_button", "ui_button_v2"))

        # the structural claim: the nested shape is what makes "+ Variant" live
        self.assertEqual(
            selection.variant_target(reg, "ui", ("Buttons",), 0), "Button")

    def test_object_form_entries_do_not_break_the_variant_walk(self):
        """D1 lets a slots[] entry be {key, frame_w, frame_h}. registry_ops
        must read the KEY out of it (a dict in a set / through the stem regex
        would crash) and keep appending a plain string."""
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
        # the override survives the write; the appended variant inherits
        self.assertEqual(reg.frame_size("enemy_stage_2"), (128, 128))
        self.assertEqual(reg.frame_size("enemy_stage_2_v2"), (64, 96))


if __name__ == "__main__":
    unittest.main()
