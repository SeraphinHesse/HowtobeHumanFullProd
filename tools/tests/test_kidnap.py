"""Kidnapping — an enemy that kills a building carries it home (Art/enemies).

Same headless fixture style as ``test_death_spawn.py``: a synth ``TileMapDoc``
board, real balancing via ``load_balance`` (the FIXTURE_DATA snapshot already
ships ``kidnapping: true`` for Standard/Raider and ``false`` for
Siege/Formation/Boss, matching the shipped tuning), a drained ``Session`` in
ENEMY phase, and a per-frame ``frame()`` helper wiring every callback the host
threads (``on_base_hit``/``on_enemy_death``/``on_kidnap``).

The board is 5 tiles wide (``bbbbs``): base(0,0), an empty buildable lane
(1,0)/(2,0), the victim building on (3,0), and the ONLY spawn tile on (4,0).
That gap between the kill site and home is deliberate — it gives the carrier
several real frames of walking before it arrives and despawns, so the
in-flight state (retag, waypoints, frozen pose, wave-clear) is observable
instead of collapsing into the same frame as the kill.
"""
import random
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Movement, Scene, SpriteAnimator
from engine.coords import CoordinateSystem, Geometry
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base, place_building
from game.core import Session, load_balance
from game.core import lightning as lt
from game.core.payday import run_payday
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.components import Kidnap, PathAgent
from game.enemies.kidnap import CARRY_OFFSET_TILES
from game.map.tile_map import TileMap
from game.map.tiles import TileState

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")


def synth(rows, base=(0, 0)):
    doc = tilemap.TileMapDoc(
        map_id="synth", display_name="Synth",
        cols=len(rows[0]), rows=len(rows),
        legend={}, terrain=[list(r) for r in rows],
        base={"col": base[0], "row": base[1], "slot": "base_hole"}, deco=[])
    return TileMap(doc, MAPBAL)


def build_board():
    """base(0,0) - (1,0) - (2,0) - (3,0)[victim] - (4,0)[the only spawn]."""
    tm = synth(["bbbbs"])
    scene, occ = Scene(), TileOccupancy()
    attach_base(tm, BaseBuilding(tm.base_col, tm.base_row, CORE), scene, occ)
    return tm, scene, occ


def armed_session(tm, occ, round_num=1, rng_seed=2):
    """A Session mid-ENEMY-phase with an armed-but-drained spawner, so the
    only enemies on the field are the ones the test spawns by hand (the
    ``test_death_spawn.py`` pattern)."""
    session = Session.create(Spawner(), tm, ENEM, CORE, BUILD,
                             rng=random.Random(rng_seed), occupancy=occ)
    session.state.round_num = round_num
    session.state.phase = GamePhase.ENEMY
    session.spawner.begin_round(round_num, tm, ENEM, rng=random.Random(rng_seed))
    session.spawner.clear()
    return session


