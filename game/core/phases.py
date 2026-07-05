"""Round-loop + top-level state enums (Phase 9F).

Ports the prototype's two state enums (``src/core/constants.py``): ``GamePhase``
is the in-round loop; ``GameState`` is the top-level app state (menus vs
gameplay vs game over). Only the members 9F actually drives are ever entered;
the rest are DECLARED now — at their prototype ordinal positions — so later
phases layer in without editing this enum (10A ``LEVELUP``, 10G
``BOSS_CUTSCENE``, the 9H shell menu states).
"""
from enum import Enum, auto


class GamePhase(Enum):
    BUILDING = auto()       # player places/upgrades; End Turn -> ENEMY
    ENEMY = auto()          # wave spawns + combat; clear -> ROUND_END
    ROUND_END = auto()      # ROUND_END_DELAY cooldown -> INCOME
    INCOME = auto()         # "PAYDAY": love collected + floaters -> BUILDING
    # Reserved — declared for ordinal fidelity, NEVER entered in 9F:
    LEVELUP = auto()        # village level-up window, after ROUND_END (10A)
    BOSS_CUTSCENE = auto()  # boss A/B choice overlay, after ROUND_END (10G)


class GameState(Enum):
    GAMEPLAY = auto()       # the round loop runs
    GAME_OVER = auto()      # world frozen; only the game-over screen lives (9G/9H)
    # Reserved — the 9H shell state machine enters these:
    CUTSCENE = auto()
    MAIN_MENU = auto()
    SETTINGS = auto()
    CREDITS = auto()
    ADD_NAME = auto()
    PAUSED = auto()
