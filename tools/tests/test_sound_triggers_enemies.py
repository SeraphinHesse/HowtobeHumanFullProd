"""SD-5: the enemy sound triggers (death / attack / spawn).

Headless and pure — no pygame, no audio device, no `data/` read and no
`data/` write. `game.enemies.sounds.sfx` is monkeypatched with a recorder,
which is the whole seam (SD-5 adds no `set_*_hook` global), and the
balancing dict is PINNED here rather than read from live `data/`: what a
designer authors into `EnemySounds` must never decide whether this passes.
"""
import os
import random
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from engine.core import Health, Scene, Transform
from engine.core.gameobject import GameObject
from game.enemies import combat as combat_mod
from game.enemies import sounds as sounds_mod
from game.enemies import spawner as spawner_mod
from game.enemies.components import EnemyCombat, PathAgent
from game.enemies.spawner import Spawner


def _slot(*files):
    return {
        "clips": [{"file": f, "volume": 1.0, "start": 0.0, "end": 0.0} for f in files],
        "loop": False,
        "pick": "random",
    }


# Pinned fixture — the shape SD-1 ships, with authored clips only where a
# test needs one. Standard's override is empty on purpose (inherit).
BAL = {
    "EnemySounds": {
        "attack": _slot("default_attack.wav"),
        "death": _slot("default_death.wav"),
        "spawn": _slot(),
    },
    "EnemyTypes": {
        "Standard": {"sounds": {"attack": _slot(), "death": _slot(), "spawn": _slot()}},
        "SiegeCannon": {
            "sounds": {"attack": _slot("cannon.wav"), "death": _slot(), "spawn": _slot()},
        },
        "Boss": {
            "sounds": {
                "attack": _slot("boss_attack.wav"),
                "death": _slot("boss_death.wav"),
                "spawn": _slot("boss_spawn.wav"),
            },
        },
    },
}

SILENT = {
    "EnemySounds": {"attack": _slot(), "death": _slot(), "spawn": _slot()},
    "EnemyTypes": {"Standard": {"sounds": {"attack": _slot(), "death": _slot(),
                                           "spawn": _slot()}}},
}


class FakeSfx:
    """Records `(clip file, key)` per `play_slot`, like the real module."""

    def __init__(self):
        self.plays = []

    def play_slot(self, slot, *, key=None, rng=None, loop=None):
        clips = slot["clips"]
        clip = clips[0] if len(clips) == 1 else (rng or random.Random(0)).choice(clips)
        self.plays.append((clip["file"], key))
        return True

    @property
    def files(self):
        return [f for f, _ in self.plays]


class _StubEnemy(GameObject):
    """The minimum the trigger sites read: a tag, `alive`, `_balance`, and a
    class-level STAT_SUBTREE (the EnemyTypes key — never ETYPE)."""

    STAT_SUBTREE = ("Standard",)
    ETYPE = "standard"
    dmg = 1

    def __init__(self, balance=BAL, alive=True, components=()):
        super().__init__(name="stub", tags=("enemy",),
                         transform=Transform(wx=0.0, wy=0.0),
                         components=list(components))
        # E-11 seals plain attributes on a GameObject; `alive` is a property
        # on the real Enemy too (backed by Health), so mirror that here.
        self._alive = alive
        self._balance = balance

    @property
    def alive(self):
        return self._alive


class _StubSiege(_StubEnemy):
    STAT_SUBTREE = ("SiegeCannon",)
    ETYPE = "siege"


class _StubBoss(_StubEnemy):
    STAT_SUBTREE = ("Boss",)
    ETYPE = "boss"


class _StubBuilding(GameObject):
    """A living victim for the attack branch — `alive` is a property for the
    same E-11 reason as above."""

    def __init__(self):
        super().__init__(name="bld", tags=("building",),
                         components=[Health(max_hp=100, hp=100)])

    @property
    def alive(self):
        return True


class _StubTile:
    col = row = 0
    occupant = None


class _StubTileMap:
    base_col = base_row = 0

    def get(self, col, row):
        return None


class _StubScene:
    """`by_tag` returns nothing; `spawn` just records — enough for the
    spawner's wave pop, which is all §1.3 fires."""

    def __init__(self):
        self.spawned = []

    def by_tag(self, tag):
        return []

    def spawn(self, obj):
        self.spawned.append(obj)


