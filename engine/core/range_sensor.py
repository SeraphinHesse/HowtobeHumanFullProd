"""RangeSensor (E-12/E-31): Chebyshev tile-range sensing component.

Supplies candidate queries only. Sticky-target retention and Euclidean
nearest-enemy tiebreak are GAME logic (built later); the engine just answers
"which objects are within this square tile range". Pure Python — no pygame.
"""
from .component import Component


class RangeSensor(Component):
    range_tiles: int = 1

    def in_range(self, my_tile, other_tile):
        """Chebyshev tile test: max(|Δcol|, |Δrow|) <= range_tiles. Tiles are
        (col, row) int tuples."""
        return (
            max(abs(other_tile[0] - my_tile[0]), abs(other_tile[1] - my_tile[1]))
            <= self.range_tiles
        )

    def query(self, grid, center_tile):
        """Objects within range via the scene's SpatialGrid (E-31)."""
        return grid.query_chebyshev(center_tile, self.range_tiles)
