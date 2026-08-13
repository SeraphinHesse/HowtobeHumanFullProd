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
    BURROW_EMERGE, BURROW_SUBMERGED, BURROW_WALKING, Boss, Commander, Digger,
    DirtPile, DIRT_PILE_SLOT, Drummer, Enemy, Formation, Projectile, Raider,
    SiegeCannon, Sniper, Spawner, attack_interval, create_enemy,
    resolve_combat,
)
from game.enemies.combat import ProjectileHoming
from game.enemies.components import (
    BUFF_DECAY_SECONDS, BuffState, BurrowAgent, DrummerAura, EnemyCombat,
    Kidnap, PathAgent,
)
from game.enemies.dirt_pile import DirtPileFade
from game.enemies.enemy import ENEMY_CLASSES
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

    `footprint` is designer content (ER-1). A test that reads it live to prove
    multi-tile behaviour degrades into a tautology the moment a designer
    flattens it — "a 1x1 cannot fit through a 1x1 gap" is not the claim these
    tests make. Pin the number so they keep testing the WIRING (balance ->
    PathAgent.footprint -> pathfinder / sprite fit); the live value has its own
    guard in the schema.

    The pair is PER-ERA for every era-shaped type, so this writes EVERY row —
    the shape `test_boss.boss_footprint` has always used for the Boss's own
    `stats[]` table."""
    enem = copy.deepcopy(ENEM)
    for row in enem["EnemyTypes"][etype]["eras"]:
        row["footprint"] = footprint
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
        """Over many spawns a seeded rng yields EVERY variant of the era's
        family, and nothing outside it.

        The family is read from the registry rather than pinned. It used to be
        the literal `{"enemy_stage_1_v1", "enemy_stage_1_v2"}`, so importing a
        third walker variant in the editor turned this red — the exact "drop a
        new `_v3` into the era and the pool grows with NO code change" contract
        the feature advertises (`game/enemies/CLAUDE.md`)."""
        tm = synth(["bbs"])
        family = set(self.REG.group_slots("enemies", ("Walker", "Era 1")))
        self.assertGreater(len(family), 1, "era 1 must have several variants, "
                                           "or this test proves nothing")
        rng = random.Random(1234)
        # Enough draws that every variant is overwhelmingly likely to appear.
        seen = {self._slot(Enemy(2, 0, ENEM, tm, 0, registry=self.REG,
                                 rng=rng)) for _ in range(50 * len(family))}
        self.assertEqual(seen, family)

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

    def test_formations_accrete_one_per_cadence_across_the_era_boundary(self):
        """One more formation every `1 / count_per_round` rounds, unbroken.

        The cadence and the first round are DERIVED, never pinned — the old
        version spelled out "r16 -> 1, r19 -> 2, r22 -> 3" and went red the day
        `start_round` was retuned 16 -> 18, though the accretion it tests had
        not changed at all.

        What is actually load-bearing is the D3' fence: the run has to stay on
        cadence THROUGH an era boundary, and it only does because `count_start`
        is a NUMBER rather than an int (era 2 anchors at 2.666..., not 2). A
        truncating anchor would drop a step exactly there, so the sweep below
        deliberately runs far enough to cross one."""
        start = FORM["start_round"]
        cpr = FORM["eras"][0]["count_per_round"]
        cadence = round(1 / cpr)
        self.assertAlmostEqual(cpr * cadence, 1.0)   # a whole-round cadence
        # Nothing before the start round.
        for r in (1, start // 2, start - 1):
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                self.assertEqual(etypes.count("formation"), 0)
        # ...then exactly one more per cadence, era boundaries included.
        # Boss rounds are skipped, not asserted against: formations never spawn
        # on one (`_boss_round` composes from `Boss.round_counts`, which carries
        # no formation key — see `test_formations_never_spawn_on_a_boss_round`).
        from engine.era_math import is_boss_round
        checked = 0
        for k in range(8):
            r = start + k * cadence
            if is_boss_round(r, SCALE["rounds_per_era"],
                             SCALE["boss_round_in_era"]):
                continue
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                self.assertEqual(etypes.count("formation"),
                                 expected_count("Formation", r))
                self.assertEqual(etypes.count("formation"), k + 1)
            checked += 1
        self.assertGreaterEqual(checked, 4, "the sweep must actually run")

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
        # The round is DERIVED: batching is only observable on a wave with more
        # than one enemy in it, and the arithmetic below is only clean while the
        # wave is walkers-only. This was hardcoded to round 1, which carried
        # several walkers when the test was written; a later retune dropped
        # round 1 to exactly ONE walker, making `events_1 > 1` unsatisfiable
        # and reddening a test whose subject is the knob, not the tuning.
        round_num = None
        for r in range(1, 60):
            etypes = self._counts(r)[1]
            if len(etypes) >= 2 and set(etypes) == {"standard"}:
                round_num = r
                break
        self.assertIsNotNone(
            round_num, "no walkers-only round carries 2+ enemies — the batch "
                       "knob cannot be observed against this balancing")

        def drive(batch):
            enem = copy.deepcopy(ENEM)
            enem["EnemyScaling"]["eras"][0]["batch_size"] = batch
            sp = Spawner()
            sp.begin_round(round_num, self.tm, enem, rng=FakeRng())
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
        self.assertEqual(total_1, expected_count("Standard", round_num))
        self.assertGreater(events_1, 1)
        self.assertEqual(events_1, total_1)          # one per expiry at 1
        self.assertEqual(total_2, total_1)           # the total never moves
        self.assertEqual(events_2, math.ceil(events_1 / 2))

    # -- TU-9: round 0 is the tutorial's forced-composition round -----------

    def test_round_zero_composes_exactly_the_tutorial_count(self):
        sp, etypes = self._counts(0)
        self.assertEqual(len(etypes), SCALE["tutorial_round_enemy_count"])
        self.assertTrue(all(e == "tutorial" for e in etypes))

    def test_round_zero_tunable_changes_the_count(self):
        enem = copy.deepcopy(ENEM)
        enem["EnemyScaling"]["tutorial_round_enemy_count"] = 3
        sp = Spawner()
        sp.begin_round(0, self.tm, enem, rng=FakeRng())
        etypes = [et for _tile, et, _d in sp._queue]
        self.assertEqual(etypes, ["tutorial"] * 3)

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

    def test_its_footprint_grows_with_the_era_and_clamps_past_the_table(self):
        """The Formation is the one shipped type whose body CHANGES size, so
        this is where the per-era footprint actually earns its keep: the fit
        must follow the era, and past the last authored row it must CLAMP
        (`endgame_scaling` carries no footprint factor, deliberately).

        Read off the LIVE rows rather than a hardcoded 2,2,3,3,4 — the claim
        under test is that `resolve_fit` lands on the right ROW, not what the
        designer tuned it to."""
        rows = ENEM["EnemyTypes"]["Formation"]["eras"]
        tm = synth(["bbs"])
        for era in range(len(rows) + 3):          # 3 eras past the table
            with self.subTest(era=era):
                row = rows[min(era, len(rows) - 1)]
                self.assertEqual(
                    Formation.resolve_fit(ENEM["EnemyTypes"]["Formation"],
                                          era),
                    (int(row["footprint"]), float(row["sprite_scale"])))
                # and the seam is what construction actually uses
                f = Formation(2, 0, ENEM, tm, era)
                self.assertEqual(f.get_component(PathAgent).footprint,
                                 int(row["footprint"]))
                self.assertEqual(f.get_component(SpriteAnimator).fit_tiles,
                                 float(row["footprint"]))
        self.assertNotEqual(rows[0]["footprint"], rows[-1]["footprint"],
                            "the fixture must actually vary, or this is a "
                            "tautology")

    def test_the_type_itself_refuses_a_one_tile_gap_a_walker_threads(self):
        """End-to-end proof that balancing -> PathAgent -> pathfinder is wired:
        it is the TYPE's footprint in the balance, not a raw footprint=2 argument,
        that seals the gap. Wall down col 2 with a ONE-tile hole.

        The footprint is PINNED, not read live: it is designer content, and a
        retune to 1 would quietly turn this into "a 1x1 walks through a 1x1
        hole" — a tautology that proves none of the wiring it names. (The live
        curve has its own test above.)"""
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

    def test_the_per_slot_frame_size_override_slices_and_fits_end_to_end(self):
        """ER-1's per-slot frame-size override, end to end — ER-4 is its FIRST
        committed consumer. The sheet is cut at the slot's OWN frame size
        rather than the enemies category's default, the grey-X placeholder
        sizes itself off that override with NO manifest entry and does not
        raise (E-23/E-37), and the downscale-only fit is applied to it.

        Every pixel number here is READ from the registry. It used to spell out
        128x128 (and "exactly 2x2 tiles", which followed from it): the
        Formation's art was later re-cut to 64x32 and the test went red for
        naming the old sheet, not for any change in the override mechanism it
        exists to cover. What must hold is that the slot's size DIFFERS from
        the category default and is honoured all the way to the drawn frame."""
        from engine.assets.store import AssetStore
        from engine.render.renderer import fit_factor

        default_size = self.REG.frame_size("enemy_stage_1_v1")
        override = self.REG.frame_size("formation_stage_1")
        self.assertNotEqual(
            override, default_size,
            "the Formation slot must carry a per-slot frame size, or this "
            "test is a tautology over the category default")
        # Every era of the type shares that override...
        for era in (1, 2, 3, 4):
            self.assertEqual(self.REG.frame_size(f"formation_stage_{era}"),
                             override)
        # ...while other categories' slots keep the default.
        self.assertEqual(self.REG.frame_size("enemy_stage_1_v1"), default_size)
        # The object form is normalised away: group_slots stays plain strings.
        self.assertEqual(self.REG.group_slots("enemies", ("Formation", "Era 1")),
                         ("formation_stage_1",))

        store = AssetStore(registry=self.REG,
                           sprites_dir=FIXTURE_DATA / "sprites")
        frame = store.frame("formation_stage_1", "walk", 0)   # no manifest entry
        self.assertEqual((frame.frame_w, frame.frame_h), override)
        self.assertEqual(frame.surface.get_size(), override)

        # Downscale-only: the frame is fitted to the era's own footprint and
        # never blown up past 1.0.
        tile_w = 64
        fit_tiles = float(FORM["eras"][0]["footprint"])
        fit = fit_factor(frame.frame_w, tile_w, fit_tiles=fit_tiles)
        self.assertEqual(fit, min(1.0, fit_tiles * tile_w / frame.frame_w))
        self.assertLessEqual(fit, 1.0)

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


DIGGER = ENEM["EnemyTypes"]["Digger"]
DIG0 = era_stats("Digger")


class TestDigger(unittest.TestCase):
    """NE-2 — the burrow / claim / emerge machine.

    A ONE-ROW board throughout, deliberately: it makes "the route runs THROUGH
    that tile" a fact of the board rather than a hope about the cost field,
    which is exactly what the `no_melee` regression needs to mean anything.
    Every expectation is hand-computed from the pinned fixture's own JSON.
    """

    #: cols 0..14 buildable (base at 0), col 15 the spawn band.
    ROW = "b" * 15 + "s"

    def _board(self):
        tm = synth([self.ROW])
        scene, occ = Scene(), TileOccupancy()
        attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE),
                    scene, occ)
        return tm, scene, occ

    def _digger(self, scene, tm, col):
        dig = create_enemy("digger", col, 0, ENEM, tm, 0)
        dig._scene = scene          # what Spawner does at both spawn sites
        scene.spawn(dig)
        return dig

    @staticmethod
    def _parts(dig):
        return (dig.get_component(BurrowAgent), dig.get_component(PathAgent),
                dig.get_component(Movement))

    def _run_until(self, scene, dig, predicate, dt=0.05, limit=2000):
        for _ in range(limit):
            scene.update(dt)
            if predicate():
                return True
        return False

    # -- wiring ------------------------------------------------------------

    def test_class_attrs_registration_and_no_melee_wiring(self):
        tm, scene, _occ = self._board()
        dig = create_enemy("digger", 10, 0, ENEM, tm, 0)
        self.assertIsInstance(dig, Digger)
        self.assertEqual(ENEMY_CLASSES["digger"], Digger)
        self.assertEqual(Digger.ETYPE, "digger")
        self.assertEqual(Digger.REGISTRY_GROUP, "Digger")
        self.assertEqual(Digger.DEFAULT_SLOT, "digger_stage_1")
        self.assertEqual(Digger.STAT_SUBTREE, ("Digger",))
        pa = dig.get_component(PathAgent)
        self.assertEqual(pa.hunt, "structure")
        self.assertTrue(pa.no_melee)
        self.assertFalse(dig.get_component(Kidnap).enabled)
        # dig_speed doubles as move_speed — ONE number for both phases.
        burrow = dig.get_component(BurrowAgent)
        self.assertEqual(burrow.dig_speed, DIGGER["dig_speed"])
        self.assertEqual(burrow.dig_range_tiles, DIGGER["dig_range_tiles"])
        self.assertAlmostEqual(dig.get_component(Movement).speed,
                               DIGGER["dig_speed"])
        self.assertEqual(dig.get_component(Health).hp, DIG0["hp"])
        self.assertEqual(dig.dmg, DIG0["dmg"])
        # BurrowAgent must sit BETWEEN PathAgent and Movement.
        kinds = [type(c).__name__ for c in dig.components]
        self.assertLess(kinds.index("PathAgent"), kinds.index("BurrowAgent"))
        self.assertLess(kinds.index("BurrowAgent"), kinds.index("Movement"))

    def test_every_other_type_keeps_no_melee_off(self):
        tm = synth(["bbs"])
        for etype in ("standard", "raider", "siege", "formation",
                      "commander", "boss"):
            with self.subTest(etype=etype):
                e = create_enemy(etype, 2, 0, ENEM, tm, 0)
                self.assertFalse(e.get_component(PathAgent).no_melee)
                self.assertIsNone(e.get_component(BurrowAgent))

    # -- the min-target-distance preference -----------------------------------

    def test_prefers_a_target_at_least_min_distance_away(self):
        """Two claimable structures: one closer than
        `min_target_distance_tiles`, one clearing it. The Digger must claim
        the FARTHER one despite it not being the literal nearest."""
        tm, scene, occ = self._board()
        min_dist = DIGGER["min_target_distance_tiles"]
        self.assertGreater(min_dist, 1)     # the fixture must exercise this
        spawn_col = 12
        near_col = spawn_col - (min_dist - 1)   # too close: excluded
        far_col = spawn_col - (min_dist + 2)    # clears the minimum
        place_building(tm, tm.get(near_col, 0), "blocker", 9999, BUILD, scene, occ)
        place_building(tm, tm.get(far_col, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, spawn_col)
        burrow, pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual(burrow.min_target_distance_tiles, min_dist)
        self.assertEqual((pa.target_col, pa.target_row), (far_col, 0))

    def test_falls_back_to_the_near_target_when_nothing_clears_the_minimum(self):
        """No candidate clears `min_target_distance_tiles` -> claim the only
        (near) one rather than standing down. The near column is also inside
        `dig_range_tiles` at this fixture, so it may submerge on the very
        first tick — that's correct, not a bug this test is checking; the
        thing under test is the CLAIM, and that the Digger goes on to erupt
        normally rather than getting stuck."""
        tm, scene, occ = self._board()
        min_dist = DIGGER["min_target_distance_tiles"]
        spawn_col = 12
        near_col = spawn_col - (min_dist - 1)
        place_building(tm, tm.get(near_col, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, spawn_col)
        burrow, pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (near_col, 0))
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))

    # -- the state machine -------------------------------------------------

    def test_submerges_at_exactly_dig_range_tiles(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, pa, _mv = self._parts(dig)
        scene.update(0.0)                       # on_spawn takes the claim
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        self.assertEqual(burrow.state, BURROW_WALKING)

        dist_before = None
        for _ in range(2000):
            dist_before = burrow.distance_to_target(dig, pa)
            scene.update(0.05)
            if burrow.state != BURROW_WALKING:
                break
        self.assertEqual(burrow.state, BURROW_SUBMERGED)
        self.assertEqual(dist_before, DIGGER["dig_range_tiles"])

    def test_never_submerges_on_a_tile_a_building_occupies(self):
        """A single-row board so the walk physically crosses the obstacle's
        tile (the `no_melee` regression's own technique). An UNRELATED
        `economic` building (not a "structure" hunt candidate) sits exactly
        `dig_range_tiles` from the real target — the first column the submerge
        trigger goes true. Absent the fix the Digger would submerge standing
        on it; the fix must relocate it to the nearest CLEAR tile first (col 7,
        the next tile toward the target — the ring search's first valid hit)."""
        tm, scene, occ = self._board()
        target_col = 2
        place_building(tm, tm.get(target_col, 0), "blocker", 9999, BUILD,
                       scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (target_col, 0))
        obstacle_col = target_col + DIGGER["dig_range_tiles"]
        place_building(tm, tm.get(obstacle_col, 0), "economic", 9999, BUILD,
                       scene, occ)

        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))

        sub_col = round(dig.transform.wx)
        sub_row = round(dig.transform.wy)
        self.assertNotEqual(sub_col, obstacle_col)
        self.assertIsNone(tm.get(sub_col, sub_row).occupant)
        self.assertEqual((sub_col, sub_row), (obstacle_col - 1, 0))
        self.assertAlmostEqual(burrow.start_wx, obstacle_col - 1)
        self.assertAlmostEqual(burrow.start_wy, 0.0)

    def test_untargetable_and_undamageable_while_submerged(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, _pa, _mv = self._parts(dig)
        scene.update(0.0)
        # Placed AFTER the claim so it cannot steal the target; it sits inside
        # the stretch the Digger travels, so a targetable Digger WOULD be shot.
        place_building(tm, tm.get(6, 0), "defence", 9999, BUILD, scene, occ)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))

        self.assertFalse(dig.targetable)
        # combat.py's one target filter drops it — the Boss `targetable`
        # contract, reused verbatim.
        self.assertNotIn(dig, [e for e in scene.by_tag("enemy")
                               if e.alive and getattr(e, "targetable", True)])
        hp0 = dig.get_component(Health).hp
        for _ in range(40):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD, VFX)
            if burrow.state != BURROW_SUBMERGED:
                break
        self.assertEqual(dig.get_component(Health).hp, hp0)

    def test_emerges_on_the_target_and_deals_one_dmg_hit(self):
        tm, scene, occ = self._board()
        blocker, _c = place_building(tm, tm.get(2, 0), "blocker", 9999,
                                     BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, _pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))

        rs = blocker.get_component(RoundStats)
        self.assertEqual(rs.dmg_taken_this_round, DIG0["dmg"])
        self.assertEqual(blocker.get_component(Health).hp,
                         max(0, blocker.get_component(Health).max_hp
                             - DIG0["dmg"]))
        # Snapped onto the target's tile, visible and targetable again.
        self.assertAlmostEqual(dig.transform.wx, 2.0)
        self.assertAlmostEqual(dig.transform.wy, 0.0)
        self.assertTrue(dig.targetable)
        self.assertFalse(dig.get_component(PathAgent).frozen)
        # Exactly ONE hit — the eruption, not a melee clock.
        scene.update(0.05)
        self.assertEqual(rs.dmg_taken_this_round, DIG0["dmg"])

    def test_interrupted_dig_emerges_at_once_deals_nothing_and_retargets(self):
        """D5 — the target dies to something else mid-dig. The Digger's NEXT
        move (after standing for `emerge_cooldown`, per the player-feedback
        rework) commits to the only survivor and dives straight back down —
        it never walks overground again; `BURROW_WALKING` is spawn-only from
        here on."""
        tm, scene, occ = self._board()
        blocker, _c = place_building(tm, tm.get(2, 0), "blocker", 9999,
                                     BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, pa, mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        # Placed AFTER the claim: it is the ONLY thing left to re-target to
        # once the committed victim dies (col 14 is nearer to the spawn than
        # col 2, so placing it first would simply have been claimed instead).
        other, _c2 = place_building(tm, tm.get(14, 0), "blocker", 9999,
                                    BUILD, scene, occ)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))

        timer_left = burrow.dig_timer
        self.assertGreater(timer_left, 0.0)     # genuinely mid-dig
        where = (dig.transform.wx, dig.transform.wy)
        blocker.get_component(Health).hp = 0    # killed by "something else"
        taken = blocker.get_component(RoundStats).dmg_taken_this_round

        scene.update(0.05)
        self.assertEqual(burrow.state, BURROW_EMERGE)          # immediately
        self.assertLess(burrow.dig_timer, timer_left)
        self.assertEqual(blocker.get_component(RoundStats).dmg_taken_this_round,
                         taken)                                # NO damage
        self.assertNotAlmostEqual(dig.transform.wx, 2.0)       # where it was
        self.assertAlmostEqual(dig.transform.wx, where[0])
        self.assertTrue(dig.targetable)
        self.assertGreater(burrow.cooldown_remaining, 0.0)

        # It stands — no instant, silent re-path (the whole bug this fixes).
        for _ in range(int(burrow.emerge_cooldown / 0.05) - 1):
            scene.update(0.05)
            self.assertEqual(burrow.state, BURROW_EMERGE)
        # Once the stand drains it commits and dives — never BURROW_WALKING.
        self.assertTrue(self._run_until(
            scene, dig, lambda: pa.target_col == 14, limit=200))
        self.assertNotEqual(burrow.state, BURROW_WALKING)
        self.assertEqual(mv.waypoints, [])

        self.assertTrue(self._run_until(
            scene, dig,
            lambda: other.get_component(RoundStats).dmg_taken_this_round > 0,
            limit=200))
        self.assertEqual(blocker.get_component(RoundStats).dmg_taken_this_round,
                         taken)                                 # still untouched

    def test_stands_down_when_nothing_is_left_to_claim(self):
        """No structure after exclusion ⇒ idle and harmless, NEVER a walk at
        the hole (the base fallback inside the hunt query must not leak).
        Standing down still goes through the post-stand decision, same as
        any other re-target — it just finds nothing."""
        tm, scene, occ = self._board()
        blocker, _c = place_building(tm, tm.get(2, 0), "blocker", 9999,
                                     BUILD, scene, occ)
        dig = self._digger(scene, tm, 10)
        burrow, pa, mv = self._parts(dig)
        scene.update(0.0)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))
        blocker.get_component(Health).hp = 0
        scene.update(0.05)                      # EMERGE
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_WALKING, limit=200))

        self.assertEqual((pa.target_col, pa.target_row), (-1, -1))
        self.assertEqual(mv.waypoints, [])
        self.assertFalse(pa.goal_is_base)
        base_hp = tm.get(0, 0).occupant.get_component(Health).hp
        for _ in range(200):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD, VFX)
        self.assertFalse(pa.reached_base)
        self.assertEqual(tm.get(0, 0).occupant.get_component(Health).hp,
                         base_hp)

    # -- the exclusive claim ------------------------------------------------

    def test_two_diggers_never_claim_the_same_building(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        place_building(tm, tm.get(4, 0), "blocker", 9999, BUILD, scene, occ)
        a = self._digger(scene, tm, 12)
        b = self._digger(scene, tm, 13)
        scene.update(0.0)                       # both on_spawn, in spawn order

        claims = [(d.get_component(PathAgent).target_col,
                   d.get_component(PathAgent).target_row) for d in (a, b)]
        self.assertEqual(sorted(claims), [(2, 0), (4, 0)])

    def test_a_third_digger_with_only_two_buildings_stands_down(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        place_building(tm, tm.get(4, 0), "blocker", 9999, BUILD, scene, occ)
        diggers = [self._digger(scene, tm, 10 + i) for i in range(3)]
        scene.update(0.0)

        claims = [(d.get_component(PathAgent).target_col,
                   d.get_component(PathAgent).target_row) for d in diggers]
        self.assertEqual(sorted(claims), [(-1, -1), (2, 0), (4, 0)])
        # No two live claims are ever equal — the whole invariant.
        live = [c for c in claims if c != (-1, -1)]
        self.assertEqual(len(live), len(set(live)))

    def test_a_dead_diggers_claim_is_released(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        a = self._digger(scene, tm, 12)
        scene.update(0.0)
        self.assertEqual(a.get_component(PathAgent).target_col, 2)
        scene.despawn(a)
        scene.update(0.0)
        b = self._digger(scene, tm, 13)
        scene.update(0.0)
        self.assertEqual(b.get_component(PathAgent).target_col, 2)

    def test_the_spawner_wires_the_scene_transient(self):
        """`Enemy._scene` is what the claim scan and the dirt pile ride on;
        it exists only because the Spawner sets it at both spawn sites."""
        tm = synth(["bbs"])
        scene = Scene()
        sp = Spawner()
        sp.begin_round(1, tm, ENEM, rng=FakeRng())
        for _ in range(400):
            sp.update(1.0, scene)
            if scene.queued_by_tag("enemy"):
                break
        spawned = scene.queued_by_tag("enemy")
        self.assertTrue(spawned)
        for e in spawned:
            self.assertIs(e._scene, scene)

    # -- no_melee ------------------------------------------------------------

    def test_never_halts_on_an_unrelated_building_en_route(self):
        """The soft-lock regression: a Digger routed straight THROUGH a
        non-structure building must walk on past it, dealing it nothing."""
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        bystander, _c = place_building(tm, tm.get(10, 0), "economic", 9999,
                                       BUILD, scene, occ)
        dig = self._digger(scene, tm, 14)
        burrow, pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        # One row: the route physically runs over the bystander's tile.
        self.assertIn([10.0, 0.0], dig.get_component(Movement).waypoints)

        ever_blocked = False
        for _ in range(2000):
            scene.update(0.05)
            ever_blocked = ever_blocked or pa.blocked
            if burrow.state == BURROW_SUBMERGED:
                break
        self.assertEqual(burrow.state, BURROW_SUBMERGED)
        self.assertFalse(ever_blocked)
        self.assertEqual(
            bystander.get_component(RoundStats).dmg_taken_this_round, 0)
        self.assertEqual(bystander.get_component(Health).hp,
                         bystander.get_component(Health).max_hp)

    def test_a_walker_on_the_same_board_still_halts_and_attacks(self):
        """The other half of the regression: `no_melee` is DEFAULT-OFF, so the
        halt-and-attack model is untouched for everything else."""
        tm, scene, occ = self._board()
        bystander, _c = place_building(tm, tm.get(10, 0), "economic", 9999,
                                       BUILD, scene, occ)
        walker = create_enemy("standard", 12, 0, ENEM, tm, 0)
        scene.spawn(walker)
        pa = walker.get_component(PathAgent)
        self.assertTrue(self._run_until(scene, walker, lambda: pa.blocked))
        self.assertGreater(
            bystander.get_component(RoundStats).dmg_taken_this_round, 0)

    # -- the dirt pile -------------------------------------------------------

    def test_submerging_drops_a_dirt_pile_decal_no_gameplay_query_can_see(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, _pa, _mv = self._parts(dig)
        scene.update(0.0)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))
        scene.update(0.0)                       # flush the spawn queue

        piles = scene.by_tag("dirt_pile")
        self.assertEqual(len(piles), 1)
        pile = piles[0]
        self.assertIsInstance(pile, DirtPile)
        self.assertNotIn("enemy", pile.tags)
        self.assertNotIn(pile, scene.by_tag("enemy"))
        self.assertIsNone(pile.get_component(Health))
        self.assertIsNone(pile.get_component(PathAgent))
        self.assertEqual(pile.get_component(SpriteAnimator).slot_key,
                         DIRT_PILE_SLOT)
        # It lives exactly as long as the dig and then removes itself.
        life = pile.get_component(DirtPileFade).life_ms
        self.assertAlmostEqual(life, burrow.dig_duration * 1000.0, places=3)
        for _ in range(int(burrow.dig_duration / 0.05) + 4):
            scene.update(0.05)
        self.assertEqual(scene.by_tag("dirt_pile"), [])

    # -- visibility while submerged ------------------------------------------

    def test_hidden_while_submerged_visible_otherwise(self):
        tm, scene, occ = self._board()
        place_building(tm, tm.get(2, 0), "blocker", 9999, BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, _pa, _mv = self._parts(dig)
        anim = dig.get_component(SpriteAnimator)
        scene.update(0.0)
        self.assertTrue(anim.visible)                    # walking: visible
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED))
        self.assertFalse(anim.visible)                    # submerged: hidden
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))
        self.assertTrue(anim.visible)                     # emerged: visible
        # It stays visible for the WHOLE stand, not just the entry frame —
        # the "stand there for a duration" player-feedback beat.
        for _ in range(int(burrow.emerge_cooldown / 0.05) - 1):
            scene.update(0.05)
            self.assertEqual(burrow.state, BURROW_EMERGE)
            self.assertTrue(anim.visible)

    # -- the emerge cooldown --------------------------------------------------

    def test_emerge_cooldown_delays_resubmerging_at_a_new_in_range_target(self):
        """The Digger (spawned at col 12) claims the NEARER building first -
        col 6, not col 2 - which dies to the eruption (500 hp vs 900 dmg at
        this fixture). The survivor at col 2 is already within
        `dig_range_tiles` of where it now stands (|6-2|=4 <= 6) — it must
        NOT dive back down the instant it strikes; `emerge_cooldown` holds
        the stand for real time first (the player-feedback fix: it always
        stands before its next move, never an instant silent re-dive), and
        when it does dive it commits and goes straight back down — it never
        walks there overground."""
        tm, scene, occ = self._board()
        far_building, _c = place_building(tm, tm.get(2, 0), "blocker", 9999,
                                          BUILD, scene, occ)
        near_building, _c2 = place_building(tm, tm.get(6, 0), "blocker", 9999,
                                            BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, pa, mv = self._parts(dig)
        self.assertEqual(burrow.emerge_cooldown, DIGGER["emerge_cooldown"])
        self.assertGreater(burrow.emerge_cooldown, 0.0)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (6, 0))   # nearer
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))
        self.assertLessEqual(near_building.get_component(Health).hp, 0)
        self.assertGreater(burrow.cooldown_remaining, 0.0)

        # It stands — never dives while cooldown_remaining is still
        # draining, even though the survivor is already within range.
        for _ in range(int(burrow.emerge_cooldown / 0.05) - 1):
            scene.update(0.05)
            self.assertEqual(burrow.state, BURROW_EMERGE)
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED, limit=5))
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        self.assertGreater(far_building.get_component(Health).hp, 0)
        self.assertEqual(mv.waypoints, [])   # never walked — dove straight down

    def test_emerge_cooldown_zero_is_a_noop(self):
        """Every OTHER type's BurrowAgent-less path is untouched, and a
        hand-built BurrowAgent with no balancing behind it defaults to 0 -
        byte-identical to submerging the instant it is back in range."""
        burrow = BurrowAgent()
        self.assertEqual(burrow.emerge_cooldown, 0.0)
        self.assertEqual(burrow.cooldown_remaining, 0.0)

    # -- the knight-hop search -------------------------------------------------

    def test_search_hop_lands_on_the_knight_offset_closest_to_the_target(self):
        """After its first strike, with nothing left within `dig_range_tiles`,
        the Digger dives a knight's-move (`dig_hop_long_tiles`/
        `_short_tiles`) toward the nearest remaining unclaimed structure —
        whichever of the (up to) 8 sign/axis offsets lands closest to it —
        deals NO damage on that hop, and surfaces to stand again before its
        next move. A 7-row board (needed for a row-offset hop; this class's
        usual one-row board can never fit one — see the stand-down test
        below for that edge)."""
        rows = ["b" * 40 for _ in range(7)]
        tm = synth(rows, base=(0, 3))
        scene, occ = Scene(), TileOccupancy()
        attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE),
                    scene, occ)
        near, _c = place_building(tm, tm.get(10, 3), "blocker", 9999,
                                  BUILD, scene, occ)
        dig = create_enemy("digger", 20, 3, ENEM, tm, 0)
        dig._scene = scene
        scene.spawn(dig)
        burrow, pa, mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (10, 3))
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))
        self.assertLessEqual(near.get_component(Health).hp, 0)
        self.assertAlmostEqual(dig.transform.wx, 10.0)
        self.assertAlmostEqual(dig.transform.wy, 3.0)

        # Placed only NOW — it cannot have influenced the first claim — well
        # outside dig_range_tiles(6) of (10, 3): Chebyshev distance 20.
        far, _c2 = place_building(tm, tm.get(30, 5), "blocker", 9999,
                                  BUILD, scene, occ)
        far_taken = far.get_component(RoundStats).dmg_taken_this_round

        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_SUBMERGED, limit=200))
        self.assertEqual((pa.target_col, pa.target_row), (-1, -1))  # blind hop
        # Exactly the knight offset closest to (30, 5) from (10, 3): (+3, +1)
        # — hand-computed, the unique minimum among all 8 candidates.
        self.assertEqual((burrow.dest_col, burrow.dest_row), (13, 4))
        self.assertAlmostEqual(burrow.dig_duration,
                               burrow.dig_hop_long_tiles / burrow.dig_speed)
        self.assertEqual(mv.waypoints, [])

        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE, limit=200))
        self.assertAlmostEqual(dig.transform.wx, 13.0)
        self.assertAlmostEqual(dig.transform.wy, 4.0)
        self.assertEqual(far.get_component(RoundStats).dmg_taken_this_round,
                         far_taken)                       # the hop dealt nothing
        self.assertTrue(dig.get_component(SpriteAnimator).visible)  # standing

    def test_stands_down_when_every_knight_hop_falls_off_a_one_row_board(self):
        """On this class's usual ONE-ROW board every knight offset needs a
        row shift that does not exist — so once the only claimed target is
        struck and a second, out-of-range structure is the sole survivor,
        the Digger cannot hop toward it at all and stands down exactly like
        the no-candidates-left case."""
        tm, scene, occ = self._board()
        near, _c = place_building(tm, tm.get(10, 0), "blocker", 9999,
                                  BUILD, scene, occ)
        dig = self._digger(scene, tm, 12)
        burrow, pa, mv = self._parts(dig)
        scene.update(0.0)
        self.assertEqual((pa.target_col, pa.target_row), (10, 0))
        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_EMERGE))
        # Placed only NOW, at Chebyshev distance 9 (> dig_range_tiles 6).
        far, _c2 = place_building(tm, tm.get(1, 0), "blocker", 9999,
                                  BUILD, scene, occ)

        self.assertTrue(self._run_until(
            scene, dig, lambda: burrow.state == BURROW_WALKING, limit=200))
        self.assertEqual((pa.target_col, pa.target_row), (-1, -1))
        self.assertEqual(mv.waypoints, [])
        self.assertGreater(far.get_component(Health).hp, 0)   # never reached

    # -- composition ---------------------------------------------------------

    def test_the_wave_carries_diggers_from_its_start_round_on(self):
        """Non-boss rounds only — a boss round composes from
        `Boss.round_counts`, which carries no digger key (see the next test).

        `start_round` is READ, never pinned. This used to open with
        `assertEqual(DIGGER["start_round"], 35)` and sweep a hardcoded round
        list; retuning the type to 32 in the editor turned it red while the
        composition it actually tests was still perfectly correct. Balancing is
        the designer's to move (`game/CLAUDE.md`: "retune freely") — what must
        hold is that composition AGREES with whatever the number is."""
        tm = synth(["bbs"])
        sp = Spawner()
        start = DIGGER["start_round"]
        # A sweep anchored on `start`, not on a literal: well before it, the
        # boundary either side, and a spread of later rounds.
        rounds = (1, start // 2, start - 1, start, start + 1,
                  start + 4, start + 10, start + 20)
        for rnd in rounds:
            with self.subTest(round=rnd):
                sp.begin_round(rnd, tm, ENEM, rng=random.Random(7))
                got = len([e for _, e in sp.pending() if e == "digger"])
                self.assertEqual(got, expected_count("Digger", rnd))
        # `start_round` really is the first wave that carries one.
        self.assertGreaterEqual(expected_count("Digger", start), 1)
        self.assertEqual(expected_count("Digger", start - 1), 0)

    def test_no_diggers_on_a_boss_round(self):
        """The SAME deliberate rule the Formation follows: `_boss_round`
        composes from `Boss.round_counts`, a `$defs/spawn_counts` table shared
        with every `death_spawn.spawns` row, so a `digger` key there would land
        on all 14 committed rows. One line into `_boss_round`'s `rest` if it is
        ever wanted — never by accident."""
        tm = synth(["bbs"])
        sp = Spawner()
        for rnd in (40, 50, 60):
            with self.subTest(round=rnd):
                self.assertGreater(expected_count("Digger", rnd), 0)
                sp.begin_round(rnd, tm, ENEM, rng=random.Random(7))
                self.assertEqual(
                    [e for _, e in sp.pending() if e == "digger"], [])

    def test_diggers_are_body_mixed_never_queue_leading(self):
        tm = TestSpawnTilesAreSpawningOnly._tm()
        sp = Spawner()
        sp.begin_round(35, tm, ENEM, rng=random.Random(3))
        etypes = [e for _, e in sp.pending()]
        self.assertIn("digger", etypes)
        self.assertNotEqual(etypes[0], "digger")


