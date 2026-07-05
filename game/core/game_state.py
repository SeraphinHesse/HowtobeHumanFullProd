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

    @classmethod
    def from_balance(cls, core_balance):
        """Seed a fresh run from the ``core`` balancing domain."""
        hole = core_balance["TheHole"]
        return cls(
            love=core_balance["General"]["starting_currency"],
            base_lives=hole["base_lives"],
        )

    def add_love(self, amount):
        self.love = max(0, self.love + amount)

    def spend_love(self, amount):
        self.love = max(0, self.love - amount)
