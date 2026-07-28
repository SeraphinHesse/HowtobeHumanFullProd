"""game.map — runtime tile grid + Dijkstra pathfinder (Phase 9C).

Runtime layer over an ``engine.tilemap.TileMapDoc``: zone/unlock state, the
2×2-chunk tile-unlock mechanic + spawn-zone recede, the six-variant Dijkstra
pathfinder, and screen→tile picking. Behaviour matches the prototype's
``src/map/*``; balancing comes from ``data/balancing/map.json``.
"""
from .conditions import condition_render_items, draws_tint
from .spawn_deco import spawn_deco_render_items, spawn_tree_slots
from .pathfinder import (
    find_path,
    find_path_ignoring_walls,
    find_path_to_nearest_building,
    find_path_to_nearest_defence,
    find_path_to_nearest_economic,
    find_path_to_nearest_non_base_building,
    nearest_non_base_building_tile,
)
from .picking import tile_at_screen, world_to_tile
from .tile_map import BASE_CONTENT_KEY, TileMap, load_map_balance
from .tiles import Tile, TileCondition, TileState

__all__ = [
    "Tile",
    "TileState",
    "TileCondition",
    "TileMap",
    "BASE_CONTENT_KEY",
    "load_map_balance",
    "condition_render_items",
    "draws_tint",
    "spawn_deco_render_items",
    "spawn_tree_slots",
    "find_path",
    "find_path_ignoring_walls",
    "find_path_to_nearest_building",
    "find_path_to_nearest_defence",
    "find_path_to_nearest_economic",
    "find_path_to_nearest_non_base_building",
    "nearest_non_base_building_tile",
    "tile_at_screen",
    "world_to_tile",
]
