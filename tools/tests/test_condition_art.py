"""Tile-condition ART: the per-tile slot roll + the `terrain`-layer emitter.

Conditions themselves (the weighted roll, the path weights, the stat modifiers)
are pinned by `test_tile_conditions.py`; this module covers only what turns a
condition into a drawn sprite — `Tile.condition_slot`, `game/map/conditions.py`,
and the tint fallback the two share.

Headless and fixture-pinned: the registry is built from an in-memory
`slots.json` document rather than read from `data/`, so an artist adding a
`cond_mountain_v3` can never make these tests fail (`data/CLAUDE.md`: never
assert against live data).
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.assets.registry import SlotRegistry
from engine.render import LAYERS
from game.core.balance import load_balance
from game.map.conditions import LAYER, condition_render_items, draws_tint
from game.map.tile_map import TileMap
from game.map.tiles import CONDITION_CATEGORY, CONDITION_GROUP, TileCondition

MAPBAL = load_balance(FIXTURE_DATA, "map")

# A pinned two-variant-per-condition registry — the shape data/slots.json ships,
# plus a second Mountain variant so the per-tile variant roll has something to
# choose between.
REGISTRY_DOC = {
    "categories": [{
        "key": CONDITION_CATEGORY,
        "display_name": "Tile Conditions",
        "frame_w": 64,
        "frame_h": 96,
        "animations": ["idle"],
        "groups": [{
            "label": "Terrain",
            "children": [
                {"label": "Grass", "slots": ["cond_grass"]},
                {"label": "Mountain",
                 "slots": ["cond_mountain", "cond_mountain_v2"]},
                {"label": "Pond", "slots": ["cond_pond"]},
                {"label": "Forest", "slots": ["cond_forest"]},
            ],
        }],
    }],
}
REGISTRY = SlotRegistry(REGISTRY_DOC)
ALL_SLOTS = frozenset(REGISTRY.group_slots(CONDITION_CATEGORY))


def synth(rows, base=(0, 0), rng=None, registry=None):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL, rng=rng, registry=registry)


# 12x12: a buildable pocket, combat beyond, a background border row.
ROWS = ["bb" + "c" * 10] * 2 + ["c" * 12] * 9 + ["f" * 12]


def slots_of(tm):
    return [[tm.get(c, r).condition_slot for c in range(tm.cols)]
            for r in range(tm.rows)]


# ---------------------------------------------------------------------------
# 1. The per-tile slot roll
# ---------------------------------------------------------------------------
class TestConditionSlotRoll(unittest.TestCase):

    def test_no_registry_or_no_rng_leaves_every_slot_none(self):
        """The fixture mode every pre-existing headless test runs in: nothing
        is rolled, so the terrain layer can emit nothing."""
        for kwargs in ({}, {"rng": random.Random(1)}, {"registry": REGISTRY}):
            tm = synth(ROWS, **kwargs)
            flat = [s for row in slots_of(tm) for s in row]
            self.assertEqual(set(flat), {None}, kwargs)

    def test_same_seed_same_slots_different_seed_differs(self):
        a = slots_of(synth(ROWS, rng=random.Random(7), registry=REGISTRY))
        b = slots_of(synth(ROWS, rng=random.Random(7), registry=REGISTRY))
        c = slots_of(synth(ROWS, rng=random.Random(8), registry=REGISTRY))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)

    def test_every_playable_tile_gets_a_slot_background_gets_none(self):
        """Art covers the starting pocket and the base too — those stay GRASS
        (gameplay), but imported grass art must not leave a hole there."""
        tm = synth(ROWS, rng=random.Random(3), registry=REGISTRY)
        for tile in tm.all_tiles():
            if tile.state.name == "BACKGROUND":
                self.assertIsNone(tile.condition_slot, (tile.col, tile.row))
            else:
                self.assertIn(tile.condition_slot, ALL_SLOTS,
                              (tile.col, tile.row))

    def test_slot_matches_the_tile_own_condition(self):
        tm = synth(ROWS, rng=random.Random(11), registry=REGISTRY)
        for tile in tm.all_tiles():
            if tile.condition_slot is None:
                continue
            expected = REGISTRY.group_slots(
                CONDITION_CATEGORY, CONDITION_GROUP[tile.condition])
            self.assertIn(tile.condition_slot, expected)

    def test_variants_are_rolled_per_tile(self):
        """Both Mountain variants show up across a map — a new `_v3` dropped in
        via the editor grows the pool with no code change."""
        tm = synth(["c" * 40] * 40, base=(0, 0), rng=random.Random(5),
                   registry=REGISTRY)
        seen = {t.condition_slot for t in tm.all_tiles()
                if t.condition is TileCondition.MOUNTAIN}
        self.assertEqual(seen, {"cond_mountain", "cond_mountain_v2"})

    def test_an_unknown_group_degrades_to_no_slot(self):
        """A registry missing a condition's group must not crash a boot."""
        doc = {"categories": [{
            "key": CONDITION_CATEGORY, "display_name": "X",
            "frame_w": 64, "frame_h": 96, "animations": ["idle"],
            "groups": [{"label": "Terrain",
                        "children": [{"label": "Grass",
                                      "slots": ["cond_grass"]}]}],
        }]}
        tm = synth(ROWS, rng=random.Random(2), registry=SlotRegistry(doc))
        for tile in tm.all_tiles():
            self.assertIn(tile.condition_slot, (None, "cond_grass"))


