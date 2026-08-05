"""Phase 9E: enemy walker + wave spawner + combat (game/enemies).

Pure-Python, headless (no SDL) — mirrors the 9C/9D map/building tests: a synth
``TileMapDoc`` -> ``TileMap`` fixture and real balancing via ``load_balance``.
The ledger tests step a ``Scene`` at fixed dt and pin HP against the prototype's
migrated values (×10 scale).
"""
import copy
import math
import os
import random
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")   # the ER-4 art-size test
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.assets import load_registry
from engine.core import Health, Movement, Scene, SpriteAnimator
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats
from game.core import Session
from game.core.balance import load_balance
from game.core.phases import GamePhase, GameState
import game.enemies.spawner as spawner_mod
from game.enemies import (
    Boss, Commander, Enemy, Formation, Projectile, Raider, SiegeCannon,
    Spawner, attack_interval, create_enemy, resolve_combat,
)
from game.enemies.combat import ProjectileHoming
from game.enemies.components import EnemyCombat, PathAgent
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

STD = ENEM["EnemyTypes"]["Standard"]
SCALE = ENEM["EnemyScaling"]
RPE = SCALE["rounds_per_era"]        # ES-2: THE clock (era == the old tier)


def era_stats(type_key, era=0):
    """A type's stats for `era`, straight off its own era rows (ES-2).

    Rows clamp to the last authored one, exactly as `engine.era_math` does —
    written out here so the expectations stay hand-computable from `data/`."""
    rows = ENEM["EnemyTypes"][type_key]["eras"]
    return rows[min(max(era, 0), len(rows) - 1)]["stats"]


