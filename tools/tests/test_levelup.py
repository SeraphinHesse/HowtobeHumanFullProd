"""Phase 10A: XP, village level-up, research + era gates.

Pure-Python, headless — same fixtures as ``test_phase_loop`` (synth TileMapDoc ->
TileMap, real balancing via ``load_balance``). The option roll takes an injected
rng so every draw is deterministic.
"""
import copy
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, PlacementError, attach_base, place_building
from game.buildings.research import ResearchSpec, buildable
from game.core import RunState, Session, load_balance
from game.core import levelup as lv
from game.core import xp as xpmod
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

XP = CORE["XP"]

# The defence line's tier-2 row, the pool/gate tests' favourite subject —
# derived so a fixture refresh can never strand a mirrored literal (D5).
DEF_T2 = BUILD["DefenceBuildings"]["BasicDefence"]["tiers"][1]


class NoShuffle:
    """rng stub: preserves pool order so a draw is fully predictable."""

    @staticmethod
    def shuffle(seq):
        pass


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board(rows):
    tm = synth(rows)
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def make_session(rows=("bs",), core=CORE, rng=None):
    tm, scene, occ = build_board(rows)
    session = Session.create(Spawner(), tm, ENEM, core, BUILD, rng=rng)
    return session, tm, scene, occ