SNIPER = ENEM["EnemyTypes"]["Sniper"]
STAND_OFF = SNIPER["stand_off_range"]
DT = 0.05


class SniperCase(unittest.TestCase):
    """Shared board for the NE-1 stand-off fixtures.

    One row, base at (0,0), the last two tiles the spawn zone. Defence
    buildings go where each test wants them; the sniper is created on the far
    spawn tile and hunts them (`hunts: "defence"`, widened by NE-0).
    """

    ROW = "bbbbbbbss"      # cols 0..6 buildable, 7..8 spawning
    SPAWN_COL = 8

    def board(self, *defence_cols):
        tm = synth([self.ROW])
        scene, occ = Scene(), TileOccupancy()
        built = {}
        for col in defence_cols:
            b, _c = place_building(tm, tm.get(col, 0), "defence", 999999,
                                   BUILD, scene, occ)
            # Keep every target standing for as long as the test wants it:
            # these fixtures are about the STAND-OFF, not about how many shots
            # a shipped Defender survives.
            b.get_component(Health).hp = 10 ** 7
            b.get_component(Health).max_hp = 10 ** 7
            built[col] = b
        return tm, scene, built

    def sniper(self, tm, scene, era=0, col=None):
        e = create_enemy("sniper", self.SPAWN_COL if col is None else col, 0,
                         ENEM, tm, era)
        scene.spawn(e)
        scene.update(0.0)          # apply the spawn + on_spawn pathing
        return e

    @staticmethod
    def pa(enemy):
        return enemy.get_component(PathAgent)


