"""Enemy — the walker hierarchy (Phase 9E).

``Enemy(GameObject)`` wires the engine locomotion/sensing components
(``Health`` / ``Movement`` / ``SpriteAnimator`` / ``RangeSensor``) plus the game
components ``PathAgent`` + ``EnemyCombat``. All state is in components (E-11);
the duck-typed values the combat sweep reads (``alive`` / ``dmg``) are guard-safe
``@property``s over ``Health`` / ``EnemyCombat``.

``Standard`` / ``Raider`` / ``SiegeCannon`` are all LIVE since 10F, ``Boss``
since 10G (nearest-building hunting with re-path-on-kill, the ``"boss"`` scene
tag), ``Formation`` since ER-4 (the 2×2 marching column that dies at half HP and
scatters regulars — pure data over the ER-1/ER-2/ER-3 mechanics, no new code
path). Each subclass resolves its own stat subtree + slot prefix and little else.

Stats are resolved at CONSTRUCTION into component fields, since ES-2 from the
type's OWN per-era rows (``EnemyTypes.<type>.eras[era]``): fully manual absolute
values per era plus a flat ``per_round`` growth inside the era
(``era_stats`` → ``engine.era_math``). The old cumulative ``scale_tiers`` are
gone; the Raider's "never scales" exception is now DATA (five identical rows),
and ``Boss`` still reads its own ``stats`` table. Movement is in fractional tile
coords (``move_speed`` tiles/sec straight into ``Movement.speed`` — no ×32 pixel
conversion; that lived in the prototype's pixel space).

Sprite slots are registry-group-driven (prototype ``_STAGE_SLOT_PREFIX`` +
``_variant``): each type's ``data/slots.json`` group holds one era subgroup
(``REGISTRY_GROUP`` names it), each era listing its variant slots.
At construction the enemy clamps its era to an era index and picks a random
variant from that era (``rng`` threaded from the spawner for determinism) — so a
walker rolls between ``enemy_stage_1_v1``/``_v2`` on spawn, and dropping a
``_v3`` slot into the era grows the pool with no code change. Absent a registry
(headless stat/logic tests) it falls back to ``DEFAULT_SLOT``.
"""
import random

from engine.era_math import resolve_era_row, stats_at_round
from engine.core import (
    GameObject, Health, Movement, RangeSensor, SpriteAnimator, Transform,
)
from game.map.pathfinder import (
    find_path, find_path_ignoring_walls,
    find_path_to_nearest_non_base_building,
)
from .components import _HUNT_QUERIES, DeathSpawn, EnemyCombat, Kidnap, PathAgent


