"""Phase 9D: building placement seam (game/buildings/registry.py).

place_building wires a building through the 9C seams: tile occupant/content_key/
state, Scene.spawn, and TileMap.sync_occupancy into engine.physics.TileOccupancy.
It rejects non-buildable tiles and insufficient love. A placed building then
satisfies the pathfinder's duck-typed occupant contract (replacing the
SimpleNamespace stubs test_pathfinder uses).
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import PlacementError, place_building
from game.core.balance import load_balance
from game.map import find_path_to_nearest_defence
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAPBAL = load_balance(REPO / "data", "map")
BAL = load_balance(REPO / "data", "buildings")


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


if __name__ == "__main__":
    unittest.main()