def frame(session, scene, tilemap_, dt):
    """One host frame, including 10A's freeze gate + death callback."""
    session.pre_sim(dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(dt)
        resolve_combat(scene, tilemap_, dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death)
        session.post_sim(scene)


# ---------------------------------------------------------------------------
class TestRunStateSeeding(unittest.TestCase):
    def test_xp_fields_seeded_from_core(self):
        st = RunState.from_balance(CORE, BUILD)
        self.assertEqual(st.player_xp, 0)
        self.assertEqual(st.village_level, 1)
        self.assertEqual(st.xp_threshold, XP["village_xp_base_threshold"])
        self.assertEqual(st.xp_threshold_inc, XP["village_xp_threshold_inc"])
        self.assertFalse(st.levelup_pending)

    def test_research_seeded_from_table(self):
        st = RunState.from_balance(CORE, BUILD)
        # 9D lines start unlocked at tier 1. Every other type starts LOCKED
        # (data-driven via buildings.json starts_unlocked -- only Stone
        # Thrower/defence and Flute Player/economic start unlocked), earned
        # via a level-up unlock card. ``starts_with_tier`` is GONE (the
        # Joel-Balancing regate): every type -- including meditator and
        # wall_builder, which used to seed 0 -- now seeds tier 1, so
        # unlocking a type makes it immediately placeable with no second
        # "research tier 1" card.
        self.assertEqual(
            st.tiers_unlocked,
            {"defence": 1, "economic": 1, "aoe_defence": 1, "sun_scorcher": 1,
             "storm_priest": 1, "painter": 1, "meditator": 1,
             "boost_speed": 1, "boost_damage": 1, "boost_hp": 1,
             "blocker": 1, "wall_builder": 1})
        self.assertEqual(
            st.unlocked_buildings,
            {"defence": True, "economic": True,
             "aoe_defence": False, "sun_scorcher": False,
             "storm_priest": False, "painter": False, "meditator": False,
             "boost_speed": False, "boost_damage": False, "boost_hp": False,
             "blocker": False, "wall_builder": False})


# ---------------------------------------------------------------------------
class TestXpMath(unittest.TestCase):
    def test_xp_per_enemy_type(self):
        self.assertEqual(xpmod.xp_for_etype("standard", CORE),
                         XP["xp_per_standard_enemy"])
        self.assertEqual(xpmod.xp_for_etype("raider", CORE),
                         XP["xp_per_raider"])
        self.assertEqual(xpmod.xp_for_etype("siege", CORE),
                         XP["xp_per_siege_enemy"])
        self.assertEqual(xpmod.xp_for_etype("boss", CORE), XP["xp_per_boss"])

    def test_unknown_etype_pays_standard(self):
        self.assertEqual(xpmod.xp_for_etype("gribbly", CORE),
                         XP["xp_per_standard_enemy"])

    def test_award_arms_pending_once_at_threshold(self):
        st = RunState.from_balance(CORE, BUILD)
        threshold = XP["village_xp_base_threshold"]
        xpmod.award_xp(st, threshold - 1)
        self.assertFalse(st.levelup_pending)
        xpmod.award_xp(st, 1)
        self.assertTrue(st.levelup_pending)
        self.assertEqual(st.player_xp, threshold)

    def test_award_records_floater_event_only_with_a_position(self):
        st = RunState.from_balance(CORE, BUILD)
        xpmod.award_xp(st, 3)
        self.assertEqual(st.xp_events, [])
        xpmod.award_xp(st, 2, (4.0, 5.0))
        self.assertEqual(st.xp_events, [(4.0, 5.0, 2)])

    def test_threshold_curve(self):
        """e.g. 50 -> 65 -> 85 -> 110 -> 140: the increment itself grows.

        Expected values re-derived from the tunables with the documented
        recurrence (threshold += inc; inc += growth), independently of
        ``advance_village_level``'s own arithmetic."""
        st = RunState.from_balance(CORE, BUILD)
        inc = XP["village_xp_threshold_inc"]
        expect = [XP["village_xp_base_threshold"]]
        for _ in range(4):
            expect.append(expect[-1] + inc)
            inc += XP["village_xp_threshold_inc_growth"]
        seen = [st.xp_threshold]
        for _ in range(4):
            xpmod.advance_village_level(st, CORE)
            seen.append(st.xp_threshold)
        self.assertEqual(seen, expect)
        self.assertEqual(st.village_level, 5)

    def test_surplus_xp_carries_forward(self):
        st = RunState.from_balance(CORE, BUILD)
        threshold = XP["village_xp_base_threshold"]
        xpmod.award_xp(st, threshold + 13)
        xpmod.advance_village_level(st, CORE)
        self.assertEqual(st.player_xp, 13)
        self.assertEqual(st.xp_threshold,
                         threshold + XP["village_xp_threshold_inc"])

    def test_scaled_base_income(self):
        st = RunState.from_balance(CORE, BUILD)
        base = CORE["TheHole"]["base_income"]
        per = XP["base_income_per_village_level"]
        self.assertEqual(xpmod.scaled_base_income(st, CORE), base)
        st.village_level = 3
        self.assertEqual(xpmod.scaled_base_income(st, CORE), base + 2 * per)


# ---------------------------------------------------------------------------
class TestOptionRoll(unittest.TestCase):
    def roll(self, state):
        return lv.roll_levelup_options(state, BUILD, CORE, NoShuffle)

    def test_early_pool_offers_unlocks_then_pads(self):
        # Round 1, village level 1: every locked type's unlock card is now
        # gated by its OWN tiers[0].unlock_min_round (there is no more
        # group-level era key). Sun Scorcher (10), Meditator (10), the boost
        # trio (10) and Blocker (5) are all still round-gated out at round 1,
        # so the only real candidates are Maw Mortar (min_village_level 1),
        # Storm Priest (no gate at all) and Painter (min_village_level 0) —
        # exactly three, so the pool needs no fallback pad at round 1.
        st = RunState.from_balance(CORE, BUILD)
        options = self.roll(st)
        self.assertEqual(len(options), 3)
        unlocks = [o for o in options if o["kind"] == "unlock_building"]
        fallbacks = [o for o in options if o["kind"] == "fallback"]
        self.assertEqual([o["title"] for o in unlocks],
                         ["Unlock Maw Mortar", "Unlock Storm Priest",
                          "Unlock Painter"])
        self.assertEqual(len(fallbacks), 0)

    def test_fully_researched_pool_pads_with_fallbacks(self):
        """With every type unlocked and every tier maxed, nothing real is left
        to offer — the roll pads all three slots with the love fallback."""
        st = RunState.from_balance(CORE, BUILD)
        st.unlocked_buildings = dict.fromkeys(st.unlocked_buildings, True)
        st.tiers_unlocked = dict.fromkeys(st.tiers_unlocked, 3)
        options = self.roll(st)
        self.assertEqual(len(options), 3)
        self.assertTrue(all(o["kind"] == "fallback" for o in options))
        self.assertTrue(all(o["amount"] == XP["levelup_love_reward"]
                            for o in options))

    def test_tier_two_enters_the_pool_at_its_unlock_min_round(self):
        st = RunState.from_balance(CORE, BUILD)
        st.round_num = 7
        # No TIER card yet: the defence/economic tier-2s are round-gated to 10 and
        # the Blocker's Bulwark to round 8, so at round 7 the only cards are the
        # two village-level unlocks (Maw Mortar / Painter) — not tier options.
        self.assertFalse(any(o["kind"] == "tier" for o in self.roll(st)))
        st.round_num = 10
        titles = {o["title"] for o in self.roll(st) if o["kind"] == "tier"}
        self.assertEqual(titles, {"Slinger", "Harp Player"})

    def test_only_the_single_next_locked_tier_is_offered(self):
        """With Slinger researched, Pistoleer (round 30) is the only defence
        candidate — and it stays out of the pool until round 30."""
        st = RunState.from_balance(CORE, BUILD)
        st.round_num = 10
        st.tiers_unlocked["defence"] = 2
        tiers = [o for o in self.roll(st) if o["kind"] == "tier"]
        self.assertEqual([o["title"] for o in tiers], ["Harp Player"])
        st.round_num = 30
        titles = {o["title"] for o in self.roll(st) if o["kind"] == "tier"}
        # defence has advanced to its 3rd tier candidate; economic, still at one
        # researched tier, keeps offering only its own next one.
        self.assertEqual(titles, {"Pistoleer", "Harp Player"})

    def test_tier_option_shape(self):
        st = RunState.from_balance(CORE, BUILD)
        st.round_num = 10
        option = next(o for o in self.roll(st)
                      if o.get("building_type") == "defence")
        self.assertEqual(option["kind"], "tier")
        self.assertEqual(option["tier_index"], 1)
        self.assertEqual(option["tier_no"], 2)
        self.assertEqual(option["tier_max"], 3)
        self.assertEqual(option["prev_name"], "Stone Thrower")
        self.assertEqual(option["cost"], DEF_T2["build_cost"])
        self.assertEqual(option["sprite_key"], "slinger_t2_lvl1")

    def test_tier_zero_round_gates_a_locked_types_unlock_card(self):
        """A locked type's UNLOCK card is gated by its own
        tiers[0].unlock_min_round — there is no more group-level era key.
        (Storm Priest carries no gate_kind and its tier 0 round is 0, so
        Meditator — locked, tiers[0].unlock_min_round == 10 — is the clean
        example.) Every other type is maxed out first so it doesn't crowd
        Meditator out of the three-card pool."""
        st = RunState.from_balance(CORE, BUILD)
        for bt in lv.RESEARCH:
            if bt == "meditator":
                continue
            st.unlocked_buildings[bt] = True
            st.tiers_unlocked[bt] = 3
        st.round_num = 9
        self.assertFalse(any(o.get("building_type") == "meditator"
                             for o in self.roll(st)))
        st.round_num = 10
        card = next(o for o in self.roll(st)
                    if o.get("building_type") == "meditator")
        self.assertEqual(card["kind"], "unlock_building")

    def test_tier_zero_round_does_not_gate_an_already_unlocked_types_tiers(self):
        """Once a type is unlocked, its tiers[0].unlock_min_round plays no
        further role — only each tier's OWN unlock_min_round gates it."""
        bal = copy.deepcopy(BUILD)
        bal["DefenceBuildings"]["BasicDefence"]["tiers"][0]["unlock_min_round"] = 9999
        st = RunState.from_balance(CORE, BUILD)   # defence starts unlocked, tier 1
        st.round_num = 10
        titles = {o["title"] for o in lv.roll_levelup_options(
            st, bal, CORE, NoShuffle) if o["kind"] == "tier"}
        self.assertIn("Slinger", titles)          # defence's tier-2 card unaffected

    def test_no_group_carries_era_unlock_round_and_shipped_tier_zero_rounds(self):
        """era_unlock_round is deleted entirely (the Joel-Balancing regate) --
        the single round gate per type is its own tiers[0].unlock_min_round."""
        for group in (BUILD["DefenceBuildings"]["BeamDefence"],
                      BUILD["EconomyBuildings"]["Meditators"],
                      BUILD["StructureBuildings"]["WallBuilder"],
                      BUILD["BoostBuildings"]["globals"]):
            self.assertNotIn("era_unlock_round", group)
        self.assertNotIn("unlock_min_round", BUILD["BoostBuildings"]["globals"])
        self.assertEqual(
            BUILD["DefenceBuildings"]["BeamDefence"]["tiers"][0]["unlock_min_round"],
            10)                                       # was era 14, now tier-0's 10
        self.assertEqual(
            BUILD["EconomyBuildings"]["Meditators"]["tiers"][0]["unlock_min_round"],
            10)
        self.assertEqual(
            BUILD["StructureBuildings"]["WallBuilder"]["tiers"][0]["unlock_min_round"],
            10)
        self.assertEqual(
            BUILD["StructureBuildings"]["Blocker"]["tiers"][0]["unlock_min_round"],
            5)                                        # was ungated, now tier-0's 5
        for group in (BUILD["BoostBuildings"]["Speed"],
                      BUILD["BoostBuildings"]["Damage"],
                      BUILD["BoostBuildings"]["HP"]):
            self.assertEqual(group["tiers"][0]["unlock_min_round"], 10)
        for group in (BUILD["DefenceBuildings"]["AOEDefence"],
                      BUILD["DefenceBuildings"]["BasicDefence"],
                      BUILD["DefenceBuildings"]["StormPriest"],
                      BUILD["EconomyBuildings"]["Musicians"],
                      BUILD["EconomyBuildings"]["Painters"]):
            self.assertEqual(group["tiers"][0]["unlock_min_round"], 0)


# ---------------------------------------------------------------------------
class TestUnlockOptions(unittest.TestCase):
    """The generic type-unlock machinery, driven through a synthetic RESEARCH
    row so the gate mechanics (ungated / village-level / round / grouped) are
    tested in isolation from whichever shipped types happen to be locked."""

    def synthetic(self, spec):
        return mock.patch.dict(lv.RESEARCH, {"economic": spec}, clear=False)

    def locked_state(self):
        st = RunState.from_balance(CORE, BUILD)
        st.unlocked_buildings["economic"] = False
        return st

    def test_ungated_locked_type_offers_an_unlock_card(self):
        spec = ResearchSpec(unlock_title="Unlock Music")
        with self.synthetic(spec):
            options = lv.roll_levelup_options(
                self.locked_state(), BUILD, CORE, NoShuffle)
        card = next(o for o in options if o["kind"] == "unlock_building")
        self.assertEqual(card["title"], "Unlock Music")
        self.assertEqual(card["cost"], 0)             # the unlock is free
        self.assertEqual(card["display_cost"], 10)    # tier-1 build cost
        self.assertEqual(card["building_types"], ("economic",))

    def test_village_level_gate_withholds_the_card(self):
        spec = ResearchSpec(
            gate_kind="min_village_level",
            gate_path=("EconomyBuildings", "Painters",
                       "unlock_min_village_level"))
        bal = copy.deepcopy(BUILD)
        bal["EconomyBuildings"]["Painters"]["unlock_min_village_level"] = 3
        st = self.locked_state()
        with self.synthetic(spec):
            # Scope to the synthetic "economic" card — the shipped Maw Mortar
            # unlock (10B) is also an unlock_building card in every pool.
            self.assertFalse(any(o.get("building_type") == "economic"
                                 for o in lv.roll_levelup_options(
                                     st, bal, CORE, NoShuffle)))
            st.village_level = 3
            self.assertTrue(any(o.get("building_type") == "economic"
                                for o in lv.roll_levelup_options(
                                    st, bal, CORE, NoShuffle)))

    def test_group_unlock_frees_every_type_in_the_group(self):
        spec = ResearchSpec(unlock_group=("economic", "defence"))
        st = self.locked_state()
        st.unlocked_buildings["defence"] = False
        with self.synthetic(spec):
            options = lv.roll_levelup_options(st, BUILD, CORE, NoShuffle)
        card = next(o for o in options if o.get("building_type") == "economic")
        self.assertEqual(card["building_types"], ("economic", "defence"))
        lv.apply_levelup_option(st, card, CORE)
        self.assertTrue(st.unlocked_buildings["economic"])
        self.assertTrue(st.unlocked_buildings["defence"])


# ---------------------------------------------------------------------------
class TestApplyOption(unittest.TestCase):
    def test_tier_option_researches_and_charges(self):
        st = RunState.from_balance(CORE, BUILD)
        st.round_num = 10
        st.love = 100
        option = next(o for o in lv.roll_levelup_options(st, BUILD, CORE,
                                                         NoShuffle)
                      if o.get("building_type") == "defence")
        lv.apply_levelup_option(st, option, CORE)
        self.assertEqual(st.tiers_unlocked["defence"], 2)
        self.assertEqual(st.love, 100 - DEF_T2["build_cost"])

    def test_tier_cost_clamps_love_at_zero(self):
        st = RunState.from_balance(CORE, BUILD)
        st.round_num = 10
        st.love = 5
        option = next(o for o in lv.roll_levelup_options(st, BUILD, CORE,
                                                         NoShuffle)
                      if o.get("building_type") == "defence")
        lv.apply_levelup_option(st, option, CORE)
        self.assertEqual(st.love, 0)

    def test_fallback_pays_love(self):
        st = RunState.from_balance(CORE, BUILD)
        st.love = 0
        # Every type unlocked + maxed -> nothing real to offer -> a fallback
        # is guaranteed in the pool.
        st.unlocked_buildings = dict.fromkeys(st.unlocked_buildings, True)
        st.tiers_unlocked = dict.fromkeys(st.tiers_unlocked, 3)
        fallback = next(o for o in lv.roll_levelup_options(
            st, BUILD, CORE, NoShuffle) if o["kind"] == "fallback")
        lv.apply_levelup_option(st, fallback, CORE)
        self.assertEqual(st.love, XP["levelup_love_reward"])

    def test_unknown_kind_raises(self):
        st = RunState.from_balance(CORE, BUILD)
        with self.assertRaises(ValueError):
            lv.apply_levelup_option(st, {"kind": "nonsense"}, CORE)


# ---------------------------------------------------------------------------
class TestUpgradeGate(unittest.TestCase):
    """The five modes the upgrade button classifies into."""

    def defender(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE, BUILD)
        st.love = 1000
        b, _ = place_building(tm, tm.get(1, 1), "defence", st.love, BUILD,
                              scene, occ, state=st)
        return st, b

    def test_in_tier_below_the_tier_cap(self):
        st, b = self.defender()
        self.assertEqual(lv.upgrade_gate(st, b, BUILD)[0], "in_tier")

    def test_tier_hidden_until_the_next_tiers_unlock_min_round(self):
        st, b = self.defender()
        b.upgrade(); b.upgrade()                      # level 3 of tier 1
        mode, name, cost = lv.upgrade_gate(st, b, BUILD)
        self.assertEqual(mode, "tier_hidden")
        self.assertIsNone(name)                       # the name stays secret
        self.assertEqual(cost, DEF_T2["unlock_min_round"])  # the unlock round

    def test_tier_locked_once_offerable_but_unresearched(self):
        st, b = self.defender()
        b.upgrade(); b.upgrade()
        st.round_num = 10
        mode, name, cost = lv.upgrade_gate(st, b, BUILD)
        self.assertEqual((mode, name, cost),
                         ("tier_locked", DEF_T2["name"], DEF_T2["build_cost"]))

    def test_tier_upgrade_once_researched(self):
        st, b = self.defender()
        b.upgrade(); b.upgrade()
        st.round_num = 10
        st.tiers_unlocked["defence"] = 2
        mode, name, cost = lv.upgrade_gate(st, b, BUILD)
        self.assertEqual((mode, name, cost),
                         ("tier_upgrade", DEF_T2["name"], DEF_T2["build_cost"]))

    def test_max_tier_at_the_end_of_the_line(self):
        st, b = self.defender()
        st.round_num = 30
        st.tiers_unlocked["defence"] = 3
        for _ in range(2):
            b.upgrade(); b.upgrade()
            self.assertTrue(b.advance_tier())
        b.upgrade(); b.upgrade()                      # top of tier 3
        self.assertEqual(lv.upgrade_gate(st, b, BUILD)[0], "max_tier")


# ---------------------------------------------------------------------------
class TestPlacementGate(unittest.TestCase):
    def test_unlocked_type_is_immediately_placeable(self):
        """With ``starts_with_tier`` gone, ``tiers_unlocked_for`` is never below
        1 for an unlocked type -- ``buildable`` collapses to the type-unlock
        check alone, so there is no more "unlocked but tier 0" placement gate."""
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE, BUILD)
        st.love = 1000
        self.assertTrue(buildable(st, "defence"))
        b, _ = place_building(tm, tm.get(1, 1), "defence", st.love, BUILD, scene,
                              occ, state=st)
        self.assertIsNotNone(b)

    def test_locked_type_cannot_be_placed(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE, BUILD)
        st.love = 1000
        st.unlocked_buildings["economic"] = False
        with self.assertRaises(PlacementError):
            place_building(tm, tm.get(1, 1), "economic", st.love, BUILD, scene,
                           occ, state=st)

    def test_no_state_skips_the_gate(self):
        """9D-era stat/logic tests call place_building without a run state."""
        tm, scene, occ = build_board(["bb", "bb"])
        b, _ = place_building(tm, tm.get(1, 1), "defence", 1000, BUILD, scene,
                              occ)
        self.assertIsNotNone(b)