def expected_count(type_key, round_num):
    """How many of `type_key` round `round_num` must contain, hand-computed
    from the era rows: `floor(count_start + k * count_per_round)` counted from
    the era's first ACTIVE round `max(era first round, start_round)` (D3/D3'),
    and 0 before `start_round`."""
    block = ENEM["EnemyTypes"][type_key]
    rows = block["eras"]
    era = max(0, (round_num - 1) // RPE)
    row = rows[min(era, len(rows) - 1)]
    r0 = max(era * RPE + 1, block["start_round"])
    if round_num < r0:
        return 0
    return math.floor(round(
        row["count_start"] + (round_num - r0) * row["count_per_round"], 9))


STD0 = era_stats("Standard")


def footprint_balance(etype, footprint):
    """A copy of the enemies balance with ONE type's `footprint` pinned.

    `footprint` is designer content (ER-1) and every type sits at 1 today. A test
    that reads it live to prove multi-tile behaviour degrades into a tautology the
    moment a designer flattens it — "a 1x1 cannot fit through a 1x1 gap" is not the
    claim these tests make. Pin the number so they keep testing the WIRING
    (balance -> PathAgent.footprint -> pathfinder / sprite fit); the live value has
    its own guard in the schema."""
    enem = copy.deepcopy(ENEM)
    enem["EnemyTypes"][etype]["footprint"] = footprint
    return enem


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


class FakeRng:
    """Deterministic rng stand-in: ``choice`` -> first, ``shuffle`` -> identity,
    ``uniform`` -> a fixed value (default 1.0 so ramp delays equal the ramp)."""

    def __init__(self, uniform_val=1.0):
        self.uniform_val = uniform_val

    def choice(self, seq):
        return seq[0]

    def shuffle(self, seq):
        pass

    def uniform(self, a, b):
        return self.uniform_val


# ---------------------------------------------------------------------------
# Per-era stats resolved at spawn (ES-2: the type's own `eras` rows, clamped)
# ---------------------------------------------------------------------------
class TestScaling(unittest.TestCase):
    def test_stats_come_from_the_era_row(self):
        tm = synth(["bbs"])
        for era in range(0, 6):
            with self.subTest(era=era):
                e = Enemy(2, 0, ENEM, tm, era)
                st = era_stats("Standard", era)     # clamps past the last row
                self.assertEqual(e.get_component(Health).max_hp, st["hp"])
                self.assertEqual(e.get_component(Health).hp, st["hp"])
                self.assertEqual(e.dmg, st["dmg"])
                self.assertAlmostEqual(e.get_component(Movement).speed,
                                       st["move_speed"])
                self.assertEqual(
                    e.get_component(EnemyCombat).attack_speed,
                    st["attack_speed"])

    def test_era0_is_the_first_row(self):
        tm = synth(["bbs"])
        e = Enemy(2, 0, ENEM, tm, 0)
        self.assertEqual(e.get_component(Health).hp, STD0["hp"])
        self.assertEqual(e.dmg, STD0["dmg"])

    def test_subclasses_read_own_subtree(self):
        tm = synth(["bbs"])
        r = Raider(2, 0, ENEM, tm)
        self.assertEqual(r.get_component(Health).hp, era_stats("Raider")["hp"])
        s = SiegeCannon(2, 0, ENEM, tm)
        self.assertEqual(s.get_component(Health).hp,
                         era_stats("SiegeCannon")["hp"])

    def test_siege_reads_its_own_era_rows(self):
        tm = synth(["bbs"])
        for era in range(0, 6):
            with self.subTest(era=era):
                st = era_stats("SiegeCannon", era)
                s = SiegeCannon(2, 0, ENEM, tm, era)
                self.assertEqual(s.get_component(Health).hp, st["hp"])
                self.assertEqual(s.dmg, st["dmg"])
                self.assertAlmostEqual(s.get_component(Movement).speed,
                                       st["move_speed"])

    def test_raider_era_rows_are_flat(self):
        # The Raider's "it never scales" is DATA now (five identical rows), not
        # a code exception — so every era resolves to the same numbers.
        tm = synth(["bbs"])
        first = era_stats("Raider", 0)
        for era in (0, 1, 3, 9):
            with self.subTest(era=era):
                self.assertEqual(era_stats("Raider", min(era, 4)), first)
                r = Raider(2, 0, ENEM, tm, era)
                self.assertEqual(r.get_component(Health).hp, first["hp"])
                self.assertEqual(r.dmg, first["dmg"])
                self.assertAlmostEqual(r.get_component(Movement).speed,
                                       first["move_speed"])


class TestEndgameScaling(unittest.TestCase):
    """ES-4/D5 — past the last authored era the row clamps AND the type's own
    ``endgame_scaling`` factors compound: ``last * factor ** N`` with
    ``N = era - (len(eras) - 1)``. `test_era_math` proves `f**N` on the pure
    resolver; this is the ONE integration pin that the game's two era-row
    lookups (stat resolution + count) actually thread the factors through."""

    FACTORS = {"hp": 2.0, "dmg": 1.5, "move_speed": 1.1, "count": 2.0}

    def _scaled_balance(self):
        bal = copy.deepcopy(ENEM)
        bal["EnemyTypes"]["Standard"]["endgame_scaling"] = dict(self.FACTORS)
        return bal

    def test_eras_5_6_7_compound_the_factors(self):
        bal = self._scaled_balance()
        tm = synth(["bbs"])
        rpe = bal["EnemyScaling"]["rounds_per_era"]
        rows = bal["EnemyTypes"]["Standard"]["eras"]
        last, spawner = rows[-1], Spawner()
        for era in (5, 6, 7):
            n = era - (len(rows) - 1)          # 1, 2, 3
            with self.subTest(era=era, n=n):
                e = Enemy(2, 0, bal, tm, era)
                self.assertEqual(e.get_component(Health).max_hp,
                                 math.floor(last["stats"]["hp"] * 2.0 ** n))
                self.assertEqual(e.dmg,
                                 math.floor(last["stats"]["dmg"] * 1.5 ** n))
                self.assertAlmostEqual(e.get_component(Movement).speed,
                                       last["stats"]["move_speed"] * 1.1 ** n)
                # Counts at the era's FIRST round: zero in-era steps, so the
                # expectation is exactly the scaled anchor, floored to an int.
                first_round = era * rpe + 1
                self.assertEqual(
                    spawner._count_of(bal, "Standard", first_round),
                    math.floor(last["count_start"] * 2.0 ** n))

    def test_shipped_all_1_factors_are_a_plain_clamp(self):
        # The invariant: with the shipped all-1.0 file a past-the-end wave is
        # byte-identical to the pre-ES-4 raw clamp.
        tm, spawner = synth(["bbs"]), Spawner()
        rows = ENEM["EnemyTypes"]["Standard"]["eras"]
        for era in (5, 6, 7):
            with self.subTest(era=era):
                e = Enemy(2, 0, ENEM, tm, era)
                self.assertEqual(e.get_component(Health).max_hp,
                                 rows[-1]["stats"]["hp"])
                self.assertEqual(spawner._count_of(ENEM, "Standard", 60),
                                 expected_count("Standard", 60))


# ---------------------------------------------------------------------------
# Sprite variant selection (registry-group driven; random per spawn)
# ---------------------------------------------------------------------------
class TestSpriteVariants(unittest.TestCase):
    REG = load_registry(FIXTURE_DATA)

    def _slot(self, enemy):
        return enemy.get_component(SpriteAnimator).slot_key

    def test_era_selects_the_matching_era_slot(self):
        # Walker eras 1-4 = enemy_stage_1..4; the era clamps to the last one.
        # FakeRng.choice -> first variant, so multi-variant eras resolve to _v1.
        tm = synth(["bbs"])
        cases = {0: "enemy_stage_1_v1", 1: "enemy_stage_2",
                 2: "enemy_stage_3", 3: "enemy_stage_4_v1",
                 9: "enemy_stage_4_v1"}
        for era, slot in cases.items():
            with self.subTest(era=era):
                e = Enemy(2, 0, ENEM, tm, era, registry=self.REG,
                          rng=FakeRng())
                self.assertEqual(self._slot(e), slot)

    def test_random_variant_picked_at_spawn(self):
        # Era 1 has two variants; over many spawns a seeded rng yields both.
        tm = synth(["bbs"])
        rng = random.Random(1234)
        seen = {self._slot(Enemy(2, 0, ENEM, tm, 0, registry=self.REG,
                                 rng=rng)) for _ in range(50)}
        self.assertEqual(seen, {"enemy_stage_1_v1", "enemy_stage_1_v2"})

    def test_raider_resolves_its_own_group(self):
        tm = synth(["bbs"])
        r = Raider(2, 0, ENEM, tm, 2, registry=self.REG, rng=FakeRng())
        self.assertEqual(self._slot(r), "raider_stage_3")

    def test_fallback_slot_without_registry(self):
        # Headless stat/logic tests construct without a registry -> DEFAULT_SLOT.
        tm = synth(["bbs"])
        self.assertEqual(
            self._slot(Enemy(2, 0, ENEM, tm, 0)), "enemy_stage_1_v1")
        self.assertEqual(
            self._slot(Raider(2, 0, ENEM, tm)), "raider_stage_1")

    def test_spawner_threads_registry_into_variants(self):
        # Round 2 guarantees a non-empty wave regardless of base_enemy_count
        # tuning (round-1 grace rounds spawn nothing); tier is still 0 (< the
        # 10-level scale step), so variants come from Era 1.
        tm = synth(["bbs", "bbs", "bbs"])
        scene = Scene()
        sp = Spawner()
        sp.begin_round(2, tm, ENEM, rng=random.Random(7), registry=self.REG)
        for _ in range(2000):
            sp.update(0.1, scene)
        scene.update(0.0)
        slots = {self._slot(e) for e in scene.by_tag("enemy")}
        self.assertTrue(slots)
        self.assertTrue(slots <= {"enemy_stage_1_v1", "enemy_stage_1_v2"})


# ---------------------------------------------------------------------------
# Wave composition (prototype game.py:876-921) — standard + raiders + siege
# live since 10F, the boss since 10G (its rounds compose via round_counts).
# ---------------------------------------------------------------------------
RAIDER = ENEM["EnemyTypes"]["Raider"]
SIEGE = ENEM["EnemyTypes"]["SiegeCannon"]
FORM = ENEM["EnemyTypes"]["Formation"]
FORM0 = era_stats("Formation")


class TestSpawnComposition(unittest.TestCase):
    def setUp(self):
        self.tm = synth(["bbs", "bbs", "bbs"])
        self.spawn_tiles = {(t.col, t.row) for t in self.tm.spawning_tiles()}

    def _counts(self, round_num):
        sp = Spawner()
        sp.begin_round(round_num, self.tm, ENEM, rng=FakeRng())
        etypes = [et for _tile, et, _d in sp._queue]
        return sp, etypes

    # Boss rounds (every Boss.round_interval-th, LIVE since 10G) take the
    # BOSS_ROUND_COUNTS composition instead of the per-type formulas — those
    # rounds are covered by tools/tests/test_boss.py, so the formula loops
    # below skip them.
    _BOSS_INTERVAL = SCALE["rounds_per_era"]   # boss_round_in_era == the last

    def test_standard_count_formula(self):
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                self.assertEqual(etypes.count("standard"),
                                 expected_count("Standard", r))

    def test_raider_count_formula_and_start_round(self):
        start = RAIDER["start_round"]
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                if r < start:
                    self.assertEqual(etypes.count("raider"), 0)
                else:
                    self.assertEqual(etypes.count("raider"),
                                     expected_count("Raider", r))

    def test_siege_count_formula_and_start_round(self):
        start = SIEGE["start_round"]
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                if r < start:
                    self.assertEqual(etypes.count("siege"), 0)
                else:
                    self.assertEqual(etypes.count("siege"),
                                     expected_count("SiegeCannon", r))

    def test_siege_lead_group_heads_the_queue(self):
        # The lead group spawns FIRST (prototype siege_front + shuffled rest);
        # FakeRng.shuffle is identity, so the head of the queue is exactly it.
        r = SIEGE["start_round"] + 4
        _sp, etypes = self._counts(r)
        n_siege = etypes.count("siege")
        lead = min(int(SIEGE["queue_lead_count"] * SIEGE["mix_ratio"]), n_siege)
        self.assertGreater(lead, 0)
        self.assertEqual(etypes[:lead], ["siege"] * lead)
        # The remainder is mixed into the shuffled body, not appended in front.
        self.assertEqual(etypes[lead:].count("siege"), n_siege - lead)

    # -- formations (ER-4): the siege ACCRETION formula, body-mixed ---------

    def test_formation_count_formula_and_start_round(self):
        start = FORM["start_round"]
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss rounds carry no formations — pinned below
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                if r < start:
                    self.assertEqual(etypes.count("formation"), 0)
                else:
                    self.assertEqual(etypes.count("formation"),
                                     expected_count("Formation", r))

    def test_formations_accrete_one_every_three_rounds(self):
        # The proposed tuning spells out to r16 -> 1, r19 -> 2, r22 -> 3 — and
        # r22 is the D3' fence: it only survives the era-1 -> era-2 boundary
        # because count_start is a NUMBER (era 2 anchors at 2.666..., not 2).
        self.assertEqual(FORM["start_round"], 16)
        self.assertAlmostEqual(FORM["eras"][0]["count_per_round"], 1 / 3)
        for r, n in ((15, 0), (16, 1), (19, 2), (22, 3)):
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                self.assertEqual(etypes.count("formation"), n)

    def test_formations_are_body_mixed_never_queue_leading(self):
        # Siege leads the wave; a 2x2 at the head would wall the choke point
        # before anything else arrived, so formations sit in the shuffled body.
        r = 18   # >= siege start (14) AND >= formation start (16)
        _sp, etypes = self._counts(r)
        n_siege = etypes.count("siege")
        lead = min(int(SIEGE["queue_lead_count"] * SIEGE["mix_ratio"]), n_siege)
        self.assertGreater(lead, 0)
        self.assertGreater(etypes.count("formation"), 0)
        self.assertNotIn("formation", etypes[:lead])   # never in siege_front

    def test_no_formations_on_a_boss_round(self):
        # DELIBERATE: _boss_round composes from Boss.round_counts, a
        # $defs/spawn_counts table shared with every death_spawn row — adding a
        # formation key there would break the balancing-parity gate.
        r = self._BOSS_INTERVAL * 2          # 20: past the formation start
        self.assertGreaterEqual(r, FORM["start_round"])
        _sp, etypes = self._counts(r)
        self.assertEqual(etypes[0], "boss")
        self.assertNotIn("formation", etypes)

    def test_below_start_round_the_wave_is_byte_identical(self):
        # _formation_group is called LAST and returns [] below start_round, so
        # it consumes ZERO rng: a seeded wave is unchanged by the ER-4 flag.
        r = FORM["start_round"] - 1
        def queue(seed):
            sp = Spawner()
            sp.begin_round(r, self.tm, ENEM, rng=random.Random(seed))
            return [(t.col, t.row, e, d) for t, e, d in sp._queue]

        with_flag = queue(11)
        spawner_mod.ENABLE_FORMATION = False
        try:
            without_flag = queue(11)
        finally:
            spawner_mod.ENABLE_FORMATION = True
        self.assertTrue(with_flag)
        self.assertEqual(with_flag, without_flag)

    def test_the_non_formation_queue_is_unchanged_at_a_formation_round(self):
        # Calling _formation_group LAST keeps every earlier group's rng draw
        # sequence intact: strip the formations back out and the wave is the
        # same one ER-3 composed. (FakeRng.shuffle is identity, so the ORDER of
        # the remaining entries is directly comparable.)
        r = 22
        _sp, etypes = self._counts(r)
        self.assertEqual(etypes.count("formation"), 3)
        spawner_mod.ENABLE_FORMATION = False
        try:
            _sp2, without = self._counts(r)
        finally:
            spawner_mod.ENABLE_FORMATION = True
        self.assertEqual([e for e in etypes if e != "formation"], without)

    def test_boss_leads_every_boss_round(self):
        # ENABLE_BOSS flipped in 10G: every boss round (the era clock's
        # boss_round_in_era) emits exactly ONE boss at the head of the queue,
        # and non-boss rounds never emit one (composition -> test_boss.py).
        interval = SCALE["rounds_per_era"]
        for r in (interval, interval * 2):
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                self.assertEqual(etypes[0], "boss")
                self.assertEqual(etypes.count("boss"), 1)
        _sp, etypes = self._counts(interval + 1)
        self.assertNotIn("boss", etypes)

    def test_spawn_tiles_from_spawning_zone(self):
        sp = Spawner()
        sp.begin_round(5, self.tm, ENEM)  # real rng
        for tile, _et, _d in sp._queue:
            self.assertIn((tile.col, tile.row), self.spawn_tiles)

    def test_ramp_is_linear_slow_to_fast(self):
        # With jitter pinned to 1.0, delays equal the ramp: monotonic decreasing
        # from (center+span) to (center-span).
        sp = Spawner()
        sp.begin_round(3, self.tm, ENEM, rng=FakeRng(uniform_val=1.0))
        delays = [d for _t, _e, d in sp._queue]
        self.assertGreater(len(delays), 2)
        center = sp._interval
        span = SCALE["spawn_ramp_range"]
        self.assertAlmostEqual(delays[0], max(0.1, center + span))
        for a, b in zip(delays, delays[1:]):
            self.assertGreaterEqual(a + 1e-9, b)

    def test_update_spawns_into_scene(self):
        sp = Spawner()
        sp.begin_round(1, self.tm, ENEM, rng=FakeRng())
        scene = Scene()
        n = expected_count("Standard", 1)
        # Drive well past the total wave duration; one pop per expiry.
        for _ in range(2000):
            sp.update(0.1, scene)
        scene.update(0.0)
        self.assertEqual(len(scene.by_tag("enemy")), n)
        self.assertTrue(sp.done)

    def test_batch_size_halves_the_spawn_events_not_the_round_total(self):
        # ES-3/D4: `batch_size` is how many queue entries ONE timer expiry
        # releases. It changes how many spawn EVENTS a wave takes; the round's
        # total is untouched by the knob.
        def drive(batch):
            enem = copy.deepcopy(ENEM)
            enem["EnemyScaling"]["eras"][0]["batch_size"] = batch
            sp = Spawner()
            sp.begin_round(1, self.tm, enem, rng=FakeRng())
            scene, events = Scene(), 0
            for _ in range(2000):
                if sp.done:
                    break
                queued = len(sp._queue)
                sp.update(0.1, scene)
                if len(sp._queue) < queued:
                    events += 1
            scene.update(0.0)
            return len(scene.by_tag("enemy")), events

        total_1, events_1 = drive(1)
        total_2, events_2 = drive(2)
        self.assertEqual(total_1, expected_count("Standard", 1))
        self.assertGreater(events_1, 1)
        self.assertEqual(events_1, total_1)          # one per expiry at 1
        self.assertEqual(total_2, total_1)           # the total never moves
        self.assertEqual(events_2, math.ceil(events_1 / 2))

    # -- TU-9: round 0 is the tutorial's forced-composition round -----------

    def test_round_zero_composes_exactly_the_tutorial_count(self):
        sp, etypes = self._counts(0)
        self.assertEqual(len(etypes), SCALE["tutorial_round_enemy_count"])
        self.assertTrue(all(e == "standard" for e in etypes))

    def test_round_zero_tunable_changes_the_count(self):
        enem = copy.deepcopy(ENEM)
        enem["EnemyScaling"]["tutorial_round_enemy_count"] = 3
        sp = Spawner()
        sp.begin_round(0, self.tm, enem, rng=FakeRng())
        etypes = [et for _tile, et, _d in sp._queue]
        self.assertEqual(etypes, ["standard"] * 3)

    def test_round_zero_never_produces_a_boss_at_any_interval(self):
        # (0 - 1) // n goes negative for every n, and a naive `0 % n == 0`
        # boss check would fire at EVERY era length — era_math clamps round 0
        # to era 0 and never calls it a boss round (D11), and the round-0
        # composition branch is still checked first, unconditionally.
        for interval in (1, 2, 5, self._BOSS_INTERVAL):
            with self.subTest(interval=interval):
                enem = copy.deepcopy(ENEM)
                enem["EnemyScaling"]["rounds_per_era"] = interval
                enem["EnemyScaling"]["boss_round_in_era"] = interval
                sp = Spawner()
                sp.begin_round(0, self.tm, enem, rng=FakeRng())
                etypes = [et for _tile, et, _d in sp._queue]
                self.assertNotIn("boss", etypes)
                self.assertEqual(
                    len(etypes), enem["EnemyScaling"]["tutorial_round_enemy_count"])

    def test_round_zero_leaves_round_one_scaling_unshifted(self):
        # Composing round 0 THEN round 1 on the SAME spawner instance must
        # yield the identical round-1 composition as composing round 1
        # fresh — round 0 must leave no era/interval state that shifts the
        # real wave-scaling formulas (the actual user requirement).
        sp = Spawner()
        sp.begin_round(0, self.tm, ENEM, rng=FakeRng())
        self.assertEqual(sp._era, 0)          # D11: round 0 is era 0
        sp.begin_round(1, self.tm, ENEM, rng=FakeRng())
        after_zero = [et for _tile, et, _d in sp._queue]

        fresh = Spawner()
        fresh.begin_round(1, self.tm, ENEM, rng=FakeRng())
        fresh_etypes = [et for _tile, et, _d in fresh._queue]

        self.assertEqual(after_zero, fresh_etypes)


# ---------------------------------------------------------------------------
# Walker locomotion + block-and-attack (prototype enemy._do_move/_do_attack)
# ---------------------------------------------------------------------------
class TestWalkerPath(unittest.TestCase):
    def test_walks_to_base_and_flags_reached(self):
        tm = synth(["bbs"])  # base(0,0), (1,0) buildable empty, (2,0) spawn
        scene = Scene()
        e = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(e)
        for _ in range(200):
            scene.update(0.1)
            if e.get_component(PathAgent).reached_base:
                break
        self.assertTrue(e.get_component(PathAgent).reached_base)

    def test_blocks_and_attacks_building_on_path(self):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        blocker, _c = place_building(tm, tm.get(1, 0), "economic", 9999,
                                     BUILD, scene, occ)
        e = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(e)
        for _ in range(4):
            scene.update(0.1)
        pa = e.get_component(PathAgent)
        self.assertTrue(pa.blocked)
        self.assertFalse(pa.reached_base)
        # Enemy attacks immediately on stopping (cooldown starts at 0).
        self.assertGreaterEqual(
            blocker.get_component(RoundStats).dmg_taken_this_round, e.dmg)


# ---------------------------------------------------------------------------
# Combat HP ledger (the phase Quick Test)
# ---------------------------------------------------------------------------
class TestCombatLedger(unittest.TestCase):
    def test_defender_kills_stationary_enemy_exact_ledger(self):
        tm = synth(["bbs"])  # defender on (1,0), enemy frozen on (2,0)
        scene, occ = Scene(), TileOccupancy()
        defender, _c = place_building(tm, tm.get(1, 0), "defence", 9999,
                                      BUILD, scene, occ)
        e = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(e)
        scene.update(0.0)              # apply spawn + on_spawn
        e.get_component(Movement).waypoints = []  # freeze: a pure target

        hp0 = e.get_component(Health).hp
        dmg = defender.damage()
        expected_shots = math.ceil(hp0 / dmg)

        alive_frames = 0
        for _ in range(1000):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD, VFX)
            if not scene.by_tag("enemy"):
                break
            alive_frames += 1
        else:
            self.fail("enemy never died")

        # Only shots that land while alive count; the ledger is exact.
        self.assertEqual(
            defender.get_component(RoundStats).dmg_dealt_this_round,
            expected_shots * dmg)
        self.assertEqual(expected_shots, math.ceil(hp0 / dmg))
        self.assertEqual(scene.by_tag("enemy"), [])

    def test_min_attack_speed_floor(self):
        class _FastDefender:
            def attack_speed(self):
                return 0.01
        floor = BUILD["DefenceBuildings"]["globals"]["min_attack_speed"]
        self.assertEqual(attack_interval(_FastDefender(), floor), floor)

    def test_projectile_wasted_on_dead_target(self):
        tm = synth(["bbs"])
        scene = Scene()
        e = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(e)
        scene.update(0.0)
        e.get_component(Movement).waypoints = []
        proj = Projectile(2.0, 0.0, 10, 3.75)
        proj.get_component(ProjectileHoming).launch(e, defender_stub(), scene)
        scene.spawn(proj)
        # Kill the enemy before the shot lands.
        e.get_component(Health).hp = 0
        for _ in range(20):
            scene.update(0.05)
        self.assertEqual(scene.by_tag("projectile"), [])  # projectile despawned
        # Dead target took no negative HP; nothing crashed.
        self.assertLessEqual(e.get_component(Health).hp, 0)


