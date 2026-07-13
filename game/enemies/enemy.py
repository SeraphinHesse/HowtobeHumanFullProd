"""Enemy — the walker hierarchy (Phase 9E).

``Enemy(GameObject)`` wires the engine locomotion/sensing components
(``Health`` / ``Movement`` / ``SpriteAnimator`` / ``RangeSensor``) plus the game
components ``PathAgent`` + ``EnemyCombat``. All state is in components (E-11);
the duck-typed values the combat sweep reads (``alive`` / ``dmg``) are guard-safe
``@property``s over ``Health`` / ``EnemyCombat``.

``Standard`` / ``Raider`` / ``SiegeCannon`` are all LIVE since 10F, ``Boss``
since 10G (era stats via tier-as-era, nearest-building hunting with
re-path-on-kill, the ``"boss"`` scene tag), ``Formation`` since ER-4 (the 2×2
marching column that dies at half HP and scatters regulars — pure data over the
ER-1/ER-2/ER-3 mechanics, no new code path). Each subclass resolves its own stat
subtree + slot prefix and little else.

Scale-tier stats are resolved at CONSTRUCTION into component fields (prototype
``enemy.py:88-108``): ``hp``/``dmg``/``speed`` = the type's base plus the
cumulative sum of ``EnemyScaling.scale_tiers[0..tier)`` bonuses — Standard and
SiegeCannon scale that way, ``Raider`` deliberately does NOT, and ``Boss`` reads a
per-era table (see ``tier_scaled_stats``). Movement is in
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
from game.map.pathfinder import (
    find_path, find_path_ignoring_walls, find_path_to_nearest_building,
)
from .components import DeathSpawn, EnemyCombat, PathAgent


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


def tier_scaled_stats(type_block, balance, tier):
    """``type_block``'s base stats plus the cumulative sum of
    ``EnemyScaling.scale_tiers[0..tier)`` (prototype ``enemy.py:88-100``).

    Standard AND SiegeCannon scale this way; ``Raider`` deliberately does not
    (prototype ``raider.py`` overrides the stats without adding tier bonuses),
    and ``Boss`` reads a per-era table instead of scaling at all.
    """
    tiers = balance["EnemyScaling"]["scale_tiers"]
    n = min(tier, len(tiers))
    hp = type_block["hp"] + sum(tiers[i]["hp"] for i in range(n))
    dmg = type_block["dmg"] + sum(tiers[i]["dmg"] for i in range(n))
    speed = type_block["move_speed"] + sum(tiers[i]["speed"] for i in range(n))
    return (hp, dmg, speed, type_block["attack_speed"],
            type_block["attack_range_tiles"])


class Enemy(GameObject):
    ETYPE = "standard"
    REGISTRY_GROUP = "Walker"      # data/slots.json enemies group (era subtree)
    DEFAULT_SLOT = "enemy_stage_1_v1"  # no-registry fallback (headless tests)
    STAT_SUBTREE = ("Standard",)  # under EnemyTypes; scaled by scale_tiers
    EXTRA_TAGS = ()               # extra scene tags beside "enemy" (Boss: 10G)
    # Overhead HP bar, read by game/ui/effects.py; base-zoom px, widths
    # prototype-exact. PAD is only the GAP above the sprite's head — how high
    # the bar actually floats is measured off the sprite as the renderer draws
    # it (footprint-fitted since ER-1), never off the sheet's raw pixels.
    HP_BAR_W, HP_BAR_H, HP_BAR_PAD = 14, 2, 4

    def __init__(self, col, row, enemies_balance, tilemap, tier=0,
                 registry=None, rng=None):
        hp, dmg, speed, attack_speed, attack_range = self._resolve_stats(
            enemies_balance, tier)
        slot = variant_slot(registry, self.REGISTRY_GROUP, tier, rng,
                            self.DEFAULT_SLOT)
        block = enemies_balance["EnemyTypes"]
        for seg in self.STAT_SUBTREE:
            block = block[seg]
        ds = block["death_spawn"]
        era = self._resolve_era(enemies_balance, tier)
        rows = ds["spawns"]
        spawn_row = rows[min(max(era, 0), len(rows) - 1)]
        components = [
            Health(max_hp=hp, hp=hp),
            PathAgent(footprint=int(block["footprint"])),
            Movement(speed=speed),
            EnemyCombat(dmg=dmg, attack_speed=attack_speed),
            RangeSensor(range_tiles=attack_range),
            SpriteAnimator(slot_key=slot, animation="walk",
                           phase_ms=(col * 137 + row * 251) % 2000,
                           fit_tiles=float(block["footprint"]),
                           scale=float(block["sprite_scale"])),
            DeathSpawn(era=era,
                       enabled=ds["enabled"],
                       at_hp_fraction=float(ds["at_hp_fraction"]),
                       spawn_hp_fraction=float(ds["spawn_hp_fraction"]),
                       counts=dict(spawn_row)),
        ]
        super().__init__(
            name=self.ETYPE,
            tags=("enemy",) + self.EXTRA_TAGS,
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
        return tier_scaled_stats(
            balance["EnemyTypes"]["Standard"], balance, tier)

    def _resolve_era(self, balance, tier):
        """Which row of ``death_spawn.spawns`` (and, for the Boss, of
        ``stats``) this unit uses. Types with no era table are always row 0."""
        return 0

    # -- lifecycle ---------------------------------------------------------

    def on_spawn(self):
        """Request a path to the base and load it as tile-coord waypoints. The
        footprint is read back off the component (E-11: state lives in
        components, never a stashed ``self._footprint``)."""
        fp = self.get_component(PathAgent).footprint
        path = find_path(self._tilemap, self._col, self._row, footprint=fp)
        if not path:
            path = find_path_ignoring_walls(
                self._tilemap, self._col, self._row, footprint=fp)
        mv = self.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        mv.index = 0
        mv.arrived = False

    # -- duck-typed contract read by the combat sweep ----------------------

    @property
    def alive(self):
        """Dead once HP falls to or below ``at_hp_fraction`` of max (ER-3 / D4:
        breaking formation IS dying — one code path, no separate break state).
        At the default ``at_hp_fraction`` 0.0 this is exactly
        ``not Health.is_dead`` (``hp <= 0``), so every pre-ER-3 type is
        byte-identical."""
        h = self.get_component(Health)
        ds = self.get_component(DeathSpawn)
        return h.hp > h.max_hp * ds.at_hp_fraction

    @property
    def dmg(self):
        return self.get_component(EnemyCombat).dmg

    # -- duck-typed contract read by Session.on_enemy_death (ER-3) ----------

    @property
    def death_spawn_plan(self):
        """The burst this unit leaves behind, or ``None`` when it carries no
        ENABLED ``death_spawn``. Plain, already-resolved data: the Session
        stashes it and hands it straight back to
        ``Spawner.spawn_death_swarm`` without ever inspecting it, so
        ``game/core`` still imports nothing from ``game/enemies``."""
        ds = self.get_component(DeathSpawn)
        if not ds.enabled:
            return None
        return {"counts": dict(ds.counts),
                "spawn_hp_fraction": ds.spawn_hp_fraction}

    @property
    def death_spawned(self):
        return self.get_component(DeathSpawn).death_spawned

    def mark_death_spawned(self):
        """One-shot burst guard setter. A METHOD, not a property setter — the
        E-11 ``GameObject.__setattr__`` guard intercepts public attribute
        assignment before a data descriptor would run."""
        self.get_component(DeathSpawn).death_spawned = True


class Raider(Enemy):
    ETYPE = "raider"
    REGISTRY_GROUP = "Raider"
    DEFAULT_SLOT = "raider_stage_1"
    STAT_SUBTREE = ("Raider",)

    def _resolve_stats(self, balance, tier):
        # Raiders do NOT take the scale-tier bonuses (prototype raider.py).
        r = balance["EnemyTypes"]["Raider"]
        return (r["hp"], r["dmg"], r["move_speed"], r["attack_speed"],
                r["attack_range_tiles"])


class SiegeCannon(Enemy):
    ETYPE = "siege"
    REGISTRY_GROUP = "Siege Cannon"
    DEFAULT_SLOT = "siege_cannon"
    STAT_SUBTREE = ("SiegeCannon",)
    HP_BAR_W = 24                    # prototype siege_cannon.py:145-152

    def _resolve_stats(self, balance, tier):
        # Siege scales with the tiers exactly like Standard (prototype
        # siege_cannon.py adds the same cumulative ENEMY_SCALE_TIERS bonuses).
        return tier_scaled_stats(
            balance["EnemyTypes"]["SiegeCannon"], balance, tier)


class Formation(Enemy):
    """A marching column — many soldiers moving as one body (ER-4). Two tiles
    square (``footprint: 2``, ER-2 clearance pathing: it only stands where all
    four tiles are clear, so it cannot thread a one-tile gap a walker slips
    through). It takes the scale-tier bonuses exactly like Standard/Siege.

    It has NO break state: ``death_spawn.at_hp_fraction`` 0.5 makes ``alive``
    False at half HP (D4 — breaking formation IS dying), and the ER-3 pipeline
    bursts its ``spawns`` row of regulars at ``spawn_hp_fraction`` of their own
    max HP. One code path, one editor form — hence no ``__init__``, no
    ``on_spawn``, no ``_resolve_era`` (it is not era-indexed: it inherits row 0
    and ships a single ``spawns`` row)."""

    ETYPE = "formation"
    REGISTRY_GROUP = "Formation"
    DEFAULT_SLOT = "formation_stage_1"
    STAT_SUBTREE = ("Formation",)
    HP_BAR_W = 32                    # a 2-tile body; siege 24, boss 48

    def _resolve_stats(self, balance, tier):
        # MANDATORY override: the base Enemy._resolve_stats reads the
        # `Standard` block LITERALLY (STAT_SUBTREE does not drive it), so an
        # un-overridden Formation would silently ship walker stats. Scales with
        # the tiers exactly like Standard and SiegeCannon.
        return tier_scaled_stats(
            balance["EnemyTypes"]["Formation"], balance, tier)


class Boss(Enemy):
    """The boss (LIVE since 10G). ``tier`` doubles as the ERA index — the
    spawner passes ``round // interval - 1``, clamped to the stat table; NO
    scale-tier bonuses ever apply (prototype ``boss.py:17-39`` overwrites the
    ``super().__init__(tier=tier)`` stats from ``BOSS_ERAS``). It hunts the
    nearest alive building (base included) and re-paths every time its target
    dies; arrival only breaches when the goal IS the base (``goal_is_base``).
    ``era``/``death_spawned`` are the duck-typed properties the Session's
    death-spawn stash reads over ``DeathSpawn`` (game/core never imports this
    package). Its 10G swarm is now just the generalised ER-3 mechanic with
    ``at_hp_fraction`` 0.0 + ``spawn_hp_fraction`` 1.0 — same counts, same
    tile, same tier."""

    ETYPE = "boss"
    REGISTRY_GROUP = "Boss"
    DEFAULT_SLOT = "boss_era_0"
    STAT_SUBTREE = ("Boss",)
    EXTRA_TAGS = ("boss",)  # scene queries by HUD bar / shake need no host ref
    HP_BAR_W, HP_BAR_H = 48, 4   # prototype boss.py:136-143 max(48, …) floor

    def _resolve_era(self, balance, tier):
        # `tier` doubles as the era index for the boss (spawner-threaded, 10G).
        return min(max(tier, 0),
                   len(balance["EnemyTypes"]["Boss"]["stats"]) - 1)

    def _resolve_stats(self, balance, tier):
        st = balance["EnemyTypes"]["Boss"]["stats"][
            self._resolve_era(balance, tier)]
        return (st["hp"], st["dmg"], st["move_speed"], st["attack_speed"],
                st["attack_range_tiles"])

    def on_spawn(self):
        """Path to the nearest ALIVE building of any type — base included
        (prototype ``boss.py:49-97`` via ``find_path_to_nearest_building``,
        ported at ``game/map/pathfinder.py``). Arms the 10G ``PathAgent``
        flags: re-path when the attack target dies, and never count arrival
        at a non-base goal as a breach."""
        path = find_path_to_nearest_building(
            self._tilemap, self._col, self._row)
        if not path:
            path = find_path_ignoring_walls(
                self._tilemap, self._col, self._row)
        mv = self.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        mv.index = 0
        mv.arrived = False
        pa = self.get_component(PathAgent)
        pa.repath_on_kill = True
        pa.goal_is_base = (bool(path) and path[-1] == (
            self._tilemap.base_col, self._tilemap.base_row))

    @property
    def era(self):
        """The era index (read by tests + any future era-keyed UI)."""
        return self.get_component(DeathSpawn).era


# etype string -> class (the spawner queues etype strings).
ENEMY_CLASSES = {
    "standard": Enemy,
    "raider": Raider,
    "siege": SiegeCannon,
    "formation": Formation,
    "boss": Boss,
}


def create_enemy(etype, col, row, enemies_balance, tilemap, tier=0,
                 registry=None, rng=None):
    """Construct an enemy of ``etype`` at ``(col, row)`` (the spawner factory).
    ``registry``/``rng`` drive the random sprite-variant pick (E-34 groups)."""
    return ENEMY_CLASSES[etype](col, row, enemies_balance, tilemap, tier,
                                registry, rng)
