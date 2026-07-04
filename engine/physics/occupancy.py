"""TileOccupancy (E-32): which object occupies a tile. Pure Python.

A tile holds at most one occupant. Placement logic and the map editor query
this to know whether a (col, row) is free. Tiles are (col, row) int tuples.
"""


class TileOccupancy:
    def __init__(self):
        self._tiles = {}  # (col, row) -> obj

    def set(self, tile, obj):
        """Record `obj` as the sole occupant of `tile` (replaces any prior)."""
        self._tiles[tuple(tile)] = obj

    def clear(self, tile):
        """Free `tile`. No-op if it was already empty."""
        self._tiles.pop(tuple(tile), None)

    def get(self, tile):
        """The occupant of `tile`, or None."""
        return self._tiles.get(tuple(tile))

    def is_occupied(self, tile):
        return tuple(tile) in self._tiles
