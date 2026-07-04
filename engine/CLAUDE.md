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
  never hardcoded. `clamp` keeps the viewport on the map, *centring* an axis
  only when the map is smaller than the viewport there; `center_on(wx, wy, w,
  h)` instead parks a chosen world point at the viewport centre (then clamps)
  — use it to frame a target that overflows the viewport, where `clamp` would
  anchor to an edge (the editor's entity preview).
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
  idempotent; already run — its output is committed. Follow-up (Phase 6):
  the same script's `migrate_tiles()` bakes the 9 map tile slots the
  prototype generated procedurally (never stored in its v1 manifest) to
  static PNGs + manifest entries via `editor.asset_import.import_idle_sheet`
  — 7 are direct file copies, `tile_combat[_b]` are a one-time Pillow
  grayscale+tint reproduction of `sprite_gen.py`'s runtime tinting (this
  codebase does not generate art at runtime, D-1/D-2). Also already run;
  output committed.

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

## Phase 9B conventions (physics / components / HUD data)
Everything below is pure Python — no pygame — and headless-testable.

- **`engine/physics/` primitives** (generic; no game vocabulary):
  - `SpatialGrid(cell_size=1.0)` (`grid.py`, E-31) — buckets objects by
    `(floor(wx/cell), floor(wy/cell))`; objects expose
    `obj.transform.world_pos`. `insert/remove/move/rebuild`;
    `query_radius(world_pos, radius)` (Euclidean; scans candidate cells then
    exact-tests) and `query_chebyshev(center_tile, range_tiles)` (tile =
    `(round(wx), round(wy))`, `max(|Δcol|,|Δrow|) <= range`). Returns are in
    **insertion order** (deterministic). Cell membership is fixed at
    insert/rebuild; the exact tests read **live** `world_pos`, so callers keep
    membership fresh via `move()` or a periodic `rebuild()`.
  - `TileOccupancy` (`occupancy.py`, E-32) — `(col,row) -> obj`, one occupant
    per tile: `set/clear/get/is_occupied` (tile keys normalized to tuples).
  - `advance(pos, waypoints, index, speed, dt, threshold=0.06)`
    (`movement.py`, E-30) — pure waypoint step, prototype-exact
    (`enemy.py _do_move`): snap onto the waypoint and advance the index when
    within `threshold`, else step `speed*dt` along the unit direction (no
    overshoot clamp). Returns `(new_pos, new_index, arrived_this_step,
    reached_end)`.
- **`on_added(self, owner)` owner seam** — `Component.on_added` is a default
  no-op; `GameObject.add_component` calls it right after appending. A component
  that needs its owner's transform caches `self._owner = owner` (underscore
  transient — the E-11 setattr guard is on GameObject, not Component).
- **New components** (declared fields only, JSON-safe):
  - `Movement` (`core/movement.py`) — `waypoints/speed/index/
    arrival_threshold/arrived`; `on_added` caches the owner, `update(dt)`
    drives the owner's transform via `physics.advance`, sets `arrived` at
    end-of-path. Inert with no waypoints or once arrived.
  - `RangeSensor` (`core/range_sensor.py`) — `range_tiles`; `in_range(my_tile,
    other_tile)` (pure Chebyshev) and `query(grid, center_tile)` (delegates to
    `grid.query_chebyshev`). Sticky-target / nearest-enemy tiebreak is GAME
    logic (9D/9E), NOT here — the engine only supplies candidates.
- **`Scene` spatial queries** — Scene owns a `SpatialGrid`, `rebuild`t once at
  the start of each `update(dt)` (after the spawn queue). `query_area(world_pos,
  radius)` → `grid.query_radius`; `query_chebyshev(center_tile, range_tiles)` →
  `grid.query_chebyshev`. `by_type`/`by_tag`/`render_items` unchanged.
- **HUD data pass** (`render/hud.py`, E-12) — four frozen, pure, screen-space
  dataclasses: `HudRect`, `HudText`, `HudSprite`, `HudLines`. The host calls
  `Renderer.submit_hud(item)`; at `flush`, AFTER sprites and overlay lines, HUD
  items fold into the same flat draw list **in screen space (no coords
  conversion, no depth sort)** — `HudSprite` resolves to a `DrawCall` via
  `assets.frame(slot_key)`, the other three pass through as-is for the pygame
  backend to `isinstance`-dispatch (mirrors `OverlayLines`). `_hud` clears each
  flush; HUD count folds into the returned count.
