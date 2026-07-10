"""Round-loop + top-level state enums (Phase 9F).

Ports the prototype's two state enums (``src/core/constants.py``): ``GamePhase``
is the in-round loop; ``GameState`` is the top-level app state (menus vs
gameplay vs game over). Members are DECLARED at their prototype ordinal
positions so later phases layer in without editing this enum; ``LEVELUP`` was
reserved by 9F and is entered since 10A. ``BOSS_CUTSCENE`` (10G) is still
reserved.
"""
from enum import Enum, auto


class GamePhase(Enum):
    BUILDING = auto()       # player places/upgrades; End Turn -> ENEMY
    ENEMY = auto()          # wave spawns + combat; clear -> ROUND_END
    ROUND_END = auto()      # ROUND_END_DELAY cooldown -> LEVELUP? -> INCOME
    INCOME = auto()         # "PAYDAY": love collected + floaters -> BUILDING
    LEVELUP = auto()        # modal reward window after ROUND_END (10A)
    # Reserved — declared for ordinal fidelity, NEVER entered yet:
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
