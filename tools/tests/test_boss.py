"""Phase 10G: Boss — queue composition, era stats, death swarm, pathing guard,
A/B bonuses (payday slot 3 + in-sweep deltas + story damage), cutscene flow, XP.

Pure-Python, headless — the ``test_phase_loop.py`` fixture style: a synth
``TileMapDoc`` -> ``TileMap`` board, real balancing via ``load_balance``, and a
deterministic ``random.Random(seed)`` injected into ``Spawner.begin_round`` /
``Session``. All hand-computed expectations use the REPO's live JSON (NOT the
prototype's numbers — ``EnemyScaling.scale_every_n_levels`` is 9 here vs the
prototype's 10, a pre-existing deliberate drift)."""
import copy
import random
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Movement, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats
from game.core import RunState, Session, load_balance, run_payday
from game.core import boss_bonuses as bb
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.components import EnemyCombat, PathAgent
from game.enemies.enemy import tier_scaled_stats
from game.map.tile_map import TileMap
from game.map.tiles import TileCondition

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
UI = load_balance(FIXTURE_DATA, "ui")
VFX = load_balance(FIXTURE_DATA, "vfx")

BOSS = ENEM["EnemyTypes"]["Boss"]
SCALE = ENEM["EnemyScaling"]
RAIDER = ENEM["EnemyTypes"]["Raider"]
SIEGE = ENEM["EnemyTypes"]["SiegeCannon"]
HOLE = CORE["TheHole"]
PHASE = CORE["PhaseLoop"]
INTERVAL = BOSS["round_interval"]


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


