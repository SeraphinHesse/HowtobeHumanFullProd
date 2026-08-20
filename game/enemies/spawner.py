"""Spawner — the wave queue (Phase 9E).

Ports the prototype's ``_begin_enemy_phase`` (composition + queue build) and the
``_update_enemy_phase`` spawn loop (``src/core/game.py``). Standard, raider and
siege enemies are all EMITTED since 10F (raiders from ``Raider.start_round``,
siege from ``SiegeCannon.start_round``); the boss is LIVE since 10G — every
boss round (the era clock's ``boss_round_in_era``) composes ``[boss] + ALL
siege + shuffle(standard + raiders + commanders)`` from the ``round_counts``
table (falling back to the normal per-type era-row counts beyond it — BR-4
briefly replaced that fallback with the endgame-scaled table row and BR-5
reverted it), and the boss entry's era is its own. Formations join since ER-4
(from ``Formation.start_round``, mixed
into the shuffled body — never leading the queue, never on a boss round). The
Commander's branch exists since BR-2 but is DORMANT: its era rows AND every
``round_counts`` row's ``commander`` count are 0, so it never enters a wave.
Snipers join since NE-1 (from ``Sniper.start_round``, body-mixed like
formations — never leading the queue, never on a boss round).

Since ES-2 every count and the spawn interval come from the ONE era clock in
``EnemyScaling`` (``rounds_per_era`` / ``boss_round_in_era``) resolved through
``engine.era_math`` — no formula lives in this file any more. Timing is
otherwise prototype-exact: a linear slow→fast
ramp across the wave with a per-enemy ``uniform(0.4, 1.6)`` jitter (or, ramp-off,
a re-rolled jitter per batch). Since ES-3 one timer expiry releases the era row's
``batch_size`` enemies at once (D4) — pacing and batching are the same era row,
and a round's TOTAL is unaffected by either. The round loop that CALLS ``begin_round`` and
detects wave-clear is 9F; 9E exposes the pieces (``begin_round`` / ``update`` /
``active`` / ``done``);
``spawn_death_swarm`` (ER-3) is the Session-driven death burst for ANY type
carrying an enabled ``death_spawn``. Since BR-3 the BOSS instead carries a
``second_phase``: ``_advance_second_phases`` (driven first in ``update``)
trickles its children out one per ``spawn_delay`` while the boss is frozen and
untouchable, through the same ``_spawn_child`` path the burst uses.

An ``rng`` is injectable so tests are deterministic (default: the ``random``
module).
"""
import random

from engine import era_math
from engine.core import Health
from game.map.pathfinder import block_tiles

from .enemy import ENEMY_CLASSES, SWARM_TYPES, create_enemy
from .sounds import SPAWN, play_enemy_sound

# Raiders + siege went live in 10F; the boss in 10G; the formation in ER-4.
ENABLE_RAIDERS = True
ENABLE_SIEGE = True
ENABLE_BOSS = True
ENABLE_FORMATION = True
# BR-2: the Commander branch is LIVE but emits nothing — its era rows ship
# count_start/count_per_round at 0 (D8), so it never enters a normal wave. BR-3
# gives it its real entrance, the boss's second phase.
ENABLE_COMMANDER = True
# NE-1: the Sniper, the first ranged stand-off type. LIVE from its own
# `start_round` (26) — before that `_count_of` returns 0 and `_sniper_group`
# draws no rng, so every wave below round 26 is byte-identical to BR-5.
ENABLE_SNIPER = True
# NE-2: the Digger. LIVE from EnemyTypes.Digger.start_round (35).
ENABLE_DIGGER = True
# NE-3: the Drummer support unit, live from its own start_round (25).
ENABLE_DRUMMER = True

# The burst order now lives beside ENEMY_CLASSES in enemy.py, because BR-3's
# delayed second phase lays out its child queue from the SAME table and
# enemy.py cannot import this module (the dependency runs the other way).
# BR-3 appended ("commander", "commander") to it LAST: until then a non-zero
# `commander` count in ANY spawn_counts row silently spawned nothing.
_SWARM_TYPES = SWARM_TYPES


def _footprint_of(balance, etype, era=0):
    """The etype's footprint from balancing (G-7), resolved through the class's
    ``STAT_SUBTREE`` — so a new enemy type needs no change here.

    BR-1: the WHERE is the class's own ``resolve_fit`` seam (flat at the type
    root for every type but the Boss, whose footprint is per-era), so this
    function and ``Enemy.__init__`` can never read different values."""
    cls = ENEMY_CLASSES[etype]
    block = balance["EnemyTypes"]
    for seg in cls.STAT_SUBTREE:
        block = block[seg]
    return cls.resolve_fit(block, era)[0]


