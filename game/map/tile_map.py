"""Runtime tile grid (Phase 9C): zones, 2×2 unlock + spawn recede, occupancy.

Wraps an ``engine.tilemap.TileMapDoc`` into a live grid of ``Tile`` objects and
ports the prototype's ``src/map/tile_map.py`` unlock / recede / weight-refresh
logic. Balancing (``data/balancing/map.json``) is injected as a plain dict;
``load_map_balance`` reads it directly until 9D's ``game/core/balance.py``
generalises the loader.

Grid is indexed ``_grid[row][col]`` (prototype-exact); ``get(col, row)`` swaps.
Unlock sections and the playfield window anchor at the base (the buildable min
corner) rather than the prototype's hardcoded ``PLAYFIELD_*`` constants, so the
math is map-driven. Pure Python — no pygame.
"""
from game.core.balance import load_balance
from .tiles import Tile, TileState


# Map-file legend code -> runtime zone state. The three background kinds
# (forest/cliff/ocean) all collapse to BACKGROUND (impassable terrain).
_CODE_STATE = {
    "b": TileState.BUILDABLE,
    "c": TileState.COMBAT,
    "s": TileState.SPAWNING,
    "f": TileState.BACKGROUND,
    "l": TileState.BACKGROUND,
    "o": TileState.BACKGROUND,
}

BASE_CONTENT_KEY = "base_building"


def load_map_balance(data_dir):
    """Load + schema-validate ``data/balancing/map.json`` (the pathfinder /
    unlock tuning). Thin shim over the centralised loader (9D); kept because
    tests and ``game.map`` re-export this name.
    """
    return load_balance(data_dir, "map")


