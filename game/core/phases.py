"""Round-loop + top-level state enums (Phase 9F).

Ports the prototype's two state enums (``src/core/constants.py``): ``GamePhase``
is the in-round loop; ``GameState`` is the top-level app state (menus vs
gameplay vs game over). Members are DECLARED at their prototype ordinal
positions so later phases layer in without editing this enum; ``LEVELUP`` was
reserved by 9F and is entered since 10A, ``BOSS_CUTSCENE`` since 10G.
``ENEMY_INTRO`` (feature-enemy-intro-dialogue) is appended LAST, after every
prior member, so no existing ordinal moves.
"""
from enum import Enum, auto


class GamePhase(Enum):
    BUILDING = auto()       # player places/upgrades; End Turn -> ENEMY
    ENEMY = auto()          # wave spawns + combat; clear -> ROUND_END
    ROUND_END = auto()      # ROUND_END_DELAY cooldown -> LEVELUP? -> INCOME
    INCOME = auto()         # "PAYDAY": love collected + floaters -> BUILDING
    LEVELUP = auto()        # modal reward window after ROUND_END (10A)
    BOSS_CUTSCENE = auto()  # boss A/B choice overlay, after ROUND_END (10G)
    # queued enemy-intro dialogue(s) at End Turn, BEFORE the wave actually
    # spawns (feature-enemy-intro-dialogue) — see game/core/CLAUDE.md.
    ENEMY_INTRO = auto()


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
    # Player-identity/high-scores feature. Appended LAST so every ordinal
    # above is unchanged. Unlike the debug-settings modal (a plain
    # ``Shell`` flag — one screen reachable from one place), the high-score
    # table is a real full screen reached from the main menu, so it earns a
    # ``GameState`` member like CREDITS/ADD_NAME.
    HIGHSCORES = auto()
