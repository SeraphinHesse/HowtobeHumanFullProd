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

from .phases import GamePhase, GameState


@dataclass
class RunState:
    phase: GamePhase = GamePhase.BUILDING
    state: GameState = GameState.GAMEPLAY
    round_num: int = 1
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
    # -- XP / village level (10A) -----------------------------------------
    player_xp: int = 0
    village_level: int = 1
    xp_threshold: int = 0       # seeded from core.XP.village_xp_base_threshold
    xp_threshold_inc: int = 0   # seeded from core.XP.village_xp_threshold_inc
    levelup_pending: bool = False
    # Research progress, GLOBAL per building type (every building of a type
    # shares its researched-tier count). Seeded from the RESEARCH table.
    tiers_unlocked: dict = field(default_factory=dict)
    unlocked_buildings: dict = field(default_factory=dict)
    # Two more runtime-only ledgers, same contract as ``income_events``: filled
    # by core, drained by the UI, never serialized. ``xp_events`` holds
    # ``(wx, wy, amount)`` XP-floater spawns; ``levelup_options`` holds the
    # three rolled cards the LEVELUP window renders.
    xp_events: list = field(default_factory=list)
    levelup_options: list = field(default_factory=list)

    @classmethod
    def from_balance(cls, core_balance):
        """Seed a fresh run from the ``core`` balancing domain + the RESEARCH
        table (which decides what starts unlocked / researched)."""
        # Local import: game.buildings.research is pure, but importing it at
        # module scope would run during game/core/__init__ (see research.py's
        # import-boundary note).
        from game.buildings.research import RESEARCH

        hole, xp = core_balance["TheHole"], core_balance["XP"]
        return cls(
            love=core_balance["General"]["starting_currency"],
            base_lives=hole["base_lives"],
            xp_threshold=xp["village_xp_base_threshold"],
            xp_threshold_inc=xp["village_xp_threshold_inc"],
            tiers_unlocked={bt: s.starts_with_tier
                            for bt, s in RESEARCH.items()},
            unlocked_buildings={bt: s.starts_unlocked
                                for bt, s in RESEARCH.items()},
        )

    def add_love(self, amount):
        self.love = max(0, self.love + amount)

    def spend_love(self, amount):
        self.love = max(0, self.love - amount)
