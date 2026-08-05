"""Phase ER-3: the generalised toggleable death_spawn (plan D4).

One mechanic, declared per type in `data/balancing/enemies.json`: a unit DIES
once `hp <= max_hp * at_hp_fraction` (breaking formation IS dying — one code
path, no second state machine) and, if `enabled`, bursts its era's `spawns` row
at the tile it died on, each child seeded to `spawn_hp_fraction` of its own max
HP. The Boss's 10G swarm is the `at_hp_fraction 0.0` + `spawn_hp_fraction 1.0`
case and is pinned byte-for-byte by `test_boss.py`.

Same headless fixture style as `test_boss.py`: a synth TileMap board, the real
balancing tree via `load_balance`, and a deep-copied balance dict so a test can
flip `death_spawn` fields without touching `data/`.
"""
import copy
import random
import unittest
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
from tools.tests.fixture_data import FIXTURE_DATA

from engine import tilemap
from engine.core import Health, Scene
from engine.physics import TileOccupancy
from game.buildings import BaseBuilding, attach_base
from game.core import Session, load_balance
from game.core.phases import GamePhase, GameState
from game.enemies import Spawner, create_enemy, resolve_combat
from game.enemies.components import DeathSpawn
from game.enemies.enemy import era_stats
from game.map.tile_map import TileMap

MAPBAL = load_balance(FIXTURE_DATA, "map")
BUILD = load_balance(FIXTURE_DATA, "buildings")
CORE = load_balance(FIXTURE_DATA, "core")
ENEM = load_balance(FIXTURE_DATA, "enemies")
VFX = load_balance(FIXTURE_DATA, "vfx")

STOCK_TYPES = ("standard", "raider", "siege", "boss")


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


def frame(session, scene, tilemap_, dt):
    """One host frame with the death callback wired (game/main.py)."""
    session.pre_sim(dt, scene)
    if session.state.state == GameState.GAMEPLAY and not session.frozen:
        scene.update(dt)
        resolve_combat(scene, tilemap_, dt, BUILD, VFX,
                       on_base_hit=session.on_base_hit,
                       on_enemy_death=session.on_enemy_death)
        session.post_sim(scene)


def armed_session(tm, scene, occ, balance, round_num=1):
    """A Session mid-ENEMY-phase with an armed-but-drained spawner, so the only
    enemies on the field are the ones the test spawns by hand."""
    session = Session.create(Spawner(), tm, balance, CORE, BUILD,
                             rng=random.Random(2), occupancy=occ)
    session.state.round_num = round_num
    session.state.phase = GamePhase.ENEMY
    session.spawner.begin_round(round_num, tm, balance, rng=random.Random(2))
    session.spawner.clear()
    return session


def with_death_spawn(etype_key, **fields):
    """A deep copy of the real balance tree with one type's `death_spawn`
    block overridden — the mechanic under test, never a write to data/."""
    balance = copy.deepcopy(ENEM)
    balance["EnemyTypes"][etype_key]["death_spawn"].update(fields)
    return balance


class TestDisabledSpawnsNothing(unittest.TestCase):
    def test_enabled_false_dies_normally_and_spawns_nothing(self):
        """The three stock non-boss types ship `enabled: false` — they die at
        zero HP and leave nothing behind."""
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, ENEM)
        enemy = create_enemy("standard", 1, 0, ENEM, tm)
        scene.spawn(enemy)
        scene.update(0.0)

        enemy.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)   # death -> despawn, no stash
        scene.update(0.0)

        self.assertIsNone(enemy.death_spawn_plan)
        self.assertEqual(session._death_spawns_pending, [])
        self.assertEqual([e for e in scene.by_tag("enemy") if e.alive], [])
        self.assertEqual(session.state.enemies_killed, 1)  # XP path untouched


