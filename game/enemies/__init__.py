"""game.enemies — the enemy walker, wave spawner, and combat sweep (Phase 9E).

Pure Python (no pygame); combat runs headless for the HP-ledger tests. See
``game/CLAUDE.md`` for the component/subclass line and the projectile semantics.
"""
from .combat import Projectile, ProjectileHoming, attack_interval, resolve_combat
from .components import (
    BURROW_EMERGE, BURROW_SUBMERGED, BURROW_WALKING, CARRY_OFFSET_TILES,
    BurrowAgent, DeathSpawn, EnemyCombat, Kidnap, PathAgent,
)
from .corpse import DEATH_ANIM, Corpse, spawn_corpse
from .dirt_pile import DIRT_PILE_SLOT, DirtPile, spawn_dirt_pile
from .enemy import (
    Boss, Commander, Digger, Enemy, Formation, Raider, SiegeCannon, Sniper,
    create_enemy, variant_slot,
)
from .kidnap import KIDNAP_ANIM, begin_kidnap, set_kidnap_pose
from .spawner import Spawner

__all__ = [
    "BURROW_EMERGE",
    "BURROW_SUBMERGED",
    "BURROW_WALKING",
    "Boss",
    "BurrowAgent",
    "CARRY_OFFSET_TILES",
    "Commander",
    "Corpse",
    "DEATH_ANIM",
    "DIRT_PILE_SLOT",
    "DeathSpawn",
    "Digger",
    "DirtPile",
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
    "spawn_dirt_pile",
    "variant_slot",
]
