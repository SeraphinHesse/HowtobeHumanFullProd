# CLAUDE.md — engine/core

`GameObject`, `Component`, `Transform`, `Scene`, frame order (E-10..E-15), plus
the `Movement`/`RangeSensor` components (E-30/31). You reached here from
`engine/CLAUDE.md`. When you change core conventions, update THIS doc.

**The rule:** components are what the editor sees; subclasses are behavior
convenience. All gameplay state lives in declared component fields — that is what
makes serialization (E-15) and the editor inspector work. Never add authoritative
state as a plain subclass attribute.

## Phase 2 conventions (core)
- **Component fields** are class-level annotations with defaults
  (`max_hp: int = 10`); `Component.__init_subclass__` collects them into
  `cls._fields`, rejects non-JSON types (allowed: bool/int/float/str/list/dict),
  and registers the class by name for `component_from_dict`. Constructor takes
  field overrides as kwargs, type-checked.
- **Serialization (E-15)**: `GameObject.to_dict()` → `{id, name, tags, transform:
  {wx, wy, layer}, components: [{type, fields}]}`. `GameObject.from_dict` returns
  a *base* GameObject — subclass identity is not persisted (components carry all
  state; subclasses are behavior convenience).
- **Setattr guard (E-11, mechanical)**: after `GameObject.__init__`, new public
  attributes raise `AttributeError`; underscore-prefixed transient caches are
  allowed (never serialized, non-authoritative).
- **Frame boundaries (E-13)**: `Scene.update(dt)` applies the spawn queue first
  (`on_spawn`), updates live objects in spawn order (components in list order,
  then the subclass `on_update` hook), applies the despawn queue last
  (`on_despawn`).
- **`queued_by_tag(tag)` (ER-5)** — the objects `spawn()`ed but not yet live.
  `spawn` only QUEUES; the queue merges at the top of the next `update` (E-13), and
  `by_tag`/`objects` read the LIVE list. So any caller that spawns and then asks "is
  anything of this kind left?" **within the same frame** cannot see what it just
  spawned unless it also consults this. That gap silently ended a round under the
  children of an enemy that burst on the wave's last frame (`game/core/session.py`).
- **Render submit hook**: a component with a visual presence defines
  `render_items(transform) -> iterable[RenderItem]` (SpriteAnimator does);
  `Scene.render_items()` collects generically and the host submits to the
  Renderer. `engine.core` may import `engine.render.item` (pure data) — still no
  pygame.
- **E-12 phasing**: `SpriteAnimator` + `Health` shipped in Phase 2. `Movement`
  and `RangeSensor` land with the `engine/physics` primitives they wrap (below).

## Phase 9B conventions (Movement / RangeSensor / owner seam / spatial queries)
Everything below is pure Python — no pygame — and headless-testable.
- **`on_added(self, owner)` owner seam** — `Component.on_added` is a default
  no-op; `GameObject.add_component` calls it right after appending. A component
  that needs its owner's transform caches `self._owner = owner` (underscore
  transient — the E-11 setattr guard is on GameObject, not Component).
- **New components** (declared fields only, JSON-safe):
  - `Movement` (`core/movement.py`) — `waypoints/speed/index/arrival_threshold/
    arrived`; `on_added` caches the owner, `update(dt)` drives the owner's
    transform via `physics.advance`, sets `arrived` at end-of-path. Inert with no
    waypoints or once arrived.
  - `RangeSensor` (`core/range_sensor.py`) — `range_tiles`; `in_range(my_tile,
    other_tile)` (pure Chebyshev) and `query(grid, center_tile)` (delegates to
    `grid.query_chebyshev`). Sticky-target / nearest-enemy tiebreak is GAME logic
    (9D/9E), NOT here — the engine only supplies candidates.
- **`Scene` spatial queries** — Scene owns a `SpatialGrid`, `rebuild`t once at the
  start of each `update(dt)` (after the spawn queue). `query_area(world_pos,
  radius)` → `grid.query_radius`; `query_chebyshev(center_tile, range_tiles)` →
  `grid.query_chebyshev`. `by_type`/`by_tag`/`render_items` unchanged. (The
  primitives themselves live in `engine/physics/` — see that doc.)

## Verify
Unit tests (component field collection, serialization round-trip, frame order,
grid-backed queries): `py -m unittest discover -s tools/tests -t .`