class TestThresholdDeath(unittest.TestCase):
    """A type with at_hp_fraction 0.5 + spawn_hp_fraction 0.8 bursting 4."""

    def _balance(self):
        return with_death_spawn(
            "Standard", at_hp_fraction=0.5, enabled=True,
            spawn_hp_fraction=0.8,
            spawns=[{"raiders": 0, "regular": 4, "siege": 0}])

    def test_alive_boundary_is_at_or_below_the_threshold(self):
        """The boundary is `<=`: hp EXACTLY at the threshold is DEAD, one point
        above it is alive. max_hp is forced even so the 0.5 threshold is an
        integer and equality is genuinely exercised (the stock Standard's 55
        gives 27.5, which an int hp can never hit)."""
        balance = self._balance()
        tm = synth(["bs"])
        enemy = create_enemy("standard", 1, 0, balance, tm)
        health = enemy.get_component(Health)
        health.max_hp = 60
        threshold = 30                      # 60 * at_hp_fraction 0.5, exactly

        health.hp = threshold + 1
        self.assertTrue(enemy.alive)
        health.hp = threshold               # EXACT equality -> dead
        self.assertFalse(enemy.alive)
        health.hp = threshold - 1
        self.assertFalse(enemy.alive)

    def test_breaks_once_into_four_children_at_80_percent_hp(self):
        balance = self._balance()
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, balance)
        parent = create_enemy("standard", 1, 0, balance, tm)
        scene.spawn(parent)
        scene.update(0.0)

        health = parent.get_component(Health)
        health.hp = int(health.max_hp * 0.5)      # at the threshold => dead
        self.assertFalse(parent.alive)

        frame(session, scene, tm, 0.0)            # report -> stash -> flush
        scene.update(0.0)

        children = [e for e in scene.by_tag("enemy") if e.alive]
        self.assertEqual(Counter(e.ETYPE for e in children),
                         Counter({"standard": 4}))
        self.assertNotIn(parent, scene.by_tag("enemy"))   # the parent despawned

        era = session.spawner.enemy_era
        child_max = era_stats(balance["EnemyTypes"]["Standard"], era)[0]
        for child in children:
            ch = child.get_component(Health)
            self.assertEqual(ch.max_hp, child_max)
            self.assertEqual(ch.hp, max(1, int(child_max * 0.8)))
            self.assertLess(ch.hp, ch.max_hp)
            self.assertEqual((child._col, child._row), (1, 0))  # parent's tile

    def test_children_do_not_chain_break_on_the_frame_they_appear(self):
        """spawn_hp_fraction 0.8 > at_hp_fraction 0.5, so the 80%-HP children
        are alive — the burst does not cascade."""
        balance = self._balance()
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, balance)
        parent = create_enemy("standard", 1, 0, balance, tm)
        scene.spawn(parent)
        scene.update(0.0)
        parent.get_component(Health).hp = 0
        frame(session, scene, tm, 0.0)
        scene.update(0.0)

        children = [e for e in scene.by_tag("enemy") if e.alive]
        self.assertEqual(len(children), 4)
        frame(session, scene, tm, 0.0)            # a second sweep: no cascade
        scene.update(0.0)
        self.assertEqual(
            len([e for e in scene.by_tag("enemy") if e.alive]), 4)


class TestOneShotGuard(unittest.TestCase):
    def test_double_report_in_one_frame_bursts_once(self):
        balance = with_death_spawn(
            "Standard", at_hp_fraction=0.0, enabled=True,
            spawn_hp_fraction=1.0,
            spawns=[{"raiders": 0, "regular": 3, "siege": 0}])
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, balance)
        parent = create_enemy("standard", 1, 0, balance, tm)
        scene.spawn(parent)
        scene.update(0.0)
        parent.get_component(Health).damage(10 ** 9)

        session.on_enemy_death(parent)
        self.assertEqual(len(session._death_spawns_pending), 1)
        self.assertTrue(parent.death_spawned)
        session.on_enemy_death(parent)                  # the double-death frame
        self.assertEqual(len(session._death_spawns_pending), 1)

        session.post_sim(scene)
        scene.update(0.0)
        self.assertEqual(
            len([e for e in scene.by_tag("enemy") if e.alive]), 3)

        session.post_sim(scene)                         # nothing left to flush
        scene.update(0.0)
        self.assertEqual(
            len([e for e in scene.by_tag("enemy") if e.alive]), 3)


class TestDefaultFractionIsByteIdentical(unittest.TestCase):
    def test_at_hp_fraction_zero_matches_health_is_dead(self):
        """Every stock type ships at_hp_fraction 0.0, so `alive` is exactly
        `not Health.is_dead` at every HP — the pre-ER-3 rule, unchanged."""
        tm = synth(["bs"])
        for etype in STOCK_TYPES:
            enemy = create_enemy(etype, 1, 0, ENEM, tm)
            health = enemy.get_component(Health)
            self.assertEqual(
                enemy.get_component(DeathSpawn).at_hp_fraction, 0.0)
            for hp in (health.max_hp, 1, 0):
                with self.subTest(etype=etype, hp=hp):
                    health.hp = hp
                    self.assertEqual(enemy.alive, not health.is_dead)