def frame(session, scene, tilemap_, dt, dmg_bonus=0):
    """One host frame with BOTH callbacks + the frozen gate (game/main.py)."""
    session.pre_sim(dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(dt)
        resolve_combat(scene, tilemap_, dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death,
                       dmg_bonus=dmg_bonus)
        session.post_sim(scene)


def queue_etypes(round_num, tm, seed=1):
    sp = Spawner()
    sp.begin_round(round_num, tm, ENEM, rng=random.Random(seed))
    return sp, [et for _t, et, _d in sp._queue]


# ---------------------------------------------------------------------------
# 1. Boss-round queue composition (prototype game.py:831-874)
# ---------------------------------------------------------------------------
class TestBossQueueComposition(unittest.TestCase):
    def setUp(self):
        self.tm = synth(["bbs", "bbs", "bbs"])

    def test_round_10_table_row_0(self):
        _sp, etypes = queue_etypes(INTERVAL, self.tm)
        row = BOSS["round_counts"][0]
        self.assertEqual(len(etypes),
                         1 + row["siege"] + row["regular"] + row["raiders"])
        self.assertEqual(etypes[0], "boss")
        self.assertEqual(etypes.count("siege"), row["siege"])  # zero at r10
        self.assertEqual(Counter(etypes[1:]),
                         Counter({"standard": row["regular"],
                                  "raider": row["raiders"]}))

    def test_round_20_all_siege_lead_no_mix_split(self):
        _sp, etypes = queue_etypes(INTERVAL * 2, self.tm)
        row = BOSS["round_counts"][1]
        self.assertEqual(len(etypes), 1 + row["siege"] + row["regular"]
                         + row["raiders"])
        self.assertEqual(etypes[0], "boss")
        # EVERY siege cannon leads behind the boss — no lead/mix split.
        self.assertEqual(etypes[1:1 + row["siege"]],
                         ["siege"] * row["siege"])
        self.assertEqual(Counter(etypes[1 + row["siege"]:]),
                         Counter({"standard": row["regular"],
                                  "raider": row["raiders"]}))

    def test_round_60_beyond_table_falls_back_to_formulas(self):
        r = INTERVAL * 6  # boss_idx 5 — past the 5-row table
        _sp, etypes = queue_etypes(r, self.tm)
        tier = (r - 1) // SCALE["scale_every_n_levels"]
        n_regular = SCALE["base_enemy_count"] + (r - 1) * (
            SCALE["enemies_per_round"] + tier)
        n_raiders = (RAIDER["base_count"]
                     + (r - RAIDER["start_round"]) * RAIDER["per_round"])
        n_siege = (SIEGE["base_count"]
                   + (r - SIEGE["start_round"]) // SIEGE["rounds_per_cannon"])
        self.assertEqual(etypes[0], "boss")
        self.assertEqual(etypes.count("boss"), 1)
        self.assertEqual(etypes.count("standard"), n_regular)
        self.assertEqual(etypes.count("raider"), n_raiders)
        self.assertEqual(etypes.count("siege"), n_siege)
        self.assertEqual(etypes[1:1 + n_siege], ["siege"] * n_siege)

    def test_non_boss_round_composes_as_before_10g(self):
        r = INTERVAL + 1
        _sp, etypes = queue_etypes(r, self.tm)
        self.assertNotIn("boss", etypes)
        tier = (r - 1) // SCALE["scale_every_n_levels"]
        self.assertEqual(
            etypes.count("standard"),
            SCALE["base_enemy_count"] + (r - 1) * (
                SCALE["enemies_per_round"] + tier))
        self.assertEqual(
            etypes.count("raider"),
            RAIDER["base_count"]
            + (r - RAIDER["start_round"]) * RAIDER["per_round"])
        self.assertEqual(etypes.count("siege"), 0)  # r11 < siege start_round


# ---------------------------------------------------------------------------
# 2. Era stats — verbatim from the table, NO tier scaling, clamped
# ---------------------------------------------------------------------------
class TestBossEraStats(unittest.TestCase):
    def setUp(self):
        self.tm = synth(["bs"])

    def _boss(self, era):
        return create_enemy("boss", 1, 0, ENEM, self.tm, era)

    def test_stats_match_table_verbatim_no_tier_bonus(self):
        for era, st in enumerate(BOSS["stats"]):
            with self.subTest(era=era):
                b = self._boss(era)
                health = b.get_component(Health)
                self.assertEqual(health.max_hp, st["hp"])   # exact — no tiers
                self.assertEqual(health.hp, st["hp"])
                combat = b.get_component(EnemyCombat)
                self.assertEqual(combat.dmg, st["dmg"])
                self.assertAlmostEqual(combat.attack_speed, st["attack_speed"])
                self.assertAlmostEqual(
                    b.get_component(Movement).speed, st["move_speed"])
                self.assertEqual(b.era, era)

    def test_huge_era_clamps_to_last_row(self):
        b = self._boss(99)
        self.assertEqual(b.get_component(Health).max_hp, BOSS["stats"][-1]["hp"])
        self.assertEqual(b.era, len(BOSS["stats"]) - 1)

    def test_spawner_era_selection(self):
        # round 10 -> era 0, round 50 -> era 4, round 60 -> era 4 (clamped).
        for round_num, era in ((INTERVAL, 0), (INTERVAL * 5, 4),
                               (INTERVAL * 6, 4)):
            with self.subTest(round=round_num):
                sp, _etypes = queue_etypes(round_num, synth(["bbs"]))
                scene = Scene()
                sp.update(1000.0, scene)  # pop entry 0 — the boss
                scene.update(0.0)
                boss = next(e for e in scene.by_tag("enemy")
                            if e.ETYPE == "boss")
                self.assertEqual(
                    boss.get_component(Health).max_hp,
                    BOSS["stats"][era]["hp"])


# ---------------------------------------------------------------------------
# 3. Death swarm — one-shot, at the boss tile, CURRENT tier, never on skip
# ---------------------------------------------------------------------------
#: The era-0 swarm this class PINS. The live numbers are designer content and
#: era 0 is legitimately {0, 0, 0} today — a first-era boss is not meant to burst.
#: A test that reads those numbers proves nothing once they are zero (it asserts
#: "no children" and then trips over the first `next(...)`) and re-breaks whenever
#: balance moves. Pin the counts so these tests exercise the ER-3 MECHANIC — the
#: plan, the one-shot guard, the tile, the tier — never the balance of the day.
#: That balance has its own guard: the schema + tools/smoke.py.
SWARM = {"regular": 3, "raiders": 2, "siege": 1}


def swarm_balance(counts=SWARM, spawn_hp_fraction=1.0):
    """A copy of the enemies balance whose boss leaves a NON-EMPTY era-0 burst."""
    enem = copy.deepcopy(ENEM)
    death_spawn = enem["EnemyTypes"]["Boss"]["death_spawn"]
    death_spawn["enabled"] = True
    death_spawn["spawn_hp_fraction"] = spawn_hp_fraction
    death_spawn["spawns"][0] = dict(counts)
    return enem


class TestDeathSwarm(unittest.TestCase):
    def _setup(self, round_num=INTERVAL, enem=None):
        enem = enem if enem is not None else swarm_balance()
        self.enem = enem
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, enem, CORE, BUILD,
                                 rng=random.Random(2), occupancy=occ)
        session.state.round_num = round_num
        session.state.phase = GamePhase.ENEMY
        # Arm the spawner (balance/tilemap/tier) then drop its queue so the
        # only live enemy is the boss we spawn by hand.
        session.spawner.begin_round(round_num, tm, enem,
                                    rng=random.Random(2))
        session.spawner.clear()
        boss = create_enemy("boss", 1, 0, enem, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        return tm, scene, session, boss

    def test_swarm_spawns_once_at_boss_tile_with_current_tier(self):
        tm, scene, session, boss = self._setup()
        boss.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)   # death -> stash -> post_sim flush
        scene.update(0.0)
        enemies = [e for e in scene.by_tag("enemy") if e.alive]
        counts = Counter(e.ETYPE for e in enemies)
        self.assertEqual(counts, Counter({"standard": SWARM["regular"],
                                          "raider": SWARM["raiders"],
                                          "siege": SWARM["siege"]}))
        for e in enemies:
            self.assertEqual((e._col, e._row), (1, 0))  # the boss's tile
        # CURRENT tier: standard swarm members carry the cumulative bonus
        # (round 10 -> tier (10-1)//9 = 1 with repo data); raiders never do.
        tier = (INTERVAL - 1) // SCALE["scale_every_n_levels"]
        std_hp = tier_scaled_stats(
            self.enem["EnemyTypes"]["Standard"], self.enem, tier)[0]
        std = next(e for e in enemies if e.ETYPE == "standard")
        self.assertEqual(std.get_component(Health).max_hp, std_hp)
        raider = next(e for e in enemies if e.ETYPE == "raider")
        self.assertEqual(raider.get_component(Health).max_hp,
                         self.enem["EnemyTypes"]["Raider"]["hp"])
        # One-shot guard: reporting the same boss again spawns nothing.
        n = len(enemies)
        session.on_enemy_death(boss)
        session.post_sim(scene)
        scene.update(0.0)
        self.assertEqual(len([e for e in scene.by_tag("enemy") if e.alive]), n)

    def test_swarm_children_spawn_at_full_hp(self):
        """spawn_hp_fraction 1.0 means the burst never touches Health — every
        child arrives at its own full max HP (ER-3)."""
        tm, scene, session, boss = self._setup(
            enem=swarm_balance(spawn_hp_fraction=1.0))
        boss.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)
        scene.update(0.0)
        children = [e for e in scene.by_tag("enemy") if e.alive]
        self.assertEqual(len(children), sum(SWARM.values()))
        for e in children:
            health = e.get_component(Health)
            self.assertEqual(health.hp, health.max_hp)

    def test_an_all_zero_swarm_row_spawns_nothing(self):
        """The live era-0 shape: an ENABLED death_spawn whose counts are all zero
        leaves no children. Balance says "this boss doesn't burst" and the code
        honours it — the case that used to masquerade as a passing assertion."""
        tm, scene, session, boss = self._setup(
            enem=swarm_balance({"regular": 0, "raiders": 0, "siege": 0}))
        boss.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)
        scene.update(0.0)
        self.assertEqual([e for e in scene.by_tag("enemy") if e.alive], [])

    def test_quick_skip_despawns_boss_without_swarm(self):
        tm, scene, session, _boss = self._setup()
        session.quick_skip_combat(scene)
        scene.update(0.0)
        self.assertEqual(scene.by_tag("enemy"), [])   # no swarm
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)