# ---------------------------------------------------------------------------
# 2. The emitter
# ---------------------------------------------------------------------------
class TestConditionRenderItems(unittest.TestCase):

    def setUp(self):
        self.tm = synth(ROWS, rng=random.Random(4), registry=REGISTRY)

    def test_layer_sits_between_ground_and_entities(self):
        self.assertEqual(LAYER, "terrain")
        self.assertLess(LAYERS.index("ground"), LAYERS.index(LAYER))
        self.assertLess(LAYERS.index(LAYER), LAYERS.index("entities"))

    def test_emits_one_item_per_tile_with_art_on_the_terrain_layer(self):
        art = {s: False for s in ALL_SLOTS}
        items = condition_render_items(self.tm, 0, self.tm.cols - 1,
                                       0, self.tm.rows - 1, art)
        expected = [(t.col, t.row) for t in self.tm.all_tiles()
                    if t.condition_slot is not None]
        self.assertEqual(len(items), len(expected))
        self.assertEqual({i.layer for i in items}, {LAYER})
        self.assertEqual({i.world_pos for i in items}, set(expected))
        for item in items:
            self.assertEqual(item.slot_key,
                             self.tm.get(*item.world_pos).condition_slot)

    def test_slots_without_art_emit_nothing(self):
        """An un-imported condition draws NO sprite — never a grey X."""
        art = {"cond_mountain": False, "cond_mountain_v2": False}
        items = condition_render_items(self.tm, 0, self.tm.cols - 1,
                                       0, self.tm.rows - 1, art)
        self.assertTrue(items)
        self.assertEqual({i.slot_key for i in items} - set(art), set())
        self.assertEqual(
            condition_render_items(self.tm, 0, self.tm.cols - 1,
                                   0, self.tm.rows - 1, {}), [])

    def test_windowed_and_clamped_to_the_map(self):
        art = {s: False for s in ALL_SLOTS}
        items = condition_render_items(self.tm, 2, 4, 1, 3, art)
        self.assertTrue(items)
        for item in items:
            col, row = item.world_pos
            self.assertTrue(2 <= col <= 4 and 1 <= row <= 3)
        # An out-of-bounds window clamps instead of raising.
        full = condition_render_items(self.tm, -50, 500, -50, 500, art)
        self.assertEqual(
            len(full),
            len(condition_render_items(self.tm, 0, self.tm.cols - 1,
                                       0, self.tm.rows - 1, art)))

    def test_animation_phase_is_deterministic_and_per_cell(self):
        art = {s: False for s in ALL_SLOTS}
        a = condition_render_items(self.tm, 0, 5, 0, 5, art, anim_time_ms=1000)
        b = condition_render_items(self.tm, 0, 5, 0, 5, art, anim_time_ms=1000)
        self.assertEqual([i.anim_time_ms for i in a],
                         [i.anim_time_ms for i in b])
        self.assertGreater(len({i.anim_time_ms for i in a}), 1)


# ---------------------------------------------------------------------------
# 3. The tint fallback (shared by the emitter's caller and MapOverlays)
# ---------------------------------------------------------------------------
class TestDrawsTint(unittest.TestCase):

    def test_no_slot_draws_the_tint(self):
        self.assertTrue(draws_tint(None, {}))
        self.assertTrue(draws_tint(None, {"cond_pond": False}))

    def test_slot_without_art_draws_the_tint(self):
        self.assertTrue(draws_tint("cond_pond", {}))
        self.assertTrue(draws_tint("cond_pond", {"cond_mountain": False}))

    def test_slot_with_art_replaces_the_tint(self):
        self.assertFalse(draws_tint("cond_pond", {"cond_pond": False}))

    def test_entry_can_opt_back_into_the_tint(self):
        self.assertTrue(draws_tint("cond_pond", {"cond_pond": True}))


if __name__ == "__main__":
    unittest.main()