# ---------------------------------------------------------------------------
class TestDefence10BGates(unittest.TestCase):
    """The two 10B defence lines enter the pool by their shipped RESEARCH rows:
    Maw Mortar by village level, Sun Scorcher by its own tiers[0].unlock_min_round
    — both hidden until the unlock card is taken."""

    def roll(self, st):
        return lv.roll_levelup_options(st, BUILD, CORE, NoShuffle)

    def test_maw_mortar_unlock_offered_from_village_level_one(self):
        st = RunState.from_balance(CORE, BUILD)          # village level 1, round 1
        card = next(o for o in self.roll(st)
                    if o.get("building_type") == "aoe_defence")
        self.assertEqual(card["kind"], "unlock_building")
        self.assertEqual(card["title"], "Unlock Maw Mortar")
        self.assertEqual(card["building_types"], ("aoe_defence",))
        self.assertEqual(card["cost"], 0)                    # free unlock
        self.assertEqual(card["display_cost"],
                         BUILD["DefenceBuildings"]["AOEDefence"]["tiers"][0]
                         ["build_cost"])
        self.assertEqual(card["sprite_key"], "maw_mortar_t1_lvl1")

    def test_maw_mortar_gate_reads_the_village_level_key(self):
        bal = copy.deepcopy(BUILD)
        bal["DefenceBuildings"]["AOEDefence"]["unlock_min_village_level"] = 4
        st = RunState.from_balance(CORE, BUILD)
        self.assertFalse(any(o.get("building_type") == "aoe_defence"
                             for o in lv.roll_levelup_options(
                                 st, bal, CORE, NoShuffle)))
        st.village_level = 4
        self.assertTrue(any(o.get("building_type") == "aoe_defence"
                            for o in lv.roll_levelup_options(
                                st, bal, CORE, NoShuffle)))

    def test_sun_scorcher_is_gated_to_its_own_tier_zero_round(self):
        st = RunState.from_balance(CORE, BUILD)
        # Drop the tier competition so both locked-type unlock cards fit the
        # three-card pool regardless of order.
        st.tiers_unlocked["defence"] = 3
        st.tiers_unlocked["economic"] = 3
        gate_round = BUILD["DefenceBuildings"]["BeamDefence"]["tiers"][0][
            "unlock_min_round"]
        st.round_num = gate_round - 1
        self.assertFalse(any(o.get("building_type") == "sun_scorcher"
                             for o in self.roll(st)))
        st.round_num = gate_round
        card = next(o for o in self.roll(st)
                    if o.get("building_type") == "sun_scorcher")
        self.assertEqual(card["kind"], "unlock_building")
        self.assertEqual(card["title"], "Unlock Sun Scorcher")
        self.assertEqual(card["sprite_key"], "sun_scorcher_t1_lvl1")

    def test_unlocking_lets_the_type_be_placed(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE, BUILD)
        st.love = 1000
        with self.assertRaises(PlacementError):           # locked initially
            place_building(tm, tm.get(1, 1), "aoe_defence", st.love, BUILD,
                           scene, occ, state=st)
        card = next(o for o in self.roll(st)
                    if o.get("building_type") == "aoe_defence")
        lv.apply_levelup_option(st, card, CORE)
        self.assertTrue(buildable(st, "aoe_defence"))
        b, _ = place_building(tm, tm.get(1, 1), "aoe_defence", st.love, BUILD,
                              scene, occ, state=st)
        self.assertEqual(b.building_type, "aoe_defence")


