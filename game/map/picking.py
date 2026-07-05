"""Screen→tile picking (Phase 9C).

Uses ``engine.coords`` exclusively — no iso math lives here (clean-arch rule:
only ``engine/coords`` projects between world and screen). The prototype's
bespoke diamond test + ``_world_to_tile`` inverse are replaced by
``screen_to_world`` + floor: world (col, row) is the top corner of that tile's
diamond, so a screen point inside tile (col, row) inverts to world coords in the
unit square ``[col, col+1) × [row, row+1)`` and floors to (col, row).

Pure Python — no pygame.
"""
import math


def world_to_tile(wx, wy):
    """Fractional world coords → integer tile (col, row)."""
    return math.floor(wx), math.floor(wy)


def tile_at_screen(tilemap, coords, screen_x, screen_y):
    """The ``Tile`` under screen pixel (screen_x, screen_y), or None if the
    point falls outside the grid. ``coords`` is the
    ``engine.coords.CoordinateSystem`` (it carries the active camera)."""
    wx, wy = coords.screen_to_world(screen_x, screen_y)
    col, row = world_to_tile(wx, wy)
    return tilemap.get(col, row)
