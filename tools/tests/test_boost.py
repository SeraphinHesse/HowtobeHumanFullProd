"""Phase 10D: Boost buildings (speed / damage / hp).

Pure-Python, headless — same synth ``TileMap`` + real balancing fixtures as
``test_painter_meditator``. Covers the tier math, the ramp accumulation onto a
range-adjacent defender, the
cardinal-4 placement block, flat mode, the single-card trio unlock, and
(booster-range-config feature) the configurable
``BoostBuildings.globals.range_tiles``/``.range_shape`` pair — the shipped
default (``"plus"``, magnitude 1) reproduces the original cardinal-4-only
behaviour byte-for-byte; ``"square"``/a larger magnitude are opt-in.
"""
import copy
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings import range_shape
from game.buildings.boost import BoostDamage, BoostHP, BoostSpeed
from game.buildings.components import BoostReceiver
from game.buildings.registry import PlacementError
from game.buildings.research import RESEARCH
from game.core import RunState, load_balance, run_payday
from game.core.levelup import (
    apply_levelup_option, roll_levelup_options, tiers_for, timeline_level_for,
)
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
PROGRESSION = load_balance(FIXTURE_DATA, "progression")
HOLE = CORE["TheHole"]

FLAT = copy.deepcopy(BUILD)
FLAT["BoostBuildings"]["globals"]["flat_mode"] = True

# The three boost lines' tier-1 rows. Every expected number below is derived
# from these rather than mirrored as a literal, so a balance retune (or a
# fixture refresh that picks one up) can never strand the assertion — the
# ``DEF_T2`` precedent in ``test_levelup.py`` (D5).
DMG_T1 = BUILD["BoostBuildings"]["Damage"]["tiers"][0]
HP_T1 = BUILD["BoostBuildings"]["HP"]["tiers"][0]
SPD_T1 = BUILD["BoostBuildings"]["Speed"]["tiers"][0]
# ``BoostBuilding.apply_flat``/``remove_flat``'s multiplier — a code constant
# (like AOE_TRAVEL_TIME), not balancing, so it is mirrored here deliberately.
FLAT_MULTIPLE = 10

SQUARE = copy.deepcopy(BUILD)
SQUARE["BoostBuildings"]["globals"]["range_shape"] = "square"

PLUS2 = copy.deepcopy(BUILD)
PLUS2["BoostBuildings"]["globals"]["range_tiles"] = 2


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
    st = RunState.from_balance(CORE, BUILD)
    for bt in unlocked:
        st.unlocked_buildings[bt] = True
    return st


