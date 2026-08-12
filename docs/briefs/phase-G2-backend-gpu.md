# Phase G2 — `backend_gpu.py`: world sprites, overlays, texture cache

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6 "Phase G2"
(lines 397–437), decisions **D6** (dual backend, lines 139–146), **D7** (GPU
scope is world sprites + ground cache; HUD stays on Surface, lines 147–149),
**D8** (fallback is the Surface backend, lines 150–155), environment facts §4
(lines 168–196, including the RESOLVED dummy-driver probe), and the measured
targets in §6/G0 RESULTS (lines 281–370).

G2 is **one new backend module and one new test module**. It writes against the
seam G1 already landed (`engine/render/backend_api.py`). Nothing is wired to a
host in this phase: **no `game/main.py` edit, no HUD composite, no fallback
selection, no ground-cache port.** Those are G3 (`ground_cache_gpu`, plan
lines 439–473) and G4 (host wiring + HUD composite + fallback, plan lines
475–503). A diff touching `game/**`, `engine/render/ground_cache.py`, or
`engine/render/backend.py` has left this phase.

---

## 1. Behavioral spec

Every claim below is **verified** by reading the file at the cited line.

### 1.1 What already exists (do not rebuild it)

**The seam.** `engine/render/backend_api.py` holds a pure `Backend`
`typing.Protocol` — `def __call__(self, target, draw_calls) -> None`
(`backend_api.py:53-68`) — plus `default_backend()`, which lazily imports and
returns `backend.draw` (`backend_api.py:71-80`). The Protocol is deliberately
**not** `@runtime_checkable` and nothing anywhere does `isinstance` against it
(`backend_api.py:60-66`). G2 adds **no** runtime gate either.

**Resolution stays lazy.** `Renderer.flush()` memoises once —
`if self._backend is None: self._backend = backend_api.default_backend()`
(`engine/render/renderer.py:204-205`), called at `:206`. **Do not propose or
make this eager.** Pure callers construct `Renderer` with no `backend=`
(`engine/render/ground_cache.py`, `editor/panels/viewport.py`,
`editor/panels/vfx_preview.py`) and must never pull pygame in at import time;
`engine/render/__init__.py:1-8` documents that purity and imports only
`backend_api`, never `backend`.

**The draw list.** `Renderer.flush()` builds one flat, order-significant,
heterogeneous list (`renderer.py:149-203`) in exactly this order:
1. sprite `DrawCall`s, depth-sorted (`renderer.py:150-173`);
2. overlay entries — `OverlayPolys` / `OverlayLines`, already in screen space
   (`renderer.py:174-184`);
3. the HUD pass — `HudSprite` resolved by the renderer into a `DrawCall`
   carrying `slice=frame.slice` and `crop_rect=hud.crop`
   (`renderer.py:188-201`); `HudRect` / `HudText` / `HudLines` pass through
   untouched (`renderer.py:202-203`). `HudSprite` itself never reaches a
   backend (`backend_api.py:16-18`).

### 1.2 The reference implementation G2 must reach parity with

`engine/render/backend.py` is the pin. Behaviour, per call:

- **Size** — `size = (max(1, _round(call.size[0])), max(1, _round(call.size[1])))`
  (`backend.py:203`), where `_round` is `item.round_half_up`
  (`backend.py:20`, definition `engine/render/item.py:14-22`). A size equal to
  the source size is the identity (`backend.py:41-42`).
- **Dest** — top-left, quantized the same way at blit time:
  `(_round(call.dest[0]), _round(call.dest[1]))` (`backend.py:225`).
- **Scale cache** — a module-level `weakref.WeakKeyDictionary` keyed by SOURCE
  SURFACE identity, holding an inner dict keyed by size / `("9p", …)` /
  `("crop", …)` (`backend.py:37-49`, `:67-71`, `:118-124`). The comment at
  `backend.py:31-36` states the reason the key is weak: the grey-X placeholder
  is a **fresh surface every call**, so a strong key would leak. G2's texture
  cache copies this shape exactly.
- **Flip** — `pygame.transform.flip(surface, True, False)`: **horizontal
  only** (`backend.py:220-221`).
- **Tint** — `surface.copy()` then `fill(call.tint, special_flags=BLEND_RGBA_MULT)`
  (`backend.py:222-224`). The copy is load-bearing: the cached/shared source
  surface is never mutated.
