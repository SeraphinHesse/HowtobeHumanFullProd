"""BossUpgradeTimelinePLAN BU-6 — the boss-upgrade domain, engine and hooks.

Three layers, deliberately in ONE module because they are one feature:

1. **The shipped document** (``TestShippedContent``) — the only class here that
   reads live ``data/``, and it reads it as its SUBJECT: does today's
   ``boss_upgrades.json`` still satisfy the design invariants JSON Schema
   cannot express (D1's 4 milestones, D2's 3 slots, D3's at-most-one-placement
   uniqueness, every slot naming a real catalog id, every ``ONE_TIME_IDS``
   member still present)? The same rationale ``test_balancing_data.py`` carries
   for the other domains — see ``test_fixture_guard.ALLOWED``.

2. **The engine** (``game/core/boss_upgrades.py``) — every reader and
   ``apply_pick``, against a HAND-PINNED balance document (``BALANCE`` below),
   never the live one. ``data/CLAUDE.md``: a test that reads today's data is
   testing the designer. ``test_boss.py``'s own ``BOSS_UPGRADES`` pin is the
   precedent, and the two are deliberately separate — that one pins the
   *session flow*, this one the *engine*.

3. **The hook-site helpers** that live too far from any one existing suite to
   have a natural home: the buildings-side free-advance
   (``boss_upgrade_effects``), the two combat-side spec resolvers, the shared
   slow seam, thorns' reflect arithmetic and the 3-card cutscene picker. The
   hook sites that DO have a home were extended there instead —
   ``test_tile_unlock.py`` (#6), ``test_structure.py`` (#2 + #8),
   ``test_building_movement.py`` (#4), ``test_boost.py`` (#10),
   ``test_lightning.py`` (#7), ``test_buff_debuff_arrows.py`` (D20).

Pure-Python, headless: the ``test_phase_loop`` synth-``TileMap`` fixture style
with real balancing off the pinned ``FIXTURE_DATA`` snapshot.
"""
import copy
import json
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import data_io, tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import (
    BaseBuilding, attach_base, create, place_building,
)
from game.buildings.boss_upgrade_effects import (
    advance_free_levels, advance_free_to_level, apply_musician_auto_level,
    placed_buildings, sync_stone_throwers,
)
from game.buildings.defender import Defender
from game.buildings.musician import Musician
from game.core import RunState, load_balance
from game.core import boss_upgrades as bu
from game.core import lightning as lt
from game.enemies import create_enemy
from game.enemies import components as ec
from game.enemies import combat as cb
from game.map.tile_map import TileMap
from game.map.tiles import TileCondition
from game.ui.boss_cutscene import BossCutscene

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")

# The live pair — read ONLY by TestShippedContent (see the module docstring).
LIVE_DOC = REPO / "data" / "balancing" / "boss_upgrades.json"
LIVE_SCHEMA = REPO / "data" / "schemas" / "boss_upgrades.schema.json"


def _catalog(**params_by_id):
    return {uid: {"name": uid.replace("_", " ").title(),
                  "description": "x", "params": dict(p)}
            for uid, p in params_by_id.items()}


#: THE hand-pinned balance every behavioural assertion below reads. Written
#: out rather than loaded so a designer retuning ``discount_pct`` can never
#: decide whether this suite is green (``data/CLAUDE.md``); it carries all 12
#: real ids so an id typo here is still a typo against the real roster.
BALANCE = {
    "BossUpgrades": {
        "Catalog": _catalog(
            restock_lives={},
            wall_cost_discount={"cost_reduction_pct": 50},
            mortar_slow={"slow_pct": 20, "duration_seconds": 2.5},
            move_time_cap={"move_time_cap": 1},
            musician_auto_level={"bonus_levels": 1},
            tile_discount={"discount_pct": 20},
            stormpriest_slow={"slow_pct": 20, "duration_seconds": 2.5},
            thorns={"reflect_pct": 10},
            stone_thrower_sync={},
            boost_double_trigger={"extra_triggers": 1},
            condition_dmg_bonus={"dmg_bonus_pct": 20},
            tile_refund={},
        ),
        "Timeline": {"milestones": [
            {"slots": ["restock_lives", "mortar_slow", "tile_discount"],
             "retaliation_bonus_love": 30},
            {"slots": ["thorns", "musician_auto_level", "move_time_cap"],
             "retaliation_bonus_love": 60},
            {"slots": ["stormpriest_slow", "wall_cost_discount", None],
             "retaliation_bonus_love": 100},
            {"slots": ["condition_dmg_bonus", "boost_double_trigger",
                       "tile_refund"],
             "retaliation_bonus_love": 150},
        ]},
    }
}

MILESTONES = BALANCE["BossUpgrades"]["Timeline"]["milestones"]


def run_state():
    return RunState.from_balance(CORE, BUILD)


