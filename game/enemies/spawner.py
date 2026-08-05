"""Spawner — the wave queue (Phase 9E).

Ports the prototype's ``_begin_enemy_phase`` (composition + queue build) and the
``_update_enemy_phase`` spawn loop (``src/core/game.py``). Standard, raider and
siege enemies are all EMITTED since 10F (raiders from ``Raider.start_round``,
siege from ``SiegeCannon.start_round``); the boss is LIVE since 10G — every
boss round (the era clock's ``boss_round_in_era``) composes ``[boss] + ALL
siege + shuffle(standard + raiders)`` from the ``round_counts`` table (falling
back to the normal per-type era-row counts beyond it), and the boss entry's era
is its own. Formations join since ER-4 (from ``Formation.start_round``, mixed
into the shuffled body — never leading the queue, never on a boss round).

Since ES-2 every count and the spawn interval come from the ONE era clock in
``EnemyScaling`` (``rounds_per_era`` / ``boss_round_in_era``) resolved through
``engine.era_math`` — no formula lives in this file any more. Timing is
otherwise prototype-exact: a linear slow→fast
ramp across the wave with a per-enemy ``uniform(0.4, 1.6)`` jitter (or, ramp-off,
a re-rolled jitter per spawn). The round loop that CALLS ``begin_round`` and
detects wave-clear is 9F; 9E exposes the pieces (``begin_round`` / ``update`` /
``active`` / ``done``);
``spawn_death_swarm`` (ER-3) is the Session-driven death burst for ANY type
carrying an enabled ``death_spawn`` (10G's boss swarm is one instance of it).

An ``rng`` is injectable so tests are deterministic (default: the ``random``
module).
"""
import random

from engine import era_math
from engine.core import Health
from game.map.pathfinder import block_tiles

from .enemy import ENEMY_CLASSES, create_enemy

# Raiders + siege went live in 10F; the boss in 10G; the formation in ER-4.
ENABLE_RAIDERS = True
ENABLE_SIEGE = True
ENABLE_BOSS = True
ENABLE_FORMATION = True

# spawn_counts key -> the etype it spawns. The iteration ORDER is load-bearing:
# it fixes how many draws each burst takes from the injected `rng` (variant
# picks), so it must stay standard -> raider -> siege (prototype
# game.py:1314-34).
_SWARM_TYPES = (("standard", "regular"), ("raider", "raiders"),
                ("siege", "siege"))


def _footprint_of(balance, etype):
    """The etype's footprint from balancing (G-7), resolved through the class's
    ``STAT_SUBTREE`` — so a new enemy type needs no change here."""
    block = balance["EnemyTypes"]
    for seg in ENEMY_CLASSES[etype].STAT_SUBTREE:
        block = block[seg]
    return block["footprint"]


