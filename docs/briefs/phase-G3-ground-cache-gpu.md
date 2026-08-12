# Phase G3 — Ground cache on the GPU path

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6 "Phase G3" (lines 534–568),
decisions **D6** (dual backend, lines 139–146), **D7** (GPU scope is world
sprites + ground cache, lines 147–149), **D8** (fallback is the Surface backend,
lines 150–155), environment facts §4 (lines 168–196), the measured targets in
§6/G0 RESULTS (lines 281–370), what G2 actually shipped in §6/G2 RESULTS (lines
439–532), the verify table §8 (lines 843–889) and the risks in §9 — in
particular the **snapshot precondition at lines 925–931**, which is the loudest
line in this brief.

G3 is **one new module, one small pure extraction inside the existing module,
two doc edits and a parameterised test class.** Nothing is wired to a host:
`backend_api.default_backend()` still returns the Surface blitter
(`engine/render/backend_api.py:71-80`), `game/main.py` still constructs the
Surface `GroundCache` (`game/main.py:339`), and **G4 wires the host** (plan lines
570–598). A diff that touches `game/**`, `engine/render/renderer.py`,
`engine/render/backend.py` or `engine/render/backend_gpu.py` has left this phase.

---

## 1. Behavioral spec

Every claim below is **verified** by reading the cited file at the cited line,
or **measured** by the probe transcript quoted in §1.6.

### 1.1 The public surface that must not move

`GroundCache.ensure(view_w, view_h, ground_items_fn)`
(`engine/render/ground_cache.py:66-73`) is the contract. `ground_items_fn` is
`(d_min, d_max, s_min, s_max) -> iterable[RenderItem]` — the **band** form, not a
tile rectangle — and the caller decides terrain/tint (`ground_cache.py:68-72`;
`engine/render/CLAUDE.md`, "Ground layer cache", "Content-agnostic" bullet).
The other two public members are `blit(target)` (`ground_cache.py:96-109`) and
`invalidate()` (`ground_cache.py:62-64`).

**Correction to the plan's prose, verified.** Plan line 546 says the signature
must hold "so both callers (game and editor) are untouched". **The editor does
not use `GroundCache` at all** — a repo-wide grep for `GroundCache` /
`ground_cache` / `band_render_items` under `editor/` returns nothing; the editor
viewport submits its ground tiles directly
(`editor/panels/viewport.py:1816-1818`). The real callers are exactly three:

| Caller | Lines |
|---|---|
| `game/main.py` | `:339` construct, `:432-433` `on_zone_change = ground_cache.invalidate`, `:1503-1508` `ensure(...)` then `blit(window)` |
| `tools/profile_render.py` | `:194` construct, `:263-264` `ensure` + `blit` |
| `tools/tests/test_ground_cache.py` | `:81-84`, `:133-134`, `:152-153`, `:169-170`, `:198-236` |

The signature still must not move — but the reason is the test suite and the
host, not an editor consumer. Do not "fix" the editor to use it.

### 1.2 What `ensure` must do, step by step

Verbatim from `ground_cache.py:66-94`, and the GPU variant must reproduce this
decision tree exactly:

1. Read `cam.pan_x/pan_y/zoom` off the **host's live** `CoordinateSystem`
   (`:74-76`). The host camera is never mutated (`:50-53`).
2. **Full rebuild** when the surface does not exist yet, the view size changed,
   the zoom changed, or `_generation != _seen_generation` (`:78-82`). That is
   first use / resize / zoom / `invalidate()`.
3. Otherwise compute the integer scroll delta
   `sx = -_round(pan.x - anchor.x)`, `sy = -_round(pan.y - anchor.y)`
   (`:86-87`) with `_round = item.round_half_up` (`ground_cache.py:33`,
   definition `engine/render/item.py:14-22`).
4. `sx == 0 and sy == 0` → **return, do nothing** (`:88-89`). This is the
   steady-state fast path and the "no-op does nothing" pin
   (`test_ground_cache.py:214-215`).
5. `abs(sx) >= cw or abs(sy) >= ch` → the camera jumped clear off the cached
   region → **full rebuild** (`:90-92`).
6. Otherwise **scroll and repaint the exposed L** (`:94`, `:168-186`).

### 1.3 The anchor + sub-pixel remainder rule — preserve it exactly

This is what makes the cache rounding-exact against a direct render, and it is
pinned pixel-for-pixel across successive scroll steps
(`test_ground_cache.py:125-162`). Three inseparable parts:

- **A private `CoordinateSystem` + `Renderer`**, never the host's
  (`ground_cache.py:50-53`). `_anchor_cache_camera(zoom)` points it at
  `pan = anchor_pan - margin` on both axes and copies the host zoom by direct
  field assignment (`:113-120`), deliberately skipping `set_zoom`'s
  re-validation.