def picked(*upgrade_ids):
    """A ``RunState`` with each id picked once (twice if listed twice)."""
    st = run_state()
    for uid in upgrade_ids:
        st.boss_upgrade_stacks[uid] = st.boss_upgrade_stacks.get(uid, 0) + 1
    return st


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def board(rows="bbbbbb"):
    tm = synth([rows] * len(rows))
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


# ---------------------------------------------------------------------------
# 1. The shipped document — invariants the schema cannot state (live data/)
# ---------------------------------------------------------------------------
class TestShippedContent(unittest.TestCase):
    """The ONE live-data class here. Its subject IS today's tree: these are
    the D1/D2/D3 authoring rules JSON Schema cannot express, so nothing else
    catches a designer (or an agent) breaking one."""

    @classmethod
    def setUpClass(cls):
        cls.doc = data_io.load_validated(LIVE_DOC, LIVE_SCHEMA)
        cls.catalog = cls.doc["BossUpgrades"]["Catalog"]
        cls.milestones = cls.doc["BossUpgrades"]["Timeline"]["milestones"]

    def test_the_pair_validates_and_is_canonical_on_disk(self):
        raw = LIVE_DOC.read_text(encoding="utf-8")
        self.assertEqual(raw, data_io.dumps_deterministic(self.doc),
                         "boss_upgrades.json is not in canonical D-3 form — "
                         "write it through engine.data_io, never by hand")
        jsonschema.Draft202012Validator.check_schema(
            json.loads(LIVE_SCHEMA.read_text(encoding="utf-8")))

    def test_the_catalog_is_the_closed_set_of_twelve(self):
        self.assertEqual(len(self.catalog), 12)
        for uid, entry in self.catalog.items():
            with self.subTest(upgrade=uid):
                self.assertTrue(entry["name"].strip())
                self.assertTrue(entry["description"].strip())
                self.assertIsInstance(entry["params"], dict)

    def test_every_one_time_id_is_a_real_catalog_key(self):
        """``ONE_TIME_IDS`` is a hardcoded dispatch table in the engine; an id
        that fell out of the catalog would make it dispatch on nothing."""
        for uid in bu.ONE_TIME_IDS:
            self.assertIn(uid, self.catalog)

    def test_every_description_formats_against_its_own_params(self):
        """The cutscene card formats the description with the upgrade's live
        params. A placeholder with no matching param would show raw braces."""
        for uid, entry in self.catalog.items():
            with self.subTest(upgrade=uid):
                entry["description"].format(**entry["params"])

    def test_four_milestones_of_three_slots_each(self):
        self.assertEqual(len(self.milestones), bu.milestone_index(5) + 4)
        self.assertEqual(len(self.milestones), 4)          # D1, spelled out
        for i, m in enumerate(self.milestones):
            with self.subTest(milestone=i):
                self.assertEqual(len(m["slots"]), 3)       # D2
                self.assertGreaterEqual(m["retaliation_bonus_love"], 0)

    def test_every_placed_slot_names_a_catalog_id(self):
        for i, m in enumerate(self.milestones):
            for j, uid in enumerate(m["slots"]):
                with self.subTest(milestone=i, slot=j):
                    if uid is not None:
                        self.assertIn(uid, self.catalog)

    def test_no_upgrade_is_placed_twice(self):
        """D3 — 'seen once' is an AUTHORING constraint: at most one slot per
        upgrade across the whole timeline. The editor warns; nothing in the
        game enforces it, so the shipped file is pinned here."""
        placed = [uid for m in self.milestones for uid in m["slots"]
                  if uid is not None]
        self.assertEqual(sorted(placed), sorted(set(placed)))


# ---------------------------------------------------------------------------
# 2. The engine — the cycle, the readers, apply_pick
# ---------------------------------------------------------------------------
class TestMilestoneCycle(unittest.TestCase):
    def test_boss_num_is_one_based_and_wraps_every_four(self):
        self.assertEqual([bu.milestone_index(n) for n in range(1, 10)],
                         [0, 1, 2, 3, 0, 1, 2, 3, 0])

    def test_boss_five_re_offers_boss_ones_identical_options(self):
        self.assertEqual(bu.milestone_slots(BALANCE, 5),
                         bu.milestone_slots(BALANCE, 1))
        self.assertEqual(bu.milestone_slots(BALANCE, 1), MILESTONES[0]["slots"])

    def test_slots_are_a_copy_not_the_live_list(self):
        got = bu.milestone_slots(BALANCE, 1)
        got[0] = "tampered"
        self.assertEqual(MILESTONES[0]["slots"][0], "restock_lives")

    def test_an_empty_slot_survives_as_none(self):
        self.assertEqual(bu.milestone_slots(BALANCE, 3)[2], None)

    def test_retaliation_love_cycles_with_the_milestones(self):
        for boss_num in range(1, 9):
            with self.subTest(boss=boss_num):
                self.assertEqual(
                    bu.retaliation_love(BALANCE, boss_num),
                    MILESTONES[bu.milestone_index(boss_num)]
                    ["retaliation_bonus_love"])

    def test_no_balance_offers_three_empty_slots_and_pays_nothing(self):
        """The `timeline_level_for` tolerance: a bare Session a logic test
        builds wires no boss_upgrades balance and must not crash."""
        self.assertEqual(bu.milestone_slots(None, 1), [None, None, None])
        self.assertEqual(bu.retaliation_love(None, 1), 0)


