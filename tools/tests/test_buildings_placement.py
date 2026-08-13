"""Phase 9D: building placement seam (game/buildings/registry.py).

place_building wires a building through the 9C seams: tile occupant/content_key/
state, Scene.spawn, and TileMap.sync_occupancy into engine.physics.TileOccupancy.
It rejects non-buildable tiles and insufficient love. A placed building then
satisfies the pathfinder's duck-typed occupant contract (replacing the
SimpleNamespace stubs test_pathfinder uses).
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene, SpriteAnimator
from engine.physics import TileOccupancy
from game.buildings import PlacementError, place_building
from game.buildings.components import TierState
from game.core.balance import load_balance
from game.core.game_state import RunState
from game.map import find_path_to_nearest_defence
from game.map.tile_map import TileMap
from game.map.tiles import TileState

CORE = load_balance(FIXTURE_DATA, "core")

MAPBAL = load_balance(FIXTURE_DATA, "map")
BAL = load_balance(FIXTURE_DATA, "buildings")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


class TestPlacement(unittest.TestCase):
    def test_place_wires_all_seams(self):
        tm = synth(["bbb", "bbb", "bbb"])
        scene, occ = Scene(), TileOccupancy()
        tile = tm.get(1, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)

        building, cost = place_building(
            tm, tile, "defence", 9999, BAL, scene, occ)

        self.assertIs(tile.occupant, building)
        self.assertEqual(tile.content_key, "defence_building")
        self.assertEqual(tile.state, TileState.BUILT)
        self.assertEqual(occ.get((1, 0)), building)
        self.assertEqual(
            cost, BAL["DefenceBuildings"]["BasicDefence"]["tiers"][0]["build_cost"])
        # spawned into the scene (queued -> live after an update tick)
        scene.update(0.0)
        self.assertIn(building, scene.by_tag("combat"))

    def test_economic_content_key(self):
        tm = synth(["bbb", "bbb", "bbb"])
        _, occ = Scene(), TileOccupancy()
        b, _c = place_building(tm, tm.get(2, 1), "economic", 9999, BAL,
                               Scene(), occ)
        self.assertEqual(tm.get(2, 1).content_key, "economic_building")
        self.assertEqual(b.building_type, "economic")

    def test_reject_non_buildable(self):
        tm = synth(["bbb", "bbb", "bbb"])  # base (0,0) is BUILT, not BUILDABLE
        with self.assertRaises(PlacementError):
            place_building(tm, tm.get(0, 0), "defence", 9999, BAL,
                           Scene(), TileOccupancy())

    def test_reject_insufficient_love(self):
        tm = synth(["bbb", "bbb", "bbb"])
        with self.assertRaises(PlacementError):
            place_building(tm, tm.get(1, 1), "defence", 0, BAL,
                           Scene(), TileOccupancy())
        # tile untouched by the failed placement
        self.assertEqual(tm.get(1, 1).state, TileState.BUILDABLE)
        self.assertIsNone(tm.get(1, 1).occupant)

    def test_pathfinder_targets_placed_defence(self):
        # A real placed Defender is a valid goal for find_path_to_nearest_defence.
        tm = synth(["bbbbb", "bbbbb", "bbbbb"], base=(0, 0))
        scene, occ = Scene(), TileOccupancy()
        place_building(tm, tm.get(4, 2), "defence", 9999, BAL, scene, occ)
        path = find_path_to_nearest_defence(tm, 0, 2)
        self.assertTrue(path)
        self.assertEqual(path[0], (0, 2))
        self.assertEqual(path[-1], (4, 2))

    def test_places_at_the_researched_tier(self):
        """Once tier 2 (index 1) is researched, a FRESH placement builds a
        Slinger directly -- not a Stone Thrower -- and charges tier 1's own
        build_cost, not tier 0's."""
        tm = synth(["bbb", "bbb", "bbb"])
        scene, occ = Scene(), TileOccupancy()
        state = RunState.from_balance(CORE, BAL)
        state.tiers_unlocked["defence"] = 2  # tier index 1 researched
        tier1_cost = BAL["DefenceBuildings"]["BasicDefence"]["tiers"][1]["build_cost"]
        state.love = tier1_cost

        building, cost = place_building(
            tm, tm.get(1, 1), "defence", state.love, BAL, scene, occ,
            state=state)

        self.assertEqual(cost, tier1_cost)
        self.assertNotEqual(cost,
            BAL["DefenceBuildings"]["BasicDefence"]["tiers"][0]["build_cost"])
        self.assertEqual(building.get_component(TierState).current_tier, 1)

    def test_state_none_still_places_at_tier_zero(self):
        """Logic tests that predate RunState (state=None) keep today's
        tier-0-only placement behavior."""
        tm = synth(["bbb", "bbb", "bbb"])
        scene, occ = Scene(), TileOccupancy()
        building, cost = place_building(
            tm, tm.get(1, 1), "defence", 9999, BAL, scene, occ, state=None)
        self.assertEqual(
            cost, BAL["DefenceBuildings"]["BasicDefence"]["tiers"][0]["build_cost"])
        self.assertEqual(building.get_component(TierState).current_tier, 0)