- **`slice`** — nine-slice, **HUD only**; an all-zero slice or a 1:1 draw takes
  the plain scale path (`backend.py:215-219`).
- **`crop_rect`** — source sub-rect, **HUD only**, resolved BEFORE
  scale/nine-slice, clamped rather than raising (`backend.py:100-125`,
  `:210-213`).
- **`OverlayLines`** — `pygame.draw.lines(target, color, closed, points, width)`
  with points quantized by `_round` (`backend.py:188-191`). `width` is an
  arbitrary int (`item.py:57`).
- **`OverlayPolys`** — an **arbitrary-length** filled polygon (`item.py:61-68`;
  `Renderer.submit_overlay_polys` requires only `len(points) >= 3`,
  `renderer.py:115-122`; `engine/render/CLAUDE.md` "Overlay primitives" notes
  ellipses are caller-side polygon approximations, i.e. many points). Opaque
  colours take `pygame.draw.polygon` directly; RGBA with alpha < 255 goes
  through a bounding-box `SRCALPHA` scratch surface (`backend.py:158-171`).
- **HUD primitives** — `HudRect` (`backend.py:145-155`), `HudLines`
  (`backend.py:196-199`), `HudText` via the font cache (`backend.py:132-142`).
- **Order is exact** — sprites batch into one `target.blits(...)`; any
  non-sprite call flushes the batch first (`backend.py:174-187`, `:226-227`).
  A backend that reorders must reproduce output identical to front-to-back
  drawing (`backend_api.py:45-47`).

### 1.3 The measured target this phase is judged against

From §6/G0 RESULTS (**measured** 2026-08-12, plan lines 301–354):
`Renderer.flush` is **84–97% of every frame measured** — **61–81 ms of a
63–84 ms frame** at the era-4 boss load (976 enemies) on
`data/maps/first_light.json`, i.e. **12–16 fps**, the frame-rate complaint that
motivated the plan. Everything else is second-order and measured: the submit
loop **0.05–0.75 ms**, `display.flip` **0.6–1.9 ms**, the ground cache
**0.2–5.0 ms**. `py tools/profile_render.py` is committed and is how these get
re-measured.

**G2 does not move those numbers**, because nothing calls this backend from the
host yet — G4 re-takes the measurements (plan lines 500–503). §4's Quick Test
therefore judges G2 on **pixel parity and per-draw cost characteristics**, not
on fps. State that plainly in the phase report rather than claiming an fps win
this phase cannot have produced.

### 1.4 Environment facts G2 depends on

Headless is **ANSWERED and measured** (plan §4, lines 175–196):
`SDL_VIDEODRIVER=dummy` — the driver the whole suite and `tools/smoke.py`
already run under (`tools/tests/test_render.py:11-12`) — hosts
`pygame._sdl2.video.Window` + `Renderer` + `Texture.from_surface` upload +
`draw()` + `to_surface()` readback correctly; the read-back pixel matched the
uploaded colour exactly. **So `tools/tests/test_render_backend_parity.py` runs
in normal CI and must NOT be marked live-only, skipped, or gated behind an env
var.** `offscreen`/`software` fail at `Window()` in this SDL build and are
irrelevant.

### 1.5 Three places the plan's G2 prose does not match the source — read these before coding

These are contradictions found while writing this brief; the source wins.

1. **There is no `flip_y`.** Plan line 417 says "`flip_x`/`flip_y` are
   native". `DrawCall` carries a single `flip: bool` (`item.py:44`), documented
   and implemented as **horizontal only** (`backend.py:220-221`,
   `backend_api.py:40`). SDL's `Texture.draw` does take both, so pass
   `flip_x=call.flip, flip_y=False`. **Do not add a `flip_y` field to
   `DrawCall`** — that is a contract change, out of scope, and no producer
   sets one.
2. **`Renderer.blit` cannot express flip or per-draw modulation.**
   `pygame._sdl2.video.Renderer.blit(source, dest, area, special_flags)` has no
   flip parameters; `Texture.draw(srcrect, dstrect, angle, origin, flip_x,
   flip_y)` does, and `color`/`alpha` are properties of the **Texture object**.
   So the sprite path goes through `Texture.draw`, not `Renderer.blit`, despite
   plan line 416's wording. Verify the exact signatures against the installed
   pygame-ce 2.5.7 (plan line 170) before coding and state what you found.