class TestSniper(SniperCase):
    """NE-1 — the first RANGED enemy: it halts `stand_off_range` tiles short of
    its committed target and fires from there, never closing to melee."""

    def test_class_attrs_and_registration(self):
        from game.enemies.enemy import ENEMY_CLASSES
        self.assertIs(ENEMY_CLASSES["sniper"], Sniper)
        self.assertEqual(Sniper.ETYPE, "sniper")
        self.assertEqual(Sniper.REGISTRY_GROUP, "Sniper")
        self.assertEqual(Sniper.DEFAULT_SLOT, "sniper_stage_1")
        self.assertEqual(Sniper.STAT_SUBTREE, ("Sniper",))
        # A normal era-shaped type: the base resolvers do everything but the
        # ONE new seam (the Boss keeps the only `_resolve_stats` override).
        for name in ("_resolve_stats", "_resolve_era", "on_spawn",
                     "resolve_fit", "__init__"):
            self.assertIsNone(Sniper.__dict__.get(name),
                              f"Sniper must not override {name}")

    def test_stats_and_stand_off_come_from_its_own_block(self):
        sn0 = era_stats("Sniper")
        tm, scene, _ = self.board(2)
        s = self.sniper(tm, scene)
        self.assertIsInstance(s, Sniper)
        self.assertEqual(s.get_component(Health).hp, sn0["hp"])
        self.assertEqual(s.dmg, sn0["dmg"])
        self.assertAlmostEqual(s.get_component(Movement).speed,
                               sn0["move_speed"])
        self.assertNotEqual(sn0["hp"], STD0["hp"])       # the fixture is real
        self.assertEqual(self.pa(s).hunt, "defence")
        self.assertEqual(self.pa(s).stand_off_range, STAND_OFF)
        # The stand-off leaf reaches PathAgent through the ONE seam, and is
        # flat/per-type (D10) — never an era row.
        self.assertEqual(Sniper.resolve_stand_off_range(SNIPER), STAND_OFF)
        for row in SNIPER["eras"]:
            self.assertNotIn("stand_off_range", row)
            self.assertNotIn("stand_off_range", row["stats"])

    def test_halts_at_exactly_chebyshev_stand_off_and_never_blocks(self):
        tm, scene, _built = self.board(2)
        s = self.sniper(tm, scene)
        pa = self.pa(s)
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        self.assertFalse(pa.in_range)                     # 8 -> 2 is 6 tiles
        for _ in range(600):
            scene.update(DT)
            # THE claim: it never reaches the melee state on the way in.
            self.assertFalse(pa.blocked,
                             "a stand-off unit must halt on geometry, never "
                             "by being physically blocked")
            if pa.in_range:
                break
        else:
            self.fail("the sniper never came into range")
        col = round(s.transform.wx)
        self.assertEqual(col - pa.target_col, STAND_OFF)
        self.assertEqual(s.get_component(Movement).speed, 0.0)
        self.assertFalse(s.get_component(Movement).arrived)
        # And it STAYS there — no creep toward the target once halted.
        for _ in range(200):
            scene.update(DT)
        self.assertEqual(round(s.transform.wx), col)
        self.assertTrue(pa.in_range)
        self.assertFalse(pa.blocked)

    def test_fires_on_its_attack_speed_cadence_once_in_range(self):
        sn0 = era_stats("Sniper")
        # Spawn already inside the stand-off: target at 6, spawn at 8.
        tm, scene, built = self.board(6)
        s = self.sniper(tm, scene)
        rs = built[6].get_component(RoundStats)
        # It spawns already in range, and `cooldown` starts at 0 — so the very
        # first shot lands on the setup frame, exactly as a melee enemy's does
        # the instant it stops. That IS the "no adjacency requirement" claim.
        self.assertTrue(self.pa(s).in_range)
        self.assertEqual(rs.dmg_taken_this_round, sn0["dmg"])

        hits, t, last = [0.0], 0.0, rs.dmg_taken_this_round
        for _ in range(400):                # 20 s at DT
            scene.update(DT)
            t += DT
            now = rs.dmg_taken_this_round
            if now > last:
                self.assertEqual(now - last, sn0["dmg"])   # exact ledger
                hits.append(t)
                last = now
        self.assertTrue(self.pa(s).in_range)
        self.assertFalse(self.pa(s).blocked)
        self.assertGreaterEqual(len(hits), 6)
        for a, b in zip(hits, hits[1:]):
            self.assertAlmostEqual(b - a, sn0["attack_speed"], delta=DT + 1e-9)
        self.assertEqual(rs.dmg_taken_this_round, len(hits) * sn0["dmg"])

    def test_retargets_when_its_victim_dies(self):
        """The existing `repath_on_kill` dead-target watch already covers the
        in-range case — it is gated on `not blocked`, and a stand-off unit is
        never blocked. Pinned here because NE-1 relies on that and adds no
        second watch."""
        tm, scene, built = self.board(2, 6)
        s = self.sniper(tm, scene)
        pa = self.pa(s)
        scene.update(DT)
        self.assertTrue(pa.in_range)                       # 8 -> 6 is 2
        self.assertEqual((pa.target_col, pa.target_row), (6, 0))
        self.assertTrue(pa.repath_on_kill)
        far_rs = built[2].get_component(RoundStats)
        self.assertEqual(far_rs.dmg_taken_this_round, 0)

        built[6].get_component(Health).hp = 0
        self.assertFalse(built[6].alive)
        scene.update(DT)
        # Re-committed to the survivor, and NOT still flagged in-range: the
        # dead-target watch re-paths and returns, so if `_repath` did not drop
        # the flag itself the sniper would land one free shot on a building
        # four tiles outside its stand-off. Regression pin.
        self.assertEqual((pa.target_col, pa.target_row), (2, 0))
        self.assertFalse(pa.in_range)
        self.assertEqual(far_rs.dmg_taken_this_round, 0)
        scene.update(DT)                                   # and it walks on
        self.assertGreater(s.get_component(Movement).speed, 0.0)

        rs = far_rs
        for _ in range(600):
            scene.update(DT)
            if pa.in_range:
                break
        else:
            self.fail("the sniper never re-engaged the surviving building")
        self.assertEqual(round(s.transform.wx) - 2, STAND_OFF)
        self.assertFalse(pa.blocked)
        # The cooldown SURVIVES the walk (EnemyCombat does not tick while out
        # of range), so re-engaging costs a full `attack_speed` — it does not
        # refund a shot for having changed target.
        self.assertEqual(rs.dmg_taken_this_round, 0)
        for _ in range(int(era_stats("Sniper")["attack_speed"] / DT) + 4):
            scene.update(DT)
        self.assertEqual(rs.dmg_taken_this_round, era_stats("Sniper")["dmg"])

    def test_round_26_ledger_on_the_era_2_row(self):
        """The scripted-round HP ledger: round 26 is the Sniper's first, era 2,
        and its shots are hand-computable straight out of `data/`."""
        rnd = SNIPER["start_round"]
        era = max(0, (rnd - 1) // RPE)
        self.assertEqual(era, 2)
        sn = era_stats("Sniper", era)

        tm, scene, built = self.board(6)
        s = self.sniper(tm, scene, era=era)
        self.assertEqual(s.get_component(Health).hp, sn["hp"])
        self.assertEqual(s.dmg, sn["dmg"])

        rs = built[6].get_component(RoundStats)
        shots, hits, t, last = 5, [0.0], 0.0, rs.dmg_taken_this_round
        self.assertEqual(last, sn["dmg"])       # shot 1, on the setup frame
        while len(hits) < shots and t < 60.0:
            scene.update(DT)
            t += DT
            now = rs.dmg_taken_this_round
            if now > last:
                self.assertEqual(now - last, sn["dmg"])
                hits.append(t)
                last = now
        self.assertEqual(len(hits), shots)
        self.assertEqual(rs.dmg_taken_this_round, shots * sn["dmg"])
        self.assertEqual(built[6].get_component(Health).hp,
                         10 ** 7 - shots * sn["dmg"])
        self.assertAlmostEqual(hits[-1], (shots - 1) * sn["attack_speed"],
                               delta=shots * DT)

    def test_wave_composition_starts_at_its_start_round(self):
        tm = synth(["bbs"])
        sp = Spawner()
        for rnd in (1, 14, 25, 26, 28, 31, 41):
            with self.subTest(round=rnd):
                sp.begin_round(rnd, tm, ENEM, rng=random.Random(7))
                queued = [e for _t, e in sp.pending() if e == "sniper"]
                self.assertEqual(len(queued), expected_count("Sniper", rnd))
        # Below start_round it draws nothing at all, so every pre-NE-1 wave is
        # byte-identical (the `_commander_group`-is-last rule, again).
        self.assertEqual(expected_count("Sniper", 25), 0)
        self.assertEqual(expected_count("Sniper", 26), 1)

    def test_never_leads_the_queue_and_never_joins_a_boss_round(self):
        tm = synth(["bbs"])
        sp = Spawner()
        sp.begin_round(41, tm, ENEM, rng=random.Random(3))   # era 4, non-boss
        etypes = [et for _t, et, _d in sp._queue]
        self.assertGreater(etypes.count("sniper"), 0)
        self.assertNotEqual(etypes[0], "sniper")             # body-mixed
        boss_round = SCALE["boss_round_in_era"] + 4 * RPE    # era 4's boss
        sp.begin_round(boss_round, tm, ENEM, rng=random.Random(3))
        self.assertNotIn("sniper", [et for _t, et, _d in sp._queue])


class TestStandOffIsOffForEveryOtherType(SniperCase):
    """`PathAgent` is shared by EVERY enemy type, so NE-1's two new fields are
    pinned default-off here: nothing but the Sniper may change behaviour."""

    OTHERS = ("standard", "raider", "siege", "formation", "commander", "boss")

    def test_every_other_type_ships_stand_off_range_zero(self):
        tm = synth(["bbbs"])
        for etype in self.OTHERS:
            with self.subTest(etype=etype):
                e = create_enemy(etype, 3, 0, ENEM, tm)
                pa = e.get_component(PathAgent)
                self.assertEqual(pa.stand_off_range, 0)
                self.assertFalse(pa.in_range)

    def test_the_seam_returns_zero_for_every_class_but_the_sniper(self):
        for cls in (Enemy, Raider, SiegeCannon, Formation, Commander, Boss):
            block = ENEM["EnemyTypes"]
            for seg in cls.STAT_SUBTREE:
                block = block[seg]
            with self.subTest(cls=cls.__name__):
                self.assertEqual(cls.resolve_stand_off_range(block), 0)
                if cls is not Enemy:      # Enemy DEFINES the seam, at 0
                    self.assertIsNone(
                        cls.__dict__.get("resolve_stand_off_range"),
                        "only Sniper may override the NE-1 seam")
                # The leaf lives ONLY on blocks that have the mechanic — that
                # is the whole point of routing it through a classmethod.
                self.assertNotIn("stand_off_range", block)

    def test_the_melee_block_and_attack_path_is_unchanged(self):
        """The pre-NE-1 behaviour, re-asserted with the new flag in the frame:
        a walker still stops ON CONTACT, sets `blocked` (never `in_range`) and
        damages what blocks it."""
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
        self.assertFalse(pa.in_range)
        self.assertIs(pa._target, blocker)
        self.assertFalse(pa.reached_base)
        self.assertGreaterEqual(
            blocker.get_component(RoundStats).dmg_taken_this_round, e.dmg)


DRUM = ENEM["EnemyTypes"]["Drummer"]


class TestDrummer(unittest.TestCase):
    """NE-3 — the game's FIRST buff/aura mechanism, so these pin the model
    itself and not just one enemy type: additive per-source stacking, the
    D6 heal-on-apply / shrink-and-clamp-on-decay hp rule, and the per-source
    4-second decay clock that starts the frame a Drummer stops sustaining.

    Board is one row, base at (0, 0): b b c c c c s s."""

    ROWS = ["bbccccss"]

    def _board(self):
        return synth(self.ROWS), Scene()

    def _spawn(self, scene, tm, etype, col, row, era=0, pos=1):
        """Construct + spawn ONE enemy, wiring the scene by hand exactly the
        way ``Spawner._attach_scene`` does for a real wave."""
        e = create_enemy(etype, col, row, ENEM, tm, era, None, None, pos)
        e._scene = scene
        scene.spawn(e)
        return e

    @staticmethod
    def _settle(scene, times=2):
        """Two zero-dt frames. Objects update in SPAWN order, so a Drummer
        spawned after the unit it buffs applies its aura only AFTER that
        unit's own PathAgent has already written this frame's move speed —
        the second frame is what makes the speed observable. Zero dt so
        nothing walks and no decay clock moves."""
        for _ in range(times):
            scene.update(0.0)

    @staticmethod
    def _freeze(*enemies):
        """Drop the waypoints so nothing walks while the decay clock runs:
        ``PathAgent.update`` returns early with no path, so tiles stay put
        and only ``BuffState``/``DrummerAura`` are exercised."""
        for e in enemies:
            mv = e.get_component(Movement)
            mv.waypoints = []
            mv.speed = 0.0

    @staticmethod
    def _step(scene, seconds, dt=0.25):
        """``seconds`` of scene time in exact-binary 0.25s frames — the decay
        boundary has to land on a frame edge, not inside float drift."""
        for _ in range(round(seconds / dt)):
            scene.update(dt)

    # -- the type itself ---------------------------------------------------

    def test_class_attrs_and_registration(self):
        self.assertEqual(Drummer.ETYPE, "drummer")
        self.assertEqual(Drummer.REGISTRY_GROUP, "Drummer")
        self.assertEqual(Drummer.DEFAULT_SLOT, "drummer_stage_1")
        self.assertEqual(Drummer.STAT_SUBTREE, ("Drummer",))
        self.assertIs(ENEMY_CLASSES["drummer"], Drummer)
        # A walker's march, not a hunter's: no repath_on_kill, no goal set.
        self.assertEqual(DRUM["hunts"], "base")
        # The fit pair is PER-ERA for every type now, and the Drummer's
        # "slightly taller" 1.15 must hold in EVERY row (it is the type's
        # look, not an era's) — a row that lost it would draw walker-sized.
        for row in DRUM["eras"]:
            self.assertEqual(row["footprint"], 1)
            self.assertGreater(row["sprite_scale"], 1.0)
        # No stat override (the Commander's D8 rule): the base
        # STAT_SUBTREE-driven resolver must read the Drummer's own era rows.
        self.assertIsNone(Drummer.__dict__.get("_resolve_stats"))
        tm, _scene = self._board()
        d = create_enemy("drummer", 3, 0, ENEM, tm)
        drum0 = era_stats("Drummer")
        self.assertEqual(d.get_component(Health).hp, drum0["hp"])
        self.assertEqual(d.get_component(EnemyCombat).dmg, drum0["dmg"])
        self.assertNotEqual(drum0["hp"], STD0["hp"])    # the fixture is real
        self.assertEqual(d.get_component(PathAgent).hunt, "base")
        aura = d.get_component(DrummerAura)
        self.assertEqual(aura.support_range, DRUM["support_range"])
        self.assertEqual(aura.hp_increase, DRUM["hp_increase"])

    def test_every_enemy_type_carries_the_inert_buff_ledger(self):
        """`BuffState` is on EVERY type, not just the Drummer's targets —
        that is what lets a future buff source aim at anything."""
        tm, _scene = self._board()
        for etype in ENEMY_CLASSES:
            with self.subTest(etype=etype):
                e = create_enemy(etype, 3, 0, ENEM, tm)
                buffs = e.get_component(BuffState)
                self.assertIsNotNone(buffs)
                self.assertEqual(buffs.sources, {})    # inert as constructed
        # And only the Drummer carries the aura.
        self.assertIsNone(
            create_enemy("standard", 3, 0, ENEM, tm).get_component(DrummerAura))

    # -- one Drummer -------------------------------------------------------

    def test_one_drummer_buffs_hp_dmg_move_speed_and_attack_speed(self):
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0)
        self._settle(scene)
        health = walker.get_component(Health)
        combat = walker.get_component(EnemyCombat)
        base_max, base_dmg = health.max_hp, combat.dmg
        base_interval = combat.attack_speed
        base_speed = walker.get_component(Movement).speed
        self.assertEqual(base_max, STD0["hp"])
        self.assertAlmostEqual(base_speed, STD0["move_speed"])

        drummer = self._spawn(scene, tm, "drummer", 2, 0)   # Chebyshev 1
        self._settle(scene)

        grant = int(round(base_max * DRUM["hp_increase"]))
        self.assertGreater(grant, 0)
        # D6: max HP rises AND current HP rises with it — a real heal.
        self.assertEqual(health.max_hp, base_max + grant)
        self.assertEqual(health.hp, base_max + grant)
        self.assertEqual(
            walker.dmg, int(base_dmg * (1.0 + DRUM["dmg_increase"])))
        self.assertAlmostEqual(
            walker.get_component(Movement).speed,
            base_speed * (1.0 + DRUM["move_speed_increase"]))
        # attack_speed is an INTERVAL, so a bonus DIVIDES: more swings/sec.
        self.assertAlmostEqual(
            combat.buffed_attack_speed,
            base_interval / (1.0 + DRUM["attack_speed_increase"]))
        self.assertLess(combat.buffed_attack_speed, base_interval)
        # Keyed by the contributing Drummer, and the Drummer never buffs
        # itself.
        self.assertEqual(list(walker.get_component(BuffState).sources),
                         [drummer.id])
        self.assertEqual(drummer.get_component(BuffState).sources, {})

    def test_sustaining_a_buff_does_not_re_heal_every_frame(self):
        """The heal is applied on the transition only — a Drummer parked next
        to a damaged unit must not top it up frame after frame."""
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0)
        self._spawn(scene, tm, "drummer", 2, 0)
        self._settle(scene)
        health = walker.get_component(Health)
        health.damage(20)
        wounded = health.hp
        self._settle(scene, times=10)
        self.assertEqual(health.hp, wounded)

    # -- decay -------------------------------------------------------------

    def test_the_buff_decays_exactly_four_seconds_after_leaving_range(self):
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0)
        drummer = self._spawn(scene, tm, "drummer", 2, 0)
        self._settle(scene)
        self._freeze(walker, drummer)
        health = walker.get_component(Health)
        buffs = walker.get_component(BuffState)
        grant = int(round(STD0["hp"] * DRUM["hp_increase"]))
        self.assertEqual(health.max_hp, STD0["hp"] + grant)
        self.assertEqual(health.hp, STD0["hp"] + grant)   # at the buffed cap

        drummer.transform.wx = 7.0                        # out of range
        self._step(scene, BUFF_DECAY_SECONDS - 0.25)
        self.assertEqual(list(buffs.sources), [drummer.id],
                         "the contribution must survive its whole countdown")
        self.assertEqual(health.max_hp, STD0["hp"] + grant)

        self._step(scene, 0.25)                           # exactly 4.0s
        self.assertEqual(buffs.sources, {})
        self.assertEqual(health.max_hp, STD0["hp"])       # ceiling shrinks
        self.assertEqual(health.hp, STD0["hp"])           # D6 clamp down
        self.assertEqual(walker.dmg, walker.get_component(EnemyCombat).dmg)

    def test_a_unit_already_below_the_new_max_keeps_its_hp_on_decay(self):
        """The clamp only clamps: losing the ceiling must not also drain HP
        the unit still legitimately has."""
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0)
        drummer = self._spawn(scene, tm, "drummer", 2, 0)
        self._settle(scene)
        self._freeze(walker, drummer)
        health = walker.get_component(Health)
        health.hp = 10
        drummer.transform.wx = 7.0
        self._step(scene, BUFF_DECAY_SECONDS)
        self.assertEqual(health.max_hp, STD0["hp"])
        self.assertEqual(health.hp, 10)

    # -- two Drummers ------------------------------------------------------

    def test_two_drummers_stack_additively_and_decay_independently(self):
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0)
        self._settle(scene)
        base_speed = walker.get_component(Movement).speed
        d1 = self._spawn(scene, tm, "drummer", 2, 0)
        d2 = self._spawn(scene, tm, "drummer", 4, 0)
        self._settle(scene)

        health = walker.get_component(Health)
        combat = walker.get_component(EnemyCombat)
        buffs = walker.get_component(BuffState)
        grant = int(round(STD0["hp"] * DRUM["hp_increase"]))
        # D7: exactly TWICE one Drummer — each grant is sized off the
        # UNBUFFED max, so they add instead of compounding.
        self.assertEqual(sorted(buffs.sources), sorted([d1.id, d2.id]))
        self.assertEqual(health.max_hp, STD0["hp"] + 2 * grant)
        self.assertEqual(health.hp, STD0["hp"] + 2 * grant)
        self.assertEqual(
            walker.dmg, int(STD0["dmg"] * (1.0 + 2 * DRUM["dmg_increase"])))
        self.assertAlmostEqual(
            walker.get_component(Movement).speed,
            base_speed * (1.0 + 2 * DRUM["move_speed_increase"]))
        self.assertAlmostEqual(
            combat.buffed_attack_speed,
            combat.attack_speed / (1.0 + 2 * DRUM["attack_speed_increase"]))

        # ONE Drummer walks off. Only ITS contribution decays.
        self._freeze(walker, d1, d2)
        d1.transform.wx = 7.0
        self._step(scene, BUFF_DECAY_SECONDS)
        self.assertEqual(list(buffs.sources), [d2.id])
        self.assertEqual(health.max_hp, STD0["hp"] + grant)
        self.assertEqual(
            walker.dmg, int(STD0["dmg"] * (1.0 + DRUM["dmg_increase"])))

        # Its clock kept running for four MORE seconds and nothing else fell
        # off — d2 is still sustaining.
        self._step(scene, BUFF_DECAY_SECONDS * 2)
        self.assertEqual(list(buffs.sources), [d2.id])
        self.assertEqual(health.max_hp, STD0["hp"] + grant)

        # Now d2 leaves too.
        d2.transform.wx = 7.0
        self._step(scene, BUFF_DECAY_SECONDS)
        self.assertEqual(buffs.sources, {})
        self.assertEqual(health.max_hp, STD0["hp"])

    # -- out of range ------------------------------------------------------

    def test_an_enemy_outside_every_radius_is_completely_unaffected(self):
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 2, 0)
        self._settle(scene)
        base_speed = walker.get_component(Movement).speed
        self._spawn(scene, tm, "drummer", 5, 0)     # Chebyshev 3 > range 1
        self._settle(scene, times=6)

        health = walker.get_component(Health)
        combat = walker.get_component(EnemyCombat)
        self.assertEqual(walker.get_component(BuffState).sources, {})
        self.assertEqual((health.max_hp, health.hp), (STD0["hp"], STD0["hp"]))
        self.assertEqual(walker.dmg, combat.dmg)
        self.assertEqual(combat.buffed_attack_speed, combat.attack_speed)
        self.assertAlmostEqual(walker.get_component(Movement).speed,
                               base_speed)

    # -- the wave ----------------------------------------------------------

    def test_the_start_round_is_the_first_wave_that_carries_drummers(self):
        """`start_round` is READ, not pinned — see the Digger's twin of this
        test for why (the literal 25 went stale the day the type was retuned
        to 22, reddening a test whose subject was composition, not tuning)."""
        tm = synth(self.ROWS)
        start = DRUM["start_round"]
        for rnd in (0, 1, start // 2, start - 1):
            with self.subTest(round=rnd):
                self.assertEqual(expected_count("Drummer", rnd), 0)
                sp = Spawner()
                sp.begin_round(rnd, tm, ENEM, rng=random.Random(3))
                self.assertEqual(
                    [e for _t, e in sp.pending() if e == "drummer"], [])
        wanted = expected_count("Drummer", start)
        self.assertGreaterEqual(wanted, 1)
        sp = Spawner()
        sp.begin_round(start, tm, ENEM, rng=random.Random(3))
        drummers = [e for _t, e in sp.pending() if e == "drummer"]
        self.assertEqual(len(drummers), wanted)
        # Body-mixed, never queue-leading (a support unit ahead of the units
        # it supports buffs nothing).
        self.assertNotEqual(sp.pending()[0][1], "drummer")

    def test_round_25_ledger_a_live_wave_buffs_through_the_spawner(self):
        """The scripted round-25 HP ledger, hand-computed off era 2 (round 25
        is era (25-1)//10 == 2, position 5 — every type's `per_round` deltas
        are 0, so position does not move the numbers).

        It also proves the ONE piece of wiring a unit test could otherwise
        miss: the spawner hands each enemy the scene (`_attach_scene`), which
        is the only reason a real wave's aura can see anything at all."""
        era, pos = 2, 5
        tm, scene = self._board()
        walker = self._spawn(scene, tm, "standard", 3, 0, era, pos)
        drummer = self._spawn(scene, tm, "drummer", 2, 0, era, pos)
        self._settle(scene)

        std2, drum2 = era_stats("Standard", era), era_stats("Drummer", era)
        grant = int(round(std2["hp"] * DRUM["hp_increase"]))
        health = walker.get_component(Health)
        self.assertEqual(health.max_hp, std2["hp"] + grant)
        self.assertEqual(health.hp, std2["hp"] + grant)
        self.assertEqual(drummer.get_component(Health).hp, drum2["hp"])
        self.assertEqual(drummer.get_component(EnemyCombat).dmg, drum2["dmg"])
        self.assertEqual(
            walker.dmg, int(std2["dmg"] * (1.0 + DRUM["dmg_increase"])))
        self.assertAlmostEqual(
            walker.get_component(Movement).speed,
            std2["move_speed"] * (1.0 + DRUM["move_speed_increase"]))

        # And the real spawner path wires the scene onto every enemy it makes.
        live = Scene()
        sp = Spawner()
        sp.begin_round(25, tm, ENEM, rng=random.Random(3))
        for _ in range(4000):
            if sp.done:
                break
            sp.update(0.1, live)
        live.update(0.0)
        spawned = live.by_tag("enemy")
        self.assertTrue(spawned)
        self.assertTrue(all(getattr(e, "_scene", None) is live
                            for e in spawned))
        self.assertTrue(any(e.ETYPE == "drummer" for e in spawned))

    def test_support_range_increase_is_inert_as_shipped(self):
        """Flagged open item (NE-3): the leaf exists so the data shape is
        future-proof, but NOTHING reads it — there is deliberately no
        era-growth mechanic behind it. If this ever fails, someone wired it
        up and the plan's open question needs answering first."""
        self.assertEqual(DRUM["support_range_increase"], 0)
        self.assertNotIn("support_range_increase", DrummerAura._fields)


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
        for cls in (Enemy, Raider, SiegeCannon, Formation, Sniper, Commander,
                    Digger, Drummer, Boss):
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
