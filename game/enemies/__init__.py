"""game.enemies — the enemy walker, wave spawner, and combat sweep (Phase 9E).

Pure Python (no pygame); combat runs headless for the HP-ledger tests. See
``game/CLAUDE.md`` for the component/subclass line and the projectile semantics.
"""
from .combat import Projectile, ProjectileHoming, attack_interval, resolve_combat
from .components import CARRY_OFFSET_TILES, DeathSpawn, EnemyCombat, Kidnap, PathAgent
from .corpse import DEATH_ANIM, Corpse, spawn_corpse
from .enemy import (
    Boss, Commander, Enemy, Formation, Raider, SiegeCannon, Sniper,
    create_enemy, variant_slot,
)
from .kidnap import KIDNAP_ANIM, begin_kidnap, set_kidnap_pose
from .spawner import Spawner

__all__ = [
    "Boss",
    "CARRY_OFFSET_TILES",
    "Commander",
    "Corpse",
    "DEATH_ANIM",
    "DeathSpawn",
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
    "Sniper",
    "Spawner",
    "attack_interval",
    "begin_kidnap",
    "create_enemy",
    "resolve_combat",
    "set_kidnap_pose",
    "spawn_corpse",
    "variant_slot",
]
