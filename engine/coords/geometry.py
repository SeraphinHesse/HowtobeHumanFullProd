"""Geometry constants for the coordinate system (E-1).

Values always come from data/geometry.json (validated) — construct via
Geometry.from_dict; never hardcode pitch or map dims in engine code.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Geometry:
    tile_w: int
    tile_h: int
    map_cols: int
    map_rows: int
    zoom_levels: tuple

    @classmethod
    def from_dict(cls, data):
        return cls(
            tile_w=data["tile_w"],
            tile_h=data["tile_h"],
            map_cols=data["map_cols"],
            map_rows=data["map_rows"],
            zoom_levels=tuple(data["zoom_levels"]),
        )