class TestBaseArrival(unittest.TestCase):
    def test_enemy_damages_base_and_despawns(self):
        tm = synth(["bs"])  # base(0,0), (1,0) spawn
        scene, occ = Scene(), TileOccupancy()
        base = BaseBuilding(tm.base_col, tm.base_row, CORE)
        attach_base(tm, base, scene, occ)
        e = create_enemy("standard", 1, 0, ENEM, tm)
        scene.spawn(e)
        for _ in range(200):
            scene.update(0.1)
            resolve_combat(scene, tm, 0.1, BUILD, VFX)
            if not scene.by_tag("enemy"):
                break
        else:
            self.fail("enemy never reached the base")
        self.assertEqual(base.get_component(Health).hp,
                         max(0, CORE["TheHole"]["base_hp"] - STD0["dmg"]))
        self.assertEqual(
            base.get_component(RoundStats).dmg_taken_this_round, STD0["dmg"])


class TestSpawnTilesAreSpawningOnly(unittest.TestCase):
    """Pin: enemies ONLY spawn on SPAWNING-state tiles — every queued spawn
    rides one, both at seed and again after an unlock recedes the band (the
    dual-axis recede moves the band; the spawner must follow it)."""

    @staticmethod
    def _tm():
        # buildable pocket, combat field, an east AND a south spawn band, with
        # forest room behind both for the recede backfills
        return synth([
            "bbccssff",
            "bbccssff",
            "ccccssff",
            "ccccssff",
            "ssssffff",
            "ssssffff",
            "ffffffff",
            "ffffffff",
        ])

    @staticmethod
    def _assert_queue_on_spawning(test, sp, tm):
        spawning = {(t.col, t.row) for t in tm.spawning_tiles()}
        queued = [tile for tile, _etype, _delay in sp._queue]
        test.assertTrue(queued)   # a real wave, not a vacuous pass
        for tile in queued:
            test.assertEqual(tile.state, TileState.SPAWNING,
                             (tile.col, tile.row))
            test.assertIn((tile.col, tile.row), spawning)

    def test_queue_rides_spawning_tiles_before_and_after_recede(self):
        tm = self._tm()
        sp = Spawner()
        sp.begin_round(2, tm, ENEM, rng=random.Random(3))
        self._assert_queue_on_spawning(self, sp, tm)

        before = {(t.col, t.row) for t in tm.spawning_tiles()}
        self.assertTrue(tm.do_unlock(tm.get(2, 0)))   # recedes both bands
        after = {(t.col, t.row) for t in tm.spawning_tiles()}
        self.assertNotEqual(before, after)            # the band really moved

        sp2 = Spawner()
        sp2.begin_round(2, tm, ENEM, rng=random.Random(3))
        self._assert_queue_on_spawning(self, sp2, tm)