3. **`fill_quad` cannot draw an `OverlayPolys`.** SDL2's renderer primitives
   are points / lines / rects / triangles / quads; `OverlayPolys` is an
   arbitrary-length polygon with optional alpha (§1.2). Likewise SDL
   `draw_line` is 1px, while `OverlayLines.width` is an arbitrary int
   (`item.py:57`). See §2.4 — the choice is still yours to make and justify.

---

## 2. Architecture plan

### 2.1 New file — `engine/render/backend_gpu.py`

A module exposing one public callable satisfying the `Backend` Protocol:

```python
def draw(target, draw_calls):
    ...
```

`target` is a **`pygame._sdl2.video.Renderer`** (the contract says `target` is
opaque to `backend_api`, `backend_api.py:5-8`). The module imports pygame at
module level — it is a backend, exactly like `backend.py:15`.

**Module docstring must state**, up front: this is the second and only other
module in `engine/render` allowed to import pygame's SDL2 layer; it draws the
**world path only** (sprites + overlays), per D7; the HUD, nine-slice, crop and
fonts stay single-implementation on `backend.py` and composite over the GPU
frame in G4; and `item.round_half_up` — not SDL's rounding — is the
authoritative quantizer.

### 2.2 Texture cache (the "one upload per source file" deliverable)

Mirror `backend.py:37-49` structurally:

```python
_texture_cache = weakref.WeakKeyDictionary()   # source Surface -> {renderer key: Texture}
```

- **Outer key is the source Surface identity, in a `WeakKeyDictionary`** — so
  each `AssetStore` sheet Surface uploads exactly once, and the grey-X
  placeholder (a fresh surface per call, `backend.py:31-36`) evicts with its
  surface and never leaks. This is non-negotiable; the plan's required GC test
  (§4) asserts precisely it.
- **The inner key must distinguish SDL renderers.** A `Texture` belongs to the
  `Renderer` that created it; keying on the surface alone would hand a texture
  from a destroyed renderer to a live one the moment a second test creates its
  own. Preferred inner key: the SDL `Renderer` object in a nested
  `weakref.WeakKeyDictionary`; if pygame-ce's `Renderer` is not
  weak-referenceable (**verify at implementation time and report which you
  found**), fall back to `id(target)` and say so, noting the bounded id-reuse
  hazard and that `clear_cache()` (below) is what keeps tests honest.
- Expose a module-level **`clear_cache()`**, mirroring how
  `tools/tests/test_render.py:394` and `:420` call
  `backend._scale_cache.clear()` in throughput tests. The parity test calls it
  in `setUp`.

### 2.3 Sprite `DrawCall` → one textured draw

Order of operations, per sprite call:

1. **Reject HUD-only fields loudly.** Immediately at the top of the sprite
   branch, before any texture lookup:

   ```python
   if (call.slice and any(call.slice)) or call.crop_rect:
       raise NotImplementedError(
           "backend_gpu draws the WORLD path only. slice/crop_rect are HUD-only "
           "(engine/render/backend_api.py:34-38); the HUD stays on the Surface "
           "backend and composites over the GPU frame in G4 (plan D7)."
       )
   ```

   `and any(call.slice)` matters: an all-zero slice tuple is truthy but is
   arithmetically a plain scale, and `backend.py:216` already treats it as one.
   This **asserts** the HUD-only invariant instead of implementing nine-slice
   and crop a second time (plan lines 421–422).
2. **Quantize with `round_half_up`, then build an INTEGER dest rect.**

   ```python
   from .item import round_half_up as _round
   w = max(1, _round(call.size[0]))
   h = max(1, _round(call.size[1]))
   dst = pygame.Rect(_round(call.dest[0]), _round(call.dest[1]), w, h)
   ```

   **This is the one place SDL's own rounding must be pre-empted.** pygame-ce's
   `Texture.draw` accepts float rects and routes to SDL's float copy, which
   rounds its own way; handing it an already-integer `pygame.Rect` built from
   `round_half_up` is what keeps this backend pixel-aligned with the ground
   cache and every other consumer of the quantizer (`engine/render/CLAUDE.md`,
   "Pixel quantizer"; `item.py:14-22`). Never pass raw floats through.
3. **Scale lives entirely in the dest rect.** No `pygame.transform.scale`
   anywhere in this module — the texture is uploaded once at source size and
   `dst` carries the scale. That is the win G2 exists for.
