"""Enemy — the walker hierarchy (Phase 9E).

``Enemy(GameObject)`` wires the engine locomotion/sensing components
(``Health`` / ``Movement`` / ``SpriteAnimator`` / ``RangeSensor``) plus the game
components ``PathAgent`` + ``EnemyCombat``. All state is in components (E-11);
the duck-typed values the combat sweep reads (``alive`` / ``dmg``) are guard-safe
``@property``s over ``Health`` / ``EnemyCombat``.

Standard is the only walker enabled in 9E; ``Raider`` / ``SiegeCannon`` / ``Boss``
are thin subclasses present for the spawner's (zeroed) branches — they resolve
their own stat subtree + slot prefix and nothing else (10F/10G enable them).

Scale-tier stats are resolved at CONSTRUCTION into component fields (prototype
``enemy.py:88-108``): ``hp``/``dmg``/``speed`` = the type's base plus the
cumulative sum of ``EnemyScaling.scale_tiers[0..tier)`` bonuses. Movement is in
fractional tile coords (``move_speed`` tiles/sec straight into ``Movement.speed``
— no ×32 pixel conversion; that lived in the prototype's pixel space).

Sprite slots are registry-group-driven (prototype ``_STAGE_SLOT_PREFIX`` +
``_variant``): each type's ``data/slots.json`` group holds one era subgroup per
scaling tier (``REGISTRY_GROUP`` names it), each era listing its variant slots.
At construction the enemy clamps its tier to an era index and picks a random
variant from that era (``rng`` threaded from the spawner for determinism) — so a
walker rolls between ``enemy_stage_1_v1``/``_v2`` on spawn, and dropping a
``_v3`` slot into the era grows the pool with no code change. Absent a registry
(headless stat/logic tests) it falls back to ``DEFAULT_SLOT``.
"""
import random

from engine.core import (
    GameObject, Health, Movement, RangeSensor, SpriteAnimator, Transform,
)
from game.map.pathfinder import find_path, find_path_ignoring_walls
from .components import BossState, EnemyCombat, PathAgent


def variant_slot(registry, group_label, tier, rng=None, fallback=None):
    """Random variant slot for ``group_label`` at the era matching ``tier``.

    The type's registry group (``data/slots.json`` enemies category) lists eras
    as ordered children; ``tier`` clamps to an era index and one of that era's
    variant slots is chosen via ``rng`` (module ``random`` if None). Returns
    ``fallback`` when no registry / group / variants are available so headless
    tests that construct enemies without art still work."""
    if registry is None:
        return fallback
    try:
        eras = registry.group("enemies", (group_label,)).children
    except KeyError:
        return fallback
    if not eras:
        return fallback
    era = eras[min(max(tier, 0), len(eras) - 1)]
    variants = registry.group_slots("enemies", (group_label, era.label))
    if not variants:
        return fallback
    return (rng or random).choice(variants)