# ---------------------------------------------------------------------------
# Formation (ER-4) — the 2×2 marching column. It adds NO mechanism: it is the
# first consumer of ER-1's per-slot frame size, ER-2's footprint clearance
# pathing and ER-3's death_spawn, all three driven purely from balancing.
# ---------------------------------------------------------------------------
class TestFormation(unittest.TestCase):
    REG = load_registry(FIXTURE_DATA)

    def test_class_attrs_and_registration(self):
        self.assertEqual(Formation.ETYPE, "formation")
        self.assertEqual(Formation.REGISTRY_GROUP, "Formation")
        self.assertEqual(Formation.STAT_SUBTREE, ("Formation",))
        self.assertEqual(Formation.DEFAULT_SLOT, "formation_stage_1")
        self.assertEqual(Formation.HP_BAR_W, 32)   # a 2-tile body
        tm = synth(["bbs"])
        self.assertIsInstance(create_enemy("formation", 2, 0, ENEM, tm),
                              Formation)

    def test_construction_threads_footprint_and_sprite_fit(self):
        enem = footprint_balance("Formation", 2)
        tm = synth(["bbs"])
        f = create_enemy("formation", 2, 0, enem, tm)
        self.assertEqual(f.get_component(PathAgent).footprint, 2)
        anim = f.get_component(SpriteAnimator)
        self.assertEqual(anim.fit_tiles, 2.0)      # threaded from the balance
        self.assertEqual(anim.scale, 1.0)
        self.assertEqual(f.get_component(Health).max_hp, FORM0["hp"])

    def test_stats_come_from_the_formation_block_not_standard(self):
        """The bug an un-overridden `_resolve_stats` would ship: the BASE
        Enemy._resolve_stats reads balance["EnemyTypes"]["Standard"] LITERALLY
        — STAT_SUBTREE does not drive it — so a Formation without the override
        would silently walk around with walker stats."""
        tm = synth(["bbs"])
        f = Formation(2, 0, ENEM, tm, 0)
        self.assertEqual(f.get_component(Health).hp, FORM0["hp"])
        self.assertEqual(f.dmg, FORM0["dmg"])
        self.assertAlmostEqual(f.get_component(Movement).speed,
                               FORM0["move_speed"])
        self.assertNotEqual(FORM0["hp"], STD0["hp"])        # the fixture is real
        self.assertNotEqual(f.get_component(Health).hp, STD0["hp"])
        self.assertNotEqual(f.dmg, STD0["dmg"])

    def test_reads_its_own_era_rows_like_standard_and_siege(self):
        tm = synth(["bbs"])
        for era in range(0, 6):
            with self.subTest(era=era):
                st = era_stats("Formation", era)
                f = Formation(2, 0, ENEM, tm, era)
                self.assertEqual(f.get_component(Health).hp, st["hp"])
                self.assertEqual(f.dmg, st["dmg"])
                self.assertAlmostEqual(f.get_component(Movement).speed,
                                       st["move_speed"])

    def test_the_type_itself_refuses_a_one_tile_gap_a_walker_threads(self):
        """End-to-end proof that balancing -> PathAgent -> pathfinder is wired:
        it is the TYPE's footprint in the balance, not a raw footprint=2 argument,
        that seals the gap. Wall down col 2 with a ONE-tile hole.

        The footprint is PINNED, not read live: `footprint` is designer content and
        every type sits at 1 today, which would quietly turn this into "a 1x1 walks
        through a 1x1 hole" — a tautology that proves none of the wiring it names."""
        enem = footprint_balance("Formation", 2)
        tm = synth(["ccfcc", "ccfcc", "ccccc", "ccfcc", "ccfcc"], base=(0, 2))
        walker = create_enemy("standard", 4, 2, enem, tm)
        walker.on_spawn()
        wp = walker.get_component(Movement).waypoints
        self.assertTrue(wp, "a 1x1 must thread the one-tile hole")
        self.assertIn([2.0, 2.0], wp)               # it goes through the gap

        form = create_enemy("formation", 4, 2, enem, tm)
        form.on_spawn()
        # No 2x2 anchor can cover col 2 — the hole is one tile tall, so the body
        # would always straddle background. Both path variants come back empty;
        # the unit simply stands still (never a phantom base hit).
        self.assertEqual(form.get_component(Movement).waypoints, [])
        self.assertFalse(form.get_component(PathAgent).reached_base)

    def test_the_128x128_sheet_slices_and_draws_at_exactly_2x2_tiles(self):
        """ER-1's per-slot frame-size override, end to end — ER-4 is its FIRST
        committed consumer. The 128x128 sheet is cut at 128x128 (not the
        enemies category's 64x96), the grey-X placeholder sizes itself off that
        override with NO manifest entry and does not raise (E-23/E-37), and the
        downscale-only fit lands it at exactly 2x2 tiles at scale 1.0."""
        from engine.assets.store import AssetStore
        from engine.render.renderer import fit_factor

        for era in (1, 2, 3, 4):
            self.assertEqual(
                self.REG.frame_size(f"formation_stage_{era}"), (128, 128))
        # ...while the category default is untouched.
        self.assertEqual(self.REG.frame_size("enemy_stage_1_v1"), (64, 96))
        # The object form is normalised away: group_slots stays plain strings.
        self.assertEqual(self.REG.group_slots("enemies", ("Formation", "Era 1")),
                         ("formation_stage_1",))

        store = AssetStore(registry=self.REG,
                           sprites_dir=FIXTURE_DATA / "sprites")
        frame = store.frame("formation_stage_1", "walk", 0)   # no manifest entry
        self.assertEqual((frame.frame_w, frame.frame_h), (128, 128))
        self.assertEqual(frame.surface.get_size(), (128, 128))

        # fit = min(1.0, 2*64 / 128) = 1.0 -> drawn 128px wide = 2 tiles.
        tile_w = 64
        fit = fit_factor(frame.frame_w, tile_w, fit_tiles=2.0)
        self.assertEqual(fit, 1.0)
        self.assertEqual(frame.frame_w * fit * FORM["sprite_scale"],
                         2 * tile_w)

    def test_the_registry_group_resolves_a_slot_per_era(self):
        tm = synth(["bbs"])
        for era, slot in {0: "formation_stage_1", 1: "formation_stage_2",
                           2: "formation_stage_3", 3: "formation_stage_4",
                           9: "formation_stage_4"}.items():
            with self.subTest(era=era):
                f = Formation(2, 0, ENEM, tm, era, registry=self.REG,
                              rng=FakeRng())
                self.assertEqual(f.get_component(SpriteAnimator).slot_key, slot)