# ---------------------------------------------------------------------------
class TestNoDoubleUnlockCard(unittest.TestCase):
    """Regression: Meditator/WallBuilder used to require a free unlock card AND
    a second, identically-titled "research tier 1" card (the deleted
    ``ResearchSpec(starts_with_tier=0)``) before either type was placeable —
    root-caused by ``starts_with_tier=0`` seeding ``tiers_unlocked=0``. Now
    every type seeds tier 1, so ONE unlock card is enough."""

    def _isolate(self, st, btype):
        """Unlock + max every OTHER type so ``btype``'s unlock card is the only
        real candidate left in the pool (avoids a NoShuffle table-order fight
        with the other locked types also eligible at round 10)."""
        for bt in lv.RESEARCH:
            if bt == btype:
                continue
            st.unlocked_buildings[bt] = True
            st.tiers_unlocked[bt] = 3

    def _check(self, btype, tier1_name, tier2_name, tier2_round):
        st = RunState.from_balance(CORE, BUILD)
        self._isolate(st, btype)
        st.round_num = 10                      # every shipped tier-0 round is 10
        card = next(o for o in lv.roll_levelup_options(st, BUILD, CORE, NoShuffle)
                    if o.get("building_type") == btype)
        self.assertEqual(card["kind"], "unlock_building")
        lv.apply_levelup_option(st, card, CORE)
        self.assertTrue(buildable(st, btype))
        # No second card offers the same tier-1 name — the bug this guards.
        next_titles = {o["title"] for o in lv.roll_levelup_options(
            st, BUILD, CORE, NoShuffle)}
        self.assertNotIn(tier1_name, next_titles)
        # The real next card is tier 2, round-gated as shipped.
        st.round_num = tier2_round
        titles = {o["title"] for o in lv.roll_levelup_options(
            st, BUILD, CORE, NoShuffle) if o.get("building_type") == btype}
        self.assertEqual(titles, {tier2_name})

    def test_meditator_unlocks_in_one_card(self):
        self._check("meditator", "Meditator", "Shaman", 20)

    def test_wall_builder_unlocks_in_one_card(self):
        self._check(
            "wall_builder", "Bush Wall Builder", "Wooden Wall Builder", 20)


