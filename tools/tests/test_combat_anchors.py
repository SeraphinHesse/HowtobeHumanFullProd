"""ESV-1 §1.4 — the D4 guardrail: a muzzle anchor moves where a projectile
VISUALLY spawns (``game/anchors.py world_offset``, wired into ``_fire``/
``_fire_splash``) and never touches when damage lands (``ProjectileHoming
.launch(origin=...)``, always the shooter's unmodified ``transform.world_pos``).

Same headless ``synth`` tilemap + ``Scene`` harness as ``test_enemies.py`` /
``test_defence_aoe_beam.py``.
"""
import math
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.assets import Manifest, entry_from_dict
from engine.assets.store import AssetStore
from engine.coords import load_coordinate_system
from engine.core import GameObject, Health, Movement, Scene, SpriteAnimator, Transform
from engine.physics import TileOccupancy
from game.buildings import AOEDefenceBuilding, RoundStats, place_building
from game.core.balance import load_balance
from game.enemies import Projectile, create_enemy, resolve_combat
from game.enemies.combat import (
    AOE_TRAVEL_TIME, ProjectileArc, ProjectileHoming, _fire_splash,
    _predict_lead,
)
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
ENEM = load_balance(FIXTURE_DATA, "enemies")

CS = load_coordinate_system(FIXTURE_DATA)   # tile_w=64/tile_h=32, fixture geometry


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def defender_stub():
    """A minimal shooter carrying a RoundStats (the projectile credits it)."""
    return GameObject(transform=Transform(wx=1.0, wy=0.0),
                      components=[RoundStats()])


def make_store(slot_key, anchor_xy=None, frame_w=64, frame_h=64):
    """A one-entry AssetStore whose `slot_key` optionally carries a `muzzle`
    anchor — no sheet is ever loaded (frame_size/anchor are pure metadata)."""
    raw = {
        "sheet": "imported/x.png", "frame_w": frame_w, "frame_h": frame_h,
        "offset_x": 0, "offset_y": 0,
        "rows": [{"animation": "idle", "frames": 1, "fps": 8, "hidden": [],
                  "loop_start": 0, "loop_end": 0, "loop_count": 1}],
    }
    if anchor_xy is not None:
        raw["anchors"] = {"muzzle": list(anchor_xy)}
    entry = entry_from_dict(slot_key, raw)
    return AssetStore(manifest=Manifest({slot_key: entry}), sprites_dir=None,
                      frame_sizes={slot_key: (frame_w, frame_h)})


def frozen_defender(tm, scene, occ, col, row, slot_key="anchor_test"):
    defender, _c = place_building(tm, tm.get(col, row), "defence", 9999,
                                  BUILD, scene, occ)
    defender.get_component(SpriteAnimator).slot_key = slot_key
    return defender


def frozen_target(scene, tm, col, row, hp=100000):
    e = create_enemy("standard", col, row, ENEM, tm)
    scene.spawn(e)
    scene.update(0.0)
    e.get_component(Movement).waypoints = []
    h = e.get_component(Health)
    h.max_hp = hp
    h.hp = hp
    return e


# ---------------------------------------------------------------------------
# 4(a) — the spawn point moves to the muzzle-anchored world point
# ---------------------------------------------------------------------------
class TestMuzzleShiftsTheSpawnPoint(unittest.TestCase):
    def test_projectile_spawns_at_world_pos_plus_world_offset(self):
        from game.anchors import world_offset

        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        defender = frozen_defender(tm, scene, occ, 1, 0)
        frozen_target(scene, tm, 2, 0)
        assets = make_store("anchor_test", anchor_xy=(40, -10))

        scene.update(0.05)
        resolve_combat(scene, tm, 0.05, BUILD, assets=assets, cs=CS)
        scene.update(0.0)   # flush the spawn queue
        projectiles = scene.by_tag("projectile")
        self.assertEqual(len(projectiles), 1)

        bx, by = defender.transform.world_pos
        dwx, dwy = world_offset(assets, CS, defender, "muzzle")
        self.assertGreater(abs(dwx) + abs(dwy), 0.0)   # really did move
        px, py = projectiles[0].transform.world_pos
        self.assertAlmostEqual(px, bx + dwx, places=9)
        self.assertAlmostEqual(py, by + dwy, places=9)