4. **Flip is native**: `flip_x=call.flip, flip_y=False` (§1.5 item 1).
5. **Tint → `texture.color` / `texture.alpha`.** `backend.py:222-224` applies
   `BLEND_RGBA_MULT` against `call.tint`, which may be a 3-tuple or a 4-tuple
   (`item.py:32` types it loosely; handle both — RGB sets `color` only, RGBA
   also sets `alpha`).
   **The texture is CACHED and SHARED, so modulation state LEAKS.** This is the
   exact hazard `backend.py:223`'s `surface.copy()` avoids on the Surface path.
   Set `color`/`alpha` before the draw and **reset them to `(255, 255, 255)` /
   `255` immediately after** (or skip setting them at all when `tint is None`
   *and* the previous call left them clean — the simplest correct version is
   set-then-reset unconditionally when a tint is present). A parity test with a
   tinted sprite followed by an untinted one drawn from the same source surface
   is the pin; write it.
6. **Blend mode.** Set the texture's blend mode explicitly to alpha blending
   rather than relying on `from_surface`'s default; name the constant you used
   in the report.
7. **No batching.** Draw in list order. The contract only demands output
   identical to front-to-back (`backend_api.py:45-47`), and per-draw SDL calls
   are the whole point of the port.

### 2.4 `OverlayLines` / `OverlayPolys` — you decide, and you justify

Two admissible implementations (plan lines 418–420):

- **native primitives** — `target.draw_line` / `target.draw_quad` (or
  `fill_triangle` fans), or
- **a CPU-drawn scratch texture** — draw into an `SRCALPHA` `pygame.Surface`
  with the same `pygame.draw` calls `backend.py:158-171`/`:188-191` use, upload
  it, and draw it at its bounding box.

**Decide by the parity test, and state which you chose and why in the phase
report.** The brief deliberately does not pre-decide. Two facts from §1.5 item 3
should inform it: SDL `draw_line` is 1px while `OverlayLines.width` is an
arbitrary int, and `OverlayPolys` is an arbitrary-length polygon with optional
alpha that no quad/triangle primitive covers in general. If you land on
per-primitive mixed strategies (native for the cheap cases, scratch texture for
the rest), say exactly where the boundary is and why.

Overlay points get the same `round_half_up` treatment as `backend.py:189` /
`:159` before they reach any draw call.

### 2.5 HUD primitives reaching this backend

`HudRect` / `HudLines` / `HudText` are out of scope (D7). Since nothing calls
this backend from a host in G2, the loud shape is correct: `isinstance`-detect
them and raise `NotImplementedError` naming G4 and D7, mirroring §2.3 item 1's
message. Pin it with one test. G4 may replace that branch with the composite
path; it must not be a silent drop today.

### 2.6 Docs

- **`engine/CLAUDE.md`** — the pygame-import allow-list, first bullet of
  "## Hard rules (whole package)" at `engine/CLAUDE.md:282-284`. Amend the
  phrase "`render/`'s backend" to name **both** backends explicitly:
  `render/backend.py` **and `render/backend_gpu.py`** (the SDL2/Texture world
  backend). One clause; do not restructure the bullet.
- **`engine/render/CLAUDE.md`** — two small edits: the "**pygame lives here**"
  line at `engine/render/CLAUDE.md:8` gains `backend_gpu.py`; and add a short
  subsection near "## Backend throughput" (`:143`) — three to five sentences —
  saying a second backend exists, that it is the world path only (sprites +
  overlays; HUD/nine-slice/crop/fonts stay on `backend.py` per D7), that its
  texture cache is keyed by source-Surface identity in a `WeakKeyDictionary`
  exactly like `_scale_cache`, that dests/sizes still go through
  `round_half_up`, and that **nothing selects it yet** (G4 wires the host).
  Do not restate the contract — `backend_api.py` holds it.

---

## 3. File scope + shared-file contract

**New**
- `engine/render/backend_gpu.py` — §2.1–§2.5.
- `tools/tests/test_render_backend_parity.py` — §4.

**Modified**
- `engine/CLAUDE.md` — the one allow-list clause at `:282-284`. Nothing else in
  that file.
- `engine/render/CLAUDE.md` — line `:8` plus one new short subsection near
  `:143`. Nothing else.
