"""Scene (E-13/E-14): owns GameObjects, drives deterministic update order.

Frame-boundary semantics (E-13): spawn/despawn are queued. update(dt)
applies the spawn queue first (on_spawn), updates live objects in spawn
order, then applies the despawn queue (on_despawn). An object spawned
mid-update is first updated NEXT frame; one despawned mid-update finishes
the current frame. The host's frame order is input → Scene.update(dt) →
render submit (E-14).

Pure Python — no pygame.
"""
from engine.physics import SpatialGrid


class Scene:
    def __init__(self):
        self._objects = []  # live, in spawn order (E-14 determinism)
        self._spawn_queue = []
        self._despawn_queue = []
        self._grid = SpatialGrid()  # rebuilt each update from live transforms

    # -- lifecycle queues (E-13) -------------------------------------------

    def spawn(self, obj):
        self._spawn_queue.append(obj)
        return obj

    def despawn(self, obj):
        self._despawn_queue.append(obj)

    def update(self, dt):
        for obj in self._spawn_queue:
            self._objects.append(obj)
            obj.on_spawn()
        self._spawn_queue.clear()
        # Rebuild the spatial grid once per frame (E-31): buckets objects by
        # their position now, so this frame's queries hit an up-to-date grid.
        # (Exact distance/tile tests read live transforms; the once-per-frame
        # rebuild keeps cell membership fresh — see engine/physics/grid.py.)
        self._grid.rebuild(self._objects)
        for obj in list(self._objects):  # snapshot: mid-update spawns wait
            obj.update(dt)
        for obj in self._despawn_queue:
            if obj in self._objects:
                self._objects.remove(obj)
                obj.on_despawn()
        self._despawn_queue.clear()

    # -- iteration & queries (E-13) ------------------------------------------

    def objects(self):
        return list(self._objects)

    def by_type(self, cls):
        return [obj for obj in self._objects if isinstance(obj, cls)]

    def by_tag(self, tag):
        return [obj for obj in self._objects if tag in obj.tags]

    def queued_by_tag(self, tag):
        """Objects SPAWNED this frame but not yet live: `spawn()` only queues,
        and the queue is merged at the top of the next `update` (E-13). A caller
        that asks "is anything of this kind left?" after spawning within the same
        frame must consult this too, or it will not see what it just spawned."""
        return [obj for obj in self._spawn_queue if tag in obj.tags]

    def query_area(self, world_pos, radius):
        """Objects within Euclidean `radius` of `world_pos` (E-31), via the
        spatial grid rebuilt at the start of the last update."""
        return self._grid.query_radius(world_pos, radius)

    def query_chebyshev(self, center_tile, range_tiles):
        """Objects within Chebyshev tile `range_tiles` of `center_tile` — the
        square range used by tile-range targeting (E-31)."""
        return self._grid.query_chebyshev(center_tile, range_tiles)

    # -- render submit leg of the frame (E-14 / E-20) -------------------------

    def render_items(self):
        """Yield RenderItems from every component that has a visual presence
        (a render_items(transform) hook — e.g. SpriteAnimator)."""
        for obj in self._objects:
            for component in obj.components:
                hook = getattr(component, "render_items", None)
                if hook is not None:
                    yield from hook(obj.transform)
