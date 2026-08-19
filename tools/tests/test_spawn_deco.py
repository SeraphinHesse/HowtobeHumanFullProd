"""Spawn-band tree deco: the per-tile roll (folded into `TileMap.__init__`'s
condition-art pass) + the `deco`-layer emitter, `game/map/spawn_deco.py`.

Headless and fixture-pinned: the registry is built from an in-memory
`slots.json` document rather than read from `data/`, so an artist adding a
`deco_tree_v11` can never make these tests fail (`data/CLAUDE.md`: never
assert against live data) — mirrors `test_condition_art.py`'s pattern.
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
from game.map.spawn_deco import (
    LAYER, SPAWN_TREE_EXCLUDED, spawn_deco_render_items, spawn_tree_slots,
)
from game.map.tile_map import TileMap
from game.map.tiles import DECO_CATEGORY, SPAWN_DECO_GROUP, TileState

MAPBAL = load_balance(FIXTURE_DATA, "map")

REGISTRY_DOC = {
    "categories": [{
        "key": DECO_CATEGORY,
        "display_name": "Deco",
        "frame_w": 64,
        "frame_h": 96,
        "animations": ["idle"],
        "groups": [
            {"label": "Props", "children": [
                {"label": "Tree", "slots": ["deco_tree", "deco_tree_v2"]},
            ]},
        ],
    }],
}
REGISTRY = SlotRegistry(REGISTRY_DOC)
# Through the SHARED helper, not a raw `group_slots` — these tests must index
# exactly the family the roll is sized against (see `spawn_tree_slots`).
TREE_SLOTS = spawn_tree_slots(REGISTRY)


def synth(rows, base=(0, 0), rng=None, registry=None):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL, rng=rng, registry=registry)


# 6x6: a buildable pocket, a spawn strip, a background border row (the
# background row backfills into spawning once unlocked, exercising the
# "rolled even though BACKGROUND at init" rule below).
ROWS = ["bb" + "c" * 4] * 2 + ["c" * 6] * 2 + ["s" * 6] + ["f" * 6]


class TestSpawnDecoRoll(unittest.TestCase):

    def test_no_rng_or_no_registry_rolls_nothing(self):
        """The fixture mode every pre-existing headless test runs in: every
        roll stays -1, so the emitter draws nothing."""
        for kwargs in ({}, {"rng": random.Random(1)}, {"registry": REGISTRY}):
            tm = synth(ROWS, **kwargs)
            rolls = {t.spawn_deco_roll for t in tm.all_tiles()}
            self.assertEqual(rolls, {-1}, kwargs)

    def test_background_tiles_are_rolled_too(self):
        """Unlike the condition roll, BACKGROUND tiles ARE rolled: they are
        exactly what later backfills into SPAWNING, and nothing re-rolls them
        at that point."""
        tm = synth(ROWS, rng=random.Random(1), registry=REGISTRY)
        bg = [t for t in tm.all_tiles() if t.state == TileState.BACKGROUND]
        self.assertTrue(bg)
        self.assertTrue(any(t.spawn_deco_roll >= 0 for t in bg))

    def test_density_lands_near_tree_chance_over_a_large_grid(self):
        tm = synth(["s" * 200] * 200, base=(0, 0),
                   rng=random.Random(42), registry=REGISTRY)
        tiles = list(tm.all_tiles())
        n_rolled = sum(1 for t in tiles if t.spawn_deco_roll >= 0)
        fraction = n_rolled / len(tiles)
        self.assertAlmostEqual(
            fraction, MAPBAL["SpawnDeco"]["tree_chance"], delta=0.02)

    def test_flip_bit_produces_both_orientations(self):
        tm = synth(["s" * 200] * 200, base=(0, 0),
                   rng=random.Random(3), registry=REGISTRY)
        flips = {t.spawn_deco_roll % 2 for t in tm.all_tiles()
                 if t.spawn_deco_roll >= 0}
        self.assertEqual(flips, {0, 1})

    def test_reserve_marked_background_draws_before_it_is_released(self):
        """A BACKGROUND cell the designer marked as a FUTURE spawn tile
        (`spawnable_background`) is rolled exactly like every other tile, and
        its tree draws WHILE IT IS STILL BACKGROUND — the painted reserve
        wears the whole treeline up front rather than growing in batch by
        batch — then carries that same tree over when the reserve releases it
        into the band."""
        marks = {(c, 5): 1 for c in range(6)}
        doc = tilemap.TileMapDoc(
            map_id="synthreserve", display_name="Synth Reserve",
            cols=6, rows=6, legend={}, terrain=[list(r) for r in ROWS],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            spawnable_background=dict(marks))
        tm = TileMap(doc, MAPBAL, rng=random.Random(9), registry=REGISTRY)

        marked = [tm.get(c, r) for (c, r) in marks]
        self.assertTrue(all(t.state == TileState.BACKGROUND for t in marked))
        self.assertTrue(all(t.spawn_reserved for t in marked))
        rolled = [t for t in marked if t.spawn_deco_roll >= 0]
        self.assertTrue(rolled, "no reserve-marked cell carries a tree roll")
        expected = {(t.col, t.row) for t in rolled}
        # drawn already, while still background...
        before = spawn_deco_render_items(tm, 0, tm.cols - 1, 5, 5, TREE_SLOTS)
        self.assertEqual({i.world_pos for i in before}, expected)
        # ...and unchanged once they join the band
        for tile in marked:
            tm.set_tile_state(tile, TileState.SPAWNING)
        items = spawn_deco_render_items(tm, 0, tm.cols - 1, 5, 5, TREE_SLOTS)
        self.assertEqual({i.world_pos for i in items}, expected)

    def test_reserve_tree_is_gone_once_the_tile_reaches_combat(self):
        """`spawn_reserved` never overrides the LIVE state read: a released
        reserve tile that goes on to COMBAT stops emitting, flag or no flag."""
        marks = {(c, 5): 1 for c in range(6)}
        doc = tilemap.TileMapDoc(
            map_id="synthreserve2", display_name="Synth Reserve 2",
            cols=6, rows=6, legend={}, terrain=[list(r) for r in ROWS],
            base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[],
            spawnable_background=dict(marks))
        tm = TileMap(doc, MAPBAL, rng=random.Random(9), registry=REGISTRY)
        for (c, r) in marks:
            tm.set_tile_state(tm.get(c, r), TileState.COMBAT)
        self.assertEqual(
            spawn_deco_render_items(tm, 0, tm.cols - 1, 5, 5, TREE_SLOTS), [])

    def test_unmarked_background_still_draws_nothing(self):
        """The flag is what widens the emitter, not BACKGROUND itself — an
        unpainted background tile keeps its roll waiting and draws nothing."""
        tm = synth(ROWS, rng=random.Random(4), registry=REGISTRY)
        bg = [t for t in tm.all_tiles()
              if t.state == TileState.BACKGROUND and t.spawn_deco_roll >= 0]
        self.assertTrue(bg)
        self.assertFalse(any(t.spawn_reserved for t in bg))
        drawn = {i.world_pos for i in spawn_deco_render_items(
            tm, 0, tm.cols - 1, 0, tm.rows - 1, TREE_SLOTS)}
        self.assertFalse(drawn & {(t.col, t.row) for t in bg})

    def test_no_tree_family_leaves_every_roll_at_minus_one(self):
        """A registry with no Props/Tree group must not crash a boot."""
        doc = {"categories": [{
            "key": DECO_CATEGORY, "display_name": "X",
            "frame_w": 64, "frame_h": 96, "animations": ["idle"],
            "groups": [{"label": "Props", "children": [
                {"label": "Rock", "slots": ["deco_rock"]}]}],
        }]}
        tm = synth(ROWS, rng=random.Random(1), registry=SlotRegistry(doc))
        rolls = {t.spawn_deco_roll for t in tm.all_tiles()}
        self.assertEqual(rolls, {-1})


class TestSpawnTreeFamily(unittest.TestCase):
    """`spawn_tree_slots` — the ONE definition both consumers share."""

    # A family that DOES carry the excluded variants, unlike REGISTRY_DOC.
    FULL = SlotRegistry({"categories": [{
        "key": DECO_CATEGORY, "display_name": "Deco",
        "frame_w": 64, "frame_h": 96, "animations": ["idle"],
        "groups": [{"label": "Props", "children": [
            {"label": "Tree", "slots": [
                "deco_tree", "deco_tree_v6", "deco_tree_v7",
                "deco_tree_v8", "deco_tree_v9"]},
        ]}],
    }]})

    def test_excluded_variants_are_filtered_out(self):
        self.assertEqual(spawn_tree_slots(self.FULL),
                         ("deco_tree", "deco_tree_v9"))

    def test_registry_order_is_preserved_for_the_survivors(self):
        """The roll is an INDEX into this tuple, so its order is load-bearing:
        a reordering would silently repaint every tile on an existing map."""
        family = spawn_tree_slots(self.FULL)
        raw = self.FULL.group_slots(DECO_CATEGORY, SPAWN_DECO_GROUP)
        self.assertEqual(list(family), [s for s in raw if s in family])

    def test_missing_group_degrades_to_empty(self):
        doc = {"categories": [{
            "key": DECO_CATEGORY, "display_name": "X",
            "frame_w": 64, "frame_h": 96, "animations": ["idle"],
            "groups": [{"label": "Props", "children": [
                {"label": "Rock", "slots": ["deco_rock"]}]}],
        }]}
        self.assertEqual(spawn_tree_slots(SlotRegistry(doc)), ())

    def test_no_excluded_variant_can_ever_be_emitted(self):
        """The end-to-end guarantee: roll sized against the filtered family,
        emitter indexing the same one, so no excluded slot reaches a
        RenderItem — the property the two-source version could not offer."""
        tm = synth(ROWS, rng=random.Random(4), registry=self.FULL)
        items = spawn_deco_render_items(
            tm, 0, tm.cols - 1, 0, tm.rows - 1, spawn_tree_slots(self.FULL))
        self.assertTrue(items)   # guard: an empty list would pass vacuously
        self.assertFalse(
            {i.slot_key for i in items} & SPAWN_TREE_EXCLUDED)


class TestSpawnDecoRenderItems(unittest.TestCase):

    def setUp(self):
        self.tm = synth(ROWS, rng=random.Random(4), registry=REGISTRY)

    def test_layer_sits_above_entities(self):
        self.assertEqual(LAYER, "deco")
        self.assertLess(LAYERS.index("entities"), LAYERS.index(LAYER))

    def test_spawning_tile_with_a_roll_emits_exactly_one_item(self):
        tile = next(t for t in self.tm.all_tiles()
                    if t.state == TileState.SPAWNING and t.spawn_deco_roll >= 0)
        items = spawn_deco_render_items(
            self.tm, tile.col, tile.col, tile.row, tile.row, TREE_SLOTS)
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item.layer, "deco")
        self.assertEqual(item.world_pos, (tile.col, tile.row))

    def test_conversion_to_combat_stops_the_emission(self):
        """The headline requirement: a spawning tile's tree vanishes the
        instant it becomes COMBAT — no re-roll, no `set_tile_state` hook,
        just the emitter reading `tile.state` live."""
        tile = next(t for t in self.tm.all_tiles()
                    if t.state == TileState.SPAWNING and t.spawn_deco_roll >= 0)
        before = spawn_deco_render_items(
            self.tm, tile.col, tile.col, tile.row, tile.row, TREE_SLOTS)
        self.assertEqual(len(before), 1)

        self.tm.set_tile_state(tile, TileState.COMBAT)
        after = spawn_deco_render_items(
            self.tm, tile.col, tile.col, tile.row, tile.row, TREE_SLOTS)
        self.assertEqual(after, [])
        # The roll itself is untouched — set_tile_state never writes it.
        self.assertGreaterEqual(tile.spawn_deco_roll, 0)

    def test_backfilled_background_tile_emits_once_spawning(self):
        """A BACKGROUND tile that recedes into play (spawn-band backfill)
        emits its pre-rolled tree the moment it becomes SPAWNING — the
        treeline follows the receding band."""
        tile = next(t for t in self.tm.all_tiles()
                    if t.state == TileState.BACKGROUND and t.spawn_deco_roll >= 0)
        before = spawn_deco_render_items(
            self.tm, tile.col, tile.col, tile.row, tile.row, TREE_SLOTS)
        self.assertEqual(before, [])

        self.tm.set_tile_state(tile, TileState.SPAWNING)
        after = spawn_deco_render_items(
            self.tm, tile.col, tile.col, tile.row, tile.row, TREE_SLOTS)
        self.assertEqual(len(after), 1)

    def test_column_rides_every_item_and_defaults_to_none(self):
        # N2: an OPAQUE master-sheet column (the host drives it from
        # RunState.season) rides every emitted item. Default None ("no live
        # column"), never 0 — 0 is a real column, i.e. the first season.
        items = spawn_deco_render_items(
            self.tm, 0, self.tm.cols - 1, 0, self.tm.rows - 1, TREE_SLOTS,
            column=2)
        self.assertTrue(items)   # guard: an empty list would pass vacuously
        self.assertTrue(all(i.column == 2 for i in items))
        plain = spawn_deco_render_items(
            self.tm, 0, self.tm.cols - 1, 0, self.tm.rows - 1, TREE_SLOTS)
        self.assertTrue(all(i.column is None for i in plain))

    def test_no_tree_slots_emits_nothing(self):
        self.assertEqual(
            spawn_deco_render_items(self.tm, 0, self.tm.cols - 1,
                                    0, self.tm.rows - 1, ()),
            [])

    def test_windowed_and_clamped_to_the_map(self):
        items = spawn_deco_render_items(self.tm, 2, 3, 0, 5, TREE_SLOTS)
        for item in items:
            col, row = item.world_pos
            self.assertTrue(2 <= col <= 3)
        # An out-of-bounds window clamps instead of raising.
        full = spawn_deco_render_items(self.tm, -50, 500, -50, 500, TREE_SLOTS)
        self.assertEqual(
            len(full),
            len(spawn_deco_render_items(self.tm, 0, self.tm.cols - 1,
                                        0, self.tm.rows - 1, TREE_SLOTS)))

    def test_tile_outside_the_window_emits_nothing(self):
        """A window that does not cover the tile's column never emits it,
        regardless of what else the neighbouring column carries."""
        tile = next(t for t in self.tm.all_tiles()
                    if t.state == TileState.SPAWNING and t.spawn_deco_roll >= 0)
        other_col = (tile.col + 1) % self.tm.cols
        if other_col == tile.col:
            self.skipTest("map too small to pick a distinct column")
        items = spawn_deco_render_items(
            self.tm, other_col, other_col, tile.row, tile.row, TREE_SLOTS)
        self.assertNotIn((tile.col, tile.row), {i.world_pos for i in items})

    def test_short_tree_slots_tuple_still_resolves(self):
        """The `% len` guard: a manifest-filtered family smaller than the
        registry family the roll was sized against must still resolve."""
        tm = synth(["s" * 20] * 20, base=(0, 0),
                   rng=random.Random(9), registry=REGISTRY)
        short = TREE_SLOTS[:1]
        items = spawn_deco_render_items(
            tm, 0, tm.cols - 1, 0, tm.rows - 1, short)
        self.assertTrue(items)
        self.assertEqual({i.slot_key for i in items}, set(short))

    def test_animation_phase_is_deterministic_and_per_cell(self):
        a = spawn_deco_render_items(self.tm, 0, self.tm.cols - 1,
                                    0, self.tm.rows - 1, TREE_SLOTS,
                                    anim_time_ms=1000)
        b = spawn_deco_render_items(self.tm, 0, self.tm.cols - 1,
                                    0, self.tm.rows - 1, TREE_SLOTS,
                                    anim_time_ms=1000)
        self.assertEqual([i.anim_time_ms for i in a],
                         [i.anim_time_ms for i in b])
        if len(a) > 1:
            self.assertGreater(len({i.anim_time_ms for i in a}), 1)


if __name__ == "__main__":
    unittest.main()