BUILD = {"DefenceBuildings": {"globals": {"min_attack_speed": 0.1,
                                          "projectile_speed_tiles": 5.0}}}
VFX = {"procedural": {"crater": {"life": 1.0}, "projectile": {"lift_frac": 0.0}}}


class SoundTriggerCase(unittest.TestCase):
    def setUp(self):
        self.fake = FakeSfx()
        self._real = sounds_mod.sfx
        sounds_mod.sfx = self.fake

    def tearDown(self):
        sounds_mod.sfx = self._real

    # 1 -- death fires exactly once, at the sweep --------------------------
    def test_death_fires_once_at_the_sweep(self):
        scene = Scene()
        dead = _StubEnemy(alive=False)
        alive = _StubEnemy(alive=True)
        scene.spawn(dead)
        scene.spawn(alive)
        scene.update(0.0)   # E-13: `spawn()` only QUEUES; flush before the sweep
        combat_mod.resolve_combat(scene, _StubTileMap(), 0.1, BUILD, VFX)
        self.assertEqual(self.fake.files, ["default_death.wav"])

    # 2 -- one swing = one attack sound ------------------------------------
    def test_attack_fires_once_per_swing(self):
        target = _StubBuilding()
        owner = _StubEnemy(components=[PathAgent(blocked=True),
                                       EnemyCombat(dmg=1, attack_speed=1.0)])
        pa = owner.get_component(PathAgent)
        pa._target = target
        ec = owner.get_component(EnemyCombat)
        ec.update(0.5)                      # cooldown starts at 0 -> swing
        self.assertEqual(self.fake.files, ["default_attack.wav"])
        ec.update(0.1)                      # still cooling -> silent
        self.assertEqual(self.fake.files, ["default_attack.wav"])

    # 3 -- a non-empty per-type override wins; an empty one inherits -------
    def test_per_type_override_resolution(self):
        self.assertEqual(
            sounds_mod.slot_for(_StubSiege(), sounds_mod.ATTACK)["clips"][0]["file"],
            "cannon.wav")
        self.assertEqual(
            sounds_mod.slot_for(_StubBoss(), sounds_mod.DEATH)["clips"][0]["file"],
            "boss_death.wav")
        # Standard's override is `clips: []` -> inherit the global default.
        self.assertEqual(
            sounds_mod.slot_for(_StubEnemy(), sounds_mod.ATTACK)["clips"][0]["file"],
            "default_attack.wav")

    # 4 -- empty default + empty override = silence, never a raise ---------
    def test_empty_slots_are_a_silent_no_op(self):
        quiet = _StubEnemy(balance=SILENT)
        self.assertIsNone(sounds_mod.slot_for(quiet, sounds_mod.DEATH))
        self.assertFalse(sounds_mod.play_enemy_sound(quiet, sounds_mod.DEATH))
        # No balancing dict at all is silence too, not an AttributeError.
        bare = _StubEnemy(balance=None)
        self.assertFalse(sounds_mod.play_enemy_sound(bare, sounds_mod.SPAWN))
        self.assertEqual(self.fake.plays, [])

    # 5 -- boss spawn at the wave pop; nothing at _spawn_child (§1.3) ------
    def test_boss_spawn_at_wave_pop_but_not_for_children(self):
        made = []

        def fake_create(etype, col, row, *args, **kwargs):
            enemy = _StubBoss() if etype == "boss" else _StubEnemy()
            made.append(enemy)
            return enemy

        real_create = spawner_mod.create_enemy
        spawner_mod.create_enemy = fake_create
        try:
            sp = Spawner()
            sp._rng = random.Random(1234)          # seeded (game/CLAUDE.md)
            sp._queue = [(_StubTile(), "boss", 0.0)]
            sp._timer = 0.0
            scene = _StubScene()
            sp.update(0.1, scene)
            self.assertEqual(self.fake.files, ["boss_spawn.wav"])
            sp._spawn_child(scene, "standard", 0, 0, 1.0)
            self.assertEqual(self.fake.files, ["boss_spawn.wav"])
        finally:
            spawner_mod.create_enemy = real_create


if __name__ == "__main__":
    unittest.main()
