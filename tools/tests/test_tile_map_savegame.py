"""SaveGamePLAN SG-4: TileMap.save_state()/apply_state() round-trip.

Only the runtime deltas from the deterministic legend baseline: zone-state
changes (unlock), the random condition/spawn-deco rolls, the stage-system
counters, and moving orders. Wall edges are deliberately NOT covered here —
save_state()'s docstring explains why (rebuild_walls() re-derives them for
free from each WallBuilder's own restored wall_snapshot).
"""
import types
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap as enginemap
from game.core.balance import load_balance
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAPBAL = load_balance(FIXTURE_DATA, "map")


def _synth_doc(rows, base=(0, 0)):
    return enginemap.TileMapDoc(
        map_id="synth", display_name="Synth", cols=len(rows[0]),
        rows=len(rows), legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])


class TestTileDeltaRoundTrip(unittest.TestCase):
    def test_unlocked_tile_survives_a_reload(self):
        doc = _synth_doc(["bbccc", "bbccc", "bbccc", "ccccc", "ccccc"])
        tm = TileMap(doc, MAPBAL)
        tile = tm.get(3, 0)
        self.assertEqual(tile.state, TileState.COMBAT)
        tm.set_tile_state(tile, TileState.BUILDABLE)

        data = tm.save_state()

        fresh = TileMap(doc, MAPBAL)
        fresh.apply_state(data, building_by_id={})

        self.assertEqual(fresh.get(3, 0).state, TileState.BUILDABLE)
        # an untouched tile stays at its legend baseline
        self.assertEqual(fresh.get(4, 4).state, TileState.COMBAT)

    def test_rolled_condition_survives_exactly_despite_a_different_rng_seed(self):
        import random
        doc = _synth_doc(["ccccc"] * 5)
        tm = TileMap(doc, MAPBAL, rng=random.Random(1))
        original = {(t.col, t.row): (t.condition, t.condition_variant_idx)
                   for t in tm.all_tiles()}

        data = tm.save_state()

        # A different seed would roll DIFFERENT conditions - apply_state must
        # overwrite them with the exact saved values regardless.
        fresh = TileMap(doc, MAPBAL, rng=random.Random(999))
        fresh.apply_state(data, building_by_id={})

        for t in fresh.all_tiles():
            self.assertEqual((t.condition, t.condition_variant_idx),
                             original[(t.col, t.row)], (t.col, t.row))

    def test_stage_system_counters_round_trip(self):
        doc = _synth_doc(["bbbbb"] * 5)
        tm = TileMap(doc, MAPBAL)
        tm._stage = 3
        tm._unlock_purchases = 7
        tm._retire_cursor = 2

        data = tm.save_state()
        fresh = TileMap(doc, MAPBAL)
        fresh.apply_state(data, building_by_id={})

        self.assertEqual(fresh._stage, 3)
        self.assertEqual(fresh._unlock_purchases, 7)
        self.assertEqual(fresh._retire_cursor, 2)


class TestMovingOrders(unittest.TestCase):
    def test_moving_order_round_trips_with_the_building_resolved_by_id(self):
        doc = _synth_doc(["bbbbb"] * 5)
        tm = TileMap(doc, MAPBAL)
        building = types.SimpleNamespace(id="building-uuid-1")
        tm.moving_orders.append(types.SimpleNamespace(
            building=building, from_col=0, from_row=0, to_col=2, to_row=2,
            rounds_left=2))

        data = tm.save_state()
        self.assertEqual(len(data["moving_orders"]), 1)
        self.assertEqual(data["moving_orders"][0]["building_id"], "building-uuid-1")

        fresh = TileMap(doc, MAPBAL)
        fresh.apply_state(data, building_by_id={"building-uuid-1": building})

        self.assertEqual(len(fresh.moving_orders), 1)
        order = fresh.moving_orders[0]
        self.assertIs(order.building, building)
        self.assertEqual((order.from_col, order.from_row, order.to_col,
                          order.to_row, order.rounds_left), (0, 0, 2, 2, 2))


if __name__ == "__main__":
    unittest.main()
