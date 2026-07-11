"""Phase 10D: Boost buildings (speed / damage / hp).

Pure-Python, headless — same synth ``TileMap`` + real balancing fixtures as
``test_painter_meditator``. Covers the tier math, the ramp accumulation onto a
cardinal-adjacent defender, the explosion-on-death debuff + its restore, the
cardinal-4 placement block, flat mode, and the single-card trio unlock.
"""
import copy
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.boost import BoostDamage, BoostHP, BoostSpeed
from game.buildings.components import BoostReceiver
from game.buildings.registry import PlacementError
from game.buildings.research import RESEARCH
from game.core import RunState, load_balance, run_payday
from game.core.levelup import (
    apply_levelup_option, roll_levelup_options, tiers_for,
)
from game.map.tile_map import TileMap

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
CORE = load_balance(REPO / "data", "core")
HOLE = CORE["TheHole"]

FLAT = copy.deepcopy(BUILD)
FLAT["BoostBuildings"]["globals"]["flat_mode"] = True


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


def run_state(*unlocked):
    st = RunState.from_balance(CORE)
    for bt in unlocked:
        st.unlocked_buildings[bt] = True
    return st


# ---------------------------------------------------------------------------
class TestBoostStats(unittest.TestCase):
    """Tier-table math on the leaves (prototype boost_value / upkeep / max_hp)."""

    def test_boost_value_and_upkeep_per_line(self):
        # tier1 lvl1: boost_per_turn straight from the data; upkeep = base_upkeep.
        self.assertAlmostEqual(BoostDamage(0, 0, BUILD).boost_value(), 0.01)
        self.assertAlmostEqual(BoostHP(0, 0, BUILD).boost_value(), 0.01)
        self.assertAlmostEqual(BoostSpeed(0, 0, BUILD).boost_value(), 0.001)
        self.assertEqual(BoostDamage(0, 0, BUILD).upkeep(), 2)
        self.assertEqual(BoostSpeed(0, 0, BUILD).upkeep(), 1)
        self.assertEqual(BoostDamage(0, 0, BUILD).max_hp(), 80)

    def test_boost_value_scales_with_level(self):
        b = BoostDamage(0, 0, BUILD)
        b.upgrade()  # lvl 2: 0.01 + 1 * 0.02
        self.assertAlmostEqual(b.boost_value(), 0.03)


