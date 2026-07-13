"""game.ui — the in-game UI + application shell (Phases 9G, 9H).

Pure logic emitting engine HUD primitives (no pygame; a purity test enforces
it): the in-round UI (9G) — the main ``Hud`` (love/income/lives/phase/End-Turn/
pause), the ``BuildingUI`` selection panel (unlock/construct/upgrade/base_info +
ConstructPreview modal), world-anchored ``FloaterManager`` (income/upkeep
floaters + building HP bars), and the ``GameOverScreen`` — plus the 9H shell:
the ``Shell`` top-level state machine and its menu screens (main menu, settings,
credits, add-a-name, pause) with the session-only ``SessionSettings``. Ports the
prototype's ``src/ui/*`` core onto the clean HUD pass; later phases (10A-10J)
layer the deferred UI depth on top.
"""
from .add_name import AddNameScreen
from .boss_cutscene import BossCutscene
from .building_ui import BuildingUI, ConstructPreview
from .cheat_menu import CheatMenu  # 10H
from .credits import CreditsScreen
from .effects import FloaterManager
from .game_log import GameLog  # 10J
from .game_over import GameOverScreen
from .hud import Hud
from .levelup import LevelupWindow
from .main_menu import MainMenu
from .overlays import MapOverlays
from .pause import PauseScreen
from .settings import SessionSettings, SettingsScreen
from .shell import Shell

__all__ = [
    "Hud",
    "BossCutscene",
    "BuildingUI",
    "CheatMenu",
    "ConstructPreview",
    "FloaterManager",
    "GameLog",
    "GameOverScreen",
    "LevelupWindow",
    "MapOverlays",
    "Shell",
    "MainMenu",
    "SettingsScreen",
    "SessionSettings",
    "CreditsScreen",
    "AddNameScreen",
    "PauseScreen",
]
