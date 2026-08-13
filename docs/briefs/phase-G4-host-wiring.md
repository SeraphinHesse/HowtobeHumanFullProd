# Phase G4 — Host wiring, HUD composite, fallback, re-measure

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6 "Phase G4" (lines 659–687),
decisions **D6** (dual backend, lines 139–146), **D7** (GPU scope = world sprites
+ ground cache; HUD stays on Surface, lines 147–149), **D8** (fallback is the
Surface backend, logged, never a hard failure, lines 150–155), §2's architecture
diagram (lines 58–91), §4's environment facts (lines 168–196), the measured
targets in §6/G0 RESULTS (lines 281–370), what G2 shipped (§6/G2 RESULTS, lines
439–532), what G3 shipped (§6/G3 RESULTS, lines 574–657), §8's role-scoped verify
table (lines 932–979) and **§9's risks — in particular the snapshot precondition
(lines 1013–1020), the overlay-pass measurement requirement (lines 997–1012), the
`slice`-on-a-1:1-draw divergence (lines 1021–1027) and the THREE never-run live
checks (lines 1028–1035)**.

G4 is the phase where all of Part A becomes reachable. G2 and G3 both shipped
green and both ended their reports with the same sentence: *nothing selects this
path*. `backend_api.default_backend()` still returns the Surface blitter
(`engine/render/backend_api.py:71-80`) and `game/main.py:339` still constructs the
Surface `GroundCache`. **Every visual claim about this port is therefore still
unverified by a human eye**, and closing that is this phase's headline
deliverable — not its epilogue. §4 is written for the user to run, in ten
minutes, at a display.

---

## 1. Behavioral spec

Every claim below is **verified** by reading the cited file at the cited line, or
**measured** by the probe transcripts quoted in §1.7 (pygame-ce 2.5.7 / SDL
2.32.10, Python 3.13.2, this machine, `SDL_VIDEODRIVER=dummy`).

### 1.1 What the host does today, exactly

`game/main.py` renders every frame into ONE `pygame.Surface` — the display
surface returned by `pygame.display.set_mode((view_w, view_h), pygame.SCALED)`
(`game/main.py:139-146`), held in the local `window` (`:381`, reassigned on a
display-mode change at `:572`). In frame order:

| Step | Line | What it does with `window` |
|---|---|---|
| clear | `:1455` | `window.fill(BACKGROUND)` |
| cutscene frame (shell CUTSCENE) | `:1458-1460` | `window.blit(surf, (0, 0))` — a fresh Surface per video frame |
| ground | `:1503-1508` | `ground_cache.ensure(...)` then `ground_cache.blit(window)` |
| world + HUD | `:1704` | ONE `renderer.flush(window)` — sprites, overlays **and the whole HUD pass** in a single flat list |
| in-gameplay cutscene overlay | `:1710-1717` | `window.blit(surf, (0, 0))` then a SECOND `renderer.flush(window)` |
| menu states | `:1725` | `renderer.flush(window)` |
| present | `:1727` | `pygame.display.flip()` (the SCALED upscale) |

There are **four** `renderer.flush(window)` call sites (`:1468`, `:1704`,
`:1717`, `:1725`) and **three** direct `window.blit`/`window.fill` sites
(`:1455`, `:1460`, `:1710`). All seven are frame-target touch points G4 must
route through one seam.

Timing already exists and is the thing G4 extends: `perf = {"sim", "submit",
"flush", "flip"}` (`:976`), accumulated at `:1730-1733`, printed once a second
beside the fps line when `tune_gc` is true (`:1739-1744`; `tune_gc = max_frames
is None`, `:398` — i.e. windowed runs only). `game/PERF.md:154-157` documents it
as the "Frame-timing HUD". **G0 used exactly this split and its one *inferred*
claim is that the HUD is not the dominant cost** (plan lines 366–370): the HUD's
draw is inside the `flush` bucket and nothing has ever separated it.

`data/display.json` is `640 × 360`, `display_mode: "fullscreen"` (**verified** —
that file, in full). So the logical surface is 640×360 upscaled by SCALED to the
monitor, and **the default mode is fullscreen**: any GPU path that does not
reproduce SCALED's coordinate remapping will put every click in the wrong place
(§2.6).

### 1.2 The two engine pieces waiting to be selected

- **`engine/render/backend_gpu.py`** — `draw(target, draw_calls)` where `target`
  is an SDL `Renderer` (`:166-215`). Sprites and overlays only. It **raises
  `NotImplementedError`** on `HudRect`/`HudLines`/`HudText` (`:181-183`), on a
  non-zero `DrawCall.slice` (`:187-188`) and on `DrawCall.crop_rect`
  (`:189-191`).
- **`engine/render/ground_cache_gpu.py`** — `GroundCacheGpu(sdl_renderer,
  coords, assets, *, pixel_margin=192, bg_color)` (`:55-56`), with `ensure` /
  `blit` / `invalidate` identical in name and arity to the Surface class. **Its
  `blit(target)` ignores `target`** and always draws through the SDL `Renderer`
  it was constructed with — stated in its own docstring (`ground_cache_gpu.py:
  114-127`). So `ground_cache.blit(<whatever>)` is correct on both paths and the
  host needs no branch at that call site (`game/main.py:1508`).

### 1.3 The HUD must NOT be ported, and must NOT be a cached-surface upload

D7 (plan lines 147–149) and §2 (lines 86–91) are binding and are **not** open for
re-litigation in this phase: `HudRect`/`HudText`/`HudSprite`/`HudLines`, the font
cache, the nine-slice compositor and the crop path all stay on the Surface
backend and composite over the GPU frame as **one upload per frame**. Do not port
them, do not add HUD branches to `backend_gpu.py`.

