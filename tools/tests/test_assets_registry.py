"""Slot registry loader (E-34/D-32) — pure, no pygame, no Qt.

Runs against the real data/slots.json (read-only) plus synthetic docs for
the failure modes. The registry fails LOUD on bad data (it is
infrastructure, like geometry.json) — E-37 tolerance is for art only.
"""
import unittest
from pathlib import Path

from engine.assets import SlotRegistry, load_registry

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA


def tiny_doc(categories=None):
    return {"categories": categories if categories is not None else [
        {"key": "a", "display_name": "A", "frame_w": 8, "frame_h": 16,
         "animations": ["idle"],
         "groups": [{"label": "G", "slots": ["thing"]}]},
    ]}


class TestRealRegistry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reg = load_registry(FIXTURE_DATA)

    def test_category_order_is_domain_order_plus_asset_only(self):
        """The RULE the name states, derived — the balancing domains lead in
        `domains.domains()` order, and the asset-only categories follow.

        This used to spell the roster out as a literal, and every asset-only
        category added since (`conditions`, `walls`, and the `Card Portraits`
        group in the sibling test below) reddened it — a test named after an
        ORDERING rule failing because the SET grew. Adding a category is
        routine; putting one in the wrong half is the bug worth catching."""
        from editor import domains
        keys = tuple(c.key for c in self.reg.categories())
        domain_keys = tuple(domains.domains())
        self.assertEqual(keys[:len(domain_keys)], domain_keys,
                         "the balancing domains must lead, in domains() order")
        asset_only = keys[len(domain_keys):]
        self.assertTrue(asset_only, "there is at least one asset-only category")
        # ...and nothing in the tail is a domain, so the split is a real one.
        self.assertEqual(set(asset_only) & set(domain_keys), set())
        self.assertEqual(len(set(keys)), len(keys), "no category repeats")

    def test_carried_over_frame_sizes(self):
        self.assertEqual(self.reg.frame_size("stone_thrower_t1_lvl1"), (64, 96))
        self.assertEqual(self.reg.frame_size("ground_tile"), (64, 32))

    def test_main_menu_background_slot(self):
        # 10K: full-frame menu art — one idle-only 480x270 slot
        self.assertEqual(self.reg.frame_size("main_menu_bg"), (480, 270))
        self.assertEqual(self.reg.animations("main_menu_bg"), ("idle",))

    def test_ui_vocabulary_and_frame_sizes(self):
        # 10L-A: button states are manifest rows, and the vocabulary is
        # per-category — every ui slot offers all four.
        self.assertEqual(self.reg.animations("ui_button"),
                         ("idle", "hover", "pressed", "disabled"))
        self.assertEqual(self.reg.animations("ui_icon_love"),
                         ("idle", "hover", "pressed", "disabled"))

        # 64x64 category default, except the whole-sheet menu background: at
        # 64x64 a 480x270 sheet would be grid-sliced into a 7x4 frame grid
        # instead of the ONE frame it is.
        self.assertEqual(self.reg.frame_size("ui_button"), (64, 64))
        self.assertEqual(self.reg.frame_size("ui_icon_love"), (64, 64))
        self.assertEqual(self.reg.frame_size("ui_bg_main_menu"), (480, 270))

        self.assertEqual(self.reg.category_of("ui_button").key, "ui")

        # nested parent groups with leaf children — the shape "+ Variant" needs.
        # Containment, not an exact roster: the `ui` category legitimately grows
        # (a "Card Portraits" group landed with the construct-card widget tree
        # and broke the old exact tuple). What matters here is that these
        # groups exist and that a parent group really does carry leaf children,
        # which is asserted immediately below.
        labels = tuple(g.label for g in self.reg.category("ui").groups)
        for expected in ("Buttons", "Panels", "Icons", "Backgrounds"):
            self.assertIn(expected, labels)
        self.assertEqual(
            tuple(c.label for c in self.reg.group("ui", ("Icons",)).children),
            ("Love", "XP", "Lives"))

    def test_tile_animation_vocabulary_is_idle_only(self):
        self.assertEqual(self.reg.animations("tile_buildable"), ("idle",))

    def test_building_vocabulary_carries_prototype_animations(self):
        self.assertEqual(self.reg.animations("stone_thrower_t1_lvl1"),
                         ("idle", "attack", "death", "hurt", "place", "upgrade"))

    def test_meditator_owns_its_art_separately_from_the_musician(self):
        # The Meditator line USED to point at the musician's slot keys. That
        # link is severed: neither line's art can reach the other's.
        musician = self.reg.group_slots("buildings", ("Musician",))
        meditator = self.reg.group_slots("buildings", ("Meditator",))
        self.assertIn("flute_player_t1_lvl1", musician)
        self.assertIn("meditator_t1_lvl1", meditator)
        self.assertEqual(set(musician) & set(meditator), set())

    def test_group_path_lookup(self):
        node = self.reg.group("buildings", ("Defender", "Stone Thrower"))
        self.assertEqual(node.slots, ("stone_thrower_t1_lvl1",
                                      "stone_thrower_t1_lvl2",
                                      "stone_thrower_t1_lvl3"))
        tiles = self.reg.group("map", ("Tiles",))
        self.assertEqual(tuple(c.label for c in tiles.children),
                         ("Buildable", "Combat", "Spawning", "Background"))

    def test_group_slots_walks_subtrees(self):
        defender = self.reg.group_slots("buildings", ("Defender",))
        self.assertEqual(len(defender), 9)   # 3 tiers x 3 levels
        self.assertIn("stone_thrower_t1_lvl1", defender)
        self.assertIn("pistoleer_t3_lvl3", defender)
        whole = self.reg.group_slots("map")
        self.assertIn("tile_buildable", whole)
        self.assertIn("ground_tile", whole)

    def test_category_of(self):
        self.assertEqual(self.reg.category_of("boss_era_0").key, "enemies")
        self.assertEqual(self.reg.category_of("base_hole").key, "core")

    def test_unknown_slot_raises(self):
        with self.assertRaises(KeyError):
            self.reg.frame_size("no_such_slot")
        with self.assertRaises(KeyError):
            self.reg.animations("no_such_slot")
        with self.assertRaises(KeyError):
            self.reg.category_of("no_such_slot")

    def test_unknown_category_and_path_raise(self):
        with self.assertRaises(KeyError):
            self.reg.category("no_such_category")
        with self.assertRaises(KeyError):
            self.reg.group("buildings", ("No Such Type",))