class TestReaders(unittest.TestCase):
    def test_stack_count_is_zero_until_picked_then_counts_picks(self):
        st = run_state()
        self.assertEqual(bu.stack_count(st, "thorns"), 0)
        bu.apply_pick(st, "thorns", BALANCE, CORE)
        bu.apply_pick(st, "thorns", BALANCE, CORE)
        self.assertEqual(bu.stack_count(st, "thorns"), 2)

    def test_catalog_params_reads_the_authored_dict(self):
        self.assertEqual(bu.catalog_params(BALANCE, "thorns"),
                         {"reflect_pct": 10})

    def test_catalog_params_is_empty_for_no_balance_or_unknown_id(self):
        self.assertEqual(bu.catalog_params(None, "thorns"), {})
        self.assertEqual(bu.catalog_params(BALANCE, "not_an_upgrade"), {})
        self.assertEqual(bu.catalog_params(BALANCE, "restock_lives"), {})

    def test_hook_stacks_is_inert_whenever_either_half_is_missing(self):
        st = picked("thorns")
        self.assertEqual(bu.hook_stacks(None, BALANCE, "thorns"), (0, {}))
        self.assertEqual(bu.hook_stacks(st, None, "thorns"), (0, {}))

    def test_hook_stacks_is_inert_for_an_unpicked_upgrade(self):
        self.assertEqual(bu.hook_stacks(run_state(), BALANCE, "thorns"),
                         (0, {}))

    def test_hook_stacks_returns_the_count_and_the_params(self):
        st = picked("thorns", "thorns")
        self.assertEqual(bu.hook_stacks(st, BALANCE, "thorns"),
                         (2, {"reflect_pct": 10}))


class TestDiscounted(unittest.TestCase):
    """The shared %-off reducer behind #2 and #6 (D4: additive per pick)."""

    def _cut(self, state, cost=100, floor=0):
        return bu.discounted(cost, state, BALANCE, "tile_discount",
                             "discount_pct", 20, floor=floor)

    def test_an_unpicked_upgrade_leaves_the_price_alone(self):
        self.assertEqual(self._cut(run_state()), 100)

    def test_no_pair_leaves_the_price_alone(self):
        self.assertEqual(
            bu.discounted(100, None, BALANCE, "tile_discount",
                          "discount_pct", 20), 100)
        self.assertEqual(
            bu.discounted(100, run_state(), None, "tile_discount",
                          "discount_pct", 20), 100)

    def test_picks_stack_additively_never_multiplicatively(self):
        one = self._cut(picked("tile_discount"))
        two = self._cut(picked("tile_discount", "tile_discount"))
        self.assertEqual(one, 80)                 # -20%
        self.assertEqual(two, 60)                 # -40%, NOT 0.8*0.8 = 64
        self.assertEqual(100 - two, 2 * (100 - one))

    def test_the_floor_clamps_a_big_stack(self):
        st = picked(*["tile_discount"] * 9)        # -180%
        self.assertEqual(self._cut(st, floor=0), 0)      # a tile CAN be free
        self.assertEqual(self._cut(st, floor=1), 1)      # a wall never is

    def test_a_deleted_param_key_falls_back_to_the_shipped_default(self):
        bal = copy.deepcopy(BALANCE)
        bal["BossUpgrades"]["Catalog"]["tile_discount"]["params"] = {}
        self.assertEqual(
            bu.discounted(100, picked("tile_discount"), bal, "tile_discount",
                          "discount_pct", 20), 80)


