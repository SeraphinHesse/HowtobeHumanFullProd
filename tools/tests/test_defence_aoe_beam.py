"""Phase 10B: AOE Mortar (splash + predictive lead + crater) and Sun Scorcher
(ramping beam + target-death cooldown) — game/buildings + game/enemies/combat.

Tier-math walks reuse the 9D ``TierWalkMixin``; the combat tests use the same
headless ``synth`` tilemap + ``Scene`` harness as ``test_enemies.py``. Buildings
are constructed directly and spawned into the scene (combat only needs the
``"combat"`` tag + col/row + stats — no tile/placement/research), while enemies
come from ``create_enemy`` so their pathing wiring is real; freezing an enemy is
clearing its ``Movement.waypoints``.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

from engine import tilemap
from engine.core import Health, Movement, Scene
from game.buildings import AOEDefenceBuilding, SunScorcher
from game.buildings.components import BeamAttacker
from game.core.balance import load_balance
from game.enemies import create_enemy, resolve_combat
from game.enemies.combat import BEAM_MIN_TICK, _predict_lead
from game.map.tile_map import TileMap

from tools.tests.test_buildings_tier_math import TierWalkMixin

MAPBAL = load_balance(REPO / "data", "map")
BUILD = load_balance(REPO / "data", "buildings")
ENEM = load_balance(REPO / "data", "enemies")

AOE = BUILD["DefenceBuildings"]["AOEDefence"]["tiers"]
BEAM = BUILD["DefenceBuildings"]["BeamDefence"]["tiers"]


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def frozen_enemy(scene, tm, col, row, hp=None):
    """A standard enemy planted at (col,row) with its path cleared — a pure
    stationary target."""
    e = create_enemy("standard", col, row, ENEM, tm)
    scene.spawn(e)
    scene.update(0.0)
    e.get_component(Movement).waypoints = []
    if hp is not None:
        h = e.get_component(Health)
        h.max_hp = hp
        h.hp = hp
    return e


# ---------------------------------------------------------------------------
# Tier-math walks (splash radius / beam ramp fields), reusing the 9D mixin
# ---------------------------------------------------------------------------
class TestMawMortar(TierWalkMixin, unittest.TestCase):
    tiers = AOE
    sprites = ("maw_mortar", "maw_mortar", "maw_mortar")

    def make(self):
        return AOEDefenceBuilding(1, 1, BUILD)

    def extra_expected(self, tier, idx):
        return {
            "damage": tier["base_dmg"] + idx * tier["dmg_per_level"],
            "upkeep": tier["base_upkeep"] + idx * tier["upkeep_per_level"],
            "range": tier["range_tiles"],
            # mirror the exact float expression so assertEqual is bit-stable
            "radius": tier["base_radius"] + idx * tier["radius_per_level"],
        }

    def extra_actual(self, b):
        return {"damage": b.damage(), "upkeep": b.upkeep(),
                "range": b.range_tiles(), "radius": b.splash_radius()}


class TestSunScorcher(TierWalkMixin, unittest.TestCase):
    tiers = BEAM
    sprites = ("sun_scorcher", "radiant_beam", "laser_beam")

    def make(self):
        return SunScorcher(1, 1, BUILD)

    def extra_expected(self, tier, idx):
        return {
            "damage": tier["base_dmg"] + idx * tier["dmg_per_level"],
            "range": tier["range_tiles"],
            "ramp_per_tick": tier["dmg_ramp_per_tick"],
            "ramp_max": tier["dmg_ramp_max"],
        }

    def extra_actual(self, b):
        return {"damage": b.damage(), "range": b.range_tiles(),
                "ramp_per_tick": b.ramp_per_tick(), "ramp_max": b.ramp_max()}


# ---------------------------------------------------------------------------
# AOE splash: one shell, full damage to all within radius, none outside
# ---------------------------------------------------------------------------
class TestSplash(unittest.TestCase):
    def _fire_one_shell(self, scene, tm, watch):
        """Step until the first shell lands (someone in ``watch`` loses HP)."""
        hp0 = {e: e.get_component(Health).hp for e in watch}
        for _ in range(400):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD)
            if any(e.get_component(Health).hp < hp0[e] for e in watch):
                # The impact queues the Crater during this update; one more
                # step flushes the spawn queue so it materialises in the scene.
                scene.update(0.0)
                return
        self.fail("mortar never landed a shell")

    def test_one_shell_hits_whole_cluster_not_the_outsider(self):
        tm = synth(["bcccs", "bbccs", "bcccs"])
        scene = Scene()
        mortar = AOEDefenceBuilding(1, 1, BUILD)
        scene.spawn(mortar)
        # Cluster tight around (2,1) — the nearest tile to the mortar, so the
        # shell aims there; the outsider is in range (Chebyshev 3 <= 4) but well
        # outside the 1.2-tile splash of the landing point.
        cluster = [frozen_enemy(scene, tm, 2, 0),
                   frozen_enemy(scene, tm, 2, 1),
                   frozen_enemy(scene, tm, 2, 2)]
        outsider = frozen_enemy(scene, tm, 4, 1)
        hp_out = outsider.get_component(Health).hp

        self._fire_one_shell(scene, tm, cluster)

        dmg = mortar.damage()
        for e in cluster:
            took = e.get_component(Health).max_hp - e.get_component(Health).hp
            self.assertEqual(took, dmg)               # full damage, no falloff
        self.assertEqual(outsider.get_component(Health).hp, hp_out)  # untouched
        craters = scene.by_tag("crater")
        self.assertEqual(len(craters), 1)
        self.assertAlmostEqual(craters[0].radius, mortar.splash_radius())
        self.assertGreater(craters[0].fade_frac, 0.0)

    def test_crater_fades_and_despawns(self):
        tm = synth(["bcs", "bbs", "bcs"])
        scene = Scene()
        mortar = AOEDefenceBuilding(1, 1, BUILD)
        scene.spawn(mortar)
        target = frozen_enemy(scene, tm, 2, 1, hp=100000)
        self._fire_one_shell(scene, tm, [target])
        self.assertEqual(len(scene.by_tag("crater")), 1)
        # CRATER_LIFE = 1.0s: age it past its life; it self-despawns.
        for _ in range(30):
            scene.update(0.05)
        self.assertEqual(scene.by_tag("crater"), [])


# ---------------------------------------------------------------------------
# Predictive lead (prototype _predict_intercept)
# ---------------------------------------------------------------------------
class TestPredictiveLead(unittest.TestCase):
    def test_frozen_enemy_aims_at_its_position(self):
        tm = synth(["bcs"])
        scene = Scene()
        e = frozen_enemy(scene, tm, 2, 0)   # no waypoints
        gx, gy = _predict_lead(e, 0.55)
        self.assertAlmostEqual(gx, 2.0)
        self.assertAlmostEqual(gy, 0.0)

    def test_moving_enemy_is_led_along_its_heading(self):
        tm = synth(["bcs"])
        scene = Scene()
        e = create_enemy("standard", 5, 0, ENEM, tm)
        scene.spawn(e)
        scene.update(0.0)
        mv = e.get_component(Movement)
        mv.waypoints = [[0.0, 0.0]]          # heading left (toward the base)
        mv.index = 0
        mv.speed = 2.0
        gx, gy = _predict_lead(e, 0.55)
        # led ahead by speed*travel = 1.1 tiles toward x=0.
        self.assertAlmostEqual(gx, 5.0 - 2.0 * 0.55)
        self.assertLess(gx, 5.0)

    def test_lead_clamps_to_waypoint_when_it_would_overshoot(self):
        tm = synth(["bcs"])
        scene = Scene()
        e = create_enemy("standard", 2, 0, ENEM, tm)
        scene.spawn(e)
        scene.update(0.0)
        mv = e.get_component(Movement)
        mv.waypoints = [[1.0, 0.0]]          # 1 tile away
        mv.index = 0
        mv.speed = 10.0                       # would travel 5.5 tiles > 1
        gx, gy = _predict_lead(e, 0.55)
        self.assertAlmostEqual(gx, 1.0)       # clamped to the waypoint
        self.assertAlmostEqual(gy, 0.0)


# ---------------------------------------------------------------------------
# Beam ramp / reset / target-death cooldown / highest-HP targeting
# ---------------------------------------------------------------------------
class TestBeam(unittest.TestCase):
    def _beam(self, scene, col=1, row=0, tier=0):
        b = SunScorcher(col, row, BUILD)
        for _ in range(tier):
            b.advance_tier()
        scene.spawn(b)
        return b

    def _tick_damages(self, scene, tm, target, n_ticks, dt=0.05):
        """Per-tick damage amounts against ``target`` over stepped frames."""
        prev = target.get_component(Health).hp
        out = []
        for _ in range(2000):
            scene.update(dt)
            resolve_combat(scene, tm, dt, BUILD)
            now = target.get_component(Health).hp
            if now < prev:
                out.append(prev - now)
            prev = now
            if len(out) >= n_ticks:
                break
        return out

    def test_ramp_escalates_by_per_tick_to_cap(self):
        tm = synth(["bbcs"])
        scene = Scene()
        beam = self._beam(scene)
        tank = frozen_enemy(scene, tm, 2, 0, hp=100000)
        dmgs = self._tick_damages(scene, tm, tank, 60)
        base, per, cap = beam.damage(), beam.ramp_per_tick(), beam.ramp_max()
        # First tick is base damage (ramp starts at 0), then +per each tick.
        self.assertEqual(dmgs[0], base)
        self.assertEqual(dmgs[1], base + per)
        self.assertEqual(dmgs[2], base + 2 * per)
        self.assertEqual(max(dmgs), base + cap)          # capped
        self.assertTrue(all(d <= base + cap for d in dmgs))

    def test_ramp_resets_on_target_change(self):
        tm = synth(["bbccs"])
        scene = Scene()
        beam = self._beam(scene)
        a = frozen_enemy(scene, tm, 2, 0, hp=100000)
        b = frozen_enemy(scene, tm, 2, 1, hp=100000)
        # Ramp up on `a` for a while.
        self._tick_damages(scene, tm, a, 6)
        ba = beam.get_component(BeamAttacker)
        self.assertGreater(ba.ramp, 0)
        # Remove `a` from range by killing it; the beam re-acquires `b` after
        # the death cooldown, and the ramp must be back at 0 on the first hit.
        a.get_component(Health).hp = 0
        first_b = self._tick_damages(scene, tm, b, 1)
        self.assertEqual(first_b[0], beam.damage())      # base only, ramp reset

    def test_target_death_triggers_reacquire_cooldown(self):
        tm = synth(["bbccs"])
        scene = Scene()
        beam = self._beam(scene)
        # The beam targets highest HP, so the enemy it kills must be the higher
        # of the two; the bystander stays lower so it is never the target.
        to_kill = frozen_enemy(scene, tm, 2, 0, hp=6)
        waiting = frozen_enemy(scene, tm, 2, 1, hp=2)
        for _ in range(30):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD)
            if not to_kill.alive:
                break
        ba = beam.get_component(BeamAttacker)
        self.assertGreater(ba.death_cooldown, 0)
        self.assertAlmostEqual(ba.death_cooldown,
                               beam.target_death_cooldown(), delta=0.06)
        # During the cooldown the waiting enemy takes no damage.
        hp_wait = waiting.get_component(Health).hp
        for _ in range(int(beam.target_death_cooldown() / 0.05) - 1):
            scene.update(0.05)
            resolve_combat(scene, tm, 0.05, BUILD)
        self.assertEqual(waiting.get_component(Health).hp, hp_wait)
        # After the cooldown elapses it starts taking damage again.
        dealt = self._tick_damages(scene, tm, waiting, 1)
        self.assertTrue(dealt)

    def test_targets_highest_hp_in_range(self):
        tm = synth(["bbccs"])
        scene = Scene()
        beam = self._beam(scene)
        # weak nearer, tank farther — the beam must prefer the tank (highest HP),
        # unlike the nearest-target defender/mortar.
        weak = frozen_enemy(scene, tm, 2, 0, hp=50)
        tank = frozen_enemy(scene, tm, 2, 1, hp=100000)
        scene.update(0.05)
        resolve_combat(scene, tm, 0.05, BUILD)
        self.assertIs(beam.get_component(BeamAttacker)._target, tank)

    def test_beam_min_tick_beats_the_shared_floor(self):
        # A tier-3 beam ticks at 0.08s; the shared min_attack_speed is 0.2, so a
        # naive clamp would let it fire only once per 0.2s. With the beam's own
        # 0.02 floor it fires several times.
        tm = synth(["bbcs"])
        scene = Scene()
        beam = self._beam(scene, tier=2)
        self.assertLess(beam.attack_speed(),
                        BUILD["DefenceBuildings"]["globals"]["min_attack_speed"])
        self.assertGreaterEqual(beam.attack_speed(), BEAM_MIN_TICK)
        tank = frozen_enemy(scene, tm, 2, 0, hp=100000)
        # Count ticks within ~0.2s of firing (dt small to resolve the cadence).
        ticks = 0
        prev = tank.get_component(Health).hp
        for _ in range(10):                 # 10 * 0.02 = 0.2s
            scene.update(0.02)
            resolve_combat(scene, tm, 0.02, BUILD)
            now = tank.get_component(Health).hp
            if now < prev:
                ticks += 1
            prev = now
        self.assertGreaterEqual(ticks, 2)   # >1 proves it isn't clamped to 0.2


if __name__ == "__main__":
    unittest.main()