class TestSyntheticRegistry(unittest.TestCase):
    def test_duplicate_key_across_categories_rejected(self):
        doc = tiny_doc([
            {"key": "a", "display_name": "A", "frame_w": 8, "frame_h": 8,
             "animations": ["idle"],
             "groups": [{"label": "G", "slots": ["shared"]}]},
            {"key": "b", "display_name": "B", "frame_w": 8, "frame_h": 8,
             "animations": ["idle"],
             "groups": [{"label": "H", "slots": ["shared"]}]},
        ])
        with self.assertRaises(ValueError):
            SlotRegistry(doc)

    def test_shared_key_within_one_category_allowed(self):
        doc = tiny_doc([
            {"key": "a", "display_name": "A", "frame_w": 8, "frame_h": 8,
             "animations": ["idle"],
             "groups": [{"label": "G", "slots": ["shared"]},
                        {"label": "H", "slots": ["shared"]}]},
        ])
        reg = SlotRegistry(doc)
        self.assertEqual(reg.slot_keys(), ("shared",))

    def test_frame_size_and_first_seen_order(self):
        reg = SlotRegistry(tiny_doc())
        self.assertEqual(reg.frame_size("thing"), (8, 16))
        self.assertEqual(reg.slot_keys(), ("thing",))


class TestPerSlotFrameSize(unittest.TestCase):
    """D1: a slots[] entry may be an object overriding the category's frame
    size. The object form is normalised away at parse time — it must never
    leak out of the registry as anything but a key string."""

    def doc(self, slots):
        return {"categories": [
            {"key": "a", "display_name": "A", "frame_w": 64, "frame_h": 96,
             "animations": ["idle"],
             "groups": [{"label": "G", "slots": slots}]},
        ]}

    def test_override_beats_the_category_size(self):
        reg = SlotRegistry(self.doc(
            [{"key": "big", "frame_w": 128, "frame_h": 128}]))
        self.assertEqual(reg.frame_size("big"), (128, 128))

    def test_bare_string_in_the_same_group_still_inherits(self):
        reg = SlotRegistry(self.doc(
            ["normal", {"key": "big", "frame_w": 128, "frame_h": 128}]))
        self.assertEqual(reg.frame_size("normal"), (64, 96))
        self.assertEqual(reg.frame_size("big"), (128, 128))

    def test_unknown_slot_still_raises(self):
        reg = SlotRegistry(self.doc(
            [{"key": "big", "frame_w": 128, "frame_h": 128}]))
        with self.assertRaises(KeyError):
            reg.frame_size("no_such_slot")

    def test_group_slots_stay_plain_key_strings(self):
        """The anti-leak pin: editor/selection, palette and the game's variant
        roll all consume GroupNode.slots as a tuple of key strings."""
        reg = SlotRegistry(self.doc(
            ["normal", {"key": "big", "frame_w": 128, "frame_h": 128}]))
        self.assertEqual(reg.group("a", ("G",)).slots, ("normal", "big"))
        self.assertEqual(reg.group_slots("a", ("G",)), ("normal", "big"))
        self.assertEqual(reg.slot_keys(), ("normal", "big"))

    def test_conflicting_overrides_for_one_key_rejected(self):
        doc = {"categories": [
            {"key": "a", "display_name": "A", "frame_w": 64, "frame_h": 96,
             "animations": ["idle"],
             "groups": [
                 {"label": "G", "slots": [
                     {"key": "shared", "frame_w": 128, "frame_h": 128}]},
                 {"label": "H", "slots": [
                     {"key": "shared", "frame_w": 64, "frame_h": 64}]},
             ]},
        ]}
        with self.assertRaises(ValueError):
            SlotRegistry(doc)

    def test_same_key_once_bare_once_overridden_rejected(self):
        doc = {"categories": [
            {"key": "a", "display_name": "A", "frame_w": 64, "frame_h": 96,
             "animations": ["idle"],
             "groups": [
                 {"label": "G", "slots": ["shared"]},
                 {"label": "H", "slots": [
                     {"key": "shared", "frame_w": 128, "frame_h": 128}]},
             ]},
        ]}
        with self.assertRaises(ValueError):
            SlotRegistry(doc)

    def test_shared_art_agreeing_on_its_override_is_allowed(self):
        doc = {"categories": [
            {"key": "a", "display_name": "A", "frame_w": 64, "frame_h": 96,
             "animations": ["idle"],
             "groups": [
                 {"label": "G", "slots": [
                     {"key": "shared", "frame_w": 128, "frame_h": 128}]},
                 {"label": "H", "slots": [
                     {"key": "shared", "frame_w": 128, "frame_h": 128}]},
             ]},
        ]}
        reg = SlotRegistry(doc)
        self.assertEqual(reg.slot_keys(), ("shared",))
        self.assertEqual(reg.frame_size("shared"), (128, 128))


if __name__ == "__main__":
    unittest.main()
