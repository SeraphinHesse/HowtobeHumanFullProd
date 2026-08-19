"""SaveGamePLAN SG-2: RunState.to_dict()/from_dict() round-trip.

Pure logic — no disk I/O (that's test_savegame.py's job). Covers: every
save-column field round-trips exactly, every non-save-column field resets to
its dataclass default (D8), the round-boundary assertion, and the
mortar_slow_snapshot_ids id()<->uuid translation (D5) against real Building
objects.
"""
import unittest

from tools.tests.fixture_data import FIXTURE_DATA

from game.buildings import registry
from game.core.balance import load_balance
from game.core.game_state import RunState
from game.core.phases import GamePhase, GameState


def _non_default_state():
    return RunState(
        round_num=17,
        season=1,
        love=2500,
        base_lives=7,
        enemies_killed=40,
        buildings_placed=12,
        player_xp=88,
        village_level=3,
        xp_threshold=110,
        xp_threshold_inc=15,
        tiers_unlocked={"defence": 2, "economic": 1},
        unlocked_buildings={"defence": True, "economic": True,
                            "aoe_defence": False},
        lightning_level=2,
        boss_upgrade_stacks={"wall_cost_discount": 1},
        boss_upgrade_choices=[(1, "wall_cost_discount", "win")],
        love_spent_on_tiles=300,
        used_painter_tiles={(2, 3), (4, 5)},
        boss_lives_snapshot=9,
        boss_love_snapshot=1800,
        first_end_turn_cutscene_requested=True,
        tutorial_intros_shown=True,
        levelup_pending=True,
        # transient/never-serialized fields, set to prove they reset:
        phase_timer=1.5,
        income_events=[(0, 0, 5, "income")],
        log_events=["something happened"],
        payout_love_start=42.0,
    )


class TestRoundTrip(unittest.TestCase):
    def test_save_columns_round_trip_exactly(self):
        state = _non_default_state()
        data = state.to_dict()
        restored = RunState.from_dict(data)

        for field in (
            "round_num", "season", "love", "base_lives", "enemies_killed",
            "buildings_placed", "player_xp", "village_level", "xp_threshold",
            "xp_threshold_inc", "tiers_unlocked", "unlocked_buildings",
            "lightning_level", "boss_upgrade_stacks", "boss_upgrade_choices",
            "love_spent_on_tiles", "used_painter_tiles",
            "boss_lives_snapshot", "boss_love_snapshot",
            "first_end_turn_cutscene_requested", "tutorial_intros_shown",
            "levelup_pending",
        ):
            self.assertEqual(getattr(restored, field), getattr(state, field),
                             field)
        self.assertIs(restored.phase, GamePhase.BUILDING)
        self.assertIs(restored.state, GameState.GAMEPLAY)

    def test_transient_fields_reset_to_default(self):
        state = _non_default_state()
        restored = RunState.from_dict(state.to_dict())
        fresh = RunState()

        self.assertEqual(restored.phase_timer, fresh.phase_timer)
        self.assertEqual(restored.income_events, fresh.income_events)
        self.assertEqual(restored.log_events, fresh.log_events)
        self.assertEqual(restored.payout_love_start, fresh.payout_love_start)
        self.assertFalse(restored.scripted_leveling)

    def test_bare_run_state_round_trips(self):
        """A fresh run (already at the round boundary by default) survives
        the round-trip untouched."""
        state = RunState()
        restored = RunState.from_dict(state.to_dict())
        self.assertEqual(restored.round_num, state.round_num)
        self.assertEqual(restored.love, state.love)


class TestRoundBoundaryAssertion(unittest.TestCase):
    def test_wrong_phase_raises(self):
        state = RunState(phase=GamePhase.ENEMY)
        with self.assertRaises(ValueError):
            state.to_dict()

    def test_wrong_top_level_state_raises(self):
        state = RunState(state=GameState.GAME_OVER)
        with self.assertRaises(ValueError):
            state.to_dict()


class TestMortarSnapshotIdTranslation(unittest.TestCase):
    """D5: id(building) -> GameObject.id uuid on save, back to id() on load,
    against real Building objects (registry.create)."""

    def setUp(self):
        self.buildings_balance = load_balance(FIXTURE_DATA, "buildings")
        self.mortar_a = registry.create("aoe_defence", 0, 0,
                                        self.buildings_balance)
        self.mortar_b = registry.create("aoe_defence", 1, 0,
                                        self.buildings_balance)
        self.buildings = [self.mortar_a, self.mortar_b]

    def test_ids_translate_to_uuids_and_back(self):
        state = RunState(mortar_slow_snapshot_ids={id(self.mortar_a),
                                                    id(self.mortar_b)})
        data = state.to_dict(buildings=self.buildings)
        self.assertEqual(sorted(data["mortar_slow_snapshot_ids"]),
                         sorted([self.mortar_a.id, self.mortar_b.id]))

        restored = RunState.from_dict(data, buildings=self.buildings)
        self.assertEqual(restored.mortar_slow_snapshot_ids,
                         {id(self.mortar_a), id(self.mortar_b)})

    def test_a_snapshot_id_with_no_live_building_is_dropped(self):
        ghost_id = 999999999
        state = RunState(mortar_slow_snapshot_ids={id(self.mortar_a),
                                                    ghost_id})
        data = state.to_dict(buildings=self.buildings)
        self.assertEqual(data["mortar_slow_snapshot_ids"], [self.mortar_a.id])

    def test_no_buildings_supplied_drops_every_snapshot_id(self):
        state = RunState(mortar_slow_snapshot_ids={id(self.mortar_a)})
        data = state.to_dict()      # buildings=() default
        self.assertEqual(data["mortar_slow_snapshot_ids"], [])


if __name__ == "__main__":
    unittest.main()