class TestTwoUnitsBreakingInOneFrame(unittest.TestCase):
    def test_both_bursts_flush(self):
        """The list stash — 10G's single slot would have dropped one of these
        (ER-4's Formations break in groups)."""
        balance = with_death_spawn(
            "Standard", at_hp_fraction=0.0, enabled=True,
            spawn_hp_fraction=1.0,
            spawns=[{"raiders": 0, "regular": 2, "siege": 0}])
        tm, scene, occ = build_board(["bbs"])
        session = armed_session(tm, scene, occ, balance)
        first = create_enemy("standard", 1, 0, balance, tm)
        second = create_enemy("standard", 2, 0, balance, tm)
        scene.spawn(first)
        scene.spawn(second)
        scene.update(0.0)

        first.get_component(Health).damage(10 ** 9)
        second.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)        # ONE frame, TWO deaths
        scene.update(0.0)

        children = [e for e in scene.by_tag("enemy") if e.alive]
        self.assertEqual(len(children), 4)    # 2 + 2, not 2
        self.assertEqual(session._death_spawns_pending, [])
        self.assertEqual(Counter((e._col, e._row) for e in children),
                         Counter({(1, 0): 2, (2, 0): 2}))


class TestTheRoundOutlivesTheBurst(unittest.TestCase):
    """ER-5: the wave-clear race. `Scene.spawn` only QUEUES, and `by_tag` reads
    the live list, so the children of a unit that dies as the LAST enemy of a
    drained wave used to be invisible to the wave-clear check on that frame — the
    round ended and they materialised into it. The check now also consults the
    spawn queue."""

    def _balance(self):
        return with_death_spawn(
            "Standard", at_hp_fraction=0.0, enabled=True,
            spawn_hp_fraction=1.0,
            spawns=[{"raiders": 0, "regular": 3, "siege": 0}])

    def test_the_last_enemy_bursting_does_not_end_the_round(self):
        balance = self._balance()
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, balance)
        enemy = create_enemy("standard", 1, 0, balance, tm)
        scene.spawn(enemy)
        scene.update(0.0)

        self.assertTrue(session.spawner.done)   # a DRAINED wave: this is the last
        enemy.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)

        # The children are still only QUEUED on this frame...
        self.assertEqual([e for e in scene.by_tag("enemy") if e.alive], [])
        self.assertEqual(len(scene.queued_by_tag("enemy")), 3)
        # ...so the round must NOT have ended under them.
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

        scene.update(0.0)                       # children go live
        self.assertEqual(len([e for e in scene.by_tag("enemy") if e.alive]), 3)
        frame(session, scene, tm, 0.0)
        self.assertEqual(session.state.phase, GamePhase.ENEMY)

    def test_the_round_still_ends_once_the_children_are_gone(self):
        """The guard must not wedge the round open — with nothing left to spawn
        and nothing alive, the wave clears exactly as before. The burst is
        RAIDERS here (stock `enabled: false`) so the children die quietly instead
        of chain-bursting into a wave that never drains."""
        balance = with_death_spawn(
            "Standard", at_hp_fraction=0.0, enabled=True,
            spawn_hp_fraction=1.0,
            spawns=[{"raiders": 3, "regular": 0, "siege": 0}])
        tm, scene, occ = build_board(["bs"])
        session = armed_session(tm, scene, occ, balance)
        enemy = create_enemy("standard", 1, 0, balance, tm)
        scene.spawn(enemy)
        scene.update(0.0)

        enemy.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)   # burst; round holds
        self.assertEqual(session.state.phase, GamePhase.ENEMY)
        scene.update(0.0)
        for child in [e for e in scene.by_tag("enemy") if e.alive]:
            child.get_component(Health).damage(10 ** 9)
        frame(session, scene, tm, 0.0)   # children die; they spawn nothing
        self.assertEqual(scene.queued_by_tag("enemy"), [])
        self.assertEqual(session.state.phase, GamePhase.ROUND_END)


if __name__ == "__main__":
    unittest.main()
