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
path), ``Sniper`` since NE-1 (the first RANGED type: it halts at
``PathAgent.stand_off_range`` tiles from its committed target and fires there,
never closing to melee). Each subclass resolves its own stat subtree + slot
prefix and little else.

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
from .components import (
    _HUNT_QUERIES, BURROW_SUBMERGED, BuffState, BurrowAgent, DeathSpawn,
    DrummerAura, EnemyCombat, Kidnap, PathAgent,
)

# spawn_counts key -> the etype it spawns. The ORDER is load-bearing twice
# over: it fixes how many draws a death burst takes from the injected `rng`
# (variant picks) AND the order children leave a delayed second phase.
# standard -> raider -> siege is the prototype's (game.py:1314-34); BR-3
# appended "commander" LAST for exactly that reason — a new key anywhere
# earlier would move every deterministic wave/burst fixture.
SWARM_TYPES = (("standard", "regular"), ("raider", "raiders"),
               ("siege", "siege"), ("commander", "commander"))

# BR-3 / D4: the animations the staged second phase plays. Missing manifest
# rows are graceful by construction — SpriteAnimator just holds a name string
# and the renderer falls back, so the phase still runs on its timer.
ENDPHASE_ANIM = "endphase"
DEATH_ANIM = "death"


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
    # Which balancing key holds this type's death-spawn block (BR-3): the Boss
    # renamed its to `second_phase` when it grew delayed_spawns/spawn_delay;
    # every other type keeps the plain `death_spawn`. ONE class attr rather
    # than a per-type __init__ override — the resolved fields are identical.
    DEATH_SPAWN_KEY = "death_spawn"
    # NE-2: does this type ever HALT to melee a building blocking its path?
    # False for the Digger alone — see PathAgent.no_melee for why a 0-damage
    # halt would be a permanent soft-lock rather than a slow fight. A class
    # attr, not balancing: it is a property of the type's mechanics (the
    # EXTRA_TAGS / DEATH_SPAWN_KEY shape), not a number a designer tunes.
    NO_MELEE = False
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
        ds = block[self.DEATH_SPAWN_KEY]
        # `_resolve_era` answers exactly ONE question: which row of
        # `death_spawn.spawns` (and, for the Boss, of `stats[]`) this unit
        # uses. It returns 0 for every type with no era table — it is NOT the
        # unit's era, and it must not be assigned back over `era`.
        #
        # It WAS assigned back, and that silently fed 0 into `resolve_fit`
        # below: every era-shaped type's per-era `footprint`/`sprite_scale`
        # was pinned to its era-0 row for good. A Formation is meant to grow
        # 2 -> 2 -> 3 -> 3 -> 4 across eras 0-4 (`game/enemies/CLAUDE.md`);
        # every one of them walked the board as a 2x2. Only the Boss was
        # unaffected, because its `_resolve_era` returns the global era — so
        # the one type with a bespoke override masked the bug for the other
        # eight.
        spawn_era = self._resolve_era(enemies_balance, era)
        era = max(0, int(era))
        # BR-5: WHEN/HOW the phase fires is per-era on the Boss and flat on
        # every other type — one seam, exactly like `resolve_fit`.
        phase = self.resolve_phase_row(ds, spawn_era)
        # BR-4: ONE resolver for every per-era row — the same clamp as before
        # for an authored era, and past the last row the type's endgame factors
        # compound (all 1.0 as shipped, and an int leaf floors back to itself,
        # so this is bit-equal to the old `rows[min(max(era, 0), len - 1)]`).
        spawn_row = resolve_era_row(ds["spawns"], spawn_era,
                                    self.endgame_factors(block))
        footprint, sprite_scale = self.resolve_fit(block, era)
        components = [
            Health(max_hp=hp, hp=hp),
            # NE-3: the buff ledger every enemy carries. FIRST after Health so
            # a contribution that expires this frame has already been undone
            # before PathAgent reads the buffed move speed and EnemyCombat
            # reads the buffed damage/attack clock below. Inert (and near
            # free) on every unit no Drummer has ever reached — the `Kidnap`
            # "declared field, usually inert" shape.
            BuffState(),
            PathAgent(footprint=footprint, hunt=block["hunts"],
                      no_melee=self.NO_MELEE,
                      stand_off_range=self.resolve_stand_off_range(block)),
            # NE-2: the navigation-adjacent slot — AFTER PathAgent (so it can
            # act on the walk/halt decision just made) and BEFORE Movement (so
            # a freeze it applies takes effect the same frame). Empty for every
            # type but the Digger.
            *self.nav_components(block),
            Movement(speed=speed),
            EnemyCombat(dmg=dmg, attack_speed=attack_speed),
            RangeSensor(range_tiles=attack_range),
            SpriteAnimator(slot_key=slot, animation="walk",
                           phase_ms=(col * 137 + row * 251) % 2000,
                           fit_tiles=float(footprint),
                           scale=float(sprite_scale)),
            DeathSpawn(era=spawn_era,
                       enabled=ds["enabled"],
                       at_hp_fraction=float(phase["at_hp_fraction"]),
                       spawn_hp_fraction=float(phase["spawn_hp_fraction"]),
                       counts=dict(spawn_row),
                       # BR-3: absent on every non-Boss `death_spawn` block —
                       # the component defaults ARE the historical one-frame
                       # burst, so `.get` here is a shape fallback, not a
                       # code-side default for an authored value (G-7).
                       delayed=bool(phase.get("delayed_spawns", False)),
                       spawn_delay=float(phase.get("spawn_delay", 0.0))),
            # Kidnapping (Art/enemies): LAST — it must tick after both
            # Movement (sees arrival the same frame) and SpriteAnimator (its
            # per-frame clock re-pin wins).
            Kidnap(enabled=bool(block["kidnapping"])),
        ]
        components.extend(self.extra_components(block))
        super().__init__(
            name=self.ETYPE,
            tags=("enemy",) + self.EXTRA_TAGS,
            transform=Transform(wx=float(col), wy=float(row)),
            components=components,
        )
        # Transient caches (E-11 allows underscore attrs; non-authoritative).
        self._balance = enemies_balance
        self._tilemap = tilemap
        # NE-2 — the SCENE seam, parallel to `_tilemap` above. A GameObject
        # never receives the scene (`Scene.update` calls `on_spawn()` with no
        # arguments), and `Component` cannot reach it either, which is why
        # `CorpseFade._scene`/`Kidnap._scene` are both wired externally by
        # their one transition site. The Digger needs it for TWO things
        # `_tilemap` cannot answer — who else is a live Digger (the exclusive
        # claim) and where to put the dirt pile — so it is cached here once,
        # for the whole type hierarchy, rather than threaded through four call
        # signatures. `Spawner` sets it at both of its construction sites
        # (the wave pop and `_spawn_child`); a hand-built headless enemy leaves
        # it None, which every reader treats as "no scene, no rivals".
        self._scene = None
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

    # -- per-type extra components (NE-3 seam) -----------------------------

    @classmethod
    def extra_components(cls, block):
        """Components only THIS type carries, appended after the shared list.

        The ONE seam for "a type needs a mechanism nothing else has", so a
        subclass never has to reimplement ``__init__`` just to add one
        component (and never has to re-derive the era/stat/fit resolution it
        would have to copy to do that). Base: nothing — every stock type is
        exactly the shared list.

        Kept a ``classmethod`` beside ``resolve_fit``/``endgame_factors``: it
        reads only the already-resolved balancing ``block``, and it is called
        BEFORE ``GameObject.__init__`` has run, so it must not touch instance
        state."""
        return ()

    # -- render fit / footprint (BR-1 seam) --------------------------------

    @classmethod
    def resolve_fit(cls, block, era):
        """``(footprint, sprite_scale)`` for this type at ``era``.

        The ONE seam deciding WHERE a type's render fit lives, so
        ``__init__`` and the spawner's pre-construction ``_footprint_of``
        can never disagree. **Every type's render fit is PER-ERA**: an
        era-shaped type carries the pair in its own ``eras[]`` rows, and the
        Boss overrides this to read its ``stats[]`` table (it has no
        ``eras``). Both were single FLAT keys at the type root until BR-1
        moved the Boss's, and this change moved everyone else's — a designer
        must be able to make a late-era body physically bigger than an early
        one (an era-4 Formation is 4x4 where its era-0 is 2x2).

        Past the last authored era the row clamps: ``endgame_scaling`` carries
        no ``footprint``/``sprite_scale`` factor, deliberately, so a size never
        grows on its own past the table.

        A classmethod, not an instance method: the spawner needs the footprint
        to pick a spawn tile BEFORE the enemy exists."""
        row = resolve_era_row(block["eras"], era, cls.endgame_factors(block))
        return int(row["footprint"]), float(row["sprite_scale"])

    @classmethod
    def nav_components(cls, block):
        """Extra components spliced between ``PathAgent`` and ``Movement``
        (NE-2). ``()`` for every type but the Digger, whose ``BurrowAgent``
        must see the agent's decision for the frame and be able to stop the
        locomotion that would otherwise act on it. A seam rather than an
        ``__init__`` override, for the ``resolve_fit``/``resolve_phase_row``
        reason: the component ORDER is the invariant, and keeping ONE
        construction site is what guarantees it."""
        return ()

    @classmethod
    def resolve_phase_row(cls, ds, era):
        """The block holding ``at_hp_fraction``/``spawn_hp_fraction``/
        ``delayed_spawns``/``spawn_delay`` for this type at ``era`` (BR-5).

        The ONE seam deciding WHERE those four live, the exact shape of
        ``resolve_fit``. Every type but the Boss keeps them FLAT on its
        ``death_spawn`` block (a Formation breaks at half health in era 0 and
        in era 9); the Boss overrides it to pick its ``second_phase.staging``
        row, because D5 wants the era-0 boss to stage at half health while
        eras 1-4 keep firing at actual death."""
        return ds

    @classmethod
    def resolve_stand_off_range(cls, block):
        """How many tiles short of its committed target this type halts and
        opens fire (NE-1) — ``PathAgent.stand_off_range``.

        The same shape as ``resolve_fit``/``endgame_factors``: a SEAM, so the
        `stand_off_range` balancing leaf lives only on the block of a type that
        actually has the mechanic, instead of being forced onto all six other
        `EnemyTypes` entries at 0 just to keep a flat read honest. ``0`` here is
        NOT a code-side default for an authored value (G-7) — it is the
        statement "this type has no stand-off", the exact counterpart of
        ``endgame_factors`` returning ``None`` for everything but the Boss.
        ``Sniper`` is the one override."""
        return 0

    @classmethod
    def endgame_factors(cls, block):
        """Factors compounding onto this type's PER-ERA ROWS past the last one.

        ``None`` for every type but the Boss (BR-4). The other types scale
        their ``eras[]`` stats through ``endgame_scaling`` inside
        ``era_stats``; their ``death_spawn.spawns`` is a single row that
        always clamps, so there is nothing here to scale. The Boss overrides
        it with ``endgame_boss_scaling`` — the ONE block covering its
        ``stats[]``, ``round_counts[]`` and ``second_phase.spawns[]`` alike
        (D1), which is why the factor names are the LEAF names those rows
        carry (``era_math.resolve_era_row`` matches by leaf name)."""
        return None

    # -- stat resolution (generic since ES-2; only the Boss overrides) -----

    def _resolve_stats(self, balance, era, position_in_era=1):
        """This type's stats for the round's era, off its OWN ``eras`` rows.

        ES-2 made this ``STAT_SUBTREE``-driven, retiring the trap it used to
        be: it read ``EnemyTypes["Standard"]`` LITERALLY, so every subclass had
        to override it or silently ship walker stats. Raider/SiegeCannon/
        Formation therefore carry no override any more — the Raider's
        "never scales" is five identical era rows in ``data/``, not code.

        ES-4/D5: past the last authored era the row clamps AND the type's own
        ``endgame_scaling`` factors compound (``value * factor ** N``). Shipped
        all-1.0, so this is exactly the plain clamp until a designer tunes it."""
        block = balance["EnemyTypes"]
        for seg in self.STAT_SUBTREE:
            block = block[seg]
        return era_stats(block, era, position_in_era,
                         block["endgame_scaling"])

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
        byte-identical.

        BR-3: a unit with a DELAYED second phase (the Boss only) stays alive
        from the threshold crossing until its phase completes — this is THE
        site combat, base arrivals and the wave-clear check all read, so
        holding it True here is what keeps the round open and the boss on the
        board for the whole phase without special-casing any of them."""
        ds = self.get_component(DeathSpawn)
        if ds.enabled and ds.delayed and not ds.phase_complete:
            return True
        h = self.get_component(Health)
        return h.hp > h.max_hp * ds.at_hp_fraction

    @property
    def targetable(self):
        """False while this unit is in (or past the threshold of) a delayed
        second phase — D2: fully invulnerable, defenders drop it, in-flight
        projectiles do nothing, no HP bars.

        Derived straight from HP rather than from ``phase_started``, so it
        flips on the SAME frame the crossing blow lands (the transition itself
        only runs on the next spawner tick) and the boss can never eat one
        extra volley. Duck-typed: everything else in the game reads it through
        ``getattr(obj, "targetable", True)``, so buildings and stub enemies are
        untouched."""
        ds = self.get_component(DeathSpawn)
        if not (ds.enabled and ds.delayed):
            return True
        h = self.get_component(Health)
        return h.hp > h.max_hp * ds.at_hp_fraction

    @property
    def dmg(self):
        """What this enemy hits for RIGHT NOW — the raw stat plus any live
        Drummer buff (NE-3, ``EnemyCombat.buffed_dmg``). Unbuffed it returns
        the raw field unchanged, so every pre-NE-3 reader (the base-hit
        branch of the combat sweep, its telemetry) is byte-identical."""
        return self.get_component(EnemyCombat).buffed_dmg

    # -- the delayed second phase (BR-3) -----------------------------------

    def advance_second_phase(self, dt):
        """Drive one frame of the staged second phase; return the etypes whose
        child is due NOW (``()`` on every frame of every ordinary enemy).

        The ONE state machine. Called by ``Spawner._advance_second_phases`` on
        the speed-scaled sim dt, which is also the only thing that turns a
        returned etype into an actual enemy — this method never touches the
        scene, so all construction stays on the spawner's side:

        1. below ``at_hp_fraction`` and not yet started -> freeze (D2/D6);
        2. started -> tick the clock, releasing one child per ``spawn_delay``;
        3. queue drained -> ``phase_complete``, which drops ``alive`` and lets
           the NORMAL death path run (XP, kill count, splatter, corpse).
        """
        ds = self.get_component(DeathSpawn)
        if not (ds.enabled and ds.delayed) or ds.phase_complete:
            return ()
        if not ds.phase_started:
            h = self.get_component(Health)
            if h.hp > h.max_hp * ds.at_hp_fraction:
                return ()
            self._begin_second_phase(ds)
            return ()
        if not ds.pending:
            # The last child left last tick — die through the normal path.
            ds.phase_complete = True
            self._set_phase_anim(DEATH_ANIM)
            return ()
        ds.phase_timer -= dt
        if ds.phase_timer > 0:
            return ()
        if ds.spawn_delay <= 0:      # 0 = release the whole row at once
            due, ds.pending = list(ds.pending), []
            return tuple(due)
        due = []
        while ds.phase_timer <= 0 and ds.pending:
            due.append(ds.pending.pop(0))
            ds.phase_timer += ds.spawn_delay
        return tuple(due)

    def _begin_second_phase(self, ds):
        """Freeze, become untouchable, and lay out the child queue."""
        ds.phase_started = True
        ds.pending = [etype for etype, key in SWARM_TYPES
                      for _ in range(ds.counts.get(key, 0))]
        ds.phase_timer = ds.spawn_delay
        # The phase IS the burst: claim the one-shot guard now so the eventual
        # normal death cannot ALSO stash a `death_spawn_plan` with the Session.
        ds.death_spawned = True
        mv = self.get_component(Movement)
        if mv is not None:
            mv.speed = 0.0
        pa = self.get_component(PathAgent)
        if pa is not None:
            pa.frozen = True
        self._set_phase_anim(ENDPHASE_ANIM)

    def _set_phase_anim(self, name):
        anim = self.get_component(SpriteAnimator)
        if anim is not None and anim.animation != name:
            anim.set_animation(name)

    @property
    def second_phase_child_hp_fraction(self):
        """The fraction of their own max HP second-phase children spawn at —
        the same ``spawn_hp_fraction`` the one-frame burst uses."""
        return self.get_component(DeathSpawn).spawn_hp_fraction

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
    """A marching column — many soldiers moving as one body (ER-4). A
    multi-tile block that GROWS: ``footprint`` is per-era like every other
    number now, and it ships 2, 2, 3, 3, 4 across eras 0-4 (ER-2 clearance
    pathing: it only stands where every tile of its block is clear, so it
    cannot thread a gap a walker slips through, and by era 4 it needs a 4x4).
    Its stats come from its own ``eras`` rows like every other type.

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


