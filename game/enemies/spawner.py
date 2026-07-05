"""Spawner — the wave queue (Phase 9E).

Ports the prototype's ``_begin_enemy_phase`` (composition + queue build) and the
``_update_enemy_phase`` spawn loop (``src/core/game.py``). Standard enemies are
the only type EMITTED in 9E; the raider / siege / boss branches are written with
their exact prototype formulas but gated OFF by the ``ENABLE_*`` flags (10F/10G
flip them on). Timing is prototype-exact: a linear slow→fast ramp across the wave
with a per-enemy ``uniform(0.4, 1.6)`` jitter (or, ramp-off, a re-rolled jitter
per spawn). The round loop that CALLS ``begin_round`` and detects wave-clear is
9F; 9E exposes the pieces (``begin_round`` / ``update`` / ``active`` / ``done``).

An ``rng`` is injectable so tests are deterministic (default: the ``random``
module).
"""
import random

from .enemy import create_enemy

# 10F / 10G enable these branches; zeroed (no emission) in 9E.
ENABLE_RAIDERS = False
ENABLE_SIEGE = False
ENABLE_BOSS = False


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
        """Build the (tile, etype) list for the round. Standard-only in 9E; the
        other branches are present but gated off."""
        if not spawn_tiles:
            return []
        scaling = balance["EnemyScaling"]
        count = scaling["base_enemy_count"] + (round_num - 1) * (
            scaling["enemies_per_round"] + self._tier)
        regular = [(self._rng.choice(spawn_tiles), "standard")
                   for _ in range(count)]

        raiders = self._raider_group(round_num, balance, spawn_tiles)
        siege_front, siege_mixed = self._siege_groups(
            round_num, balance, spawn_tiles)
        # Boss round is detected but composes nothing until 10G.
        _boss_round = (ENABLE_BOSS and round_num
                       % balance["EnemyTypes"]["Boss"]["round_interval"] == 0)

        rest = regular + raiders + siege_mixed
        self._rng.shuffle(rest)
        return siege_front + rest

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
        enemy = create_enemy(
            etype, tile.col, tile.row, self._balance, self._tilemap,
            self._tier, self._registry, self._rng)
        scene.spawn(enemy)
        if delay is None:
            base = self._interval
            self._timer = max(0.15, self._rng.uniform(base * 0.4, base * 1.6))
        elif self._queue:
            self._timer = self._queue[0][2]
        else:
            self._timer = 0.0