**THE LOUDEST LINE IN THIS BRIEF — the single most likely way G4 ships a silent
bug.** `backend_gpu`'s texture cache **snapshots a source Surface at first upload
and never refreshes it** (`engine/render/backend_gpu.py:29-35`, `:66`, `:75-84`;
plan §9 lines 1013–1020). A screen-sized HUD surface is **mutated every single
frame**. Therefore:

> **The HUD composite must NEVER be a `DrawCall` handed to `backend_gpu`, and
> must never rely on `backend_gpu`'s texture cache.** It must be an explicitly
> updated texture the host owns and calls `update()` on every frame (§2.4).

If you get this wrong there is **no exception, no log line and no test failure**
— the HUD simply freezes at its first frame while the world keeps moving. Love
counters stop counting, the building panel shows the first tile you ever opened.
A reviewer looking at a screenshot cannot tell. Pin it with the test in §4.

### 1.4 The `slice` trap, and how G4 guarantees it cannot fire

`DrawCall.slice` is set in exactly ONE place in the whole renderer: the HUD loop
(`engine/render/renderer.py:220-233`, `slice=frame.slice` at `:231`,
`crop_rect=hud.crop` at `:232`). The world-sprite loop (`renderer.py:194-205`)
sets neither. `backend.py` treats a non-zero slice on a 1:1-sized draw as a legal
plain scale; `backend_gpu` raises (plan §9 lines 1021–1027).

**The guarantee G4 must provide is structural, not defensive**: the world/HUD
split happens at the point of *production* inside `flush` — the HUD list is
exactly the calls the `self._hud` loop emitted (§2.3). No `isinstance` filter, no
"skip calls that look HUD-ish" heuristic over a merged list. State this in the
code comment; a later reader who moves the split to a post-hoc filter reopens the
crash.

### 1.5 Fallback (D8) — what "degrades cleanly" means concretely

Any failure creating the SDL `Window`, the `Renderer`, the HUD texture or the
ground-cache textures **logs one line and falls back to the Surface path**, which
is byte-for-byte today's code. It is never a hard failure and never a partial
GPU/Surface hybrid: a fallback rebuilds the whole frame target on the Surface
path, because a half-migrated host has no defined draw order.

**The fallback must be reachable by a test that forces it** (plan line 683) —
monkeypatch the renderer construction to raise. A fallback only a broken machine
can reach is untested code on the path a player without acceleration depends on.

### 1.6 The measured target — state it honestly

From §6/G0 RESULTS (**measured** 2026-08-12, plan lines 301–354):

