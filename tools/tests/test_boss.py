"""Phase 10G: Boss — queue composition, era stats, death swarm, pathing guard,
A/B bonuses (story damage + payday slot 3), cutscene flow, XP.

Pure-Python, headless — the ``test_phase_loop.py`` fixture style: a synth
``TileMapDoc`` -> ``TileMap`` board, real balancing via ``load_balance``, and a
deterministic ``random.Random(seed)`` injected into ``Spawner.begin_round`` /
``Session``. All hand-computed expectations come from the fixture's own JSON —
since ES-2 that means the per-era rows (``EnemyTypes.<type>.eras``) and the ONE
era clock (``EnemyScaling.rounds_per_era`` / ``boss_round_in_era``), never a
tier formula."""
import math
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
from game.core import RunState, Session, load_balance, run_payday
from game.core import boss_bonuses as bb
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.combat import _chebyshev, _fp_offset
from game.enemies.components import DeathSpawn, EnemyCombat, PathAgent
from game.enemies.enemy import era_stats
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
INTERVAL = SCALE["rounds_per_era"]   # boss_round_in_era == the era's last


def expected_count(type_key, round_num):
    """Hand-computed per-era count (D3/D3'): floor(count_start + k *
    count_per_round) from the era's first ACTIVE round, 0 before start_round."""
    block = ENEM["EnemyTypes"][type_key]
    rows = block["eras"]
    era = max(0, (round_num - 1) // INTERVAL)
    row = rows[min(era, len(rows) - 1)]
    r0 = max(era * INTERVAL + 1, block["start_round"])
    if round_num < r0:
        return 0
    return math.floor(round(
        row["count_start"] + (round_num - r0) * row["count_per_round"], 9))


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


def boss_footprint(enem, footprint):
    """Set the boss's footprint on a COPY of the balancing doc.

    BR-1: the boss's ``footprint``/``sprite_scale``/``shake`` are PER-ERA —
    they live in its ``stats[]`` rows, not flat at the type root — so a test
    that wants a footprint-N boss writes every row."""
    for row in enem["EnemyTypes"]["Boss"]["stats"]:
        row["footprint"] = footprint
    return enem


def queue_etypes(round_num, tm, seed=1, balance=None):
    sp = Spawner()
    sp.begin_round(round_num, tm, balance if balance is not None else ENEM,
                   rng=random.Random(seed))
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

    def test_round_60_beyond_table_falls_back_to_the_per_type_counts(self):
        r = INTERVAL * 6  # era 5 — one past the 5-row round_counts table.
        # The 10G behaviour, restored in BR-5 (USER DECISION): past the table
        # the COMPANIONS come from the ordinary per-type era-row counts, not
        # from the era-4 table row. BR-4 had swapped that branch — round 60
        # went 295/46/37 -> 700/215/61 — and only that branch was reverted:
        # the BOSS itself still grows through endgame_boss_scaling (see
        # TestBossEndgameScaling).
        _sp, etypes = queue_etypes(r, self.tm)
        n_regular = expected_count("Standard", r)
        n_raiders = expected_count("Raider", r)
        n_siege = expected_count("SiegeCannon", r)
        self.assertEqual(etypes[0], "boss")
        self.assertEqual(etypes.count("boss"), 1)
        self.assertEqual(etypes.count("standard"), n_regular)
        self.assertEqual(etypes.count("raider"), n_raiders)
        self.assertEqual(etypes.count("siege"), n_siege)
        self.assertEqual(etypes[1:1 + n_siege], ["siege"] * n_siege)
        # ... and it is genuinely LIGHTER than the era-4 table row it replaced
        # — the shape of the revert, pinned so a re-swap turns this red.
        self.assertLess(n_regular, BOSS["round_counts"][-1]["regular"])

    def test_commander_count_in_the_round_table_is_composed(self):
        """BR-5 wires `round_counts[era]["commander"]`, authored since BR-1 and
        consumed by nothing until now. Shipped 0 everywhere, so this pins the
        MECHANIC against a written row, never the balance of the day."""
        bal = copy.deepcopy(ENEM)
        bal["EnemyTypes"]["Boss"]["round_counts"][0]["commander"] = 4
        _sp, etypes = queue_etypes(INTERVAL, self.tm, balance=bal)
        self.assertEqual(etypes.count("commander"), 4)
        # LAST in the composition (after standard+raider) so the shipped
        # all-zero table draws no rng and every wave fixture holds.
        _sp2, shipped = queue_etypes(INTERVAL, self.tm)
        self.assertEqual(shipped.count("commander"), 0)

    def test_non_boss_round_composes_as_before_10g(self):
        r = INTERVAL + 1
        _sp, etypes = queue_etypes(r, self.tm)
        self.assertNotIn("boss", etypes)
        self.assertEqual(etypes.count("standard"), expected_count("Standard", r))
        self.assertEqual(etypes.count("raider"), expected_count("Raider", r))
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
        # At the shipped all-1.0 endgame_boss_scaling the stats still clamp;
        # `era` itself is the GLOBAL era since BR-4 (unclamped — resolve_era_row
        # needs the distance past the table to compound the factors).
        b = self._boss(99)
        self.assertEqual(b.get_component(Health).max_hp, BOSS["stats"][-1]["hp"])
        self.assertEqual(b.era, 99)

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

    def test_second_phase_staging_is_per_era(self):
        """BR-5/D5: `at_hp_fraction`/`spawn_hp_fraction`/`delayed_spawns`/
        `spawn_delay` are per-era rows on `second_phase.staging`, resolved by
        the `Enemy.resolve_phase_row` seam. Written fixture, not the balance of
        the day; era 5 proves the array CLAMPS (no endgame factor compounds a
        fraction past 1.0 and fires the phase on spawn)."""
        bal = copy.deepcopy(ENEM)
        staging = bal["EnemyTypes"]["Boss"]["second_phase"]["staging"]
        for era, row in enumerate(staging):
            row["at_hp_fraction"] = 0.1 * era
            row["spawn_hp_fraction"] = 1.0 - 0.1 * era
            row["spawn_delay"] = 0.25 * (era + 1)
        for era in list(range(len(staging))) + [5, 40]:
            with self.subTest(era=era):
                row = staging[min(era, len(staging) - 1)]
                ds = create_enemy("boss", 1, 0, bal, self.tm,
                                  era).get_component(DeathSpawn)
                self.assertAlmostEqual(ds.at_hp_fraction,
                                       row["at_hp_fraction"])
                self.assertAlmostEqual(ds.spawn_hp_fraction,
                                       row["spawn_hp_fraction"])
                self.assertAlmostEqual(ds.spawn_delay, row["spawn_delay"])
                self.assertLessEqual(ds.at_hp_fraction, 1.0)


class TestBossEndgameScaling(unittest.TestCase):
    """BR-4/D1 — past the last authored era every boss array is the last row
    grown by ``endgame_boss_scaling``: ``last * factor ** N`` with
    ``N = era - (len(stats) - 1)``. ``test_era_math`` proves ``f ** N`` on the
    pure resolver; this is the ONE integration pin that the boss's THREE
    era-row lookups (stats and second_phase.spawns) actually thread the factors
    through — the commander count included, since that key is invisible in the
    shipped file (it is 0 everywhere).

    BR-5 removed the THIRD lookup from this list: ``round_counts`` no longer
    feeds a past-the-table boss round at all (the per-type counts do again, a
    user decision), so there is nothing there for the factors to reach. The
    factors themselves stay in the block — the table is still consulted at
    eras 0-4, where a factor is by definition inert."""

    FACTORS = {"hp": 2.0, "dmg": 1.5, "move_speed": 1.1, "regular": 1.2,
               "commander": 3.0}

    def _scaled_balance(self):
        bal = copy.deepcopy(ENEM)
        boss = bal["EnemyTypes"]["Boss"]
        boss["endgame_boss_scaling"] = {
            **{k: 1.0 for k in boss["endgame_boss_scaling"]}, **self.FACTORS}
        # The shipped commander counts are all 0, and 0 * anything is 0.
        boss["second_phase"]["spawns"][-1]["commander"] = 2
        boss["round_counts"][-1]["commander"] = 2
        return bal

    def test_eras_5_6_7_compound_the_factors(self):
        bal = self._scaled_balance()
        boss_cfg = bal["EnemyTypes"]["Boss"]
        last = boss_cfg["stats"][-1]
        last_spawns = boss_cfg["second_phase"]["spawns"][-1]
        last_counts = boss_cfg["round_counts"][-1]
        tm = synth(["bs"])
        sp = Spawner()
        for era in (5, 6, 7):
            n = era - (len(boss_cfg["stats"]) - 1)     # 1, 2, 3
            with self.subTest(era=era, n=n):
                b = create_enemy("boss", 1, 0, bal, tm, era)
                self.assertEqual(b.era, era)           # unclamped since BR-4
                self.assertEqual(b.get_component(Health).max_hp,
                                 math.floor(last["hp"] * 2.0 ** n))
                self.assertEqual(b.get_component(EnemyCombat).dmg,
                                 math.floor(last["dmg"] * 1.5 ** n))
                self.assertAlmostEqual(b.get_component(Movement).speed,
                                       last["move_speed"] * 1.1 ** n)
                # second_phase.spawns — counts floor to whole enemies.
                counts = b.get_component(DeathSpawn).counts
                self.assertEqual(counts["regular"], math.floor(round(
                    last_spawns["regular"] * 1.2 ** n, 9)))
                self.assertEqual(counts["commander"], math.floor(round(
                    last_spawns["commander"] * 3.0 ** n, 9)))
                self.assertEqual(counts["raiders"], last_spawns["raiders"])
                # round_counts is NOT reached past the table since BR-5 — the
                # companions come from the per-type counts again, untouched by
                # this block however hard it is tuned.
                r = (era + 1) * INTERVAL
                sp.begin_round(r, synth(["bbs"]), bal, rng=random.Random(3))
                etypes = [et for _t, et, _d in sp._queue]
                self.assertEqual(etypes.count("standard"),
                                 expected_count("Standard", r))
                self.assertNotEqual(etypes.count("standard"), math.floor(round(
                    last_counts["regular"] * 1.2 ** n, 9)))

    def test_shipped_all_1_factors_are_a_plain_clamp(self):
        # The invariant BR-4 shipped: an all-1.0 block IS the old clamp, on
        # every one of the boss's arrays (int leaves floor back to themselves).
        tm = synth(["bs"])
        last = BOSS["stats"][-1]
        for era in (5, 8, 40):
            with self.subTest(era=era):
                b = create_enemy("boss", 1, 0, ENEM, tm, era)
                self.assertEqual(b.get_component(Health).max_hp, last["hp"])
                self.assertEqual(b.get_component(EnemyCombat).dmg, last["dmg"])
                self.assertEqual(b.get_component(PathAgent).footprint,
                                 last["footprint"])
                self.assertEqual(b.shake, last["shake"])
                self.assertEqual(b.get_component(DeathSpawn).counts,
                                 BOSS["second_phase"]["spawns"][-1])


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
SWARM = {"regular": 3, "raiders": 2, "siege": 1, "commander": 0}


def swarm_balance(counts=SWARM, spawn_hp_fraction=1.0, delayed=False,
                  spawn_delay=0.0, at_hp_fraction=0.0):
    """A copy of the enemies balance whose boss leaves a NON-EMPTY era-0 burst.

    BR-3 renamed the boss's block `death_spawn` -> `second_phase` and gave it
    `delayed_spawns`/`spawn_delay`. This class pins the ONE-FRAME burst, so it
    forces `delayed_spawns` OFF (the shipped data has it ON); the staged phase
    has its own class below.

    BR-5 moved those four keys into per-era `staging` rows, so this writes
    EVERY row: the callers below spawn era-0 bosses, but pinning one row would
    leave a silently different era 1+ for anything that ever moves."""
    enem = copy.deepcopy(ENEM)
    second_phase = enem["EnemyTypes"]["Boss"]["second_phase"]
    second_phase["enabled"] = True
    second_phase["spawns"][0] = dict(counts)
    for row in second_phase["staging"]:
        row["at_hp_fraction"] = at_hp_fraction
        row["spawn_hp_fraction"] = spawn_hp_fraction
        row["delayed_spawns"] = delayed
        row["spawn_delay"] = spawn_delay
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
        # CURRENT era: swarm members carry the round's era row (round 10 is
        # still era 0); the raider's rows are flat, so it never moves.
        era = (INTERVAL - 1) // INTERVAL
        std_hp = era_stats(self.enem["EnemyTypes"]["Standard"], era)[0]
        std = next(e for e in enemies if e.ETYPE == "standard")
        self.assertEqual(std.get_component(Health).max_hp, std_hp)
        raider = next(e for e in enemies if e.ETYPE == "raider")
        self.assertEqual(raider.get_component(Health).max_hp,
                         era_stats(self.enem["EnemyTypes"]["Raider"], era)[0])
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
            enem=swarm_balance({"regular": 0, "raiders": 0, "siege": 0,
                                "commander": 0}))
        boss.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)
        scene.update(0.0)
        self.assertEqual([e for e in scene.by_tag("enemy") if e.alive], [])

    def test_delayed_boss_stages_instead_of_bursting(self):
        """BR-3: the ONE test of the delay -> second-phase machine.

        `delayed_spawns: true` + `at_hp_fraction 0.5`: crossing the threshold
        must NOT kill the boss. It freezes, goes untargetable, trickles exactly
        `sum(counts)` children one per `spawn_delay` at its own tile, holds the
        round open the whole time, then dies exactly once through the normal
        path (kill count + the round ending)."""
        delay = 0.25
        enem = swarm_balance(delayed=True, spawn_delay=delay,
                             at_hp_fraction=0.5)
        # A LONG board, unlike the burst tests' two-tile one: the phase runs
        # over real dt, so children that spawned early would otherwise reach
        # the hole mid-phase and wipe the round out from under the machine.
        tm, scene, occ = build_board(["b" + "." * 40 + "s"])
        session = Session.create(Spawner(), tm, enem, CORE, BUILD,
                                 rng=random.Random(2), occupancy=occ)
        session.state.round_num = INTERVAL
        session.state.phase = GamePhase.ENEMY
        session.spawner.begin_round(INTERVAL, tm, enem, rng=random.Random(2))
        session.spawner.clear()
        boss_col = 41
        boss = create_enemy("boss", boss_col, 0, enem, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        health = boss.get_component(Health)
        health.hp = health.max_hp // 2          # <= 0.5 * max: the crossing

        self.assertTrue(boss.alive)             # NOT dead — the whole point
        self.assertFalse(boss.targetable)       # D2: immune + no HP bar

        frame(session, scene, tm, 0.0)          # the transition frame
        scene.update(0.0)
        self.assertIn(boss, scene.by_tag("enemy"))
        self.assertEqual(boss.get_component(Movement).speed, 0.0)
        self.assertTrue(boss.get_component(PathAgent).frozen)
        self.assertEqual(session.state.enemies_killed, 0)
        # Immune while frozen: a full-power hit changes nothing.
        before = health.hp
        resolve_combat(scene, tm, 0.0, BUILD, VFX)
        self.assertEqual(health.hp, before)

        total = sum(SWARM.values())
        children = 0
        for _ in range(400):                    # 400 * delay/2 >> the phase
            frame(session, scene, tm, delay / 2)
            scene.update(0.0)
            children = len([e for e in scene.by_tag("enemy")
                            if e.alive and e is not boss])
            if boss not in scene.by_tag("enemy"):
                break
            # The round can never end while the boss is mid-phase.
            self.assertEqual(session.state.phase, GamePhase.ENEMY)
            self.assertLessEqual(children, total)
        self.assertEqual(children, total)       # exactly sum(counts), no more
        self.assertNotIn(boss, scene.by_tag("enemy"))
        self.assertEqual(session.state.enemies_killed, 1)   # died ONCE
        for e in scene.by_tag("enemy"):
            self.assertEqual((e._col, e._row), (boss_col, 0))  # the boss's tile

    def test_era_zero_phase_spawns_the_commander(self):
        """The era-0 shipping shape: `commander: 1` on the staged second phase
        must produce exactly ONE real Commander (BR-3's `SWARM_TYPES` entry is
        what makes the count non-inert), at the boss's own tile, at
        `spawn_hp_fraction` of its OWN max HP — and the boss dies once the
        queue drains. Counts are pinned here, not read from live balance."""
        delay = 0.25
        enem = swarm_balance({"regular": 0, "raiders": 0, "siege": 0,
                              "commander": 1},
                             spawn_hp_fraction=0.5, delayed=True,
                             spawn_delay=delay, at_hp_fraction=0.5)
        tm, scene, occ = build_board(["b" + "." * 40 + "s"])
        session = Session.create(Spawner(), tm, enem, CORE, BUILD,
                                 rng=random.Random(2), occupancy=occ)
        session.state.round_num = INTERVAL
        session.state.phase = GamePhase.ENEMY
        session.spawner.begin_round(INTERVAL, tm, enem, rng=random.Random(2))
        session.spawner.clear()
        boss_col = 41
        boss = create_enemy("boss", boss_col, 0, enem, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        health = boss.get_component(Health)
        health.hp = int(health.max_hp * 0.49)   # past the 0.5 crossing

        self.assertTrue(boss.alive)             # staging, not dead
        self.assertFalse(boss.targetable)
        for _ in range(400):
            frame(session, scene, tm, delay / 2)
            scene.update(0.0)
            if boss not in scene.by_tag("enemy"):
                break
        self.assertNotIn(boss, scene.by_tag("enemy"))
        self.assertEqual(session.state.enemies_killed, 1)
        children = [e for e in scene.by_tag("enemy") if e is not boss]
        self.assertEqual(Counter(e.ETYPE for e in children),
                         Counter({"commander": 1}))
        child = children[0]
        self.assertEqual((child._col, child._row), (boss_col, 0))
        ch = child.get_component(Health)
        self.assertEqual(ch.hp, max(1, int(ch.max_hp * 0.5)))

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
BB = CORE["BossBonuses"]


class TestBossBonuses(unittest.TestCase):
    """The reworked six. Magnitudes come from ``core.json``'s ``BossBonuses``,
    so every expectation is ``count * magnitude * stacks`` — never a literal."""

    def _state(self, **stacks):
        st = RunState.from_balance(CORE, BUILD)
        for key, value in stacks.items():
            st.boss_stacks[key] = value
        return st

    # -- 1A/1B/3A/3B: the four story-damage contributors -------------------

    def test_boss1a_pays_per_unbuilt_tile(self):
        tm, _scene, _occ = build_board(["bbbb"])
        st = self._state(boss1a=2)
        n = len(tm.buildable_tiles())
        self.assertGreater(n, 0)
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE),
                         n * BB["dmg_per_unbuilt_tile"] * 2)
        st.boss_stacks["boss1a"] = 0
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE), 0)

    def test_boss1b_pays_per_alive_building(self):
        tm, scene, occ = build_board(["bbbb"])
        place_building(tm, tm.get(1, 0), "defence", 9999, BUILD, scene, occ)
        place_building(tm, tm.get(2, 0), "economic", 9999, BUILD, scene, occ)
        st = self._state(boss1b=3)
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE),
                         2 * BB["dmg_per_building"] * 3)

    def test_boss3a_pays_per_love_chunk_of_the_end_turn_snapshot(self):
        tm, _scene, _occ = build_board(["bbbb"])
        chunk = BB["love_chunk_size"]
        st = self._state(boss3a=2)
        st.boss_love_snapshot = chunk * 3 + 1     # the remainder never pays
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE),
                         3 * BB["dmg_per_love_chunk"] * 2)

    def test_boss3b_pays_per_lightning_building(self):
        tm, scene, occ = build_board(["bbbb"])
        priest, _ = place_building(tm, tm.get(1, 0), "storm_priest", 9999,
                                   BUILD, scene, occ)
        self.assertIn("lightning_source", priest.tags)
        place_building(tm, tm.get(2, 0), "defence", 9999, BUILD, scene, occ)
        st = self._state(boss3b=2)
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE),
                         1 * BB["dmg_per_lightning_building"] * 2)

    # -- 2A/2B: paid through payday slot 3, silently ------------------------

    def test_boss2a_pays_per_level_past_the_threshold_through_payday(self):
        tm, scene, occ = build_board(["bbb"])
        defender, _ = place_building(tm, tm.get(1, 0), "defence", 9999,
                                     BUILD, scene, occ)
        defender.upgrade()
        defender.upgrade()          # in-tier level 3
        levels_past = max(0, 3 - BB["level_past_threshold"])
        st = self._state(boss2a=2)
        story = levels_past * BB["love_per_level_past"] * 2
        self.assertEqual(bb.love_bonus_income(st, tm, CORE), story)
        love0 = st.love
        run_payday(st, tm, CORE)
        self.assertEqual(
            st.love,
            love0 + story + HOLE["base_income"] - defender.upkeep())
        # Slot 3 pays SILENTLY — only base income leaves an income floater.
        self.assertEqual(
            len([e for e in st.income_events if e[3] == "income"]), 1)

    def test_boss2b_pays_per_low_level_building_through_payday(self):
        tm, scene, occ = build_board(["bbbb"])
        low, _ = place_building(tm, tm.get(1, 0), "defence", 9999, BUILD,
                                scene, occ)
        high, _ = place_building(tm, tm.get(2, 0), "defence", 9999, BUILD,
                                 scene, occ)
        for _ in range(BB["low_level_target"]):
            high.upgrade()          # past the target level
        st = self._state(boss2b=2)
        story = BB["love_per_low_level_building"] * 2      # exactly one match
        self.assertEqual(bb.love_bonus_income(st, tm, CORE), story)
        love0 = st.love
        run_payday(st, tm, CORE)
        self.assertEqual(
            st.love,
            love0 + story + HOLE["base_income"]
            - low.upkeep() - high.upkeep())
        self.assertEqual(
            len([e for e in st.income_events if e[3] == "income"]), 1)

    def test_a_dead_building_drops_out_of_every_count(self):
        """The rework's deliberate change from 10G's un-filtered counts: a
        destroyed building stops counting (1B / 2A / 2B / 3B) until revive."""
        tm, scene, occ = build_board(["bbbb"])
        priest, _ = place_building(tm, tm.get(1, 0), "storm_priest", 9999,
                                   BUILD, scene, occ)
        defender, _ = place_building(tm, tm.get(2, 0), "defence", 9999,
                                     BUILD, scene, occ)
        defender.upgrade()
        defender.upgrade()          # in-tier level 3, so 2A has something
        st = self._state(boss1b=1, boss2a=1, boss2b=1, boss3b=1)
        alive_dmg = bb.story_damage_bonus(st, tm, CORE)
        alive_love = bb.love_bonus_income(st, tm, CORE)
        self.assertGreater(alive_dmg, 0)
        self.assertGreater(alive_love, 0)
        priest.get_component(Health).damage(10 ** 9)
        defender.get_component(Health).damage(10 ** 9)
        self.assertFalse(priest.alive or defender.alive)
        self.assertEqual(bb.story_damage_bonus(st, tm, CORE), 0)
        self.assertEqual(bb.love_bonus_income(st, tm, CORE), 0)

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

    def test_stacking_and_set_cycling(self):
        st = RunState.from_balance(CORE, BUILD)
        bb.apply_choice(st, 0, "A")
        bb.apply_choice(st, 0, "A")               # same pick twice = doubled
        self.assertEqual(st.boss_stacks["boss1a"], 2)
        self.assertEqual((4 - 1) % 3, 0)          # boss 4 -> set 0 again
        bb.apply_choice(st, (4 - 1) % 3, "B")
        self.assertEqual(st.boss_stacks["boss1b"], 1)
        # The copy quotes the LIVE magnitude, so it can never advertise a
        # number the math no longer uses.
        desc = bb.choice_desc(2, "A", CORE)
        self.assertEqual(len(desc.split("\n")), 2)
        self.assertIn(str(BB["love_chunk_size"]), desc)
        self.assertIn(str(BB["dmg_per_love_chunk"]), desc)


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

    def _end_turn_past_any_intro(self, session):
        """end_turn(), then drain any enemy-intro entry queued on this round
        (feature-enemy-intro-dialogue) — round 10 (INTERVAL, a boss round)
        carries both a Boss and a Commander entry in the fixture data — so
        the round's real ENEMY phase begins exactly like it did before this
        feature existed."""
        session.end_turn()
        while session.state.phase == GamePhase.ENEMY_INTRO:
            session.resolve_enemy_intro()

    def test_cutscene_beats_levelup_and_chains_through_it(self):
        session, scene, tm = self._session(INTERVAL)
        st = session.state
        st.levelup_pending = True
        self._end_turn_past_any_intro(session)     # boss wave queued
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
        self._end_turn_past_any_intro(session)
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
        self._end_turn_past_any_intro(session)

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
                real = ENEM["EnemyTypes"][key]["eras"][0]["stats"]["move_speed"]
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