def variant_slot(registry, group_label, era, rng=None, fallback=None):
    """Random variant slot for ``group_label`` at ``era``.

    The type's registry group (``data/slots.json`` enemies category) lists eras
    as ordered children; ``era`` clamps to an era index and one of that era's
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
    era_group = eras[min(max(era, 0), len(eras) - 1)]
    variants = registry.group_slots("enemies", (group_label, era_group.label))
    if not variants:
        return fallback
    return (rng or random).choice(variants)


def era_stats(type_block, era, position_in_era=1, endgame_factors=None):
    """``type_block``'s stats for ``era`` at ``position_in_era`` (ES-2, D2/D5).

    The type's own ``eras`` row is clamped to the last authored one (past it the
    optional ``endgame_factors`` compound it, D5), then grown by its flat
    ``per_round`` deltas for the position inside the era. NO cumulative tier
    sums exist any more — a row IS the answer. Returns the constructor's
    ``(hp, dmg, move_speed, attack_speed, attack_range_tiles)`` tuple.
    """
    row = resolve_era_row(type_block["eras"], era, endgame_factors)
    st = stats_at_round(row, position_in_era)
    return (st["hp"], st["dmg"], st["move_speed"], st["attack_speed"],
            st["attack_range_tiles"])


class Enemy(GameObject):
    ETYPE = "standard"
    REGISTRY_GROUP = "Walker"      # data/slots.json enemies group (era subtree)
    DEFAULT_SLOT = "enemy_stage_1_v1"  # no-registry fallback (headless tests)
    STAT_SUBTREE = ("Standard",)  # under EnemyTypes; drives EVERY lookup
    EXTRA_TAGS = ()               # extra scene tags beside "enemy" (Boss: 10G)
    # Overhead HP bar, read by game/ui/effects.py; base-zoom px, widths
    # prototype-exact. PAD is only the GAP above the sprite's head — how high
    # the bar actually floats is measured off the sprite as the renderer draws
    # it (footprint-fitted since ER-1), never off the sheet's raw pixels.
    HP_BAR_W, HP_BAR_H, HP_BAR_PAD = 14, 2, 4

    def __init__(self, col, row, enemies_balance, tilemap, era=0,
                 registry=None, rng=None, position_in_era=1):
        hp, dmg, speed, attack_speed, attack_range = self._resolve_stats(
            enemies_balance, era, position_in_era)
        slot = variant_slot(registry, self.REGISTRY_GROUP, era, rng,
                            self.DEFAULT_SLOT)
        block = enemies_balance["EnemyTypes"]
        for seg in self.STAT_SUBTREE:
            block = block[seg]
        ds = block["death_spawn"]
        era = self._resolve_era(enemies_balance, era)
        rows = ds["spawns"]
        spawn_row = rows[min(max(era, 0), len(rows) - 1)]
        components = [
            Health(max_hp=hp, hp=hp),
            PathAgent(footprint=int(block["footprint"]), hunt=block["hunts"]),
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
            # Kidnapping (Art/enemies): LAST — it must tick after both
            # Movement (sees arrival the same frame) and SpriteAnimator (its
            # per-frame clock re-pin wins).
            Kidnap(enabled=bool(block["kidnapping"])),
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
        self._enemy_era = era
        pa = self.get_component(PathAgent)
        pa._tilemap = tilemap
        pa._real_speed = speed
        # Chunk 3: this unit's own path-weight profile, a transient (E-11)
        # beside _tilemap — a dict is not JSON-safe component state. Copied
        # (not aliased) so a caller can never mutate the balancing doc's own
        # dict through it.
        pa._cond_weights = dict(block["condition_path_weights"])

    # -- stat resolution (generic since ES-2; only the Boss overrides) -----

    def _resolve_stats(self, balance, era, position_in_era=1):
        """This type's stats for the round's era, off its OWN ``eras`` rows.

        ES-2 made this ``STAT_SUBTREE``-driven, retiring the trap it used to
        be: it read ``EnemyTypes["Standard"]`` LITERALLY, so every subclass had
        to override it or silently ship walker stats. Raider/SiegeCannon/
        Formation therefore carry no override any more — the Raider's
        "never scales" is five identical era rows in ``data/``, not code."""
        block = balance["EnemyTypes"]
        for seg in self.STAT_SUBTREE:
            block = block[seg]
        return era_stats(block, era, position_in_era)

    def _resolve_era(self, balance, era):
        """Which row of ``death_spawn.spawns`` (and, for the Boss, of
        ``stats``) this unit uses. Types with no era table are always row 0."""
        return 0

    # -- lifecycle ---------------------------------------------------------

    def on_spawn(self):
        """Request a path toward this type's hunt target and load it as
        tile-coord waypoints. The footprint/hunt/weight-profile are read back
        off the component (E-11: state lives in components, never stashed
        ``self._`` fields).

        ``hunt == "base"`` (Standard, Formation) keeps the ORIGINAL walk-to-
        the-hole behaviour byte-for-byte: ``find_path`` with the
        ``find_path_ignoring_walls`` fallback, no ``repath_on_kill``, no
        ``adopt_goal`` call — ``goal_is_base`` stays at its default-True.
        Any other hunt (Chunk 4 — was boss-only, ``Boss.on_spawn`` collapsed
        into this generic version) runs the matching goal-set query
        (``_HUNT_QUERIES``, keyed by ``PathAgent.hunt``) with the SAME
        ``find_path_ignoring_walls`` fallback the boss always used, arms
        ``repath_on_kill`` and calls ``adopt_goal`` — the one site that
        derives ``goal_is_base``/``target_col``/``target_row`` from the
        fresh path, so ``on_spawn`` and ``_repath`` can never drift apart."""
        pa = self.get_component(PathAgent)
        fp = pa.footprint
        cw = pa._cond_weights
        if pa.hunt == "base":
            path = find_path(self._tilemap, self._col, self._row,
                             footprint=fp, cond_weights=cw)
            if not path:
                path = find_path_ignoring_walls(
                    self._tilemap, self._col, self._row, footprint=fp,
                    cond_weights=cw)
            mv = self.get_component(Movement)
            mv.waypoints = [[float(c), float(r)] for c, r in path]
            mv.index = 0
            mv.arrived = False
            return
        query = _HUNT_QUERIES.get(pa.hunt, find_path_to_nearest_non_base_building)
        path = query(self._tilemap, self._col, self._row, footprint=fp,
                     cond_weights=cw)
        if not path:
            path = find_path_ignoring_walls(
                self._tilemap, self._col, self._row, footprint=fp,
                cond_weights=cw)
        mv = self.get_component(Movement)
        mv.waypoints = [[float(c), float(r)] for c, r in path]
        mv.index = 0
        mv.arrived = False
        pa.repath_on_kill = True
        pa.adopt_goal(path, self._tilemap)

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
    # No _resolve_stats override: the Raider "never scales" as DATA now —
    # five identical era rows with zero per_round deltas (ES-2, D6).


class SiegeCannon(Enemy):
    ETYPE = "siege"
    REGISTRY_GROUP = "Siege Cannon"
    DEFAULT_SLOT = "siege_cannon"
    STAT_SUBTREE = ("SiegeCannon",)
    HP_BAR_W = 24                    # prototype siege_cannon.py:145-152


class Formation(Enemy):
    """A marching column — many soldiers moving as one body (ER-4). Two tiles
    square (``footprint: 2``, ER-2 clearance pathing: it only stands where all
    four tiles are clear, so it cannot thread a one-tile gap a walker slips
    through). Its stats come from its own ``eras`` rows like every other type.

    It has NO break state: ``death_spawn.at_hp_fraction`` 0.5 makes ``alive``
    False at half HP (D4 — breaking formation IS dying), and the ER-3 pipeline
    bursts its ``spawns`` row of regulars at ``spawn_hp_fraction`` of their own
    max HP. One code path, one editor form — hence no ``__init__``, no
    ``on_spawn``, no ``_resolve_stats`` (ES-2 made the base one
    ``STAT_SUBTREE``-driven; it used to REQUIRE an override, and
    ``test_enemies.TestFormation`` still pins that its stats come from the
    Formation block) and no ``_resolve_era`` for ``death_spawn`` (it ships a
    single ``spawns`` row and clamps to row 0)."""

    ETYPE = "formation"
    REGISTRY_GROUP = "Formation"
    DEFAULT_SLOT = "formation_stage_1"
    STAT_SUBTREE = ("Formation",)
    HP_BAR_W = 32                    # a 2-tile body; siege 24, boss 48


class Boss(Enemy):
    """The boss (LIVE since 10G). It reads the GLOBAL era straight off the
    clock (the spawner passes it like every other type), clamped to its own
    stat table; it never took the retired scale-tier bonuses either
    (prototype ``boss.py:17-39`` overwrites the
    ``super().__init__(tier=tier)`` stats from ``BOSS_ERAS``). It grinds through
    the player's buildings one at a time — nearest alive NON-BASE building, the
    hole strictly last (D2) — re-pathing every time its target dies, whoever
    killed it; arrival only breaches when the goal IS the base
    (``goal_is_base``).
    ``era``/``death_spawned`` are the duck-typed properties the Session's
    death-spawn stash reads over ``DeathSpawn`` (game/core never imports this
    package). Its 10G swarm is now just the generalised ER-3 mechanic with
    ``at_hp_fraction`` 0.0 + ``spawn_hp_fraction`` 1.0 — same counts, same
    tile, same era."""

    ETYPE = "boss"
    REGISTRY_GROUP = "Boss"
    DEFAULT_SLOT = "boss_era_0"
    STAT_SUBTREE = ("Boss",)
    EXTRA_TAGS = ("boss",)  # scene queries by HUD bar / shake need no host ref
    HP_BAR_W, HP_BAR_H = 48, 4   # prototype boss.py:136-143 max(48, …) floor

    def _resolve_era(self, balance, era):
        # The global era, clamped to the boss's own 5-row table (D5's clamp
        # precedent — the boss had it first).
        return min(max(era, 0),
                   len(balance["EnemyTypes"]["Boss"]["stats"]) - 1)

    def _resolve_stats(self, balance, era, position_in_era=1):
        # The ONE surviving override: the boss's table is `stats[]`, not
        # `eras[]` (its rework is BossReworkPLAN's job, D8).
        st = balance["EnemyTypes"]["Boss"]["stats"][
            self._resolve_era(balance, era)]
        return (st["hp"], st["dmg"], st["move_speed"], st["attack_speed"],
                st["attack_range_tiles"])

    # No on_spawn override (Chunk 4 — collapsed into the generic
    # Enemy.on_spawn): EnemyTypes.Boss.hunts == "any_non_base" is exactly the
    # dispatch it used to hardcode (find_path_to_nearest_non_base_building,
    # the find_path_ignoring_walls fallback, repath_on_kill, adopt_goal) —
    # nothing boss-specific was left once every type could carry its own
    # hunt string. Pinned by tools/tests/test_boss.py.

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


def create_enemy(etype, col, row, enemies_balance, tilemap, era=0,
                 registry=None, rng=None, position_in_era=1):
    """Construct an enemy of ``etype`` at ``(col, row)`` (the spawner factory).

    ``era`` is the global era (stats row, ART era and death-spawn row — ONE
    number, never a second channel); ``position_in_era`` is the round's 1-based
    place inside it, which drives the era row's ``per_round`` growth (D2).
    ``registry``/``rng`` drive the random sprite-variant pick (E-34 groups)."""
    return ENEMY_CLASSES[etype](col, row, enemies_balance, tilemap, era,
                                registry, rng, position_in_era)