class TestApplyPick(unittest.TestCase):
    def tearDown(self):
        for uid in ("stone_thrower_sync", "mortar_slow"):
            bu.set_one_time_hook(uid, None)

    def test_every_pick_increments_its_stack(self):
        st = run_state()
        bu.apply_pick(st, "wall_cost_discount", BALANCE, CORE)
        self.assertEqual(st.boss_upgrade_stacks, {"wall_cost_discount": 1})
        bu.apply_pick(st, "wall_cost_discount", BALANCE, CORE)
        self.assertEqual(st.boss_upgrade_stacks, {"wall_cost_discount": 2})

    def test_restock_lives_refills_from_the_core_balance(self):
        st = run_state()
        full = CORE["TheHole"]["base_lives"]
        st.base_lives = 1
        bu.apply_pick(st, "restock_lives", BALANCE, CORE)
        self.assertEqual(st.base_lives, full)

    def test_restock_lives_re_triggers_idempotently(self):
        """D4: a one-time effect picked again simply re-fires."""
        st = run_state()
        st.base_lives = 1
        bu.apply_pick(st, "restock_lives", BALANCE, CORE)
        st.base_lives = 2
        bu.apply_pick(st, "restock_lives", BALANCE, CORE)
        self.assertEqual(st.base_lives, CORE["TheHole"]["base_lives"])
        self.assertEqual(st.boss_upgrade_stacks["restock_lives"], 2)

    def test_tile_refund_pays_back_the_tile_spend_ledger(self):
        st = run_state()
        st.love_spent_on_tiles = 137
        love_before = st.love
        bu.apply_pick(st, "tile_refund", BALANCE, CORE)
        self.assertEqual(st.love, love_before + 137)

    def test_tile_refund_with_nothing_spent_pays_nothing(self):
        st = run_state()
        love_before = st.love
        bu.apply_pick(st, "tile_refund", BALANCE, CORE)
        self.assertEqual(st.love, love_before)

    def test_a_persistent_passive_only_counts_its_stack(self):
        st = run_state()
        love_before, lives_before = st.love, st.base_lives
        bu.apply_pick(st, "thorns", BALANCE, CORE)
        self.assertEqual((st.love, st.base_lives), (love_before, lives_before))

    def test_the_one_time_hook_needs_BOTH_a_tilemap_and_a_scene(self):
        calls = []
        bu.set_one_time_hook("stone_thrower_sync",
                             lambda s, tm, sc: calls.append((s, tm, sc)))
        st = run_state()
        tm, scene, _occ = board()
        bu.apply_pick(st, "stone_thrower_sync", BALANCE, CORE)
        bu.apply_pick(st, "stone_thrower_sync", BALANCE, CORE, tilemap=tm)
        bu.apply_pick(st, "stone_thrower_sync", BALANCE, CORE, scene=scene)
        self.assertEqual(calls, [], "a pick with no world in hand must be a "
                                    "silent no-op, never a crash")
        bu.apply_pick(st, "stone_thrower_sync", BALANCE, CORE,
                      tilemap=tm, scene=scene)
        self.assertEqual(calls, [(st, tm, scene)])
        self.assertEqual(st.boss_upgrade_stacks["stone_thrower_sync"], 4)

    def test_no_hook_installed_is_a_harmless_no_op(self):
        st = run_state()
        tm, scene, _occ = board()
        bu.apply_pick(st, "stone_thrower_sync", BALANCE, CORE,
                      tilemap=tm, scene=scene)
        self.assertEqual(st.boss_upgrade_stacks["stone_thrower_sync"], 1)

    def test_a_PERSISTENT_upgrade_may_also_register_a_pick_time_hook(self):
        """The load-bearing half of the seam: the hook table is looked up by
        id INDEPENDENTLY of ONE_TIME_IDS, which is what lets mortar_slow (a
        persistent passive) take its D16 snapshot at pick time."""
        self.assertNotIn("mortar_slow", bu.ONE_TIME_IDS)
        fired = []
        bu.set_one_time_hook("mortar_slow", lambda s, tm, sc: fired.append(1))
        st = run_state()
        tm, scene, _occ = board()
        bu.apply_pick(st, "mortar_slow", BALANCE, CORE,
                      tilemap=tm, scene=scene)
        self.assertEqual(fired, [1])

    def test_set_one_time_hook_none_clears_it(self):
        fired = []
        bu.set_one_time_hook("mortar_slow", lambda s, tm, sc: fired.append(1))
        bu.set_one_time_hook("mortar_slow", None)
        tm, scene, _occ = board()
        bu.apply_pick(run_state(), "mortar_slow", BALANCE, CORE,
                      tilemap=tm, scene=scene)
        self.assertEqual(fired, [])


class TestEnginePurity(unittest.TestCase):
    def test_the_effect_engine_imports_no_buildings_or_enemies(self):
        """BU-2's hard rule — the reason the one-time hook seam exists at
        all. A grep, not an import graph: the ban is on the SOURCE."""
        src = (REPO / "game" / "core" / "boss_upgrades.py").read_text(
            encoding="utf-8")
        code = "\n".join(line for line in src.splitlines()
                         if line.startswith(("import ", "from ")))
        for banned in ("game.buildings", "game.enemies", "pygame"):
            self.assertNotIn(banned, code)


