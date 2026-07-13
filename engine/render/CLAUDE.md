# CLAUDE.md — engine/render

RenderItem submit → resolve frames via assets → depth sort → coords → blit
(E-20..E-25). You reached here from `engine/CLAUDE.md`. **Target-agnostic:** the
game window and the editor viewport use the SAME pipeline. When you change render
conventions, update THIS doc.

**pygame lives here** (`backend.py`, `fonts.py`, `ground_cache.py`) — `renderer.py`
itself is pure orchestration. See the engine router's pygame-import allow-list.

## Render flow
- `Renderer(coords, assets, backend=None)` — `renderer.py` produces `DrawCall`s;
  the pygame backend (`render/backend.py`) is lazily imported on first `flush()`
  and injectable for tests.
- Draw layers fixed: `LAYERS = ("ground", "entities", "deco", "overlay")` (E-26);
  HUD is drawn by the host after flush.
- **`depth_key = (layer_index, wx+wy, wy)`** makes the draw LAYER the primary sort
  key, so the whole `ground` layer always draws before `entities`/`deco`/
  `overlay`. This is a **LOAD-BEARING invariant** — if `depth_key` ever
  interleaves layers, the ground cache breaks.

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

## HUD pass + fonts (Phase 9B)
- **`render/hud.py`** (E-12) — four frozen, pure, screen-space dataclasses:
  `HudRect`, `HudText`, `HudSprite`, `HudLines`. The host calls
  `Renderer.submit_hud(item)`; at `flush`, AFTER sprites and overlay lines, HUD
  items fold into the same flat draw list **in screen space (no coords
  conversion, no depth sort)** — `HudSprite` resolves to a `DrawCall` via
  `assets.frame(slot_key)`, the other three pass through for the pygame backend to
  `isinstance`-dispatch (mirrors `OverlayLines`). `_hud` clears each flush.
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

## Verify
Render/asset-facing changes: headless smoke test (`tools/smoke.py`) and, if
visuals changed, a live `py game/main.py` look. State exactly which you did.
`tools/render_demo.py` renders the grey-X grid offscreen to `build/render_demo.png`
(gitignored) for a quick visual check.
