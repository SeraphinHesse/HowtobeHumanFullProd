"""game.enemies — the enemy walker, wave spawner, and combat sweep (Phase 9E).

Pure Python (no pygame); combat runs headless for the HP-ledger tests. See
``game/CLAUDE.md`` for the component/subclass line and the projectile semantics.
"""
from .combat import Projectile, ProjectileHoming, attack_interval, resolve_combat
from .components import BossState, EnemyCombat, PathAgent
from .enemy import Boss, Enemy, Raider, SiegeCannon, create_enemy, variant_slot
from .spawner import Spawner

__all__ = [
    "Boss",
    "BossState",
    "Enemy",
    "EnemyCombat",
    "PathAgent",
    "Projectile",
    "ProjectileHoming",
    "Raider",
    "SiegeCannon",
    "Spawner",
    "attack_interval",
    "create_enemy",
    "resolve_combat",
    "variant_slot",
]