# ---------------------------------------------------------------------------
# 3a. Buildings-side hook helpers (#5, #9)
# ---------------------------------------------------------------------------
class TestFreeAdvance(unittest.TestCase):
    """``boss_upgrade_effects`` is the ONE place a building levels for free —
    and it must go through ``upgrade()``/``advance_tier()`` so
    ``apply_tier_stats`` (and its full-heal) still fires."""

    def _defender(self):
        return create("defence", 0, 0, BUILD)

    def test_advance_free_levels_stays_inside_the_current_tier(self):
        b = self._defender()
        tier_before = b.tier_number()
        granted = advance_free_levels(b, 1)
        self.assertEqual(granted, 1)
        self.assertEqual(b.level, 2)
        self.assertEqual(b.tier_number(), tier_before)

    def test_advance_free_levels_never_crosses_a_tier_boundary(self):
        """A tier advance is gated on research; a placement bonus must not
        hand out a tier the run has not earned."""
        b = self._defender()
        before_tier = b.tier_number()
        granted = advance_free_levels(b, 99)
        self.assertLess(granted, 99)
        self.assertEqual(b.tier_number(), before_tier)

    def test_advance_free_levels_full_heals_through_the_normal_path(self):
        b = self._defender()
        health = b.get_component(Health)
        health.hp = 1
        advance_free_levels(b, 1)
        self.assertEqual(health.hp, health.max_hp)

    def test_advance_free_to_level_crosses_tiers_and_stops_at_the_ceiling(self):
        b = self._defender()
        advance_free_to_level(b, 4)
        self.assertEqual(b.level, 4)
        self.assertGreater(b.tier_number(), 1)      # it crossed a boundary
        advance_free_to_level(b, 10_000)            # unreachable -> lands high
        top = b.level
        advance_free_to_level(b, 10_000)
        self.assertEqual(b.level, top)              # and stays there


class TestStoneThrowerSync(unittest.TestCase):
    """#9 — one-time (D17), levels every placed Defender up to the best one."""

    def _board_with_defenders(self, n):
        # col 0 is the base's own BUILT tile — placements start at col 1.
        tm, scene, occ = board()
        built = [place_building(tm, tm.get(i + 1, 0), "defence", 10 ** 6,
                                BUILD, scene, occ)[0] for i in range(n)]
        return tm, scene, built

    def test_a_lone_defender_changes_nothing(self):
        tm, scene, built = self._board_with_defenders(1)
        self.assertEqual(sync_stone_throwers(run_state(), tm, scene), 0)
        self.assertEqual(built[0].level, 1)

    def test_every_defender_is_levelled_up_to_the_best_one(self):
        tm, scene, built = self._board_with_defenders(3)
        advance_free_to_level(built[1], 4)
        target = built[1].level
        changed = sync_stone_throwers(run_state(), tm, scene)
        self.assertEqual(changed, 2)
        self.assertEqual([b.level for b in built], [target] * 3)

    def test_an_already_matched_board_is_a_no_op(self):
        tm, scene, built = self._board_with_defenders(2)
        self.assertEqual(sync_stone_throwers(run_state(), tm, scene), 0)

    def test_it_only_sweeps_defenders(self):
        tm, scene, occ = board()
        d, _ = place_building(tm, tm.get(1, 0), "defence", 10 ** 6,
                              BUILD, scene, occ)
        m, _ = place_building(tm, tm.get(2, 0), "economic", 10 ** 6,
                              BUILD, scene, occ)
        advance_free_to_level(d, 3)
        sync_stone_throwers(run_state(), tm, scene)
        self.assertEqual(m.level, 1)
        self.assertEqual(placed_buildings(tm, Defender), [d])
        self.assertEqual(placed_buildings(tm, Musician), [m])


class TestMusicianAutoLevel(unittest.TestCase):
    """#5 — placement-time, Musician line only (D12), additive per pick."""

    def _place(self, btype, state=None, balance=None, col=1):
        # col 0 is the base's own BUILT tile — placements start at col 1.
        tm, scene, occ = board()
        b, _cost = place_building(
            tm, tm.get(col, 0), btype, 10 ** 6, BUILD, scene, occ,
            state=state, boss_upgrades_balance=balance)
        return b

    def test_a_fresh_placement_is_unchanged_without_the_pair(self):
        self.assertEqual(self._place("economic").level, 1)
        self.assertEqual(
            self._place("economic", state=picked("musician_auto_level")).level,
            1, "the RunState alone must not arm the hook")

    def test_an_unpicked_upgrade_leaves_the_placement_alone(self):
        b = self._place("economic", state=run_state(), balance=BALANCE)
        self.assertEqual(b.level, 1)

    def test_one_pick_grants_one_bonus_level(self):
        b = self._place("economic", state=picked("musician_auto_level"),
                        balance=BALANCE)
        self.assertEqual(b.level, 2)

    def test_two_picks_stack_additively(self):
        st = picked("musician_auto_level", "musician_auto_level")
        self.assertEqual(self._place("economic", state=st,
                                     balance=BALANCE).level, 3)

    def test_a_non_musician_is_never_levelled(self):
        st = picked("musician_auto_level")
        self.assertEqual(
            self._place("defence", state=st, balance=BALANCE).level, 1)
        self.assertEqual(
            apply_musician_auto_level(create("defence", 0, 0, BUILD), st,
                                      BALANCE), 0)


