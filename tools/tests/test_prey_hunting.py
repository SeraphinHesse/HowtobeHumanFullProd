"""Chunk 3 + Chunk 4 — per-enemy terrain weights + prey hunting.

Bare-minimum tests, per the dispatch brief: a Raider (shipped
``hunts: "economic"``) must path to an off-route economy building instead of
walking straight at the base, and must choose the GEOMETRICALLY nearest one
even when a cost-cheaper one exists (D3's whole point — see
``game/map/CLAUDE.md``). Flow-field-sharing and the per-enemy-pond-weight
route change are pinned at the pure-pathfinder level in
``test_pathfinder.py::TestWeightProfiles``.
"""
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Movement, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.core import load_balance
from game.enemies import create_enemy
from game.enemies.components import PathAgent
from game.map.tile_map import TileMap
from game.map.tiles import TileCondition

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows, base=(0, 0)):
    tm = synth(rows, base)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


class TestRaiderHuntsEconomy(unittest.TestCase):
    def test_raider_paths_to_an_off_route_economy_building_not_the_base(self):
        # Base at (0,0); the straight route from the spawn (4,0) to the base
        # never touches row 1, so a "base" hunter's waypoints would never
        # reach the economy building sitting at (2,1).
        tm, scene, occ = build_board(["bbbbb", "bbbbb"])
        place_building(tm, tm.get(2, 1), "economic", 9999, BUILD, scene, occ)
        raider = create_enemy("raider", 4, 0, ENEM, tm, 0)
        scene.spawn(raider)
        scene.update(0.0)
        mv = raider.get_component(Movement)
        self.assertEqual(tuple(mv.waypoints[-1]), (2.0, 1.0))
        self.assertNotEqual(tuple(mv.waypoints[-1]), (0.0, 0.0))
        pa = raider.get_component(PathAgent)
        self.assertFalse(pa.goal_is_base)
        self.assertTrue(pa.repath_on_kill)
        self.assertEqual((pa.target_col, pa.target_row), (2, 1))

    def test_raider_picks_the_geometrically_nearest_economy_building(self):
        """D3's whole point: a pond-ringed NEAR building must still win over a
        cost-cheaper FAR one — a cost-only search (the bug Chunk 4 fixes)
        would pick the far building instead."""
        tm, scene, occ = build_board(["bbbbbbb"] * 5)
        near, _ = place_building(tm, tm.get(4, 2), "economic", 9999, BUILD,
                                 scene, occ)     # 2 tiles from the spawn
        far, _ = place_building(tm, tm.get(1, 2), "economic", 9999, BUILD,
                                scene, occ)      # 5 tiles from the spawn
        for c, r in ((5, 2), (3, 2), (4, 1), (4, 3)):   # moat around "near"
            tm.get(c, r).condition = TileCondition.POND
        raider = create_enemy("raider", 6, 2, ENEM, tm, 0)
        scene.spawn(raider)
        scene.update(0.0)
        pa = raider.get_component(PathAgent)
        self.assertEqual((pa.target_col, pa.target_row), (4, 2))
        self.assertTrue(near.alive and far.alive)


if __name__ == "__main__":
    unittest.main()
