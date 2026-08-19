"""SaveGamePLAN SG-3: generic Building save/restore round-trip.

registry.save_building()/restore_building() are built on the engine's
existing generic GameObject/Component serialization (engine/core) — this
tests that every one of the twelve LEAF_CLASSES types round-trips every
component field exactly, including a damaged (non-full) HP value that a
fresh construction would NOT produce (apply_tier_stats always full-heals),
proving the "restore overwrites the fresh instance's derived stats" ordering
actually works.
"""
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from game.buildings import registry
from game.buildings.components import Nameplate, RoundStats, TierState
from game.buildings.research import LEAF_CLASSES
from game.core.balance import load_balance
from engine.core import Health
from game.map.tile_map import TileMap

BAL = load_balance(FIXTURE_DATA, "buildings")
MAPBAL = load_balance(FIXTURE_DATA, "map")


def _synth_tilemap():
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth", cols=5, rows=5, legend={},
        terrain=[list("bbbbb") for _ in range(5)],
        base={"col": 0, "row": 0, "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def _mutate(building):
    """Push every component to a non-default value so the round-trip has
    something real to prove."""
    health = building.get_component(Health)
    health.hp = max(1, health.max_hp - 2)
    tier = building.get_component(TierState)
    if tier.current_level_in_tier < building.tier_data()["levels"]:
        tier.current_level_in_tier += 1
    nameplate = building.get_component(Nameplate)
    nameplate.custom_name = "Ol' Reliable"
    round_stats = building.get_component(RoundStats)
    round_stats.dmg_dealt_last_round = 42


class TestBuildingRoundTrip(unittest.TestCase):
    def setUp(self):
        self.tilemap = _synth_tilemap()

    def test_every_leaf_type_round_trips_every_component_field(self):
        for building_type in LEAF_CLASSES:
            with self.subTest(building_type=building_type):
                building = registry.create(building_type, 2, 2, BAL)
                _mutate(building)

                data = registry.save_building(building)
                restored = registry.restore_building(data, self.tilemap, BAL)

                self.assertEqual(restored.id, building.id)
                self.assertEqual(restored.building_type, building_type)
                self.assertEqual(restored.col, building.col)
                self.assertEqual(restored.row, building.row)

                by_type = {type(c).__name__: c for c in building.components}
                for r_comp in restored.components:
                    type_name = type(r_comp).__name__
                    orig = by_type[type_name]
                    for field_name in r_comp._fields:
                        self.assertEqual(
                            getattr(r_comp, field_name),
                            getattr(orig, field_name),
                            f"{building_type}.{type_name}.{field_name}")

    def test_damaged_hp_survives_the_full_heal_that_apply_tier_stats_does(self):
        """The ordering guarantee this whole helper exists for: apply_tier_
        stats() (called twice inside restore_building, once by create() and
        once after the condition stamp) always full-heals, so a correct
        restore must OVERWRITE that with the saved (damaged) hp afterward."""
        building = registry.create("defence", 1, 1, BAL)
        full_hp = building.get_component(Health).max_hp
        building.get_component(Health).hp = 1
        self.assertNotEqual(building.get_component(Health).hp, full_hp)

        data = registry.save_building(building)
        restored = registry.restore_building(data, self.tilemap, BAL)

        self.assertEqual(restored.get_component(Health).hp, 1)
        self.assertEqual(restored.get_component(Health).max_hp, full_hp)


class TestSchemaDrift(unittest.TestCase):
    def test_a_saved_component_with_no_live_match_raises(self):
        building = registry.create("defence", 1, 1, BAL)
        data = registry.save_building(building)
        data["gameobject"]["components"].append(
            {"type": "NotARealComponent", "fields": {}})

        with self.assertRaises(ValueError):
            registry.restore_building(data, _synth_tilemap(), BAL)


if __name__ == "__main__":
    unittest.main()
