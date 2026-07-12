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

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
CORE = load_balance(REPO / "data", "core")
ENEM = load_balance(REPO / "data", "enemies")

XP = CORE["XP"]


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
        resolve_combat(scene, tilemap_, dt, BUILD,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death)
        session.post_sim(scene)


# ---------------------------------------------------------------------------
class TestRunStateSeeding(unittest.TestCase):
    def test_xp_fields_seeded_from_core(self):
        st = RunState.from_balance(CORE)
        self.assertEqual(st.player_xp, 0)
        self.assertEqual(st.village_level, 1)
        self.assertEqual(st.xp_threshold, XP["village_xp_base_threshold"])
        self.assertEqual(st.xp_threshold_inc, XP["village_xp_threshold_inc"])
        self.assertFalse(st.levelup_pending)

    def test_research_seeded_from_table(self):
        st = RunState.from_balance(CORE)
        # 9D lines start unlocked at tier 1; the 10B defence lines start LOCKED
        # (earned via a level-up unlock card) but with tier 1 ready once unlocked.
        # 10C: Painter is a LOCKED type (tier 1 ready once unlocked); Meditator's
        # type is always unlocked but starts at ZERO researched tiers (tier 1
        # researched at a level-up, era-gated to round 10). 10D: the three boost
        # types start LOCKED (unlocked together by one round-10 card) but tier 1
        # ready once unlocked. 10E: Blocker is always unlocked at tier 1
        # (placeable from the start); WallBuilder's type is unlocked but starts at
        # ZERO researched tiers (tier 1 researched at a level-up, era-gated to 5).
        self.assertEqual(
            st.tiers_unlocked,
            {"defence": 1, "economic": 1, "aoe_defence": 1, "sun_scorcher": 1,
             "painter": 1, "meditator": 0,
             "boost_speed": 1, "boost_damage": 1, "boost_hp": 1,
             "blocker": 1, "wall_builder": 0})
        self.assertEqual(
            st.unlocked_buildings,
            {"defence": True, "economic": True,
             "aoe_defence": False, "sun_scorcher": False,
             "painter": False, "meditator": True,
             "boost_speed": False, "boost_damage": False, "boost_hp": False,
             "blocker": True, "wall_builder": True})


# ---------------------------------------------------------------------------
class TestXpMath(unittest.TestCase):
    def test_xp_per_enemy_type(self):
        self.assertEqual(xpmod.xp_for_etype("standard", CORE), 1)
        self.assertEqual(xpmod.xp_for_etype("raider", CORE), 1)
        self.assertEqual(xpmod.xp_for_etype("siege", CORE), 3)
        self.assertEqual(xpmod.xp_for_etype("boss", CORE), 150)

    def test_unknown_etype_pays_standard(self):
        self.assertEqual(xpmod.xp_for_etype("gribbly", CORE), 1)

    def test_award_arms_pending_once_at_threshold(self):
        st = RunState.from_balance(CORE)
        xpmod.award_xp(st, 49)
        self.assertFalse(st.levelup_pending)
        xpmod.award_xp(st, 1)
        self.assertTrue(st.levelup_pending)
        self.assertEqual(st.player_xp, 50)

    def test_award_records_floater_event_only_with_a_position(self):
        st = RunState.from_balance(CORE)
        xpmod.award_xp(st, 3)
        self.assertEqual(st.xp_events, [])
        xpmod.award_xp(st, 2, (4.0, 5.0))
        self.assertEqual(st.xp_events, [(4.0, 5.0, 2)])

    def test_threshold_curve(self):
        """50 -> 65 -> 85 -> 110 -> 140: the increment itself grows by 5."""
        st = RunState.from_balance(CORE)
        seen = [st.xp_threshold]
        for _ in range(4):
            xpmod.advance_village_level(st, CORE)
            seen.append(st.xp_threshold)
        self.assertEqual(seen, [50, 65, 85, 110, 140])
        self.assertEqual(st.village_level, 5)

    def test_surplus_xp_carries_forward(self):
        st = RunState.from_balance(CORE)
        xpmod.award_xp(st, 63)            # threshold 50, surplus 13
        xpmod.advance_village_level(st, CORE)
        self.assertEqual(st.player_xp, 13)
        self.assertEqual(st.xp_threshold, 65)

    def test_scaled_base_income(self):
        st = RunState.from_balance(CORE)
        base = CORE["TheHole"]["base_income"]
        self.assertEqual(xpmod.scaled_base_income(st, CORE), base)
        st.village_level = 3
        self.assertEqual(xpmod.scaled_base_income(st, CORE), base + 4)


