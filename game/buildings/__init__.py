"""game.buildings — the building hierarchy (Phase 9D).

Component-owned state (E-11); derived values computed from ``TierState`` +
``data/balancing/buildings.json``. 9D ships the Musician (economy line), the
Defender (defence line) and the BaseBuilding, plus the shared hierarchy and the
factory/placement seam. The other families (Meditator/Painter/AOE/Beam/Boost/
Structure) land in 10x.
"""
from .aoe_defence import AOEDefenceBuilding
from .base_building import BaseBuilding
from .building import Building
from .components import (
    Attacker,
    BeamAttacker,
    Nameplate,
    RoundStats,
    SplashAttacker,
    TierState,
    WallBuilderState,
    YieldEconomy,
)
from .defence import DefenceBuilding
from .defender import Defender
from .economy import EconomyBuilding
from .musician import Musician
from .storm_priest import StormPriest
from .structure import Blocker, StructureBuilding, WallBuilder
from .sun_scorcher import SunScorcher
from .registry import (
    BUILDING_CLASSES,
    PlacementError,
    attach_base,
    build_cost,
    create,
    place_building,
)

__all__ = [
    "Building",
    "EconomyBuilding",
    "Musician",
    "DefenceBuilding",
    "Defender",
    "AOEDefenceBuilding",
    "SunScorcher",
    "StormPriest",
    "StructureBuilding",
    "Blocker",
    "WallBuilder",
    "BaseBuilding",
    "TierState",
    "Nameplate",
    "RoundStats",
    "Attacker",
    "SplashAttacker",
    "BeamAttacker",
    "WallBuilderState",
    "YieldEconomy",
    "BUILDING_CLASSES",
    "PlacementError",
    "create",
    "build_cost",
    "place_building",
    "attach_base",
]
