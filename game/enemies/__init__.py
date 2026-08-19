"""game.enemies — the enemy walker, wave spawner, and combat sweep (Phase 9E).

Pure Python (no pygame); combat runs headless for the HP-ledger tests. See
``game/CLAUDE.md`` for the component/subclass line and the projectile semantics.
"""
from .combat import Projectile, ProjectileHoming, attack_interval, resolve_combat
from .components import (
    BUFF_DECAY_SECONDS, BURROW_EMERGE, BURROW_SUBMERGED, BURROW_WALKING,
    CARRY_OFFSET_TILES, BuffState, BurrowAgent, DeathSpawn, DrummerAura,
    EnemyCombat, Kidnap, PathAgent, buff_total,
)
from .corpse import DEATH_ANIM, Corpse, spawn_corpse
from .crowd_spacing import CrowdSpacing, apply_crowd_spacing, restore_crowd_positions
from .dirt_pile import DIRT_PILE_SLOT, DirtPile, spawn_dirt_pile
from .enemy import (
    Boss, Commander, Digger, Drummer, Enemy, Formation, Raider, SiegeCannon,
    Sniper, create_enemy, variant_slot,
)
from .kidnap import (
    KIDNAP_ANIM, RESCUE_FLIGHT_SECONDS, RESCUE_TAG, KidnapReturnFlight,
    begin_kidnap, release_kidnap, revive_rescued_building, set_kidnap_pose,
)
from .sounds import ATTACK, DEATH, SPAWN, play_enemy_sound, slot_for
from .spawner import Spawner

__all__ = [
    "ATTACK",
    "BUFF_DECAY_SECONDS",
    "BURROW_EMERGE",
    "BURROW_SUBMERGED",
    "BURROW_WALKING",
    "Boss",
    "BuffState",
    "BurrowAgent",
    "CARRY_OFFSET_TILES",
    "Commander",
    "Corpse",
    "CrowdSpacing",
    "DEATH",
    "DEATH_ANIM",
    "DIRT_PILE_SLOT",
    "DeathSpawn",
    "Digger",
    "DirtPile",
    "Drummer",
    "DrummerAura",
    "Enemy",
    "EnemyCombat",
    "Formation",
    "KIDNAP_ANIM",
    "Kidnap",
    "KidnapReturnFlight",
    "PathAgent",
    "RESCUE_FLIGHT_SECONDS",
    "RESCUE_TAG",
    "Projectile",
    "ProjectileHoming",
    "Raider",
    "SPAWN",
    "SiegeCannon",
    "Sniper",
    "Spawner",
    "apply_crowd_spacing",
    "attack_interval",
    "begin_kidnap",
    "buff_total",
    "create_enemy",
    "play_enemy_sound",
    "release_kidnap",
    "revive_rescued_building",
    "resolve_combat",
    "restore_crowd_positions",
    "set_kidnap_pose",
    "slot_for",
    "spawn_corpse",
    "spawn_dirt_pile",
    "variant_slot",
]
