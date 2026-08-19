"""SaveGamePLAN SG-6: `_apply_save_to_world`'s restore ordering.

`game.main._apply_save_to_world` is the piece `_load_save`/`_step_world`
call, and it is where the SG-4 ordering bug (a restored building needs its
tile's condition restored FIRST, but moving orders need buildings restored
FIRST) was actually found and fixed. This pins the fix directly, without
driving the full pygame frame loop (SG-7's live Quick Test covers that):
build a world, place a building + a mid-move building on a rolled-condition
tile, assemble a save doc the same way `_autosave` does, apply it onto a
SECOND fresh world, and confirm everything survived.
"""
import random
import types
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from engine.core import Health
from game.buildings import registry
from game.core.balance import load_balance
from game.core.phases import GamePhase, GameState
from game.main import _World, _apply_save_to_world
from game.map.tiles import TileState

CORE = load_balance(FIXTURE_DATA, "core")
MAP_BAL = load_balance(FIXTURE_DATA, "map")
BUILDINGS_BAL = load_balance(FIXTURE_DATA, "buildings")
ENEMIES_BAL = load_balance(FIXTURE_DATA, "enemies")


def _load_map(map_id):
    from engine import tilemap
    return tilemap.load_map(tilemap.map_path(FIXTURE_DATA, map_id),
                            tilemap.map_schema_path(FIXTURE_DATA))


class TestApplySaveToWorld(unittest.TestCase):
    def test_full_world_round_trips_through_a_second_world(self):
        map_doc = _load_map("first_light")
        world = _World(map_doc, MAP_BAL, ENEMIES_BAL, CORE, BUILDINGS_BAL,
                       registry=None)
        world.session.rng = random.Random(7)   # deterministic if consulted

        # Unlock a tile, place a building on it, damage it.
        tile = next(t for t in world.tile_map.buildable_tiles())
        building, _cost = registry.place_building(
            world.tile_map, tile, "defence", 99999, BUILDINGS_BAL,
            world.scene, world.occupancy, state=world.session.state)
        building.get_component(Health).hp -= 2

        # A building mid-move: real Building, despawned, held only by
        # moving_orders (never wired to a tile/occupancy/scene).
        mover = registry.create("economic", tile.col, tile.row, BUILDINGS_BAL)
        world.tile_map.moving_orders.append(types.SimpleNamespace(
            building=mover, from_col=0, from_row=0, to_col=1, to_row=1,
            rounds_left=1))

        world.session.state.round_num = 5
        world.session.state.phase = GamePhase.BUILDING
        world.session.state.state = GameState.GAMEPLAY
        world.session.state.love = 777
        world.session.combat_speed_idx = 2

        buildings = [t.occupant for t in world.tile_map.built_tiles()
                    if t.occupant is not None
                    and t.occupant.building_type != "base"]
        buildings += [o.building for o in world.tile_map.moving_orders]

        restore_data = {
            "map_id": map_doc.map_id,
            "run_state": world.session.state.to_dict(buildings=buildings),
            "session": world.session.to_dict(),
            "tile_map": world.tile_map.save_state(),
            "buildings": [registry.save_building(b) for b in buildings],
        }

        world2 = _World(map_doc, MAP_BAL, ENEMIES_BAL, CORE, BUILDINGS_BAL,
                        registry=None)
        restored = _apply_save_to_world(world2, restore_data, BUILDINGS_BAL)

        self.assertEqual(len(restored), 2)
        self.assertEqual(world2.session.state.round_num, 5)
        self.assertEqual(world2.session.state.love, 777)
        self.assertEqual(world2.session.combat_speed_idx, 2)

        tile2 = world2.tile_map.get(tile.col, tile.row)
        self.assertEqual(tile2.state, TileState.BUILT)
        self.assertIsNotNone(tile2.occupant)
        self.assertEqual(tile2.occupant.building_type, "defence")
        self.assertEqual(tile2.occupant.get_component(Health).hp,
                         building.get_component(Health).hp)
        self.assertEqual(world2.occupancy.get((tile.col, tile.row)),
                         tile2.occupant)

        self.assertEqual(len(world2.tile_map.moving_orders), 1)
        restored_mover = world2.tile_map.moving_orders[0].building
        self.assertEqual(restored_mover.building_type, "economic")
        self.assertEqual(restored_mover.id, mover.id)
        # never wired onto a tile - it is despawned, held only by the order
        self.assertNotEqual(tile2.occupant, restored_mover)


if __name__ == "__main__":
    unittest.main()