- **`engine/video_playback.py`** (E-12) — pure clock/state machine
  (`VideoPlayback(length, enabled=True)`) the cv2 video source composes for
  timing: `advance(dt)` accumulates and marks `done` at the `length` cap;
  `finish/skip/mark_source_ended` all end it; `enabled=False` starts `done`
  (graceful disable). `length` is a constructor param (engine stays
  game-agnostic; the prototype's 44.2 s cap is a caller concern).

## Phase 9B conventions (render backend HUD / fonts / audio / video)
- **`render/fonts.py`** — a lazy `SysFont("monospace", …)` cache keyed by
  font_key (`sm/md/lg/xl/xxl` = prototype `src/ui/fonts.py` 1:1, lg/xl/xxl
  bold; plus `hud_phase=14`, `hud_lvl=12`). `get_font(key)` builds on first
  use (unknown key → 'md'); `TextMetrics().size(text, key)` → `(w, h)` for
  layout without blitting. `pygame.font.init()` is called defensively — works
  headless under SDL dummy. Pure-metadata code that needs string widths asks
  `TextMetrics` so it never imports pygame itself.
- **`render/backend.py` HUD pass** — the backend's flat draw list is
  heterogeneous: sprite `DrawCall`, `OverlayLines` (E-24), and the screen-space
  HUD primitives the RENDERER folds in AFTER sprites+overlays: `HudRect`
  (`pygame.draw.rect` with `border_radius`/`width`), `HudLines`
  (`pygame.draw.lines`), `HudText` (rendered via the `fonts.py` cache, blitted
  at `pos`, `align` left/center/right shifts x by text width). `HudSprite` is
  resolved to a `DrawCall` by the renderer and never reaches the backend. HUD
  coords are already screen-space — the backend does NOT convert them.
  Dispatch is `isinstance`, mirroring `OverlayLines`; the HUD dataclasses live
  in `render/hud.py`. The font cache is lazy, so non-text frames pay nothing.
- **`engine/audio.py`** — thin `pygame.mixer.music` wrapper
  (`play_music`/`stop_music`/`set_volume`). Every call swallows ALL exceptions
  → silent no-op when audio is unavailable (no device, missing file, mixer not
  initialised, SDL dummy). No game vocabulary; the caller passes the path.
- **`engine/video.py`** — OpenCV `VideoSource(path, length, target_size=None)`
  for the cutscene. cv2 is imported LAZILY; graceful skip (`enabled=False`,
  `done=True` immediately) if cv2 is absent, the file is missing, or the
  capture won't open — never crashes, never hangs, headless-safe. Timing is
  delegated to the pure `engine.video_playback` clock (composed; an in-file
  fallback clock keeps it standalone). `update(dt)` advances + reads one frame;
  `frame_surface()` does BGR→RGB → optional resize →
  `pygame.surfarray.make_surface`; `skip()`/`release()` free the capture.
  opencv-python is an OPTIONAL requirement (absent = cutscene skips);
  `tools/build.py` bundles it for the frozen exe via `--collect-all cv2`
  `--hidden-import cv2`.

## Hard rules
- **pygame imports are allowed ONLY in** `render/`'s backend, `render/fonts.py`,
  the asset surface cache, `engine/audio.py`, and `engine/video.py`. `coords/`,
  `core/`, `physics/`, and asset *metadata* code are pure Python — that is what
  keeps game logic headless-testable.
- Rendering never raises on a missing asset (grey X instead).
- No game-specific names in the engine (no "raider", no "flute_player") —
  those belong in `game/` and `data/`.

## Verify before finishing
- Pure-logic changes: run/extend the unit tests (coords round-trip,
  playback_order, grid queries) — T-3.
- Anything render/asset facing: run the headless smoke test (`tools/smoke.py`)
  and, if visuals changed, a live `py game/main.py` look. State exactly which
  you did.