class Sniper(Enemy):
    """The Sniper (NE-1) — the first enemy that fights at RANGE.

    Every other type is a melee unit: `attack_range_tiles` exists on all of
    them and is read by nothing on the enemy's own attack path, so they all
    walk until something physically blocks them and then punch it. The Sniper
    walks at the nearest ATTACK-CAPABLE building (`hunts: "defence"` — NE-0
    widened that category from the single `defence` type to mortars, Storm
    Priests and Sun Scorchers too), halts at `stand_off_range` tiles from it,
    and fires on its `attack_speed` cooldown from there. It never closes.

    **It adds no attack code.** The stand-off halt is `PathAgent`'s
    `stand_off_range`/`in_range` pair (both default-off, so the melee path is
    byte-identical for every other type) and the firing is the SAME
    `EnemyCombat.update()` clock, whose gate widened from `blocked` to
    `blocked or in_range`. Re-targeting when its victim dies is likewise the
    existing `repath_on_kill` dead-target watch, which is gated on `not
    blocked` — and a stand-off unit is never blocked, so it fires unchanged.

    **The ranged hit lands instantly on cooldown** (v1): there is no
    projectile-travel system for enemies, and building one was deliberately
    NOT part of this phase. A muzzle/arrow visual is a `/replace-visual` pass.

    Four class attrs plus the one seam override — no `__init__`, no
    `on_spawn`, no `_resolve_stats` (the base `STAT_SUBTREE` resolver reads its
    own `EnemyTypes.Sniper.eras` rows), no `_resolve_era`, no `EXTRA_TAGS`."""

    ETYPE = "sniper"
    REGISTRY_GROUP = "Sniper"
    DEFAULT_SLOT = "sniper_stage_1"
    STAT_SUBTREE = ("Sniper",)

    @classmethod
    def resolve_stand_off_range(cls, block):
        # The ONE override of the NE-1 seam. Flat at the type root like
        # `footprint`/`kidnapping` (D10): standing off at 2 tiles is this
        # type's IDENTITY, not a number that scales with the round, so it is
        # deliberately not an era-row leaf.
        return int(block["stand_off_range"])