class TileMap:
    def __init__(self, doc, balance):
        self._doc = doc
        self._balance = balance
        self.cols = doc.cols
        self.rows = doc.rows
        self.base_col = doc.base["col"]
        self.base_row = doc.base["row"]

        # Unlock sections + playfield window anchor at the base (buildable min
        # corner); a one-tile background border → max index = dim-1. This
        # reproduces the prototype's PLAYFIELD 1..dim-1 for the shipped map.
        self._pf_col_min = self.base_col
        self._pf_row_min = self.base_row
        self._pf_col_max = self.cols - 1
        self._pf_row_max = self.rows - 1

        # Round gate for the damage-weight discount (dormant: nothing calls
        # set_round until 9F/10F). Defence-range coverage function is wired by
        # core in 10I; None keeps the range-affects-path feature dormant.
        self.round_num = 1
        self._defence_coverage_fn = None
        # DEFENCE_RANGE_PATH_WEIGHT_ADD lives in the buildings domain and is
        # wired in 10I; 0 keeps the coverage add inert in 9C (and coverage is
        # empty anyway, so it never fires).
        self._defence_range_add = 0

        # Seed the runtime grid from terrain codes; the base occupies its tile.
        self._grid = [
            [Tile(c, r, _CODE_STATE[doc.terrain[r][c]]) for c in range(self.cols)]
            for r in range(self.rows)
        ]
        base_tile = self.get(self.base_col, self.base_row)
        base_tile.state = TileState.BUILT
        base_tile.content_key = BASE_CONTENT_KEY

    # -- balancing accessors ----------------------------------------------

    @property
    def balance(self):
        return self._balance

    @property
    def impassable_weight(self):
        return self._balance["Pathfinding"]["content_weights"]["impassable"]

    def weight(self, tile):
        """Dijkstra edge weight for `tile` under this map's balancing."""
        return tile.pathfinding_weight(self._balance, self._defence_range_add)

    # -- access -----------------------------------------------------------

    def get(self, col, row):
        if 0 <= col < self.cols and 0 <= row < self.rows:
            return self._grid[row][col]
        return None

    def all_tiles(self):
        for r in range(self.rows):
            for c in range(self.cols):
                yield self._grid[r][c]

    def spawning_tiles(self):
        return [t for t in self.all_tiles() if t.state == TileState.SPAWNING]

    def built_tiles(self):
        return [t for t in self.all_tiles() if t.state == TileState.BUILT]

    def buildable_tiles(self):
        return [t for t in self.all_tiles() if t.state == TileState.BUILDABLE]

    # -- tile unlocking (prototype tile_map.py:298-374) -------------------

    def _section_index(self, tile):
        """(col_section, row_section) of the fixed 2×2 grid anchored at the
        base corner. The starting buildable pocket is section (0, 0)."""
        return ((tile.col - self._pf_col_min) // 2,
                (tile.row - self._pf_row_min) // 2)

    def unlock_cost(self, tile):
        """BASE + (col_sec + row_sec) * MOD — cost scales with 2×2-section
        Manhattan distance from the starting buildable section."""
        u = self._balance["TileUnlocking"]
        sc, sr = self._section_index(tile)
        return u["base_unlock_cost"] + (sc + sr) * u["unlock_cost_distance_mod"]

    def get_chunk_for_tile(self, tile):
        """The fixed 2×2 chunk containing `tile` (aligned to the base corner so
        every playfield tile belongs to exactly one non-overlapping chunk)."""
        anchor_col = self._pf_col_min + ((tile.col - self._pf_col_min) // 2) * 2
        anchor_row = self._pf_row_min + ((tile.row - self._pf_row_min) // 2) * 2
        chunk = []
        for dc in range(2):
            for dr in range(2):
                t = self.get(anchor_col + dc, anchor_row + dr)
                if t is not None:
                    chunk.append(t)
        return chunk

    @staticmethod
    def _is_unlocked_state(state):
        return state in (TileState.BUILDABLE, TileState.BUILT)

    def can_unlock(self, tile):
        """Whether the tile's 2×2 chunk may be unlocked now. With
        ``adjacent_unlock_only`` a chunk COMBAT tile must be orthogonally
        edge-adjacent to an already-unlocked (BUILDABLE/BUILT) tile."""
        if not self._balance["TileUnlocking"]["adjacent_unlock_only"]:
            return True
        for t in self.get_chunk_for_tile(tile):
            if t.state != TileState.COMBAT:
                continue
            for nc, nr in ((t.col + 1, t.row), (t.col - 1, t.row),
                           (t.col, t.row + 1), (t.col, t.row - 1)):
                n = self.get(nc, nr)
                if n is not None and self._is_unlocked_state(n.state):
                    return True
        return False

    def do_unlock(self, tile):
        """Convert the tile's 2×2 chunk's COMBAT tiles → BUILDABLE, then recede
        the spawn band one section outward. Returns True if anything changed."""
        if not self.can_unlock(tile):
            return False
        chunk = self.get_chunk_for_tile(tile)
        converted = False
        for t in chunk:
            if t.state == TileState.COMBAT:
                t.state = TileState.BUILDABLE
                converted = True
        if converted:
            self._recede_spawn_after_unlock(chunk)
        return converted

    # -- dynamic zone progression (prototype tile_map.py:377-438) ---------

    def _find_2x2(self, predicate, ref_col, ref_row, min_ring=None):
        """Nearest 2×2 block (top-left anchor) whose four tiles all satisfy
        `predicate`, by squared distance to (ref_col, ref_row). `min_ring`
        optionally forces the block centre's Chebyshev ring ≥ that value (keeps
        the new spawn block strictly behind the converted one)."""
        best = None
        best_d = float("inf")
        for r in range(self.rows - 1):
            for c in range(self.cols - 1):
                block = [self.get(c, r), self.get(c + 1, r),
                         self.get(c, r + 1), self.get(c + 1, r + 1)]
                if any(t is None or not predicate(t) for t in block):
                    continue
                cc, rr = c + 0.5, r + 0.5
                if min_ring is not None and max(cc, rr) < min_ring:
                    continue
                d = (cc - ref_col) ** 2 + (rr - ref_row) ** 2
                if d < best_d:
                    best_d, best = d, block
        return best

    def _in_playfield(self, t):
        return (self._pf_col_min <= t.col <= self._pf_col_max and
                self._pf_row_min <= t.row <= self._pf_row_max)

    def _recede_spawn_after_unlock(self, chunk):
        """Push the spawn band one 2×2 section outward: nearest SPAWNING 2×2 →
        COMBAT, then nearest in-playfield BACKGROUND 2×2 behind it → SPAWNING.
        Never touches BUILDABLE/BUILT tiles; degrades silently at the map edge
        (the prototype logged; a shrinking band is the intended fallback)."""
        if not chunk:
            return
        ref_c = sum(t.col for t in chunk) / len(chunk)
        ref_r = sum(t.row for t in chunk) / len(chunk)

        spawn_block = self._find_2x2(
            lambda t: t.state == TileState.SPAWNING, ref_c, ref_r)
        if spawn_block is None:
            return
        for t in spawn_block:
            t.state = TileState.COMBAT

        sc = sum(t.col for t in spawn_block) / 4
        sr = sum(t.row for t in spawn_block) / 4
        spawn_ring = max(sc, sr)
        bg_pred = lambda t: (t.state == TileState.BACKGROUND
                             and self._in_playfield(t))
        bg_block = self._find_2x2(bg_pred, sc, sr, min_ring=spawn_ring)
        if bg_block is None:  # nothing strictly behind → any background block
            bg_block = self._find_2x2(bg_pred, sc, sr)
        if bg_block is None:
            return
        for t in bg_block:
            t.state = TileState.SPAWNING

    # -- round gate + dormant weight drivers (prototype tile_map.py:117-150) --

    def set_round(self, n):
        self.round_num = n

    def refresh_damage_weight_reductions(self):
        """Mark the top-N damage-dealing built tiles for a weight discount so
        later waves route over them. Dormant in 9C: no occupant reports damage
        and nothing calls ``set_round`` (round gate), so this is a no-op — but
        it is ported whole for 9F/10F to activate by wiring its producers."""
        dmg_cfg = self._balance["Pathfinding"]["damage_reduction"]
        candidates = []
        for t in self.built_tiles():
            t.damage_weight_reduced = False
            occ = t.occupant
            if occ is None or not getattr(occ, "alive", False):
                continue
            if t.content_key == BASE_CONTENT_KEY:
                continue
            dmg = getattr(occ, "damage_dealt_last_round", 0)
            if dmg > 0:
                candidates.append((dmg, t))
        if self.round_num <= dmg_cfg["min_round"] or not candidates:
            return
        candidates.sort(key=lambda dt: dt[0], reverse=True)
        for _, t in candidates[:int(dmg_cfg["top_n"])]:
            t.damage_weight_reduced = True

    def refresh_defence_range_coverage(self, covered_set):
        for t in self.all_tiles():
            t.defence_range_covered = (t.col, t.row) in covered_set

    # -- wall hook (10E) --------------------------------------------------

    def get_wall_between(self, c1, r1, c2, r2):
        """Perimeter wall on the edge between two tiles, or None. No walls
        exist until 10E, so this always returns None (pathfinder treats every
        edge as passable)."""
        return None

    # -- occupancy sync to engine physics (E-32) --------------------------

    def sync_occupancy(self, occupancy):
        """Mirror occupied tiles into an ``engine.physics.TileOccupancy`` so
        placement + range queries (9D+) see the map. Occupancy is *occupant*
        driven (an object standing on the tile); BACKGROUND impassability is a
        pathfinding-weight concern, not occupancy. In 9C nothing occupies a
        tile yet, so this clears everything — it is the single seam 9D wires."""
        for t in self.all_tiles():
            if t.occupant is not None:
                occupancy.set((t.col, t.row), t.occupant)
            else:
                occupancy.clear((t.col, t.row))