# ---------------------------------------------------------------------------
class TestBoostStats(unittest.TestCase):
    """Tier-table math on the leaves (prototype boost_value / upkeep / max_hp)."""

    def test_boost_value_and_upkeep_per_line(self):
        # tier1 lvl1: boost_per_turn straight from the data; upkeep = base_upkeep.
        self.assertAlmostEqual(BoostDamage(0, 0, BUILD).boost_value(),
                               DMG_T1["boost_per_turn"])
        self.assertAlmostEqual(BoostHP(0, 0, BUILD).boost_value(),
                               HP_T1["boost_per_turn"])
        self.assertAlmostEqual(BoostSpeed(0, 0, BUILD).boost_value(),
                               SPD_T1["boost_per_turn"])
        self.assertEqual(BoostDamage(0, 0, BUILD).upkeep(),
                         DMG_T1["base_upkeep"])
        self.assertEqual(BoostSpeed(0, 0, BUILD).upkeep(),
                         SPD_T1["base_upkeep"])
        self.assertEqual(BoostDamage(0, 0, BUILD).max_hp(), DMG_T1["base_hp"])

    def test_boost_value_scales_with_level(self):
        b = BoostDamage(0, 0, BUILD)
        b.upgrade()  # lvl 2: boost_per_turn + 1 * boost_increase_per_level
        self.assertAlmostEqual(
            b.boost_value(),
            DMG_T1["boost_per_turn"] + DMG_T1["boost_increase_per_level"])


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
        step = DMG_T1["boost_per_turn"]
        base = dfn.damage()
        run_payday(st, tm, CORE, occ, scene)               # +one step of damage
        self.assertEqual(dfn.damage(), int(base * (1 + step)))
        self.assertIn((1, 0), [(c, r) for c, r, _t in st.boost_events])
        run_payday(st, tm, CORE, occ, scene)               # +two steps total
        self.assertEqual(dfn.damage(), int(base * (1 + 2 * step)))

    def test_speed_ramps_faster(self):
        tm, scene, occ, st, dfn, _ = self._pair("boost_speed")
        base = dfn.attack_speed()
        run_payday(st, tm, CORE, occ, scene)
        self.assertAlmostEqual(dfn.attack_speed(),
                               base * (1 - SPD_T1["boost_per_turn"]))

    def test_hp_ramps_and_heals(self):
        tm, scene, occ, st, dfn, _ = self._pair("boost_hp")
        base = dfn.max_hp()
        health = dfn.get_component(Health)
        health.hp = 10                                     # wounded
        run_payday(st, tm, CORE, occ, scene)               # +one step of max hp
        boosted = int(base * (1 + HP_T1["boost_per_turn"]))
        self.assertEqual(dfn.max_hp(), boosted)
        self.assertEqual(health.max_hp, boosted)           # cached value refreshed
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

    def test_square_shape_touches_diagonal_neighbour(self):
        # Same layout as above, but range_shape="square": now the diagonal
        # booster DOES touch the defender (booster-range-config feature).
        # Asserts on the BoostReceiver fraction directly, not the rounded
        # `.damage()` int, since a single 2% bump can round away on a small base.
        tm, scene, occ = board(["bbb", "bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, SQUARE,
                                scene, occ, state=st)
        place_building(tm, tm.get(2, 1), "boost_damage", 9999, SQUARE,
                       scene, occ, state=st)
        run_payday(st, tm, CORE, occ, scene)
        self.assertGreater(dfn.get_component(BoostReceiver).damage_pct, 0)

    def test_plus_shape_magnitude_two_reaches_further_cardinal_not_diagonal(self):
        # range_tiles=2, shape stays "plus": 2 tiles out cardinally touches,
        # an off-axis offset still does not, regardless of magnitude. Base
        # occupies (0,0) (the `board()` helper default), so placements start
        # at col 1.
        tm, scene, occ = board(["bbbbbbb", "bbbbbbb"])
        st = run_state("boost_damage")
        far, _ = place_building(tm, tm.get(1, 0), "defence", 9999, PLUS2,
                                scene, occ, state=st)
        diag, _ = place_building(tm, tm.get(6, 1), "defence", 9999, PLUS2,
                                 scene, occ, state=st)
        place_building(tm, tm.get(3, 0), "boost_damage", 9999, PLUS2,
                       scene, occ, state=st)
        run_payday(st, tm, CORE, occ, scene)
        self.assertGreater(far.get_component(BoostReceiver).damage_pct, 0)   # 2 W
        self.assertEqual(diag.get_component(BoostReceiver).damage_pct, 0)    # off-axis


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
        # 10x of one boost step, immediately on placement.
        self.assertEqual(
            dfn.damage(),
            int(base * (1 + FLAT_MULTIPLE * DMG_T1["boost_per_turn"])))
        booster.get_component(Health).hp = 0
        run_payday(st, tm, CORE, occ, scene)               # slot 7 removes the flat
        # The flat contribution is fully reversed — back to the raw base damage.
        self.assertLessEqual(dfn.get_component(BoostReceiver).damage_pct, 1e-9)
        self.assertEqual(dfn.damage(), base)

    def test_dead_booster_leaves_no_debuff(self):
        """The booster-death explosion debuff is REMOVED: a dead booster in ramp
        mode neither halves damage nor removes max HP from its neighbours."""
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        booster, _ = place_building(tm, tm.get(2, 0), "boost_damage", 9999,
                                    BUILD, scene, occ, state=st)
        base_dmg, base_hp = dfn.damage(), dfn.max_hp()
        booster.get_component(Health).hp = 0
        run_payday(st, tm, CORE, occ, scene)
        self.assertGreaterEqual(dfn.damage(), base_dmg)
        self.assertGreaterEqual(dfn.max_hp(), base_hp)


# ---------------------------------------------------------------------------
class TestTrioUnlock(unittest.TestCase):
    """The three boosters surface as ONE level-up card that unlocks all of
    them, gated by each boost line's own tier-0 Timeline placement
    (``data/balancing/progression.json``, village level 2 as shipped — no
    shared BoostBuildings.globals key, and no ``unlock_min_round`` any more)."""

    # Every boost line's tier 0 is placed at the same village level (the trio
    # unlocks together); the lead's placement is what the roll actually reads.
    GATE_LEVEL = timeline_level_for("boost_speed", 0, PROGRESSION)

    def _silence_non_boost(self, st):
        # Max out every non-boost type so only the boost trio is offerable.
        for bt in RESEARCH:
            if bt.startswith("boost_"):
                continue
            st.unlocked_buildings[bt] = True
            st.tiers_unlocked[bt] = len(tiers_for(bt, BUILD))

    def test_single_card_unlocks_all_three_at_its_timeline_level(self):
        st = RunState.from_balance(CORE, BUILD)
        st.village_level = self.GATE_LEVEL
        self._silence_non_boost(st)
        opts = roll_levelup_options(st, BUILD, CORE, random.Random(0),
                                    PROGRESSION)
        cards = [o for o in opts if o.get("kind") == "unlock_building"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(tuple(cards[0]["building_types"]),
                         ("boost_speed", "boost_damage", "boost_hp"))
        apply_levelup_option(st, cards[0], CORE)
        for bt in ("boost_speed", "boost_damage", "boost_hp"):
            self.assertTrue(st.unlocked_buildings[bt])

    def test_not_offered_before_its_timeline_level(self):
        st = RunState.from_balance(CORE, BUILD)
        # The roll gates on the level being REACHED (village_level + 1), so
        # the last level-up that must NOT show the card is the one reaching
        # GATE_LEVEL - 1.
        st.village_level = self.GATE_LEVEL - 2
        self._silence_non_boost(st)
        opts = roll_levelup_options(st, BUILD, CORE, random.Random(0),
                                    PROGRESSION)
        self.assertFalse([o for o in opts if o.get("kind") == "unlock_building"])


# ---------------------------------------------------------------------------
class TestTrioTierResearch(unittest.TestCase):
    """The trio's LATER tiers work like its unlock: ONE card researches tier N
    for all three lines, titled from ``BoostBuildings.globals.tier_card_titles``
    (no single line's tier name can title a card granting all three), gated by
    the lead's own Timeline placement."""

    T2_LEVEL = timeline_level_for("boost_speed", 1, PROGRESSION)

    def _boost_only(self, st):
        for bt in RESEARCH:
            if bt.startswith("boost_"):
                st.unlocked_buildings[bt] = True
            else:
                st.unlocked_buildings[bt] = True
                st.tiers_unlocked[bt] = len(tiers_for(bt, BUILD))

    def test_one_card_researches_tier_2_for_all_three(self):
        st = RunState.from_balance(CORE, BUILD)
        st.village_level = self.T2_LEVEL
        self._boost_only(st)
        opts = roll_levelup_options(st, BUILD, CORE, random.Random(0),
                                    PROGRESSION)
        cards = [o for o in opts if o.get("kind") == "tier"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(tuple(cards[0]["building_types"]),
                         ("boost_speed", "boost_damage", "boost_hp"))
        self.assertEqual(cards[0]["title"],
                         BUILD["BoostBuildings"]["globals"]["tier_card_titles"][1])
        apply_levelup_option(st, cards[0], CORE)
        for bt in ("boost_speed", "boost_damage", "boost_hp"):
            self.assertEqual(st.tiers_unlocked[bt], 2)

    def test_tier_cards_are_free_and_only_preview_the_price(self):
        st = RunState.from_balance(CORE, BUILD)
        st.village_level = self.T2_LEVEL
        self._boost_only(st)
        card = [o for o in roll_levelup_options(st, BUILD, CORE,
                                                random.Random(0), PROGRESSION)
                if o.get("kind") == "tier"][0]
        self.assertEqual(card["cost"], 0)
        self.assertEqual(card["display_cost"],
                         tiers_for("boost_speed", BUILD)[1]["build_cost"])
        st.love = 3
        apply_levelup_option(st, card, CORE)
        self.assertEqual(st.love, 3)


# ---------------------------------------------------------------------------
class TestRangeShapeOffsets(unittest.TestCase):
    """Pure tile-offset geometry (``game/buildings/range_shape.py``), shared
    by the booster buff sweep, the RANGE overlay, the selection highlight,
    and defence-range pathfinding coverage."""

    def test_plus_magnitude_one_is_the_original_cardinal_four(self):
        self.assertEqual(
            set(range_shape.offsets(1, "plus")),
            {(0, -1), (0, 1), (-1, 0), (1, 0)})

    def test_plus_magnitude_two_extends_each_arm(self):
        self.assertEqual(
            set(range_shape.offsets(2, "plus")),
            {(0, -1), (0, -2), (0, 1), (0, 2), (-1, 0), (-2, 0), (1, 0), (2, 0)})

    def test_square_magnitude_one_is_all_eight_surrounding_tiles(self):
        offsets = set(range_shape.offsets(1, "square"))
        self.assertEqual(len(offsets), 8)
        self.assertNotIn((0, 0), offsets)
        self.assertIn((1, 1), offsets)          # a diagonal neighbour

    def test_square_magnitude_two_is_a_five_by_five_minus_origin(self):
        self.assertEqual(len(range_shape.offsets(2, "square")), 24)

    def test_zero_magnitude_is_empty_for_both_shapes(self):
        self.assertEqual(range_shape.offsets(0, "plus"), [])
        self.assertEqual(range_shape.offsets(0, "square"), [])


# ---------------------------------------------------------------------------
# BossUpgradeTimelinePLAN BU-3 3.6 — #10 `boost_double_trigger`
# ---------------------------------------------------------------------------
#: Hand-pinned (BU-6): what a designer types into the new editor panel must
#: never decide whether this module is green (`data/CLAUDE.md`).
EXTRA_TRIGGERS = 1
BOSS_UPGRADES = {
    "BossUpgrades": {
        "Catalog": {
            "boost_double_trigger": {
                "name": "Double Boost", "description": "",
                "params": {"extra_triggers": EXTRA_TRIGGERS}},
        },
        "Timeline": {"milestones": [
            {"slots": ["boost_double_trigger", None, None],
             "retaliation_bonus_love": 30},
        ] * 4},
    }
}


class TestBoostDoubleTrigger(unittest.TestCase):
    """D18 — a PERMANENT GLOBAL rule: `apply_per_turn()` runs `extra_triggers`
    ADDITIONAL times inside payday's own slot 7. The payday ordering is
    sacrosanct, so a second trigger is a repeat of that step's work, never a
    new step — and the param IS the count, so repeat picks do not multiply it.
    """

    def _pair(self, picks=0):
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        if picks:
            st.boss_upgrade_stacks["boost_double_trigger"] = picks
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        place_building(tm, tm.get(2, 0), "boost_damage", 9999, BUILD,
                       scene, occ, state=st)
        return tm, scene, occ, st, dfn

    def _payday(self, picks=0, balance=BOSS_UPGRADES):
        tm, scene, occ, st, dfn = self._pair(picks)
        run_payday(st, tm, CORE, occ, scene, None, balance)
        return st, dfn

    def test_no_balance_threaded_is_byte_identical(self):
        st, dfn = self._payday(picks=1, balance=None)
        step = DMG_T1["boost_per_turn"]
        self.assertEqual(dfn.get_component(BoostReceiver).damage_pct, step)

    def test_an_unpicked_upgrade_triggers_exactly_once(self):
        st, dfn = self._payday(picks=0)
        step = DMG_T1["boost_per_turn"]
        self.assertAlmostEqual(dfn.get_component(BoostReceiver).damage_pct,
                               step)
        self.assertEqual(len(st.boost_events), 1)

    def test_one_pick_adds_extra_triggers_inside_the_same_payday(self):
        st, dfn = self._payday(picks=1)
        step = DMG_T1["boost_per_turn"]
        self.assertAlmostEqual(dfn.get_component(BoostReceiver).damage_pct,
                               step * (1 + EXTRA_TRIGGERS))
        # every repeat pushes its OWN floater, so the UI shows each trigger
        self.assertEqual(len(st.boost_events), 1 + EXTRA_TRIGGERS)

    def test_repeat_picks_do_NOT_multiply_the_count(self):
        """Unlike every %-based passive, the param IS the count here."""
        one = self._payday(picks=1)[1].get_component(BoostReceiver).damage_pct
        two = self._payday(picks=2)[1].get_component(BoostReceiver).damage_pct
        self.assertAlmostEqual(one, two)

    def test_a_negative_authored_count_can_never_remove_the_base_trigger(self):
        bal = copy.deepcopy(BOSS_UPGRADES)
        bal["BossUpgrades"]["Catalog"]["boost_double_trigger"]["params"][
            "extra_triggers"] = -5
        tm, scene, occ, st, dfn = self._pair(picks=1)
        run_payday(st, tm, CORE, occ, scene, None, bal)
        self.assertAlmostEqual(dfn.get_component(BoostReceiver).damage_pct,
                               DMG_T1["boost_per_turn"])

    def test_a_booster_placed_AFTER_the_pick_is_covered_too(self):
        """D18: a permanent global rule, not a snapshot — nothing about the
        booster itself is consulted."""
        tm, scene, occ = board(["bbb"])
        st = run_state("boost_damage")
        st.boss_upgrade_stacks["boost_double_trigger"] = 1   # picked first...
        dfn, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ, state=st)
        place_building(tm, tm.get(2, 0), "boost_damage", 9999, BUILD,
                       scene, occ, state=st)                # ...booster after
        run_payday(st, tm, CORE, occ, scene, None, BOSS_UPGRADES)
        self.assertAlmostEqual(
            dfn.get_component(BoostReceiver).damage_pct,
            DMG_T1["boost_per_turn"] * (1 + EXTRA_TRIGGERS))


if __name__ == "__main__":
    unittest.main()
