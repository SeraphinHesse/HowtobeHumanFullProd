"""RunState — the mutable per-run state (Phase 9F).

The single owner of the round loop's authoritative values, mirroring the fields
the prototype's ``Game`` carries (``src/core/game.py`` __init__ /
``_start_new_game``): the current phase + top-level state, round number, love
(the currency), base lives, the phase timer, and run stats. ``Session`` reads
and mutates this; ``payday`` writes love + round. Seeded from ``core.json``.

``round_num`` starts at 1 (BUILDING of round 1) and is ``++``'d in payday, so
the wave spawned by End Turn uses the pre-increment value — prototype-exact.
Love is clamped at ``>= 0`` on every write (the prototype clamps on every
currency mutation).
"""
from dataclasses import dataclass, field

from engine.era_math import era_of_round

from .phases import GamePhase, GameState


@dataclass
class RunState:
    phase: GamePhase = GamePhase.BUILDING
    state: GameState = GameState.GAMEPLAY
    round_num: int = 1
    # -- N1: the season clock -----------------------------------------------
    # 0-based ground-art season index, derived from ``round_num`` by
    # ``update_season`` (never set by hand). ``0`` is a REAL season — the first
    # one — not "unset": a fresh run is round 1, which is season 0, so the
    # default already agrees with the derived value and ``from_balance`` needs
    # no season seeding. Round 0 (the tutorial round) is season 0 too, via
    # ``era_of_round``'s ``round_num < 1`` guard.
    season: int = 0
    love: int = 0
    base_lives: int = 0
    phase_timer: float = 0.0
    enemies_killed: int = 0
    buildings_placed: int = 0
    # Runtime-only floater ledger (9G): payday records what each tile paid this
    # income phase as ``(col, row, amount, kind)`` (kind = "income" | "upkeep",
    # amount signed) so the UI spawns income/upkeep floaters without re-deriving
    # payday math. Cleared + refilled every ``run_payday``; never serialized
    # (RunState is rebuilt from balance, not persisted).
    income_events: list = field(default_factory=list)
    # -- Painter (10C) ----------------------------------------------------
    # ``(col, row)`` of tiles that completed a Painter payout: permanently
    # barred from hosting another Painter (prototype ``used_painter_tiles``).
    # A painter LOST before payout does NOT go here — only a completed one.
    used_painter_tiles: set = field(default_factory=set)
    # Message-floater ledger, same drained-by-UI contract as ``income_events``:
    # ``(col, row, text, kind)`` where kind = "finished" | "lost". Filled by
    # ``run_payday``, drained by the UI; never serialized.
    painter_events: list = field(default_factory=list)
    # -- Boost (10D) ------------------------------------------------------
    # White per-turn boost floaters, same drained-by-UI contract as the others:
    # ``(col, row, text)`` anchored on each buffed defender's tile. Filled by the
    # payday boost slot, drained by the UI; never serialized.
    boost_events: list = field(default_factory=list)
    # -- Building respawn (VfxAuthoringPLAN VA-4) --------------------------
    # ``(col, row, tier)`` per non-base building the payday revive slot brought
    # BACK from dead — NOT the full-heal every living building also gets in
    # that same slot. Same drained-by-UI contract as the ledgers above; never
    # serialized.
    #
    # It carries the building's 0-indexed tier where its siblings carry only a
    # point, and that is deliberate rather than inconsistent: D4 declines to
    # WIDEN the existing ledgers to thread a level through for a cosmetic
    # lever, but this ledger is new, payday already holds the building, and a
    # respawn is exactly the per-building event whose "vary the art by tier"
    # this feature was asked for. Nothing that already existed changed shape.
    building_respawn_events: list = field(default_factory=list)
    # -- XP / village level (10A) -----------------------------------------
    player_xp: int = 0
    village_level: int = 1
    xp_threshold: int = 0       # seeded from core.XP.village_xp_base_threshold
    xp_threshold_inc: int = 0   # seeded from core.XP.village_xp_threshold_inc
    levelup_pending: bool = False
    # Designer-scripted leveling: XP is not a mechanic at all and the village
    # level advances on the rounds authored on the Timeline
    # (``progression.json`` ``Timeline.scripted_leveling``). Host-set by
    # ``Session.__init__`` off ``progression_balance``; ``False`` (the default,
    # and what a bare RunState a logic test builds always carries) is the
    # shipped XP-threshold behaviour, unchanged. RunState owns it because BOTH
    # the round machine (``Session.pre_sim``) and the HUD (``game/ui/hud.py``'s
    # XP readout) have to see it, and RunState is already what both read.
    scripted_leveling: bool = False
    # Research progress, GLOBAL per building type (every building of a type
    # shares its researched-tier count). Every type starts at its first tier
    # (1) — unlocking a type is the only gate; there is no longer a
    # "starts at tier 0" case.
    tiers_unlocked: dict = field(default_factory=dict)
    unlocked_buildings: dict = field(default_factory=dict)
    # Two more runtime-only ledgers, same contract as ``income_events``: filled
    # by core, drained by the UI, never serialized. ``xp_events`` holds
    # ``(wx, wy, amount)`` XP-floater spawns; ``levelup_options`` holds the
    # three rolled cards the LEVELUP window renders.
    xp_events: list = field(default_factory=list)
    levelup_options: list = field(default_factory=list)
    # -- Boss (10G) ---------------------------------------------------------
    # The six A/B bonus stack counters (see ``game/core/boss_bonuses.py``); a
    # fresh RunState = the prototype's new-game reset. ``boss_choices`` is the
    # per-run history ledger of ``(boss_num, option, outcome)`` tuples — no disk
    # persistence. The two snapshots are taken at End Turn: love EVERY round
    # (Boss3A), lives on boss rounds only (the win/loss compare).
    # ``pending_boss_cutscene`` is ``{"boss_num", "outcome"}`` queued at a boss
    # round's ROUND_END and consumed by ``resolve_boss_cutscene``.
    # ``boss_events`` is a drained-by-UI announcement ledger (same contract as
    # ``xp_events``): one marker per boss-round End Turn.
    boss_stacks: dict = field(default_factory=lambda: dict.fromkeys(
        ("boss1a", "boss1b", "boss2a", "boss2b", "boss3a", "boss3b"), 0))
    boss_choices: list = field(default_factory=list)
    boss_lives_snapshot: int = 0
    boss_love_snapshot: int = 0
    pending_boss_cutscene: object = None
    boss_events: list = field(default_factory=list)
    # -- Boss upgrade timeline (BossUpgradeTimelinePLAN BU-2) ----------------
    # The new boss-upgrade system's per-run ledgers. Purely ADDITIVE for now:
    # the 10G fields above (``boss_stacks``/``boss_choices``) are still live
    # and are retired in BU-4, when the cutscene stops offering the old A/B
    # narrative pick.
    #
    # ``boss_upgrade_stacks`` is ``{upgrade_id: pick_count}`` — the ONE store
    # for both questions every hook site asks: "is this upgrade active" (``> 0``)
    # and "how many times has it been picked" (persistent %-effects stack
    # ADDITIVELY per pick, D4). Read it through
    # ``game.core.boss_upgrades.stack_count``, never by indexing here.
    boss_upgrade_stacks: dict = field(default_factory=dict)
    # Running total of love the player has spent UNLOCKING TILES this run — a
    # ledger nothing else kept. The ``tile_refund`` upgrade (#12) pays exactly
    # this back, once, via ``add_love``. Incremented at the ONE spend site,
    # ``game/ui/building_ui.py``'s ``_unlock_click`` (wired in BU-3).
    love_spent_on_tiles: int = 0
    # ``id(building)`` of every mortar alive at the moment ``mortar_slow`` (#3)
    # was picked — the upgrade is SNAPSHOT-scoped (D16), so mortars built
    # afterwards never gain slow-on-hit. Frozen at pick time (populated in
    # BU-3); ids are only ever compared against live buildings held by the
    # tilemap, so they cannot be recycled out from under this set.
    mortar_slow_snapshot_ids: set = field(default_factory=set)
    # The per-run history ledger of ``(boss_num, upgrade_id, outcome)`` tuples
    # — ``boss_choices``' replacement (BU-4 re-points the base-info popup at
    # it and deletes the old field). No disk persistence, same as its
    # predecessor.
    boss_upgrade_choices: list = field(default_factory=list)
    # -- 10J: game log + gore -----------------------------------------------
    # Two more drained-by-UI ledgers (the ``income_events`` contract):
    # ``log_events`` holds plain message strings for the fading game log;
    # ``enemy_death_events`` holds ``(wx, wy)`` death positions the splatter
    # layer consumes (filled by the Session death/base-hit callbacks).
    log_events: list = field(default_factory=list)
    enemy_death_events: list = field(default_factory=list)
    # -- /10J --
    # -- "Lost 1 life" announcement ledger -----------------------------------
    # The ``boss_events`` contract exactly: a drained-by-UI marker list, never
    # serialized. One entry (the round number) is appended by
    # ``Session.on_base_hit`` at the moment a life is actually CHARGED — a
    # tutorial free-loss waiver appends nothing, because no life was lost.
    # No coalescing is needed: ``_wipe_pending``/``_wipe_round`` despawn every
    # enemy and end the round on the first hit, so at most one entry per round
    # can ever exist by construction.
    life_lost_events: list = field(default_factory=list)
    # -- TU-5: registry-driven cutscene request -----------------------------
    # {"id": <registry key>} queued by Session.end_turn() on the FIRST End
    # Turn of the run (round 0's tutorial round, or round 1 on a skipped
    # run — see first_end_turn_cutscene_requested below), BEFORE
    # spawner.begin_round(); consumed (set back to None) by the host once it
    # starts playing the matching CutscenePlayer. Never serialized.
    pending_cutscene: object = None
    # -- TU-9: one-shot latch for the above (round 0 = tutorial) ------------
    # The prototype/TU-5 keyed the cutscene request on `round_num == 1`; once
    # the tutorial became round 0, that test would silently never fire for a
    # real tutorial run. This flag fires the request on the first
    # `end_turn()` of the run, whether that round is 0 (tutorial) or 1
    # (skipped straight to round 1), and never again. Never serialized.
    first_end_turn_cutscene_requested: bool = False
    # -- ESV-5: splash-impact trigger ledger ---------------------------------
    # A mortar shell's landing point, same drained-by-UI contract as
    # enemy_death_events: `(wx, wy)` world points. Appended by
    # game/enemies/combat.py's ProjectileArc._impact via resolve_combat's
    # optional on_splash_impact callback (game/enemies imports NO game/core —
    # the callback crosses the boundary opaquely, the on_enemy_death
    # pattern); drained by game/ui/effects.py's spawn_splash_impact_events
    # (called beside spawn_death_events) into the splash_impact trigger row.
    # The Crater GameObject's own continuous fade mark spawns unconditionally
    # regardless of this ledger — this only decides whether an ADDITIONAL
    # one-shot cosmetic plays at the same point.
    splash_impact_events: list = field(default_factory=list)
    # -- /ESV-5 --
    # -- ESV-6: defender_fire / projectile_hit trigger ledgers ---------------
    # Same drained-by-UI contract as splash_impact_events: `(wx, wy)` world
    # points, already muzzle/impact-anchored by the producer (game/enemies/
    # combat.py's _fire/_fire_splash for defender_fire, ProjectileHoming.
    # _impact for projectile_hit) via resolve_combat's two new optional
    # callbacks. Both trigger rows ship INERT (empty sprite_slot/procedural),
    # so filling these ledgers is a no-op emit on a fresh checkout — see
    # game/ui/effects.py's spawn_defender_fire_events/spawn_projectile_hit_
    # events.
    defender_fire_events: list = field(default_factory=list)
    projectile_hit_events: list = field(default_factory=list)
    # -- /ESV-6 --
    # -- 10H: lightning + cheat menu ---------------------------------------
    # Lightning strike ability (see game/core/lightning.py). SEEDED AT LEVEL 0
    # (Storm Priest wiring): every run now boots with lightning LOCKED —
    # placing a Storm Priest (the "lightning_source"-tagged building) is the
    # ONLY way to raise it to L1, via
    # ``game.core.lightning.unlock_from_placement`` called from
    # ``game.ui.building_ui._do_place`` after a successful placement. This
    # replaces the prior boot-unlocked design (the prototype's __init__ set
    # lightning_level = 1, game.py:117, and _start_new_game never reset it) —
    # a deliberate balance change, not a bug: the L0 unlock branch in
    # ``lightning.py`` (``can_strike`` / the UNLOCK button) is now reachable
    # from a normal boot, not dead weight. A fresh Session per run still
    # erases the prototype's quirk of upgrades persisting across "new game"
    # in the same app session (the 10F combat-speed treatment). The seed is
    # structural (like combat_speed_idx), so no from_balance change.
    #
    # feature-storm-acolyte-multi-build: its MEANING narrowed — several Storm
    # Priests may now be placed, each levelled independently, so this field
    # is no longer "the" ability's level. It stays as a pure UI/gating
    # signal (is lightning unlocked at all / the best tier ever placed, via
    # the same latching max() both helpers below already used) — nothing
    # reads it for damage/radius/cooldown any more (that comes off each
    # firing building's own tier). `lightning_cooldown` is DELETED: the
    # cooldown moved onto each acolyte's own `LightningCaster` component
    # (game/core/lightning.py), since a run can have several now, each on
    # its own clock.
    lightning_level: int = 0
    # -- /10H --
    # -- feature-enemy-intro-dialogue -----------------------------------
    # Queued at ``Session.end_turn()`` when one or more ``core.json``
    # ``EnemyIntro.entries`` match ``round_num`` (the LEVELUP/
    # ``pending_boss_cutscene`` "transient request" precedent — never
    # serialized). The host opens ``entries[0]`` on the BUILDING ->
    # ENEMY_INTRO phase edge; ``Session.resolve_enemy_intro()`` pops the
    # shown entry once its close animation finishes, re-arming the host to
    # open the new head entry, and returns the phase to ENEMY once the
    # queue drains.
    pending_enemy_intros: list = field(default_factory=list)
    # -- /feature-enemy-intro-dialogue --
    # -- Payout-phase sequencing: love-counter checkpoints ------------------
    # Two transient values `run_payday` stamps at its step 12 (never
    # serialized, the `pending_boss_cutscene` precedent), so the UI's payout
    # beat queue (`FloaterManager.begin_payout`) can animate the HUD love
    # counter in the two segments the player actually sees: up while the
    # economy beat's floaters show, down while the upkeep beat's do.
    # `payout_love_start` is `love` at the very top of `run_payday` (before
    # story/base/yield/upkeep/painter all ran this round);
    # `payout_love_after_economy` is what `love` was right after story +
    # base income + economy yield + the Painter payout, i.e. before upkeep
    # was deducted — recovered as `love + total_upkeep` since upkeep runs
    # before this snapshot is taken. The real, final total stays plain
    # `love` — these two are read-only checkpoints, nothing else in the game
    # consults them.
    payout_love_start: float = 0.0
    payout_love_after_economy: float = 0.0
    # -- /Payout-phase sequencing --

    @classmethod
    def from_balance(cls, core_balance, buildings_balance):
        """Seed a fresh run from the ``core`` + ``buildings`` balancing
        domains + the RESEARCH table (every type starts researched to tier 1;
        what starts UNLOCKED is data, read live per type)."""
        # Local import: game.buildings.research is pure, but importing it at
        # module scope would run during game/core/__init__ (see research.py's
        # import-boundary note).
        from game.buildings.research import RESEARCH, starts_unlocked_for

        hole, xp = core_balance["TheHole"], core_balance["XP"]
        return cls(
            love=core_balance["General"]["starting_currency"],
            base_lives=hole["base_lives"],
            xp_threshold=xp["village_xp_base_threshold"],
            xp_threshold_inc=xp["village_xp_threshold_inc"],
            tiers_unlocked={bt: 1 for bt in RESEARCH},
            unlocked_buildings={bt: starts_unlocked_for(bt, buildings_balance)
                                for bt in RESEARCH},
        )

    def add_love(self, amount):
        self.love = max(0, self.love + amount)

    def spend_love(self, amount):
        self.love = max(0, self.love - amount)

    def update_season(self, rounds_per_season):
        """Recompute ``season`` from ``round_num``; True iff it CHANGED.

        The bool is the caller's invalidate trigger: the host repaints its
        cached ground layer only when the season actually turns, not on every
        round edge. No new math — ``era_of_round`` IS the season formula (D7),
        so the era clock and the season clock cannot drift apart.
        """
        new = era_of_round(self.round_num, rounds_per_season)
        if new == self.season:
            return False
        self.season = new
        return True