# ---------------------------------------------------------------------------
# 3b. Combat-side hook helpers (#3, #7, #8, #11) + the shared slow seam
# ---------------------------------------------------------------------------
class TestConditionDamageBonus(unittest.TestCase):
    """#11 — the multiplier reads the TARGET's OWN tile condition (D15)."""

    def _enemy(self, condition):
        tm = synth(["bbbb"] * 4)
        e = create_enemy("standard", 2, 2, ENEM, tm)
        e.get_component(ec.PathAgent)._current_condition = condition
        return e

    def test_grass_never_counts(self):
        e = self._enemy(TileCondition.GRASS)
        self.assertFalse(ec.on_non_grass_condition(e))
        self.assertEqual(
            cb._condition_bonus_dmg(100, e, picked("condition_dmg_bonus"),
                                    BALANCE), 100)

    def test_every_non_grass_condition_counts(self):
        for cond in (TileCondition.MOUNTAIN, TileCondition.POND,
                     TileCondition.FOREST):
            with self.subTest(condition=cond.name):
                e = self._enemy(cond)
                self.assertTrue(ec.on_non_grass_condition(e))
                self.assertEqual(
                    cb._condition_bonus_dmg(
                        100, e, picked("condition_dmg_bonus"), BALANCE), 120)

    def test_picks_stack_additively(self):
        e = self._enemy(TileCondition.POND)
        st = picked("condition_dmg_bonus", "condition_dmg_bonus")
        self.assertEqual(cb._condition_bonus_dmg(100, e, st, BALANCE), 140)

    def test_the_hook_is_inert_without_the_pair_or_a_pick(self):
        e = self._enemy(TileCondition.POND)
        self.assertEqual(cb._condition_bonus_dmg(100, e, None, BALANCE), 100)
        self.assertEqual(cb._condition_bonus_dmg(100, e, picked(), None), 100)
        self.assertEqual(
            cb._condition_bonus_dmg(100, e, run_state(), BALANCE), 100)

    def test_a_stub_with_no_path_agent_reads_as_grass(self):
        self.assertFalse(ec.on_non_grass_condition(object()))


class TestMortarSlowSpec(unittest.TestCase):
    """#3 — snapshot-scoped to the mortars alive at pick time (D16)."""

    def _mortar(self):
        return create("aoe_defence", 0, 0, BUILD)

    def test_a_mortar_outside_the_snapshot_never_slows(self):
        m = self._mortar()
        st = picked("mortar_slow")
        self.assertIsNone(cb._mortar_slow_spec(m, st, BALANCE))

    def test_a_snapshotted_mortar_slows_by_the_authored_fraction(self):
        m = self._mortar()
        st = picked("mortar_slow")
        st.mortar_slow_snapshot_ids.add(id(m))
        source, fraction, duration = cb._mortar_slow_spec(m, st, BALANCE)
        self.assertEqual(source, cb.MORTAR_SLOW_SOURCE)
        self.assertAlmostEqual(fraction, 0.20)
        self.assertAlmostEqual(duration, 2.5)

    def test_repeat_picks_deepen_the_slow_but_not_its_duration(self):
        m = self._mortar()
        st = picked("mortar_slow", "mortar_slow")
        st.mortar_slow_snapshot_ids.add(id(m))
        _source, fraction, duration = cb._mortar_slow_spec(m, st, BALANCE)
        self.assertAlmostEqual(fraction, 0.40)
        self.assertAlmostEqual(duration, 2.5)

    def test_it_is_inert_without_the_pair_or_a_pick(self):
        m = self._mortar()
        st = run_state()
        st.mortar_slow_snapshot_ids.add(id(m))
        self.assertIsNone(cb._mortar_slow_spec(m, st, BALANCE))
        self.assertIsNone(cb._mortar_slow_spec(m, None, BALANCE))
        self.assertIsNone(cb._mortar_slow_spec(m, picked("mortar_slow"), None))

    def test_one_source_key_for_the_whole_upgrade(self):
        """N mortars hitting one enemy must read as ONE slow, or a
        bombardment would stack into a full stop."""
        a, b = self._mortar(), self._mortar()
        st = picked("mortar_slow")
        st.mortar_slow_snapshot_ids.update((id(a), id(b)))
        self.assertEqual(cb._mortar_slow_spec(a, st, BALANCE)[0],
                         cb._mortar_slow_spec(b, st, BALANCE)[0])