- **Scroll advances the anchor by the INTEGER scrolled**:
  `anchor_pan = (anchor.x - sx, anchor.y - sy)` (`:174`). The sub-pixel
  remainder is never stored and never lost — it rides in the blit's float dest.
- **The blit dest is `anchor_pan - current_pan - margin`**, quantized once at
  blit time (`:96-109`, derived from `screen = iso*zoom - pan` in the docstring
  at `:99-102`). Its sign is pinned by `test_ground_cache.py:166-186`.

**Do not re-derive, re-centre, or "simplify" any of this.** Copy the three
expressions across unchanged; only what the pixels live in changes.

### 1.4 The diagonal-band derivation — reuse it VERBATIM

`_paint(rect, ground_items_fn)` (`ground_cache.py:122-153`) is the subtle,
already-correct part, and restating it from scratch is how this phase regresses.
A thin *screen* strip is a *diagonal* in tile space, so an axis-aligned tile
window balloons to nearly the whole viewport (and re-introduces map-size
scaling); the strip is therefore addressed by the rotated coordinates
`d = col - row`, `s = col + row` through
`engine.tilemap.band_render_items` on the caller's side
(`engine/render/CLAUDE.md`, "Diagonal-band emission"; `engine/CLAUDE.md`'s
`band_render_items` bullet). The derivation from the rect's pixels is
`ground_cache.py:137-145`, verbatim:

```python
z  = cam.zoom
hw = self._coords.geometry.tile_w / 2 * z
hh = self._coords.geometry.tile_h / 2 * z
x0, y0, w, h = rect
d_min = math.floor((x0 + cam.pan_x) / hw) - 1
d_max = math.ceil((x0 + w + cam.pan_x) / hw) + 1
s_min = math.floor((y0 + cam.pan_y) / hh) - 2
s_max = math.ceil((y0 + h + cam.pan_y) / hh)
```

The `-1/+1` and `-2/+0` pads are the diamond-overhang correction documented at
`:133-136` (a diamond spans ±1 in `d` and `[s, s+2]` down-screen). **Every
constant here is load-bearing.** §2.2 tells you how to share this expression
rather than copy it.

`_paint` then does three things in order (`:146-153`): clip to the rect, fill the
clipped region with the background, submit the band items into the private
`Renderer` and `flush` into the cache surface. **The clip is what makes seams
exact** — a diamond straddling a scrolled boundary has its exposed half painted
here and its scrolled half already in place (`:126-129`).

### 1.5 The scroll/repaint contract

`_scroll` (`ground_cache.py:168-186`): move the content by `(sx, sy)`, advance
the anchor, re-anchor the private camera, then repaint **an L of up to two
strips** — `(0, 0, sx, ch)` or `(cw+sx, 0, -sx, ch)` for the horizontal move and
`(0, 0, cw, sy)` or `(0, ch+sy, cw, -sy)` for the vertical. Their overlap corner
is painted twice and that is explicitly harmless (`:176-178`). Reproduce the
same four rects with the same signs; the sign convention (`scroll(sx, sy)` moves
content by `+(sx, sy)`, so the vacated edge is on the **opposite** side) is the
easiest thing in this phase to get backwards, and
`test_ground_cache.py:137-138`'s mixed-sign deltas are what will catch you.

`bg_color` is **required** for the scroll path: the exposed strip is filled with
it before repaint (`ground_cache.py:41-49`; `engine/render/CLAUDE.md`,
"Content-agnostic" bullet). The `None`/SRCALPHA mode is for static
(non-scrolling) consumers only, and there are none on the GPU path — see §2.4.

### 1.6 SDL mechanics — measured on the installed pygame-ce, not guessed

Probed on this machine under `SDL_VIDEODRIVER=dummy`, pygame-ce **2.5.7 /
SDL 2.32.10** (plan §4 line 170). **Measured**, all six:

1. **A render-target texture is
   `Texture(renderer, size, target=True, scale_quality=SCALEQUALITY_NEAREST)`.**
   The constructor docstring reads: "`:param bool target:` Initialize the texture
   as target (can be used as a rendering target)" and "One of `static`,
   `streaming`, or `target` can be set to `True`". `scale_quality` is a separate,
   independent parameter — `0` is nearest-pixel sampling, which
   `SCALEQUALITY_NEAREST` names.
