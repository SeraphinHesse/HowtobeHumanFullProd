# CLAUDE.md — engine/coords

THE coordinate authority (E-1..E-5). You reached here from `engine/CLAUDE.md`.
**No other module in the repo may do iso math.** When you change coords
conventions, update THIS doc.

## What it owns
- `world_to_screen`, `screen_to_world` (exact inverse), iso depth key, camera
  state. Geometry constants come from `data/`, never hardcoded.
- **`depth_key(wx, wy, layer_index=0, rank=0)` → `(layer_index, wx+wy, wy,
  rank)`** (VA-3). `rank` is the LAST element and decides only an otherwise
  EXACT tie — layer stays primary (the ground cache depends on it) and iso
  depth still beats it. A 4-tuple with a constant last element sorts exactly as
  the old 3-tuple did, so every existing caller is untouched; `engine/render`
  is still the only consumer. Why it exists and why the lever above it is one
  bool rather than two → `engine/render/CLAUDE.md`.
- `clamp` keeps the viewport on the map, *centring* an axis only when the map is
  smaller than the viewport there.
- **The optional camera LEASH**: `set_camera_limit(CameraLimit(anchor_wx,
  anchor_wy, max_tiles_x, max_tiles_y))` narrows `clamp` to `map bounds ∩ a box
  around the anchor`, and `limit_center_bounds()` exposes that box. Sizes are in
  TILES (grid steps) — converted through the tile half-pitch × zoom, so the leash
  allows the same travel at every zoom level; `0` (or negative) on an axis is
  unlimited and comes back as `±inf`, so a per-axis disable needs no branch at
  the call site. It bounds the viewport **CENTRE**, not the visible edge: the box
  is widened by half a viewport inside `clamp` to become a region box like
  `map_pixel_bounds`', and `_clamp_axis` then does the rest — including the
  existing "centre it instead" branch when the intersection is narrower than the
  viewport. `CameraLimit` is vocabulary-free (an anchor and a tile count, never a
  "spawn point"): **the HOST installs it, never a data loader.** `game/main.py`
  builds one at boot from `core` balancing's `Camera.max_offset_tiles_x/_y`,
  anchored at the map's `camera_limit_center` marker — painted for exactly this
  and nothing else, so "where the camera opens" and "what the play area is
  centred on" stay separately tunable — falling back to `camera_start`, then
  the map centre; the editor
  deliberately never installs one, so its viewport stays free-roam. Storing it on
  the `CoordinateSystem` rather than passing it per call is what makes every
  clamp site — drag-pan, the hosts' `step_zoom`, `center_on`'s trailing clamp —
  honour it with no extra wiring, and is why the editor gets free roam by
  construction rather than by remembering not to pass something.
- `center_on(wx, wy, w, h)` instead parks a chosen world point at the viewport
  centre (then clamps) — use it to frame a target that overflows the viewport,
  where `clamp` would anchor to an edge (the editor's entity preview).
- `visible_tile_window(vw, vh, margin)` returns the integer `(col_min, col_max,
  row_min, row_max)` of tiles that can touch the viewport (AABB of the four
  `screen_to_world` corners, padded by `margin` whole tiles) — the basis of
  windowed tile culling so arbitrarily large maps cost only their visible window.

## Conventions
- **Integer-pan invariant (JitteryMapFix)**: every camera mutator (`pan`,
  `clamp`, `center_on` via its clamp) leaves `pan_x`/`pan_y` WHOLE. Pan is in
  screen pixels; a fractional pan (which only ever leaked in via
  clamp-centring and zoom-recentre division) makes each render path quantize
  it independently at blit time — the ground cache steps at one global
  threshold while per-item sprites (deco/conditions) step at per-item
  sub-pixel phases, so the layers visibly desynced while panning (worst at
  zoom 0.5, where `frame_w/2 · zoom` terms land on quarter pixels). Pinned by
  `test_coords.TestCamera.test_mutators_keep_pan_integer`. Direct `Camera(...)`
  construction stays float-capable (tests, the ground cache's private anchor
  camera); the invariant lives in the mutators, not the dataclass.
- **Geometry** comes from `data/geometry.json` +
  `data/schemas/geometry.schema.json` via
  `engine.coords.load_coordinate_system(data_dir)` (E-1). Camera pan is in screen
  pixels: `screen = iso * zoom - pan`; world (0,0) is the TOP corner of tile
  (0,0)'s diamond.
- `load_coordinate_system(data_dir, map_cols=None, map_rows=None,
  zoom_levels=None, default_zoom=None)`: optional overrides — each map owns its
  dims (D-20); geometry.json keeps pitch as global truth plus fallback dims/zoom
  for map-less/balance-less callers. **Zoom is a balancing tunable, not a
  geometry constant**: the real `zoom_levels`/`default_zoom` live in the
  `core` balancing domain's `Camera` group (`data/balancing/core.json` +
  `schemas/core.schema.json`), and real hosts (game, editor) always pass them
  as the override, the same way each map passes its own cols/rows — mirrors the
  map-dims paragraph above exactly. `default_zoom`, when given, is applied via
  `CoordinateSystem.set_zoom` right after construction, which reuses that
  method's "must be a valid level" `ValueError` as the cross-field check
  (`default_zoom` must be a member of `zoom_levels`) — schema validates each
  field's shape, the loader validates the relationship between them, same split
  `engine/tilemap.py` uses for its own cross-checks.
- Pure Python — no pygame. That is what keeps game logic headless-testable.

## Verify
Coords round-trip unit tests (`world↔screen`), T-3:
`py -m pytest tools/tests/test_<area>.py -q`

Which tests you may run is ROLE-scoped — the role table in §"Test Suite Policy"
(root `CLAUDE.md`) is the only authority, enforced by a `PreToolUse` hook.