class Spawner:
    def __init__(self):
        self._queue = []       # list of (tile, etype, delay | None)
        self._timer = 0.0
        self._interval = 0.0
        self._batch_size = 1   # enemies released per timer expiry (ES-3/D4)
        self._era = 0          # the round's era (ES-2: era IS the old tier)
        self._round_in_era = 1  # 1-based position inside that era (D2)
        self._round = 0
        self._balance = None
        self._tilemap = None
        self._registry = None
        self._rng = random
        self._boss_era = 0     # era passed as `tier` to a popping boss (10G)
        self._clear_cache = {}  # footprint -> spawn tiles with a clear block
        # feature-enemy-intro-dialogue: etypes that actually entered the scene
        # since the last drain, from EVERY construction site in this class (the
        # wave pop AND `_spawn_child`'s burst/second-phase children). Drained
        # once per frame by `Session.post_sim` to fire spawn-triggered intro
        # dialogues — an entry whose `show_on_spawn_of` names a type that is
        # never in a wave (the Commander is summoned mid-boss-fight) cannot be
        # matched on the round alone.
        self._spawned_types = []

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

    def drain_spawned_types(self):
        """Pop every etype spawned since the last call, in spawn order
        (feature-enemy-intro-dialogue). One drain per frame, from
        ``Session.post_sim``; nobody else may consume it, since a second
        reader would see an empty list."""
        types = self._spawned_types
        self._spawned_types = []
        return types

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
        # ES-4/D5: past the last authored era the row clamps AND
        # EnemyScaling.endgame_scaling's factors compound onto it. All 1.0 as
        # shipped, so this is exactly the plain clamp until a designer tunes it.
        pacing = era_math.resolve_era_row(
            scaling["eras"], self._era, scaling["endgame_scaling"])
        self._interval = max(0.1, pacing["spawn_interval"])
        # ES-3/D4: how many queue entries ONE timer expiry releases.
        self._batch_size = max(1, int(pacing["batch_size"]))

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
        clearance filter itself consumes NO rng.

        The era passed to ``_footprint_of`` is the same one the enemy will be
        CONSTRUCTED with in ``update`` (the boss takes ``_boss_era``, stashed
        by ``_boss_round`` before it picks any tile) — since BR-1 the boss's
        footprint is per-era, so the clearance filter must ask about the era
        that is actually about to spawn."""
        era = self._boss_era if etype == "boss" else self._era
        fp = _footprint_of(self._balance, etype, era)
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
        game, shared by the standard/raider/siege/formation/commander sites AND
        by ``_boss_round``'s past-the-table fallback (BR-4 removed that borrow,
        BR-5 restored it — see ``_boss_round``).

        ES-4/D5: past the last authored era the row clamps AND the type's own
        ``endgame_scaling`` factors compound onto it (all 1.0 as shipped, so a
        round-60 wave is unchanged until a designer tunes them)."""
        block = balance["EnemyTypes"][type_key]
        rounds_per_era = balance["EnemyScaling"]["rounds_per_era"]
        era = era_math.era_of_round(round_num, rounds_per_era)
        row = era_math.resolve_era_row(
            block["eras"], era, block["endgame_scaling"])
        return era_math.count_at_round(
            row, round_num, era * rounds_per_era + 1, block["start_round"])

    def _compose(self, round_num, balance, spawn_tiles):
        """Build the (tile, etype) list for the round: standard + raiders +
        siege (10F) + formations (ER-4). The queue is led by EVERY digger
        (unsplit), then the siege lead slice; everything else is shuffled
        behind them. A boss round (``era_math.is_boss_round``) takes
        the boss composition instead (10G) — the lead/mix siege split applies
        to NON-boss rounds only, and formations do not appear at all (see
        ``_formation_group``).

        ``_formation_group``, then ``_commander_group``, then ``_sniper_group``,
        ``_digger_group`` and ``_drummer_group`` are called LAST on
        purpose, newest last: every earlier group's rng draw sequence then
        stays byte-identical, so the standard/raider/siege counts and picks are
        unchanged at every round. (The Commander draws nothing at all today —
        its counts are 0 — so BR-2 is provably wave-neutral. The Sniper draws
        nothing below its `start_round` 26 and the Digger nothing below 35, so
        every wave under those rounds is byte-identical too; the Drummer draws
        nothing before round 25, so NE-3 is wave-neutral up to there.)

        TU-9: round 0 is the tutorial's forced-composition round — checked
        FIRST, before the boss check (``era_math.is_boss_round`` is already
        False at round 0 for every configuration, D11, but the round-0 branch
        is a COMPOSITION rule and stays ahead of it). It always composes
        exactly
        ``EnemyScaling.tutorial_round_enemy_count`` ``"tutorial"`` enemies
        (add-enemy dispatch, user decision — split off the real ``"standard"``
        Walker so this round's spawn can be tuned independently; it hunts
        buildings rather than the hole), ignoring every other composition
        rule."""
        if not spawn_tiles:
            return []
        if round_num == 0:
            n = balance["EnemyScaling"]["tutorial_round_enemy_count"]
            return [(self._pick_spawn_tile(spawn_tiles, "tutorial"), "tutorial")
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
        commanders = self._commander_group(round_num, balance, spawn_tiles)
        snipers = self._sniper_group(round_num, balance, spawn_tiles)
        diggers = self._digger_group(round_num, balance, spawn_tiles)
        drummers = self._drummer_group(round_num, balance, spawn_tiles)

        rest = (regular + raiders + siege_mixed + formations + commanders
                + snipers + drummers)
        self._rng.shuffle(rest)
        return diggers + siege_front + rest

    def _boss_round(self, round_num, balance, spawn_tiles):
        """Boss-round composition (10G, prototype ``game.py:831-874``): exactly
        ONE boss leads, then EVERY siege cannon (no lead/mix split), then the
        shuffled standard+raider+commander companions. Counts come from
        ``Boss.round_counts[era]``; **beyond the table the normal per-type
        era-row counts (``_count_of``, start-round guards included) take
        over** — the 10G behaviour, restored in BR-5.

        BR-4 had swapped that fallback for the era-4 table row grown by
        ``endgame_boss_scaling`` (all factors 1.0, so: the era-4 wave forever),
        which turned a round-60 boss round from 295/46/37 companions into
        700/215/61. **The user reverted exactly that branch in BR-5** and kept
        everything else BR-4 shipped: the boss's own stats/fit/shake and its
        ``second_phase.spawns`` still resolve through ``endgame_boss_scaling``,
        and ``Boss._resolve_era`` still returns the unclamped global era. So
        past era 4 the BOSS keeps growing while its escort follows the ordinary
        per-type curve again.

        BR-5 also wires ``round_counts[era]["commander"]``, which was authored
        but never consumed. It is composed **LAST**, after the standard and
        raider picks, so every earlier group's rng draw sequence — and with it
        every deterministic wave fixture — stays byte-identical (the same rule
        ``_formation_group``/``_commander_group`` follow in ``_compose``). Every
        shipped row is 0, so this is behaviourally neutral today.

        The boss entry's era is the global era (unclamped since BR-4);
        companions carry the round's own era, as always."""
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
            n_commander = row["commander"]
        else:
            n_regular = self._count_of(balance, "Standard", round_num)
            n_raiders = (self._count_of(balance, "Raider", round_num)
                         if ENABLE_RAIDERS else 0)
            n_siege = (self._count_of(balance, "SiegeCannon", round_num)
                       if ENABLE_SIEGE else 0)
            n_commander = (self._count_of(balance, "Commander", round_num)
                           if ENABLE_COMMANDER else 0)
        boss = [(self._pick_spawn_tile(spawn_tiles, "boss"), "boss")]
        siege = [(self._pick_spawn_tile(spawn_tiles, "siege"), "siege")
                 for _ in range(n_siege)]
        rest = ([(self._pick_spawn_tile(spawn_tiles, "standard"), "standard")
                 for _ in range(n_regular)]
                + [(self._pick_spawn_tile(spawn_tiles, "raider"), "raider")
                   for _ in range(n_raiders)]
                + [(self._pick_spawn_tile(spawn_tiles, "commander"),
                    "commander")
                   for _ in range(n_commander)])
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

    def _commander_group(self, round_num, balance, spawn_tiles):
        """Commanders from the shared count formula — ZERO at the shipped
        values (BR-2/D8: every era row's ``count_start``/``count_per_round`` is
        0), so this returns an empty list on every round and consumes no rng.

        It exists so switching the Commander into normal waves is a data edit
        alone. Called LAST in ``_compose`` (after ``_formation_group``) for the
        same reason the Formation was: an earlier call site would shift every
        other group's rng draw sequence and move the deterministic wave
        fixtures. Its real entrance — the boss's second phase — is BR-3 and
        does not come through here."""
        if not ENABLE_COMMANDER:
            return []
        n = self._count_of(balance, "Commander", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "commander"), "commander")
                for _ in range(n)]

    def _sniper_group(self, round_num, balance, spawn_tiles):
        """Snipers from ``Sniper.start_round`` (NE-1), through the same shared
        count formula every other type uses.

        Mixed into the shuffled body, never leading the queue: the Sniper's
        whole point is that it stops 2 tiles short of an attack building and
        shoots it, so putting it at the head of the wave would have it
        out-ranging the player's defences before anything else arrived to draw
        fire. Same reasoning as the Formation's body-mix, different mechanic.

        Snipers never appear on a boss round — ``_boss_round`` composes from
        ``Boss.round_counts``, a ``$defs/spawn_counts`` table shared with every
        ``death_spawn.spawns`` row, and adding a `sniper` key there would force
        a meaningless sniper count onto all 14 committed rows (the same
        judgement the Formation section of ``game/enemies/CLAUDE.md`` records;
        BR-1 overrode it once, for `commander`, deliberately).

        Called after ``_commander_group`` — newest last, so every earlier
        group's rng draw sequence stays byte-identical."""
        if not ENABLE_SNIPER:
            return []
        n = self._count_of(balance, "Sniper", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "sniper"), "sniper")
                for _ in range(n)]

    def _digger_group(self, round_num, balance, spawn_tiles):
        """Diggers from ``Digger.start_round`` on, through the shared
        count formula. EVERY digger the round rolls LEADS the queue, ahead of
        even the siege lead slice (user decision) — the whole group tunnels out
        first, so the wave opens with the burrow-and-erupt threat rather than
        having it trickle in behind the swarm. No lead/mix split: unlike siege
        (``_siege_groups``) there is no ``queue_lead_count``/``mix_ratio`` for
        diggers, so the count formula alone decides how many lead.

        Called LAST in ``_compose``, after ``_sniper_group`` — the same
        newest-last rule the Formation/Commander/Sniper follow, so every
        earlier group's rng draw sequence (and therefore every deterministic
        wave fixture) stays byte-identical. Below round 35 the shared formula
        returns 0 and this draws no rng at all.

        Diggers never appear on a boss round — the SAME deliberate rule the
        Formation follows (`_boss_round` composes from `Boss.round_counts`, a
        `$defs/spawn_counts` table shared with every `death_spawn.spawns` row,
        so a `digger` key there would land on all 14 committed rows). Pinned by
        `test_enemies.TestDigger.test_no_diggers_on_a_boss_round`."""
        if not ENABLE_DIGGER:
            return []
        n = self._count_of(balance, "Digger", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "digger"), "digger")
                for _ in range(n)]

    def _drummer_group(self, round_num, balance, spawn_tiles):
        """Drummers from ``Drummer.start_round`` (25) through the shared count
        formula — a handful per wave, not a swarm: the support unit is meant
        to be the thing you go and kill, and every extra one multiplies the
        whole field's stats.

        Body-mixed like the Formation, never queue-leading: a support unit
        that arrives ahead of the units it supports buffs nothing. Called
        LAST in ``_compose`` (after ``_digger_group``) for the usual rng
        reason — an earlier call site would shift every other group's draw
        sequence and move every deterministic wave fixture. Below round 25
        it returns an empty list and consumes no rng, so rounds 0-24 are
        byte-identical to BR-5.

        Drummers never appear on a boss round, exactly like Formations:
        ``_boss_round`` composes from ``Boss.round_counts``, a
        ``$defs/spawn_counts`` table SHARED with every ``death_spawn.spawns``
        row, and nothing wants a drummer count in a death-spawn row. If
        drummers on boss rounds are ever wanted it is a one-line
        ``+ self._drummer_group(...)`` into ``_boss_round``'s ``rest``,
        computed from the formula and never from the table."""
        if not ENABLE_DRUMMER:
            return []
        n = self._count_of(balance, "Drummer", round_num)
        return [(self._pick_spawn_tile(spawn_tiles, "drummer"), "drummer")
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
        """Advance the spawn timer; when it expires, release ONE BATCH — up to
        ``_batch_size`` queue entries at once (ES-3/D4) — and schedule the next.

        Each popped entry spawns exactly as it did when the spawner released one
        per expiry: one ``create_enemy`` + one ``scene.spawn``, in queue order,
        so the rng draw sequence WITHIN a batch is unchanged. The boss simply
        leads its batch. At ``batch_size == 1`` this loop is byte-identical to
        ES-2 (same draws, same times) — that is the fence for the deterministic
        wave fixtures. Round totals never move with this knob: it changes how
        many spawn EVENTS a wave takes, not how many enemies are in it.

        BR-3: the delayed second phase is driven FIRST, before the queue's own
        early-out — a boss stages long after its wave queue has drained, so it
        cannot hang off the `if not self._queue: return` below."""
        self._advance_second_phases(dt, scene)
        if not self._queue:
            return
        self._timer -= dt
        if self._timer > 0:
            return
        ramp_off = False
        for _ in range(self._batch_size):
            if not self._queue:
                break
            tile, etype, delay = self._queue.pop(0)
            # ES-2: ONE era for stats, art and death-spawn rows alike. The boss
            # takes the era stashed by _boss_round (identical to self._era
            # today — kept separate so a future boss-only clock has a seam).
            era = self._boss_era if etype == "boss" else self._era
            enemy = create_enemy(
                etype, tile.col, tile.row, self._balance, self._tilemap,
                era, self._registry, self._rng, self._round_in_era)
            self._attach_scene(enemy, scene)
            scene.spawn(enemy)
            self._spawned_types.append(etype)
            # SD-5: the spawn sound, for EVERY popped enemy, resolved through
            # the same per-type machinery — a type with no authored `spawn`
            # clips is a silent no-op, so only the Boss is audible today. This
            # is also the boss-spawn row: no boss-specific call site exists.
            play_enemy_sound(enemy, SPAWN)
            if delay is None:
                ramp_off = True
        if ramp_off:
            # Ramp-off: ONE re-rolled jitter per BATCH, not per enemy.
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
                self._spawn_child(scene, etype, col, row, frac)

    @staticmethod
    def _attach_scene(enemy, scene):
        """Wire the ``Enemy._scene`` transient (NE-2, ``enemy.py``).

        Called at BOTH of this class's construction sites — the wave pop in
        ``update`` and ``_spawn_child`` below — immediately BEFORE
        ``scene.spawn``, so the reference is already there when
        ``Scene.update`` calls ``on_spawn()``. That ordering is load-bearing
        for the Digger: its ``on_spawn`` is where the exclusive claim is first
        taken, and taking it needs to see the other live Diggers. NE-3's
        ``DrummerAura`` is the other consumer — its per-frame ``by_tag
        ("enemy")`` aura scan needs the same world reference.

        A ``GameObject`` is never handed the scene by the engine
        (``on_spawn()`` takes no arguments) and a ``Component`` cannot reach it
        either — this is the ``spawn_corpse`` / ``begin_kidnap`` "the
        transition site wires it" pattern, hoisted into a named helper so the
        two sites (and any future third) can never drift apart."""
        enemy._scene = scene

    def _spawn_child(self, scene, etype, col, row, frac):
        """Construct ONE death-spawn / second-phase child at ``(col, row)``.
        The single per-child path both the one-frame burst above and BR-3's
        delayed phase go through, so the two can never drift on era,
        registry/rng variant picks or the HP seeding.

        **No spawn sound here, deliberately (SD-5).** This is the death-swarm /
        second-phase child path, and an era-4 burst is 55 children in ONE
        frame — the channel-exhaustion load case. The plan authors no
        child-spawn row; only the wave pop in ``update`` is audible. Do not
        "fix" this by adding a ``play_enemy_sound`` call below."""
        enemy = create_enemy(
            etype, col, row, self._balance, self._tilemap,
            self._era, self._registry, self._rng, self._round_in_era)
        self._attach_scene(enemy, scene)
        if frac < 1.0:
            health = enemy.get_component(Health)
            health.hp = max(1, int(health.max_hp * frac))
        scene.spawn(enemy)
        self._spawned_types.append(etype)

    # -- delayed second phase (BR-3) ---------------------------------------

    def _advance_second_phases(self, dt, scene):
        """Tick every staged second phase and spawn the children it releases.

        Duck-typed over ``by_tag("enemy")`` rather than ``by_tag("boss")``: the
        Boss is the only type with a ``second_phase`` block today, but the
        mechanic is a property of the data, not of the tag. ``dt`` is the
        host's speed-scaled ``sim_dt`` (``Session.pre_sim``), which is what
        keeps the cadence honest at 1.5x/2x — the ``Corpse`` fade-clock rule.

        The children land at the parent's own tile (D6) through the SAME
        ``_spawn_child`` path the one-frame burst uses. ``Enemy`` owns the
        state machine; this method owns the scene."""
        for enemy in list(scene.by_tag("enemy")):
            advance = getattr(enemy, "advance_second_phase", None)
            if advance is None:
                continue
            due = advance(dt)
            if not due:
                continue
            wx, wy = enemy.transform.world_pos
            col, row = round(wx), round(wy)
            frac = enemy.second_phase_child_hp_fraction
            for etype in due:
                self._spawn_child(scene, etype, col, row, frac)
