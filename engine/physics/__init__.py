"""engine.physics — waypoint movement + spatial grid + tile occupancy
(E-30..E-32). Deliberately simple, pure Python, no pygame. Do not grow
forces or collision response without the user asking.
"""
from .grid import SpatialGrid
from .movement import DEFAULT_THRESHOLD, advance
from .occupancy import TileOccupancy

__all__ = ["SpatialGrid", "TileOccupancy", "advance", "DEFAULT_THRESHOLD"]