def frame(session, scene, tm, dt):
    """One host frame with every combat callback wired (game/main.py's
    shape): base hit, enemy death, and the kidnap handoff."""
    def _on_kidnap(enemy, building, _scene=scene):
        session.on_kidnap(enemy, building, _scene)

    session.pre_sim(dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(dt)
        resolve_combat(scene, tm, dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death,
                       on_kidnap=_on_kidnap)
        session.post_sim(scene)


def place_victim(tm, scene, occ, col=3, row=0):
    """A killable "economic" building at (col, row) with 1 HP, so a single
    landed attack finishes it."""
    building, _cost = place_building(tm, tm.get(col, row), "economic", 9999,
                                     BUILD, scene, occ)
    building.get_component(Health).hp = 1
    return building


def run_until_kidnapper(session, scene, tm, max_frames=60, dt=0.1):
    """Spawn a Standard walker at the far spawn tile and run frames until it
    becomes a kidnapper (or fail)."""
    e = create_enemy("standard", 4, 0, ENEM, tm)
    scene.spawn(e)
    for _ in range(max_frames):
        frame(session, scene, tm, dt)
        if scene.by_tag("kidnapper"):
            return e
    raise AssertionError("enemy never became a kidnapper")


class TestKidnappingDisabledTypesAreUnaffected(unittest.TestCase):
    """Standard 1-8 verification item #1: kidnapping:false types stay exactly
    what they were before this feature — no retag, building stays dead+intact
    on its tile, the enemy just keeps walking (a revive candidate at payday)."""

    def test_siege_cannon_kills_and_walks_on(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        victim = place_victim(tm, scene, occ)
        self.assertFalse(ENEM["EnemyTypes"]["SiegeCannon"]["kidnapping"])

        e = create_enemy("siege", 4, 0, ENEM, tm)
        scene.spawn(e)
        for _ in range(200):
            frame(session, scene, tm, 0.1)
            if not victim.alive:
                break
        else:
            self.fail("victim building never died")

        self.assertFalse(victim.alive)
        self.assertEqual(scene.by_tag("kidnapper"), [])
        self.assertIn(e, scene.by_tag("enemy"))
        k = e.get_component(Kidnap)
        self.assertFalse(k.enabled)  # SiegeCannon.kidnapping is false
        self.assertFalse(k.active)
        self.assertFalse(k.pending)
        tile = tm.get(3, 0)
        self.assertEqual(tile.state, TileState.BUILT)
        self.assertIs(tile.occupant, victim)  # dead but still on the board


class TestKidnapTransition(unittest.TestCase):
    """Verification item #2: the retag + carry-home state on the killing
    blow."""

    def test_standard_kill_arms_the_carry(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        e = run_until_kidnapper(session, scene, tm)

        kidnapper = scene.by_tag("kidnapper")[0]
        self.assertIs(kidnapper, e)
        self.assertNotIn("enemy", kidnapper.tags)
        self.assertEqual(kidnapper.tags, ("kidnapper",))

        k = kidnapper.get_component(Kidnap)
        pa = kidnapper.get_component(PathAgent)
        mv = kidnapper.get_component(Movement)
        self.assertTrue(k.active)
        self.assertFalse(k.pending)
        self.assertTrue(pa.carrying)
        self.assertFalse(pa.goal_is_base)  # load-bearing: no phantom base hit
        self.assertGreater(mv.speed, 0.0)
        self.assertTrue(mv.waypoints)
        last = mv.waypoints[-1]
        last_tile = tm.get(round(last[0]), round(last[1]))
        self.assertEqual(last_tile.state, TileState.SPAWNING)


class TestBuildingGoneForGood(unittest.TestCase):
    """Verification item #3: the tile is freed, not revived at payday, and
    stays placeable."""

    def test_tile_freed_and_survives_payday(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        run_until_kidnapper(session, scene, tm)

        tile = tm.get(3, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)
        self.assertIsNone(tile.occupant)
        self.assertIsNone(occ.get((3, 0)))

        run_payday(session.state, tm, CORE, occ, scene)
        scene.update(0.0)
        tile = tm.get(3, 0)
        self.assertEqual(tile.state, TileState.BUILDABLE)
        self.assertIsNone(tile.occupant)

        # Still placeable.
        new_building, _cost = place_building(
            tm, tile, "economic", 9999, BUILD, scene, occ)
        self.assertIsNotNone(new_building)


class TestScoringNoVfxNoBurst(unittest.TestCase):
    """Verification item #4."""

    def test_kill_counts_and_xp_once_no_splatter_no_burst(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        self.assertEqual(session.state.enemies_killed, 0)
        self.assertEqual(session.state.player_xp, 0)

        run_until_kidnapper(session, scene, tm)

        self.assertEqual(session.state.enemies_killed, 1)
        self.assertGreater(session.state.player_xp, 0)
        self.assertEqual(session.state.enemy_death_events, [])
        self.assertEqual(session._death_spawns_pending, [])

        # A second sweep must not double-count the same kidnap.
        frame(session, scene, tm, 0.1)
        self.assertEqual(session.state.enemies_killed, 1)


class TestKidnapperIsInvisibleToCombatAndLightning(unittest.TestCase):
    """Verification item #5."""

    def test_no_damage_from_defenders_or_lightning(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        kidnapper = run_until_kidnapper(session, scene, tm)
        hp_before = kidnapper.get_component(Health).hp

        # A defender that would otherwise reach it stays with no target.
        defender, _c = place_building(tm, tm.get(2, 0), "defence", 9999,
                                      BUILD, scene, occ)
        for _ in range(10):
            frame(session, scene, tm, 0.1)
        self.assertEqual(kidnapper.get_component(Health).hp, hp_before)
        self.assertEqual(
            [e for e in scene.by_tag("enemy") if e.alive], [])

        # Lightning sweeps by_tag("enemy") too — a retagged carrier is never
        # in that set, regardless of radius.
        cs = CoordinateSystem(Geometry(
            tile_w=64, tile_h=32, map_cols=16, map_rows=16,
            zoom_levels=(1.0,)))
        state = session.state
        state.lightning_level = 1
        state.lightning_cooldown = 0.0
        wx, wy = kidnapper.transform.world_pos
        struck = lt.strike(state, CORE, VFX, scene, cs, wx, wy)
        self.assertTrue(struck)  # it fired (unlocked, off cooldown)...
        self.assertEqual(kidnapper.get_component(Health).hp, hp_before)  # ...but hit nothing


class TestWaveClearHoldsForKidnappers(unittest.TestCase):
    """Verification item #6: the round cannot end while a kidnapper still
    walks home; ``quick_skip_combat`` clears it."""

    def test_round_waits_then_ends_when_the_kidnapper_is_gone(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        run_until_kidnapper(session, scene, tm)

        self.assertTrue(session.spawner.done)
        self.assertEqual(
            [e for e in scene.by_tag("enemy") if e.alive], [])
        self.assertTrue(scene.by_tag("kidnapper"))
        # The wave-clear check must NOT have flipped the phase yet.
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

        for _ in range(200):
            frame(session, scene, tm, 0.1)
            if not scene.by_tag("kidnapper"):
                break
        else:
            self.fail("kidnapper never reached the spawn tile / despawned")
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)

    def test_quick_skip_clears_kidnappers(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        run_until_kidnapper(session, scene, tm)
        self.assertTrue(scene.by_tag("kidnapper"))

        session.quick_skip_combat(scene)
        scene.update(0.0)  # flush the queued despawn (Scene.despawn only queues)
        self.assertEqual(scene.by_tag("kidnapper"), [])
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)


class TestCarriedSpriteGeometry(unittest.TestCase):
    """Verification item #7: the (-d, +d) world offset."""

    def test_render_item_offset_and_depth(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        kidnapper = run_until_kidnapper(session, scene, tm)

        k = kidnapper.get_component(Kidnap)
        self.assertTrue(k.slot_key)  # copied from the victim's SpriteAnimator
        items = list(k.render_items(kidnapper.transform))
        self.assertEqual(len(items), 1)
        item = items[0]

        wx, wy = kidnapper.transform.world_pos
        ix, iy = item.world_pos
        self.assertAlmostEqual(ix + iy, wx + wy)   # same depth (wx+wy)
        self.assertGreater(iy, wy)                 # larger wy -> draws in front

        cs = CoordinateSystem(Geometry(
            tile_w=64, tile_h=32, map_cols=16, map_rows=16,
            zoom_levels=(1.0,)))
        sx0, _sy0 = cs.world_to_screen(wx, wy)
        sx1, sy1 = cs.world_to_screen(ix, iy)
        # `world_to_screen` is `iso * zoom - pan`, so the screen delta scales
        # with the camera's zoom. Derive the expectation from the camera this
        # test actually uses instead of assuming 1.0: the `Camera.zoom` default
        # moved 1.0 -> 2.0 (engine/coords/camera.py) and silently doubled this
        # number, which is exactly what a hardcoded 16 could not survive. The
        # invariant under test is the OFFSET, not the zoom it is viewed at.
        half_w = 64 / 2
        self.assertAlmostEqual(
            sx0 - sx1, 2 * CARRY_OFFSET_TILES * half_w * cs.camera.zoom)
        self.assertAlmostEqual(_sy0, sy1)  # zero vertical screen change


class TestFrozenPoseWithNoKidnapRow(unittest.TestCase):
    """Verification item #8: with no ``kidnap`` sheet row (the default this
    package ever picks without a host upgrading it — see ``game/main.py``),
    the sprite freezes on idle frame 0 across multiple ticks."""

    def test_pose_stays_pinned_idle_at_frame_zero(self):
        tm, scene, occ = build_board()
        session = armed_session(tm, occ)
        place_victim(tm, scene, occ)
        kidnapper = run_until_kidnapper(session, scene, tm)

        anim = kidnapper.get_component(SpriteAnimator)
        k = kidnapper.get_component(Kidnap)
        self.assertTrue(k.frozen)
        self.assertEqual(anim.animation, "idle")
        for _ in range(5):
            scene.update(0.1)
            self.assertEqual(anim.animation, "idle")
            self.assertEqual(anim.anim_time_ms, 0.0)


if __name__ == "__main__":
    unittest.main()