class Commander(Enemy):
    """The Commander (BR-2, plan D8) — the boss's officer, DORMANT as shipped.

    A building hunter like the Boss (``hunts: "any_non_base"`` routes it
    through the generic ``Enemy.on_spawn``, which arms
    ``PathAgent.repath_on_kill`` and calls ``adopt_goal`` — so
    ``goal_is_base`` is False while any non-base building stands), sized like
    a walker (``footprint`` 1) with a siege-sized 24×2 overhead bar, and
    carrying NEITHER camera shake NOR the ``"boss"`` scene tag.

    **Deliberately no ``_resolve_stats`` override** (D8): it is a normal
    era-shaped type, so the base ``STAT_SUBTREE``-driven resolver reads its own
    ``EnemyTypes.Commander.eras`` rows. The Boss's is the ONE surviving
    override in this module; ``game/enemies/CLAUDE.md`` used to document
    Formation's pre-ES-2 override as mandatory, so a reader may still expect
    one here — there is none, and there must not be.

    Nothing spawns it yet: every era row ships ``count_start`` /
    ``count_per_round`` at 0, so ``Spawner._commander_group`` emits zero, and
    every ``spawn_counts`` row's ``commander`` is 0. BR-3 wires it to the
    boss's second phase."""

    ETYPE = "commander"
    REGISTRY_GROUP = "Commander"
    DEFAULT_SLOT = "commander_stage_1"
    STAT_SUBTREE = ("Commander",)
    HP_BAR_W, HP_BAR_H = 24, 2       # siege-sized (D8), no boss 48×4 bar


