"""Spawner — the wave queue (Phase 9E).

Ports the prototype's ``_begin_enemy_phase`` (composition + queue build) and the
``_update_enemy_phase`` spawn loop (``src/core/game.py``). Standard, raider and
siege enemies are all EMITTED since 10F (raiders from ``Raider.start_round``,
siege from ``SiegeCannon.start_round``); the boss is LIVE since 10G — every
``Boss.round_interval``-th round composes ``[boss] + ALL siege +
shuffle(standard + raiders)`` from the ``round_counts`` table (falling back to
the three normal per-type formulas beyond it), and the boss entry's tier IS its
era. Timing is prototype-exact: a linear slow→fast ramp across the wave
with a per-enemy ``uniform(0.4, 1.6)`` jitter (or, ramp-off, a re-rolled jitter
per spawn). The round loop that CALLS ``begin_round`` and detects wave-clear is
9F; 9E exposes the pieces (``begin_round`` / ``update`` / ``active`` / ``done``);
``spawn_death_swarm`` (ER-3) is the Session-driven death burst for ANY type
carrying an enabled ``death_spawn`` (10G's boss swarm is one instance of it).

An ``rng`` is injectable so tests are deterministic (default: the ``random``
module).
"""
import random

from engine.core import Health

from .enemy import create_enemy

# Raiders + siege went live in 10F; the boss in 10G.
ENABLE_RAIDERS = True
ENABLE_SIEGE = True
ENABLE_BOSS = True

# spawn_counts key -> the etype it spawns. The iteration ORDER is load-bearing:
# it fixes how many draws each burst takes from the injected `rng` (variant
# picks), so it must stay standard -> raider -> siege (prototype
# game.py:1314-34).
_SWARM_TYPES = (("standard", "regular"), ("raider", "raiders"),
                ("siege", "siege"))