- `conftest.py` — **`TIERS` entry only**, exactly one line:

  ```python
      "test_render_backend_parity": "core",
  ```

  inserted immediately **after** `"test_render": "core",` at `conftest.py:136`
  and before `"test_right_click_dismiss": "core",` at `:137` (the table is
  alphabetical; `test_render` < `test_render_backend_parity` <
  `test_right_click_dismiss`). Matches how every render module is registered:
  `test_alpha_render` `:72`, `test_ground_cache` `:110`, `test_nine_slice`
  `:122`, `test_render` `:136` — all `"core"`. **Without this entry the module
  silently never runs under a marker-selected gate** and `test_tiers.py` fails
  (`engine/CLAUDE.md`, "Conventions shared across subsystems"). Change nothing
  else in `conftest.py`.

**Untouched — stated hard, because the temptation is real**
- `engine/render/backend_api.py` — **not modified.** Its docstring
  (`:1-49`) already enumerates every field G2 must honour, and the `Backend`
  Protocol already fits a module-level `draw` function. Nothing G2 needs is
  missing. If you believe otherwise, **stop and report** rather than editing
  the contract mid-phase.
- `engine/render/__init__.py` — **not modified.** Exporting `backend_gpu`
  would make `import engine.render` import pygame and break the purity rule
  stated at `__init__.py:1-8` and `renderer.py:4-6`. Import it by full path
  (`engine.render.backend_gpu`), exactly as `ground_cache.py` and `backend.py`
  are imported today (`engine/render/CLAUDE.md`, "Ground layer cache", last
  bullet).
- `engine/render/renderer.py` — untouched. Resolution stays lazy and
  memoise-once (`:204-205`); no eager resolution, no selection logic (G4).
- `engine/render/backend.py` — untouched. It **is** the parity pin; changing it
  to make parity pass inverts the test.
- `engine/render/ground_cache.py` — G3.
- `game/**`, `editor/**`, `data/**`, `tools/smoke.py`, `tools/profile_render.py`
  — none of them. No host wiring, no fallback wiring, no HUD composite.
- `tools/tests/test_render.py` — **run, do not edit.** It is the regression pin
  for the Surface backend. If an existing test there needs a change to pass,
  that is a behavioural regression in your diff, not a test to update — stop
  and report.

**Shared-file contract.** This is a single-phase run against a clean branch, so
there is no sibling phase to reconcile with; the fence above is absolute. The
one file a later phase will also touch is `conftest.py`'s `TIERS` table (M3 adds
`test_master_sheet_import`, plan line 608) — insert your one line at the
alphabetical position given above and touch no other line, so the two edits can
never conflict beyond a trivial adjacent-line merge.

---

## 4. Exit gate + Quick Test

### Required tests — `tools/tests/test_render_backend_parity.py`

Set `SDL_VIDEODRIVER`/`SDL_AUDIODRIVER` to `dummy` at the top exactly as
`tools/tests/test_render.py:11-12` does (`os.environ.setdefault`, before
importing pygame). **The module is a normal CI test — no live-only marker, no
skip, no env gate** (§1.4; plan lines 175–196 retire that risk explicitly).
Build every surface the test uses in-process; **never write into `data/`, and
never assert against live `data/` content** — use tiny generated
`pygame.Surface`s, not manifest slots.

1. **Parity, the core test.** One fixture scene rendered through both backends
   and compared:
   - several sprites at **zoom ≠ 1** (a source surface drawn at a dest size
     that is neither its own size nor an integer multiple — include at least
     one whose `dest`/`size` land on a `.5` tie, so `round_half_up` is actually
     exercised),
   - one **flipped** sprite,
   - one **tinted** sprite, immediately followed by an **untinted** sprite from
     the same source surface (the §2.3 item 5 modulation-leak pin),
   - one `OverlayLines` polyline (width > 1, and a `closed=True` case),
   - one `OverlayPolys` filled polygon — both an opaque one and an
     alpha < 255 one.

   Surface path: `backend.draw(pygame.Surface((W, H)), calls)`. GPU path:
   `pygame._sdl2.video.Window` + `Renderer`, `backend_gpu.draw(renderer, calls)`,
   read back with `renderer.to_surface()`. Clear both to the same background
   colour first.

   Compare **per channel with a pinned tolerance**, with a comment on the
   constant stating why it is not zero: SDL's scaler is not guaranteed
   bit-identical to `pygame.transform.scale`
   (`planning/GpuAndMasterSheetsPLAN.md` lines 805–809). Pin the tolerance as a
   named module constant, not an inline literal, and pin the **fraction of
   pixels allowed to differ at all** too if a pure per-channel bound proves too
   blunt — but never widen either number to make a failure go away without
   saying so in the report.

   > **If the GPU output is visibly blurrier on pixel art at zoom, that is a
   > finding to SURFACE, not to absorb into the tolerance.** Pixel art is the
   > whole aesthetic here and a blurrier GPU path is a regression no fps number
   > redeems (plan lines 805–809). Report it with the numbers and a saved PNG
   > pair; do not quietly raise the tolerance and call the phase done.