class TestFormationBreak(unittest.TestCase):
    """D4 — there is NO break state: breaking formation IS dying. The whole
    mechanic is ER-3's death_spawn driven from data (at_hp_fraction 0.5), so
    this pins the DATA, not a new code path."""

    # base (0,0); a 2x2-clear spawn band bottom-right, so the formation both
    # spawns and paths legally.
    ROWS = ["bbcc", "bbcc", "ccss", "ccss"]

    def _session(self, tm, scene, occ, round_num=1):
        session = Session.create(Spawner(), tm, ENEM, CORE, BUILD,
                                 rng=random.Random(2), occupancy=occ)
        session.state.round_num = round_num
        session.state.phase = GamePhase.ENEMY
        session.spawner.begin_round(round_num, tm, ENEM, rng=random.Random(2))
        session.spawner.clear()   # only the enemies this test spawns by hand
        return session

    def _board(self):
        tm = synth(self.ROWS)
        scene, occ = Scene(), TileOccupancy()
        attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
        return tm, scene, occ

    @staticmethod
    def _frame(session, scene, tm, dt=0.0):
        session.pre_sim(dt, scene)
        if session.state.state == GameState.GAMEPLAY and not session.frozen:
            scene.update(dt)
            resolve_combat(scene, tm, dt, BUILD, VFX,
                           on_base_hit=session.on_base_hit,
                           on_enemy_death=session.on_enemy_death)
            session.post_sim(scene)

    def test_dead_at_half_hp_and_bursts_four_regulars_at_80_percent(self):
        self.assertEqual(FORM["death_spawn"]["at_hp_fraction"], 0.5)
        tm, scene, occ = self._board()
        session = self._session(tm, scene, occ)
        parent = create_enemy("formation", 2, 2, ENEM, tm)
        scene.spawn(parent)
        scene.update(0.0)

        health = parent.get_component(Health)
        self.assertTrue(parent.alive)
        health.hp = int(health.max_hp * 0.5)      # AT the threshold => dead
        self.assertFalse(parent.alive)            # no HP left to chew through

        self._frame(session, scene, tm)           # report -> stash -> flush
        scene.update(0.0)

        children = [e for e in scene.by_tag("enemy") if e.alive]
        self.assertEqual(Counter(e.ETYPE for e in children),
                         Counter({"standard": 4}))
        self.assertNotIn(parent, scene.by_tag("enemy"))   # the parent despawned

        frac = FORM["death_spawn"]["spawn_hp_fraction"]
        for child in children:
            ch = child.get_component(Health)
            self.assertEqual(ch.max_hp, STD0["hp"])       # era 0
            self.assertEqual(ch.hp, max(1, int(ch.max_hp * frac)))
            self.assertLess(ch.hp, ch.max_hp)
            self.assertTrue(child.alive)   # 0.8 > Standard's 0.0 -> no cascade
            self.assertEqual((child._col, child._row), (2, 2))  # parent's tile

    def test_the_burst_fires_exactly_once(self):
        tm, scene, occ = self._board()
        session = self._session(tm, scene, occ)
        parent = create_enemy("formation", 2, 2, ENEM, tm)
        scene.spawn(parent)
        scene.update(0.0)
        health = parent.get_component(Health)
        health.hp = int(health.max_hp * 0.5)

        session.on_enemy_death(parent)
        self.assertEqual(len(session._death_spawns_pending), 1)
        self.assertTrue(parent.death_spawned)
        session.on_enemy_death(parent)            # the double-death frame
        self.assertEqual(len(session._death_spawns_pending), 1)

        session.post_sim(scene)
        scene.update(0.0)
        self.assertEqual(
            len([e for e in scene.by_tag("enemy") if e.alive]), 4)

        session.post_sim(scene)                   # nothing left to flush
        scene.update(0.0)
        self.assertEqual(
            len([e for e in scene.by_tag("enemy") if e.alive]), 4)

    def test_the_scattering_pool_is_the_intended_hp_budget(self):
        """The tuning story, pinned so a retune in the editor stays honest: it
        absorbs half its HP as one body, then the survivors carry the rest."""
        absorbed = FORM0["hp"] * FORM["death_spawn"]["at_hp_fraction"]
        row = FORM["death_spawn"]["spawns"][0]
        scattered = row["regular"] * int(
            STD0["hp"] * FORM["death_spawn"]["spawn_hp_fraction"])
        self.assertEqual(absorbed, 220)           # 440 * 0.5
        self.assertEqual(scattered, 176)          # 4 * int(55 * 0.8)
        siege_hp = era_stats("SiegeCannon")["hp"]
        self.assertGreater(absorbed + scattered, siege_hp)      # > one cannon
        self.assertLess(absorbed + scattered, 2 * siege_hp)     # < two

    def test_spawn_hp_fraction_stays_above_every_child_at_hp_fraction(self):
        """The documented footgun: a spawn_hp_fraction at or below a child
        type's own at_hp_fraction kills the children on the frame they appear.
        There is deliberately no runtime guard — so pin the shipped data."""
        frac = FORM["death_spawn"]["spawn_hp_fraction"]
        for key in ("regular", "raiders", "siege"):
            n = FORM["death_spawn"]["spawns"][0][key]
            if not n:
                continue
            child = {"regular": "Standard", "raiders": "Raider",
                     "siege": "SiegeCannon"}[key]
            self.assertGreater(
                frac,
                ENEM["EnemyTypes"][child]["death_spawn"]["at_hp_fraction"])


