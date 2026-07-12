"""Phase 9E: enemy walker + wave spawner + combat (game/enemies).

Pure-Python, headless (no SDL) — mirrors the 9C/9D map/building tests: a synth
``TileMapDoc`` -> ``TileMap`` fixture and real balancing via ``load_balance``.
The ledger tests step a ``Scene`` at fixed dt and pin HP against the prototype's
migrated values (×10 scale).
"""
import math
import random
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.assets import load_registry
from engine.core import Health, Movement, Scene, SpriteAnimator
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.buildings.components import RoundStats
from game.core.balance import load_balance
from game.enemies import (
    Enemy, Projectile, Raider, SiegeCannon, Spawner, attack_interval,
    create_enemy, resolve_combat,
)
from game.enemies.combat import ProjectileHoming
from game.enemies.components import EnemyCombat, PathAgent
from game.map.tile_map import TileMap

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
CORE = load_balance(REPO / "data", "core")
ENEM = load_balance(REPO / "data", "enemies")

STD = ENEM["EnemyTypes"]["Standard"]
SCALE = ENEM["EnemyScaling"]


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
# Scale-tier stats resolved at spawn (prototype enemy.py:88-108)
# ---------------------------------------------------------------------------
class TestScaling(unittest.TestCase):
    def _expected(self, tier):
        tiers = SCALE["scale_tiers"]
        n = min(tier, len(tiers))
        hp = STD["hp"] + sum(tiers[i]["hp"] for i in range(n))
        dmg = STD["dmg"] + sum(tiers[i]["dmg"] for i in range(n))
        speed = STD["move_speed"] + sum(tiers[i]["speed"] for i in range(n))
        return hp, dmg, speed

    def test_stats_scale_cumulatively(self):
        tm = synth(["bbs"])
        for tier in range(0, 6):
            with self.subTest(tier=tier):
                e = Enemy(2, 0, ENEM, tm, tier=tier)
                hp, dmg, speed = self._expected(tier)
                self.assertEqual(e.get_component(Health).max_hp, hp)
                self.assertEqual(e.get_component(Health).hp, hp)
                self.assertEqual(e.dmg, dmg)
                self.assertAlmostEqual(e.get_component(Movement).speed, speed)
                self.assertEqual(
                    e.get_component(EnemyCombat).attack_speed,
                    STD["attack_speed"])

    def test_tier0_is_base_stats(self):
        tm = synth(["bbs"])
        e = Enemy(2, 0, ENEM, tm, tier=0)
        self.assertEqual(e.get_component(Health).hp, STD["hp"])
        self.assertEqual(e.dmg, STD["dmg"])

    def test_subclasses_read_own_subtree(self):
        tm = synth(["bbs"])
        r = Raider(2, 0, ENEM, tm)
        self.assertEqual(r.get_component(Health).hp,
                         ENEM["EnemyTypes"]["Raider"]["hp"])
        s = SiegeCannon(2, 0, ENEM, tm)
        self.assertEqual(s.get_component(Health).hp,
                         ENEM["EnemyTypes"]["SiegeCannon"]["hp"])

    def test_siege_scales_with_tiers_like_standard(self):
        # Prototype siege_cannon.py adds the same cumulative tier bonuses the
        # standard walker takes (10F).
        tm = synth(["bbs"])
        siege = ENEM["EnemyTypes"]["SiegeCannon"]
        tiers = SCALE["scale_tiers"]
        for tier in range(0, 6):
            with self.subTest(tier=tier):
                n = min(tier, len(tiers))
                s = SiegeCannon(2, 0, ENEM, tm, tier=tier)
                self.assertEqual(
                    s.get_component(Health).hp,
                    siege["hp"] + sum(tiers[i]["hp"] for i in range(n)))
                self.assertEqual(
                    s.dmg,
                    siege["dmg"] + sum(tiers[i]["dmg"] for i in range(n)))
                self.assertAlmostEqual(
                    s.get_component(Movement).speed,
                    siege["move_speed"]
                    + sum(tiers[i]["speed"] for i in range(n)))

    def test_raider_never_takes_tier_bonuses(self):
        # Prototype raider.py overrides the stats WITHOUT adding tier bonuses.
        tm = synth(["bbs"])
        raider = ENEM["EnemyTypes"]["Raider"]
        for tier in (0, 1, 3, 9):
            with self.subTest(tier=tier):
                r = Raider(2, 0, ENEM, tm, tier=tier)
                self.assertEqual(r.get_component(Health).hp, raider["hp"])
                self.assertEqual(r.dmg, raider["dmg"])
                self.assertAlmostEqual(r.get_component(Movement).speed,
                                       raider["move_speed"])