# ---------------------------------------------------------------------------
class TestLevelupPhase(unittest.TestCase):
    """ROUND_END -> [LEVELUP] -> INCOME."""

    def at_round_end(self, pending):
        session, tm, scene, occ = make_session(rng=NoShuffle)
        st = session.state
        st.phase = GamePhase.ROUND_END
        st.phase_timer = 0.0
        st.levelup_pending = pending
        return session, tm, scene

    def test_round_end_without_pending_runs_payday_directly(self):
        session, tm, scene = self.at_round_end(False)
        before = session.state.love
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.phase, GamePhase.INCOME)
        self.assertEqual(session.state.round_num, 2)
        self.assertEqual(session.state.love,
                         before + CORE["TheHole"]["base_income"])

    def test_round_end_with_pending_opens_the_window_and_defers_payday(self):
        session, tm, scene = self.at_round_end(True)
        before = session.state.love
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.phase, GamePhase.LEVELUP)
        self.assertEqual(session.state.round_num, 1)   # payday NOT run
        self.assertEqual(session.state.love, before)
        self.assertEqual(len(session.state.levelup_options), 3)

    def test_levelup_freezes_the_world(self):
        session, tm, scene = self.at_round_end(True)
        frame(session, scene, tm, 0.1)
        self.assertTrue(session.frozen)
        session.state.phase_timer = 0.0
        for _ in range(5):
            frame(session, scene, tm, 1.0)
        self.assertEqual(session.state.phase, GamePhase.LEVELUP)

    def test_resolve_grants_the_reward_then_runs_payday(self):
        session, tm, scene = self.at_round_end(True)
        # Every type unlocked + maxed -> nothing real to offer -> a fallback
        # is guaranteed in the rolled pool.
        st = session.state
        st.unlocked_buildings = dict.fromkeys(st.unlocked_buildings, True)
        st.tiers_unlocked = dict.fromkeys(st.tiers_unlocked, 3)
        frame(session, scene, tm, 0.1)
        before = st.love
        fallback = next(o for o in st.levelup_options if o["kind"] == "fallback")
        session.resolve_levelup(fallback)                # a +25 Love fallback
        self.assertEqual(st.village_level, 2)
        self.assertFalse(st.levelup_pending)
        self.assertEqual(st.levelup_options, [])
        self.assertEqual(st.phase, GamePhase.INCOME)
        self.assertEqual(st.round_num, 2)
        # +reward love, then payday's village-scaled base income at level 2
        payday = (CORE["TheHole"]["base_income"]
                  + 1 * XP["base_income_per_village_level"])
        self.assertEqual(st.love, before + XP["levelup_love_reward"] + payday)

    def test_payday_scales_base_income_with_village_level(self):
        session, tm, scene = self.at_round_end(False)
        session.state.village_level = 4
        before = session.state.love
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.love,
                         before + CORE["TheHole"]["base_income"]
                         + 3 * XP["base_income_per_village_level"])


