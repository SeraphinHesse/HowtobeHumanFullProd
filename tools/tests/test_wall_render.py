"""``game/map/wall_render.py`` — the ONE edge-wall art emitter.

Pure Python, headless: hand-built ``WallEdge``s in a stub tile_map with a stub
owner that only implements ``wall_slot()`` (the duck-typed contract the map layer
reaches through — no ``game.buildings`` import here either). Nothing reads or
writes live ``data/``.
"""
import unittest

from game.map.tile_map import WallEdge
from game.map.wall_render import (
    FRONT_SIDES, LAYER, SIDE_OF_DELTA, edge_world_points, wall_render_items,
)


class StubOwner:
    """The duck-typed builder: ``wall_slot()`` is all the emitter asks for."""

    def __init__(self, slot="wall_t1_lvl1"):
        self._slot = slot

    def wall_slot(self):
        return self._slot


class StubTileMap:
    """Just the ``wall_edges`` registry the emitter iterates."""

    def __init__(self, edges):
        self.wall_edges = {i: e for i, e in enumerate(edges)}


def edge(col_a, row_a, col_b, row_b, owner):
    return WallEdge(col_a, row_a, col_b, row_b, 50, 50, owner)


# ---------------------------------------------------------------------------
class TestEdgeGeometry(unittest.TestCase):
    """The delta -> side table and the shared-corner geometry, both DERIVED from
    engine/coords/system.py's iso math (see the module docstring)."""

    def test_side_of_delta_covers_the_four_neighbours(self):
        self.assertEqual(SIDE_OF_DELTA, {
            (1, 0): "edge_se",
            (0, 1): "edge_sw",
            (-1, 0): "edge_nw",
            (0, -1): "edge_ne",
        })

    def test_edge_world_points_are_the_shared_diamond_corners(self):
        c, r = 3, 5
        # tile (c,r) corners: top (c,r) right (c+1,r) bottom (c+1,r+1) left (c,r+1)
        self.assertEqual(edge_world_points(c, r, c + 1, r),      # edge_se
                         ((c + 1, r), (c + 1, r + 1)))           # right -> bottom
        self.assertEqual(edge_world_points(c, r, c, r + 1),      # edge_sw
                         ((c, r + 1), (c + 1, r + 1)))           # left  -> bottom
        self.assertEqual(edge_world_points(c, r, c - 1, r),      # edge_nw
                         ((c, r), (c, r + 1)))                   # top   -> left
        self.assertEqual(edge_world_points(c, r, c, r - 1),      # edge_ne
                         ((c, r), (c + 1, r)))                   # top   -> right

    def test_non_adjacent_pair_has_no_edge(self):
        self.assertIsNone(edge_world_points(0, 0, 2, 0))         # two apart
        self.assertIsNone(edge_world_points(0, 0, 1, 1))         # diagonal
        self.assertIsNone(edge_world_points(0, 0, 0, 0))         # same tile


# ---------------------------------------------------------------------------
class TestWallRenderItems(unittest.TestCase):
    def test_one_item_per_edge_with_slot_animation_and_layer(self):
        owner = StubOwner("wall_t2_lvl3")
        tm = StubTileMap([
            edge(1, 1, 2, 1, owner),      # +col -> edge_se
            edge(1, 1, 1, 2, owner),      # +row -> edge_sw
            edge(1, 1, 0, 1, owner),      # -col -> edge_nw
            edge(1, 1, 1, 0, owner),      # -row -> edge_ne
        ])
        items = wall_render_items(tm, 0, 4, 0, 4, {"wall_t2_lvl3"})
        # Several walls on ONE tile is correct: different animation rows of the
        # same slot (a corner tile really is walled on two sides).
        self.assertEqual(len(items), 4)
        self.assertEqual({i.animation for i in items},
                         {"edge_se", "edge_sw", "edge_nw", "edge_ne"})
        by_animation = {it.animation: it for it in items}
        for it in items:
            self.assertEqual(it.slot_key, "wall_t2_lvl3")
            self.assertEqual(it.world_pos, (1, 1))   # the PLAYER tile (col_a,row_a)
            # fix/depth-sorted-world-fills: every side is the SAME layer as
            # buildings now — depth is resolved by real position (or, for a
            # same-tile tie, by the HOST's submission order around
            # `FRONT_SIDES` — see game/main.py), not by a fixed layer split.
            self.assertEqual(it.layer, LAYER)
        self.assertEqual(FRONT_SIDES, {"edge_se", "edge_sw"})

    def test_slot_without_art_emits_nothing(self):
        tm = StubTileMap([edge(1, 1, 2, 1, StubOwner("wall_t3_lvl1"))])
        # E-37: an un-imported wall tier draws no sprite at all, not a grey X.
        self.assertEqual(wall_render_items(tm, 0, 4, 0, 4, {"wall_t1_lvl1"}), [])
        # ...and an empty art_slots map early-returns, like conditions.py.
        self.assertEqual(wall_render_items(tm, 0, 4, 0, 4, set()), [])


if __name__ == "__main__":
    unittest.main()