class Tutorial(Enemy):
    """Round 0's forced enemy (add-enemy dispatch, user decision) — split off
    Standard so the tutorial's scripted spawn can be tuned independently of
    the real Walker. It reuses the Walker's registry group/slots (no new art)
    and Standard's era-0 stats verbatim, but ``EnemyTypes.Tutorial.hunts`` is
    ``"any_non_base"`` (Boss/Commander's value) rather than ``"base"``, so it
    targets buildings instead of walking straight at the hole. No override
    needed for that: the generic ``Enemy.on_spawn`` already dispatches on the
    data block's ``hunts`` value (see game/enemies/CLAUDE.md's "Prey hunting"
    section)."""

    ETYPE = "tutorial"
    REGISTRY_GROUP = "Walker"
    DEFAULT_SLOT = "enemy_stage_1_v1"
    STAT_SUBTREE = ("Tutorial",)


class Digger(Enemy):
    """The Digger (NE-2) — the burrower that erupts under a claimed structure.

    The one type that is a genuine new state machine rather than data over the
    existing one. It walks visibly at a structure it has EXCLUSIVELY claimed
    (``hunts: "structure"``), submerges untargetable at ``dig_range_tiles``,
    travels underground, erupts for one large ``dmg`` hit, then re-claims. The
    machine itself is ``BurrowAgent``; this class is the four class attrs, the
    three seams it needs, and nothing else.

    * **``NO_MELEE = True``** — it has no attack outside digging, so a halt on
      an incidental blocker would be a 0-damage soft-lock (``PathAgent.
      no_melee``).
    * **``repath_on_kill`` stays OFF** (hence the ``on_spawn`` override, which
      does NOT call the generic non-base branch): the agent's generic re-path
      would re-run the hunt with no claim exclusion, and would silently accept
      the empty-goal-set fallback to the hole. ``BurrowAgent.retarget`` is the
      only re-targeting path, at spawn and after every eruption alike.
    * **``targetable``** is overridden off the SUBMERGED state — the exact
      duck-typed contract the boss's second phase already uses, so combat
      targeting, in-flight projectiles, the lightning storm and both HP bars
      drop a burrowed Digger with no per-site change.
    * **``kidnapping: false``** in balancing: Diggers do not kidnap.
    """

    ETYPE = "digger"
    REGISTRY_GROUP = "Digger"
    DEFAULT_SLOT = "digger_stage_1"
    STAT_SUBTREE = ("Digger",)
    NO_MELEE = True

    @classmethod
    def nav_components(cls, block):
        return (BurrowAgent(
            dig_range_tiles=int(block["dig_range_tiles"]),
            dig_speed=float(block["dig_speed"]),
            dig_hop_long_tiles=int(block["dig_hop_long_tiles"]),
            dig_hop_short_tiles=int(block["dig_hop_short_tiles"]),
            emerge_cooldown=float(block["emerge_cooldown"]),
            min_target_distance_tiles=int(block["min_target_distance_tiles"])),)

    def _resolve_stats(self, balance, era, position_in_era=1):
        """The era row as usual, with ``move_speed`` REPLACED by the flat
        ``dig_speed`` — the design brief's "one speed value for both phases".
        Doing it here rather than trusting the two to be authored equal is what
        makes overground and underground provably the same number; the era
        rows still carry their own ``move_speed`` because ``$defs/type_era_row``
        requires it and the balancing panel renders it."""
        hp, dmg, _speed, attack_speed, attack_range = super()._resolve_stats(
            balance, era, position_in_era)
        dig_speed = float(balance["EnemyTypes"]["Digger"]["dig_speed"])
        return (hp, dmg, dig_speed, attack_speed, attack_range)

    def on_spawn(self):
        """Claim a structure and walk at it — ``BurrowAgent.retarget``, never
        the generic hunt branch (see the class docstring). Deliberately leaves
        ``PathAgent.repath_on_kill`` at False."""
        burrow = self.get_component(BurrowAgent)
        burrow.retarget(self, self.get_component(PathAgent),
                        self.get_component(Movement), self._tilemap)

    @property
    def targetable(self):
        """False while burrowed — nothing can shoot a Digger underground."""
        burrow = self.get_component(BurrowAgent)
        if burrow is not None and burrow.state == BURROW_SUBMERGED:
            return False
        return super().targetable