# ---------------------------------------------------------------------------
class TestXpAwardSites(unittest.TestCase):
    def enemy(self, tm, etype="standard", col=1, row=0):
        return create_enemy(etype, col, row, ENEM, tm, 0, None, None)

    def test_field_kill_awards_xp_and_counts_the_kill(self):
        session, tm, _, _ = make_session()
        e = self.enemy(tm)
        session.on_enemy_death(e)
        self.assertEqual(session.state.player_xp, 1)
        self.assertEqual(session.state.enemies_killed, 1)
        self.assertEqual(len(session.state.xp_events), 1)

    def test_base_damage_kill_awards_xp_when_the_rule_allows(self):
        session, tm, _, _ = make_session()
        session.on_base_hit(self.enemy(tm))
        self.assertEqual(session.state.player_xp, 1)

    def test_base_damage_kill_awards_nothing_when_the_rule_forbids(self):
        core = copy.deepcopy(CORE)
        core["XP"]["xp_on_base_damage_kill"] = False
        session, tm, _, _ = make_session(core=core)
        session.on_base_hit(self.enemy(tm))
        self.assertEqual(session.state.player_xp, 0)
        self.assertEqual(session.state.enemies_killed, 1)   # still a kill

    def test_a_wipe_pays_queued_enemies_but_not_live_ones(self):
        """A lives-mode breach clears the field silently; the enemies still in
        the spawn queue pay their XP so the round-clear doesn't rob the player."""
        session, tm, scene, _ = make_session(rows=("bs",))
        st = session.state
        st.phase = GamePhase.ENEMY
        # round 3: base_enemy_count is 0 here, so round 1 spawns nothing
        session.spawner.begin_round(3, tm, ENEM)
        queued = len(session.spawner.pending())
        self.assertGreater(queued, 0)
        scene.spawn(self.enemy(tm))                    # one live enemy on field
        scene.update(0.0)
        session.on_base_hit(self.enemy(tm))            # -> lose a life, wipe
        xp_from_breach = st.player_xp
        session.post_sim(scene)
        self.assertEqual(st.player_xp - xp_from_breach, queued)
        self.assertEqual(session.spawner.pending(), [])

    def test_building_death_pays_xp_exactly_once_per_building(self):
        """Prototype quirk: the awarded-id set is never reset, so a building
        that dies, revives at payday and dies again pays only the first time."""
        session, tm, scene, occ = make_session(rows=("bb", "bb"))
        st = session.state
        st.phase = GamePhase.ENEMY
        b, _ = place_building(tm, tm.get(1, 1), "defence", 1000, BUILD, scene,
                              occ, state=st)
        scene.update(0.0)
        b.get_component(Health).damage(10 ** 6)
        session.pre_sim(0.1, scene)
        self.assertEqual(st.player_xp, BUILD["BuildingsGlobal"]["xp_on_death"]["defence"])
        session.pre_sim(0.1, scene)                    # still dead, no re-award
        self.assertEqual(st.player_xp, 1)
        b.rebuild()                                    # payday revive
        b.get_component(Health).damage(10 ** 6)        # dies again
        session.pre_sim(0.1, scene)
        self.assertEqual(st.player_xp, 1)

    def test_building_death_xp_respects_the_feature_flag(self):
        core = copy.deepcopy(CORE)
        core["XP"]["xp_from_buildings"] = False
        session, tm, scene, occ = make_session(rows=("bb", "bb"), core=core)
        st = session.state
        st.phase = GamePhase.ENEMY
        b, _ = place_building(tm, tm.get(1, 1), "defence", 1000, BUILD, scene,
                              occ, state=st)
        scene.update(0.0)
        b.get_component(Health).damage(10 ** 6)
        session.pre_sim(0.1, scene)
        self.assertEqual(st.player_xp, 0)

    def test_a_building_dying_as_the_wave_clears_still_pays(self):
        """``pre_sim`` only sweeps building deaths while the phase is ENEMY, so
        a building that dies on the very frame the round ends would never pay —
        and payday's revive then makes it ``alive`` again, losing the XP for
        good. ``post_sim`` awards on the round-ending frame for exactly this."""
        session, tm, scene, occ = make_session(rows=("bb", "bb"))
        st = session.state
        st.phase = GamePhase.ENEMY
        b, _ = place_building(tm, tm.get(1, 1), "defence", 1000, BUILD, scene,
                              occ, state=st)
        scene.update(0.0)
        session.spawner.clear()                        # drained -> wave clear
        b.get_component(Health).damage(10 ** 6)        # dies THIS frame
        session.post_sim(scene)
        self.assertEqual(st.phase, GamePhase.ROUND_END)
        self.assertEqual(st.player_xp,
                         BUILD["BuildingsGlobal"]["xp_on_death"]["defence"])

    def test_the_base_never_pays_death_xp(self):
        session, tm, scene, _ = make_session()
        st = session.state
        st.phase = GamePhase.ENEMY
        scene.update(0.0)
        base = tm.get(tm.base_col, tm.base_row).occupant
        base.get_component(Health).damage(10 ** 6)
        session.pre_sim(0.1, scene)
        self.assertEqual(st.player_xp, 0)