class TestBossFootprintTwoDoesNotFreezeBesideANeighbour(unittest.TestCase):
    """The real boss footprint is 2 (``data/balancing/enemies.json``), but
    every other test in this module runs against the fixture's ``footprint:
    1`` — a materially different collision profile. At footprint 1,
    ``PathAgent.target_col``/``target_row`` (the path's terminal ANCHOR) is
    always the building's own tile; at footprint 2 the covering anchor can sit
    a tile away from it, and ``_target_alive`` used to read that anchor tile
    literally, finding no occupant and wrongly concluding the committed target
    was already dead while it stood one tile over. That falsely tripped the
    dead-target repath every frame, short-circuiting ``update`` before it ever
    reached ``_blocker_ahead`` again — the boss froze beside the still-alive
    neighbour, body overlapping its tile, never attacking it."""

    def test_boss_kills_a_neighbour_instead_of_freezing_beside_it(self):
        enem = boss_footprint(copy.deepcopy(ENEM), 2)
        tm, scene, occ = build_board(["b" * 12] * 12)
        b1 = place_defence(tm, scene, occ, 5, 5, hp=50)
        b2 = place_defence(tm, scene, occ, 7, 5, hp=50)
        scene.update(0.0)
        boss = create_enemy("boss", 0, 5, enem, tm, 0)
        scene.spawn(boss)
        scene.update(0.0)
        pa = boss.get_component(PathAgent)
        for _ in range(20000):
            scene.update(0.02)
            if pa.reached_base:
                break
        self.assertFalse(b1.alive)
        self.assertFalse(b2.alive)
        self.assertTrue(pa.reached_base)


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