# ---------------------------------------------------------------------------
# 4. Boss pathing — hunts buildings, no phantom base hit, base still breaches
# ---------------------------------------------------------------------------
class TestBossPathing(unittest.TestCase):
    def test_dead_goal_repaths_instead_of_phantom_breach(self):
        tm, scene, occ = build_board(["bbbs"])
        defender, _ = place_building(tm, tm.get(2, 0), "defence", 9999,
                                     BUILD, scene, occ)
        boss = create_enemy("boss", 3, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertFalse(pa.goal_is_base)      # goal = the defender's tile
        self.assertTrue(pa.repath_on_kill)
        # The goal building dies while the boss is en route.
        defender.get_component(Health).damage(10 ** 9)
        for _ in range(500):
            scene.update(0.05)
            if pa.reached_base:
                break
        self.assertTrue(pa.reached_base)
        # The breach fired at the BASE tile, not at the dead defender's tile
        # (the 10F phantom-base-hit hazard).
        wx, wy = boss.transform.world_pos
        self.assertAlmostEqual(wx, float(tm.base_col), delta=0.25)
        self.assertAlmostEqual(wy, float(tm.base_row), delta=0.25)
        self.assertTrue(pa.goal_is_base)       # re-derived by the repath

    def test_base_only_goal_still_breaches(self):
        tm, scene, occ = build_board(["bs"])
        boss = create_enemy("boss", 1, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertTrue(pa.goal_is_base)
        for _ in range(300):
            scene.update(0.05)
            if pa.reached_base:
                break
        self.assertTrue(pa.reached_base)


# ---------------------------------------------------------------------------
# 5. Bonus payout math — pure helpers, dmg_bonus threading, payday slot 3
# ---------------------------------------------------------------------------
class TestBossBonuses(unittest.TestCase):
    def test_story_damage_bonus(self):
        tm, _scene, _occ = build_board(["bbbb"])
        st = RunState.from_balance(CORE, BUILD)
        st.boss_stacks["boss1a"] = 2
        st.boss_stacks["boss3a"] = 1
        st.boss_love_snapshot = 57
        n = len(tm.buildable_tiles())
        self.assertGreater(n, 0)
        self.assertEqual(bb.story_damage_bonus(st, tm), n * 2 + 5)
        st.boss_stacks["boss1a"] = 0
        st.boss_stacks["boss3a"] = 0
        self.assertEqual(bb.story_damage_bonus(st, tm), 0)

    def _projectile_delta(self, dmg_bonus):
        tm, scene, occ = build_board(["bbs"])
        defender, _ = place_building(tm, tm.get(1, 0), "defence", 9999,
                                     BUILD, scene, occ)
        enemy = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(enemy)
        scene.update(0.0)
        health = enemy.get_component(Health)
        health.max_hp = 10 ** 6
        health.hp = 10 ** 6
        resolve_combat(scene, tm, 0.0, BUILD, VFX, dmg_bonus=dmg_bonus)  # fires
        for _ in range(60):                    # let the shot travel + impact
            scene.update(0.05)
            if health.hp < 10 ** 6:
                break
        return defender, 10 ** 6 - health.hp

    def test_resolve_combat_dmg_bonus_adds_flat_damage(self):
        defender, base_delta = self._projectile_delta(0)
        self.assertEqual(base_delta, defender.damage())
        defender, boosted = self._projectile_delta(7)
        self.assertEqual(boosted, defender.damage() + 7)

    def test_payday_slot3_boss1b_pays_per_level_past_2(self):
        tm, scene, occ = build_board(["bbb"])
        defender, _ = place_building(tm, tm.get(1, 0), "defence", 9999,
                                     BUILD, scene, occ)
        defender.upgrade()
        defender.upgrade()                       # in-tier level 3 -> +1/stack
        st = RunState.from_balance(CORE, BUILD)
        st.boss_stacks["boss1b"] = 1
        love0 = st.love
        expected = (bb.boss1b_income(st, tm)
                    + CORE["TheHole"]["base_income"] - defender.upkeep())
        self.assertEqual(bb.boss1b_income(st, tm), 1)
        run_payday(st, tm, CORE)
        self.assertEqual(st.love, love0 + expected)
        # Slot 3 pays silently: no floater event beyond base income + upkeep.
        self.assertEqual(len([e for e in st.income_events
                              if e[3] == "income"]), 1)

    def test_payday_slot3_boss3b_reads_the_snapshot_just_rolled(self):
        tm, scene, occ = build_board(["bbb"])
        defender, _ = place_building(tm, tm.get(1, 0), "defence", 9999,
                                     BUILD, scene, occ)
        defender.get_component(RoundStats).dmg_dealt_this_round = 37
        st = RunState.from_balance(CORE, BUILD)
        st.boss_stacks["boss3b"] = 2
        love0 = st.love
        net = HOLE["base_income"] - defender.upkeep() + (37 // 10) * 2
        run_payday(st, tm, CORE)
        # Proves slot 3 ran AFTER the snapshot roll (this->last) — it read 37.
        self.assertEqual(
            defender.get_component(RoundStats).dmg_dealt_last_round, 37)
        self.assertEqual(st.love, love0 + net)

    def test_boss2a_musician_delta_counts_dead_defence_too(self):
        tm, scene, occ = build_board(["bbbb"])
        musician, _ = place_building(tm, tm.get(1, 0), "economic", 9999,
                                     BUILD, scene, occ)
        defender, _ = place_building(tm, tm.get(2, 0), "defence", 9999,
                                     BUILD, scene, occ)
        defender.get_component(Health).hp = 0     # dead — STILL counts
        st = RunState.from_balance(CORE, BUILD)
        st.boss_stacks["boss2a"] = 1
        base_yield = musician.yield_amount()
        run_payday(st, tm, CORE)
        amounts = {(c, r): a for c, r, a, k in st.income_events
                   if k == "income"}
        self.assertEqual(amounts[(1, 0)], base_yield + 1)  # folded into amount

    def test_boss2b_meditator_delta_via_aoe_count(self):
        tm, scene, occ = build_board(["bbbb"])
        meditator, _ = place_building(tm, tm.get(1, 0), "meditator", 9999,
                                      BUILD, scene, occ)
        place_building(tm, tm.get(2, 0), "aoe_defence", 9999, BUILD, scene,
                       occ)
        self.assertEqual(bb.aoe_count(tm), 1)
        self.assertEqual(bb.defence_count(tm), 0)  # aoe is NOT "defence"
        st = RunState.from_balance(CORE, BUILD)
        st.boss_stacks["boss2b"] = 1
        base_payout = meditator.yield_amount()     # pure (streak 0)
        run_payday(st, tm, CORE)
        amounts = {(c, r): a for c, r, a, k in st.income_events
                   if k == "income"}
        self.assertEqual(amounts[(1, 0)], base_payout + 1)

    def test_stacking_and_set_cycling(self):
        st = RunState.from_balance(CORE, BUILD)
        bb.apply_choice(st, 0, "A")
        bb.apply_choice(st, 0, "A")               # same pick twice = doubled
        self.assertEqual(st.boss_stacks["boss1a"], 2)
        self.assertEqual((4 - 1) % 3, 0)          # boss 4 -> set 0
        bb.apply_choice(st, (4 - 1) % 3, "B")
        self.assertEqual(st.boss_stacks["boss1b"], 1)
        self.assertEqual(bb.choice_desc(2, "A"),
                         "Per 10 love held, defence\nbuildings deal +1 damage")


# ---------------------------------------------------------------------------
# 6. Cutscene phase flow — priority over LEVELUP, chain, payday exactly once
# ---------------------------------------------------------------------------
class TestBossCutsceneFlow(unittest.TestCase):
    def _session(self, round_num):
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD,
                                 rng=random.Random(3), occupancy=occ)
        session.state.round_num = round_num
        return session, scene, tm

    def _ride_to_cutscene(self, session, scene, tm):
        for _ in range(10):
            frame(session, scene, tm, 0.2)
            if session.state.phase not in (GamePhase.ROUND_END,):
                break
        return session.state.phase

    def test_cutscene_beats_levelup_and_chains_through_it(self):
        session, scene, tm = self._session(INTERVAL)
        st = session.state
        st.levelup_pending = True
        session.end_turn()                        # boss wave queued
        self.assertEqual(st.phase, GamePhase.ENEMY)
        self.assertEqual(st.boss_events, [INTERVAL])   # announce marker
        self.assertEqual(st.boss_love_snapshot, st.love)
        self.assertEqual(st.boss_lives_snapshot, st.base_lives)
        session.quick_skip_combat(scene)          # wave over -> ROUND_END
        self.assertEqual(st.pending_boss_cutscene,
                         {"boss_num": 1, "outcome": "win"})
        phase = self._ride_to_cutscene(session, scene, tm)
        self.assertEqual(phase, GamePhase.BOSS_CUTSCENE)  # NOT LEVELUP
        self.assertTrue(session.frozen)
        round_before = st.round_num
        session.resolve_boss_cutscene("A", scene)
        self.assertEqual(st.boss_stacks["boss1a"], 1)
        self.assertEqual(st.boss_choices, [(1, "A", "win")])
        self.assertIsNone(st.pending_boss_cutscene)
        # levelup was pending -> the chain lands in LEVELUP, payday DEFERRED.
        self.assertEqual(st.phase, GamePhase.LEVELUP)
        self.assertEqual(st.round_num, round_before)      # payday not yet run
        session.resolve_levelup(st.levelup_options[0], scene)
        self.assertEqual(st.phase, GamePhase.INCOME)
        self.assertEqual(st.round_num, round_before + 1)  # payday exactly once

    def test_cutscene_straight_to_payday_without_levelup(self):
        session, scene, tm = self._session(INTERVAL)
        st = session.state
        session.end_turn()
        session.quick_skip_combat(scene)
        self._ride_to_cutscene(session, scene, tm)
        self.assertEqual(st.phase, GamePhase.BOSS_CUTSCENE)
        round_before = st.round_num
        session.resolve_boss_cutscene("B", scene)
        self.assertEqual(st.phase, GamePhase.INCOME)      # payday ran
        self.assertEqual(st.round_num, round_before + 1)
        self.assertEqual(st.boss_stacks["boss1b"], 1)

    def test_outcome_is_loss_when_a_life_was_lost(self):
        session, scene, tm = self._session(INTERVAL)
        st = session.state
        session.end_turn()

        class _Dummy:
            ETYPE = "standard"
            dmg = 5
        session.on_base_hit(_Dummy())             # lose a life -> wipe pends
        session.post_sim(scene)                   # wipe -> ROUND_END
        self.assertEqual(st.pending_boss_cutscene["outcome"], "loss")

    def test_no_cutscene_on_a_non_boss_round(self):
        session, scene, tm = self._session(INTERVAL + 1)
        st = session.state
        session.end_turn()
        self.assertEqual(st.boss_events, [])      # no announce marker either
        session.quick_skip_combat(scene)
        self.assertIsNone(st.pending_boss_cutscene)
        for _ in range(20):
            frame(session, scene, tm, 0.2)
            if st.phase == GamePhase.BUILDING:
                break
        self.assertNotIn(st.phase,
                         (GamePhase.BOSS_CUTSCENE, GamePhase.LEVELUP))


# ---------------------------------------------------------------------------
# 7. XP — the boss kill pays core.XP.xp_per_boss through on_enemy_death
# ---------------------------------------------------------------------------
class TestBossXP(unittest.TestCase):
    def test_boss_kill_pays_xp_per_boss(self):
        tm, scene, occ = build_board(["bs"])
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD)
        boss = create_enemy("boss", 1, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        xp0 = session.state.player_xp
        session.on_enemy_death(boss)
        self.assertEqual(session.state.player_xp - xp0,
                         CORE["XP"]["xp_per_boss"])


# ---------------------------------------------------------------------------
# 8. BP-1 — the terrain speed floor. The boss can cross forest/mountain.
# ---------------------------------------------------------------------------
class TestConditionSpeedFloor(unittest.TestCase):
    """``TileConditions.min_speed_fraction`` floors a terrain-penalised speed at
    a fraction of the unit's OWN base speed.

    The old ``max(0, real − enemy_speed_penalty)`` was not a slowdown but a
    LATCH: the penalty is a flat 0.4 t/s and the boss moves at 0.3–0.45, so
    eras 0–3 computed exactly 0.0 — and a unit at speed 0 never advances
    ``Movement.index``, which is the only thing that refreshes
    ``_current_condition``, so the speed stayed 0 forever."""

    PEN = MAPBAL["TileConditions"]["modifiers"]["Forest"]["enemy_speed_penalty"]
    FRAC = MAPBAL["TileConditions"]["min_speed_fraction"]

    def _speed_on(self, enemy, condition):
        pa = enemy.get_component(PathAgent)
        pa._current_condition = condition
        return pa._condition_speed()

    def test_every_boss_era_moves_on_forest(self):
        """Eras 0–3 are the ones the old clamp welded to a dead 0.0 (era 3 by
        the hair of 0.4 − 0.4); era 4 merely crawled at 0.05. The floor lifts
        all five to a fraction of their own speed — it is the LARGER term for
        every era, so the boss is the one type the floor governs outright."""
        tm = synth(["bs"])
        for era, st in enumerate(BOSS["stats"]):
            with self.subTest(era=era):
                real = st["move_speed"]
                self.assertLessEqual(real - self.PEN,
                                     0.0 if era <= 3 else 0.05)
                speed = self._speed_on(create_enemy("boss", 1, 0, ENEM, tm,
                                                    era), TileCondition.FOREST)
                self.assertGreater(speed, 0.0)
                self.assertAlmostEqual(speed, real * self.FRAC)
                self.assertGreater(real * self.FRAC, real - self.PEN)

    def test_the_four_normal_types_are_byte_identical(self):
        """D1's fence: the floor must move ONLY the boss. Each normal type is
        FASTER than its own floor even after the penalty, so ``real − penalty``
        still wins and the number does not budge. If this goes red the floor has
        leaked into the rest of the roster — that is a bug, not a rebalance."""
        tm = synth(["bs"])
        for etype, key, expect in (("standard", "Standard", 0.8),
                                   ("raider", "Raider", 2.3),
                                   ("siege", "SiegeCannon", 0.6),
                                   ("formation", "Formation", 0.5)):
            with self.subTest(etype=etype):
                real = ENEM["EnemyTypes"][key]["move_speed"]
                speed = self._speed_on(create_enemy(etype, 1, 0, ENEM, tm),
                                       TileCondition.FOREST)
                self.assertAlmostEqual(speed, real - self.PEN)
                self.assertAlmostEqual(speed, expect)   # hand-computed

    def test_grass_is_still_the_unpenalised_speed(self):
        tm = synth(["bs"])
        boss = create_enemy("boss", 1, 0, ENEM, tm, 0)
        self.assertAlmostEqual(self._speed_on(boss, TileCondition.GRASS),
                               BOSS["stats"][0]["move_speed"])

    def test_boss_crosses_a_forest_lane_instead_of_welding_to_it(self):
        """The end-to-end repro: an era-0 boss (0.3 t/s) spawned behind three
        forest tiles used to freeze on the first one. Now it walks through."""
        tm, scene, _occ = build_board(["bcccs"])
        for col in (1, 2, 3):
            tm.get(col, 0).condition = TileCondition.FOREST
        boss = create_enemy("boss", 4, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        for _ in range(4000):            # 0.15 t/s over 4 tiles ≈ 27 s
            scene.update(0.05)
            if pa.reached_base:
                break
        self.assertTrue(pa.reached_base)
        self.assertEqual(pa._current_condition, TileCondition.FOREST)


# ---------------------------------------------------------------------------
# 9. BP-2/BP-3/BP-4 — the boss grinds through the buildings, hole LAST.
# ---------------------------------------------------------------------------
def place_defence(tm, scene, occ, col, row, hp=None):
    b, _ = place_building(tm, tm.get(col, row), "defence", 10 ** 9, BUILD,
                          scene, occ)
    if hp is not None:
        health = b.get_component(Health)
        health.max_hp, health.hp = hp, hp
    return b


class TestBossHuntsBuildingsBaseLast(unittest.TestCase):
    """D2: the base leaves the boss's goal set until no other building is alive.

    Before BP-2 the goal predicate was ``lambda b: True`` — the base was IN the
    goal set — and ``content_weights.base_building`` is 0, cheaper than any real
    building (1–2). So the weighted search walked the boss past its prey and
    parked it on the hole."""

    def test_the_base_is_not_the_goal_while_a_building_stands(self):
        tm, scene, occ = build_board(["bbbbs"])
        # The base is at (0,0) and the boss at (2,0) is strictly NEARER to it
        # than to the defender at (4,0)... but a building is alive, so the
        # boss must turn its back on the hole and hunt.
        place_defence(tm, scene, occ, 3, 0)
        boss = create_enemy("boss", 2, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertFalse(pa.goal_is_base)
        self.assertEqual((pa.target_col, pa.target_row), (3, 0))
        self.assertEqual(boss.get_component(Movement).waypoints[-1], [3.0, 0.0])

    def test_the_base_becomes_the_goal_once_the_board_is_clear(self):
        tm, scene, occ = build_board(["bbs"])
        boss = create_enemy("boss", 2, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertTrue(pa.goal_is_base)               # nothing else alive
        self.assertEqual((pa.target_col, pa.target_row), (-1, -1))

    def test_it_destroys_every_building_before_it_touches_the_hole(self):
        """The plan's headline gate. The pre-fix run destroyed 2 of 8."""
        tm, scene, occ = build_board(["bbbbbbbbbccss"] * 7)
        spots = [(2, 1), (3, 4), (5, 2), (6, 5), (1, 3), (7, 1), (4, 6), (8, 3)]
        built = [place_defence(tm, scene, occ, c, r, hp=60) for c, r in spots]
        scene.update(0.0)
        boss = create_enemy("boss", 12, 6, ENEM, tm, 4)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        for _ in range(100000):
            scene.update(0.02)
            if pa.reached_base:
                break
        self.assertTrue(pa.reached_base)
        self.assertEqual([b for b in built if b.alive], [])   # all eight
        self.assertTrue(pa.goal_is_base)


class TestBossCommittedTarget(unittest.TestCase):
    """BP-3: remember the victim; notice it dying; choose it by DISTANCE."""

    def test_a_target_killed_by_someone_else_repaths_immediately(self):
        """Boss rounds are crowded, so 'a defender shot my target while I was
        walking to it' is the common case, not an edge one. The boss used to
        march on to the corpse and only re-path on arrival."""
        tm, scene, occ = build_board(["bbbbbbbbs"])
        near = place_defence(tm, scene, occ, 7, 0)
        far = place_defence(tm, scene, occ, 2, 0)
        boss = create_enemy("boss", 8, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertEqual((pa.target_col, pa.target_row), (7, 0))   # the near one
        # Something else kills it while the boss is still en route.
        near.get_component(Health).damage(10 ** 9)
        self.assertFalse(near.alive)
        scene.update(0.05)                     # ONE frame — no arrival needed
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))   # re-committed
        self.assertFalse(pa.goal_is_base)
        self.assertEqual(boss.get_component(Movement).waypoints[-1], [2.0, 0.0])
        self.assertTrue(far.alive)

    def test_the_route_still_walks_around_a_pond(self):
        """D3's second half: the ROUTE stays a weighted Dijkstra. A pond costs
        +9, so the boss goes the long way round rather than wading, even though
        the water is the straight line to its target."""
        tm, scene, occ = build_board(["bbbbb", "bbbbb", "bbbbb"])
        place_defence(tm, scene, occ, 2, 1)
        tm.get(3, 1).condition = TileCondition.POND    # dead ahead
        boss = create_enemy("boss", 4, 1, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        path = [tuple(w) for w in boss.get_component(Movement).waypoints]
        self.assertEqual(path[-1], (2.0, 1.0))         # same target
        self.assertNotIn((3.0, 1.0), path)             # but not through water

    def test_the_target_is_the_nearest_by_DISTANCE_even_when_it_costs_more(self):
        """D3's first half, and the whole reason the two jobs were split.

        The near building is ringed by pond, so REACHING it costs 12 while the
        building four tiles further away costs only 10 — a weighted search (what
        the boss used to choose with) picks the far one. The player, looking at
        the screen, expects the boss to go for the one right next to it. Choice
        is geometric; only the route is weighted."""
        tm, scene, occ = build_board(["bbbbbbb"] * 5)
        near = place_defence(tm, scene, occ, 4, 2)     # 2 tiles away, cost 12
        far = place_defence(tm, scene, occ, 1, 2)      # 5 tiles away, cost 10
        for c, r in ((5, 2), (3, 2), (4, 1), (4, 3)):  # moat around the near one
            tm.get(c, r).condition = TileCondition.POND
        boss = create_enemy("boss", 6, 2, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertEqual((pa.target_col, pa.target_row), (4, 2))
        self.assertTrue(near.alive and far.alive)
        # Prove the premise: a cost-ranked search really would have gone far.
        from game.map.pathfinder import _dijkstra, _pre_query_refresh
        _pre_query_refresh(tm)
        cost = {}
        for label, goal in (("near", (4, 2)), ("far", (1, 2))):
            p = _dijkstra(tm, 6, 2, {goal}, ignore_walls=False)
            cost[label] = sum(tm.weight(tm.get(c, r)) for c, r in p[1:])
        self.assertGreater(cost["near"], cost["far"])

    def test_a_cleared_target_stops_the_repath_loop(self):
        """A sealed board (no path anywhere) must leave the agent standing with
        NO target — otherwise the dead-target watch re-paths every single frame
        forever."""
        tm, scene, occ = build_board(["bbs"])
        boss = create_enemy("boss", 2, 0, ENEM, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        self.assertEqual((pa.target_col, pa.target_row), (-1, -1))
        self.assertTrue(pa._target_alive(tm))   # "no target" reads as alive


class TestBossDoesNotRewind(unittest.TestCase):
    """BP-4: ``_repath`` used to snap to ``round(wx)`` and reset ``index = 0``,
    walking the boss BACKWARD onto its own tile centre after every kill
    (measured: col 11.000 -> 10.705 in the second after a kill)."""

    def test_position_is_monotonic_along_the_new_path_after_a_kill(self):
        tm, scene, occ = build_board(["bbbbbbbbs"])
        near = place_defence(tm, scene, occ, 6, 0, hp=40)
        place_defence(tm, scene, occ, 2, 0)
        boss = create_enemy("boss", 8, 0, ENEM, tm, 4)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        # Walk until the boss is mid-tile (not on a centre), then kill its
        # target out from under it — the exact rewind trigger.
        while abs(boss.transform.wx - round(boss.transform.wx)) < 0.25:
            scene.update(0.02)
        near.get_component(Health).damage(10 ** 9)
        scene.update(0.02)                       # the re-path frame
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        # The new goal is to the LEFT (col 2), so a correct boss only ever
        # decreases its column. Any increase is the rewind.
        prev = boss.transform.wx
        for _ in range(3000):                    # 0.45 t/s over ~5 tiles ≈ 11 s
            scene.update(0.02)
            self.assertLessEqual(boss.transform.wx, prev + 1e-9,
                                 "the boss reversed after re-pathing")
            prev = boss.transform.wx
            if pa.blocked:
                break
        self.assertTrue(pa.blocked)              # arrived, punching the far one


if __name__ == "__main__":
    unittest.main()
