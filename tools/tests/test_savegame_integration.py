"""SaveGamePLAN SG-5: the full save-assembly chain, end to end.

Exercises the SAME sequence game/main.py's ``_autosave`` helper runs —
RunState.to_dict + Session.to_dict + TileMap.save_state + save_building per
building (including one mid-move) + savegame.add_slot — against a real,
multi-building world, then reloads the slot and confirms every piece comes
back. This is NOT a drive of the actual pygame frame loop (SG-7's live
Quick Test covers that); it pins that the pieces SG-1..SG-4 built actually
compose correctly when assembled the way the host assembles them.
"""
import tempfile
import types
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap as enginemap
from engine.physics import TileOccupancy
from engine.core import Health, Scene
from game.buildings import registry
from game.buildings.registry import save_building
from game.core import savegame
from game.core.balance import load_balance
from game.core.game_state import RunState
from game.core.phases import GamePhase, GameState
from game.core.session import Session
from game.enemies.spawner import Spawner
from game.map.tile_map import TileMap

CORE = load_balance(FIXTURE_DATA, "core")
MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILDINGS_BAL = load_balance(FIXTURE_DATA, "buildings")
ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")


def _doc():
    rows = ["bbbbbbbb"] * 8
    return enginemap.TileMapDoc(
        map_id="synth", display_name="Synth", cols=8, rows=8, legend={},
        terrain=[list(r) for r in rows],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[])


class TestFullAssemblyRoundTrip(unittest.TestCase):
    def test_multi_building_world_survives_save_and_reload(self):
        doc = _doc()
        tile_map = TileMap(doc, MAPBAL)
        occupancy = TileOccupancy()
        scene = Scene()
        spawner = Spawner()
        session = Session.create(spawner, tile_map, ENEMIES_BAL, CORE,
                                 BUILDINGS_BAL, occupancy=occupancy)

        placed, _cost = registry.place_building(
            tile_map, tile_map.get(2, 0), "defence", 99999, BUILDINGS_BAL,
            scene, occupancy, state=session.state)
        placed.get_component(Health).hp -= 3

        # A building mid-move is a REAL Building (despawned, held alive only
        # by moving_orders) - never placed on a tile, matching game/buildings
        # /CLAUDE.md's "represented by ABSENCE" Building Movement design.
        mover = registry.create("economic", 5, 5, BUILDINGS_BAL)
        tile_map.moving_orders.append(types.SimpleNamespace(
            building=mover, from_col=4, from_row=4, to_col=5, to_row=5,
            rounds_left=1))

        session.state.round_num = 5
        session.state.phase = GamePhase.BUILDING
        session.state.state = GameState.GAMEPLAY
        session.state.love = 250

        buildings = [t.occupant for t in tile_map.built_tiles()
                    if t.occupant is not None
                    and t.occupant.building_type != "base"]
        buildings += [order.building for order in tile_map.moving_orders]

        slot_doc = savegame.make_slot_doc(
            slot_id=savegame.new_slot_id(),
            map_id="synth",
            round_num=session.state.round_num,
            run_state=session.state.to_dict(buildings=buildings),
            session=session.to_dict(),
            tile_map=tile_map.save_state(),
            buildings=[save_building(b) for b in buildings],
        )

        with tempfile.TemporaryDirectory() as tmp:
            index_doc, evicted = savegame.add_slot(tmp, slot_doc, FIXTURE_DATA)
            self.assertIsNone(evicted)
            loaded = savegame.load_slot(
                savegame.slot_path(tmp, slot_doc["slot_id"]), FIXTURE_DATA)

        self.assertEqual(loaded["round_num"], 5)
        self.assertEqual(loaded["run_state"]["love"], 250)
        self.assertEqual(len(loaded["buildings"]), 2)  # the defence + the mover
        by_type = {b["building_type"] for b in loaded["buildings"]}
        self.assertIn("defence", by_type)
        self.assertEqual(len(loaded["tile_map"]["moving_orders"]), 1)
        self.assertEqual(loaded["tile_map"]["moving_orders"][0]["building_id"],
                         mover.id)


if __name__ == "__main__":
    unittest.main()
