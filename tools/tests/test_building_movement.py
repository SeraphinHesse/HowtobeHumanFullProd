"""Building Movement: the move seam (game/buildings/movement.py).

Covers the three things the feature's correctness rests on:
1. the Manhattan (straight-line-only) + floor-divided cost/time formulas
   (and the two off-switches),
2. ``start_move``'s validation + the "a move in transit is represented by
   ABSENCE" contract — the origin goes back to plain BUILDABLE with no
   occupant, the building leaves the scene, and BOTH endpoints are barred from
   new construction while staying walkable,
3. the payday tick landing the building on its destination with its
   ``col``/``row`` caches AND its Transform following it.
"""
import inspect
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Scene
from engine.physics import TileOccupancy
from game.buildings import PlacementError, place_building
from game.buildings.movement import (
    MoveError, is_movable, move_cost, move_distance, move_time, process_moves,
    start_move,
)
from game.core.balance import load_balance
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAPBAL = load_balance(FIXTURE_DATA, "map")
BAL = load_balance(FIXTURE_DATA, "buildings")
MOVE = BAL["BuildingsGlobal"]["Movement"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def board():
    """A 6x6 all-buildable board with a Stone Thrower placed at (1, 1)."""
    tm = synth(["bbbbbb"] * 6)
    scene, occ = Scene(), TileOccupancy()
    building, _ = place_building(
        tm, tm.get(1, 1), "defence", 9999, BAL, scene, occ)
    scene.update(0.0)
    return tm, scene, occ, building


class TestFormula(unittest.TestCase):
    def test_distance_is_manhattan(self):
        self.assertEqual(move_distance(0, 0, 3, 0), 3)
        self.assertEqual(move_distance(0, 0, 0, 3), 3)
        # no diagonal shortcut — a move that changes both axes sums them,
        # it does not take the max of the two
        self.assertEqual(move_distance(0, 0, 3, 3), 6)
        self.assertEqual(move_distance(5, 5, 2, 4), 4)

    def test_worked_example_from_the_spec(self):
        """3 tiles at the shipped defaults (base 10 / +10 per 2 tiles, base 1
        round / +1 per 2 tiles) is 20 love and 2 rounds."""
        self.assertEqual(move_cost(3, MOVE), 20)
        self.assertEqual(move_time(3, MOVE), 2)

    def test_steps_floor_divide(self):
        bal = dict(MOVE, base_love_cost=10, love_cost_increase_increment=2,
                   love_cost_increase=10)
        self.assertEqual([move_cost(d, bal) for d in range(7)],
                         [10, 10, 20, 20, 30, 30, 40])

    def test_disabled_flags_zero_each_axis_independently(self):
        free = dict(MOVE, money_cost_enabled=False)
        self.assertEqual(move_cost(5, free), 0)
        self.assertEqual(move_time(5, free), move_time(5, MOVE))  # untouched
        instant = dict(MOVE, time_cost_enabled=False)
        self.assertEqual(move_time(5, instant), 0)
        self.assertEqual(move_cost(5, instant), move_cost(5, MOVE))


class TestStartMove(unittest.TestCase):
    def test_unowned_tiles_between_endpoints_count_like_any_other(self):
        """The straight-line span between a building's tile and its
        destination may cross tiles the player has not unlocked yet ('c' =
        TileState.COMBAT, not BUILDABLE/BUILT — Tile.is_unlocked is False).
        move_distance carries no tilemap/ownership check at all, so those
        tiles must cost exactly what an equal-span move over an
        all-BUILDABLE board costs — the quoted price/time depends only on
        the two endpoint coordinates, unowned tiles included or not."""
        mixed = synth([
            "bbbccc",
            "bbbccc",
            "bbbccc",
            "cccbbb",
            "cccbbb",
            "cccbbb",
        ])
        scene, occ = Scene(), TileOccupancy()
        b, _ = place_building(mixed, mixed.get(1, 1), "defence", 9999, BAL,
                              scene, occ)
        scene.update(0.0)
        cost, rounds = start_move(mixed, b, mixed.get(4, 4), MOVE, 9999,
                                  occ, scene)

        full_tm, full_scene, full_occ, full_b = board()
        full_cost, full_rounds = start_move(
            full_tm, full_b, full_tm.get(4, 4), MOVE, 9999, full_occ,
            full_scene)

        self.assertEqual((cost, rounds), (full_cost, full_rounds))
        self.assertEqual(cost, move_cost(move_distance(1, 1, 4, 4), MOVE))

    def test_in_transit_is_represented_by_absence(self):
        tm, scene, occ, b = board()
        cost, rounds = start_move(tm, b, tm.get(4, 1), MOVE, 9999, occ, scene)
        self.assertEqual((cost, rounds), (20, 2))
        scene.update(0.0)

        origin = tm.get(1, 1)
        # the origin is plain empty buildable ground again...
        self.assertIsNone(origin.occupant)
        self.assertIsNone(origin.content_key)
        self.assertEqual(origin.state, TileState.BUILDABLE)
        self.assertIsNone(occ.get((1, 1)))
        # ...and the building is out of every scene-tag sweep, which is what
        # stops combat/income/boosts seeing it with no guards of their own.
        self.assertNotIn(b, scene.by_tag("combat"))
        self.assertNotIn(b, scene.by_tag("building"))
        # the destination is untouched and still BUILDABLE
        self.assertEqual(tm.get(4, 1).state, TileState.BUILDABLE)

    def test_both_endpoints_are_barred_but_still_walkable(self):
        tm, scene, occ, b = board()
        start_move(tm, b, tm.get(4, 1), MOVE, 9999, occ, scene)
        self.assertTrue(tm.is_moving(1, 1))
        self.assertTrue(tm.is_moving(4, 1))
        self.assertFalse(tm.is_moving(2, 2))
        # BUILDABLE with no occupant == the ordinary buildable-tile weight, so
        # an enemy still paths straight through both endpoints.
        empty_elsewhere = tm.weight(tm.get(2, 2))
        for col, row in ((1, 1), (4, 1)):
            weight = tm.weight(tm.get(col, row))
            self.assertGreater(weight, 0)
            self.assertLess(weight, tm.impassable_weight)
            # identical to any other empty buildable tile — a move endpoint is
            # not a special pathfinding case, which is the whole point of
            # reusing BUILDABLE rather than adding a TileState member.
            self.assertEqual(weight, empty_elsewhere)

    def test_neither_endpoint_may_be_built_on(self):
        """The bar is enforced at ``place_building``, the single legal
        placement path — both endpoints are ordinary BUILDABLE tiles, so
        without this guard the player could simply build on the tile the
        moving building is headed for (or the one it just left)."""
        tm, scene, occ, b = board()
        start_move(tm, b, tm.get(4, 1), MOVE, 9999, occ, scene)
        for col, row in ((1, 1), (4, 1)):
            with self.assertRaises(PlacementError):
                place_building(tm, tm.get(col, row), "defence", 9999, BAL,
                               scene, occ)
        # an ordinary buildable tile is unaffected
        place_building(tm, tm.get(5, 5), "defence", 9999, BAL, scene, occ)

    def test_instant_move_records_no_order(self):
        tm, scene, occ, b = board()
        cost, rounds = start_move(tm, b, tm.get(4, 1),
                                  dict(MOVE, time_cost_enabled=False),
                                  9999, occ, scene)
        self.assertEqual(rounds, 0)
        self.assertEqual(tm.moving_orders, [])
        scene.update(0.0)
        self.assertEqual(tm.get(4, 1).state, TileState.BUILT)
        self.assertIs(tm.get(4, 1).occupant, b)
        self.assertEqual((b.col, b.row), (4, 1))
        self.assertIn(b, scene.by_tag("combat"))

    def test_rejects_a_non_buildable_destination(self):
        tm, scene, occ, b = board()
        other, _ = place_building(tm, tm.get(3, 3), "defence", 9999, BAL,
                                  scene, occ)
        with self.assertRaises(MoveError):
            start_move(tm, b, tm.get(3, 3), MOVE, 9999, occ, scene)

    def test_rejects_a_tile_already_in_a_move(self):
        tm, scene, occ, b = board()
        other, _ = place_building(tm, tm.get(3, 3), "defence", 9999, BAL,
                                  scene, occ)
        scene.update(0.0)
        start_move(tm, b, tm.get(4, 1), MOVE, 9999, occ, scene)
        with self.assertRaises(MoveError):
            start_move(tm, other, tm.get(4, 1), MOVE, 9999, occ, scene)

    def test_rejects_too_little_love(self):
        tm, scene, occ, b = board()
        with self.assertRaises(MoveError):
            start_move(tm, b, tm.get(4, 1), MOVE, 19, occ, scene)
        # nothing was touched by the refusal
        self.assertIs(tm.get(1, 1).occupant, b)
        self.assertEqual(tm.moving_orders, [])

    def test_a_wall_builder_can_never_be_moved(self):
        tm = synth(["bbbbbb"] * 6)
        scene, occ = Scene(), TileOccupancy()
        wb, _ = place_building(tm, tm.get(1, 1), "wall_builder", 9999, BAL,
                               scene, occ)
        scene.update(0.0)
        self.assertFalse(is_movable(wb))
        with self.assertRaises(MoveError):
            start_move(tm, wb, tm.get(4, 1), MOVE, 9999, occ, scene)
        self.assertIs(tm.get(1, 1).occupant, wb)


class TestProcessMoves(unittest.TestCase):
    def test_ticks_down_then_lands_the_building(self):
        tm, scene, occ, b = board()
        _cost, rounds = start_move(tm, b, tm.get(4, 1), MOVE, 9999, occ, scene)
        self.assertEqual(rounds, 2)

        process_moves(tm, occ, scene)          # round 1 of 2
        self.assertEqual(tm.moving_orders[0].rounds_left, 1)
        self.assertEqual(tm.get(4, 1).state, TileState.BUILDABLE)

        process_moves(tm, occ, scene)          # arrives
        scene.update(0.0)
        self.assertEqual(tm.moving_orders, [])
        self.assertFalse(tm.is_moving(1, 1))
        self.assertFalse(tm.is_moving(4, 1))

        dest = tm.get(4, 1)
        self.assertIs(dest.occupant, b)
        self.assertEqual(dest.content_key, b.CONTENT_KEY)
        self.assertEqual(dest.state, TileState.BUILT)
        self.assertEqual(occ.get((4, 1)), b)
        self.assertIn(b, scene.by_tag("combat"))

    def test_the_building_carries_its_coords_and_transform_with_it(self):
        tm, scene, occ, b = board()
        start_move(tm, b, tm.get(4, 3), MOVE, 9999, occ, scene)
        for _ in range(move_time(move_distance(1, 1, 4, 3), MOVE)):
            process_moves(tm, occ, scene)
        self.assertEqual((b.col, b.row), (4, 3))
        self.assertEqual((b.transform.wx, b.transform.wy), (4.0, 3.0))

    def test_no_orders_is_a_no_op(self):
        tm, scene, occ, b = board()
        process_moves(tm, occ, scene)
        self.assertIs(tm.get(1, 1).occupant, b)
        self.assertEqual(tm.moving_orders, [])


# ---------------------------------------------------------------------------
# BossUpgradeTimelinePLAN BU-3 3.2 — #4 `move_time_cap` (D14: the TIME dial)
# ---------------------------------------------------------------------------
#: Hand-pinned (BU-6): the cap a designer types in the new editor panel must
#: never decide whether this module is green — `data/CLAUDE.md`.
CAP = 1
BOSS_UPGRADES = {
    "BossUpgrades": {
        "Catalog": {
            "move_time_cap": {"name": "Quick Relocation", "description": "",
                              "params": {"move_time_cap": CAP}},
        },
        "Timeline": {"milestones": [
            {"slots": ["move_time_cap", None, None],
             "retaliation_bonus_love": 30},
        ] * 4},
    }
}

#: A move long enough that the uncapped formula exceeds the cap — derived,
#: never a literal, so a Movement retune cannot strand these assertions.
LONG = next(d for d in range(1, 500)
            if move_time(d, MOVE) > CAP)


class _StubRunState:
    """`move_time` reads exactly one thing off the RunState (the stack dict,
    via `boss_upgrades.stack_count`); a real one would need core/buildings
    balancing this module does not otherwise load."""

    def __init__(self, picks=0):
        self.boss_upgrade_stacks = {"move_time_cap": picks} if picks else {}


class TestMoveTimeCapBossUpgrade(unittest.TestCase):
    def test_no_pair_is_byte_identical(self):
        want = move_time(LONG, MOVE)
        self.assertEqual(move_time(LONG, MOVE, None, None), want)
        self.assertEqual(move_time(LONG, MOVE, _StubRunState(1), None), want)
        self.assertEqual(move_time(LONG, MOVE, None, BOSS_UPGRADES), want)

    def test_an_unpicked_upgrade_leaves_the_duration_alone(self):
        self.assertEqual(
            move_time(LONG, MOVE, _StubRunState(0), BOSS_UPGRADES),
            move_time(LONG, MOVE))

    def test_a_long_move_is_clamped_to_the_cap(self):
        self.assertGreater(move_time(LONG, MOVE), CAP)
        self.assertEqual(
            move_time(LONG, MOVE, _StubRunState(1), BOSS_UPGRADES), CAP)

    def test_a_move_already_under_the_cap_is_untouched(self):
        short = move_time(0, MOVE)
        if short <= CAP:
            self.assertEqual(
                move_time(0, MOVE, _StubRunState(1), BOSS_UPGRADES), short)

    def test_a_cap_does_NOT_stack_per_pick(self):
        """Two ceilings are the lower one, which is the same number — unlike
        every %-based passive, a repeat pick changes nothing here."""
        one = move_time(LONG, MOVE, _StubRunState(1), BOSS_UPGRADES)
        for picks in (2, 5):
            with self.subTest(picks=picks):
                self.assertEqual(
                    move_time(LONG, MOVE, _StubRunState(picks), BOSS_UPGRADES),
                    one)

    def test_the_LOVE_dial_never_grew_a_cap(self):
        """D14 caps the TIME dial only. `move_cost` calls the same `_stepped`
        helper and must stay untouched — which is exactly why the clamp lives
        in `move_time` and not in that shared helper."""
        self.assertEqual(list(inspect.signature(move_cost).parameters),
                         ["distance", "movement_balance"])


if __name__ == "__main__":
    unittest.main()