class TestCommander(unittest.TestCase):
    """BR-2/D8 — the Commander ships DORMANT. Two pins only: it resolves its
    OWN era rows through the base resolver (no `_resolve_stats` override), and
    it contributes nothing to any wave at the shipped values."""

    def test_stats_come_from_its_own_block_via_the_base_resolver(self):
        cmd0 = era_stats("Commander")
        tm = synth(["bbs"])
        c = create_enemy("commander", 2, 0, ENEM, tm, 0)
        self.assertIsInstance(c, Commander)
        self.assertIsNone(Commander.__dict__.get("_resolve_stats"),
                          "D8: the Commander must use the BASE per-era "
                          "resolver — the Boss's is the one override left")
        self.assertEqual(c.get_component(Health).hp, cmd0["hp"])
        self.assertEqual(c.dmg, cmd0["dmg"])
        self.assertAlmostEqual(c.get_component(Movement).speed,
                               cmd0["move_speed"])
        self.assertNotEqual(cmd0["hp"], STD0["hp"])      # the fixture is real
        # A building hunter with a siege-sized bar and no boss tag (D8).
        self.assertEqual(c.get_component(PathAgent).hunt, "any_non_base")
        self.assertEqual((Commander.HP_BAR_W, Commander.HP_BAR_H), (24, 2))
        self.assertNotIn("boss", c.tags)

    def test_contributes_zero_to_every_wave_at_the_shipped_values(self):
        tm = synth(["bbs"])
        sp = Spawner()
        for rnd in (0, 1, 6, 10, 14, 30, 60):
            with self.subTest(round=rnd):
                self.assertEqual(expected_count("Commander", rnd), 0)
                sp.begin_round(rnd, tm, ENEM, rng=random.Random(7))
                self.assertEqual(
                    [e for _, e in sp.pending() if e == "commander"], [])