# ---------------------------------------------------------------------------
class TestRampBoost(unittest.TestCase):
    """A booster accumulates its stat onto a cardinal-adjacent defender each
    surviving income phase (prototype ``_process_boosts``)."""

    def _pair(self, btype, balance=BUILD):
        tm, scene, occ = board(["bbb"])
        st = run_state(btype)
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, balance,
                                scene, occ, state=st)
        booster, _ = place_building(tm, tm.get(2, 0), btype, 9999, balance,
                                    scene, occ, state=st)
        return tm, scene, occ, st, dfn, booster

    def test_damage_ramps_each_payday(self):
        tm, scene, occ, st, dfn, _ = self._pair("boost_damage")
        base = dfn.damage()
        run_payday(st, tm, CORE, occ, scene)               # +1% damage
        self.assertEqual(dfn.damage(), int(base * 1.01))
        self.assertIn((1, 0), [(c, r) for c, r, _t in st.boost_events])
        run_payday(st, tm, CORE, occ, scene)               # +2% total
        self.assertEqual(dfn.damage(), int(base * 1.02))

    def test_speed_ramps_faster(self):
        tm, scene, occ, st, dfn, _ = self._pair("boost_speed")
        base = dfn.attack_speed()
        run_payday(st, tm, CORE, occ, scene)
        self.assertAlmostEqual(dfn.attack_speed(), base * (1 - 0.001))

    def test_hp_ramps_and_heals(self):
        tm, scene, occ, st, dfn, _ = self._pair("boost_hp")
        base = dfn.max_hp()
        health = dfn.get_component(Health)
        health.hp = 10                                     # wounded
        run_payday(st, tm, CORE, occ, scene)               # +1% max hp
        self.assertEqual(dfn.max_hp(), int(base * 1.01))
        self.assertEqual(health.max_hp, int(base * 1.01))  # cached value refreshed
        self.assertGreater(health.hp, 10)                  # healed by the increase

    def test_boost_only_touches_cardinal_combat_neighbours(self):
        # A booster diagonal to the defender must NOT boost it.
        tm, scene, occ = board(["bbb", "bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        # (2,1) is diagonal to (1,0): not a cardinal neighbour.
        place_building(tm, tm.get(2, 1), "boost_damage", 9999, BUILD,
                       scene, occ, state=st)
        base = dfn.damage()
        run_payday(st, tm, CORE, occ, scene)
        self.assertEqual(dfn.damage(), base)               # unchanged


# ---------------------------------------------------------------------------
class TestExplosionDebuff(unittest.TestCase):
    """A dead booster curses its neighbours until a booster is rebuilt on the tile
    (prototype ``apply_explosion_debuff`` / ``clear_explosion_debuff_from``)."""

    def test_damage_debuff_halves_and_clears(self):
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        booster, _ = place_building(tm, tm.get(2, 0), "boost_damage", 9999,
                                    BUILD, scene, occ, state=st)
        base = dfn.damage()
        booster.apply_explosion_debuff(tm)
        self.assertEqual(dfn.damage(), max(1, base // 2))
        booster.clear_explosion_debuff_from(2, 0, tm)      # a fresh booster placed
        self.assertEqual(dfn.damage(), base)

    def test_hp_debuff_removes_half_and_restores_exactly(self):
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_hp")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        booster, _ = place_building(tm, tm.get(2, 0), "boost_hp", 9999, BUILD,
                                    scene, occ, state=st)
        base = dfn.max_hp()
        booster.apply_explosion_debuff(tm)
        self.assertEqual(dfn.max_hp(), max(1, base - max(1, base // 2)))
        booster.clear_explosion_debuff_from(2, 0, tm)
        self.assertEqual(dfn.max_hp(), base)

    def test_dead_booster_explodes_once_via_payday(self):
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        booster, _ = place_building(tm, tm.get(2, 0), "boost_damage", 9999,
                                    BUILD, scene, occ, state=st)
        base = dfn.damage()
        booster.get_component(Health).hp = 0               # died this round
        run_payday(st, tm, CORE, occ, scene)               # slot 7 explodes it
        self.assertEqual(dfn.get_component(BoostReceiver).count_debuffs("damage"), 1)
        self.assertEqual(dfn.damage(), max(1, base // 2))


# ---------------------------------------------------------------------------
class TestPlacementBlock(unittest.TestCase):
    def test_cardinal_adjacent_booster_blocked_diagonal_allowed(self):
        tm, scene, occ = board(["bbb", "bbb"])
        st = run_state("boost_speed", "boost_damage")
        place_building(tm, tm.get(1, 0), "boost_speed", 9999, BUILD,
                       scene, occ, state=st)
        with self.assertRaises(PlacementError):            # (2,0) is cardinal
            place_building(tm, tm.get(2, 0), "boost_damage", 9999, BUILD,
                           scene, occ, state=st)
        # (0,1) is diagonal to (1,0) — allowed.
        place_building(tm, tm.get(0, 1), "boost_damage", 9999, BUILD,
                       scene, occ, state=st)


# ---------------------------------------------------------------------------
class TestFlatMode(unittest.TestCase):
    """flat_mode=True applies a one-time 10x boost on placement, reversed on death
    (prototype ``apply_flat_boost`` / ``remove_flat_boost``)."""

    def test_flat_applied_on_placement_and_removed_on_death(self):
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, FLAT,
                                scene, occ, state=st)
        base = dfn.damage()
        booster, _ = place_building(tm, tm.get(2, 0), "boost_damage", 9999,
                                    FLAT, scene, occ, state=st)
        # 10x of 0.01 = +10% immediately on placement.
        self.assertEqual(dfn.damage(), int(base * 1.10))
        booster.get_component(Health).hp = 0
        run_payday(st, tm, CORE, occ, scene)               # slot 7 removes the flat
        # damage boost gone (explosion debuff still halves it), so not > base.
        self.assertLessEqual(dfn.get_component(BoostReceiver).damage_pct, 1e-9)


# ---------------------------------------------------------------------------
class TestTrioUnlock(unittest.TestCase):
    """The three boosters surface as ONE level-up card that unlocks all of them,
    gated to round 10 (BoostBuildings.globals.unlock_min_round)."""

    def _silence_non_boost(self, st):
        # Max out every non-boost type so only the boost trio is offerable.
        for bt in RESEARCH:
            if bt.startswith("boost_"):
                continue
            st.unlocked_buildings[bt] = True
            st.tiers_unlocked[bt] = len(tiers_for(bt, BUILD))

    def test_single_card_unlocks_all_three_at_round_10(self):
        st = RunState.from_balance(CORE)
        st.round_num = 10
        self._silence_non_boost(st)
        opts = roll_levelup_options(st, BUILD, CORE, random.Random(0))
        cards = [o for o in opts if o.get("kind") == "unlock_building"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(tuple(cards[0]["building_types"]),
                         ("boost_speed", "boost_damage", "boost_hp"))
        apply_levelup_option(st, cards[0], CORE)
        for bt in ("boost_speed", "boost_damage", "boost_hp"):
            self.assertTrue(st.unlocked_buildings[bt])

    def test_not_offered_before_round_10(self):
        st = RunState.from_balance(CORE)
        st.round_num = 9
        self._silence_non_boost(st)
        opts = roll_levelup_options(st, BUILD, CORE, random.Random(0))
        self.assertFalse([o for o in opts if o.get("kind") == "unlock_building"])


if __name__ == "__main__":
    unittest.main()