class TestStormpriestSlowSpec(unittest.TestCase):
    """#7 — live, never snapshotted: every acolyte, whenever it was built."""

    def test_inert_until_picked(self):
        self.assertIsNone(lt._slow_spec(run_state(), BALANCE))

    def test_picked_resolves_source_fraction_and_duration(self):
        source, fraction, duration = lt._slow_spec(
            picked("stormpriest_slow"), BALANCE)
        self.assertEqual(source, lt.STORMPRIEST_SLOW_SOURCE)
        self.assertAlmostEqual(fraction, 0.20)
        self.assertAlmostEqual(duration, 2.5)

    def test_repeat_picks_stack_the_fraction_only(self):
        _s, fraction, duration = lt._slow_spec(
            picked("stormpriest_slow", "stormpriest_slow"), BALANCE)
        self.assertAlmostEqual(fraction, 0.40)
        self.assertAlmostEqual(duration, 2.5)

    def test_the_two_slows_use_distinct_source_keys(self):
        self.assertNotEqual(lt.STORMPRIEST_SLOW_SOURCE, cb.MORTAR_SLOW_SOURCE)


class TestSharedSlowSeam(unittest.TestCase):
    """D19 — one slow mechanism, living on the Drummer's own ``BuffState``."""

    def _enemy(self):
        tm = synth(["bbbb"] * 4)
        return create_enemy("standard", 2, 2, ENEM, tm)

    def test_apply_slow_writes_a_negative_move_speed_contribution(self):
        e = self._enemy()
        self.assertTrue(ec.apply_slow(e, "src", 0.25, 2.5))
        self.assertAlmostEqual(ec.buff_total(e, "move_speed"), -0.25)

    def test_a_positive_magnitude_can_never_speed_an_enemy_up(self):
        e = self._enemy()
        ec.apply_slow(e, "src", -0.25, 2.5)          # a caller's sign slip
        self.assertLess(ec.buff_total(e, "move_speed"), 0)

    def test_one_source_key_refreshes_instead_of_stacking(self):
        e = self._enemy()
        for _ in range(5):
            ec.apply_slow(e, cb.MORTAR_SLOW_SOURCE, 0.2, 2.5)
        self.assertAlmostEqual(ec.buff_total(e, "move_speed"), -0.2)

    def test_two_different_sources_do_stack(self):
        e = self._enemy()
        ec.apply_slow(e, cb.MORTAR_SLOW_SOURCE, 0.2, 2.5)
        ec.apply_slow(e, lt.STORMPRIEST_SLOW_SOURCE, 0.2, 2.5)
        self.assertAlmostEqual(ec.buff_total(e, "move_speed"), -0.4)

    def test_an_inert_magnitude_or_duration_writes_nothing(self):
        e = self._enemy()
        self.assertFalse(ec.apply_slow(e, "src", 0.0, 2.5))
        self.assertFalse(ec.apply_slow(e, "src", 0.2, 0.0))
        self.assertFalse(ec.apply_slow(None, "src", 0.2, 2.5))
        self.assertEqual(ec.buff_total(e, "move_speed"), 0.0)

    def test_an_owner_with_no_buff_state_is_refused_not_crashed(self):
        self.assertFalse(ec.apply_slow(create("defence", 0, 0, BUILD),
                                       "src", 0.2, 2.5))

    def test_the_slow_expires_on_its_own_duration_clock(self):
        e = self._enemy()
        ec.apply_slow(e, "src", 0.2, 1.0)
        buffs = e.get_component(ec.BuffState)
        buffs.update(0.5)
        self.assertAlmostEqual(ec.buff_total(e, "move_speed"), -0.2)
        buffs.update(0.6)
        self.assertEqual(ec.buff_total(e, "move_speed"), 0.0)