class Drummer(Enemy):
    """The Drummer (NE-3) — the game's first SUPPORT enemy.

    It marches at the hole like a walker (``hunts: "base"``, so the generic
    ``Enemy.on_spawn`` takes the original byte-identical walk-to-the-base
    branch: no ``repath_on_kill``, no building hunting) and hits for almost
    nothing. Its whole contribution is the aura: every enemy standing within
    Chebyshev ``support_range`` of it gets a share of its
    ``hp``/``dmg``/``move_speed``/``attack_speed`` increases, stacking
    additively per Drummer and fading 4 seconds after leaving the radius.

    The ONLY thing that makes it different from a walker is one extra
    component (``DrummerAura``) through the ``extra_components`` seam — no
    ``__init__``, no ``on_spawn``, no ``_resolve_stats`` (D8's rule for the
    Commander applies here too: the base ``STAT_SUBTREE`` resolver reads its
    own ``EnemyTypes.Drummer.eras`` rows), no ``_resolve_era``, no
    ``EXTRA_TAGS``. ``sprite_scale`` 1.15 is the brief's "slightly taller"
    cosmetic ask and is pure data.

    Note the ``support_range_increase`` leaf is deliberately NOT read here —
    see ``game/enemies/CLAUDE.md``; it ships as an inert 0 so the data shape
    is future-proof, pending a user decision on whether support range is
    meant to grow at all."""

    ETYPE = "drummer"
    REGISTRY_GROUP = "Drummer"
    DEFAULT_SLOT = "drummer_stage_1"
    STAT_SUBTREE = ("Drummer",)

    @classmethod
    def extra_components(cls, block):
        return (DrummerAura(
            support_range=int(block["support_range"]),
            hp_increase=float(block["hp_increase"]),
            dmg_increase=float(block["dmg_increase"]),
            move_speed_increase=float(block["move_speed_increase"]),
            attack_speed_increase=float(block["attack_speed_increase"]),
        ),)