class TestRegistryGroupDrift(unittest.TestCase):
    """fix-editor-preview-footprint §2.4: `data/balancing/enemies.json`'s new
    required `registry_group` leaf (added so the editor can resolve a slot's
    footprint fit without importing `game/`) is a SECOND home for what
    `game/enemies/enemy.py`'s `REGISTRY_GROUP` class constants already say —
    nothing wires the two together, and the brief deliberately does NOT ask
    for that refactor here (follow-up work). This pins the two so a drift
    between them turns red instead of silently breaking the editor preview
    for whichever type moved."""

    def test_registry_group_matches_data_for_every_enemy_subclass(self):
        for cls in (Enemy, Raider, SiegeCannon, Formation, Commander,
                    Boss):
            block = ENEM["EnemyTypes"]
            for seg in cls.STAT_SUBTREE:
                block = block[seg]
            self.assertEqual(
                cls.REGISTRY_GROUP, block["registry_group"],
                msg=f"{cls.__name__}.REGISTRY_GROUP ({cls.REGISTRY_GROUP!r}) "
                    f"drifted from EnemyTypes.{'.'.join(cls.STAT_SUBTREE)}."
                    f"registry_group ({block['registry_group']!r})")


class TestPurity(unittest.TestCase):
    def test_game_enemies_imports_no_pygame(self):
        code = ("import sys; import game.enemies; "
                "assert 'pygame' not in sys.modules, 'pygame leaked into game.enemies'")
        result = subprocess.run([sys.executable, "-c", code], cwd=REPO,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, msg=result.stderr)


def defender_stub():
    """A minimal shooter carrying a RoundStats (the projectile credits it)."""
    from engine.core import GameObject, Transform
    return GameObject(transform=Transform(wx=1.0, wy=0.0),
                      components=[RoundStats()])


if __name__ == "__main__":
    unittest.main()