class Spawner:
    def __init__(self):
        self._queue = []       # list of (tile, etype, delay | None)
        self._timer = 0.0
        self._interval = 0.0
        self._tier = 0
        self._round = 0
        self._balance = None
        self._tilemap = None
        self._registry = None
        self._rng = random
        self._boss_era = 0     # era passed as `tier` to a popping boss (10G)

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
    def enemy_tier(self):
        return self._tier

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

        scaling = enemies_balance["EnemyScaling"]
        tiers = scaling["scale_tiers"]
        self._tier = (round_num - 1) // scaling["scale_every_n_levels"]
        n = min(self._tier, len(tiers))
        interval = scaling["spawn_interval"] - sum(
            tiers[i]["spawn_interval"] for i in range(n))
        self._interval = max(0.1, interval)

        spawn_tiles = tilemap.spawning_tiles()
        combined = self._compose(round_num, enemies_balance, spawn_tiles)
        self._queue = self._build_queue(combined, scaling)
        if not self._queue:
            self._timer = 0.0
        elif scaling["spawn_ramp_enabled"]:
            self._timer = self._queue[0][2]
        else:
            self._timer = 0.1

    def _compose(self, round_num, balance, spawn_tiles):
        """Build the (tile, etype) list for the round: standard + raiders +
        siege (10F). Siege leads the queue; everything else is shuffled behind
        it. Every ``Boss.round_interval``-th round takes the boss composition
        instead (10G) — the lead/mix siege split applies to NON-boss rounds
        only."""
        if not spawn_tiles:
            return []
        if (ENABLE_BOSS and round_num
                % balance["EnemyTypes"]["Boss"]["round_interval"] == 0):
            return self._boss_round(round_num, balance, spawn_tiles)
        scaling = balance["EnemyScaling"]
        count = scaling["base_enemy_count"] + (round_num - 1) * (
            scaling["enemies_per_round"] + self._tier)
        regular = [(self._rng.choice(spawn_tiles), "standard")
                   for _ in range(count)]

        raiders = self._raider_group(round_num, balance, spawn_tiles)
        siege_front, siege_mixed = self._siege_groups(
            round_num, balance, spawn_tiles)

        rest = regular + raiders + siege_mixed
        self._rng.shuffle(rest)
        return siege_front + rest

    def _boss_round(self, round_num, balance, spawn_tiles):
        """Boss-round composition (10G, prototype ``game.py:831-874``): exactly
        ONE boss leads, then EVERY siege cannon (no lead/mix split), then the
        shuffled standard+raider companions. Counts come from
        ``Boss.round_counts[boss_idx]``; beyond the table the three normal
        per-type formulas (incl. start-round guards) take over. The boss
        entry's tier is its ERA (``round // interval - 1``, clamped in
        ``Boss.__init__``); companions keep the real scale tier."""
        boss_cfg = balance["EnemyTypes"]["Boss"]
        boss_idx = round_num // boss_cfg["round_interval"] - 1
        self._boss_era = max(0, boss_idx)
        counts = boss_cfg["round_counts"]
        if boss_idx < len(counts):
            row = counts[boss_idx]
            n_regular = row["regular"]
            n_raiders = row["raiders"]
            n_siege = row["siege"]
        else:
            scaling = balance["EnemyScaling"]
            n_regular = scaling["base_enemy_count"] + (round_num - 1) * (
                scaling["enemies_per_round"] + self._tier)
            r = balance["EnemyTypes"]["Raider"]
            n_raiders = (
                r["base_count"] + (round_num - r["start_round"]) * r["per_round"]
                if ENABLE_RAIDERS and round_num >= r["start_round"] else 0)
            s = balance["EnemyTypes"]["SiegeCannon"]
            n_siege = (
                s["base_count"]
                + (round_num - s["start_round"]) // s["rounds_per_cannon"]
                if ENABLE_SIEGE and round_num >= s["start_round"] else 0)
        boss = [(self._rng.choice(spawn_tiles), "boss")]
        siege = [(self._rng.choice(spawn_tiles), "siege")
                 for _ in range(n_siege)]
        rest = ([(self._rng.choice(spawn_tiles), "standard")
                 for _ in range(n_regular)]
                + [(self._rng.choice(spawn_tiles), "raider")
                   for _ in range(n_raiders)])
        self._rng.shuffle(rest)
        return boss + siege + rest

    def _raider_group(self, round_num, balance, spawn_tiles):
        if not ENABLE_RAIDERS:
            return []
        r = balance["EnemyTypes"]["Raider"]
        if round_num < r["start_round"]:
            return []
        n = r["base_count"] + (round_num - r["start_round"]) * r["per_round"]
        return [(self._rng.choice(spawn_tiles), "raider") for _ in range(n)]

    def _siege_groups(self, round_num, balance, spawn_tiles):
        if not ENABLE_SIEGE:
            return [], []
        s = balance["EnemyTypes"]["SiegeCannon"]
        if round_num < s["start_round"]:
            return [], []
        n = (s["base_count"]
             + (round_num - s["start_round"]) // s["rounds_per_cannon"])
        siege = [(self._rng.choice(spawn_tiles), "siege") for _ in range(n)]
        lead = min(int(s["queue_lead_count"] * s["mix_ratio"]), len(siege))
        return siege[:lead], siege[lead:]

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
        # The boss's `tier` argument IS its era (Boss.__init__ clamps it, 10G);
        # every other entry keeps the real scale tier.
        tier = self._boss_era if etype == "boss" else self._tier
        enemy = create_enemy(
            etype, tile.col, tile.row, self._balance, self._tilemap,
            tier, self._registry, self._rng)
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
        scale tier (standard + siege scale; raiders never do). Each child is
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
                    self._tier, self._registry, self._rng)
                if frac < 1.0:
                    health = enemy.get_component(Health)
                    health.hp = max(1, int(health.max_hp * frac))
                scene.spawn(enemy)
