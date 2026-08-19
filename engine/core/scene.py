"""Scene (E-13/E-14): owns GameObjects, drives deterministic update order.

Frame-boundary semantics (E-13): spawn/despawn are queued. update(dt)
applies the spawn queue first (on_spawn), updates live objects in spawn
order, then applies the despawn queue (on_despawn). An object spawned
mid-update is first updated NEXT frame; one despawned mid-update finishes
the current frame. The host's frame order is input → Scene.update(dt) →
render submit (E-14).

Pure Python — no pygame.
"""
from engine.core.gameobject import tags_epoch
from engine.physics import SpatialGrid


class Scene:
    def __init__(self):
        self._objects = []  # live, in spawn order (E-14 determinism)
        self._spawn_queue = []
        self._despawn_queue = []
        # cell_size 2.0, not the class default 1.0: a query scans every cell
        # its range box touches, so one-cell-per-tile makes a range-5 tile
        # query ~144 dict lookups — more than the full scan it replaces at
        # small object counts. Two tiles per cell halves each axis (~36) and
        # measured fastest-or-tied across 20..600 enemies for combat
        # targeting, the one hot caller (`game/PERF.md`).
        # Rebuilt LAZILY — see `_ensure_grid`.
        self._grid = SpatialGrid(cell_size=2.0)
        # Stamp the grid's buckets were built from, or None = dirty. `update`
        # dirties it once per frame (objects moved); a query rebuilds it only
        # if something is actually asking. See `_ensure_grid`.
        self._grid_stamp = None
        # Tag index (E-13): tag -> list of live objects, in spawn order. Lazily
        # (re)built and cached; `_index_stamp` is the (structure, tags-epoch)
        # pair it was built from, so ANY spawn/despawn or `obj.tags = ...`
        # invalidates it. See `_tag_index`.
        self._tag_index_cache = None
        self._index_stamp = None
        self._structure_epoch = 0

    # -- lifecycle queues (E-13) -------------------------------------------

    def spawn(self, obj):
        self._spawn_queue.append(obj)
        return obj

    def despawn(self, obj):
        self._despawn_queue.append(obj)

    def update(self, dt):
        for obj in self._spawn_queue:
            self._objects.append(obj)
            # Per-object, NOT once per batch: on_spawn() may itself call
            # by_tag(), and a stamp bumped before the loop would let that call
            # cache a half-merged index for the rest of the frame.
            self._structure_epoch += 1
            obj.on_spawn()
        self._spawn_queue.clear()
        # Mark the spatial grid stale (E-31) rather than rebuilding it here:
        # objects have moved since last frame, so its cell membership is no
        # longer valid — but nothing may ask this frame, and an unqueried
        # rebuild is pure tax proportional to object count. The first
        # query_area/query_chebyshev of the frame pays for it (`_ensure_grid`).
        self._grid_stamp = None
        for obj in list(self._objects):  # snapshot: mid-update spawns wait
            obj.update(dt)
        for obj in self._despawn_queue:
            if obj in self._objects:
                self._objects.remove(obj)
                self._structure_epoch += 1  # per-object; on_despawn may query
                obj.on_despawn()
        self._despawn_queue.clear()

    # -- iteration & queries (E-13) ------------------------------------------

    def objects(self):
        return list(self._objects)

    def by_type(self, cls):
        return [obj for obj in self._objects if isinstance(obj, cls)]

    def _tag_index(self):
        """tag -> live objects carrying it, in spawn order. Cached; rebuilt only
        when the live set changed (`_structure_epoch`) or some object was
        retagged (`tags_epoch()`).

        This exists because `by_tag` is called ~25x per frame from the effect,
        session and combat passes; as a linear scan that was ~25 full sweeps of
        every object every frame, allocating a list each time. Now it is one
        sweep per frame at most, and usually zero (nothing spawned, despawned or
        retagged since the last query).
        """
        stamp = (self._structure_epoch, tags_epoch())
        if self._tag_index_cache is None or self._index_stamp != stamp:
            index = {}
            for obj in self._objects:
                for tag in obj.tags:
                    index.setdefault(tag, []).append(obj)
            self._tag_index_cache = index
            self._index_stamp = stamp
        return self._tag_index_cache

    def by_tag(self, tag):
        # Copy: callers get a snapshot they may mutate or outlive the index with
        # (several already wrap this in `list(...)` before despawning during the
        # loop) — the same contract the linear-scan version had.
        return list(self._tag_index().get(tag, ()))

    def queued_by_tag(self, tag):
        """Objects SPAWNED this frame but not yet live: `spawn()` only queues,
        and the queue is merged at the top of the next `update` (E-13). A caller
        that asks "is anything of this kind left?" after spawning within the same
        frame must consult this too, or it will not see what it just spawned."""
        return [obj for obj in self._spawn_queue if tag in obj.tags]

    def _ensure_grid(self):
        """Rebuild the spatial grid iff it is stale, then return it.

        Stale means either `update` dirtied it this frame (objects moved) or the
        live set changed since the buckets were built (`_structure_epoch`, which
        ticks on every individual spawn/despawn — so a mid-update despawn cannot
        leave a dead object in a bucket a later query reads).

        Lazy, not per-frame: the grid used to be rebuilt unconditionally at the
        top of every `update`, which is three dict clears plus two dict writes, a
        tuple key and two `math.floor` calls PER OBJECT PER FRAME — paid whether
        or not anything queried. Now a frame with no query costs one attribute
        store, and the frames that DO query pay the rebuild once between them:
        `game/enemies/combat.py::_acquire` (defender target acquisition) queries
        once per defender, so an in-round frame rebuilds exactly once no matter
        how many defenders ask.
        """
        if self._grid_stamp != self._structure_epoch:
            self._grid.rebuild(self._objects)
            self._grid_stamp = self._structure_epoch
        return self._grid

    def query_area(self, world_pos, radius):
        """Objects within Euclidean `radius` of `world_pos` (E-31). Rebuilds the
        spatial grid first if it went stale since the last query."""
        return self._ensure_grid().query_radius(world_pos, radius)

    def query_chebyshev(self, center_tile, range_tiles):
        """Objects within Chebyshev tile `range_tiles` of `center_tile` — the
        square range used by tile-range targeting (E-31)."""
        return self._ensure_grid().query_chebyshev(center_tile, range_tiles)

    # -- render submit leg of the frame (E-14 / E-20) -------------------------

    def render_items(self):
        """Yield RenderItems from every component that has a visual presence
        (a render_items(transform) hook — e.g. SpriteAnimator)."""
        for obj in self._objects:
            for component in obj.components:
                hook = getattr(component, "render_items", None)
                if hook is not None:
                    yield from hook(obj.transform)