# ---------------------------------------------------------------------------
# 4(b) — damage timing/HP ledger is invariant under the anchor value
# ---------------------------------------------------------------------------
class TestDamageTimingInvariantUnderAnchor(unittest.TestCase):
    def _ledger(self, anchor_xy, n_frames=200, dt=0.05):
        tm = synth(["bbs"])
        scene, occ = Scene(), TileOccupancy()
        frozen_defender(tm, scene, occ, 1, 0)
        target = frozen_target(scene, tm, 2, 0)
        assets = make_store("anchor_test", anchor_xy=anchor_xy)
        health = target.get_component(Health)
        ledger = []
        for _ in range(n_frames):
            scene.update(dt)
            resolve_combat(scene, tm, dt, BUILD, assets=assets, cs=CS)
            ledger.append(health.hp)
        return ledger

    def test_no_anchor_vs_a_large_anchor_vs_an_absurd_one(self):
        baseline = self._ledger(None)
        large = self._ledger((40, -10))          # most of a tile
        absurd = self._ledger((2000, -1800))      # deliberately absurd
        self.assertTrue(any(h < baseline[0] for h in baseline))  # it did fight
        self.assertEqual(baseline, large)
        self.assertEqual(baseline, absurd)


# ---------------------------------------------------------------------------
# 6 — ProjectileHoming.launch(origin=...) default is byte-identical
# ---------------------------------------------------------------------------
class TestLaunchOriginDefault(unittest.TestCase):
    def test_no_origin_matches_todays_expression(self):
        tm = synth(["bbs"])
        scene = Scene()
        target = frozen_target(scene, tm, 2, 0)
        proj = Projectile(1.0, 0.0, 10, 3.75)
        proj.get_component(ProjectileHoming).launch(target, defender_stub(), scene)
        tx, ty = target.transform.world_pos
        px, py = proj.transform.world_pos
        expected = math.hypot(tx - px, ty - py) / 3.75
        self.assertAlmostEqual(
            proj.get_component(ProjectileHoming).timer, expected, places=9)

    def test_explicit_origin_is_used_instead_of_the_spawn_point(self):
        tm = synth(["bbs"])
        scene = Scene()
        target = frozen_target(scene, tm, 2, 0)
        proj = Projectile(1.0, 0.0, 10, 3.75)   # spawned at (1, 0)
        proj.get_component(ProjectileHoming).launch(
            target, defender_stub(), scene, origin=(0.0, 0.0))
        tx, ty = target.transform.world_pos
        expected = math.hypot(tx - 0.0, ty - 0.0) / 3.75
        self.assertAlmostEqual(
            proj.get_component(ProjectileHoming).timer, expected, places=9)


# ---------------------------------------------------------------------------
# 7 — `_fire_splash`'s travel time (fixed) and landing point (target-only)
# are untouched by a muzzle anchor; only the shell's spawn point moves.
# ---------------------------------------------------------------------------
class TestFireSplashUnaffectedByAnchor(unittest.TestCase):
    def test_travel_time_and_landing_point_match_the_unanchored_run(self):
        tm = synth(["bcs"])
        scene = Scene()
        mortar = AOEDefenceBuilding(1, 1, BUILD)
        mortar.get_component(SpriteAnimator).slot_key = "anchor_test"
        scene.spawn(mortar)
        scene.update(0.0)
        target = create_enemy("standard", 2, 1, ENEM, tm)
        scene.spawn(target)
        scene.update(0.0)
        mv = target.get_component(Movement)
        mv.waypoints = [[0.0, 1.0]]
        mv.index = 0
        mv.speed = 1.5

        expected_gx, expected_gy = _predict_lead(target, AOE_TRAVEL_TIME)
        bx, by = mortar.transform.world_pos

        assets = make_store("anchor_test", anchor_xy=(2000, -1800))
        _fire_splash(mortar, target, scene, dmg_bonus=0, assets=assets, cs=CS)
        scene.update(0.0)   # flush the spawn queue

        shells = scene.by_tag("projectile")
        self.assertEqual(len(shells), 1)
        arc = shells[0].get_component(ProjectileArc)
        self.assertEqual(arc.timer, AOE_TRAVEL_TIME)     # fixed, not distance-derived
        self.assertAlmostEqual(arc._gx, expected_gx, places=9)
        self.assertAlmostEqual(arc._gy, expected_gy, places=9)
        # only the SPAWN point moved
        self.assertNotAlmostEqual(shells[0].transform.wx, bx, places=6)


if __name__ == "__main__":
    unittest.main()
