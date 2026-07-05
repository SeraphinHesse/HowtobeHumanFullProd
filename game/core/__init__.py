"""game.core — cross-cutting game runtime.

Phase 9D shipped the single validated balancing loader (``balance.py``). Phase
9F adds the round loop: ``GamePhase`` / ``GameState`` enums (``phases.py``), the
``RunState`` container (``game_state.py``), the prototype-exact ``run_payday``
(``payday.py``), and the ``Session`` orchestrator (``session.py``).
"""
from .balance import DOMAINS, load_all, load_balance
from .game_state import RunState
from .payday import run_payday
from .phases import GamePhase, GameState
from .session import Session

__all__ = [
    "DOMAINS", "load_all", "load_balance",
    "GamePhase", "GameState", "RunState", "run_payday", "Session",
]
