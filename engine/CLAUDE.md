# CLAUDE.md — ENGINE package

Self-contained guide for `engine/` — the pseudo-engine that carries exactly
this game's workload. You reached here from the root router. Requirements:
SPEC.md §4 (`E-*`). **When you change engine architecture/conventions, update
THIS doc** (not the router, not another package's doc).

## File scope you may edit
`engine/**` and engine-focused tests. Never edit `game/**` or `editor/**` from
an engine task; if an engine change forces a caller change, tell the user
(cross-package task).

## Module map
- `coords/` — THE coordinate authority (E-1..E-5). `world_to_screen`,
  `screen_to_world` (exact inverse), iso depth key, camera state. **No other
  module in the repo may do iso math.** Geometry constants come from `data/`,
  never hardcoded.
- `core/` — `GameObject`, `Component`, `Transform`, `Scene`, frame order
  (E-10..E-15). Rule: **components are what the editor sees; subclasses are
  behavior convenience.** All gameplay state lives in declared component
  fields — that is what makes serialization (E-15) and the editor inspector
  work. Never add authoritative state as a plain subclass attribute.
- `render/` — RenderItem submit → resolve frames via assets → depth sort →
  coords → blit (E-20..E-25). Target-agnostic: game window and editor
  viewport use the SAME pipeline. Overlay pass for range circles / highlights.
- `physics/` — waypoint movement, spatial grid (radius + Chebyshev queries),
  tile occupancy (E-30..E-32). Deliberately simple; do not grow forces or
  collision response without the user asking.
- `assets/` — data-driven slot registry, manifest v2 loader, `playback_order`
  row semantics (rows = animations, row 0 = idle), grey-X placeholder
  (E-33..E-38). Missing/corrupt art logs and falls back — never crashes boot.

## Phase 1 conventions (coords / render / placeholder)
- **Tests** live in `tools/tests/` (unittest, stdlib — no pytest dep). Run
  from the repo root: `py -m unittest discover -s tools/tests -t .`
  SDL dummy drivers are set in-code, so no env setup is needed.
- `engine/data_io.py` — the schema-validating JSON load/write (pure Python;
  used by coords to load geometry, later by the editor/agents to write).
  Deterministic dumps: sorted keys, 2-space indent, trailing newline (D-3).
- **Geometry** comes from `data/geometry.json` +
  `data/schemas/geometry.schema.json` via
  `engine.coords.load_coordinate_system(data_dir)` (E-1). Camera pan is in
  screen pixels: `screen = iso * zoom - pan`; world (0,0) is the TOP corner
  of tile (0,0)'s diamond.
- **Render flow**: `Renderer(coords, assets, backend=None)` — renderer.py is
  pure orchestration producing `DrawCall`s; the pygame backend
  (`engine/render/backend.py`) is lazily imported on first `flush()` and
  injectable for tests. Draw layers fixed: `LAYERS = ("ground", "entities",
  "deco", "overlay")` (E-26); HUD is drawn by the host after flush.
- **Anchor convention**: a frame blits centred horizontally on its world
  position with its bottom edge on the bottom of that tile's diamond
  (`world_to_screen(...)y + tile_h*zoom`). A 64x32 tile frame covers its
  diamond exactly; taller frames rise above it.
- **Assets import boundary**: `engine.assets` package `__init__` + `types` +
  `manifest` + `registry` are pure; pygame lives only in
  `engine.assets.placeholder` and `engine.assets.store` (import those by
  full path). Manifest v2 + registry loading landed in Phase 5 (below).
- `tools/render_demo.py` renders the grey-X grid offscreen and saves
  `build/render_demo.png` (gitignored) for visual verification.

## Phase 2 conventions (core)
- **Component fields** are class-level annotations with defaults
  (`max_hp: int = 10`); `Component.__init_subclass__` collects them into
  `cls._fields`, rejects non-JSON types (allowed: bool/int/float/str/
  list/dict), and registers the class by name for `component_from_dict`.
  Constructor takes field overrides as kwargs, type-checked.
- **Serialization (E-15)**: `GameObject.to_dict()` →
  `{id, name, tags, transform: {wx, wy, layer}, components:
  [{type, fields}]}`. `GameObject.from_dict` returns a *base* GameObject —
  subclass identity is not persisted (components carry all state;
  subclasses are behavior convenience).
- **Setattr guard (E-11, mechanical)**: after `GameObject.__init__`, new
  public attributes raise `AttributeError`; underscore-prefixed transient
  caches are allowed (never serialized, non-authoritative).
- **Frame boundaries (E-13)**: `Scene.update(dt)` applies the spawn queue
  first (`on_spawn`), updates live objects in spawn order (components in
  list order, then the subclass `on_update` hook), applies the despawn
  queue last (`on_despawn`). `Scene.query_area` raises until
  `engine/physics` lands.
- **Render submit hook**: a component with a visual presence defines
  `render_items(transform) -> iterable[RenderItem]` (SpriteAnimator does);
  `Scene.render_items()` collects generically and the host submits to the
  Renderer. `engine.core` may import `engine.render.item` (pure data) —
  still no pygame.
- **E-12 phasing**: `SpriteAnimator` + `Health` shipped in Phase 2.
  `Movement` and `RangeSensor` are deliberately absent (not stubbed) —
  they land together with the `engine/physics` primitives they wrap
  (E-30/E-31), ahead of the phase-9 gameplay port.

## Phase 5 conventions (assets)
- **Module split**: `manifest.py` (pure) holds `playback_order`/`parse_loop`
  — PROTOTYPE-EXACT semantics (rows = animations, row 0 = idle required,
  fps→`max(1, round(1000/fps))` ms, loop = pre-roll + range×count +
  post-roll, hidden dropped AFTER expansion) — plus `Track`/`ManifestEntry`/
  `Manifest`/`entry_from_dict`/`load_manifest`. `registry.py` (pure) loads
  `data/slots.json` into `SlotRegistry` (E-34). `store.py` (pygame) does
  sheet loading + subsurface slicing.
- **E-36**: `Manifest.current_frame(slot, animation, time_ms, phase_ms=0)`
  is a pure function of time → `(sheet_row, sheet_col)` or the `PLACEHOLDER`
  sentinel (`types.py`; compare with `is`). Missing animation falls back to
  the idle row; missing slot / no usable idle → PLACEHOLDER. Note
  `SpriteAnimator` sums `phase_ms` into `anim_time_ms` at emit, so the
  store's `frame(slot, animation, anim_time_ms)` takes ONE summed time.
- **Tolerance split (E-37)**: `load_manifest` NEVER raises — absent file →
  empty manifest (normal pre-import state); corrupt file → warn + empty;
  corrupt entry → warn + skip that entry. `load_registry` fails LOUD (the
  registry is infrastructure, like geometry.json). tools/smoke.py still
  fails loud on an invalid COMMITTED manifest — separate concern.
- **Store**: `AssetStore(manifest, registry, frame_sizes, default_frame_size,
  sprites_dir)`; frame-size precedence manifest entry > registry >
  frame_sizes > default. Sheets load via `pygame.image.load` with NO
  `convert()`/`convert_alpha()` (they need a display; the editor runs SDL
  dummy). Sliced frames are SUBSURFACES — the parent sheet must stay cached.
  There is no cache invalidation: when the manifest changes, build a new
  AssetStore (the editor's `reload_assets()` does exactly that).
- **E-38**: `tools/migrate_prototype_assets.py` converts the prototype's v1
  manifest + imported/ PNGs (read-only) to manifest v2 + copied sheets;
  idempotent; already run — its output is committed.

## Phase 6 conventions (tilemap / overlay / per-map dims)
- **`engine/tilemap.py`** (pure — no pygame, no Qt) is the ONE authority for
  the D-20 map file format, shared by game and editor (they may not import
  each other; user-approved scope addition). `TileMapDoc` +
  `load_map`/`save_map` (schema via data_io PLUS fail-loud ValueError
  cross-checks the schema can't express: row counts/lengths vs dims,
  bounds, id == filename stem). NO game vocabulary in the code: terrain
  cells are single chars resolved through the map file's own schema-pinned
  `legend` (`defaults_from_schema` digs the canonical legend/base slot out
  of `map_file.schema.json`'s consts — schemas over convention).
- **Checkerboard parity is PROTOTYPE-EXACT** (src/map/tile.py):
  `slot_for_code`/`slot_for_cell` append `_b` iff the legend entry has
  `checker: true` AND `(col + row + 1) % 2 == 1` (col+row even).
  Background kinds never alternate. Pinned in test_tilemap_model.
- `render_items(doc, *, terrain/base/deco, tint_for_code)` emits the whole
  map for the one pipeline: ground tiles (optional per-code tint — the
  editor's zone-tint eye), base on `entities`, deco on `deco` (above
  entities, E-26). The game submits all; the editor filters by its eyes.
- **E-24 overlay primitive**: `Renderer.submit_overlay_lines(points_world,
  color, width, closed)` → `OverlayLines` (item.py). Points convert via
  coords at flush; overlay entries are appended AFTER every sprite
  DrawCall in the same flat list (overlays always draw last); the backend
  dispatches on isinstance. Grid lines in the editor use exactly this.
- `load_coordinate_system(data_dir, map_cols=None, map_rows=None)`:
  optional dim overrides — each map owns its dims (D-20); geometry.json
  keeps pitch/zoom as global truth plus fallback dims for map-less hosts.

## Hard rules
- **pygame imports are allowed ONLY in** `render/`'s backend and the asset
  surface cache. `coords/`, `core/`, `physics/`, and asset *metadata* code are
  pure Python — that is what keeps game logic headless-testable.
- Rendering never raises on a missing asset (grey X instead).
- No game-specific names in the engine (no "raider", no "flute_player") —
  those belong in `game/` and `data/`.

## Verify before finishing
- Pure-logic changes: run/extend the unit tests (coords round-trip,
  playback_order, grid queries) — T-3.
- Anything render/asset facing: run the headless smoke test (`tools/smoke.py`)
  and, if visuals changed, a live `py game/main.py` look. State exactly which
  you did.
