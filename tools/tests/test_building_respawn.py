"""VfxAuthoringPLAN VA-4: the building_respawn cosmetic event.

Two halves, tested apart:
* payday's revive slot fills a new ledger — and ONLY for a building that was
  actually dead, not for the full-heal every living building gets in the same
  slot. That distinction is the whole content of the fill site.
* FloaterManager drains it into the trigger table.

Nothing here asserts an ORDERING change, because there is none: the ledger
append rides inside the existing step 9 and the sacrosanct payday order is
untouched.
"""
import os
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import random

from engine import data_io
from engine.assets.registry import SlotRegistry
from game import vfx_variants
from game.ui.effects import FloaterManager
from tools.tests.fixture_data import FIXTURE_DATA

VFX_BAL = data_io.load_json(FIXTURE_DATA / "balancing" / "vfx.json")
UI_BAL = data_io.load_json(FIXTURE_DATA / "balancing" / "ui.json")
CORE_BAL = data_io.load_json(FIXTURE_DATA / "balancing" / "core.json")


def _fm():
    return FloaterManager(UI_BAL, CORE_BAL, VFX_BAL)


class _State:
    """Only the attribute the drain reads."""

    def __init__(self, events):
        self.building_respawn_events = list(events)


class TestTheShippedRow(unittest.TestCase):
    def test_it_exists_and_is_not_inert(self):
        """Unlike defender_fire/projectile_hit, this event ships DOING
        something — the designer asked for a respawn effect, so an inert row
        would be a feature that is not there."""
        row = VFX_BAL["triggers"]["building_respawn"]
        self.assertEqual(row["procedural"], "spark_respawn")
        self.assertEqual(row["sprite_slot"], "")

    def test_the_respawn_spark_preset_exists(self):
        preset = VFX_BAL["procedural"]["spark"]["presets"]["respawn"]
        self.assertGreater(preset["count"], 0)
        self.assertGreater(preset["life"], 0)

    def test_the_kind_is_a_recognised_spark(self):
        """`_run_procedural` branches on membership in _SPARK_KINDS; a kind
        absent from it degrades to a silent no-op, which would make the row
        above a lie."""
        self.assertIn("spark_respawn", FloaterManager._SPARK_KINDS)


class TestDrain(unittest.TestCase):
    def test_it_emits_one_burst_per_revived_building(self):
        fm = _fm()
        state = _State([(1, 2, 0), (5, 6, 1)])
        fm.spawn_building_respawn_events(state)
        self.assertEqual(len(fm._vfx._particles),
                         2 * VFX_BAL["procedural"]["spark"]["presets"]
                         ["respawn"]["count"])

    def test_it_clears_the_ledger(self):
        fm = _fm()
        state = _State([(1, 2, 0)])
        fm.spawn_building_respawn_events(state)
        self.assertEqual(state.building_respawn_events, [])

    def test_an_empty_ledger_is_a_no_op(self):
        fm = _fm()
        state = _State([])
        fm.spawn_building_respawn_events(state)
        self.assertEqual(fm._vfx._particles, [])

    def test_it_bursts_at_the_tile_centre(self):
        fm = _fm()
        fm.spawn_building_respawn_events(_State([(3, 4, 0)]))
        self.assertTrue(fm._vfx._particles)
        for p in fm._vfx._particles:
            self.assertEqual((p.wx, p.wy), (3.5, 4.5))


class TestLevelVariantSelection(unittest.TestCase):
    """The reason this ledger carries a tier: it is the one event that can
    drive `level` mode without an object in hand."""

    REGISTRY = SlotRegistry({"categories": [{
        "key": "vfx", "display_name": "VFX", "frame_w": 64, "frame_h": 64,
        "animations": ["idle"],
        "groups": [{"label": "Effects", "children": [
            {"label": "Respawn",
             "slots": ["vfx_respawn", "vfx_respawn_v2", "vfx_respawn_v3"]},
        ]}],
    }]})

    def test_an_explicit_level_picks_the_variant(self):
        for tier, expected in ((0, "vfx_respawn"), (1, "vfx_respawn_v2"),
                               (2, "vfx_respawn_v3")):
            with self.subTest(tier=tier):
                self.assertEqual(
                    vfx_variants.resolve(self.REGISTRY, "vfx_respawn",
                                         vfx_variants.LEVEL, level=tier),
                    expected)

    def test_an_explicit_level_beats_a_source(self):
        """`level` is for a call site that knows the number without holding
        the object; when both are somehow present the explicit one wins."""
        class _Src:
            _enemy_era = 0

            def get_component(self, _cls):
                return None

        self.assertEqual(
            vfx_variants.resolve(self.REGISTRY, "vfx_respawn",
                                 vfx_variants.LEVEL, level=2, source=_Src()),
            "vfx_respawn_v3")

    def test_no_level_still_resolves_to_variant_zero(self):
        self.assertEqual(
            vfx_variants.resolve(self.REGISTRY, "vfx_respawn",
                                 vfx_variants.LEVEL, rng=random.Random(0)),
            "vfx_respawn")


class TestTheSlotIsRegistered(unittest.TestCase):
    def test_vfx_respawn_is_in_the_registry(self):
        from engine.assets.registry import load_registry
        registry = load_registry(FIXTURE_DATA)
        self.assertIn("vfx_respawn", registry.group_slots("vfx"))

    def test_it_is_selectable_as_a_trigger_binding(self):
        """The generated enum (VA-1/D2) has to have picked it up, or a
        designer could not bind art to the event they just got."""
        schema = data_io.load_json(
            FIXTURE_DATA / "schemas" / "vfx.schema.json")
        enum = schema["$defs"]["trigger_row"]["properties"]["sprite_slot"]["enum"]
        self.assertIn("vfx_respawn", enum)


if __name__ == "__main__":
    unittest.main()
