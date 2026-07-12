"""Phase 10E: Blocker + WallBuilder + edge walls (game/buildings/structure.py +
the map wall-edge registry + enemy wall-attack + the payday teardown/rebuild
slots).

Pure-Python, headless — the same synth ``TileMap`` fixture as the other building
tests. Covers the tier math, the perimeter derivation (player-exterior edges
only), pathfinding through/around walls, the enemy attacking a wall on its
ignoring-walls path, and the payday wall lifecycle.
"""
import copy
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import (
    BaseBuilding, Blocker, WallBuilder, attach_base, place_building,
)
from game.buildings.components import WallBuilderState
from game.buildings.registry import PlacementError
from game.core import RunState, load_balance, run_payday
from game.enemies import create_enemy
from game.enemies.components import EnemyCombat, PathAgent
from game.map.pathfinder import find_path, find_path_ignoring_walls
from game.map.tile_map import TileMap, WallEdge, _wall_key

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
CORE = load_balance(REPO / "data", "core")
ENEM = load_balance(REPO / "data", "enemies")

BLOCKER = BUILD["StructureBuildings"]["Blocker"]["tiers"]
WALLB = BUILD["StructureBuildings"]["WallBuilder"]["tiers"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def board(rows):
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def run_state(**tiers):
    st = RunState.from_balance(CORE)
    for bt, n in tiers.items():
        st.unlocked_buildings[bt] = True
        st.tiers_unlocked[bt] = n
    return st


# ---------------------------------------------------------------------------
class TestStructureStats(unittest.TestCase):
    """Tier-table math on the leaves (prototype BlockerBuilding /
    WallBuilderBuilding: HP soak, per-tier wall_hp, upkeep)."""

    def test_blocker_hp_scales_no_upkeep_no_yield(self):
        b = Blocker(0, 0, BUILD)
        self.assertEqual(b.max_hp(), BLOCKER[0]["base_hp"])        # 500
        self.assertEqual(b.upkeep(), 0)                            # passive
        self.assertFalse(hasattr(b, "yield_amount"))
        self.assertFalse(hasattr(b, "damage"))
        b.upgrade()                                                # lvl 2
        self.assertEqual(
            b.max_hp(), BLOCKER[0]["base_hp"] + BLOCKER[0]["hp_per_level"])
        b.advance_tier()                                           # Bulwark
        self.assertEqual(b.max_hp(), BLOCKER[1]["base_hp"])        # 1200

    def test_blocker_uses_traversable_economy_weight(self):
        # NOT impassable: enemies path over it and attack (prototype fallback).
        self.assertEqual(Blocker(0, 0, BUILD).CONTENT_KEY, "economic_building")

    def test_wall_builder_wall_hp_upkeep_and_hp(self):
        w = WallBuilder(0, 0, BUILD)
        self.assertEqual(w.max_hp(), WALLB[0]["base_hp"])          # 300
        self.assertEqual(w.wall_hp(), WALLB[0]["wall_hp"])         # 50 (not x10)
        self.assertEqual(w.upkeep(), WALLB[0]["base_upkeep"])      # 3
        w.upgrade()                                                # lvl 2
        self.assertEqual(
            w.upkeep(),
            WALLB[0]["base_upkeep"] + WALLB[0]["upkeep_per_level"])  # 6
        self.assertEqual(w.wall_hp(), WALLB[0]["wall_hp"])         # const in tier
        w.advance_tier()                                           # Wooden
        self.assertEqual(w.wall_hp(), WALLB[1]["wall_hp"])         # 120

    def test_wall_builder_flat_slot_key(self):
        self.assertEqual(WallBuilder(0, 0, BUILD).slot_key(), "wall_builder")
        self.assertEqual(Blocker(0, 0, BUILD).slot_key(), "blocker")


# ---------------------------------------------------------------------------
# A 4x3 board whose player pocket is fully wallable. base(0,0).
#   row0: b b b c      player: (0..2,0),(0..2,1)   spawn: (0..2,2)
#   row1: b b b c      combat: (3,0),(3,1),(3,2)
#   row2: s s s c
WALL_MAP = ["bbbc", "bbbc", "sssc"]
# The perimeter edges a builder should raise (player tile <-> exterior tile):
EXPECTED_WALL_KEYS = {
    _wall_key(0, 1, 0, 2), _wall_key(1, 1, 1, 2), _wall_key(2, 1, 2, 2),
    _wall_key(2, 0, 3, 0), _wall_key(2, 1, 3, 1),
}


class TestWallRegistry(unittest.TestCase):
    def _place_builder(self, at=(2, 1)):
        tm, scene, occ = board(WALL_MAP)
        w, _ = place_building(tm, tm.get(*at), "wall_builder", 9999, BUILD,
                              scene, occ)  # state=None -> skip research gate
        return tm, scene, occ, w

    def test_perimeter_is_player_to_exterior_edges_only(self):
        tm, _s, _o, _w = self._place_builder()
        self.assertEqual(set(tm.wall_edges), EXPECTED_WALL_KEYS)
        # An interior player<->player edge is never walled.
        self.assertIsNone(tm.get_wall_between(0, 0, 1, 0))
        # Every raised wall carries the tier-1 wall HP.
        for edge in tm.wall_edges.values():
            self.assertEqual((edge.hp, edge.max_hp), (WALLB[0]["wall_hp"],) * 2)

    def test_snapshot_frozen_on_builder(self):
        _tm, _s, _o, w = self._place_builder()
        snap = {_wall_key(*e) for e in w.wall_snapshot()}
        self.assertEqual(snap, EXPECTED_WALL_KEYS)
        self.assertIsInstance(w.get_component(WallBuilderState).wall_snapshot, list)

    def test_walls_enclose_base_ignoring_walls_gets_through(self):
        tm, _s, _o, _w = self._place_builder()
        # Enclosed: no wall-respecting path from a spawn tile to the base...
        self.assertEqual(find_path(tm, 0, 2), [])
        # ...but the walls-ignoring variant crosses them.
        self.assertTrue(find_path_ignoring_walls(tm, 0, 2))

    def test_damage_wall_breaks_and_reopens_the_step(self):
        tm, _s, _o, _w = self._place_builder()
        key = _wall_key(0, 1, 0, 2)
        hp = tm.wall_edges[key].hp
        self.assertFalse(tm.damage_wall(0, 1, 0, 2, hp - 1))       # survives
        self.assertTrue(tm.damage_wall(0, 1, 0, 2, 1))             # breaks
        self.assertIsNone(tm.get_wall_between(0, 1, 0, 2))
        # That edge is now passable, so a path opens through the gap.
        self.assertTrue(find_path(tm, 0, 2))

    def test_no_walls_before_any_builder(self):
        tm, _s, _o = board(WALL_MAP)
        self.assertEqual(tm.wall_edges, {})
        self.assertIsNone(tm.get_wall_between(0, 1, 0, 2))
        self.assertTrue(find_path(tm, 0, 2))                       # freely reachable


# ---------------------------------------------------------------------------
class TestEnemyWallAttack(unittest.TestCase):
    """An enemy whose only route to the base crosses walls attacks each wall it
    hits, then resumes the same path once it breaks (prototype wall-attack)."""

    def test_walker_drains_a_wall_then_reaches_base(self):
        tm, scene, occ = board(WALL_MAP)
        place_building(tm, tm.get(2, 1), "wall_builder", 9999, BUILD, scene, occ)
        key = _wall_key(0, 1, 0, 2)
        self.assertIn(key, tm.wall_edges)

        e = create_enemy("standard", 0, 2, ENEM, tm)   # on a spawn tile
        e.get_component(EnemyCombat).dmg = 20           # 3 hits break a 50hp wall
        e.get_component(EnemyCombat).attack_speed = 0.2
        scene.spawn(e)

        blocked_at_wall = False
        for _ in range(400):
            scene.update(0.1)
            pa = e.get_component(PathAgent)
            if pa.blocked and pa._wall_target is not None:
                blocked_at_wall = True
            if pa.reached_base:
                break
        self.assertTrue(blocked_at_wall)                # it stopped to attack
        self.assertNotIn(key, tm.wall_edges)            # the wall was destroyed
        self.assertTrue(e.get_component(PathAgent).reached_base)  # then walked in


# ---------------------------------------------------------------------------
class TestPaydayWallLifecycle(unittest.TestCase):
    """Payday slot 8 tears down a dead builder's walls (before revive); slot 10
    rebuilds every alive builder's walls to full HP (after revive)."""

    def _setup(self):
        tm, scene, occ = board(WALL_MAP)
        st = run_state(wall_builder=1)
        w, _ = place_building(tm, tm.get(2, 1), "wall_builder", 9999, BUILD,
                              scene, occ, state=st)
        return tm, scene, occ, st, w

    def test_damaged_walls_regenerate_each_payday(self):
        tm, scene, occ, st, _w = self._setup()
        key = _wall_key(0, 1, 0, 2)
        tm.damage_wall(0, 1, 0, 2, 30)                  # 50 -> 20 during the round
        self.assertEqual(tm.wall_edges[key].hp, 20)
        run_payday(st, tm, CORE, occ, scene)
        self.assertEqual(tm.wall_edges[key].hp, tm.wall_edges[key].max_hp)  # full

    def test_dead_builder_walls_torn_down_then_restored_on_revive(self):
        tm, scene, occ, st, w = self._setup()
        self.assertTrue(tm.wall_edges)
        w.get_component(Health).hp = 0                  # died this round
        run_payday(st, tm, CORE, occ, scene)            # slot 8 tears down...
        # ...slot 9 revives the builder, slot 10 rebuilds its perimeter to full.
        self.assertTrue(w.alive)
        self.assertEqual(set(tm.wall_edges), EXPECTED_WALL_KEYS)

    def test_dead_builder_walls_stay_gone_when_revive_off(self):
        tm, scene, occ, st, w = self._setup()
        core = copy.deepcopy(CORE)
        core["TheHole"]["building_revive"] = False
        w.get_component(Health).hp = 0
        run_payday(st, tm, core, occ, scene)
        self.assertFalse(w.alive)
        self.assertEqual(tm.wall_edges, {})             # perimeter permanently gone


# ---------------------------------------------------------------------------
class TestResearchGating(unittest.TestCase):
    """Blocker is placeable from the start; WallBuilder is not until researched
    (prototype ``blocker_tiers_unlocked = 1`` vs the wall-builder tier gate)."""

    def test_blocker_placeable_from_round_one(self):
        tm, scene, occ = board(["bb"])
        st = RunState.from_balance(CORE)                # fresh: nothing researched
        b, _ = place_building(tm, tm.get(1, 0), "blocker", 9999, BUILD,
                              scene, occ, state=st)
        self.assertEqual(b.building_type, "blocker")

    def test_wall_builder_needs_research_first(self):
        tm, scene, occ = board(["bb"])
        st = RunState.from_balance(CORE)                # wall_builder starts_with_tier=0
        with self.assertRaises(PlacementError):
            place_building(tm, tm.get(1, 0), "wall_builder", 9999, BUILD,
                           scene, occ, state=st)
        st.tiers_unlocked["wall_builder"] = 1           # researched at a level-up
        w, _ = place_building(tm, tm.get(1, 0), "wall_builder", 9999, BUILD,
                              scene, occ, state=st)
        self.assertEqual(w.building_type, "wall_builder")


if __name__ == "__main__":
    unittest.main()