# ---------------------------------------------------------------------------
class TestOptionRoll(unittest.TestCase):
    def roll(self, state):
        return lv.roll_levelup_options(state, BUILD, CORE, NoShuffle)

    def test_early_pool_offers_unlocks_then_pads(self):
        # Round 1, village level 1: the tier-2s are round-gated to 10, Sun
        # Scorcher is era-gated to 14 and the Meditator to 10 — so the only real
        # cards are the two village-level-gated unlocks whose gate is met from
        # the start: Maw Mortar (min_village_level 1) and Painter (0). The roll
        # pads the remaining slot with a love fallback.
        st = RunState.from_balance(CORE)
        options = self.roll(st)
        self.assertEqual(len(options), 3)
        unlocks = [o for o in options if o["kind"] == "unlock_building"]
        fallbacks = [o for o in options if o["kind"] == "fallback"]
        self.assertEqual([o["title"] for o in unlocks],
                         ["Unlock Maw Mortar", "Unlock Painter"])
        self.assertEqual(len(fallbacks), 1)
        self.assertTrue(all(o["amount"] == XP["levelup_love_reward"]
                            for o in fallbacks))

    def test_tier_two_enters_the_pool_at_its_unlock_min_round(self):
        st = RunState.from_balance(CORE)
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
        st = RunState.from_balance(CORE)
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
        st = RunState.from_balance(CORE)
        st.round_num = 10
        option = next(o for o in self.roll(st)
                      if o.get("building_type") == "defence")
        self.assertEqual(option["kind"], "tier")
        self.assertEqual(option["tier_index"], 1)
        self.assertEqual(option["tier_no"], 2)
        self.assertEqual(option["tier_max"], 3)
        self.assertEqual(option["prev_name"], "Stone Thrower")
        self.assertEqual(option["cost"], 20)          # tier_unlock_cost
        self.assertEqual(option["sprite_key"], "slinger_t2_lvl1")

    def test_era_gate_excludes_a_type_entirely(self):
        """A group-level era_unlock_round keeps the type out of the pool — even
        when its next tier's own unlock_min_round has passed."""
        bal = copy.deepcopy(BUILD)
        bal["DefenceBuildings"]["BasicDefence"]["era_unlock_round"] = 20
        st = RunState.from_balance(CORE)
        st.round_num = 10
        titles = {o["title"] for o in lv.roll_levelup_options(
            st, bal, CORE, NoShuffle) if o["kind"] == "tier"}
        self.assertEqual(titles, {"Harp Player"})     # defence era-gated out
        st.round_num = 20
        titles = {o["title"] for o in lv.roll_levelup_options(
            st, bal, CORE, NoShuffle) if o["kind"] == "tier"}
        self.assertEqual(titles, {"Slinger", "Harp Player"})

    def test_shipped_era_gates_match_the_canonical_group_key(self):
        """The 10A data lift: the wired Sun Scorcher era is 14 (was a dead 10)."""
        self.assertEqual(
            BUILD["DefenceBuildings"]["BeamDefence"]["era_unlock_round"], 14)
        self.assertEqual(
            BUILD["EconomyBuildings"]["Meditators"]["era_unlock_round"], 10)
        self.assertEqual(
            BUILD["StructureBuildings"]["WallBuilder"]["era_unlock_round"], 5)
        for group in (BUILD["DefenceBuildings"]["BeamDefence"],
                      BUILD["EconomyBuildings"]["Meditators"],
                      BUILD["StructureBuildings"]["WallBuilder"]):
            self.assertNotIn("era_unlock_round", group["tiers"][0])


# ---------------------------------------------------------------------------
class TestUnlockOptions(unittest.TestCase):
    """The generic type-unlock machinery. No shipped type uses it yet (both 9D
    lines start unlocked), so it is driven through a synthetic RESEARCH row —
    exactly the shape 10B-10E will add."""

    def synthetic(self, spec):
        return mock.patch.dict(lv.RESEARCH, {"economic": spec}, clear=False)

    def locked_state(self):
        st = RunState.from_balance(CORE)
        st.unlocked_buildings["economic"] = False
        return st

    def test_ungated_locked_type_offers_an_unlock_card(self):
        spec = ResearchSpec(starts_unlocked=False, unlock_title="Unlock Music")
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
            starts_unlocked=False, gate_kind="min_village_level",
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

    def test_round_gate_withholds_the_card(self):
        spec = ResearchSpec(
            starts_unlocked=False, gate_kind="min_round",
            gate_path=("BoostBuildings", "globals", "unlock_min_round"))
        st = self.locked_state()
        with self.synthetic(spec):
            st.round_num = 9
            self.assertFalse(any(o.get("building_type") == "economic"
                                 for o in lv.roll_levelup_options(
                                     st, BUILD, CORE, NoShuffle)))
            st.round_num = 10   # BoostBuildings.globals.unlock_min_round
            self.assertTrue(any(o.get("building_type") == "economic"
                                for o in lv.roll_levelup_options(
                                    st, BUILD, CORE, NoShuffle)))

    def test_group_unlock_frees_every_type_in_the_group(self):
        spec = ResearchSpec(starts_unlocked=False,
                            unlock_group=("economic", "defence"))
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
        st = RunState.from_balance(CORE)
        st.round_num = 10
        st.love = 100
        option = next(o for o in lv.roll_levelup_options(st, BUILD, CORE,
                                                         NoShuffle)
                      if o.get("building_type") == "defence")
        lv.apply_levelup_option(st, option, CORE)
        self.assertEqual(st.tiers_unlocked["defence"], 2)
        self.assertEqual(st.love, 80)                 # 100 - 20

    def test_tier_cost_clamps_love_at_zero(self):
        st = RunState.from_balance(CORE)
        st.round_num = 10
        st.love = 5
        option = next(o for o in lv.roll_levelup_options(st, BUILD, CORE,
                                                         NoShuffle)
                      if o.get("building_type") == "defence")
        lv.apply_levelup_option(st, option, CORE)
        self.assertEqual(st.love, 0)

    def test_fallback_pays_love(self):
        st = RunState.from_balance(CORE)
        st.love = 0
        fallback = next(o for o in lv.roll_levelup_options(
            st, BUILD, CORE, NoShuffle) if o["kind"] == "fallback")
        lv.apply_levelup_option(st, fallback, CORE)
        self.assertEqual(st.love, XP["levelup_love_reward"])

    def test_unknown_kind_raises(self):
        st = RunState.from_balance(CORE)
        with self.assertRaises(ValueError):
            lv.apply_levelup_option(st, {"kind": "nonsense"}, CORE)