class TestColourColumn(unittest.TestCase):
    """MasterSheetColumnsPLAN B1: a placement stamps the master-sheet colour
    column onto the building's animator, and it is COLOUR that survives every
    later upgrade. The capability map is built in-test — live `data/` declares
    no `columns` yet, and a test must never assert against live art anyway.
    """
    # A Stone Thrower places at tier 0 / level 1 (defender.TIER_SPRITES[0]).
    SLOT = "stone_thrower_t1_lvl1"
    COLOURS = {SLOT: ("red", "green", "blue")}

    def _place(self, **kwargs):
        tm = synth(["bbb", "bbb", "bbb"])
        scene, occ = Scene(), TileOccupancy()
        building, _cost = place_building(
            tm, tm.get(1, 1), "defence", 9999, BAL, scene, occ, **kwargs)
        return building, scene

    def test_roll_lands_inside_the_slots_colour_count(self):
        # Seeded (game/CLAUDE.md): the outcome depends on the draw.
        building, _ = self._place(colour_columns=self.COLOURS,
                                  rng=random.Random(1234))
        anim = building.get_component(SpriteAnimator)
        self.assertEqual(anim.slot_key, self.SLOT)
        self.assertIn(anim.column, range(len(self.COLOURS[self.SLOT])))

    def test_slot_without_colours_keeps_the_minus_one_sentinel(self):
        # Both the "no map at all" default (which is what keeps every caller
        # that predates B1 byte-identical) and a map that simply does not name
        # this slot. -1 means "no driver"; 0 would be a REAL colour.
        for kwargs in ({}, {"colour_columns": {"some_other_slot": ("red",)}}):
            with self.subTest(kwargs=kwargs):
                building, _ = self._place(**kwargs)
                self.assertEqual(
                    building.get_component(SpriteAnimator).column, -1)

    def test_explicit_column_wins_over_the_roll_and_zero_is_honoured(self):
        # B2's swatch pick: the chosen colour is placed verbatim, no draw. 0 is
        # a real colour index, so it must survive the `is not None` test.
        for chosen in (0, 2):
            with self.subTest(column=chosen):
                building, _ = self._place(colour_columns=self.COLOURS,
                                          rng=random.Random(1234),
                                          column=chosen)
                self.assertEqual(
                    building.get_component(SpriteAnimator).column, chosen)

    def test_colour_survives_a_level_up_and_a_tier_advance(self):
        building, _ = self._place(colour_columns=self.COLOURS, column=2)
        anim = building.get_component(SpriteAnimator)

        self.assertTrue(building.upgrade())          # level change
        self.assertEqual(anim.slot_key, "stone_thrower_t1_lvl2")
        self.assertEqual(anim.column, 2)

        self.assertTrue(building.advance_tier())     # tier change
        self.assertEqual(anim.slot_key, "slinger_t2_lvl1")
        self.assertEqual(anim.column, 2)

    def test_submitted_render_item_carries_the_column(self):
        building, scene = self._place(colour_columns=self.COLOURS, column=1)
        scene.update(0.0)  # queued -> live
        items = [i for i in scene.render_items() if i.slot_key == self.SLOT]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].column, 1)


if __name__ == "__main__":
    unittest.main()