2. **Texture cache — one texture per source surface across many draws.** Draw
   the same source surface many times (varying dest/size/flip/tint) and assert
   exactly one `Texture` was created for it — count via a spy on
   `Texture.from_surface` (the shape `test_render.py:400-412` uses to count
   `pygame.transform.scale`) and/or by asserting object identity of the cached
   entry. Call `backend_gpu.clear_cache()` in `setUp`.

3. **A GC'd surface evicts its texture.** Draw a locally-created surface, drop
   the last reference, `gc.collect()`, and assert the cache no longer holds an
   entry for it — the grey-X-placeholder leak argument from `backend.py:31-36`.

4. **HUD-only fields are rejected**, not silently drawn: a `DrawCall` with a
   non-zero `slice`, one with a `crop_rect`, and a bare `HudRect` each raise
   `NotImplementedError` from `backend_gpu.draw` (§2.3 item 1, §2.5).

Bare-minimum coverage — these four, and no exhaustive matrix beyond them.

### Exit gate (the coder's, verbatim)

1. `py tools/smoke.py` — green.
2. `py -m pytest tools/tests/test_render_backend_parity.py tools/tests/test_render.py`
   — green, with `test_render.py` **unedited**.

> That is the whole test budget. **NOT** the full suite, **NOT** a tier sweep
> (`-m core` / `-m editor` / `-m meta`), **NOT** `py tools/testgate.py check`,
> **NOT** `--affected`. The `test_guard.py` hook denies all of those for a
> subagent.

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

### Quick Test — concrete scenario

Nothing in the game runs on this backend yet (G4 wires the host), so the Quick
Test is a **deliberate side-by-side pixel-art look**, run by hand from a
throwaway script in the scratchpad directory (never committed, never in
`data/`):

1. Load one real pixel-art sheet Surface from `data/sprites/imported/` **read
   only** via `AssetStore` (e.g. the slot `tools/render_demo.py` already
   exercises), and pick a frame with hard pixel edges and per-pixel alpha.
2. Build one `DrawCall` list by hand: the frame at **zoom 1.0**, at **2.0**,
   and at **4.0** (dest sizes 1×, 2×, 4× the frame), plus one flipped copy, one
   tinted copy, and one `OverlayPolys` ellipse-approximation with alpha over
   the top — i.e. the visual vocabulary a real frame uses.
3. Render that list twice: `backend.draw` onto a `pygame.Surface`, and
   `backend_gpu.draw` onto a real (non-dummy) `pygame._sdl2.video.Renderer`,
   reading back with `to_surface()`.
4. Save both to `build/` (gitignored) as `quicktest_cpu.png` /
   `quicktest_gpu.png` and **look at them at 1:1 and magnified**.

**Pass condition, stated as something a human can judge:** at every zoom the
GPU image's pixel-art edges are as hard as the CPU image's — no interpolation
fringe along alpha edges, no half-tone row at a scaled block boundary — and the
sprite sits on the same pixel (overlay the two PNGs and confirm the sprite's
bounding box has not shifted by one pixel; the `round_half_up` requirement in
§2.3 item 2 is exactly what a one-pixel shift would mean was skipped). Colours
under the tint match within the pinned tolerance. Report the max per-channel
delta you measured, the tolerance you pinned, and — if the GPU image is softer
at any zoom — say so as a finding with the PNGs attached, per the boxed rule
above.

Also state in the report: which overlay strategy §2.4 landed on and why;
whether pygame-ce's `Renderer` turned out to be weak-referenceable (§2.2); the
exact `Texture.draw` / `Renderer.blit` signatures found on pygame-ce 2.5.7
(§1.5 item 2); and **that G2 moved no fps number**, because no host calls this
backend yet — the §1.3 measurements are G4's to re-take.