# ---------------------------------------------------------------------------
class TestUpgradeGate(unittest.TestCase):
    """The five modes the upgrade button classifies into."""

    def defender(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE)
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
        self.assertEqual(cost, 10)                    # ...it unlocks at round 10

    def test_tier_locked_once_offerable_but_unresearched(self):
        st, b = self.defender()
        b.upgrade(); b.upgrade()
        st.round_num = 10
        mode, name, cost = lv.upgrade_gate(st, b, BUILD)
        self.assertEqual((mode, name, cost), ("tier_locked", "Slinger", 20))

    def test_tier_upgrade_once_researched(self):
        st, b = self.defender()
        b.upgrade(); b.upgrade()
        st.round_num = 10
        st.tiers_unlocked["defence"] = 2
        mode, name, cost = lv.upgrade_gate(st, b, BUILD)
        self.assertEqual((mode, name, cost), ("tier_upgrade", "Slinger", 20))

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
    def test_unresearched_type_cannot_be_placed(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE)
        st.love = 1000
        st.tiers_unlocked["defence"] = 0              # tier 1 not researched
        with self.assertRaises(PlacementError):
            place_building(tm, tm.get(1, 1), "defence", st.love, BUILD, scene,
                           occ, state=st)
        self.assertFalse(buildable(st, "defence"))

    def test_locked_type_cannot_be_placed(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE)
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
    Maw Mortar by village level, Sun Scorcher by era round — both hidden until
    the unlock card is taken."""

    def roll(self, st):
        return lv.roll_levelup_options(st, BUILD, CORE, NoShuffle)

    def test_maw_mortar_unlock_offered_from_village_level_one(self):
        st = RunState.from_balance(CORE)          # village level 1, round 1
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
        st = RunState.from_balance(CORE)
        self.assertFalse(any(o.get("building_type") == "aoe_defence"
                             for o in lv.roll_levelup_options(
                                 st, bal, CORE, NoShuffle)))
        st.village_level = 4
        self.assertTrue(any(o.get("building_type") == "aoe_defence"
                            for o in lv.roll_levelup_options(
                                st, bal, CORE, NoShuffle)))

    def test_sun_scorcher_is_era_gated_to_round_14(self):
        st = RunState.from_balance(CORE)
        # Drop the tier competition so both locked-type unlock cards fit the
        # three-card pool regardless of order.
        st.tiers_unlocked["defence"] = 3
        st.tiers_unlocked["economic"] = 3
        st.round_num = 13
        self.assertFalse(any(o.get("building_type") == "sun_scorcher"
                             for o in self.roll(st)))
        st.round_num = 14
        card = next(o for o in self.roll(st)
                    if o.get("building_type") == "sun_scorcher")
        self.assertEqual(card["kind"], "unlock_building")
        self.assertEqual(card["title"], "Unlock Sun Scorcher")
        self.assertEqual(card["sprite_key"], "sun_scorcher_t1_lvl1")

    def test_unlocking_lets_the_type_be_placed(self):
        tm, scene, occ = build_board(["bb", "bb"])
        st = RunState.from_balance(CORE)
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
        frame(session, scene, tm, 0.1)
        st = session.state
        before = st.love
        fallback = next(o for o in st.levelup_options if o["kind"] == "fallback")
        session.resolve_levelup(fallback)                # a +25 Love fallback
        self.assertEqual(st.village_level, 2)
        self.assertFalse(st.levelup_pending)
        self.assertEqual(st.levelup_options, [])
        self.assertEqual(st.phase, GamePhase.INCOME)
        self.assertEqual(st.round_num, 2)
        # +25 love, then payday's village-scaled base income (5 + 1*2)
        self.assertEqual(st.love, before + XP["levelup_love_reward"] + 7)

    def test_payday_scales_base_income_with_village_level(self):
        session, tm, scene = self.at_round_end(False)
        session.state.village_level = 4
        before = session.state.love
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.love, before + 5 + 3 * 2)


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
        w = LevelupWindow(1280, 720)
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