# ---------------------------------------------------------------------------
# 10. The range GATE reaches a footprint-2 block from any adjacent tile
# ---------------------------------------------------------------------------
class TestChebyshevRangeGateNearestBlockTile(unittest.TestCase):
    """``_chebyshev`` (game/enemies/combat.py) gates a defender's range on the
    NEAREST TILE of the enemy's block, not its centre. A footprint-2 boss
    anchored at (10,10) spans (10,10)..(11,11); a centre-only gate measured
    every tile OUTSIDE that block at Chebyshev >= 1.5, so a range-1 defender
    standing right next to it could never target it — while the boss's own
    block-and-attack scan (``_blocker_ahead``, a block-wide occupancy check)
    hit that same defender fine."""

    def _footprint_2_boss(self, tm):
        enem = boss_footprint(copy.deepcopy(ENEM), 2)
        return create_enemy("boss", 10, 10, enem, tm, 0)

    def test_range_1_defenders_touching_the_block_are_all_in_range(self):
        tm = synth(["b" * 15] * 15)
        boss = self._footprint_2_boss(tm)
        off = _fp_offset(boss)
        for center in ((9, 10), (10, 9), (12, 10), (10, 12)):
            with self.subTest(center=center):
                self.assertLessEqual(_chebyshev(center, boss, off), 1)

    def test_a_defender_one_tile_further_out_stays_out_of_range(self):
        tm = synth(["b" * 15] * 15)
        boss = self._footprint_2_boss(tm)
        off = _fp_offset(boss)
        self.assertGreater(_chebyshev((8, 10), boss, off), 1)

    def test_footprint_1_range_gate_is_byte_identical(self):
        """The ``off == 0`` branch must be untouched: today's behaviour for
        every non-footprint-2 enemy in the game stays exactly as it was."""
        tm = synth(["bs"])
        walker = create_enemy("standard", 10, 10, ENEM, tm)
        off = _fp_offset(walker)
        self.assertEqual(off, 0.0)
        self.assertLessEqual(_chebyshev((9, 10), walker, off), 1)
        self.assertGreater(_chebyshev((12, 10), walker, off), 1)


if __name__ == "__main__":
    unittest.main()
