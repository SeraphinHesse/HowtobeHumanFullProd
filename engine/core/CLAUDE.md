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
- **`Transform.rank` (VA-3)** — the depth-key tie-break, sitting beside `layer`
  because it is the same kind of thing: draw-order metadata about the OBJECT's
  position, with the same lifetime and the same one consumer
  (`SpriteAnimator.render_items` already reads `layer` off the transform, so a
  one-shot cosmetic sprite needs no new component field to say "draw me behind
  the building I came from"). Deliberately NOT a `SpriteAnimator` field: that
  component is on every building and enemy in the game, and this concerns
  exactly one cosmetic object type — the same argument that kept `loop_count`
  off it in ESV-5. **`to_dict` OMITS it at its default 0** (the manifest
  `row_start`/`slice` convention), so every object saved before VA-3, and every
  object that never opts in, serializes byte-identically.
- **Serialization (E-15)**: `GameObject.to_dict()` → `{id, name, tags, transform:
  {wx, wy, layer}, components: [{type, fields}]}` (plus `rank` when non-zero). `GameObject.from_dict` returns
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
- **`SpriteAnimator.column: int = -1` (MasterSheetColumnsPLAN C3)** — the live
  master-sheet COLUMN this sprite draws at (a season index, a building's
  colour), emitted onto `RenderItem.column`. **`-1` is a sentinel meaning "no
  driver"**, and `render_items` translates it to `RenderItem.column = None`,
  which is what makes the manifest entry's own stored `column` win (D3). Two
  constraints force this shape and neither is cosmetic: a Component field must
  be JSON-safe, so `_JSON_FIELD_TYPES` above rejects `int | None` outright; and
  the sentinel cannot be `0`, because season 0 and colour index 0 are real
  values a caller will drive. Do not "simplify" it to `0`.
- **`SpriteAnimator.visible: bool = True`** (`game/enemies`'s Digger,
  NE-2 follow-up) — `render_items` yields nothing while `False`. Default
  `True` keeps every existing sprite byte-identical; it exists so a component
  can go fully unrendered without the "blank `slot_key`" trap (an unknown key
  resolves to the grey-X placeholder, which is worse than nothing).

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
- **`Scene` spatial queries are LAZY, not per-frame.** Scene owns a
  `SpatialGrid`. `update(dt)` only *dirties* it (`_grid_stamp = None`, one
  attribute store); `_ensure_grid()` rebuilds it on the next
  `query_area(world_pos, radius)` → `grid.query_radius` or
  `query_chebyshev(center_tile, range_tiles)` → `grid.query_chebyshev`, and a
  frame with no query never rebuilds. Staleness is `_grid_stamp !=
  _structure_epoch`, so a mid-update spawn/despawn also invalidates it — a dead
  object can't survive in a bucket a later query reads. Why: the rebuild used to
  run unconditionally at the top of `update`, costing three dict clears plus two
  dict writes, a tuple key and two `math.floor` calls **per object per frame** —
  paid on every frame whether or not anything asked.
  **THE hot caller is defender target acquisition** (`game/enemies/combat.py`
  `_acquire`, via `query_chebyshev`), which asks once per defender, so an
  in-round frame rebuilds exactly once no matter how many defenders there are;
  a frame with no combat (menus, build phase, the editor) still rebuilds never.
  `RangeSensor.query()` remains callerless.
  **Scene's own grid is `SpatialGrid(cell_size=2.0)`, not the class default
  1.0** — a query walks every cell its range box touches, so one cell per tile
  made a range-5 tile query ~144 dict lookups, i.e. *slower* than the full scan
  it replaces at small object counts; two tiles per cell measured
  fastest-or-tied from 20 to 600 objects (`game/PERF.md`). It is a bucket-size
  knob only: results and their order are identical at any cell size.
  `by_type`/`by_tag`/`render_items` unchanged. (The primitives themselves live in
  `engine/physics/` — see that doc.)
- **`by_tag` is INDEXED, not a scan.** Scene keeps `tag -> [live objects]`
  (`_tag_index`), rebuilt lazily when its stamp — `(_structure_epoch,
  gameobject.tags_epoch())` — changes. `_structure_epoch` ticks on **every**
  individual append/remove inside `update` (not once per batch: `on_spawn` can
  itself call `by_tag`, and a batch-level stamp let such a call cache a
  half-merged index for the rest of the frame). `tags_epoch()` is a module-level
  counter in `engine/core/gameobject.py` bumped by the `GameObject.tags` setter,
  so a runtime retag (`game/enemies/kidnap.py` flips a carrier to
  `("kidnapper",)`) invalidates the index without GameObject needing a
  back-reference to its Scene. `by_tag` still returns a fresh list in spawn
  order — same contract, so callers may mutate it or despawn while iterating.
  Why: the game calls `by_tag` ~25x/frame from the effects/session/combat
  passes; at ~700 objects that was ~25 full sweeps per frame (measured 1.28
  ms/frame → 0.013 ms/frame, ~100x). The tradeoff is that a query following a
  mutation pays a rebuild; invalidating before *every* one of the 25 queries
  measures ~3x SLOWER than the old scan, so do not introduce a per-query retag.

## Verify
Unit tests (component field collection, serialization round-trip, frame order,
grid-backed queries): `py -m pytest tools/tests/test_<area>.py -q`

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
