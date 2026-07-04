"""SpatialGrid (E-31): bucket objects by world cell for radius / Chebyshev
queries without a full scan. Pure Python — no pygame.

Objects expose their position via ``obj.transform.world_pos -> (wx, wy)``.
Candidate cells are scanned first, then an exact test filters them, so a
query touches only the cells near the point, not every object. Return order
is deterministic (insertion order) so tests are stable.
"""
import math


def _cell_key(wx, wy, cell_size):
    return (math.floor(wx / cell_size), math.floor(wy / cell_size))


class SpatialGrid:
    def __init__(self, cell_size=1.0):
        if cell_size <= 0:
            raise ValueError("cell_size must be positive")
        self.cell_size = cell_size
        self._cells = {}     # cell key -> list[obj] (per-cell insertion order)
        self._cell_of = {}   # obj -> the cell key it currently sits in
        self._seq = {}       # obj -> global insertion seq (stable sort key)
        self._counter = 0

    # -- membership --------------------------------------------------------

    def _pos(self, obj):
        return obj.transform.world_pos

    def insert(self, obj):
        if obj in self._cell_of:
            return
        wx, wy = self._pos(obj)
        key = _cell_key(wx, wy, self.cell_size)
        self._cells.setdefault(key, []).append(obj)
        self._cell_of[obj] = key
        self._seq[obj] = self._counter
        self._counter += 1

    def remove(self, obj):
        key = self._cell_of.pop(obj, None)
        if key is None:
            return
        bucket = self._cells.get(key)
        if bucket is not None:
            bucket.remove(obj)
            if not bucket:
                del self._cells[key]
        self._seq.pop(obj, None)

    def move(self, obj):
        """Re-bucket obj after its transform moved. No-op if it stayed in the
        same cell; inserts it if it was not tracked yet."""
        old = self._cell_of.get(obj)
        if old is None:
            self.insert(obj)
            return
        wx, wy = self._pos(obj)
        new = _cell_key(wx, wy, self.cell_size)
        if new == old:
            return
        bucket = self._cells.get(old)
        if bucket is not None:
            bucket.remove(obj)
            if not bucket:
                del self._cells[old]
        self._cells.setdefault(new, []).append(obj)
        self._cell_of[obj] = new

    def rebuild(self, objects):
        """Drop all buckets and re-insert `objects` in iteration order. O(n);
        Scene calls this once per frame, then many queries hit the grid."""
        self._cells.clear()
        self._cell_of.clear()
        self._seq.clear()
        self._counter = 0
        for obj in objects:
            self.insert(obj)

    # -- queries -----------------------------------------------------------

    def _ordered(self, objs):
        return sorted(objs, key=lambda o: self._seq.get(o, 0))

    def query_radius(self, world_pos, radius):
        """Objects within Euclidean distance `radius` of `world_pos`. Scans
        only the cells the disc could touch, then does an exact distance test."""
        wx, wy = world_pos
        cs = self.cell_size
        min_cx = math.floor((wx - radius) / cs)
        max_cx = math.floor((wx + radius) / cs)
        min_cy = math.floor((wy - radius) / cs)
        max_cy = math.floor((wy + radius) / cs)
        r2 = radius * radius
        found = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = self._cells.get((cx, cy))
                if not bucket:
                    continue
                for obj in bucket:
                    ox, oy = self._pos(obj)
                    dx = ox - wx
                    dy = oy - wy
                    if dx * dx + dy * dy <= r2:
                        found.append(obj)
        return self._ordered(found)

    def query_chebyshev(self, center_tile, range_tiles):
        """Objects whose tile ``(round(wx), round(wy))`` is within Chebyshev
        distance `range_tiles` of `center_tile` (an (col, row) int tuple):
        ``max(|Δcol|, |Δrow|) <= range_tiles``. This is the prototype's
        square range indicator, diagonals included."""
        ccol, crow = center_tile
        cs = self.cell_size
        # A tile col = round(wx) means wx in [col-0.5, col+0.5); widen the
        # candidate world box by half a tile so every candidate cell is scanned.
        min_cx = math.floor((ccol - range_tiles - 0.5) / cs)
        max_cx = math.floor((ccol + range_tiles + 0.5) / cs)
        min_cy = math.floor((crow - range_tiles - 0.5) / cs)
        max_cy = math.floor((crow + range_tiles + 0.5) / cs)
        found = []
        for cx in range(min_cx, max_cx + 1):
            for cy in range(min_cy, max_cy + 1):
                bucket = self._cells.get((cx, cy))
                if not bucket:
                    continue
                for obj in bucket:
                    wx, wy = self._pos(obj)
                    if max(abs(round(wx) - ccol), abs(round(wy) - crow)) <= range_tiles:
                        found.append(obj)
        return self._ordered(found)