# ---------------------------------------------------------------------------
class TestLevelupWindow(unittest.TestCase):
    """Hit-testing only — the window's layout must follow the CARD COUNT, which
    is only known at ``open`` (hover/hit run before the first ``submit``)."""

    def window(self, cards=3):
        from game.ui import LevelupWindow      # local: game.ui pulls in fonts
        w = LevelupWindow(640, 360)
        self.assertFalse(w.visible)
        w.open([{"kind": "fallback", "title": f"c{i}", "cost": 0,
                 "explanation": "", "prev_name": None, "sprite_key": None,
                 "cost_label": "", "amount": 25, "reward": "love"}
                for i in range(cards)])
        return w

    def test_open_lays_out_one_box_per_card(self):
        w = self.window()
        self.assertTrue(w.visible)
        self.assertEqual(len(w.rects), 3)
        xs = [r[0] for r in w.rects]
        self.assertEqual(xs, sorted(xs))                # left to right
        self.assertEqual(xs[1] - xs[0], xs[2] - xs[1])  # evenly spaced

    def test_each_box_hits_its_own_card_before_any_submit(self):
        w = self.window()
        for i, (x, y, bw, bh) in enumerate(w.rects):
            cx, cy = x + bw // 2, y + bh // 2
            w.update(0.016, cx, cy)
            self.assertEqual(w.hovered, i)
            self.assertEqual(w.hit(cx, cy)["title"], f"c{i}")

    def test_clicks_outside_every_box_select_nothing(self):
        w = self.window()
        w.update(0.016, 2, 2)
        self.assertEqual(w.hovered, -1)
        self.assertIsNone(w.hit(2, 2))

    def test_close_hides_the_window(self):
        w = self.window()
        w.close()
        self.assertFalse(w.visible)
        self.assertIsNone(w.hit(640, 360))


# ---------------------------------------------------------------------------
class TestPurity(unittest.TestCase):
    def test_game_core_imports_no_pygame(self):
        code = ("import sys; import game.core.levelup, game.core.xp; "
                "assert 'pygame' not in sys.modules, 'pygame leaked'")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                               capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)


if __name__ == "__main__":
    unittest.main()
