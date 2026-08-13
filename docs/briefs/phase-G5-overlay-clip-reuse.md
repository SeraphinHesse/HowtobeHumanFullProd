# Phase G5 — Overlay pass: clip the scratch, reuse the buffer

**Plan**: `planning/GpuAndMasterSheetsPLAN.md` §6 phase G5 (lines 845-898);
risk register §9 (lines 1244-1253). **Base branch**:
`MasterSpritesheet_Implementation` (not `Development` — `engine/render/
backend_gpu.py` does not exist there). **Package doc**: `engine/render/CLAUDE.md`.

---

## 1. Behavioral spec (what is wrong, with citations)

### The current code

`engine/render/backend_gpu.py:110-156` holds the whole overlay path — two
near-identical functions, `_draw_lines` (110-133) and `_draw_polys` (136-156).
Both do exactly this, per call, per frame:

1. Quantize the points with `round_half_up` (`backend_gpu.py:122`, `:146`).
2. Compute a bounding box from the RAW points, with **no reference to the
   target at all** (`backend_gpu.py:126-128`, `:149-151`).
3. `pygame.Surface((w, h), pygame.SRCALPHA)` — a fresh allocation
   (`backend_gpu.py:129`, `:152`).
4. Rasterize into it with the same `pygame.draw.lines` / `pygame.draw.polygon`
   the Surface backend uses (`backend_gpu.py:130-131`, `:153-154`) — that
   shared rasterizer is the parity argument and it stays.
5. `_upload(target, scratch).draw(dstrect=...)` — a brand-new `Texture`,
   uploaded and then dropped. The comment on `backend_gpu.py:132` and `:155`
   says it outright: *"Not cached: the scratch pixels are unique to this one
   overlay call."*

So every overlay call is: allocate → rasterize → create texture → upload →
draw → destroy. Nothing is reused and nothing is bounded by the screen.

### The pin it must stay identical to

The Surface backend does none of this. `backend.py:188-191` draws `OverlayLines`
**straight onto the target** with `pygame.draw.lines(target, ...)`, so pygame's
own clip does the bounding for free; `backend.py:158-171` (`_draw_polys`) takes
the direct `pygame.draw.polygon(target, ...)` path whenever the colour is
opaque and only builds a bbox scratch for the alpha < 255 case — and even then
blits it onto the target, where the blit clips. **That free clip is precisely
what G5 has to reproduce on the GPU side.**

### The measured cost (§6/G4 RESULTS, "Overlay Δ — measured in isolation",
plan lines 767-788) — **measured**, by G4, not by this brief

first_light 20², 160 sprites, zoom 1.0, static, 300 frames:

| overlays | surface Δ ms/frame | gpu Δ ms/frame | ratio |
|---|---|---|---|
| 40 diamonds (80 overlay calls/frame) | 0.72 | **4.31** | **6.0× worse on GPU** |
| 200 diamonds | 9.30 | **17.50** | **1.9× worse on GPU** |

Each diamond is one `OverlayPolys` + one `OverlayLines`, so 40 diamonds means
**80 uncached bounding-box SRCALPHA scratch surfaces created, rasterized and
uploaded per frame**.

The pathological case (plan lines 782-788): ONE `submit_overlay_lines` whose
second point is 50 tiles off-screen. Screen bbox **1603 × 803 px = 4.9 MB
SRCALPHA**, allocated + rasterized + uploaded **fresh every frame**. Δ per
frame: **surface 6.47 ms, gpu 10.66 ms** — 1.65× worse plus 4.9 MB of per-frame
churn. The renderer converts world→screen without clipping, so any world-space
line with an off-screen endpoint produces this.

### Why this is live gameplay cost, not a synthetic benchmark

Since PR #122, every tile highlight and every wall segment is submitted as a
`WorldFill`, which `flush()` turns into `OverlayPolys` / `OverlayLines`
DrawCalls — `engine/render/CLAUDE.md` §"Depth-sorted world fills" names the
consumers explicitly: `game/ui/widgets.py`'s `submit_tile_diamond` /
`submit_tile_diamond_fill` (click/drag-select, condition tint, RANGE, HEATMAP,
TIER OVERVIEW, the tutorial highlight) and `game/map/wall_render.py`'s wall-art
emitter. Splatters, glows and the drummer-aura ring go through the same
primitives. On the GPU path today, each of those is one alloc-and-destroy per
frame.

### What "done" looks like behaviorally

Pixel output is **unchanged**, on-screen, for every overlay — the GPU path just
stops doing work whose result was going to be discarded by the target's edges
anyway. The phase succeeds when the GPU column above is no longer a *multiple*
of the surface column; it does **not** need to beat the Surface path (plan
line 898).