class Boss(Enemy):
    """The boss (LIVE since 10G). It reads the GLOBAL era straight off the
    clock (the spawner passes it like every other type) and resolves its own
    ``stats[]`` table from it — clamped to the last row in range, and past it
    grown by ``endgame_boss_scaling`` (BR-4); it never took the retired
    scale-tier bonuses either
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
    # BR-3: the boss is the ONE type whose death-spawn block is `second_phase`
    # (death_spawn + delayed_spawns + spawn_delay). Same resolved fields, one
    # extra pair — hence a key, not an __init__ override.
    DEATH_SPAWN_KEY = "second_phase"

    def _resolve_era(self, balance, era):
        # The GLOBAL era, unclamped (BR-4). It used to clamp here to the boss's
        # 5-row table; the clamp now lives one level down, inside
        # `era_math.resolve_era_row`, which needs to know HOW FAR past the last
        # row we are to compound `endgame_boss_scaling`. Clamping here would
        # silently freeze every boss from era 5 on, which is the exact cliff
        # this phase removes.
        return max(0, int(era))

    @classmethod
    def endgame_factors(cls, block):
        # BR-4/D1: ONE block for every per-era boss array.
        return block["endgame_boss_scaling"]

    @classmethod
    def resolve_fit(cls, block, era):
        # Every type's fit is per-era; the Boss's just lives somewhere else.
        # BR-1 put footprint/sprite_scale in its `stats[era]` row with every
        # other boss variable, and it carries no `eras[]` for the base
        # implementation to read. Resolved (clamped, and past the table
        # endgame-scaled) here too, so the spawner can ask before a Boss
        # instance exists.
        st = cls._stat_row(block, era)
        return int(st["footprint"]), float(st["sprite_scale"])

    @classmethod
    def resolve_phase_row(cls, ds, era):
        """The boss's ``second_phase.staging`` row for ``era`` (BR-5).

        Resolved with **no endgame factors** — deliberately the ONE per-era
        boss array that only ever clamps. `resolve_era_row` matches a factor
        to a leaf by NAME, and `endgame_boss_scaling` carries none of these
        four names today, so passing the block would be a silent no-op that
        the next designer to add a matching key would turn into nonsense:
        `at_hp_fraction`/`spawn_hp_fraction` are FRACTIONS, and compounding
        one past era 4 drives it above 1.0, which fires the phase the instant
        the boss spawns. Passing ``None`` says that in the code, not just in
        the schema description."""
        return resolve_era_row(ds["staging"], era, None)

    @classmethod
    def _stat_row(cls, block, era):
        """``EnemyTypes.Boss.stats`` row for ``era`` (BR-4).

        The ONE place a boss stat row is resolved — footprint/sprite_scale
        (``resolve_fit``), the combat stats (``_resolve_stats``) and the shake
        all come through here, so they cannot disagree about which era they
        are. In range it is the authored row itself; past it,
        ``era_math.resolve_era_row`` returns a NEW dict whose leaves are
        ``last * factor ** N`` (``N = era - (len(stats) - 1)``). At the shipped
        all-1.0 factors that is bit-equal to the old plain clamp."""
        return resolve_era_row(block["stats"], era,
                               cls.endgame_factors(block))

    def _resolve_stats(self, balance, era, position_in_era=1):
        # The ONE surviving override: the boss's table is `stats[]`, not
        # `eras[]` (its rework is BossReworkPLAN's job, D8). No `per_round`
        # growth inside an era either — a boss appears once per era.
        st = self._stat_row(balance["EnemyTypes"]["Boss"],
                            self._resolve_era(balance, era))
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
        """The GLOBAL era index (read by tests + any future era-keyed UI).

        Unclamped since BR-4: era 7 is era 7, not "the last authored row".
        Which row that resolves to — and by how much its leaves are scaled —
        is `_stat_row`'s business."""
        return self.get_component(DeathSpawn).era

    @property
    def shake(self):
        """This boss's own ``{interval, strength}`` camera shake (BR-1).

        Per-era since BR-1, so the host reads it off the LIVE boss object it
        already queries by the ``"boss"`` tag (``game/main.py``) rather than
        re-deriving an era from the round number — the boss knows which era it
        is. A plain dict copy: nothing may mutate the balancing doc through
        it. Duck-typed, like ``era``/``death_spawned``."""
        return dict(self._stat_row(
            self._balance["EnemyTypes"]["Boss"], self._enemy_era)["shake"])


# etype string -> class (the spawner queues etype strings).
ENEMY_CLASSES = {
    "standard": Enemy,
    "raider": Raider,
    "siege": SiegeCannon,
    "formation": Formation,
    "sniper": Sniper,
    "commander": Commander,
    "digger": Digger,
    "drummer": Drummer,
    "boss": Boss,
    "tutorial": Tutorial,
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
