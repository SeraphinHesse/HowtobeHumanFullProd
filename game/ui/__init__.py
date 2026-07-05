"""game.ui — the in-game UI (Phase 9G).

Pure logic emitting engine HUD primitives (no pygame; a purity test enforces
it): the main ``Hud`` (love/income/lives/phase/End-Turn), the ``BuildingUI``
selection panel (unlock/construct/upgrade/base_info + ConstructPreview modal),
world-anchored ``FloaterManager`` (income/upkeep floaters + building HP bars),
and the ``GameOverScreen``. Ports the prototype's ``src/ui/*`` core onto the
clean HUD pass; later phases (10A-10J) layer the deferred UI depth on top.
"""
from .building_ui import BuildingUI, ConstructPreview
from .effects import FloaterManager
from .game_over import GameOverScreen
from .hud import Hud

__all__ = [
    "Hud",
    "BuildingUI",
    "ConstructPreview",
    "FloaterManager",
    "GameOverScreen",
]