# ---------------------------------------------------------------------------
# Sprite variant selection (registry-group driven; random per spawn)
# ---------------------------------------------------------------------------
class TestSpriteVariants(unittest.TestCase):
    REG = load_registry(REPO / "data")

    def _slot(self, enemy):
        return enemy.get_component(SpriteAnimator).slot_key

    def test_tier_selects_the_matching_era_slot(self):
        # Walker eras 1-4 = enemy_stage_1..4; tier clamps to the last era.
        # FakeRng.choice -> first variant, so multi-variant eras resolve to _v1.
        tm = synth(["bbs"])
        cases = {0: "enemy_stage_1_v1", 1: "enemy_stage_2",
                 2: "enemy_stage_3", 3: "enemy_stage_4_v1",
                 9: "enemy_stage_4_v1"}
        for tier, slot in cases.items():
            with self.subTest(tier=tier):
                e = Enemy(2, 0, ENEM, tm, tier=tier, registry=self.REG,
                          rng=FakeRng())
                self.assertEqual(self._slot(e), slot)

    def test_random_variant_picked_at_spawn(self):
        # Era 1 has two variants; over many spawns a seeded rng yields both.
        tm = synth(["bbs"])
        rng = random.Random(1234)
        seen = {self._slot(Enemy(2, 0, ENEM, tm, tier=0, registry=self.REG,
                                 rng=rng)) for _ in range(50)}
        self.assertEqual(seen, {"enemy_stage_1_v1", "enemy_stage_1_v2"})

    def test_raider_resolves_its_own_group(self):
        tm = synth(["bbs"])
        r = Raider(2, 0, ENEM, tm, tier=2, registry=self.REG, rng=FakeRng())
        self.assertEqual(self._slot(r), "raider_stage_3")

    def test_fallback_slot_without_registry(self):
        # Headless stat/logic tests construct without a registry -> DEFAULT_SLOT.
        tm = synth(["bbs"])
        self.assertEqual(
            self._slot(Enemy(2, 0, ENEM, tm, tier=0)), "enemy_stage_1_v1")
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
    _BOSS_INTERVAL = ENEM["EnemyTypes"]["Boss"]["round_interval"]

    def test_standard_count_formula(self):
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                tier = (r - 1) // SCALE["scale_every_n_levels"]
                expected = SCALE["base_enemy_count"] + (r - 1) * (
                    SCALE["enemies_per_round"] + tier)
                self.assertEqual(etypes.count("standard"), expected)

    def test_raider_count_formula_and_start_round(self):
        start = RAIDER["start_round"]
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                if r < start:
                    expected = 0
                else:
                    expected = (RAIDER["base_count"]
                                + (r - start) * RAIDER["per_round"])
                self.assertEqual(etypes.count("raider"), expected)

    def test_siege_count_formula_and_start_round(self):
        start = SIEGE["start_round"]
        for r in range(1, 26):
            if r % self._BOSS_INTERVAL == 0:
                continue  # boss-round composition (10G) — see test_boss.py
            with self.subTest(round=r):
                _sp, etypes = self._counts(r)
                if r < start:
                    expected = 0
                else:
                    expected = (SIEGE["base_count"]
                                + (r - start) // SIEGE["rounds_per_cannon"])
                self.assertEqual(etypes.count("siege"), expected)

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

    def test_boss_leads_every_boss_round(self):
        # ENABLE_BOSS flipped in 10G: every `round_interval`-th round emits
        # exactly ONE boss at the head of the queue, and non-boss rounds never
        # emit one (the detailed composition lives in test_boss.py).
        interval = ENEM["EnemyTypes"]["Boss"]["round_interval"]
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
        n = SCALE["base_enemy_count"]
        # Drive well past the total wave duration; one pop per expiry.
        for _ in range(2000):
            sp.update(0.1, scene)
        scene.update(0.0)
        self.assertEqual(len(scene.by_tag("enemy")), n)
        self.assertTrue(sp.done)


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
            resolve_combat(scene, tm, 0.05, BUILD)
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
            resolve_combat(scene, tm, 0.1, BUILD)
            if not scene.by_tag("enemy"):
                break
        else:
            self.fail("enemy never reached the base")
        self.assertEqual(base.get_component(Health).hp,
                         max(0, CORE["TheHole"]["base_hp"] - STD["dmg"]))
        self.assertEqual(
            base.get_component(RoundStats).dmg_taken_this_round, STD["dmg"])


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
