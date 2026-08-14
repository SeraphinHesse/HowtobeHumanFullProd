# CLAUDE.md — engine/render

RenderItem submit → resolve frames via assets → depth sort → coords → blit
(E-20..E-25). You reached here from `engine/CLAUDE.md`. **Target-agnostic:** the
game window and the editor viewport use the SAME pipeline. When you change render
conventions, update THIS doc.

**pygame lives here** (`backend.py`, `backend_gpu.py`, `fonts.py`,
`ground_cache.py`, `ground_cache_gpu.py`) — `renderer.py`
itself is pure orchestration. See the engine router's pygame-import allow-list.

## Render flow
- `Renderer(coords, assets, backend=None)` — `renderer.py` produces `DrawCall`s.
  The backend CONTRACT (G1) lives in `render/backend_api.py`: a `Backend`
  `typing.Protocol` (`__call__(target, draw_calls) -> None`, documentation +
  a type hook, not a runtime check) plus `default_backend()`, which resolves
  and returns `render/backend.py`'s `draw` function. `backend_api.py` is pure
  (no pygame at module level), so the pygame allow-list below is unchanged.
  Resolution is still lazy — `Renderer.flush()` calls `default_backend()` on
  first flush and memoises the result — and still injectable for tests.
- **`flush(target, hud_target=None)` (G4, D7)** — with a `hud_target`, world
  sprites + overlays go to `target` through `self._backend` (the host's GPU
  backend) and the HUD pass goes to `hud_target` through the SURFACE backend,
  resolved and memoised separately in `self._hud_backend`. **The split is by
  PRODUCTION SITE, never a post-hoc isinstance filter**: `slice`/`crop_rect`
  are set only in the HUD loop and `backend_gpu.draw` raises on either, so
  building the HUD calls into their own list is the structural guarantee that
  such a call cannot reach the world backend. `hud_target=None` (the editor,
  the tools, the Surface host, every existing test) keeps the historical
  single flat list and single backend call, byte-identical. `flush` also
  records `renderer.last_flush_ms = {"world": ms, "hud": ms}` for the host's
  frame-timing line (`hud` is 0.0 on the single-call path).
- Draw layers fixed: `LAYERS = ("ground", "terrain", "entities", "deco",
  "overlay")` (E-26); HUD is drawn by the host after flush. **`terrain` sits
  between `ground` and `entities`** for content that overlays the ground tiles
  but must pass UNDER everything an entity draws — the game's tile-condition
  art is its one consumer (`game/map/conditions.py`). Engine-generic name on
  purpose: no game vocabulary here. Adding it left `ground` at index 0, which
  is what kept the ground-cache invariant below intact.
- **`depth_key = (layer_index, wx+wy, wy, rank)`** makes the draw LAYER the
  primary sort key, so the whole `ground` layer always draws before
  `entities`/`deco`/`overlay`. This is a **LOAD-BEARING invariant** — if
  `depth_key` ever interleaves layers, the ground cache breaks.
  - **`rank` (VA-3) is LAST, and that placement is the design.** It is how a
    cosmetic effect says it draws in front of (+1) or behind (-1) the building
    or enemy standing on its own tile — and only that. Layer still beats it (the
    ground cache), and iso depth still beats it, so an effect on a near tile
    keeps drawing over a building on a far one. It decides what position alone
    cannot: the exact tie.
  - **A 4-tuple whose last element is constant sorts identically to the old
    3-tuple**, so every existing submitter (all of them, today) is a
    byte-identical no-op. `RenderItem`, `WorldFill`, `WorldRect` and
    `WorldLines` all carry `rank: int = 0`; `Transform` carries it too, so a
    scene sprite gets it through `SpriteAnimator.render_items`.
  - **This is why the designer-facing lever is ONE bool, not two.** Buildings
    and enemies share the `entities` layer and sort against each other by the
    same iso depth, so no single total order can put an effect in front of one
    and behind the other.

## Pixel quantizer (`item.round_half_up`, JitteryMapFix)
`engine/render/item.py` exports `round_half_up(v)` = `floor(v + 0.5)` — THE
quantizer for screen coordinates: the backend's dests/sizes/points and the
ground cache's scroll delta + blit offset all use it instead of builtin
`round()`. `round()` is banker's (half-to-even): two dests both ending in .5
could land on different pixels, and a pan crossing a .5 tie double-stepped
2px per item, inconsistently — one half of the layers-desync-while-panning
bug (the other half is the integer-pan invariant in `engine/coords/
CLAUDE.md`). One expression for the `fit_factor` reason: a second copy would
drift. Pinned in `test_render.TestPixelQuantizer`.