class Spawner:
    def __init__(self):
        self._queue = []       # list of (tile, etype, delay | None)
        self._timer = 0.0
        self._interval = 0.0
        self._era = 0          # the round's era (ES-2: era IS the old tier)
        self._round_in_era = 1  # 1-based position inside that era (D2)
        self._round = 0
        self._balance = None
        self._tilemap = None
        self._registry = None
        self._rng = random
        self._boss_era = 0     # era passed as `tier` to a popping boss (10G)
        self._clear_cache = {}  # footprint -> spawn tiles with a clear block

    # -- state ------------------------------------------------------------

    @property
    def active(self):
        """A wave is mid-spawn (queue not yet drained)."""
        return bool(self._queue)

    @property
    def done(self):
        """The queue is drained (the wave is clear once no enemies remain —
        the caller checks the scene; the round loop is 9F)."""
        return not self._queue

    @property
    def enemy_era(self):
        """The round's era — what every stat/count/art lookup is keyed on."""
        return self._era

    @property
    def enemy_tier(self):
        """Alias kept for external readers (the scale TIER became the ERA in
        ES-2; one number, two names)."""
        return self._era

    def pending(self):
        """``(tile, etype)`` for every queued, not-yet-spawned enemy. The round
        loop pays their XP before a lives-mode wipe drops them (10A)."""
        return [(tile, etype) for tile, etype, _ in self._queue]

    def clear(self):
        """Drop the pending wave — a lives-mode base breach ends the round early
        (Session._wipe_round). The already-spawned enemies are cleared by the
        caller from the scene; this just abandons the unspawned queue."""
        self._queue = []
        self._timer = 0.0

    # -- round setup (prototype _begin_enemy_phase) -----------------------

    def begin_round(self, round_num, tilemap, enemies_balance, rng=None,
                    registry=None):
        self._round = round_num
        self._tilemap = tilemap
        self._balance = enemies_balance
        self._registry = registry
        self._rng = rng if rng is not None else random
        self._clear_cache = {}   # the spawn zone recedes between rounds

        scaling = enemies_balance["EnemyScaling"]
        # ES-2/D1: ONE clock. TU-9's round 0 needs no special case here —
        # era_math clamps it to era 0 (D11) instead of the old formula's
        # negative index.
        rounds_per_era = scaling["rounds_per_era"]
        self._era = era_math.era_of_round(round_num, rounds_per_era)
        self._round_in_era = era_math.round_in_era(round_num, rounds_per_era)
        pacing = era_math.resolve_era_row(scaling["eras"], self._era)
        self._interval = max(0.1, pacing["spawn_interval"])

        spawn_tiles = tilemap.spawning_tiles()
        combined = self._compose(round_num, enemies_balance, spawn_tiles)
        self._queue = self._build_queue(combined, scaling)
        if not self._queue:
            self._timer = 0.0
        elif scaling["spawn_ramp_enabled"]:
            self._timer = self._queue[0][2]
        else:
            self._timer = 0.1

    # -- spawn-tile clearance (ER-2) --------------------------------------

    def _pick_spawn_tile(self, spawn_tiles, etype):
        """THE one spawn-tile pick. A footprint-N enemy needs its whole N×N
        block inside the spawn zone; if nothing qualifies it falls back to the
        unfiltered pick, so an enemy is never dropped from the wave. footprint 1
        takes the byte-identical unfiltered choice — same list, same single rng
        draw, so the deterministic composition fixtures are untouched. The
        clearance filter itself consumes NO rng."""
        fp = _footprint_of(self._balance, etype)
        if fp <= 1:
            return self._rng.choice(spawn_tiles)
        clear = self._clear_spawn_tiles(spawn_tiles, fp)
        return self._rng.choice(clear or spawn_tiles)

    def _clear_spawn_tiles(self, spawn_tiles, footprint):
        """Spawn tiles whose whole N×N block is itself spawn zone (membership
        implies in-bounds and passable — a spawning tile weighs 1). Computed
        ONCE per round per footprint: a spawn band can be thousands of tiles."""
        hit = self._clear_cache.get(footprint)
        if hit is None:
            zone = {(t.col, t.row) for t in spawn_tiles}
            hit = [t for t in spawn_tiles
                   if all(b in zone
                          for b in block_tiles(t.col, t.row, footprint))]
            self._clear_cache[footprint] = hit
        return hit

    # -- per-type counts (ES-2: one era-row resolver, no per-type formula) --

    def _count_of(self, balance, type_key, round_num):
        """How many of ``type_key`` this round wants (D3/D3').

        The type's own era row is resolved from the global clock and handed to
        ``era_math.count_at_round``, which floors
        ``count_start + k * count_per_round`` from the era's first ACTIVE round
        ``max(era first round, start_round)`` — the ONE count formula in the
        game, shared by the standard/raider/siege/formation sites AND by
        ``_boss_round``'s past-the-table fallback."""
        block = balance["EnemyTypes"][type_key]
        rounds_per_era = balance["EnemyScaling"]["rounds_per_era"]
        era = era_math.era_of_round(round_num, rounds_per_era)
        row = era_math.resolve_era_row(block["eras"], era)
        return era_math.count_at_round(
            row, round_num, era * rounds_per_era + 1, block["start_round"])

    def _compose(self, round_num, balance, spawn_tiles):
        """Build the (tile, etype) list for the round: standard + raiders +
        siege (10F) + formations (ER-4). Siege leads the queue; everything else
        is shuffled behind it. A boss round (``era_math.is_boss_round``) takes
        the boss composition instead (10G) — the lead/mix siege split applies
        to NON-boss rounds only, and formations do not appear at all (see
        ``_formation_group``).

        ``_formation_group`` is called LAST on purpose: every earlier group's
        rng draw sequence then stays byte-identical, so the standard/raider/
        siege counts and picks are unchanged at every round.

        TU-9: round 0 is the tutorial's forced-composition round — checked
        FIRST, before the boss check (``era_math.is_boss_round`` is already
        False at round 0 for every configuration, D11, but the round-0 branch
        is a COMPOSITION rule and stays ahead of it). It always composes
        exactly
        ``EnemyScaling.tutorial_round_enemy_count`` Standard walkers,
        ignoring every other composition rule."""
        if not spawn_tiles:
            return []
        if round_num == 0:
            n = balance["EnemyScaling"]["tutorial_round_enemy_count"]
            return [(self._pick_spawn_tile(spawn_tiles, "standard"), "standard")
                    for _ in range(n)]
        scaling = balance["EnemyScaling"]
        if ENABLE_BOSS and era_math.is_boss_round(
                round_num, scaling["rounds_per_era"],
                scaling["boss_round_in_era"]):
            return self._boss_round(round_num, balance, spawn_tiles)
        count = self._count_of(balance, "Standard", round_num)
        regular = [(self._pick_spawn_tile(spawn_tiles, "standard"), "standard")
                   for _ in range(count)]

        raiders = self._raider_group(round_num, balance, spawn_tiles)
        siege_front, siege_mixed = self._siege_groups(
            round_num, balance, spawn_tiles)
        formations = self._formation_group(round_num, balance, spawn_tiles)

        rest = regular + raiders + siege_mixed + formations
        self._rng.shuffle(rest)
        return siege_front + rest

    def _boss_round(self, round_num, balance, spawn_tiles):
        """Boss-round composition (10G, prototype ``game.py:831-874``): exactly
        ONE boss leads, then EVERY siege cannon (no lead/mix split), then the
        shuffled standard+raider companions. Counts come from
        ``Boss.round_counts[era]``; beyond the table the normal per-type era-row
        counts (``_count_of``, start-round guards included) take over. The boss
        entry's era is the global era (clamped in ``Boss._resolve_era``);
        companions carry the same era."""
        boss_cfg = balance["EnemyTypes"]["Boss"]
        boss_idx = era_math.era_of_round(
            round_num, balance["EnemyScaling"]["rounds_per_era"])
        self._boss_era = max(0, boss_idx)
        counts = boss_cfg["round_counts"]
        if boss_idx < len(counts):
            row = counts[boss_idx]
            n_regular = row["regular"]
            n_raiders = row["raiders"]
            n_siege = row["siege"]
        else:
            n_regular = self._count_of(balance, "Standard", round_num)
            n_raiders = (self._count_of(balance, "Raider", round_num)
                         if ENABLE_RAIDERS else 0)
            n_siege = (self._count_of(balance, "SiegeCannon", round_num)
                       if ENABLE_SIEGE else 0)
        boss = [(self._pick_spawn_tile(spawn_tiles, "boss"), "boss")]
        siege = [(self._pick_spawn_tile(spawn_tiles, "siege"), "siege")
                 for _ in range(n_siege)]
        rest = ([(self._pick_spawn_tile(spawn_tiles, "standard"), "standard")
                 for _ in range(n_regular)]
                + [(self._pick_spawn_tile(spawn_tiles, "raider"), "raider")
                   for _ in range(n_raiders)])
        self._rng.shuffle(rest)
        return boss + siege + rest

    def _raider_group(self, round_num, balance, spawn_tiles):
        if not ENABLE_RAIDERS:
            return []
        n = self._count_of(balance, "Raider", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "raider"), "raider")
                for _ in range(n)]

    def _siege_groups(self, round_num, balance, spawn_tiles):
        if not ENABLE_SIEGE:
            return [], []
        s = balance["EnemyTypes"]["SiegeCannon"]
        n = self._count_of(balance, "SiegeCannon", round_num)
        siege = [(self._pick_spawn_tile(spawn_tiles, "siege"), "siege")
                 for _ in range(n)]
        lead = min(int(s["queue_lead_count"] * s["mix_ratio"]), len(siege))
        return siege[:lead], siege[lead:]

    def _formation_group(self, round_num, balance, spawn_tiles):
        """Formations from ``Formation.start_round``, accreting at the era
        row's fractional ``count_per_round`` (1/3 = one more every three
        rounds) — a heavy that trickles in, not a swarm that grows linearly.
        Mixed into the shuffled body: unlike siege they do NOT lead
        the queue, because a 2×2 body at the head of the wave would wall the
        choke point before anything else arrived.

        Formations never appear on a boss round — ``_boss_round`` composes from
        ``Boss.round_counts``, a ``$defs/spawn_counts`` table with exactly
        regular/raiders/siege. Adding a formation key there would change every
        death_spawn row too (they share the $def) and break balancing parity.
        Deliberate; see game/enemies/CLAUDE.md."""
        if not ENABLE_FORMATION:
            return []
        n = self._count_of(balance, "Formation", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "formation"), "formation")
                for _ in range(n)]

    def _build_queue(self, combined, scaling):
        """Attach a spawn delay to each (tile, etype). Ramp-on: a linear
        slow→fast interval × ``uniform(0.4, 1.6)`` jitter (prototype
        game.py:911-921). Ramp-off: delay ``None`` (re-rolled per pop)."""
        if not combined:
            return []
        if not scaling["spawn_ramp_enabled"]:
            return [(tile, etype, None) for tile, etype in combined]
        center = self._interval
        span = scaling["spawn_ramp_range"]
        total = len(combined)
        queue = []
        for i, (tile, etype) in enumerate(combined):
            if total > 1:
                ramped = (center + span) - (2.0 * span) * i / (total - 1)
            else:
                ramped = center
            ramped = max(0.1, ramped)
            delay = ramped * self._rng.uniform(0.4, 1.6)
            queue.append((tile, etype, delay))
        return queue

    # -- spawn loop (prototype _update_enemy_phase) -----------------------

    def update(self, dt, scene):
        """Advance the spawn timer; when it expires, pop one enemy and schedule
        the next (prototype pops at most one per tick)."""
        if not self._queue:
            return
        self._timer -= dt
        if self._timer > 0:
            return
        tile, etype, delay = self._queue.pop(0)
        # ES-2: ONE era for stats, art and death-spawn rows alike. The boss
        # takes the era stashed by _boss_round (identical to self._era today —
        # kept separate so a future boss-only clock has a seam).
        era = self._boss_era if etype == "boss" else self._era
        enemy = create_enemy(
            etype, tile.col, tile.row, self._balance, self._tilemap,
            era, self._registry, self._rng, self._round_in_era)
        scene.spawn(enemy)
        if delay is None:
            base = self._interval
            self._timer = max(0.15, self._rng.uniform(base * 0.4, base * 1.6))
        elif self._queue:
            self._timer = self._queue[0][2]
        else:
            self._timer = 0.0

    # -- death spawn (ER-3; 10G's boss swarm generalised) ------------------

    def spawn_death_swarm(self, scene, col, row, plan):
        """Burst ``plan`` — an enemy's resolved ``death_spawn_plan`` — at
        ``(col, row)``, IMMEDIATELY into the scene (never the queue), so the
        children path from that tile on spawn. Members take the CURRENT round's
        era row (the Raider's rows are flat by design). Each child is
        seeded to ``plan["spawn_hp_fraction"]`` of its own max HP; at 1.0 (the
        Boss's 10G swarm) ``Health`` is not touched at all, so that path is
        byte-identical. The Session flushes this before its wave-clear check;
        all enemy construction stays in this package."""
        counts = plan["counts"]
        frac = plan["spawn_hp_fraction"]
        for etype, key in _SWARM_TYPES:
            for _ in range(counts[key]):
                enemy = create_enemy(
                    etype, col, row, self._balance, self._tilemap,
                    self._era, self._registry, self._rng, self._round_in_era)
                if frac < 1.0:
                    health = enemy.get_component(Health)
                    health.hp = max(1, int(health.max_hp * frac))
                scene.spawn(enemy)