class Enemy(GameObject):
    ETYPE = "standard"
    REGISTRY_GROUP = "Walker"      # data/slots.json enemies group (era subtree)
    DEFAULT_SLOT = "enemy_stage_1_v1"  # no-registry fallback (headless tests)
    STAT_SUBTREE = ("Standard",)  # under EnemyTypes; scaled by scale_tiers

    def __init__(self, col, row, enemies_balance, tilemap, tier=0,
                 registry=None, rng=None):
        hp, dmg, speed, attack_speed, attack_range = self._resolve_stats(
            enemies_balance, tier)
        slot = variant_slot(registry, self.REGISTRY_GROUP, tier, rng,
                            self.DEFAULT_SLOT)
        components = [
            Health(max_hp=hp, hp=hp),
            PathAgent(),
            Movement(speed=speed),
            EnemyCombat(dmg=dmg, attack_speed=attack_speed),
            RangeSensor(range_tiles=attack_range),
            SpriteAnimator(slot_key=slot, animation="walk",
                           phase_ms=(col * 137 + row * 251) % 2000),
        ]
        super().__init__(
            name=self.ETYPE,
            tags=("enemy",),
            transform=Transform(wx=float(col), wy=float(row)),
            components=components,
        )
        # Transient caches (E-11 allows underscore attrs; non-authoritative).
        self._balance = enemies_balance
        self._tilemap = tilemap
        self._col = col
        self._row = row
        self._enemy_tier = tier
        pa = self.get_component(PathAgent)
        pa._tilemap = tilemap
        pa._real_speed = speed

    # -- stat resolution (Standard scales; subclasses override) ------------

    def _resolve_stats(self, balance, tier):
        std = balance["EnemyTypes"]["Standard"]
        tiers = balance["EnemyScaling"]["scale_tiers"]
        n = min(tier, len(tiers))
        hp = std["hp"] + sum(tiers[i]["hp"] for i in range(n))
        dmg = std["dmg"] + sum(tiers[i]["dmg"] for i in range(n))
        speed = std["move_speed"] + sum(tiers[i]["speed"] for i in range(n))
        return hp, dmg, speed, std["attack_speed"], std["attack_range_tiles"]

    # -- lifecycle ---------------------------------------------------------

    def on_spawn(self):
        """Request a path to the base and load it as tile-coord waypoints."""
        path = find_path(self._tilemap, self._col, self._row)
        if not path:
            path = find_path_ignoring_walls(
                self._tilemap, self._col, self._row)
        mv = self.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        mv.index = 0
        mv.arrived = False

    # -- duck-typed contract read by the combat sweep ----------------------

    @property
    def alive(self):
        return not self.get_component(Health).is_dead

    @property
    def dmg(self):
        return self.get_component(EnemyCombat).dmg


class Raider(Enemy):
    ETYPE = "raider"
    REGISTRY_GROUP = "Raider"
    DEFAULT_SLOT = "raider_stage_1"

    def _resolve_stats(self, balance, tier):
        r = balance["EnemyTypes"]["Raider"]
        return (r["hp"], r["dmg"], r["move_speed"], r["attack_speed"],
                r["attack_range_tiles"])


class SiegeCannon(Enemy):
    ETYPE = "siege"
    REGISTRY_GROUP = "Siege Cannon"
    DEFAULT_SLOT = "siege_cannon"

    def _resolve_stats(self, balance, tier):
        s = balance["EnemyTypes"]["SiegeCannon"]
        return (s["hp"], s["dmg"], s["move_speed"], s["attack_speed"],
                s["attack_range_tiles"])


class Boss(Enemy):
    ETYPE = "boss"
    REGISTRY_GROUP = "Boss"
    DEFAULT_SLOT = "boss_era_0"

    def __init__(self, col, row, enemies_balance, tilemap, tier=0,
                 registry=None, rng=None):
        # `tier` doubles as the era index for the boss (10G refines this).
        self._era = min(max(tier, 0),
                        len(enemies_balance["EnemyTypes"]["Boss"]["stats"]) - 1)
        super().__init__(col, row, enemies_balance, tilemap, tier,
                         registry, rng)
        self.add_component(BossState(era=self._era))

    def _resolve_stats(self, balance, tier):
        era = min(max(tier, 0),
                  len(balance["EnemyTypes"]["Boss"]["stats"]) - 1)
        st = balance["EnemyTypes"]["Boss"]["stats"][era]
        return (st["hp"], st["dmg"], st["move_speed"], st["attack_speed"],
                st["attack_range_tiles"])


# etype string -> class (the spawner queues etype strings).
ENEMY_CLASSES = {
    "standard": Enemy,
    "raider": Raider,
    "siege": SiegeCannon,
    "boss": Boss,
}


def create_enemy(etype, col, row, enemies_balance, tilemap, tier=0,
                 registry=None, rng=None):
    """Construct an enemy of ``etype`` at ``(col, row)`` (the spawner factory).
    ``registry``/``rng`` drive the random sprite-variant pick (E-34 groups)."""
    return ENEMY_CLASSES[etype](col, row, enemies_balance, tilemap, tier,
                                registry, rng)