## Anchor convention (ER-1)
A frame blits **centred on the tile**: horizontally on its world position,
vertically on the tile diamond's CENTRE — `world_to_screen(...)y +
(tile_h/2)*zoom`. So `dest_y = py + (tile_h/2)*z − h/2`, **continuous in
`frame_h`**. Per-entry manifest `offset_x/offset_y` nudge from there.

This is not a new convention — it is the old one, derived. The old rule had two
branches (a 64x32 tile frame anchored its bottom at `y + tile_h*z`; anything
taller anchored one extra tile-height lower, at `y + 2*tile_h*z` — the prototype
`src/buildings/building.py` sheet convention, art authored centred in the 96px
frame). Write both out and each puts the frame's centre on `py + tile_h/2`:
they were the SAME rule spelled out for `frame_h == tile_h` and `frame_h ==
3*tile_h`, with a 32px cliff for everything in between. Every non-enemy world
frame that ships is 96 or 32 tall, so the new rule is **byte-identical** for
buildings / tiles / deco / core; the enemy sheets (18/26/28/56/84/88 tall) are
the intended moves — they used to hang above their tile.

**`sprite_anchor_screen(cs, wx, wy, frame_w, fit_tiles, scale, offset_xy,
anchor_xy)` (fix-anchor-origin-parity)** — exported from this module (and
`engine.render`) alongside `fit_factor`/`block_center_offset`: the SCREEN
point a manifest `anchor_xy` (frame-px, `(0, 0)` = the sprite's drawn
CENTRE) resolves to for the sprite `flush` draws at world position
`(wx, wy)`. It composes `block_center_offset` + `fit_factor` + this
module's centre convention — never restates them — evaluated for one point
instead of a whole blit. THE one shared origin every anchor consumer, game
and editor alike, must resolve through: `game/anchors.py`'s
`anchor_world_point` (game side) and `editor/panels/viewport.py`'s
`_anchor_draw_params` (editor side) both call it, closing the gap that
shipped as a live bug — the editor drew every anchor handle from the
sprite's drawn centre while the game resolved the SAME anchor from a
different base (`cs.world_to_screen(obj.transform.world_pos)`, missing both
the `tile_h/2*zoom` tile-diamond-centre shift and, for a multi-tile
footprint, the `block_center_offset` shift), so a handle dragged onto a
sprite landed somewhere else in game — always, for every anchor. Measured
gap on the fixture geometry (tile_h=32, zoom=1): exactly 16px. `frame_h`
never enters this function — the centre sits on the tile diamond's centre
regardless of frame height, per the Anchor convention above. Pure: no
pygame, no game vocabulary. See `docs/briefs/fix-anchor-origin-parity.md`.

## Sizing: `fit_tiles` / `scale` (ER-1, downscale-only)
`RenderItem`/`SpriteAnimator` carry two engine-generic sizing fields (**no game
vocabulary here** — never `footprint`/`sprite_scale`, those are the `game/` names
that feed these):

    fit  = min(1.0, (fit_tiles * tile_w) / frame_w)   if fit_tiles > 0 else 1.0
    s    = fit * scale                                # w,h,offsets all ride s

- `fit_tiles` = how many TILES wide the thing may span. The sprite is scaled DOWN
  to fit and **never up** — a 124x96 boss sheet at `fit_tiles=1` draws 64px wide;
  a 16x16 frame stays 16px (art smaller than its footprint is padded at import,
  not magnified). Sizing therefore derives from the tile footprint, never from
  raw sheet pixels.
- `scale` multiplies AFTER the fit — the deliberate knob for low-res art, and it
  may exceed 1.
- **Hard invariant:** `fit_tiles == 0.0 and scale == 1.0` (the defaults) ⇒
  `s == 1.0` ⇒ output is pixel-identical to pre-ER-1. Buildings, tiles, deco and
  the HUD pass are provably untouched — pinned by `test_render.TestAnchoring`
  (`test_ground_tile_anchor` / `test_tall_entity_anchor` are unchanged from
  before ER-1, plus a table-driven pin against the old formula).
- Manifest `offset_x/offset_y` are authored in FRAME pixels, so they ride `s`
  too (a no-op at `s == 1`).
## Multi-tile units draw on their BLOCK centre (ER-5)
A `fit_tiles`-wide unit is ADDRESSED by its anchor (the block's min corner — that
is the tile the game paths it to) but must be DRAWN on the block's centre, which
is `(fit_tiles − 1) / 2` tiles along BOTH axes. `block_center_offset(fit_tiles)`
is that expression, exported for the same reason `fit_factor` is (below).
- Added to both world axes it **cancels in the iso x term** (`ix = (wx−wy)·half_w`)
  and lowers y by `(fit_tiles − 1) · tile_h/2`: **0px at fit_tiles 1, 16px at 2,
  32px at 3.** Before ER-5 a 2-tile unit drew exactly half a tile-height above its
  block, with zero horizontal error — which is why the bug read as "slightly
  floating" rather than "misplaced".
- **It is a provable no-op at `fit_tiles` 0 (guarded) and 1 (arithmetic)** — so
  buildings, tiles, deco, HUD and every 1-tile enemy are untouched. That is the
  whole safety argument, and it is the same one ER-1 made for the fit itself.
- **It shifts the BLIT only, never `depth_key`** (which sorts on the raw
  `world_pos`). Folding it into the sort would move draw ORDER with position.
- The game's overhead HP bars (`game/ui/effects.py:_sprite_top`) call
  `block_center_offset` too — a bar has to ride the sprite it hangs off.

- **`fit_factor(frame_w, tile_w, fit_tiles)` is exported** as THE one expression
  for the fit. Anything that must place a HUD element over a drawn sprite (the
  game's overhead HP bars) has to size that sprite exactly as `flush()` does, so
  it calls this instead of restating the formula — a second copy would drift the
  moment the rule changes. `Renderer.assets` exposes the store for the frame size
  that goes with it (`frame_size()` is pure metadata — it loads no surface).

## Overlay primitives (E-24 + 10J)
`Renderer.submit_overlay_lines(points_world, color, width, closed)` →
`OverlayLines` (item.py). Points convert via coords at flush; overlay entries are
appended AFTER every sprite DrawCall in the same flat list (overlays always draw
last); the backend dispatches on isinstance. Grid lines in the editor use exactly
this.

`Renderer.submit_overlay_polys(points_world, color)` → `OverlayPolys` (10J): a
FILLED polygon, same world→screen contract, interleaved with lines in submission
order. `color` may be **RGBA** — alpha < 255 alpha-blends onto the target (the
backend draws it onto a bounding-box `SRCALPHA` scratch surface and blits; opaque
colors take the direct `pygame.draw.polygon` path). Tile fills, splatters, and
glows use this; ellipses are caller-side polygon approximations.

**Both of the above are ALWAYS drawn dead last, after every sprite in every
layer, regardless of when in the frame they were submitted** — the docstrings
say so directly ("overlays always draw on top"). This is correct and load-bearing
for their actual consumers (editor grid lines, anchor handles, splatters/craters
that are deliberately drawn over sprites — `game/ui/CLAUDE.md`'s "Known
divergences"). **It is the WRONG primitive for anything that needs to draw
BEHIND a specific building** — reordering the *submission* call relative to
`world.scene.render_items()` has NO effect on either of these two, since `flush()`
processes `self._queue` (every sprite) and `self._overlay` (every line/poly) as
two separate, fixed-order passes. (This was a real bug: `fix/highlight-render-order`
initially tried exactly that reorder for tile-highlight diamonds and it was a
complete no-op on the actual rendered frame.)

### Depth-sorted world fills — `submit_world_fill` / `WorldFill`
(`fix/depth-sorted-world-fills`) For anything that DOES need to sort against a
specific building's real tile position — a selection/heatmap/tier-overview
diamond, a wall segment — use `Renderer.submit_world_fill(points, world_pos,
layer="entities", color=None, border=None, border_width=2)` instead. Unlike
`submit_overlay_polys`/`submit_overlay_lines`, this appends a `WorldFill` (see
`item.py`'s docstring) to the SAME queue as `RenderItem` (`self._queue`, not
`self._overlay`), so it goes through the SAME `depth_key = (layer_index,
wx+wy, wy)` sort as every building — `flush()`'s single sorted loop
`isinstance`-branches per item and builds the poly/line `DrawCall`s at that
item's actual sorted position instead of in a separate trailing block.
- **`world_pos` must match the tile's building-anchor convention** — the RAW
  `(col, row)` a `Transform` uses (`game/buildings/building.py`:
  `Transform(wx=float(col), wy=float(row))`), NOT the tile centre. Match it and
  a same-tile building tie-breaks purely by SUBMISSION ORDER (Python's stable
  sort): submit the fill before the building's `RenderItem` to draw behind it,
  after to draw in front. A fill on a DIFFERENT tile sorts correctly against
  ANY building anywhere via the ordinary `wx+wy`/`wy` comparison — the exact
  same rule two buildings already sort by, so no extra math is needed for
  cross-tile depth to be correct.
- `color=None` draws outline-only (the `submit_tile_diamond` shape);
  `border=None` skips the outline (the `submit_tile_diamond_fill` shape); both
  set draws a filled diamond with an outline on top, same as before.
- Consumers: `game/ui/widgets.py`'s `submit_tile_diamond`/
  `submit_tile_diamond_fill` (→ every tile highlight: click/drag-select,
  condition tint, RANGE, HEATMAP, TIER OVERVIEW, the tutorial highlight — one
  choke point, so every caller of those two got this for free) and
  `game/map/wall_render.py`'s wall-art emitter (see `game/map/CLAUDE.md`).

### Screen-pixel depth items — `submit_world_rect` / `submit_world_lines` (VA-3)
`WorldFill` is depth-sorted but its polygon is WORLD-space, so it grows and
shrinks with zoom — right for a tile diamond, wrong for a particle, which is a
few screen pixels at every zoom level. `HudRect` has the fixed size but lives in
the HUD pass, drawn dead last with no depth at all. A spark that wants to pass
BEHIND the building that emitted it needs both halves, and `WorldRect` /
`WorldLines` are it: a world `world_pos` that decides ONLY where the item sorts,
plus **fully-resolved SCREEN-pixel geometry**.
- **The caller resolves the pixels, not `flush`.** This is deliberate: the
  caller already holds the `CoordinateSystem` (it needs it for the equivalent
  HUD submit), and resolving at flush would round at a different point than the
  HUD pass does. That is not hypothetical — an anchor-relative offset truncates
  `int(offset)` where `VfxSystem.submit_hud` truncates `int(anchor + offset)`,
  **measured 1px apart on a slash line** while writing `test_depth_rank.py`.
  Carrying the final rect makes "the same effect drawn in the other pass does
  not move" true by construction rather than by matching two rounding sites by
  hand.
- **Both resolve to `OverlayPolys`/`OverlayLines`, never a HUD primitive** —
  `backend_gpu.draw` raises `NotImplementedError` on every HUD primitive by
  design (D7), so a `HudRect` in the depth-sorted world list would crash the GPU
  host. Pinned by `test_depth_rank.TestWorldPixelPrimitives`.
- Consumer: `engine/vfx/system.py`'s `submit_world`, the depth-participating
  alternative to its `submit_hud` (which stays the default, and stays
  always-on-top).

## Backend throughput (perf, for hundreds of entities/projectiles)
`render/backend.py`:
1. A module-level `WeakKeyDictionary` **scaled-frame cache** keyed by
   source-surface identity avoids re-running `pygame.transform.scale` for the same
   (surface, size) each frame at zoom≠1 — only the scale is cached; flip/tint stay
   per-call (they copy); the grey-X placeholder is a fresh surface each call so it
   never leaks (weak eviction).
2. Plain sprite draws accumulate into one `target.blits(...)` **batch**, flushed
   whenever a non-sprite (overlay/HUD) call must land in order.
Both are pixel-transparent (tests in `test_render.TestBackendThroughput`).

## Second backend: `render/backend_gpu.py` (G2), the WORLD path only
A second `Backend` draws the same flat draw list onto a
`pygame._sdl2.video.Renderer` instead of a `Surface`: the source uploads to a
`Texture` once and all scaling lives in the destination rect, so zoom ≠ 1 costs
no `transform.scale` per frame. **Sprites and overlays only** — `HudRect`/
`HudLines`/`HudText`, `DrawCall.slice` and `DrawCall.crop_rect` stay
single-implementation on `backend.py` and raise `NotImplementedError` here
(D7; the HUD composites over the GPU frame in G4). Its texture cache is keyed by
source-surface identity in a `WeakKeyDictionary` exactly like `_scale_cache`
above (weak eviction is what stops the grey-X placeholder leaking a texture per
call), with an inner `id(renderer)` key because pygame-ce's `Renderer` is not
weak-referenceable; `clear_cache()` clears it. Dests, sizes and overlay points
still go through `round_half_up` and reach SDL as integer `Rect`s, never floats.
**The game host selects it (G4)** via `--backend={auto,gpu,surface}` (default
`auto`; `HTBH_RENDER_BACKEND` when there is no argv), constructing
`Renderer(cs, assets, backend=backend_gpu.draw)` — `default_backend()` is still
the Surface blitter for everyone else (editor, tools, tests, and the D8
fallback). The HUD composites over the GPU frame as ONE streaming-texture
upload per frame, driven by `Renderer.flush(target, hud_target=…)` (below).
Parity is pinned in `test_render_backend_parity.py`.

**Overlay pass (`OverlayLines`/`OverlayPolys`) — clipped scratch, reused
buffer (G5).** `_draw_lines`/`_draw_polys` still rasterize with the SAME
`pygame.draw.lines`/`pygame.draw.polygon` call `backend.py` uses (the parity
argument), but the bounding-box scratch is (1) clipped to
`target.get_viewport()` **before** anything is allocated — an overlay wholly
outside the target is a no-op, returned before any `Surface`/`Texture`
construction, since `Texture(renderer, (0, 0))` raises `ValueError` where
`Surface((0, 0))` would silently succeed — and (2) drawn into ONE
module-level scratch `Surface` reused across every overlay call, every
renderer, every frame, instead of a fresh allocation per call. The scratch
grows to the high-water mark and is never shrunk; growing it invalidates the
per-renderer streaming `Texture`s that mirror its size (`_overlay_textures`,
keyed by `id(target)` for the same reason `_texture_cache`'s inner key is —
`Renderer` is not weak-referenceable). Each draw clears only the sub-rect it
is about to use (`Surface.fill((0,0,0,0), rect)`, not the whole high-water
buffer), refreshes the matching Texture in place with `texture.update(scratch,
area)`, and draws with an explicit `srcrect=area` — the reused Texture is
usually larger than the current overlay, so an implicit "draw the whole
Texture" would stretch it over the destination. This Texture is **never**
routed through `_texture()`/`_texture_cache` above: that cache snapshots at
first draw and never refreshes, which is wrong for a buffer whose pixels
differ on every call. The translation that maps world points into the
scratch's local coordinates uses the **clipped** rect's origin, not the raw
bbox's — using the raw origin after clipping the size is a one-pixel-shift
regression. `clear_cache()` drops the scratch buffer and every per-renderer
overlay Texture along with the sprite texture cache. Tests:
`TestOverlayClipReuse` in `test_render_backend_parity.py`.

**KNOWN PARITY GAP — LAYERED translucent overlays differ by up to 2/255, and
it is platform-dependent.** The two backends do not blend alpha through the
same code: the GPU path uploads the scratch and lets SDL composite it with
`BLENDMODE_BLEND`, while `backend.py` blits an SRCALPHA scratch with pygame.
Over a **flat background** the two round identically on every platform tested
(hence `TestParity`'s `alpha=100` poly is green everywhere, CI included). Over
an **already-drawn destination** — a translucent overlay laid on top of an
earlier overlay — they diverge: measured **2/255 per channel** on SDL's Linux
software renderer in CI, and **0** on Windows/Direct3D. Found 2026-08-13 when
G5's new clipped-overlay cases layered a translucent poly over a line and went
red on CI while passing locally.

Consequences, in order of importance:
- **`CHANNEL_TOLERANCE = 1` stays pinned.** Plan §9 forbids relaxing it, and
  widening a global tolerance to accommodate one blend path would blind every
  other parity assertion. `TestOverlayClipReuse` uses opaque colours instead,
  so it asserts the clip and nothing else.
- **No parity test currently asserts layered-alpha equality**, deliberately —
  the platforms do not guarantee it, so asserting it makes CI a coin toss.
- **In game this is not visible**: 2/255 on one channel where two translucent
  overlays cross. It is recorded because a future reader comparing the two
  backends pixel-by-pixel will otherwise re-discover it as a "bug".
- If bit-identical layered alpha is ever actually required, the fix is to make
  both paths composite the same way (e.g. pre-composite all overlays into one
  scratch before upload), not to move the tolerance.

## Nine-slice (A2) — `DrawCall.slice`, HUD only
A `DrawCall` may carry `slice = (left, top, right, bottom)` — nine-slice margins
in FRAME pixels, authored on the manifest entry and carried
`ManifestEntry → Frame → DrawCall` untouched. **Only the backend interprets
them**; `renderer.py` copies `frame.slice` onto the HUD `DrawCall` and the
world-sprite `DrawCall` never sets it (world sprites keep uniform zoom scaling).
- `_nine_patch` composites corners **1:1 (never resampled)**, edges stretched on
  one axis, the centre on both. `_clamp_pair` floors negatives to 0, then clamps
  the opposite margins proportionally into the source and then the destination,
  so on overflow they fill the axis exactly: the centre band vanishes and the
  corners *squeeze* instead of producing a negative rect. **Any margins are safe
  at any dest size** (down to 1×1, and including negatives) — the editor feeds
  this unsaved draft margins straight from the slice spinboxes, and rendering
  degrades rather than raising (E-37).
- **`_clamp_pair` moved to `engine/assets/nine_slice.py` (A8)**, imported here as
  `from engine.assets.nine_slice import clamp_pair as _clamp_pair` — the two
  `_clamp_pair(...)` calls inside `_nine_patch` are otherwise unchanged (same
  algorithm, same object, not a reimplementation). It moved so the pixel
  hit-mask (`AssetStore.hit_opaque`, `engine/assets/CLAUDE.md` "Pixel
  hit-mask") can share the exact same clamp from a pure module (no pygame)
  when it inverts this same band layout via `nine_slice.dest_to_source` — the
  forward composite and the hit-test inverse can never drift apart.
- **No-ops take the plain `_scaled` path** (and so share its cache entry):
  `slice is None`, an all-zero slice, and a 1:1 draw. The grey-X placeholder
  never carries a slice, so it stays on that path — `test_placeholder_surfaces_
  do_not_leak` is unaffected.
- **Cache**: composites live in the SAME `WeakKeyDictionary`, in the source
  surface's inner dict, under a `("9p", size, margins)` key. A 3-tuple can never
  collide with a plain scale's bare `size` key, and weak eviction still holds
  (the inner dict hangs off the source surface). Margins are IN the key because
  the editor re-draws one cached frame at many margins while the designer drags
  the slice spinboxes.
- **`transform.scale`, not `smoothscale`** — our sheets are pixel art with
  per-pixel alpha and no `convert_alpha()`; smoothscale filters RGB across alpha
  edges (fringing) and blurs pixel art. It is also already what every world
  sprite goes through at zoom ≠ 1, so HUD skins stay consistent with the world.
  Revisit by eye if real UI art turns out to be high-res: only the 4 edges + the
  centre are ever resampled, so it is a one-line swap. Tests: `test_nine_slice.py`.

## Crop (`DrawCall.crop_rect`), HUD only (feature-enemy-intro-dialogue)
A `HudSprite` may carry `crop = (x, y, w, h)` (frame-px, resolved by
`renderer.py` onto `DrawCall.crop_rect`) — a source SUB-RECT drawn instead of
the whole resolved frame, stretched to `size` exactly like the whole-frame
case. `None` (default) is a no-op; the grey-X placeholder never carries one.
- **`backend.py`'s `_cropped(surface, rect)`** clamps the rect into the
  surface's own bounds (never raises — E-37, the `_nine_patch`/`_clamp_pair`
  tolerance style) and memoizes the resulting subsurface in the SAME weak
  `_scale_cache`, under a `("crop", (x, y, w, h))` key — distinct from
  `_nine_patch`'s `("9p", size, margins)` key, so the two kinds can't collide.
  `draw()` resolves the crop FIRST, then feeds the cropped surface into the
  existing `_scaled`/`_nine_patch` step in its place — the cropped surface is
  itself a valid, stable cache key, so "crop, then stretch to dest size"
  needs no new scaling code.
- **Incoherent combined with `slice` on the same entry, by design, not
  guarded**: nine-slice margins are authored against the FULL frame, not a
  crop sub-rect. No shipped manifest entry combines the two; a future one
  that does gets an unspecified (not a crash) composite.
- World sprites (`RenderItem`/`SpriteAnimator`) do not carry a crop — HUD
  only, same scope as `slice`/`tint`. `game/ui/enemy_intro.py`'s enlarged
  enemy-art dialogue is the first (and so far only) consumer.

## HUD pass + fonts (Phase 9B)
- **`render/hud.py`** (E-12) — four frozen, pure, screen-space dataclasses:
  `HudRect`, `HudText`, `HudSprite`, `HudLines`. The host calls
  `Renderer.submit_hud(item)`; at `flush`, AFTER sprites and overlay lines, HUD
  items fold into the same flat draw list **in screen space (no coords
  conversion, no depth sort)** — `HudSprite` resolves to a `DrawCall` via
  `assets.frame(slot_key, animation, anim_time_ms)`, the other three pass through
  for the pygame backend to `isinstance`-dispatch (mirrors `OverlayLines`). `_hud`
  clears each flush.
- **HUD sprites animate (A1)** — `HudSprite` carries `animation: str = "idle"` and
  `anim_time_ms: int = 0` (declared AFTER `flip`, because the shipping call sites
  pass `slot_key, dest, size` positionally; new call sites pass the two by
  keyword). Same slot/animation/time contract as `RenderItem`: a missing animation
  row falls back to idle, a single-frame track is time-invariant, and the defaults
  make the resolved `DrawCall` byte-identical to the pre-A1 one.
- **`HudSprite.hidden_frames` (feature-enemy-intro-dialogue)** — an optional
  tuple of frame-COLUMN indices, appended after `crop` (see above), threaded
  by `renderer.py` into `assets.frame(..., extra_hidden=hud.hidden_frames or
  None)`. `Manifest.current_frame`'s `extra_hidden` (`engine/assets/
  CLAUDE.md`) UNIONS it with whatever the manifest row's own `hidden` list
  already drops for that animation — a per-caller narrowing, never a
  widening. Deliberately HUD-only: `RenderItem`/`SpriteAnimator` gained no
  matching field, since no world-sprite consumer needs one yet.
- **`render/backend.py` HUD pass** — dispatch is `isinstance`: `HudRect`
  (`pygame.draw.rect` with `border_radius`/`width`), `HudLines`
  (`pygame.draw.lines`), `HudText` (rendered via the fonts cache, blitted at
  `pos`, `align` left/center/right shifts x by text width). `HudSprite` is
  resolved by the renderer and never reaches the backend. HUD coords are already
  screen-space — the backend does NOT convert them.
- **RGBA colors (10J)**: `HudRect` and `HudText` accept a 4-tuple color; alpha
  < 255 alpha-blends (rect via an `SRCALPHA` scratch surface, text via
  `set_alpha` on the rendered run). 3-tuples keep the original direct paths —
  callers that don't need alpha pay nothing. `HudLines`/`OverlayLines` stay
  RGB-only. Tests: `test_alpha_render.py`.
- **`render/fonts.py`** — a lazy `SysFont("monospace", …)` cache keyed by font_key
  (`sm/md/lg/xl/xxl` = prototype `src/ui/fonts.py` 1:1, lg/xl/xxl bold; plus
  `hud_phase=14`, `hud_lvl=12`). `get_font(key)` builds on first use (unknown key
  → 'md'); `TextMetrics().size(text, key)` → `(w, h)` for layout without blitting.
  `pygame.font.init()` is called defensively — works headless under SDL dummy. **A
  cached font whose pygame session was torn down (a prior `pygame.quit()`) is
  transparently rebuilt** — `get_font` probes it with `get_height()` first — so
  repeated in-process boots of a text-drawing host (tools tests / smoke re-running
  `game.main`) never hit "font module quit since font created" (added 9F).
  Pure-metadata code that needs string widths asks `TextMetrics` so it never
  imports pygame itself.
  - **`configure_fonts(doc, font_path=None)` (UH-6, D5; UH-Font-A)** — the ONE
    way `_FONT_SPECS`/`_FONT_PATH` change after import: takes a LOADED
    `data/ui/fonts.json` dict (`{key: {size, bold}}`, same 7 keys), rebinds
    `_FONT_SPECS` in place and clears `_cache` so stale fonts are rebuilt. The
    module stays data-dir-free (no `data_io` call inside it) — the HOST
    (`game/main.py`, `editor/main.py`) loads + schema-validates the file and
    passes the plain dict, mirroring how `engine.tilemap` consumes docs. Fails
    loud on a key-set mismatch. The `_FONT_SPECS` literals are the
    UNCONFIGURED FALLBACK for bare test/tool construction; a pin test
    (`tools/tests/test_theme_data.py`) proves they equal the committed
    `fonts.json`, so the fallback can never silently drift from the data it
    mirrors.
    - **`font_path` (UH-Font-A, optional)** is the game-wide custom font
      family — ORTHOGONAL to the per-key size/bold presets: an absolute path
      to a `.ttf`/`.otf`, or `None` (the default) to keep the plain
      `SysFont("monospace", ...)` fallback exactly as before. The HOST
      resolves `data/ui/active_font.json` + `data/fonts/font_manifest.json`
      to this value — `game/main.py` fails loud on a bad reference (D-2),
      the editor's Theme panel degrades to `None` (E-37). See
      `data/CLAUDE.md` "Theme data".
    - **The file is READ ONCE into `_FONT_BYTES`, and `get_font` builds each
      size from an `io.BytesIO` over those bytes — NEVER from the path.**
      `pygame.font.Font(<path>, size)` makes SDL_ttf hold that file OPEN for
      the font object's whole lifetime, and those objects live in `_cache`
      until the process exits; on Windows that is a hard lock. Via the path
      form, the editor sat on the designer's font file for its whole run and
      every `TempDataCase` teardown died on `shutil.rmtree` ->
      `PermissionError` the moment a non-`"default"` font was active — which
      is why nothing caught it until the first real font was selected. The
      editor's Qt-side PREVIEW has the identical trap and the identical fix
      (`addApplicationFontFromData`, see `editor/panels/CLAUDE.md`). Reading
      eagerly also moves a bad file's failure to config time, where the host
      is already validating, instead of the first draw.
  - **`_LAYOUT_H`/`layout_h` are NEVER touched by `configure_fonts`** — the
    pinned cross-platform layout invariant (below) stays authoritative
    regardless of a designer's font-size edits; only DRAWN glyphs move, never
    stored layout rects. `tools/tests/test_theme_data.py`'s
    `TestLayoutHAuthority` proves a `configure_fonts` call that changes every
    size does not move the exporter's `screen_defaults.json` output one bit.

## Ground layer cache (`render/ground_cache.py`, perf) — the panning fix
Windowed culling bounds the ground submit to O(visible), but that is still ~2.6k
tile blits + RenderItem allocs + a full sort EVERY frame under the SCALED software
renderer — the real large-map fps killer while panning. `GroundCache(coords,
assets, *, pixel_margin=192, bg_color=None)` composites the ground layer into an
oversized (viewport + 2·margin) surface baked at an "anchor" pan. Steady-state
(pan unchanged) is ONE blit. **On pan it SCROLLS the surface in place
(`Surface.scroll`, a memmove) and repaints only the newly-exposed edge strip** —
work proportional to pan *speed*, not viewport area or map size. A full rebuild
fires only on first use / zoom / resize / explicit `invalidate()` / a jump clear
off the cached surface.
- **Why scroll, not rebuild-on-margin-escape**: an earlier version rebuilt the
  WHOLE viewport whenever the pan escaped the margin. Each rebuild recomposited
  ~2.6k tiles (== the old per-frame full render, ~70 ms) and, on a large map,
  fired continuously while panning (a small map hits the pan clamp first, so it
  rarely rebuilt — that is why fps used to scale INVERSELY with map area:
  128²→60 fps but 1024²→2 fps). Scroll-and-fill removes the stall.
- **Diagonal-band emission (the subtle part)**: a thin *screen* strip is a
  *diagonal* in tile space, so an axis-aligned tile window
  (`visible_render_items`) for it balloons to almost the whole viewport (and is
  only cut back by map-edge clamping — reintroducing the map-size scaling). The
  strip repaint therefore addresses tiles by the rotated coords `d = col−row`,
  `s = col+row` via `tilemap.band_render_items(doc, d_min, d_max, s_min, s_max)`;
  a thin strip is a thin band in `d` (vertical) or `s` (horizontal) → only the
  ~100 tiles it truly covers. `_paint` derives the band from the strip's pixels:
  `d = (screen_x+pan_x)/(half_w·z)`, `s = (screen_y+pan_y)/(half_h·z)`, padded
  for diamond overhang, and clips the blit to the strip so seams are exact.
- **Why it's safe**: the `depth_key` layer-primary invariant (above) means the
  whole `ground` layer always draws before the dynamic layers. Callers draw the
  cache first, then submit the dynamic layers over it via the normal renderer.
- **Anchor technique**: it renders into the cache through a PRIVATE
  `CoordinateSystem` (a fresh `Camera` at `pan = anchor_pan − margin`, same zoom)
  — never mutating the host camera. Blit offset is
  `dest = anchor_pan − current_pan − margin` (derived from `screen = iso*zoom −
  pan`). Scroll advances `anchor_pan` by the integer pixels scrolled; the
  sub-pixel remainder rides along in the blit's float `dest` — so the surface
  stays rounding-exact vs a direct render (pinned pixel-for-pixel across
  successive scroll steps in `test_ground_cache`).
- **Content-agnostic**: `ensure(view_w, view_h, ground_items_fn)` takes a callback
  `(d_min,d_max,s_min,s_max) → iterable[RenderItem]` (band form) so terrain/tint
  choices stay with the caller (game: untinted; editor: `tint_for_code`).
  `bg_color=<rgb>` bakes an OPAQUE cache (pixel-identical to the old
  `fill(bg)`-then-tiles path) and is REQUIRED by scroll-fill (the exposed strip is
  `fill(bg_color)`ed before repaint); `None`/SRCALPHA is for static
  (non-scrolling) consumers only.
- **NOT exported from `engine.render.__init__`** (which stays pure) — import it by
  full path `engine.render.ground_cache`, like the backend/store.
- **GPU variant (G3, `ground_cache_gpu.py`)**: `GroundCacheGpu` sits behind the
  same `ensure`/`blit`/`invalidate` surface, backed by a pair of render-target
  `Texture`s instead of a `pygame.Surface`. `Surface.scroll`'s memmove becomes a
  self-blit between the two textures, ping-ponged, because SDL cannot read and
  write one render target in a single pass. The strip clip is
  `renderer.set_viewport`, which also translates the strip's origin to `(0, 0)`
  — compensated by shifting the private camera's pan by that same integer
  amount, which `round_half_up`'s `floor(v + 0.5)` makes exact rather than
  approximate. The background fill is `fill_rect`, never `clear()`, because
  `clear()` measures as ignoring the viewport and wiping the whole target. The
  diagonal-band derivation is shared through `ground_cache.band_for_rect`, not
  copied. **The game host selects it (G4)**: `game/main.py` builds
  `GroundCacheGpu(sdl_renderer, cs, assets, bg_color=BACKGROUND)` on the GPU
  path and today's `GroundCache` otherwise, then calls `ensure`/`blit` with no
  branch — `blit`'s `target` argument is ignored on the GPU path by design.
  `default_backend()` still returns the Surface blitter for everyone else.

## Verify
Render/asset-facing changes: headless smoke test (`tools/smoke.py`) and, if
visuals changed, a live `py game/main.py` look. State exactly which you did.
`tools/render_demo.py` renders the grey-X grid offscreen to `build/render_demo.png`
(gitignored) for a quick visual check.