class TestThornsReflect(unittest.TestCase):
    """#8 — a proportion of a landed blow, reflected onto the ATTACKER."""

    def setUp(self):
        self.addCleanup(ec.set_boss_upgrade_pair)

    def _enemy(self):
        tm = synth(["bbbb"] * 4)
        return create_enemy("standard", 2, 2, ENEM, tm)

    def test_no_pair_installed_reflects_nothing(self):
        e = self._enemy()
        hp = e.get_component(Health).hp
        self.assertEqual(ec._apply_thorns(e, 100), 0)
        self.assertEqual(e.get_component(Health).hp, hp)

    def test_an_unpicked_upgrade_reflects_nothing(self):
        ec.set_boss_upgrade_pair(run_state(), BALANCE)
        self.assertEqual(ec._apply_thorns(self._enemy(), 100), 0)

    def test_one_pick_reflects_the_authored_percentage(self):
        e = self._enemy()
        ec.set_boss_upgrade_pair(picked("thorns"), BALANCE)
        hp = e.get_component(Health).hp
        self.assertEqual(ec._apply_thorns(e, 100), 10)
        self.assertEqual(e.get_component(Health).hp, hp - 10)

    def test_picks_stack_additively(self):
        ec.set_boss_upgrade_pair(picked("thorns", "thorns"), BALANCE)
        self.assertEqual(ec._apply_thorns(self._enemy(), 100), 20)

    def test_a_blow_too_small_to_reflect_a_whole_point_reflects_nothing(self):
        e = self._enemy()
        ec.set_boss_upgrade_pair(picked("thorns"), BALANCE)
        hp = e.get_component(Health).hp
        self.assertEqual(ec._apply_thorns(e, 9), 0)   # int(0.9) == 0
        self.assertEqual(e.get_component(Health).hp, hp)

    def test_a_zero_blow_or_a_missing_attacker_is_a_no_op(self):
        ec.set_boss_upgrade_pair(picked("thorns"), BALANCE)
        self.assertEqual(ec._apply_thorns(self._enemy(), 0), 0)
        self.assertEqual(ec._apply_thorns(None, 100), 0)

    def test_an_attacker_carrying_no_health_is_refused_not_crashed(self):
        class _NoHealth:
            def get_component(self, _cls):
                return None
        ec.set_boss_upgrade_pair(picked("thorns"), BALANCE)
        self.assertEqual(ec._apply_thorns(_NoHealth(), 100), 0)

    def test_clearing_the_pair_disarms_the_hook(self):
        ec.set_boss_upgrade_pair(picked("thorns"), BALANCE)
        ec.set_boss_upgrade_pair()
        self.assertEqual(ec._apply_thorns(self._enemy(), 100), 0)


# ---------------------------------------------------------------------------
# 4. The cutscene — 3 upgrade cards, not 10G's A/B narrative pick
# ---------------------------------------------------------------------------
VIEW_W, VIEW_H = 640, 360


class TestBossCutscenePicker(unittest.TestCase):
    """BU-4/D5 replaced the two ``WinA``/``WinB`` narrative boxes with three
    catalog-sourced upgrade cards; ``hit()`` returns an UPGRADE ID string."""

    def _open(self, boss_num=1, outcome="win", balance=BALANCE, love=0):
        cut = BossCutscene(VIEW_W, VIEW_H, CORE, boss_upgrades_balance=balance)
        cut.open(boss_num, outcome, love)
        return cut

    def _centre(self, cut, i):
        x, y, w, h = cut.boxes[i].rect
        return x + w // 2, y + h // 2

    def test_it_shows_three_boxes_carrying_this_milestones_slots(self):
        cut = self._open(1)
        self.assertEqual(len(cut.boxes), 3)
        self.assertEqual(cut.slots, MILESTONES[0]["slots"])

    def test_a_click_returns_the_picked_upgrade_id(self):
        cut = self._open(1)
        for i, uid in enumerate(MILESTONES[0]["slots"]):
            with self.subTest(slot=i):
                self.assertEqual(cut.hit(*self._centre(cut, i)), uid)

    def test_boss_five_offers_boss_ones_identical_cards(self):
        self.assertEqual(self._open(5).slots, self._open(1).slots)

    def test_an_empty_slot_draws_but_is_neither_hoverable_nor_pickable(self):
        cut = self._open(3)                      # milestone 2, slot 2 is None
        self.assertIsNone(cut.slots[2])
        self.assertIsNone(cut.hit(*self._centre(cut, 2)))
        cut.update(0.0, *self._centre(cut, 2))
        self.assertEqual(cut.hovered, -1)
        self.assertEqual(len(cut.boxes[2].rect), 4)   # geometry still stable

    def test_a_click_off_every_box_picks_nothing(self):
        self.assertIsNone(self._open(1).hit(0, 0))

    def test_a_loss_offers_the_same_three_cards(self):
        self.assertEqual(self._open(1, "loss", love=30).slots,
                         self._open(1, "win").slots)

    def test_card_copy_comes_from_the_catalog_and_formats_its_params(self):
        bal = copy.deepcopy(BALANCE)
        bal["BossUpgrades"]["Catalog"]["thorns"]["description"] = (
            "reflect {reflect_pct}%")
        cut = self._open(2, balance=bal)
        name, desc = cut._card("thorns")
        self.assertEqual(name, "Thorns")
        self.assertEqual(desc, "reflect 10%")

    def test_a_bad_placeholder_falls_back_to_the_raw_text(self):
        bal = copy.deepcopy(BALANCE)
        bal["BossUpgrades"]["Catalog"]["thorns"]["description"] = "{nope}"
        _name, desc = self._open(2, balance=bal)._card("thorns")
        self.assertEqual(desc, "{nope}")

    def test_no_balance_wired_offers_three_empty_unpickable_boxes(self):
        cut = self._open(1, balance=None)
        self.assertEqual(cut.slots, [None, None, None])
        for i in range(3):
            self.assertIsNone(cut.hit(*self._centre(cut, i)))


if __name__ == "__main__":
    unittest.main()