| Bucket | Measured |
|---|---|
| **`Renderer.flush`** (the backend's blits) | **84–97% of every frame** — 61–81 ms of a 63–84 ms frame at the era-4 boss load, i.e. **12–16 fps** |
| `submit` (depth sort + `DrawCall` build) | 0.05–0.75 ms |
| `flip` (SCALED upscale) | 0.6–1.9 ms |
| `ground` (`GroundCache.ensure` + `blit`) | 0.2–5.0 ms mean, p95 10.64 ms, only in the 1024²-panning-at-max-zoom corner |

**That 61–81 ms is what G4 is trying to move, and it is the only number that
matters.** Do not report a win from the 160-sprite rows (already 86–126 fps) or
from the ground bucket. The boss-load rows (`first_light 20²`, 1016 sprites) are
the phase's scoreboard.

### 1.7 SDL / pygame-ce mechanics — MEASURED on the installed build, not assumed

Probed on this machine, pygame-ce **2.5.7 / SDL 2.32.10**, under
`SDL_VIDEODRIVER=dummy`. All eight are **measured**, with the transcript line
quoted:

1. **You cannot attach an SDL `Renderer` to the display-module window.**
   After `pygame.display.set_mode((320,240), pygame.SCALED)` (and equally
   without `SCALED`), `Window.from_display_module()` succeeds but
   `Renderer(window)` fails: `error: Surface already associated with window`.
   **The GPU path therefore does NOT use `pygame.display.set_mode` at all.**
2. **`Renderer.from_window(window)` SUCCEEDS on that same window — and is a
   trap.** It returns SCALED's own internal renderer. Anything you draw into it
   is then overwritten (or interleaved) by `pygame.display.flip()`'s own
   full-screen copy of the display surface. It looks like the easy path and it is
   not one. Do not use it; say so in a comment so the next reader does not
   "simplify" into it.
3. **A standalone window works end to end**: `Window(title, (w, h))` →
   `Renderer(window)` → `renderer.logical_size = (view_w, view_h)` →
   `draw_color` / `clear()` / `present()` all OK; `renderer.get_viewport()` reads
   back `Rect(0, 0, 320, 240)`.
4. **`pygame.display.flip()` raises `error: Display mode not set`** once the host
   is on a standalone window, and `pygame.display.get_surface()` is `None`.
   `pygame.display.get_init()` is still `True`. So the present step becomes
   `renderer.present()`, and `game/main.py:1727` must branch.
5. **Streaming texture — the HUD composite's mechanism.** The `Texture`
   constructor's own docstring reads: "`:param bool streaming:` Initialize the
   texture as streaming (changes frequently, lockable)" and "One of `static`,
   `streaming`, or `target` can be set to `True`. If all are `False`, then
   `static` is used." `scale_quality` is an independent parameter.
   `Texture(renderer, size, streaming=True, scale_quality=SCALEQUALITY_NEAREST)`
   constructs OK; `texture.update(surface)` and `texture.update(surface, area)`
   both work; the readback after a `draw()` returned the uploaded colour.
   **`blend_mode` after the constructor is `0` (`BLENDMODE_NONE`) — measured** —
   the same trap G2 hit (plan lines 486–491). Set
   `texture.blend_mode = pygame.BLENDMODE_BLEND` explicitly or the HUD draws
   with alpha ignored and paints an opaque black screen over the world.
6. **Cost of the composite, at the real 640×360 logical size** (300 iterations,
   dummy/software renderer — a real GPU driver will differ, which is why §4
   requires it re-measured on hardware):

   | Step | ms/frame |
   |---|---|
   | `Surface((640,360), SRCALPHA).fill((0,0,0,0))` | **0.024** |
   | streaming `update()` + `draw()` | **0.262** |
   | static (default) `update()` + `draw()` | **0.259** |
   | `renderer.to_surface()` readback (the capture path) | **0.75** (one-off) |

   At 1280×720 under the same software renderer, streaming measured 4.04 ms and
   static 1.01 ms — i.e. **under the software renderer the streaming hint is not
   a win, and at the real 640×360 the two are indistinguishable.** Take
   `streaming=True` as the default (it is what the type exists for on a real
   accelerated driver) but **measure both on hardware in §4's re-measure and pin
   whichever wins, with the number in a comment.** Do not assert a win you did
   not measure.
7. **Mouse remapping is available and is exact**: `renderer.logical_size` +
   `renderer.coordinates_from_window(point)` ("Translates window coordinates to
   renderer coordinates"). Measured with a 640×480 window at logical 320×240:
   `coordinates_from_window((320,240)) -> (160.0, 120.0)`, and
   `coordinates_to_window((160,120)) -> (320.0, 240.0)`. Returns **floats**.
8. **A `pygame.event.Event` can be rebuilt with a replaced `pos`**:
   `pygame.event.Event(e.type, e.__dict__ | {"pos": (5, 10)})` preserves
   `button`, `touch` and every other field (measured). This is the one-line seam
   §2.6 uses instead of touching fifteen `event.pos` call sites.

**One more, and it is load-bearing**: the `Renderer` constructor takes
`target_texture` ("Whether the renderer should support setting `Texture` objects
as target textures" — its docstring). **`GroundCacheGpu` is built entirely on
render-target textures** (`ground_cache_gpu.py:140-150`, `Texture(..., target=
True)`). Under the dummy/software renderer targets happen to work without the
flag, which is why G3's suite is green without it — **on a real D3D/OpenGL driver
they may not.** Construct the host renderer as `Renderer(window,
target_texture=True)` and treat a failure as a fallback trigger (§2.5). This is
the most likely "green in CI, broken on the user's machine" defect in the phase.

---

## 2. Architecture plan

### 2.1 Shape: one host-side "presenter" seam, two implementations

All seven frame-target touch points (§1.1) route through ONE object built in
`game/main.py`. Two implementations, chosen once at boot:

```
                       ┌ SurfacePresenter ─ display.set_mode(SCALED) → Surface
_make_presenter(...) ──┤                    flush(window)  ·  display.flip()
                       └ GpuPresenter ───── _sdl2 Window + Renderer(target_texture=True)
                                            flush(sdl_renderer, hud_target=hud_surface)
                                            hud streaming Texture · renderer.present()
```

**Interface (name it in the report; these five plus two properties are enough):**

| Member | Surface impl | GPU impl |
|---|---|---|
| `begin_frame()` | `window.fill(BACKGROUND)` | `renderer.draw_color = BACKGROUND; renderer.clear()`; `hud_surface.fill((0,0,0,0))` |
| `world_target` | the `window` Surface | the SDL `Renderer` |
| `hud_target` | **`None`** | the screen-sized SRCALPHA `hud_surface` |
| `blit_fullscreen(surface)` | `window.blit(surface, (0,0))` | `update()` + `draw()` on a SECOND streaming texture (§2.4) |
| `end_frame()` | `pygame.display.flip()` | composite the HUD texture, then `renderer.present()` |
| `map_event(event)` / `mouse_pos()` | identity / `pygame.mouse.get_pos()` | §2.6 |
| `capture(path)` | `pygame.image.save(window, path)` | `pygame.image.save(renderer.to_surface(), path)` |
| `name` | `"surface"` | `"gpu"` |

**The Surface implementation must be today's calls verbatim** — same order, same
arguments, `hud_target=None` so `Renderer.flush` takes its existing single-call
path. That is the entire no-regression argument for the fallback, the editor,
`tools/smoke.py` and every existing render test.

Both live in `game/main.py`. They are host concerns (window creation, display
mode, present, input mapping) and `engine/` must not learn them; the plan's file
list for G4 says the same (lines 664–666).

### 2.2 Backend selection, the toggle, and the log line

**Toggle spelling — recommended, and stated so the user can flip it without
editing code:**

```
py game/main.py --backend=gpu        # force the GPU path; a failure still falls back, logged
py game/main.py --backend=surface    # force today's path
py game/main.py                      # = --backend=auto (windowed): try GPU, fall back
set HTBH_RENDER_BACKEND=surface      # env override, consulted only when the flag is absent
```

- **CLI flag is primary.** It matches the entry point's one existing flag,
  `--debug[=N]`, which is hand-parsed by `debug_level_from_argv`
  (`game/main.py:1765-1789`) precisely so `main()`'s test seams stay off the
  command line. Write `backend_choice_from_argv(argv, env)` in the same shape,
  next to it, and fail loud (`SystemExit`) on an unrecognised value — a silently
  ignored `--backend=gpu` would make every A/B in §4 a lie.
- **The env var exists for the frozen exe** (a double-clicked build gets no
  argv). Flag wins when both are set.
- **Default: `auto` for a windowed run; forced `surface` whenever `max_frames is
  not None`.** `max_frames is not None` is the existing headless seam
  (`tune_gc = max_frames is None`, `game/main.py:398`), and it is what
  `tools/smoke.py:79,82` drives. That single condition is how the binding
  constraint "`tools/smoke.py` stays on the Surface path" is met **without
  `smoke.py` being modified at all** — verify that and say so. An explicit
  `--backend=gpu` still overrides it (that is what the §4 host test uses).
- **This default is the one decision worth a human's opinion**: `auto` means the
  next person to run `py game/main.py` is on the GPU path. If the orchestrator or
  the user prefers opt-in until the live look is signed off, flip the default to
  `surface` and change nothing else. Flag it in the report.

**The log line — exactly one, printed at boot, before the first frame:**

```
render backend: GPU (SDL2 texture, D3D11) | window 640x360 logical, 2560x1440 actual | ground cache: GroundCacheGpu
render backend: Surface (CPU blitter) | window 640x360 SCALED | ground cache: GroundCache
render backend: Surface (CPU blitter) — GPU requested but unavailable: <exception type>: <message>
```

Use `print()`, **not** `_log.info`. `game/main.py:112` builds a module logger but
nothing ever calls `logging.basicConfig`, so an `info` record has no handler and
is silently dropped; the one existing `_log.warning` (`:1409`) reaches stderr only
via the last-resort handler. The fps line already uses `print` (`:1739-1745`) and
that is where the user is looking. **Purpose of the line is screenshot
self-identification** — a captured PNG plus the terminal above it must answer
"which backend am I looking at?" with no guessing.

### 2.3 The HUD/world split inside `Renderer.flush` — the ONE engine change

`engine/render/renderer.py`, `flush(self, target)` (`:151-243`) becomes
`flush(self, target, hud_target=None)`:

- Build `draw_calls` exactly as today. The loops already run in the required
  order: world sprites (`:166-205`), overlays (`:206-216`), then HUD
  (`:220-235`). **Collect the HUD loop's output into a second list instead of
  appending it to `draw_calls`, and only when `hud_target is not None`.**
- `hud_target is None` → append as today and make the single
  `self._backend(target, draw_calls)` call. **Byte-identical**; this is the path
  the editor, the tests, `tools/smoke.py`, `tools/profile_render.py` and the
  fallback all keep.
- `hud_target is not None` → `self._backend(target, world_calls)` then, only if
  the HUD list is non-empty, `self._hud_backend(hud_target, hud_calls)` where
  `_hud_backend` is `backend_api.default_backend()`, resolved lazily and memoised
  exactly like `self._backend` at `:236-237`. **The HUD always goes to the
  Surface backend, whatever `self._backend` is.**
- Return value and the three `clear()` calls (`:239-242`) are unchanged.
- Comment it with §1.4's guarantee: *the split is by production site, so a
  `slice`/`crop_rect` call can never reach the world backend.*

**Also record the split's timing** (this is how G0's one inferred claim gets a
number, plan lines 366–370): wrap the two backend calls in `time.perf_counter()`
and store `self.last_flush_ms = {"world": …, "hud": …}` (single-call path:
`{"world": total, "hud": 0.0}`). Two `perf_counter` calls per frame is
sub-microsecond and `renderer.py` already imports nothing heavy. If you find a
cleaner seam, take it — **but the HUD number must exist by the end of this
phase**, so do not drop the requirement with the mechanism.

Nothing else in `engine/render/` changes. `backend.py`, `backend_gpu.py`,
`backend_api.py`, `ground_cache.py`, `ground_cache_gpu.py`, `item.py`, `hud.py`,
`__init__.py` are untouched. **`default_backend()` keeps returning the Surface
blitter** — the GPU backend is selected by the host passing
`Renderer(cs, assets, backend=backend_gpu.draw)`… except that `game/main.py:335`
constructs the `Renderer` before the presenter exists, so instead set the already
public constructor argument by constructing the `Renderer` *after* the presenter
(§3), or assign the backend on the existing instance. Prefer construction order:
`Renderer.__init__` already takes `backend=` (`renderer.py:88-91`).

### 2.4 The HUD composite, step by step (GPU path)

Per frame, in `end_frame()`:

1. The HUD was already drawn — `Renderer.flush(sdl_renderer,
   hud_target=hud_surface)` did it, through the **Surface** backend, into the
   host's screen-sized `SRCALPHA` surface. Fonts, nine-slice, crop and the four
   HUD primitives ran their existing, well-tested code (D7).
2. `hud_texture.update(hud_surface)` — **one upload per frame**, explicit,
   never through `backend_gpu`'s cache (§1.3).
3. `hud_texture.draw(dstrect=pygame.Rect(0, 0, view_w, view_h))`.
4. `renderer.present()`.

The texture is created ONCE at presenter construction:
`Texture(renderer, (view_w, view_h), streaming=True,
scale_quality=SCALEQUALITY_NEAREST)` then `blend_mode = pygame.BLENDMODE_BLEND`
**explicitly** (§1.7 item 5 — the constructor leaves it at `BLENDMODE_NONE`).
`begin_frame()` clears the surface with `fill((0, 0, 0, 0))` (0.024 ms measured).
`blit_fullscreen` (the cutscene) gets its **own** second streaming texture — do
not reuse the HUD one, the two are drawn at different points in the frame and
sharing would upload the wrong pixels.

**One honest divergence to flag, test and look at.** Today a translucent HUD
element alpha-blends directly onto the opaque world frame. On the GPU path it
blends onto a transparent surface first and the result is composited. For a
single translucent element the two are equal; for **overlapping** translucent
elements pygame's SRCALPHA-onto-SRCALPHA blit is not guaranteed to match
blend-onto-opaque exactly. There is no cheap fix (the world frame is in VRAM;
reading it back per frame defeats the port), so the answer is to **look**: the
pause overlay, the level-up window, the game-over dim, the tutorial banner and
the enemy-intro dialogue are the translucent-stacked screens. §4 names them.

### 2.5 Ground cache selection, and construction order

- GPU path: `GroundCacheGpu(sdl_renderer, cs, assets, bg_color=BACKGROUND)`.
- Surface path: today's `GroundCache(cs, assets, bg_color=BACKGROUND)`
  (`game/main.py:339`) — unchanged, and still what the editor and
  `tools/profile_render.py` use.
- **Both are then used identically.** `ensure(...)` (`:1503-1507`) and
  `blit(...)` (`:1508`) need no branch: `GroundCacheGpu.blit` ignores its
  `target` argument by design (`ground_cache_gpu.py:114-127`). Pass
  `presenter.world_target` for both and let the GPU class ignore it. Say in a
  comment that the argument is ignored on that path, or a reader will "fix" the
  call.
- `on_zone_change = ground_cache.invalidate` (`:432-433`) is identical on both.
- **Construction order must move.** `game/main.py:339` builds the ground cache
  ~40 lines BEFORE the window exists (`:381`), and the GPU cache needs the SDL
  renderer. Move the ground-cache construction (and the `Renderer` construction
  at `:335`, which now needs `backend=`) to immediately after the presenter is
  built at `:381`. Nothing between `:335` and `:381` uses either object —
  verify that before moving, and state it in the report.
- A failure constructing `GroundCacheGpu`'s render targets is a **fallback
  trigger**, not a crash (D8, §1.5). G3 deliberately let the error propagate for
  exactly this reason (its brief §2.7), so catch it here, at the one place that
  can rebuild the whole target on the Surface path.

### 2.6 Input coordinates — mandatory, not optional

Under `SCALED`, pygame remaps mouse coordinates from the physical window back to
the 640×360 logical surface for free. **On a standalone SDL window it does not**,
and `data/display.json`'s default mode is `fullscreen` — so without this the game
still runs and every click lands somewhere else. It would pass every headless
test.

- `renderer.logical_size = (view_w, view_h)` at presenter construction.
- **One insertion point**: at the head of the event loop
  (`game/main.py:995`), `event = presenter.map_event(event)`. The Surface
  implementation returns the event unchanged; the GPU one rebuilds mouse events
  via `pygame.event.Event(e.type, e.__dict__ | {"pos": mapped})` (measured, §1.7
  item 8) using `coordinates_from_window` (which returns floats — cast to `int`).
  Map `MOUSEMOTION`, `MOUSEBUTTONDOWN`, `MOUSEBUTTONUP`; if any handler reads
  `event.rel`, scale it too (**check** — a grep for `event.rel` in
  `game/main.py` returned nothing, so today it does not).
- The two `pygame.mouse.get_pos()` reads (`:1171`, `:1176`) become
  `presenter.mouse_pos()`.
- **Windowed mode makes this a no-op** (window size == logical size == 640×360),
  which is why the live test in §4 opens windowed FIRST and only then tries
  fullscreen: a clean windowed run isolates rendering from input mapping.
- Display-mode changes (`:572`, the settings intent) must go through the
  presenter too: `window.set_fullscreen(desktop=True)` / `set_windowed()` /
  `window.borderless` on the GPU path, `_apply_display_mode` unchanged on the
  Surface one. **`_apply_display_mode` itself must keep its exact signature** —
  `tools/profile_render.py:57` imports it (`from game.main import BACKGROUND,
  _apply_display_mode`).

### 2.7 The capture path — how the CPU/GPU pair finally gets compared

This is what closes G2's outstanding pixel-art check (plan lines 527–532).

- **Key binding `F12`** → save a PNG of the live frame. **Verified free**: a grep
  for `K_F` in `game/main.py` returns nothing, so no F-key is bound today.
- Path: `build/capture_<backend>_<YYYYmmdd-HHMMSS>.png` — `build/` is gitignored
  and the root `CLAUDE.md` forbids committing it, so a capture can never dirty
  the tree. Create the directory if absent. `print()` the saved path (the user
  needs to find it).
- Surface path: `pygame.image.save(window, path)`.
- GPU path: `pygame.image.save(renderer.to_surface(), path)` — **measured
  working**, 0.75 ms at 640×360 (§1.7 item 6). Capture AFTER the HUD composite
  and BEFORE `present()`, so the PNG is the full frame the user is looking at.
- The filename carries the backend name so a pair of PNGs is self-identifying
  even without the terminal.

### 2.8 Docs

- **`engine/render/CLAUDE.md`** — the "Second backend: `render/backend_gpu.py`
  (G2)" section currently ends with "**Nothing selects it yet** — `default_
  backend()` is still the Surface backend and G4 wires the host." Replace that
  one sentence: the game host selects it via `--backend`, `default_backend()` is
  still the Surface blitter for everyone else, and the HUD composites over it as
  one streaming-texture upload per frame through `Renderer.flush(target,
  hud_target=…)`. Also correct the same "nothing selects this class yet" sentence
  at the end of the "GPU variant (G3, `ground_cache_gpu.py`)" bullet inside
  "## Ground layer cache". Add the `hud_target` parameter to the "Render flow"
  bullet's description of the backend contract.
- **`engine/CLAUDE.md`** — the pygame-import allow-list needs **no change** (both
  GPU modules are already named there; verified). If nothing architectural
  changed in `engine/` beyond `flush`'s new parameter, one clause in the "Render
  flow"-adjacent text is enough — **do not restructure**, and note that G3 edited
  the allow-list bullet, so stay out of that bullet's region (§3).
- **`game/PERF.md`** — the "Frame-timing HUD" section (`:154-157`) documents the
  four buckets by name. G4 changes them (§2.9). Update it, and add a short
  paragraph naming the two backends, the `--backend` flag and the F12 capture.
  This is the game package's doc and the router says architectural changes update
  the package doc.

### 2.9 Re-measurement — half the phase (plan lines 686–687, §9 lines 997–1012)

Two instruments, both required.

**(a) `game/main.py`'s frame-timing HUD, extended.** `perf` (`:976`) gains the
split the port makes possible:

```
sim | submit | world | hud | composite | present
```

`world`/`hud` come from `renderer.last_flush_ms` (§2.3); `composite` is the HUD
upload + draw; `present` replaces `flip`. On the Surface path `hud` and
`composite` are 0.0 and the line reads as before. Keep the `tune_gc` gate so
headless stays silent. **This is the instrument that answers G0's one inferred
claim** — that the HUD is not the dominant cost — with a number, on both
backends.

**(b) `tools/profile_render.py`, taught the GPU path and the overlay pass.**

- `--backend={surface,gpu}` (default `surface`), selecting the same two stacks:
  SCALED window + `GroundCache` + `Renderer(...)`, versus `_sdl2` Window +
  `Renderer(window, target_texture=True)` + `GroundCacheGpu` +
  `Renderer(cs, assets, backend=backend_gpu.draw)`, with `renderer.present()`
  replacing `pygame.display.flip()` in `run_case` (`:283`).
- **`--overlays N`, and this is the point of the exercise.** The harness submits
  no overlays today, so G0's `flush` bucket contains none — yet `backend_gpu`
  rasterizes every `OverlayLines`/`OverlayPolys` into a bounding-box `SRCALPHA`
  scratch Surface and **uploads it per call, per frame, uncached**
  (`backend_gpu.py:110-156`), with **no clip to the target**, where `backend.py`
  draws straight onto the target and clips. PR #122's `WorldFill` now routes
  every tile highlight and wall segment through that path
  (`renderer.py:167-182`). Submit N diamonds shaped like
  `game/ui/widgets.py`'s `submit_tile_diamond_fill` and measure
  **`flush(N) − flush(0)` on BOTH backends** — the delta IS the overlay pass.
- **Also measure the pathological case once**: one polyline with a single point
  far off-screen (the renderer converts world→screen without clipping), which
  asks `backend_gpu` for a scratch Surface that wide every frame. Report the
  number even if it is fine; "we looked" is the deliverable.
- Keep every determinism property the harness already has (fixed map file, seeded
  placement, fixed serpentine pan, 30 warm-up + 300 measured frames) so the two
  backends are like-for-like.

**The table to fill in and write into the plan** — same map/zoom/camera/sprite
cells as G0 (plan lines 301–314), doubled by backend:

| Map | Zoom | Camera | Sprites | Backend | ground | submit | world | overlay Δ | hud | composite | present | frame | fps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| first_light 20² | 1.0 | static | 1016 | surface / gpu | | | | | | | | | |
| first_light 20² | 1.0 | panning | 1016 | surface / gpu | | | | | | | | | |
| first_light 20² | 2.0 | static | 1016 | surface / gpu | | | | | | | | | |
| first_light 20² | 2.0 | panning | 1016 | surface / gpu | | | | | | | | | |
| holex 1024² | 1.0 | panning | 1016 | surface / gpu | | | | | | | | | |
| holex 1024² | 2.0 | panning | 1016 | surface / gpu | | | | | | | | | |
| …the 160-sprite rows, same cells | | | | surface / gpu | | | | | | | | | |

Write it into §6/G4 RESULTS beside G0's, with the machine/driver named (the SDL
renderer's actual driver, from the log line) and a one-paragraph verdict.
**If the GPU path is SLOWER anywhere, that is a finding to report, not a number
to bury** — and the overlay Δ column is where the plan predicts it will show up.

---

## 3. File scope + shared-file contract

**Modified — and nothing else in these files**

- `game/main.py` — §2.1–§2.7. The bulk of the phase. Touch points, all cited:
  `:112` (logger note only), `:134-146` (`_apply_display_mode` — **signature
  frozen**, `tools/profile_render.py:57` imports it), `:335` + `:339` (moved
  after `:381`), `:381`/`:572` (presenter construction / display-mode change),
  `:398` (`tune_gc` — the same `max_frames` seam decides the default backend),
  `:976` + `:1730-1748` (perf buckets), `:995` (`map_event`), `:1171`/`:1176`
  (`mouse_pos`), `:1455`/`:1460`/`:1710` (`begin_frame` / `blit_fullscreen`),
  `:1468`/`:1704`/`:1717`/`:1725` (the four flushes → `presenter.world_target`
  + `hud_target`), `:1508` (ground blit), `:1727` (`end_frame`), and a new
  `backend_choice_from_argv` next to `debug_level_from_argv` (`:1765-1789`).
- `engine/render/renderer.py` — §2.3 ONLY: the `hud_target` parameter, the
  memoised `_hud_backend`, `last_flush_ms`. **No other behavioural change**; the
  `hud_target=None` path must stay byte-identical. If your diff to this file
  exceeds ~35 lines, stop and report.
- `tools/profile_render.py` — §2.9(b): `--backend`, `--overlays`, the GPU stack
  in `build_stack` (`:180-195`) and `run_case` (`:236-300`), and two new columns
  in `print_table` (`:301-329`).
- `engine/render/CLAUDE.md`, `engine/CLAUDE.md`, `game/PERF.md` — §2.8.
- `tools/tests/test_game_boot.py` — §4 (the forced-fallback and GPU-boot tests).
- `tools/tests/test_render.py` — §4 (the `hud_target` split tests). This module
  owns the `RecordingBackend` those tests need.
- `planning/GpuAndMasterSheetsPLAN.md` — §6/G4 RESULTS + the §5 Status row. (The
  orchestrator may prefer to write this itself; ask rather than assume.)

**Untouched — stated hard, because the temptation is real**

- `engine/render/backend_gpu.py` — **not modified.** It is merged and
  parity-pinned. If you believe it is missing something G4 needs (a HUD branch, a
  slice implementation, an overlay clip), **stop and report** — every one of
  those is a plan decision (D7, §9), not an implementation detail. The overlay
  clip in particular is a *measurement* task this phase, not a fix.
- `engine/render/ground_cache_gpu.py`, `ground_cache.py`, `backend.py`,
  `backend_api.py`, `item.py`, `hud.py`, `fonts.py`, `__init__.py` — untouched.
  `default_backend()` keeps returning the Surface blitter.
- `editor/**` — untouched, entirely. It keeps the Surface backend and its
  module-level `SDL_VIDEODRIVER=dummy` rule, which is precisely why D6 is a dual
  backend (plan lines 139–146, 676–678).
- `tools/smoke.py` — untouched, and it stays on the Surface path **by virtue of
  `max_frames is not None`** (§2.2). Confirm by running it; do not add a flag to
  it.
- `data/**` — nothing. No new tunable; the backend choice is a runtime flag, not
  content.
- `conftest.py` — no `TIERS` line needed: both test modules
  (`test_game_boot`, `test_render`) already have one (`conftest.py:109` and its
  neighbour). If you add a NEW module instead, it needs a `TIERS` entry or it
  silently never runs.

**Shared-file contract.** This is a single-phase run on `phase-G4-umbrella`
(stacked on `phase-G3-umbrella`); no sibling phase is in flight. Two docs were
already edited by G3 and must be appended to in **different regions**:
`engine/CLAUDE.md` (G3 added `ground_cache_gpu.py` to the pygame-import
allow-list bullet — **stay out of that bullet**; G4 needs no allow-list change at
all) and `engine/render/CLAUDE.md` (G3 appended the "GPU variant (G3,
`ground_cache_gpu.py`)" bullet at the end of "## Ground layer cache" — G4 edits
the trailing "nothing selects it yet" sentence of that bullet and of the "Second
backend" section, not the bullet's structure). The only other pending edit to
`conftest.py` in this plan is M3's `TIERS` line (plan line 792), and G4 adds none.

---

## 4. Exit gate + Quick Test

### 4.1 Required tests (bare minimum, but each pins a real failure mode)

**`tools/tests/test_render.py`** — the split, with the existing
`RecordingBackend`:

1. `flush(target)` with no `hud_target` produces the SAME single flat list as
   today (world + overlay + HUD, in order) through the injected backend. The
   no-regression pin.
2. `flush(target, hud_target=h)` sends **only** world+overlay calls to the
   injected backend and the HUD calls to `h` through a second recorded backend;
   assert the HUD list contains the `HudRect`/`HudText` objects and the resolved
   `HudSprite` `DrawCall`, and that **no call reaching the world backend has a
   non-`None` `slice` or `crop_rect`** (§1.4).
3. Both paths return the same count and leave all three queues empty.

**`tools/tests/test_game_boot.py`** — the host, headless under the dummy driver
(which **can** host a Renderer, plan §4 lines 175–196):

4. **GPU boot**: `main(max_frames=5, autostart=True)` with the backend forced to
   `gpu` returns 5 frames and prints a log line naming the GPU backend. This is
   the first CI coverage the GPU host path has ever had.
5. **Forced fallback** (plan line 683): same call, with
   `pygame._sdl2.video.Renderer` monkeypatched to raise → returns 5 frames,
   prints the Surface-with-reason line, and does **not** raise. Capture stdout to
   assert the line.
6. **The HUD does not freeze** — the §1.3 pin. Drive ≥2 frames on the GPU path
   with a spy on the HUD texture's `update`, and assert it was called **once per
   frame**, not once total. This is the only test that would catch the snapshot
   bug, and the bug is otherwise invisible.

> That is the whole test budget. Then `py tools/smoke.py`. **NOT** the full
> suite, **NOT** a tier sweep (`-m core` / `-m editor` / `-m meta`), **NOT**
> `py tools/testgate.py check`, **NOT** `--affected` — the `test_guard.py` hook
> denies all of those for a subagent (plan §8, lines 932–957).
>
> If `test_guard` denies a command, do NOT re-issue it and do not vary the flags
> (it normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints
> identically). Report the deny text and stop testing. **A denied run is a
> report, never a retry.**

### 4.2 Exit gate (the coder's, verbatim)

1. `py tools/smoke.py` — green, and **confirm from its output that it took the
   Surface path** (no GPU log line).
2. `py -m pytest tools/tests/test_render.py tools/tests/test_game_boot.py` —
   green, collected count up, **no skips** (an unexpected skip is a failure).
3. `py -m pytest tools/tests/test_render_backend_parity.py tools/tests/test_ground_cache.py`
   — still green, untouched (they are the G2/G3 pins this phase must not move).
4. The re-measurement table (§2.9) filled in on both backends and written into
   the plan, with the machine and the SDL driver named.

### 4.3 Quick Test — **the user runs this, at a display, in ten minutes**

This closes THREE checks that have never been run (plan lines 1028–1035): G2's
pixel-art look, G3's large-map pan, and G4's own GPU-vs-fallback comparison. Do
them in this order; each step says what a **pass** looks like.

**Step 0 — windowed, so input mapping is out of the picture (30 s).**
In the game's Settings, set display mode to **windowed** once, then quit. (The
committed default is `fullscreen`, and fullscreen additionally exercises the
mouse remapping in §2.6 — that is Step 5, deliberately last.)

**Step 1 — the GPU path boots and says so (1 min).**
```
py game/main.py --backend=gpu
```
*Pass*: the terminal's FIRST line reads `render backend: GPU (SDL2 texture, …)`.
The main menu and the map draw. Start a game, place a musician, run a round.
*Fail*: the line says `Surface … GPU requested but unavailable` — copy that
reason into the report; that is the fallback working, and the phase is not done.

**Step 2 — pixel-art crispness at zoom (2 min). This is G2's outstanding
check.**
Zoom all the way IN (scroll wheel) on a building and an enemy with real art.
Press **F12**. Then, in the same session or a second run:
```
py game/main.py --backend=surface
```
Reach the same zoom and roughly the same view, press **F12** again.
Open the two PNGs from `build/` side by side, at 1:1 and then magnified 4–8×
(any image viewer with nearest-neighbour zoom).
*Pass*: sprite edges are equally hard on both; no softening, no colour fringe
along alpha edges, no half-pixel shift of the whole sprite.
*Fail*: the GPU one looks blurred or fringed → the nearest-pixel sampler is not
taking effect. Report it; plan §9 (lines 989–993) says a blurrier GPU path is a
regression no fps number redeems.

**Step 3 — panning a large map, no seams, no stutter (3 min). This is G3's
outstanding check.**
Load/point the game at the 1024² map (`holex` — the map G0 profiled), zoom to
maximum, and right-click-drag pan continuously in a slow figure-eight for ~20
seconds.
*Pass*: no seam line trailing the pan direction; no flash of background colour
along the leading edge; no one-pixel jitter of the tile grid as the pan crosses
`.5` boundaries; no periodic hitch. Stop the camera: the ground is perfectly
still (not drifting).
*Fail*: any of the above — report which, with an F12 capture.

**Step 4 — the HUD is alive, and unchanged (2 min). This is the §1.3 trap.**
Watch the love counter, the round/phase text and the fps line while a round
runs; open the building panel on two different tiles in a row; open the pause
menu (Esc), the level-up window and — if you can reach one — the enemy-intro
dialogue.
*Pass*: every number updates every frame; the panel changes when you click a
different tile; text is crisp; the nine-slice panel borders look exactly as they
do on `--backend=surface`; the translucent overlays (pause dim, level-up, game
over, tutorial banner) look the same shade on both backends.
*Fail — the one to watch for*: the HUD is **frozen at its first frame** while the
world keeps moving. That is the snapshot bug (§1.3) and it must block the phase.

**Step 5 — fullscreen, i.e. input mapping (1 min).**
Set display mode back to fullscreen (or launch fullscreen) on `--backend=gpu`.
Click a tile.
*Pass*: the tile you clicked is the tile that highlights, at the top-left,
centre and bottom-right of the screen.
*Fail*: the highlight lands offset — the logical-size remap (§2.6) is wrong.

**Step 6 — the number (1 min).**
Play into a late round on both backends and read the frame-timing line
(`sim= submit= world= hud= composite= present=`) beside the fps.
*Pass criterion, stated honestly*: the `world` bucket at the boss load should be
dramatically below G0's measured **61–81 ms**, and `hud` + `composite` should be
small. If `world` did not move, say so — a re-scope is a legitimate outcome (D9's
posture), and the overlay Δ column in §2.9 is the first place to look.

### 4.4 Also state in the report

- The **toggle spelling** shipped, the **default**, and whether smoke/tests were
  confirmed to stay on the Surface path without editing `tools/smoke.py`.
- The **exact log line** emitted on each of the three outcomes (GPU, Surface,
  GPU-requested-but-failed), pasted verbatim.
- The **HUD composite mechanism**: streaming vs static texture, and the
  **measured** per-frame cost of `update()`+`draw()` on real hardware (both, if
  you measured both — §1.7 item 6 says the software renderer does not settle it).
- Whether `Renderer(window, target_texture=True)` was needed on real hardware
  (§1.7's last item) — this is a "green in CI, broken on the user's machine"
  candidate and the answer is worth writing down.
- The re-measurement table, the **overlay Δ** on both backends, the
  far-off-screen-polyline number, and the **HUD-pass number that retires G0's one
  inferred claim**.
- Which checks were **live** and which were headless — per phase-report house
  rule, and because G2 and G3 both had to write "the live look was NOT run". G4
  is the phase that stops saying that.