2. **Selecting it is `renderer.target = tex`, and `renderer.target = None`
   restores the window.** (`Renderer.target` docstring: "A value of `None` means
   that no custom rendering target was set and the Renderer's window will be
   used as the target.")
3. **Readback is `renderer.to_surface()` on the CURRENT target.**
   `Texture` has **no** `to_surface` — `Texture.to_surface` raises
   `AttributeError`. The attribute set is
   `alpha, blend_mode, color, draw, draw_quad, draw_triangle, from_surface,
   get_rect, height, renderer, update, width`.
4. **`renderer.set_viewport(rect)` both CLIPS and TRANSLATES.** With
   `set_viewport(Rect(10, 10, 20, 20))`: `fill_rect(Rect(0, 0, 5, 5))` landed at
   target pixel `(12, 12)` (and `(2, 2)` stayed background), and
   `fill_rect(Rect(15, 15, 30, 30))` was clipped — `(29, 29)` painted,
   `(33, 33)` untouched. This is the GPU stand-in for `Surface.set_clip`, and
   **the translation is not optional to handle** (§2.5).
5. **`renderer.clear()` IGNORES the viewport and wipes the WHOLE target.**
   Measured: target filled red, viewport set to `(10, 10, 20, 20)`, `clear()`
   with blue — pixel `(0, 0)` came back blue. **The strip background fill must
   be `fill_rect`, never `clear()`.** A `clear()` here silently erases the
   entire cache every scroll and the pins in §4 will fail confusingly.
6. **The viewport RESETS when the target changes** (after `renderer.target =
   None` it read back as the full window rect). Set the viewport **after**
   assigning the target, never before, and never assume it survives a swap.
7. **The two-target self-blit works**: with `renderer.target = b`,
   `a.draw(dstrect=pygame.Rect(-7, 3, 64, 64))` reproduced `a`'s pixel `(12,12)`
   at `b`'s `(5, 15)` — negative dest origins included.
8. **A `target=True` texture's `blend_mode` is `0` (`BLENDMODE_NONE`)** on
   construction — the same trap G2 hit with the empty-texture constructor
   (plan lines 486–491). For the ground cache that default is *correct* for the
   self-blit (a straight copy, no blending) and correct for an opaque cache
   drawn onto the frame; state it explicitly in code rather than inheriting it
   silently.

### 1.7 The measured target — state it honestly, claim nothing more

From §6/G0 RESULTS (**measured** 2026-08-12, plan lines 301–354):

| Bucket | Measured |
|---|---|
| `Renderer.flush` (the sprite blits) | **84–97% of every frame**, 61–81 ms of a 63–84 ms frame at the era-4 boss load |
| **`GroundCache.ensure` + `blit`** | **0.2–5.0 ms mean, p95 up to 10.64 ms** |

The ground cache is **0.2 ms static** on every map/zoom and only reaches
5.02 / 10.64 ms in **one corner**: the 1024² map, panning, at max zoom (plan
line 314). The plan's own verdict calls it "real but second-order" and says G3
is "correctly ordered *after* [G2] and correctly scoped as a **smaller win**"
(plan lines 345–350).

**So G3's target is: up to ~1–5 ms per frame recovered while panning a large
map at high zoom, and effectively nothing when the camera is still.** Do not
write "G3 improves frame rate" without that qualifier, and do not attribute any
fps change to it — nothing selects the GPU path yet, so like G2 this phase
**cannot** move an fps number, and G4 re-takes the measurements (plan lines
595–598).

**The stronger reason G3 exists is correctness, not speed.** Once G4 draws the
world onto an SDL `Renderer`, there is no `pygame.Surface` frame buffer left to
`Surface.blit` the cache onto. Without G3, G4 has no legal way to draw the
ground layer at all. Say that in the report; it is the honest framing.

### 1.8 `WorldFill` (PR #122) changes nothing for the ground layer — stated so you don't wonder

**Verified.** `WorldFill` (`engine/render/item.py:71-98`) is submitted through
`Renderer.submit_world_fill` into the same depth-sorted `_queue` as
`RenderItem` and is lowered to `OverlayPolys`/`OverlayLines` `DrawCall`s inside
the sorted loop (`renderer.py:107-121`, `:167-182`). Two facts make it a no-op
here:

1. **No shipped caller submits one on the `ground` layer.** Both call sites use
   the `layer="entities"` default — `game/ui/widgets.py:294` and `:306` (the one
   choke point every tile highlight goes through) — and `game/map/wall_render.py`
   emits on `entities` too. A repo-wide grep for `layer="ground"` finds only
   `engine/tilemap.py:286`, `:328`, `:384`, i.e. the three tile emitters.
2. **The ground cache can only ever see what its callback yields.** Its private
   `Renderer` (`ground_cache.py:53`) receives exactly
   `ground_items_fn(...)` output (`:150-151`), which is
   `tilemap.band_render_items` — plain `RenderItem`s, never a `WorldFill`.

Even if a ground-layer `WorldFill` appeared later, it would lower to
`OverlayPolys`/`OverlayLines` `DrawCall`s that `backend_gpu` already draws
(`backend_gpu.py:175-180`), so the path would still work. **Nothing to do.**

---

## 2. Architecture plan

### 2.1 THE LOUDEST LINE — never hand a mutated Surface to `backend_gpu`

`backend_gpu`'s texture cache **snapshots a source Surface at first upload and
never refreshes it** (`engine/render/backend_gpu.py:29-35`, `:66`, `:75-84`),
where `backend.py` returns the live surface at 1:1. Plan §9 (lines 925–931)
names this as a precondition **G3 must not violate**, and calls out the ground
cache by name because it composites into a surface it reuses forever.

**Concretely forbidden:** keeping the existing oversized `pygame.Surface`,
painting into it as today, and then drawing it via a `DrawCall` through
`backend_gpu`. That renders *correctly on the CPU backend* and **silently
freezes at first-frame contents on the GPU one, with no error, no exception and
no log line** — the worst failure mode in this plan. It will look like the map
"sticks" while entities keep moving.

**Therefore G3 paints into a render-target `Texture` and draws that texture
directly.** No cache Surface exists on this path at all: no `Texture.update()`
from a per-frame cache Surface, no `renderer.to_surface()` round-trip per frame,
no `DrawCall` carrying a mutated surface. If you find yourself writing
`Texture.update(self._surface)` inside `ensure`, stop — that is this bug wearing
a different hat (it would work, being an explicit re-upload, but it throws away
the entire point of the port: a full-cache RAM→VRAM upload every frame).

### 2.2 Module vs variant — decision criteria, and the recommendation

**Recommendation: a NEW module, `engine/render/ground_cache_gpu.py`, plus one
small pure extraction inside `ground_cache.py`.** The criteria, so the decision
is auditable rather than taste:

| Criterion | New module | Variant class inside `ground_cache.py` |
|---|---|---|
| **Import cost on the Surface path** | `ground_cache.py` keeps importing only `pygame` | a module-level `from pygame._sdl2.video import Texture` makes **every** importer of the Surface cache — the game host, `tools/profile_render.py`, the test module — depend on the SDL2 layer loading. **Decisive.** |
| **Symmetry with the shape reviewers already know** | mirrors `backend.py` / `backend_gpu.py` exactly (plan §2's diagram, lines 67–68, literally names `GroundCacheGpu`) | no precedent in this package |
| **G4's fallback (D8)** | two importable names, G4 picks one | one module that must be importable even when SDL2 is not usable |
| **Duplication of the band derivation** | **the one real cost** — mitigated by §2.3 | zero |
| `engine/CLAUDE.md` allow-list | one new name either way | unchanged |

The variant-class option's only advantage is avoiding duplication, and §2.3
removes that advantage. If you disagree after reading the code, you may still
choose the variant — but then you must state in the report how you kept
`pygame._sdl2.video` out of the Surface path's import graph, because that is the
constraint, not the file layout.

### 2.3 Share the band derivation — do not copy it

Extract `ground_cache.py:137-145` into a **module-level pure function in
`ground_cache.py`** and call it from both implementations:

```python
def band_for_rect(rect, pan_x, pan_y, half_w, half_h):
    """(d_min, d_max, s_min, s_max) for cache-surface pixel `rect` ... """
```

`_paint` then becomes a call to it. This is the `fit_factor` /
`block_center_offset` precedent verbatim (`engine/render/CLAUDE.md`, "THE one
expression ... a second copy would drift the moment the rule changes"), and it
is the mechanical form of the plan's "reuse the derivation verbatim" (line 551).
The extraction is **behaviour-preserving by construction** and the existing pins
(`test_ground_cache.py:92-162`) prove it — that is the whole reason it is safe to
touch `ground_cache.py` in this phase at all. **Move the expression; do not
retune a single constant while moving it.** Keep the docstring's derivation
prose with the function.

### 2.4 `GroundCacheGpu` — shape

```python
class GroundCacheGpu:
    def __init__(self, sdl_renderer, coords, assets, *, pixel_margin=192,
                 bg_color):
        ...
    def invalidate(self): ...
    def ensure(self, view_w, view_h, ground_items_fn): ...   # signature FROZEN
    def blit(self, target): ...
```

- **`ensure` / `blit` / `invalidate` keep their exact names and arity.** Only
  construction differs — it necessarily takes the SDL `Renderer`, since a
  `Texture` belongs to the renderer that created it (`backend_gpu.py:56-59`).
  Say so in the report: the *per-frame* surface is identical, the constructor is
  not, and **G4 owns the construction-site choice** (D8).
- **`bg_color` is REQUIRED here** (keyword-only, no default): the scroll-fill
  path is the only consumer and it needs an opaque fill (§1.5). Raise
  `ValueError` on `None` rather than inheriting the Surface class's SRCALPHA
  branch, which exists for static consumers that this class does not have.
- Keep `_generation` / `_seen_generation` / `_view_size` / `_anchor_pan` /
  `_anchor_zoom` and the private `CoordinateSystem` + `Renderer` **identical in
  name and meaning** to `ground_cache.py:50-60`, so the shared test mixin (§4)
  can spy on `_rebuild` / `_scroll` for both classes.
- The private `Renderer` is constructed with the GPU backend injected:
  `Renderer(self._cache_cs, assets, backend=backend_gpu.draw)`.
  `Renderer.__init__` already takes `backend=` (`renderer.py:88-91`) and
  `flush()` only falls back to `default_backend()` when it is `None`
  (`renderer.py:236-238`) — **so `renderer.py` needs no change.** Import
  `backend_gpu` by full path; do not add it to `engine/render/__init__.py`
  (that would make `import engine.render` pull in pygame).

**Module docstring must state, explicitly, not by implication:**

- **The `depth_key` layer-primary invariant is what makes caching the ground
  layer legal at all** — `depth_key = (layer_index, wx+wy, wy)` makes the draw
  layer the primary sort key, so the whole `ground` layer always draws before
  `entities`/`deco`/`overlay` (`engine/render/CLAUDE.md:28-31`, marked
  LOAD-BEARING; `ground_cache.py:4-9` says it for the Surface class). Plan line
  556 requires this sentence; do not leave it implied.
- §2.1's precondition, in one sentence: this class paints into a render-target
  `Texture` and never hands a mutated Surface to `backend_gpu`.
- That `item.round_half_up`, not SDL's rounding, is the quantizer here too
  (`backend_gpu.py:14-19`).

### 2.5 The two-target self-blit, and how the repaint strip is derived

**Scroll (`_scroll`).** SDL cannot read and write one render target in a single
pass, so keep **two** identically sized target textures and ping-pong:

1. `renderer.target = self._back`
2. `self._front.draw(dstrect=pygame.Rect(sx, sy, cw, ch))` — measured to work
   with negative origins (§1.6 item 7). This is the exact analogue of
   `Surface.scroll(sx, sy)`: content moves by `+(sx, sy)`.
3. swap `self._front, self._back`.
4. advance `anchor_pan` by the integer scrolled and re-anchor the private camera
   — **unchanged from `ground_cache.py:174-175`**.
5. repaint the same L of up to two strips, same four rects, same signs
   (`ground_cache.py:179-186`).

The region *outside* the vacated L is fully overwritten by step 2, and the L
itself is fully repainted in step 5, so nothing stale from two frames ago can
survive on the newly-front texture. Say that in a comment; it is the one thing a
reviewer will ask about the ping-pong.

**Repaint (`_paint`).** The strip rect is derived **exactly as today** (§1.4,
via the shared `band_for_rect`). What changes is only how the rect is honoured:

1. `renderer.target = self._front` — **then** `renderer.set_viewport(rect)`
   (order matters, §1.6 item 6).
2. **Compensate the viewport's translation** (§1.6 item 4). The viewport makes
   the strip's top-left the new origin, so the private camera's pan must move by
   `+(x0, y0)` for the duration of the paint:
   `cam.pan_x = anchor_pan.x - margin + x0`, `cam.pan_y = anchor_pan.y - margin
   + y0`. **This is rounding-exact and that is provable, not hoped for:**
   `x0`/`y0` are integers, and `round_half_up(v) = floor(v + 0.5)` satisfies
   `floor(v + k + 0.5) == floor(v + 0.5) + k` for integer `k` — so every dest
   lands on exactly the pixel it would have landed on with no viewport. Put that
   one-line proof in the code comment; it is the whole reason the anchor
   technique survives the port. Note the band derivation must use the **same**
   compensated pan it always used (i.e. feed `band_for_rect` the uncompensated
   `pan` with the original rect, or the compensated pan with a rect at the
   origin — pick one and be consistent; the two are algebraically identical).
3. `renderer.draw_color = bg_color` then
   `renderer.fill_rect(pygame.Rect(0, 0, w, h))` — **`fill_rect`, NOT
   `clear()`** (§1.6 item 5, measured: `clear()` wipes the whole target).
4. Submit the band items into the private `Renderer` and `flush(sdl_renderer)`.
   `flush`'s `target` argument is passed straight through to the backend
   (`renderer.py:238`), and `backend_gpu.draw` expects the SDL `Renderer`
   (`backend_gpu.py:166-171`).
5. `renderer.set_viewport(None)`, `renderer.target = None`.

**Steps 1 and 5 must be symmetric even on an exception** — wrap in
`try/finally`, exactly as `backend_gpu.py:206-215` brackets its tint modulation
for the same class of reason (leaked global state on a shared object). A leaked
`target` or viewport corrupts the host's entire next frame with no error.

**Alternative if the viewport translation proves troublesome**: paint the strip
into a scratch target texture of strip size (origin `(0,0)`, no viewport needed)
and `draw` it at `(x0, y0)`. It costs an allocation (or a cached pair of scratch
targets) per strip and an extra copy. **Recommended only as a fallback** — the
viewport route is one call, has no allocation, and is measured to clip and
translate correctly.

### 2.6 `blit(target)` — reaching the frame

Identical arithmetic to `ground_cache.py:104-109`:

```python
dx = self._anchor_pan[0] - cam.pan_x - m
dy = self._anchor_pan[1] - cam.pan_y - m
self._front.draw(dstrect=pygame.Rect(_round(dx), _round(dy), cw, ch))
```

with `renderer.target` at `None` (the window). **The dest goes through
`round_half_up` and reaches SDL as an already-integer `Rect`**, never a float —
same rule and same reason as `backend_gpu.py:193-196`. The size is the cache
size, so there is no resampling on this draw at all. Set the cache textures'
`blend_mode` explicitly (the constructor leaves it at `BLENDMODE_NONE`, §1.6
item 8): `BLENDMODE_NONE` is correct here — the cache is opaque and covers the
viewport, and blending an opaque full-cover quad is wasted work. Whichever you
choose, assign it explicitly and say why in a comment; G2 was bitten by
inheriting this value (plan lines 486–491).

### 2.7 Error / fallback behaviour

**G3 does not implement fallback selection — G4 does (D8, plan lines 580–583).**
What G3 owes G4 is a clean, detectable failure:

- Create the target texture pair **in the constructor** (or on first `_rebuild`)
  and let `pygame.error` propagate, or wrap it in one clearly named exception
  documented in the class docstring. Some SDL renderers do not support render
  targets; that is exactly the machine D8's fallback exists for.
- **Do not** catch it inside `ensure` and silently degrade to a Surface cache.
  A silent degrade inside the per-frame path is unobservable and would hide the
  one condition G4 needs to branch on.
- **Do not** add a log line, an env var, or a `default_ground_cache()` selector.
  That is G4's file scope.

### 2.8 Docs

- **`engine/CLAUDE.md`** — the pygame-import allow-list, first bullet of
  "## Hard rules (whole package)". It currently names
  `render/ground_cache.py`; add `render/ground_cache_gpu.py` in the same clause.
  One clause; do not restructure the bullet.
- **`engine/render/CLAUDE.md`** — two edits, both small:
  - the "**pygame lives here**" list at `:8-10` gains `ground_cache_gpu.py`;
  - append a short subsection (four to seven sentences) at the end of
    "## Ground layer cache" (`:359-405`): a GPU variant exists behind the same
    `ensure`/`blit`/`invalidate` surface; the `Surface.scroll` memmove is a
    self-blit between two render-target textures because SDL cannot read and
    write one target in a pass; the strip clip is `set_viewport`, which also
    translates, compensated by an integer pan shift that `round_half_up` makes
    exact; the background fill is `fill_rect` because `clear()` ignores the
    viewport; the band derivation is shared through `band_for_rect`, not copied;
    and **nothing selects it yet** — G4 wires the host.
  Do not restate the anchor derivation there; the module docstring owns it.

---

## 3. File scope + shared-file contract

**New**
- `engine/render/ground_cache_gpu.py` — §2.4–§2.7.

**Modified — and nothing else in these files**
- `engine/render/ground_cache.py` — **one change only**: extract
  `:137-145` into the module-level `band_for_rect(...)` (§2.3) and call it from
  `_paint`. No behavioural change, no constant retuned, no new import, no
  `pygame._sdl2` anywhere in this file. If your diff to this file is larger than
  that, stop and report.
- `engine/CLAUDE.md` — the one allow-list clause (§2.8).
- `engine/render/CLAUDE.md` — line `:8-10` plus one appended subsection in the
  existing "Ground layer cache" section (§2.8).
- `tools/tests/test_ground_cache.py` — §4. **Parameterise the existing pins over
  both implementations; do not copy-paste them** (plan lines 563–565).

**Untouched — stated hard, because the temptation is real**
- `engine/render/backend_gpu.py` — **not modified.** It already draws sprites
  and overlays and already exports `clear_cache()` (`:69-72`). If you believe it
  is missing something G3 needs, **stop and report** rather than editing a
  merged, parity-pinned backend mid-phase.
- `engine/render/backend.py`, `engine/render/backend_api.py`,
  `engine/render/renderer.py`, `engine/render/__init__.py`,
  `engine/render/item.py` — untouched. `Renderer.__init__` already accepts
  `backend=` (`renderer.py:88-91`); backend resolution stays lazy
  (`renderer.py:236-238`); `default_backend()` keeps returning the Surface
  blitter (`backend_api.py:71-80`).
- `game/**` — untouched. **No host wiring in G3** (plan lines 570–598).
  `game/main.py:339`, `:432-433` and `:1503-1508` stay exactly as they are.
- `tools/profile_render.py`, `tools/smoke.py`, `editor/**`, `data/**` — none of
  them.
- `conftest.py` — **no change needed.** `"test_ground_cache": "core"` already
  exists at `conftest.py:110`, and the recommendation is to keep both
  implementations' tests in that module. **If you add a new test module instead,
  it needs a `TIERS` line or it silently never runs** and `test_tiers.py` fails
  (`engine/CLAUDE.md`, "Conventions shared across subsystems") — the table is
  alphabetical, so `"test_ground_cache_gpu": "core",` goes immediately after
  `:110` and before `"test_hp_bar_anchors"` at `:111`. Touch no other line in
  that file; the only other pending edit to it in this plan is M3's own `TIERS`
  line (plan line 703), so a one-line insertion can never conflict beyond a
  trivial adjacent-line merge.

**Shared-file contract.** This is a single-phase run on `phase-G3-umbrella`, so
no sibling phase is in flight. The two files a later phase will also touch are
`engine/render/CLAUDE.md` and `engine/CLAUDE.md` (G4 edits both, plan lines
575–577) — append your subsection at the **end** of the existing "Ground layer
cache" section and add one clause to the allow-list bullet, so G4's edits land
in different regions.

---

## 4. Exit gate + Quick Test

### Required tests — `tools/tests/test_ground_cache.py`

The module already sets `SDL_VIDEODRIVER=dummy` / `SDL_AUDIODRIVER=dummy` before
importing pygame (`:12-13`) and builds from `FIXTURE_DATA` (`:18`, `:27`) — keep
both. **Never write into `data/` and never assert against live `data/`
content.** The dummy driver hosts `Window`/`Renderer`/`Texture` upload / draw /
`to_surface()` readback (plan §4 lines 175–196, **measured**; re-confirmed by
this brief's own probe), so **these tests are normal CI tests — no live-only
marker, no skip, no env gate.**

**Parameterise, don't duplicate.** Move the pinned bodies into a mixin (the
existing `GroundCacheCase` helpers `_coords`, `_ground_fn`, `_direct` at
`:55-76` are already implementation-agnostic), then have two `TestCase`
subclasses supply (a) how to build the cache and (b) how to produce the
comparison surface:

- **CPU subclass** — today's `_cached` (`:78-84`) verbatim: blit onto a
  `pygame.Surface` pre-filled with `BG`.
- **GPU subclass** — build a hidden `Window` + `Renderer` sized `VIEW_W×VIEW_H`
  in `setUpClass`, `clear()` to `BG`, `ensure` + `blit`, then read back with
  `renderer.to_surface()`. Call `backend_gpu.clear_cache()` in `setUp`
  (`backend_gpu.py:69-72`).

The pins that must run for **both** (all already written — reuse them):

1. `test_pixel_equal_zoom1` (`:92-98`), `test_pixel_equal_zoom2` (`:100-106`),
   `test_pixel_equal_with_tint` (`:108-114`), `test_pixel_equal_at_map_edge`
   (`:116-123`).
2. **`test_pixel_equal_after_scroll` (`:125-146`) and
   `test_pixel_equal_after_scroll_zoom2` (`:148-162`) — the load-bearing
   rounding-exactness pins.** Successive small pans, mixed signs, both axes,
   magnitudes inside the margin so every step scrolls; each step compared
   against a from-scratch **direct** render. This is what catches a seam gap, a
   flipped scroll sign, a lost sub-pixel remainder, and a `clear()`-instead-of-
   `fill_rect`. Keep the same delta lists.
3. `test_blit_offset_sign` (`:166-186`) — the GPU version captures the
   `dstrect` handed to `Texture.draw` (spy/monkeypatch) instead of a fake
   `blit`; assert the same `anchor - pan - margin` value.
4. `test_rebuild_vs_scroll_triggers` (`:190-236`) — unchanged logic, spying on
   `_rebuild`/`_scroll`. This is why §2.4 asks you to keep those two method
   names.

**Comparison tolerance for the GPU subclass.** The CPU pins use exact byte
equality (`:88-90`). Try **exact equality first**: G2 measured a scaled
`8×8 → 21×21` GPU draw as **byte-identical** to `pygame.transform.scale`, and
its overall parity delta of 1 was confined to alpha-blended `OverlayPolys`
(plan lines 493–509) — which the ground layer has none of. If exact equality
does not hold, pin a **named module constant** with a comment recording the
measured max per-channel delta, the differing-pixel count and the histogram, and
**report it as a finding** — do not widen a tolerance quietly to make a phase
pass. A blurrier or shifted ground layer is a regression no fps number redeems
(plan lines 900–904).

**Two GPU-mechanics tests, and no more** (bare-minimum-but-real):

5. **State is restored.** After `ensure(...)` and after `blit(...)`,
   `renderer.target is None` and `renderer.get_viewport()` is the full target
   rect. A leaked target or viewport silently corrupts the host's next frame
   (§2.5), and nothing else in the suite would catch it.
6. **The self-blit does not read and write one target.** Assert the class holds
   two distinct `Texture` objects and that the pair **swaps identity** across a
   scrolling `ensure` (capture `id()` before and after). Cheap, and it pins the
   ping-pong the plan requires (line 548).

Do not add an exhaustive matrix beyond these.

### Exit gate (the coder's, verbatim)

1. `py tools/smoke.py` — green.
2. `py -m pytest tools/tests/test_ground_cache.py` — green, **both** subclasses
   running (print/confirm the collected count went up; a silently-skipped GPU
   class is indistinguishable from a passing one — `engine/CLAUDE.md`: an
   unexpected skip is a failure).

> That is the whole test budget. **NOT** the full suite, **NOT** a tier sweep
> (`-m core` / `-m editor` / `-m meta`), **NOT** `py tools/testgate.py check`,
> **NOT** `--affected`. The `test_guard.py` hook denies all of those for a
> subagent (plan §8, lines 845–867).

> If `test_guard` denies a command, do NOT re-issue it and do not vary the flags
> (it normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints
> identically). Report the deny text and stop testing. A denied run is a report,
> never a retry.

### Quick Test — concrete, in-game where it can be

**Part A — the Surface path must be untouched (a headless coder CAN do this).**
`engine/render/ground_cache.py` was edited (§2.3). `py tools/smoke.py` plus the
CPU half of the pins is the mechanical proof; state it as **measured**.

**Part B — the live look (a human at a display; NOT performable by a headless
agent).** Plan line 566 asks for "a live look at panning a large map in
`py game/main.py` with no seams or stutter". Be precise about what that can and
cannot show **today**:

- `py game/main.py` still runs the **Surface** ground cache (`game/main.py:339`;
  `default_backend()` unchanged). So a live run right now verifies **no
  regression from the `band_for_rect` extraction** — real and worth doing, but
  it does **not** exercise `ground_cache_gpu.py` at all.
- Exercising the GPU cache live needs either G4's host wiring or a throwaway
  harness at a real (non-dummy) display: a real `Window` + `Renderer`, the
  committed 1024² map (`holex`, the map G0 profiled — plan line 311), a
  `GroundCacheGpu` fed `tilemap.band_render_items`, and a serpentine pan at
  maximum zoom, which is the exact corner where G0 measured 5.02 / 10.64 ms
  (plan line 314).

**Pass condition a human can judge:** while panning continuously at max zoom on
the 1024² map, the ground shows **no seam line** trailing the pan direction, no
one-pixel-jittering tile grid as the pan crosses `.5` boundaries, no flash of
background colour along the leading edge, and no periodic hitch. Then stop the
camera: the ground must be **byte-stable** (not slowly drifting) and the frame
cost must fall back to the steady-state single draw.

**Flag it plainly in the phase report, exactly as G2 did (plan lines 527–532):
the live look was NOT run, it needs a human at a display, and it carries forward
as an outstanding item into G4's live gate.** Every number a headless agent can
produce for this phase comes from the dummy driver in one environment.

### Also state in the report

- Which structure §2.2 landed on (new module vs variant) and — if the variant —
  how `pygame._sdl2.video` was kept out of the Surface path's import graph.
- The exact SDL spellings you used for the render target
  (`Texture(..., target=True)`, `renderer.target = …`) as found on the installed
  pygame-ce 2.5.7, and whether they matched §1.6.
- Whether the strip clip used `set_viewport` + the integer pan compensation or
  the scratch-target fallback, and why.
- The comparison tolerance the GPU pins ended up needing (ideally exact
  equality) with the measured numbers behind it.
- That **G3 moved no fps number and could not have** — nothing selects this path
  yet; §1.7's measurements are G4's to re-take. Quote G3's honest target
  (0.2–5.0 ms mean, p95 10.64 ms, and only in the panning corner) rather than
  implying a frame-rate win.