---

## 2. Architecture plan

Two changes, both required, both inside `engine/render/backend_gpu.py`.

### 2a. Clip the scratch rect to the target BEFORE allocating (the bigger win)

Compute the raw bbox exactly as today, then intersect it with the target's
bounds, and allocate/rasterize/upload **only the intersection**.

- **Target bounds**: `target.get_viewport()` on a `pygame._sdl2.video.Renderer`
  returns the current viewport as a `pygame.Rect`. **Measured** on this repo's
  pygame-ce 2.5.7 / SDL 2.32.10 under `SDL_VIDEODRIVER=dummy`: for a
  `Window(size=(200, 160))`, `Renderer(window).get_viewport()` returns
  `Rect(0, 0, 200, 160)`. Prefer it over `logical_size` — the same probe
  measured `renderer.logical_size == (0, 0)` on an unconfigured renderer, so
  logical size is not a usable bound. `Rect.clip` is the intersection.
- The rasterization still uses the **same** `pygame.draw.lines` /
  `pygame.draw.polygon` calls on an `SRCALPHA` scratch — that is the parity
  argument recorded in `backend_gpu.py:114-120` and `:137-144` and it must not
  change. Only the scratch's *origin and size* change.
- `pad = max(1, int(call.width))` on the lines path (`backend_gpu.py:123`)
  already widens the bbox for stroke width; keep it, and clip **after**
  padding, so a stroke that reaches on-screen from an off-screen centre line
  is still drawn.

**TRAP 1 — translate the points by the CLIPPED origin, not the raw bbox
origin.** Today the translation is `(x - min_x, y - min_y)` with `min_x/min_y`
from the raw bbox (`backend_gpu.py:131`, `:154`). After clipping, the scratch's
origin is the *clipped* rect's `x`/`y`, and the point translation and the
`dstrect` must both use that clipped origin. Mixing the two — clipping the
size but translating by the raw origin, or vice versa — produces a shifted
overlay. The plan calls this out by name (line 873): *"that translation is
where this regresses into a one-pixel shift, so pin it."* Every on-screen pixel
must land where `backend.py` puts it.

**TRAP 2 — an overlay wholly outside the target must be a NO-OP.** Return
early, before any allocation. Do **not** create a zero-sized scratch and do not
create a zero-area texture: `pygame.Surface((0, 0))` constructs happily
(**measured**: `pygame.Surface((0, 0), pygame.SRCALPHA).get_size() == (0, 0)`,
no exception), which means the Surface half of the trap fails *silently* and
survives to the texture step — where `Texture(renderer, (0, 0))` and even
`Texture(renderer, (4, 0))` raise **`ValueError: size must contain two positive
values`** (**measured**, same probe). Two separate traps, one crash: guard on
the clipped rect being empty (`if clipped.w <= 0 or clipped.h <= 0: return`)
and never let a zero dimension reach either constructor.

### 2b. Reuse ONE scratch Surface per backend, grown to a high-water mark

Replace the per-call `pygame.Surface(...)` + `_upload(...)` create-and-destroy
with a reused buffer:

- **One CPU-side scratch Surface**, module-level, mirroring the module's own
  existing cache precedent (`_texture_cache`, `backend_gpu.py:49-84`, itself
  modelled on `backend.py`'s `_scale_cache`). It grows to the high-water mark
  and is **never shrunk**: if the needed clipped size fits inside the current
  buffer, reuse it; only allocate when a dimension exceeds it (grow to at least
  the max of old and new on each axis).
- **Clear per use, don't reallocate**: `scratch.fill((0, 0, 0, 0), rect)` over
  just the sub-rect about to be drawn — a full-buffer `fill` would grow the
  per-call cost with the high-water mark instead of the current overlay.
- **Draw only the used sub-rect**: `Texture.draw(srcrect=..., dstrect=...)` —
  the `srcrect` parameter is supported (**measured**: `Texture.draw`'s
  docstring documents `srcrect`/`dstrect` on pygame-ce 2.5.7). Without a
  `srcrect`, a small overlay drawn from a large reused buffer would stretch the
  whole buffer over the destination. This is the most likely way 2b breaks 2a's
  parity, so it is worth its own assertion in the tests.
- **One streaming Texture per renderer, updated in place.** The scratch's
  pixels change every call, so it can **not** go through `_texture()`
  (`backend_gpu.py:75-84`) — that cache is a *snapshot at first draw and never
  refreshed*, the precondition the module docstring pins at
  `backend_gpu.py:29-35`. Keep a separate overlay texture keyed by `id(target)`
  (the same inner-key rationale as `_texture_cache`: pygame-ce's `Renderer` is
  not weak-referenceable, `backend_gpu.py:56-64`), created once per size step
  with `streaming=True`, and refresh it with `texture.update(surface, area)`
  each call. **Measured**: `Texture(renderer, size, streaming=True,
  scale_quality=SCALEQUALITY_NEAREST)` constructs, and `texture.update(surface,
  pygame.Rect(0, 0, 16, 16))` succeeds on it. Set `blend_mode =
  pygame.BLENDMODE_BLEND` explicitly, exactly as `_upload` does
  (`backend_gpu.py:106`) and for the same reason recorded in its docstring —
  the constructor leaves it at `BLENDMODE_NONE`, and alpha `OverlayPolys` need
  blending. **Inferred, and the coder should confirm by running the tests
  rather than by reasoning**: `update()`'s docstring notes it is optimized for
  static textures and that streaming textures prefer the locking functions;
  if a streaming texture measurably misbehaves under `update()` on this
  driver, a static texture refreshed with `update()` is an acceptable
  fallback — the deliverable is "one texture, updated in place", not a
  particular SDL access flag.
- **`clear_cache()` (`backend_gpu.py:69-72`) must drop the overlay buffer and
  its textures too.** It is what keeps tests honest across renderers, and the
  parity suite calls it in both `setUp` and `tearDown`
  (`tools/tests/test_render_backend_parity.py:63`, `:69`). A reused buffer that
  survives `clear_cache()` would leak a strong `Renderer` reference and make
  the allocation-counting tests order-dependent.

### 2c. Parity is not negotiable — `CHANNEL_TOLERANCE = 1` is PINNED

`tools/tests/test_render_backend_parity.py:43` sets `CHANNEL_TOLERANCE = 1`,
and the comment above it (lines 30-42) records exactly what was measured to
justify that 1: max delta 1 on 1234/32000 pixels, **all** of them inside the
alpha < 255 `OverlayPolys`, i.e. one-ULP alpha-blend rounding; scaled, flipped
and tinted sprites came back byte-identical. Plan §9 (lines 879-881, and §5
lines 508-511) forbids nudging it, and the test comment says the same in the
imperative: *"If this ever needs raising, that is a pixel-art regression to
report with the numbers, not a knob to turn."*

**In this phase's terms: a clip that moves ANY on-screen pixel is a DEFECT to
fix, never a tolerance to widen.** If a new clipped-overlay case fails at
tolerance 1, the bug is in the clipped-origin translation (Trap 1) or the
`srcrect` (2b) — fix that. Do not touch `CHANNEL_TOLERANCE`, do not add a
per-test looser tolerance, and do not weaken an existing assertion. If you
believe the tolerance is genuinely wrong, stop and report it upward with the
numbers instead of changing it.

### Not in this phase

- No change to *when* overlays draw, to their order, or to the
  `OverlayLines`/`OverlayPolys` dataclasses.
- No new opaque/alpha branch on the GPU side. `backend.py` branches on alpha
  (`_has_alpha`, `backend.py:160`) because it can draw opaque polys straight
  onto the target; the GPU path has no equivalent and the scratch stays the one
  strategy for both cases (`backend_gpu.py:140-144`).
- No `SDL_HINT` / scale-quality changes, no batching, no sprite-path changes.

---

## 3. File scope — HARD boundary, exactly three files

**You may create/modify exactly these:**

| File | What changes |
|---|---|
| `engine/render/backend_gpu.py` | `_draw_lines` / `_draw_polys` clip + the shared reused scratch buffer & streaming texture; `clear_cache()` extended to drop them |
| `tools/tests/test_render_backend_parity.py` | the new cases in §4 (append; existing cases stay green **unchanged** at tolerance 1) |
| `engine/render/CLAUDE.md` | update the "Second backend: `render/backend_gpu.py` (G2)" section (lines ~209-228) to state the overlay clip + reused buffer |

**Explicitly OUT of scope — do not open, do not edit:** `engine/render/
backend.py`, `backend_api.py`, `renderer.py`, `item.py`, `hud.py`,
`ground_cache.py`, `ground_cache_gpu.py`, `tools/profile_render.py`,
`tools/tests/test_render.py` (run it, don't edit it), `game/**`, `editor/**`,
`data/**`, and `planning/GpuAndMasterSheetsPLAN.md`.

`backend.py` is the **pin** — the thing G5's output is compared against. Editing
it to make a comparison pass inverts the whole test. If you find yourself
wanting to, stop and report.

**Shared-file contract: none.** G5 is the only phase in this wave and, per plan
§9 line 1251-1253, **no phase outside G5 may touch `backend_gpu.py`** while G5
is scoped. There is no concurrent editor of any of the three files, so there
are no insertion points to reconcile with anyone.

---

## 4. Exit gate + Quick Test

### Tests you must add (bare minimum — do not broaden)

All in `tools/tests/test_render_backend_parity.py`, all compared against
`backend.py` at the existing `CHANNEL_TOLERANCE = 1`. The module already gives
you `GpuBackendCase` with `render_cpu` / `render_gpu` (lines 60-85) and a
per-channel comparison you can lift from `test_scene_matches_surface_backend`
(lines 124-136) — reuse them, don't rewrite them.

1. **Clipped-overlay parity, one case per edge + a corner.** Overlays (a mix of
   `OverlayLines` and `OverlayPolys`, including one alpha < 255 poly) that
   extend past the **left**, **right**, **top**, **bottom** edge of the
   `200 × 160` target, plus one that overhangs a **corner** — each compared
   CPU vs GPU at tolerance 1. These are the Trap-1 detectors.
2. **Wholly off-screen draws nothing.** An overlay entirely outside the target
   (e.g. a far-off-screen polyline like the plan's pathological case) must not
   raise and must leave the rendered frame **identical to the same frame
   without that call**. Both halves matter: no `ValueError` from a zero-area
   texture, and no stray pixel.
3. **N overlay draws allocate ONE scratch Surface, not N.** Spy on the
   allocation the way `TestTextureCache.test_one_upload_per_source_surface`
   (lines 152-175) counts uploads — it monkeypatches `backend_gpu.Texture`
   with a counting shim inside `try/finally` and asserts the count. Do the
   same for whatever the new code calls to allocate the scratch, and assert
   `1` for a list of many overlay calls.
4. **The buffer GROWS and is not re-allocated when a smaller overlay follows a
   larger one.** Draw a large overlay, then a small one, and assert the
   allocation count did not increase (and, if you expose the buffer, that its
   size is still the high-water mark).

Keep it to these four. Do not add broader overlay coverage, property tests, or
parametrized sweeps — the existing suite plus these is the agreed scope.

### The gate — EXACTLY this, and nothing wider

```
py tools/smoke.py
py -m pytest tools/tests/test_render_backend_parity.py tools/tests/test_render.py -q
```

**Both must be green — the gate is ZERO failures.** The pre-existing parity
cases must pass **unchanged**, at tolerance 1, with no assertion relaxed.

**Do not run anything wider.** No `py tools/testgate.py check`, no
`--affected`, no tier sweep (`-m core` / `-m editor` / `-m meta`), no full
suite. You are a subagent; the `.claude/hooks/test_guard.py` `PreToolUse` hook
**denies** all four from a subagent, so attempting one produces a denied
command and a stall, not a result. The single full `check` is the main
session's step at handoff. Authority: §"Test Suite Policy" in the root
`CLAUDE.md`.

### Explicitly NOT the coder's job

The plan's G5 bullet (lines 893-898) also asks for a **re-measure of the
overlay Δ table through `tools/profile_render.py`** (40 diamonds, 200 diamonds,
the far-off-screen polyline) written into the plan doc beside the originals.
**That re-measure and that write-up belong to the ORCHESTRATOR, not to you.**
Do not run `tools/profile_render.py`, do not edit
`planning/GpuAndMasterSheetsPLAN.md`, and do not edit root `PLAN.md` (a
generated mirror). Report your changes upward and let the orchestrator measure
and publish.

### Report

State, with the `/report` taxonomy: which gate commands you ran and their one
result line (**measured**), what you changed in `backend_gpu.py` and why
(**verified**, with `file:line`), and anything you could not confirm by running
it (**inferred**) — in particular the streaming-vs-static texture choice from
§2b if the tests did not discriminate.

### Quick Test (for the PR body — the orchestrator or the user runs this, not you)

1. `py game/main.py --backend=gpu`, load `first_light`, and start a round.
2. **Hover and drag-select tiles** so the highlight diamonds draw, and place a
   **wall** so `game/map/wall_render.py`'s segments draw. Toggle **RANGE** and
   **HEATMAP** on a placed musician so the range rings and heat diamonds draw
   too.
3. **Pan the camera so highlighted tiles and wall segments run off each edge of
   the window, and off a corner.** The clipped edges must look exactly as they
   do today — no shifted outline, no missing sliver at the screen edge, no
   flicker as a diamond crosses the boundary.
4. Repeat the identical steps with `py game/main.py --backend=surface`. The two
   runs must be visually indistinguishable; the GPU frame-timing line's `world`
   figure should be lower than before with many highlights on screen.
5. Nothing crashes when a highlight or wall is scrolled fully off-screen (the
   Trap-2 no-op).
