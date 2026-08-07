"""game.enemies — the enemy walker, wave spawner, and combat sweep (Phase 9E).

Pure Python (no pygame); combat runs headless for the HP-ledger tests. See
``game/CLAUDE.md`` for the component/subclass line and the projectile semantics.
"""
from .combat import Projectile, ProjectileHoming, attack_interval, resolve_combat
from .components import (
    BUFF_DECAY_SECONDS, CARRY_OFFSET_TILES, BuffState, DeathSpawn,
    DrummerAura, EnemyCombat, Kidnap, PathAgent, buff_total,
)
from .corpse import DEATH_ANIM, Corpse, spawn_corpse
from .enemy import (
    Boss, Commander, Drummer, Enemy, Formation, Raider, SiegeCannon,
    create_enemy, variant_slot,
)
from .kidnap import KIDNAP_ANIM, begin_kidnap, set_kidnap_pose
from .spawner import Spawner

__all__ = [
    "BUFF_DECAY_SECONDS",
    "Boss",
    "BuffState",
    "CARRY_OFFSET_TILES",
    "Commander",
    "Corpse",
    "DEATH_ANIM",
    "DeathSpawn",
    "Drummer",
    "DrummerAura",
    "Enemy",
    "EnemyCombat",
    "Formation",
    "KIDNAP_ANIM",
    "Kidnap",
    "PathAgent",
    "Projectile",
    "ProjectileHoming",
    "Raider",
    "SiegeCannon",
    "Spawner",
    "attack_interval",
    "begin_kidnap",
    "buff_total",
    "create_enemy",
    "resolve_combat",
    "set_kidnap_pose",
    "spawn_corpse",
    "variant_slot",
]
