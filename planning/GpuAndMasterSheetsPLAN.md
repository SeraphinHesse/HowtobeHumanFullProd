<!-- status: IN PROGRESS — G0-G4 and M1 done; G5, G6 and M2-M5 remain -->

# GpuAndMasterSheetsPLAN.md — GPU render backend, then master spritesheets

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`TimelinePLAN.md`). Base branch: `Development`.

**Run it ONE PHASE AT A TIME** — `/execute-plan-phases
planning/GpuAndMasterSheetsPLAN.md G1` then `… G2`, and so on. This plan is a
dependency chain, not a fan-out; **§5.1 explains why a multi-phase range is the
wrong invocation here** and which two phases should use `/execute-phase`
instead. Written against `Development` @ `bb0af73`; every file/line reference
below was re-verified after that merge.

Packages touched: **engine** (render backend, asset store, manifest), **data**
(two schemas, one new registry, one new content folder), **editor** (details
panel, sheet preview, a new dialog, a new pure module, the vfx panel), and one
line of **game** (`game/main.py` backend selection). It is a cross-package plan
by construction — no single phase spans two packages except where stated.

## 1. Vision

Two connected asks, ordered GPU-first at the user's explicit direction.

**Master spritesheets.** Today a slot's art is a whole PNG. One PNG can
*already* back many slots — a manifest entry's `sheet` is a real relative path,
not a slot-derived name, and "Use Spritesheet…" links slots to one file with
refcounting. What is missing is the thing that makes a *master* sheet usable:
**a row window**. Slicing always starts at sheet row 0, so ten characters
stacked in one PNG cannot each claim their own rows.

The designer flow being built:

> Next to **Import Spritesheet…** and **Use Spritesheet…**, a third button
> **Use Master Spritesheet…**. It opens a small popup: import a NEW master
> spritesheet, or use an EXISTING one (a list of every master sheet already
> imported, any of which can be selected). Once a master sheet is chosen, a new
> line appears under that selection, styled exactly like the Frame W/H row:
> **using rows [ ] til [ ]**. Only those rows appear in the spritesheet preview
> and in the row editors at the bottom. Master spritesheets are saved as their
> own category.

**GPU rendering.** The renderer blits Surfaces on the CPU
(`engine/render/backend.py`). Worse for this feature: `AssetStore._sheets` is
keyed by `slot_key`, **not** by file path, so a master sheet shared by ten slots
decodes ten times and holds ten Surfaces. The user named four drivers —
one-upload-per-file, a **measured frame-rate problem in game**, memory
footprint, and future-proofing. Because a real frame-rate complaint is in scope,
this plan **measures before it rewrites** (phase G0), and G0 is allowed to
re-scope Part A.

The two halves meet at one place: *one source file = one texture* is exactly the
keying master sheets need, so doing GPU first means master sheets are built on
the texture path from day one.

## 2. Architecture

```
BEFORE                                   AFTER
──────                                   ─────
Renderer (pure orchestration)            Renderer (pure orchestration)
  └─ flush() → DrawCall list               └─ flush() → DrawCall list  (UNCHANGED)
       └─ backend.draw(surface, calls)          ├─ backend.draw(...)        editor / tests / smoke
                                                └─ backend_gpu.draw(...)    game/main.py
                                                     ▲ falls back to backend.draw

GroundCache → oversized Surface          GroundCache → Surface  (editor / tests)
   pan = Surface.scroll (memmove)        GroundCacheGpu → target Texture pair (game)
                                            pan = self-blit between two targets

AssetStore._sheets[slot_key] = Surface   AssetStore._sheets[entry.sheet] = Surface
   ten slots on one PNG = ten Surfaces      ten slots on one PNG = ONE Surface = ONE Texture

manifest entry                           manifest entry
  {sheet: "imported/x.png", …}             {sheet: "imported/x.png" | "master/y.png",
  rows[i] ≡ sheet row i                     row_start?: int,  …}
                                           rows[i] ≡ sheet row (row_start + i)

data/sprites/                            data/sprites/
  imported/*.png                           imported/*.png          (unchanged)
  asset_manifest.json                      master/*.png            NEW, committed content
                                           master_sheets.json      NEW, own schema
                                           asset_manifest.json
```

**HUD is deliberately NOT migrated.** `HudRect`/`HudText`/`HudSprite`/`HudLines`,
the font cache, the nine-slice compositor and the crop path all stay on the
Surface backend and composite over the GPU frame as **one upload per frame**.
That is a few dozen items a frame with text and 9-patch geometry — the fiddliest
to port and the least to gain — and keeping it single-implementation is what
bounds the dual-backend parity burden.

Route to the subsystem docs rather than restating them: `engine/render/CLAUDE.md`
(depth_key layer-primary invariant, ground-cache scroll technique, nine-slice,
the pixel quantizer), `engine/assets/CLAUDE.md` (manifest v2 optional keys,
store cache contract, E-37 tolerance split), `editor/panels/CLAUDE.md`
(DetailsPanel conventions, sheet preview, the `_NoWheel*` rule),
`data/CLAUDE.md` (schema house style, sheet-sharing rules, D-31 committed art).

## 3. Decisions (settled with the user — do not re-litigate)

- **D1 — Master sheets are a REGISTRY FILE + FOLDER, not a `slots.json`
  category.** `data/sprites/master/*.png` plus `data/sprites/master_sheets.json`
  and its own schema. A master sheet is a FILE with metadata; it is never
  previewed, animated or rendered on its own, so a `slots.json` category would
  hand it machinery it cannot use (an animation vocabulary, a frame-size
  category default, a selector tree node, a per-sheet slot key that must be
  unique repo-wide, an entry in the generated cross-category `sprite_slot` enum).
  This is the "own category" the ask names — its own storage concept, separate
  from `imported/`.
- **D2 — The row window is an optional `row_start` int on the manifest entry.**
  `rows[0]` (idle) resolves to sheet row `row_start`; entry row *i* resolves to
  sheet row `row_start + i`. The **til** blank in the UI is derived from
  `len(rows)`, not stored — storing both would be a second source of truth that
  must always agree with the rows array. Omitted ⇒ 0 ⇒ **every existing entry is
  byte-identical**, the same convention `slice` and `tint_overlay` already
  follow. Rejected alternative: absolute row indices per `rows[]` entry — more
  flexible (non-contiguous rows) but it breaks the "array position IS the row"
  rule the whole `playback_order` path assumes.
- **D3 — The master sheet OWNS the frame size; a linking slot inherits it.**
  `frame_w`/`frame_h` live on the registry entry, set once at master-sheet
  import, and are written into the linking slot's manifest entry. The Frame W/H
  spinboxes go **read-only (greyed + tooltip)** while a master sheet is selected.
  One sheet, one grid: if two slots cut the same master sheet at different frame
  sizes, the row numbers in "using rows a til b" mean different things per slot
  and the whole feature stops being legible. This deliberately bypasses
  `DetailsPanel._on_frame_size_changed`'s two-file write — a master sheet's grid
  is **not** a per-slot `slots.json` override and must not touch `slots.json`.
- **D4 — The row window is offered for master sheets ONLY.** A plain per-slot
  sheet starts at row 0 by definition; adding the control everywhere would put a
  spinbox pair on every slot in the editor that almost none of them would use.
  The row appears exactly when a master sheet is selected, matching the ask
  ("a new line appears under this selection").
- **D5 — The button lands in `DetailsPanel` and `VfxPreviewPanel`, not the
  palette.** DetailsPanel is the main per-slot importer and owns the Frame W/H
  row the new line mirrors. The palette's importer (`editor/panels/palette.py`)
  is the map/deco/base path, reachable only while a map is open, and is
  explicitly out of scope.
- **D6 — Dual render backend.** The existing Surface blitter STAYS as the
  editor / test / headless path; a new Texture backend serves `py game/main.py`.
  Both consume the SAME `DrawCall` list, so this is one render path in the ED-22
  sense — not a second renderer of game content. This is forced, not preferred:
  `pygame._sdl2.video.Renderer` needs a real SDL **Window**, while
  `editor/panels/viewport.py` sets `SDL_VIDEODRIVER=dummy` at module level before
  importing pygame, and the entire suite plus `tools/smoke.py` run under that
  same dummy driver.
- **D7 — GPU scope is world sprites + ground cache; HUD stays on Surface.** See
  §2. The world layer is where the sprite volume and the shared-sheet batching
  win actually are.
- **D8 — No-GPU fallback is the Surface backend**, logged, never a hard failure.
  It is the same code the editor and tests exercise on every run, so the
  fallback path is continuously tested rather than dead code. Rejected: SDL's
  software renderer (generally slower than direct Surface blitting for this
  workload, and a second untested path); fail-loud (a machine without
  acceleration could not play at all).
- **D9 — G0 measures before anything is rewritten, and may re-scope Part A.**
  The user named a real frame-rate problem. If the profile says the cost is
  elsewhere (per-frame Python in the submit loop, `pygame.transform.scale` at
  zoom, the flip), the honest outcome is a re-scope recorded in this doc, not a
  rewrite that misses.
- **D10 — `_frames` / `_hit_masks` stay keyed per slot.** Only `_sheets` is
  re-keyed onto `entry.sheet`. Two slots may legitimately slice one file at
  different frame sizes (a plain shared sheet still can — D3 constrains master
  sheets only), and a wrong key in the frame cache is a silent wrong-pixels bug,
  not a crash. Deduping frames too would mean folding `frame_w`/`frame_h`/
  `row_start` into the key; noted as a follow-up, not done here.

## 4. Environment facts (verified on this machine)

- pygame-ce **2.5.7** (SDL 2.32.10), Python 3.13.2.
- `pygame._sdl2.video.Renderer` imports cleanly — the API exists.
- `engine/render/` is small: `backend.py` 227 lines, `renderer.py` 211,
  `ground_cache.py` 186, `hud.py` 141, `fonts.py` 186, `item.py` 68. The
  migration is contained.
- **RESOLVED by G1's probe (measured 2026-08-12) — the dummy driver CAN host a
  Renderer.** This was the plan's one "unverified and load-bearing" item: whether
  an SDL2 `Renderer` can be created at all under `SDL_VIDEODRIVER=dummy`, which
  decides whether the GPU path can be *tested* headlessly. It can. A throwaway
  probe (one fresh subprocess per driver, since SDL init is process-global)
  drove `pygame.init()` → `pygame._sdl2.video.Window` → `Renderer` →
  `Texture.from_surface` upload → `clear()` + `draw()` + `to_surface()` readback
  + a pixel comparison:

  | Driver | Result |
  |---|---|
  | **`dummy`** | **full success** — Window, Renderer, Texture upload, draw and `to_surface()` readback all worked; the read-back pixel `(10, 200, 30)` matched the uploaded colour exactly |
  | `offscreen` | fails at `Window()`: "offscreen not available" |
  | `software` | fails at `Window()`: "software not available" |

  `dummy` is the one that matters — it is already the driver the entire test
  suite and `tools/smoke.py` run under. **So G2's parity test can run in normal
  CI and must NOT be marked live-only**, and §9's "reduction in safety" risk is
  retired. `offscreen`/`software` being unavailable in this SDL build is moot.
  (D6's dual backend was never contingent on this — it stands either way,
  because the editor's `SDL_VIDEODRIVER=dummy` module-level rule is about the
  editor keeping the Surface path, not about testability.)

---

## 5. Build order

| Phase | Scope | Package | Depends on | Status |
|-------|-------|---------|-----------|--------|
| G0 | Measure the real render cost (no engine changes) | tools/game | — | **DONE** — verdict in §6/G0: blit throughput dominates (84–97% of frame); Part A proceeds unchanged |
| G1 | Backend seam + headless-renderer feasibility probe | engine | G0 verdict | **DONE** — `backend_api.py` seam; probe says the dummy driver CAN host a Renderer (§4), so G2's parity test runs in CI |
| G2 | `backend_gpu.py` — world sprites, overlays, texture cache | engine | G1 | **DONE** — parity within a pinned tolerance of 1 (§6/G2 RESULTS); nothing selects it yet, G4 wires the host |
| G3 | Ground cache on the GPU path | engine | G2 | **DONE** — `ground_cache_gpu.py` on render-target textures, pins parameterised over both implementations (§6/G3 RESULTS); still nothing selects it, G4 wires the host |
| G4 | Host wiring, HUD composite, fallback, re-measure | engine + game | G3 | **DONE** — `--backend={gpu,surface,auto}` wires the host, HUD composites as one streaming upload/frame, D8 fallback tested; `GATE PASS 2334`. **All five §4.3 live checks passed at a display**, closing G2's pixel-art look and G3's large-map pan. Re-measure (SOFTWARE renderer, §6/G4 RESULTS): boss-load `world` 61–69 ms → 9.5–11.5 ms, but GPU **slower on every holex row** and the overlay pass **6× worse** — that regression is a live Part-A decision |
| G5 | Overlay pass: clip the scratch to the target, reuse the buffer | engine | G4 | not started — **scheduled, not deferred**; brief in §6/G5. Fixes the 6× overlay regression G4 measured |
| G6 | Retire G0's inferred HUD-cost claim (live frame timings) | — (measurement only) | G4 | not started — **`/execute-phase` with the user at a display**; no agent can run it (§6/G6) |
| M1 | Data layer: master-sheet registry + schema + `row_start` | data | — | **DONE** — schema + seeded registry + `data/sprites/master/`; existing manifest byte-identical |
| M2 | Engine: `row_start` slicing + sheet-path-keyed store | engine | M1, G2 | not started |
| M3 | Editor: pure master-sheet import module + picker dialog | editor | M1 | not started |
| M4 | DetailsPanel: button, row window, narrowed preview + rows | editor | M2, M3 | not started |
| M5 | VFX preview panel button | editor | M4 | not started |

### 5.1 This plan is a CHAIN, not a fan-out — read before dispatching

`/execute-plan-phases` dispatches one planner per phase and then one coder per
phase **in parallel waves**. That fits a plan whose phases are independent.
**This plan's are not.** The `Depends on` column above is near-total: G2 writes
against the seam G1 creates, G3 draws into the backend G2 wrote, M2 parses the
schema M1 added, M4 drives the dialog M3 built. Dispatching G1–G4 as one
parallel wave gives three coders a seam that does not exist yet.

Two consequences, both binding on whoever executes this:

- **Run it in dependency-respecting ranges, not one big range.** The genuine
  parallelism here is exactly one pair: **M1 is independent of all of Part A**.
  Everything else is sequential. Recommended invocations, in order:
  `G0` → *(user reads the verdict)* → `G1` → `G2` → `G3` → `G4` → `M1` → `M2`
  → `M3` → `M4` → `M5`. A single-phase range is a legal range and the
  orchestrator's wave machinery degenerates to planner→coder→reviewer for that
  one phase, which is the correct shape here.
- **`/execute-phase` is the better tool for most of these** — it is the
  interactive single-phase skill and it updates this doc's Status column the
  same way. Use `/execute-plan-phases` when you want the unattended
  planner→coder→reviewer→PR wave for one phase; use `/execute-phase` when you
  want to be in the loop. **G0 and G4 should be `/execute-phase`**: G0's output
  is a judgement call the user must read before Part A continues, and G4's exit
  gate is a live `py game/main.py` look that no headless agent can perform.

**Concurrency rule if you do run two phases at once** (only M1 alongside a Part-A
phase qualifies): each implementation agent gets `isolation: "worktree"`. A
file-scope fence written in a dispatch prompt is honour-based prose; a worktree
is enforced. This is a root `CLAUDE.md` hard rule and it has already cost this
repo one incident.

---

## 6. Part A — GPU render backend

### Phase G0 — Measure

**Goal**: know what is actually slow, in numbers, before a line of
`backend_gpu.py` exists. This phase exists to prevent the failure mode of
rewriting the wrong thing.

**Files** — new: `tools/profile_render.py` (a small, deterministic harness;
gitignored output). Modified: `game/main.py` (a per-frame timing split behind a
flag — removed or left flag-off at the end of the phase), this plan doc (the
measurement table is written INTO §6/G0 as the phase's deliverable).

**What to capture**
- Per-frame wall-clock split: `GroundCache.ensure` / `Renderer.flush` sprite
  pass / HUD pass / `display.flip`, as mean and 95th percentile over ≥300 frames.
- On the committed map `data/maps/first_light.json` (never the currently-active
  map — a profile that moves when a designer flips the active map is not a
  baseline), at a late-round enemy count, at zoom 1.0 and at the maximum zoom
  level, plus one large-map case.
- Process RSS with the asset store warm, and the count of loaded sheet Surfaces
  (the duplicate-decode number this plan claims to fix).

**Tests**: none — this phase changes no shipped behaviour. `tools/smoke.py` must
still pass, and `game/main.py` must be left with the instrumentation off by
default.

**Exit gate**: a measurement table plus a one-paragraph verdict written into this
document, naming the dominant cost. **If the dominant cost is not blit
throughput, stop and re-scope Part A with the user before G1.** Every later
phase states its target against these numbers.

#### G0 RESULTS (measured 2026-08-12, `phase-G1-umbrella`)

Harness: `tools/profile_render.py` (new, committed — deterministic: fixed map
file, seeded sprite placement, fixed serpentine pan, 300 measured frames after
30 discarded warm-up frames). Machine: pygame-ce 2.5.7 / SDL 2.32.10, Python
3.13.2, Windows 11, real `pygame.SCALED` window at `display.json`'s size.

**`game/main.py` was NOT modified.** The per-frame timing split this phase was
scoped to add **already exists** (`game/main.py:1690-1704`, documented as the
"Frame-timing HUD" in `game/PERF.md:154-157`): windowed runs already print
`sim/submit/flush/flip` mean ms beside the fps line, gated on `tune_gc` so
headless stays silent. Widening it was judged unnecessary once the harness
isolated the answer, and leaving the host untouched is strictly safer. The one
split the existing instrumentation cannot make is HUD-draw vs world-draw (both
land inside its `flush` bucket) — see the caveat below.

All times in **ms, mean / p95 per frame.** `ground` = `GroundCache.ensure` +
`blit`; `submit` = tile emit + `Renderer.submit`; `flush` = `Renderer.flush`
(the backend's blits); `flip` = `display.flip` (the SCALED upscale).

| Map | Zoom | Camera | Sprites | ground | submit | **flush** | flip | frame | fps |
|---|---|---|---|---|---|---|---|---|---|
| first_light 20² | 1.0 | static | 160 | 0.20 / 0.33 | 0.07 / 0.10 | **10.56 / 14.34** | 0.82 / 1.03 | 11.65 / 15.56 | 86 |
| first_light 20² | 1.0 | panning | 160 | 0.59 / 0.95 | 0.05 / 0.07 | **10.07 / 12.92** | 0.61 / 0.77 | 11.32 / 14.33 | 88 |
| first_light 20² | 2.0 | static | 160 | 0.19 / 0.30 | 0.06 / 0.08 | **7.08 / 7.94** | 0.59 / 0.78 | 7.91 / 8.90 | 126 |
| first_light 20² | 2.0 | panning | 160 | 1.25 / 1.55 | 0.05 / 0.07 | **9.74 / 12.45** | 0.59 / 0.76 | 11.64 / 14.60 | 86 |
| first_light 20² | 1.0 | static | 1016 | 0.20 / 0.33 | 0.23 / 0.40 | **63.02 / 101.03** | 0.87 / 1.22 | 64.32 / 103.51 | 15.5 |
| first_light 20² | 1.0 | panning | 1016 | 0.66 / 1.06 | 0.21 / 0.33 | **61.09 / 71.84** | 0.81 / 1.05 | 62.76 / 73.43 | 15.9 |
| first_light 20² | 2.0 | static | 1016 | 0.24 / 0.53 | 0.31 / 0.93 | **79.87 / 199.01** | 1.12 / 2.53 | 81.54 / 201.08 | 12.3 |
| first_light 20² | 2.0 | panning | 1016 | 1.59 / 3.22 | 0.27 / 0.57 | **80.95 / 124.49** | 0.98 / 1.48 | 83.79 / 129.01 | 11.9 |
| holex 1024² | 1.0 | static | 1016 | 0.21 / 0.32 | 0.24 / 0.40 | **14.72 / 19.45** | 0.91 / 1.39 | 16.08 / 21.51 | 62 |
| holex 1024² | 1.0 | panning | 1016 | 2.68 / 4.80 | 0.24 / 0.56 | **13.51 / 17.40** | 0.83 / 1.21 | 17.27 / 23.94 | 58 |
| holex 1024² | 2.0 | static | 1016 | 0.22 / 0.35 | 0.28 / 0.51 | **17.66 / 25.73** | 1.06 / 1.82 | 19.23 / 27.66 | 52 |
| holex 1024² | 2.0 | panning | 1016 | 5.02 / 10.64 | 0.75 / 1.46 | **33.44 / 65.33** | 1.86 / 3.80 | 41.06 / 76.25 | 24 |

The 1016-sprite cases are the **era-4 boss round** — `data/balancing/
enemies.json`'s `EnemyTypes.Boss.round_counts` era 4 spawns 976 enemies
(215 raiders + 700 regular + 61 siege); era 2 is 436. The 160-sprite cases are
a mid-game reference. `first_light` (20×20) is the worst case *because* it is
small: every sprite is on screen. On `holex` (1024²) the same 1016 sprites
scatter far beyond the viewport, which is why its `flush` is 4× cheaper — that
column is measuring how many sprites actually land on screen, not map size.

**Asset store, warm** (`py tools/profile_render.py --warm-store`, every one of
the 278 manifest slots resolved):

| Metric | Value |
|---|---|
| Manifest entries | 278 |
| Sheet Surfaces held | 274 |
| Distinct source PNGs | 194 |
| **Duplicate Surfaces** | **80** |
| Sheet pixel memory | 94.7 MB |
| **Of which duplicate decode** | **58.3 MB (62%)** |
| Process RSS, cold → warm | 83 MB → 179 MB |

**Verdict: the dominant cost IS blit throughput, and Part A proceeds
unchanged.** `Renderer.flush` is **84–97% of every frame measured**, in every
map / zoom / camera combination — 61–81 ms of a 63–84 ms frame at the era-4
boss load, which is 12–16 fps and exactly the frame-rate complaint that
motivated this plan. The three alternative hypotheses D9 named are all
measured and all dead: per-frame Python in the submit loop is **0.05–0.75 ms**
(under 1% of a frame, and it barely grows from 160 to 1016 sprites, so the
depth sort and `DrawCall` construction are not the problem); `display.flip`'s
SCALED upscale is **0.6–1.9 ms**; and the ground cache is **0.2–5.0 ms**, real
but second-order — its cost tracks pan speed and map size exactly as
`game/PERF.md` claims, peaking at 5.02 / 10.64 ms only in the 1024²-panning-
at-max-zoom corner. So G2's Texture backend targets the one bucket that
matters, and G3's ground-cache port is correctly ordered *after* it and
correctly scoped as a smaller win. Independently, the warm-store table gives
**M2 its own hard justification**: 80 of 274 sheet Surfaces are duplicate
decodes of a PNG another slot already loaded, costing **58.3 MB** — 62% of all
sheet pixel memory — before a single master sheet exists, and that number only
grows once ten slots share one master PNG.

**Two honest caveats on these numbers.**
1. **The harness measures the render stack, not a live `Session`.** It builds
   the same map doc / `AssetStore` / `Renderer` / `GroundCache` / SCALED window
   `game/main.py` builds, then drives a fixed sprite population instead of real
   `Enemy` objects — deliberate, because a fixed population is the only way two
   runs compare, and a sprite's blit cost does not depend on what produced its
   `RenderItem`. Simulation cost is therefore **not** in this table;
   `game/main.py`'s own `sim` bucket measures that on real hardware.
2. **The HUD pass is not broken out.** Its submit lands in the harness's
   `submit` bucket only for world items, and in the real host its draw is
   inside `flush` — no instrumentation separates HUD-draw from world-draw
   today. The HUD is a few dozen items a frame against 1016 world sprites, so
   it cannot plausibly be the dominant cost, but that is **inferred, not
   measured**, and it is the one number a live late-round `py game/main.py`
   run should confirm before G4 re-takes these measurements.

### Phase G1 — Backend seam + feasibility probe

**Goal**: make the backend choice explicit (it is currently a lazy import inside
`flush()`), and answer the one unverified environment question before committing
to G2's shape. **Zero behavioural change.**

**Files** — new: `engine/render/backend_api.py` (the contract a backend must
satisfy: what `draw(target, draw_calls)` accepts and must honour — scaling,
`flip`, `tint`, `slice`, `crop_rect`, `OverlayLines`, `OverlayPolys`, and the
HUD isinstance branches; pure, no pygame). Modified: `engine/render/renderer.py`
(explicit backend resolution alongside the existing injectable `backend=None`),
`engine/render/__init__.py`, `engine/render/CLAUDE.md`.

**The probe** (throwaway script, not committed): under `SDL_VIDEODRIVER=dummy`,
attempt `pygame._sdl2.video.Window` + `Renderer` + one `Texture` upload +
`to_surface()` readback. Record the result in this doc under §4. It decides
whether G2's parity test can run in CI or must be marked as a live-only check.

**Tests**: the existing `tools/tests/test_render*.py` suite passes byte-identical
— this phase must not move a pixel. Add one test asserting the default backend
resolution is unchanged when nothing is injected.

**Exit gate**: `py -m pytest tools/tests/test_render.py tools/tests/test_ground_cache.py -x -q`
green, `py tools/smoke.py` green, probe result recorded in §4.

### Phase G2 — `backend_gpu.py`: world sprites

**Goal**: a Texture-based backend that draws the sprite + overlay half of a
`DrawCall` list at parity with `backend.py`.

**Files** — new: `engine/render/backend_gpu.py`,
`tools/tests/test_render_backend_parity.py`. Modified:
`engine/CLAUDE.md` (the pygame-import allow-list gains this module — it is the
second and only other place in `engine/render` allowed to touch pygame's SDL2
layer), `engine/render/CLAUDE.md`, `conftest.py` (`TIERS` entry for the new test
module — an unmarked module silently never runs).

**Design notes**
- Texture cache keyed by **source Surface identity** in a `WeakKeyDictionary`,
  mirroring `backend.py`'s `_scale_cache` — so each `AssetStore` sheet Surface
  uploads exactly once and the grey-X placeholder (a fresh surface per call)
  never leaks. This is where "textures from one file upload once" is delivered;
  it composes with M2, after which one *file* is one Surface is one Texture.
- Sprite `DrawCall` → `Renderer.blit`: the dest rect carries the scale (no CPU
  `transform.scale` at all), `flip_x`/`flip_y` are native, `tint` becomes
  `texture.color` / `texture.alpha`.
- `OverlayLines` / `OverlayPolys` via `draw_line` / `draw_quad`, or a CPU-drawn
  scratch texture where that is what matches pixel output — decide by the parity
  test, and state which was chosen and why.
- **`slice` and `crop_rect` are HUD-only** and therefore never reach this
  backend on the world path; assert that rather than implementing them twice.
- The pixel quantizer (`item.round_half_up`) still governs dests and sizes —
  do not let SDL's own rounding substitute for it.

**Tests**: `test_render_backend_parity.py` renders a fixture scene (several
sprites at zoom ≠ 1, a flip, a tint, an overlay polyline, a filled poly) through
both backends and compares within a **pinned per-channel tolerance**, with a
comment stating why the tolerance is not zero (SDL's scaler is not guaranteed
bit-identical to `pygame.transform.scale`). Plus a test that the texture cache
yields one texture per source surface across many draws, and that a GC'd surface
evicts its texture.

**Exit gate**: parity test green within tolerance; existing render tests
untouched and green; if the G1 probe said the dummy driver cannot host a
Renderer, the parity test is marked live-only and the phase report says so
explicitly.

#### G2 RESULTS (measured 2026-08-12, `phase-G2-umbrella`)

`engine/render/backend_gpu.py` + `tools/tests/test_render_backend_parity.py`,
plus one `conftest.py` `TIERS` line (`"test_render_backend_parity": "core"` —
it runs in normal CI, not live-only, per §4's probe) and the two doc edits.
`backend.py`, `backend_api.py`, `renderer.py`, `__init__.py` and
`ground_cache.py` are untouched: **nothing selects this backend**,
`default_backend()` still returns the Surface blitter, and G4 wires the host.

**Three plan statements this phase corrected** — the source won each time:
1. **There is no `flip_y`.** `DrawCall` carries a single horizontal `flip: bool`
   (`item.py:44`, `backend_api.py:40`). The backend passes
   `flip_x=call.flip, flip_y=False`; no field was added to `DrawCall`.
2. **`Renderer.blit` cannot carry the sprite draw** — measured on pygame-ce
   2.5.7, its signature is `blit(source, dest=None, area=None,
   special_flags=0)` with no flip parameters and a docstring saying
   `special_flags` "have no effect at this moment". The path is
   `Texture.draw(srcrect, dstrect, angle, origin, flip_x, flip_y)`.
3. **`tint` → `texture.color`/`texture.alpha` leaks without a reset.** The
   Surface path's `surface.copy()` (`backend.py:223`) is what stops the shared
   source being mutated; modulation is persistent state on a *cached, shared*
   Texture, so the backend sets and resets it inside one `try/finally` that
   opens before the first assignment. Pinned by a tinted-then-untinted draw
   from the same source surface.

**Overlays are CPU-rasterized into a scratch Surface and uploaded per call**,
for both `OverlayLines` and `OverlayPolys` — no native/scratch split.
Measured: SDL's `Renderer.draw_line(p1, p2)` takes no width, while
`OverlayLines.width` is an arbitrary int (`item.py:57`), and no native
primitive covers `OverlayPolys`' arbitrary-length polygon with optional alpha.
Rasterizing through the *same* `pygame.draw` calls is parity-exact by
construction instead of requiring two rasterizers to agree forever. The cost
of that choice is recorded as a G4 risk in §9 — it is unmeasured.

**Texture cache**: outer key is the source Surface in a `WeakKeyDictionary`
(mirroring `backend.py`'s `_scale_cache`, so the grey-X placeholder's
fresh-surface-per-call never leaks a texture); inner key is `id(renderer)`,
because **pygame-ce 2.5.7's `Renderer` is not weak-referenceable** — measured,
`weakref.ref` raises `TypeError` (same for `Texture`). Id reuse cannot mix
renderers up: a cached `Texture` holds a strong reference to its `Renderer`, so
while any entry keyed `id(R)` lives, `R` lives. `clear_cache()` is exported.

**Nearest sampling is pinned in code, not inherited.** Textures are built as
`Texture(renderer, size, scale_quality=SCALEQUALITY_NEAREST)` + `update()`
rather than `Texture.from_surface`, because `from_surface` takes no
`scale_quality` and the filter would then come from
`SDL_HINT_RENDER_SCALE_QUALITY` — default nearest, but overridable process-wide
by the `SDL_RENDER_SCALE_QUALITY` env var. Pixel art is the aesthetic; the
filter is not something to inherit. That switch surfaced a real trap: **the
empty-texture constructor leaves `blend_mode` at `0` (`BLENDMODE_NONE`)** where
`from_surface` returned `1` (`BLENDMODE_BLEND`), so the explicit `blend_mode`
assignment became load-bearing — without it every sprite would have drawn with
alpha ignored.

**Parity, measured under `SDL_VIDEODRIVER=dummy`** (200×160 fixture: a 1:1
sprite, a `.5`-tie dest *and* size, a flipped sprite, a tinted sprite followed
by an untinted one from the same source, a width-3 open polyline, a width-2
closed polyline, an opaque triangle, an alpha-100 quad):

| Metric | Value |
|---|---|
| Max per-channel \|CPU − GPU\| | **1** |
| Differing pixels | 1234 / 32000 (3.86%) |
| Delta histogram | `{1: 1234}` |
| Where they are | **all** inside the alpha < 255 `OverlayPolys` |
| Scaled / flipped / tinted sprites | **byte-identical** |

`CHANNEL_TOLERANCE = 1`, a named module constant with a comment recording
exactly the above. **No blur finding**: the delta is one-ULP alpha-blend
rounding, not resampling, and an 8×8 → 21×21 GPU draw compared to
`pygame.transform.scale(s, (21, 21))` gave **0** mismatching pixels.

**The flip × non-integer-scale question was raised in review and is retired,
measured 0.** The two paths compose flip and resample in opposite orders —
`backend.py:219-221` scales *then* mirrors; the GPU path hands SDL an unscaled
texture and asks it to resample a *mirrored* read — which are provably equal
only at integer factors (`(kS−1−i)//k == S−1−i//k`), so the original test's
exact-×2 flipped sprite could not have seen a divergence. Re-measured on a
fixture with an asymmetric leftmost column (so a one-column mirror error is
unmissable), at factors 1.125 / 1.5 / 1.625 / 2.0 / 2.5625 / 2.625 / 3.8125:
**max delta 0, 0 differing pixels at every factor.** Byte-identical, not
merely within tolerance. Seven sampled factors is strong evidence, not a proof
of the general S→D case.

**G2 moved no fps number and could not have** — no host calls this backend.
G0's measurements (`flush` at 84–97% of frame; 61–81 ms of a 63–84 ms frame at
the era-4 boss load, 12–16 fps) are **G4's to re-take**.

**Still open — the live look was NOT run.** The brief's Quick Test (a real
non-dummy window, a real sheet from `data/sprites/imported/`, a saved CPU/GPU
PNG pair compared at 1:1 and magnified) needs a human at a display; every
number above comes from the dummy driver in one environment. It is the only
check that would independently catch a sampling-quality regression, and it
carries forward to G4's live gate.

### Phase G3 — Ground cache on the GPU path

**Goal**: the ground layer's scroll-and-fill technique, on textures, behind the
same public signature.

**Files** — new: `engine/render/ground_cache_gpu.py` (or a variant class inside
`ground_cache.py` — implementer's call, stated in the report). Modified:
`engine/render/ground_cache.py` (only if the variant lands there),
`engine/render/CLAUDE.md`, `tools/tests/test_ground_cache.py`.

**Design notes**
- Same `ensure(view_w, view_h, ground_items_fn)` signature, so every caller is
  untouched and the content-agnostic callback contract holds. **Corrected in
  G3 (verified): "both callers (game and editor)" was wrong — the editor never
  uses `GroundCache` at all**, it submits ground tiles directly
  (`editor/panels/viewport.py:1816-1818`). The real callers are `game/main.py`
  (`:339`, `:432-433`, `:1503-1508`), `tools/profile_render.py` (`:194`,
  `:263-264`) and the test module.
- The `Surface.scroll` memmove becomes a **self-blit between two render-target
  textures** — SDL cannot read and write one target in a single pass — then the
  newly-exposed strip is repainted.
- **Reuse the diagonal-band derivation verbatim.** A thin *screen* strip is a
  *diagonal* in tile space; the `d = col−row`, `s = col+row` band addressing
  through `tilemap.band_render_items` is the subtle, already-correct part, and
  restating it is how this regresses. Only the surface/texture mechanics change.
- The `depth_key` layer-primary invariant is what makes caching the ground layer
  legal at all — say so in the new module's docstring, do not leave it implied.
- The anchor technique (a private `CoordinateSystem` at
  `pan = anchor_pan − margin`, integer scroll with the sub-pixel remainder riding
  the blit's float dest) must be preserved exactly; it is what keeps the cache
  rounding-exact against a direct render.

**Tests**: run the existing rounding-exactness pins (successive scroll steps stay
pixel-aligned vs a direct render) against the GPU variant too, parameterised over
both implementations rather than copy-pasted.

**Exit gate**: both variants pass the same pin suite; a live look at panning a
large map in `py game/main.py` with no seams or stutter — state that it was a
live run, not a reasoned claim.

#### G3 RESULTS (measured 2026-08-12, `phase-G3-umbrella`)

`engine/render/ground_cache_gpu.py` (new, `GroundCacheGpu`), the shared
`band_for_rect(...)` extraction in `ground_cache.py`, both doc edits, and
`tools/tests/test_ground_cache.py` reworked so the existing pins run against
**both** implementations. `conftest.py` needed no `TIERS` line —
`"test_ground_cache": "core"` already existed and the GPU class lives in that
same module. `backend_gpu.py`, `backend.py`, `backend_api.py`, `renderer.py`,
`__init__.py`, `item.py` and `game/**` are untouched: **nothing selects this
either**, `default_backend()` still returns the Surface blitter, and G4 wires
the host.

**New module, not a variant class** (the choice §6/G3 left to the implementer).
The decisive criterion is import cost: a module-level `pygame._sdl2.video`
import inside `ground_cache.py` would make every importer of the *Surface*
path — the game host, `tools/profile_render.py`, the tests — depend on the SDL2
layer loading. Its only real cost, duplicating the band derivation, is removed
by extracting `ground_cache.py:137-145` into a pure module-level
`band_for_rect(...)` that both `_paint` implementations call. That extraction is
the whole of the `ground_cache.py` diff (32 lines, behaviour-preserving).

**Three SDL facts measured on pygame-ce 2.5.7 / SDL 2.32.10, not assumed.**
A render target is `Texture(renderer, size, target=True,
scale_quality=SCALEQUALITY_NEAREST)` with `renderer.target = tex / None`;
readback is `renderer.to_surface()` (**`Texture` has no `to_surface`**). Two
traps that would each have produced a subtly wrong ground layer:
1. **`set_viewport` clips *and translates*** — a fill at `(0, 0)` inside a
   viewport at `(12, 12)` lands at `(12, 12)`. The anchor technique survives it
   because the translation is compensated by shifting the private camera pan by
   integer `+(x0, y0)`, and `floor(v + k + 0.5) == floor(v + 0.5) + k` for
   integer `k` keeps that rounding-exact.
2. **`clear()` ignores the viewport and wipes the whole target** — so the strip
   background is `fill_rect`, never `clear()`. The viewport also resets on every
   target switch, and a `target=True` texture's `blend_mode` is
   `BLENDMODE_NONE`.

**Parity is NOT byte-exact; `GPU_CHANNEL_TOLERANCE = 2`** (G2's backend pin is
1). Measured against a from-scratch direct render: zoom 1 max delta 1 over
38100/76800 px; zoom 2 max delta 1 over 47585/76800 px; map edge max delta 1
over 25965/76800 px; 11 scroll steps across both scroll pins max delta 1
throughout; and the **tint (editor) path max delta 2**, histogram
`{1: 35795, 2: 7338}` — the only scenario reaching 2, i.e. tint modulation
compounding on the same alpha-blend rounding G2 already pinned. The ~50%
differing-pixel fraction is geometric, not alarming: the fixture ships **no
sprite PNGs**, so every ground tile falls back to the grey-X placeholder, whose
fill is `(110, 110, 110, 200)` — per-pixel alpha — across the whole tile
rectangle, so about half of all on-screen ground pixels pass through an alpha
blend on every draw.

**The tolerance was negative-controlled, not trusted** (measured by the
orchestrator, not the implementer). The live question was whether a ±2
per-channel tolerance could mask a one-pixel *spatial* shift — the failure the
scroll pins exist to catch. Injecting `+1` on the blit dest's x made the pins
fail at **max per-channel delta 140**, 70× the tolerance, failing 7 of the 11
GPU tests including both scroll pins and `test_blit_offset_sign`. The
placeholder's opaque border and cross lines are what make a misalignment
unmissable. The perturbation was reverted; the tree is byte-identical.

**Tests**: the pins moved into a mixin (`_make_cache`, `_blit_to_surface`,
`_capture_blit_dest`, `CHANNEL_TOLERANCE` are the only seams the two subclasses
supply), so the CPU and GPU classes cannot drift apart — collection went **8 →
18**, all green, no skips (the GPU class builds a real `Window`/`Renderer`
unconditionally under the dummy driver). Two GPU-only mechanics tests: target
and viewport are restored after `ensure`, after `blit` and after a scroll; and
the two render-target textures are distinct objects whose identities actually
swap across a scrolling `ensure`.

**G3 moved no fps number and could not have** — no host calls it. Its honest
ceiling is G0's measured ground-cache cost of **0.2–5.0 ms mean / 10.64 ms
p95**, real but second-order against `flush` at 84–97% of frame, and only in
the 1024²-panning-at-max-zoom corner. G4 re-takes the measurements.

**`WorldFill` (PR #122) changes nothing here** (verified): every
`submit_world_fill` caller uses the `layer="entities"` default
(`game/ui/widgets.py:294,306`); `layer="ground"` appears only in
`engine/tilemap.py:286,328,384`; and the cache's private `Renderer` can only
ever see `band_render_items` output.

**Still open — the live look, and this phase could not have run it even with a
human present.** `default_backend()` is still the Surface blitter, so a
`py game/main.py` pan would exercise the *Surface* cache and prove only that the
`band_for_rect` extraction is a no-op. Exercising `GroundCacheGpu` live needs
either a throwaway harness at a real display or G4's wiring. It carries forward
into G4's live gate alongside G2's outstanding pixel-art look.

### Phase G4 — Host wiring, HUD composite, fallback

**Goal**: the game actually runs on the GPU path, degrades cleanly when it
cannot, and the G0 numbers are re-taken.

**Files** — modified: `game/main.py` (backend request + fallback + one log
line), `engine/render/renderer.py`, `engine/render/CLAUDE.md`,
`engine/CLAUDE.md`, `tools/tests/test_render_backend_parity.py` (fallback path).

**Design notes**
- Any failure creating the window, renderer, or a texture logs one line and
  falls back to `backend.draw` (D8). The fallback must be reachable by a test
  that forces it, not only by a broken machine.
- **HUD composite**: draw the HUD pass into one screen-sized Surface exactly as
  today, upload it as a single streaming texture, draw it over the GPU frame.
  One upload per frame; fonts, nine-slice and crop keep their existing,
  well-tested code (D7).
- `editor/` is untouched by Part A. It keeps the Surface backend and its
  module-level `SDL_VIDEODRIVER=dummy` rule — that rule is precisely why D6 is
  a dual backend.
- `tools/smoke.py` stays on the Surface path.

**Tests**: a forced-fallback test (monkeypatch the renderer construction to
raise) asserting the game still produces frames; the parity suite still green.

**Exit gate**: `py tools/smoke.py`; a **live** `py game/main.py` confirming from
the log line that the GPU path is in use, then a second live run with the
fallback forced, confirming identical-looking output; G0's measurements re-taken
and written into this doc beside the originals. State which checks were live.

#### G4 RESULTS (2026-08-13)

`game/main.py` (the presenter seam), `engine/render/renderer.py`
(`hud_target` + `last_flush_ms`), `tools/profile_render.py` (both backends +
the overlay pass), the three doc edits, and pins in `test_render.py` /
`test_game_boot.py`. Two commits: `9200acd` (host wiring) and `9f2ef19` (the
harness + re-measure). **`backend_gpu.py`, `ground_cache_gpu.py`, `backend.py`,
`backend_api.py`, `editor/**`, `tools/smoke.py` and `data/**` are untouched**,
and `default_backend()` still returns the Surface blitter — the GPU path is
selected by the host alone.

**The port is now reachable**: `py game/main.py --backend={gpu,surface,auto}`,
env `HTBH_RENDER_BACKEND` when the flag is absent, `SystemExit` on an
unrecognised value. Default is `auto` for a windowed run and **forced
`surface` whenever `max_frames is not None`** — the existing headless seam, so
`tools/smoke.py` stays on the Surface path **with no edit to it** (confirmed
from its own boot line: `render backend: Surface (CPU blitter) | window 640x360
SCALED | ground cache: GroundCache`).

**All numbers below are the SOFTWARE renderer** (`SDL_VIDEODRIVER=dummy`,
pygame-ce 2.5.7 / SDL 2.32.10, Python 3.13.2, Windows 11). The driver string in
the boot log reads `direct3d` but is `get_drivers()[0]`, **not** a readback of
the renderer actually created — `Renderer.get_renderer_info` is gone in 2.5.7.
**No hardware re-measure has been taken**, and none of §4.3's live checks have
been run. Treat every GPU number as pending.

`world` = `Renderer.flush` minus the HUD backend call, i.e. exactly G0's
`flush` column, so the two tables compare directly. `ovlΔ` = `world(40) −
world(0)` over the identical deterministic frame sequence. 30 warm-up + 300
measured frames.

| Map | Zoom | Camera | Sprites | Backend | ground | submit | world | ovlΔ | hud | composite | present | frame | fps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| first_light 20² | 1.0 | static | 1016 | surface | 0.19 | 0.30 | **61.46** | 5.24 | 0.00 | 0.00 | 0.33 | 62.29 | 16.1 |
| first_light 20² | 1.0 | static | 1016 | **gpu** | 0.04 | 0.25 | **9.53** | 0.96 | 0.00 | 0.11 | 2.22 | **12.16** | **82.3** |
| first_light 20² | 1.0 | panning | 1016 | surface | 0.68 | 0.29 | **68.78** | 2.14 | 0.00 | 0.00 | 0.34 | 70.09 | 14.3 |
| first_light 20² | 1.0 | panning | 1016 | **gpu** | 0.86 | 0.29 | **11.47** | 2.61 | 0.00 | 0.13 | 2.63 | **15.37** | **65.1** |
| first_light 20² | 2.0 | static | 1016 | surface | 0.19 | 0.29 | **53.19** | 2.34 | 0.00 | 0.00 | 0.31 | 53.98 | 18.5 |
| first_light 20² | 2.0 | static | 1016 | **gpu** | 0.06 | 0.29 | **10.96** | 2.09 | 0.00 | 0.12 | 14.95 | **26.38** | **37.9** |
| first_light 20² | 2.0 | panning | 1016 | surface | 1.39 | 0.26 | **68.87** | 0.82 | 0.00 | 0.00 | 0.32 | 70.84 | 14.1 |
| first_light 20² | 2.0 | panning | 1016 | **gpu** | 1.73 | 0.27 | **11.10** | 2.13 | 0.00 | 0.12 | 17.64 | **30.86** | **32.4** |
| holex 1024² | 1.0 | panning | 1016 | surface | 2.18 | 0.24 | 9.16 | 0.53 | 0.00 | 0.00 | 0.30 | **11.88** | **84.2** |
| holex 1024² | 1.0 | panning | 1016 | gpu | 2.40 | 0.25 | 10.31 | 1.41 | 0.00 | 0.11 | 0.41 | **13.49** | 74.1 |
| holex 1024² | 2.0 | panning | 1016 | surface | 1.37 | 0.23 | 9.29 | 0.86 | 0.00 | 0.00 | 0.29 | **11.19** | **89.4** |
| holex 1024² | 2.0 | panning | 1016 | gpu | 1.88 | 0.25 | 10.70 | 1.54 | 0.00 | 0.11 | 0.41 | **13.35** | 74.9 |
| first_light 20² | 1.0 | static | 160 | surface | 0.16 | 0.12 | 10.43 | 0.79 | 0.00 | 0.00 | 0.29 | 11.00 | 90.9 |
| first_light 20² | 1.0 | static | 160 | gpu | 0.04 | 0.10 | 2.44 | 1.16 | 0.00 | 0.11 | 0.74 | 3.43 | 291.3 |
| first_light 20² | 1.0 | panning | 160 | surface | 0.59 | 0.11 | 10.67 | 0.32 | 0.00 | 0.00 | 0.29 | 11.65 | 85.8 |
| first_light 20² | 1.0 | panning | 160 | gpu | 0.72 | 0.11 | 2.57 | 1.27 | 0.00 | 0.11 | 0.70 | 4.22 | 237.2 |
| first_light 20² | 2.0 | static | 160 | surface | 0.15 | 0.11 | 7.56 | 0.73 | 0.00 | 0.00 | 0.28 | 8.11 | 123.4 |
| first_light 20² | 2.0 | static | 160 | gpu | 0.04 | 0.11 | 2.93 | 1.60 | 0.00 | 0.11 | 2.17 | 5.36 | 186.6 |
| first_light 20² | 2.0 | panning | 160 | surface | 1.19 | 0.11 | 10.57 | 1.05 | 0.00 | 0.00 | 0.30 | 12.17 | 82.2 |
| first_light 20² | 2.0 | panning | 160 | gpu | 1.58 | 0.11 | 3.05 | 1.70 | 0.00 | 0.11 | 2.80 | 7.66 | 130.6 |
| holex 1024² | 1.0 | panning | 160 | surface | 2.14 | 0.10 | 1.97 | 0.64 | 0.00 | 0.00 | 0.29 | **4.51** | **221.7** |
| holex 1024² | 1.0 | panning | 160 | gpu | 2.25 | 0.11 | 2.44 | 1.09 | 0.00 | 0.11 | 0.38 | **5.28** | 189.3 |
| holex 1024² | 2.0 | panning | 160 | surface | 1.46 | 0.11 | 2.16 | 0.90 | 0.00 | 0.00 | 0.30 | **4.03** | **248.0** |
| holex 1024² | 2.0 | panning | 160 | gpu | 1.81 | 0.11 | 2.95 | 1.65 | 0.00 | 0.11 | 0.39 | **5.37** | 186.2 |

**Verdict — the boss-load win is real, and it is not the whole story.** At the
era-4 boss load on `first_light` the `world` bucket drops **61–69 ms → 9.5–11.5
ms (5–7×)**, moving the frame from 54–71 ms to 12–31 ms. That is the number G4
existed to move and it moved. But three findings cut against a clean win:

1. **The GPU path is SLOWER on every `holex` row** — 11.88→13.49, 11.19→13.35,
   4.51→5.28, 4.03→5.37 ms. On a map where few sprites land on screen the CPU
   blitter is already cheap and the GPU path pays fixed per-frame costs. The
   ground bucket is also consistently *worse* on GPU when panning (0.68→0.86,
   1.39→1.73, 2.18→2.40) — G3's cache is not free on this driver.
2. **`present` is load-dependent and not free**: 0.41 ms on holex but **14.95 /
   17.64 ms** on first_light at zoom 2.0. The software renderer defers sprite
   composition to `present()`, so on THIS driver the honest GPU cost is
   `world + present`. This is the single number most likely to collapse on real
   hardware, and it is why no verdict here is final.
3. **The overlay pass is the predicted regression, and it is worse than
   predicted** (below).

**Overlay Δ — measured in isolation** (first_light 20², 160 sprites, zoom 1.0,
static, 300 frames; the `ovlΔ` column in the sweep above is inside run-to-run
variance at the 60–70 ms boss load — trust these, not that column):

| overlays | surface Δ ms/frame | gpu Δ ms/frame | ratio |
|---|---|---|---|
| 40 diamonds | 0.72 | **4.31** | **6.0× worse on gpu** |
| 200 diamonds | 9.30 | **17.50** | **1.9× worse on gpu** |

Each diamond is one `OverlayPolys` + one `OverlayLines`, so 40 diamonds = 80
uncached bounding-box SRCALPHA scratch surfaces created, rasterized and
uploaded **per frame** (`backend_gpu.py:110-156`). Since PR #122 routes every
tile highlight and wall segment through `WorldFill` → that path, this is a
live-gameplay cost, not synthetic. §9's prediction was correct.

**The pathological far-off-screen polyline** — ONE `submit_overlay_lines` with
its second point 50 tiles off-screen. Screen bbox **1603 × 803 px = 4.9 MB
SRCALPHA**, allocated + rasterized + uploaded fresh every frame on the GPU
path. Δ per frame: **surface 6.47 ms, gpu 10.66 ms**. Both are bad — the
Surface backend rasterizes the whole clipped line too — with the GPU path 1.65×
worse plus 4.9 MB of churn. **Not fine.** A real hazard if any gameplay code
ever submits a world-space line with an off-screen endpoint.

**The HUD's cost is STILL NOT MEASURED.** `hud` reads 0.00 in every row because
`tools/profile_render.py` is a render harness and submits no HUD items. G0's
one *inferred* claim — that the HUD is not the dominant cost — is therefore
**not retired**. The instrument that retires it exists and shipped
(`renderer.last_flush_ms`, surfaced in the frame-timing line as `sim | submit |
world | hud | composite | present`); it needs a live late round to read it.
That is §4.3 Step 6 and it is owed.

**Tests**: `test_render.py` gains the `hud_target` split pins (single flat list
when `hud_target is None`; world/HUD separation by production site; no
`slice`/`crop_rect` reaching the world backend) plus a `--backend`/`--overlays`
CLI pin; `test_game_boot.py` gains GPU boot, forced fallback, and the
HUD-freeze pin — which drives 5 frames and asserts `update()` was called 5
times, not once, and is the only test that would catch the §1.3 snapshot bug.

**Review of `9200acd`** found no severity-1 defects. The three ranked traps all
PASS: the HUD-freeze pin is per-frame; the world/HUD split is structural
(`renderer.py:240` aliases the same list when `hud_target is None`, no
`isinstance` filter); and the coder's one unbriefed change — `blit_fullscreen`
also clearing the HUD surface — is **correct and necessary**, since the Surface
path's opaque full-window blit covers world *and* HUD, so without the clear the
GPU composite would paint the previous frame's stale HUD back over every
cutscene frame. The brief missed this case. Also corrected: the brief claimed
nothing reads `event.rel`; `game/main.py:1499` does
(`cs.pan(-event.rel[0], -event.rel[1])`), and `map_event` maps it by
differencing two `coordinates_from_window` points — exact under an affine
remap.

**THE LIVE CHECKS RAN, AND THEY PASSED** (user-run at a display, 2026-08-13).
G4 is the phase that stops saying "the live look was NOT run". All of §4.3
passed: the GPU path boots and announces itself; pixel-art edges are equally
hard on both backends at full zoom (**G2's outstanding check, closed**); the
1024² `holex` pan shows no seam, no leading-edge flash, no grid jitter and no
drift on stop (**G3's outstanding check, closed**); the HUD updates every frame
and the building panel changes per tile (**the §1.3 snapshot trap did not
fire**); and fullscreen clicks land on the tile clicked (**§2.6's remap is
correct on real hardware**).

**One §4.3 finding worth recording, because it cost the user ten minutes and it
is not a bug.** The game boots into the intro cutscene (`game/main.py:665`),
and `:1349` swallows every input while it plays — skipping is a **two-second
hold**, not a click. On first launch this presents as "the main menu buttons do
nothing". Pre-existing behaviour on both backends, unrelated to G4, but the
first thing a live tester hits.

**Still open, and narrower than before**: the frame-timing numbers from §4.3
Step 6 were not captured, so `hud`/`composite` on real hardware are still
unknown and **G0's inferred claim that the HUD is not the dominant cost is
formally unretired** — the instrument ships and reading it is now a one-minute
job. Also unanswered: whether `target_texture=True` is strictly needed on this
driver (it was passed, and the path works), and streaming vs static texture on
hardware. **The overlay-pass regression measured above stands and needs a plan
decision** — an overlay clip in `backend_gpu.py` is the obvious fix and is
deliberately out of G4's scope.

### Phase G5 — Overlay pass: clip the scratch, reuse the buffer

**Goal**: kill the overlay regression G4 measured. This phase is **scheduled,
not deferred** — G4's own numbers make it a live Part-A decision, and §9 already
predicted it before it was measured.

**The measured problem** (§6/G4 RESULTS, "Overlay Δ — measured in isolation"):
`backend_gpu.py:110-156` rasterizes every `OverlayLines` / `OverlayPolys` into a
fresh bounding-box `SRCALPHA` scratch Surface and uploads it **per call, per
frame, uncached**. At 40 diamonds (80 overlay calls/frame) the pass costs
**4.31 ms on GPU vs 0.72 ms on Surface — 6.0× worse**; at 200 diamonds, 17.50
vs 9.30 ms (1.9×). Worse, the scratch is sized from the **raw point bounding
box with no clip to the target**, so the pathological far-off-screen polyline
(one point 50 tiles off-screen) allocates **1603 × 803 px = 4.9 MB** every
frame: **surface 6.47 ms, gpu 10.66 ms**. Since PR #122 routes every tile
highlight and wall segment through `WorldFill` → this path, it is a
live-gameplay cost, not synthetic.

**Files** — modified: `engine/render/backend_gpu.py`,
`tools/tests/test_render_backend_parity.py`, `engine/render/CLAUDE.md`,
`tools/profile_render.py` (re-measure only if the harness needs a new case).
**No other file.** `backend.py`, `backend_api.py`, `renderer.py`,
`ground_cache*.py`, `game/**`, `editor/**` and `data/**` are out of scope.

**Design notes**
- **Clip the scratch rect to the target bounds** before allocating. This is the
  bigger of the two wins and it is what `backend.py:190` already gets for free
  by drawing straight onto the target. The point coordinates must then be
  translated by the clipped origin, not the raw bbox origin — that translation
  is where this regresses into a one-pixel shift, so pin it.
- **Reuse the scratch Surface across calls** rather than allocating per call:
  one buffer per backend instance, grown to the high-water mark, `fill(0)`-ed
  per use — mirroring the `_scale_cache` / texture-cache precedent already in
  this module. A streaming texture updated in place beats create-and-destroy.
- **Parity is not negotiable.** `CHANNEL_TOLERANCE = 1` is pinned and §9 forbids
  nudging it. A clip that changes any on-screen pixel is a defect, not a
  tolerance question. Add a fixture whose overlay extends past every edge of the
  target (all four sides, and one wholly off-screen call that must draw nothing)
  and compare against `backend.py` at the existing tolerance.
- An overlay fully outside the target must become a **no-op**, not a zero-sized
  Surface — `pygame.Surface((0, 0))` and a zero-area texture are separate traps.

**Tests**: the existing parity suite green **unchanged** at tolerance 1; new
clipped-overlay parity cases (each edge, a corner, wholly off-screen); a test
that N overlay draws allocate ONE scratch Surface, not N (spy on the allocation
the way G2's texture-cache test counts uploads); a test that the buffer grows
and is not re-allocated when a smaller overlay follows a larger one.

**Exit gate**: `py tools/smoke.py` + `py -m pytest
tools/tests/test_render_backend_parity.py tools/tests/test_render.py -q`, plus a
**re-measure of the overlay Δ table above** through `tools/profile_render.py`
(40 and 200 diamonds, and the far-off-screen polyline) written into this doc
beside the originals. The phase succeeds when the GPU column is no longer a
multiple of the surface column; it does not need to *beat* the Surface path.

### Phase G6 — Retire G0's inferred HUD-cost claim

**Goal**: turn the plan's one surviving **inferred** performance claim into a
measured one. Nothing is implemented; this phase produces numbers.

**Why it is not an agent dispatch.** The instrument already shipped in G4
(`renderer.last_flush_ms`, surfaced in the frame-timing line as
`sim | submit | world | hud | composite | present`). What is missing is a
**live run at a real display, at a late round** — §4.3 Step 6. `tools/
profile_render.py` cannot supply it: it is a render harness that submits no HUD
items, which is exactly why `hud` reads 0.00 in every row of G4's table. No
headless agent can produce this number. **Run it as `/execute-phase` with the
user at a display** (§5.1's rule, the same one that scoped G0 and G4).

**The claim under test** (§6/G0, caveat 2): *"The HUD is a few dozen items a
frame against 1016 world sprites, so it cannot plausibly be the dominant cost —
but that is inferred, not measured."*

**What to capture**: from one live `py game/main.py` run on each backend,
carried to a late round (era 4 if reachable), read the frame-timing line and
record `hud` and `composite` as mean ms/frame beside `world` and `present`.
Also settles the two smaller unknowns G4 left open: whether
`target_texture=True` is strictly needed on this driver, and streaming vs
static texture on real hardware.

**Files** — modified: this plan doc only (the numbers, and the §9 bullet this
retires). If the run reveals the HUD *is* a significant cost, that is a
re-scope finding to bring to the user — D7 kept the HUD on the Surface path on
the strength of the claim this phase tests.

**Tests**: none — no shipped behaviour changes.

**Exit gate**: `hud` and `composite` recorded as measured numbers in §6/G4
RESULTS, the §9 bullet marked retired or the finding escalated, and an explicit
statement that it was a live run.

---

## 7. Part B — Master spritesheets

### Phase M1 — Data layer

**Goal**: the storage concept exists and validates. No engine or editor code.

**Files** — new: `data/schemas/master_sheets.schema.json`,
`data/sprites/master_sheets.json` (seeded `{"version": 1, "entries": {}}`),
`data/sprites/master/` (the folder; committed content like `imported/`, D-31 —
**never gitignore it**). Modified:
`data/schemas/asset_manifest.schema.json`, `data/CLAUDE.md`,
`tools/tests/test_assets_manifest.py`.

**Registry shape**

```json
{"version": 1,
 "entries": {"<sheet_id>": {"file": "master/<sheet_id>.png",
                            "display_name": "Characters",
                            "frame_w": 64, "frame_h": 96}}}
```

House style, no exceptions: `$id`, draft 2020-12, `additionalProperties: false`,
every key `required`, every property carrying a `description` documenting units,
every numeric carrying `minimum`/`maximum` (so the editor derives spinbox ranges
and out-of-range input is unrepresentable, ED-30). `sheet_id` pattern
`^[a-z][a-z0-9_]*$`, matching the slot-key convention.

**Two manifest schema changes**
1. **Widen the `sheet` pattern.** It is currently
   `^imported/[a-z][a-z0-9_]*\.png$`; it must also admit
   `^master/[a-z][a-z0-9_]*\.png$` (a two-branch pattern or an `enum`-free
   alternation — not `oneOf`, which the editor's form walker handles badly).
   Update the property's `description`: a sheet may live in either folder.
2. **Add optional `row_start`** (integer, `minimum: 0`, maximum matching the
   frame-count bounds already used elsewhere) — the FOURTH optional per-entry
   key after `slice`, `anchors`, `tint_overlay`. Omitted ⇒ 0.

**Smoke pairing**: `master_sheets.json` pairs with its schema by **normal stem**.
Confirm `tools/smoke.py::validate_data` needs **no** fourth directory exception
— it should not, and if it does, that is a finding to report rather than a
silent `if/elif` edit.

**Tests**: the seeded registry validates; a registry with a bad `file` path, a
bad id, or a missing `frame_w` is rejected; an existing manifest entry with no
`row_start` still validates; an entry with `sheet: "master/x.png"` validates; an
entry with a negative `row_start` is rejected.

**Exit gate**: `py tools/smoke.py` (now validating one more data file) +
`py -m pytest tools/tests/test_assets_manifest.py -x -q`.

### Phase M2 — Engine: `row_start` + dedup by source file

**Goal**: the engine can cut a window out of a sheet, and stops decoding one PNG
once per slot.

**Files** — modified: `engine/assets/manifest.py`, `engine/assets/store.py`,
`engine/assets/CLAUDE.md`, `tools/tests/test_assets_manifest.py`,
`tools/tests/test_asset_store.py`.

**Design notes**
- `entry_from_dict` parses `row_start` onto `ManifestEntry`, **raising** on a
  non-integer or negative value — the same defensive shape as `slice`/`anchors`,
  with `load_manifest` as the E-37 layer that turns the raise into
  warn-and-skip-this-entry. `load_registry` stays fail-loud; that split is
  unchanged.
- `AssetStore._frame_surface` offsets the row by `entry.row_start` when it cuts
  the subsurface. **This is the only place the window is applied.**
  `playback_order`, `current_frame`, and every row index above them keep meaning
  "row *i* of this entry's `rows[]`" — the window is a slicing concern, not a
  playback concern, and leaking it upward would touch the prototype-exact
  animation semantics for no reason.
- `AssetStore._sheet` re-keys `self._sheets` from `entry.slot_key` onto
  **`entry.sheet`**: one PNG = one decode = one Surface. Frames remain
  subsurfaces of that one Surface, so the parent must still stay cached for the
  store's life (unchanged contract). `_frames`/`_hit_masks` stay slot-keyed (D10)
  — leave a comment saying why, or the next reader will "fix" it.
- A window that runs past the sheet's real row count must degrade to the grey-X
  placeholder, never raise (E-37).

**Tests**: an entry with `row_start: 3` resolves frames from sheet row 3; an
entry with no `row_start` resolves **byte-identically to before** (pin this
explicitly — it is the compatibility argument for the whole key); two slots
pointing at one sheet path produce one Surface object (assert identity, and
assert the load count via a spy on `pygame.image.load`); a `row_start` past the
sheet height yields the placeholder; a corrupt `row_start` warns and skips the
entry rather than raising.

**Exit gate**: `py -m pytest tools/tests/test_assets_manifest.py tools/tests/test_asset_store.py -x -q`
plus `py tools/smoke.py`.

### Phase M3 — Editor: pure import module + picker dialog

**Goal**: master sheets can be imported and listed. No DetailsPanel changes yet.

**Files** — new: `editor/master_sheet_import.py` (Qt-free, pygame-free, Pillow
only — mirrors `editor/asset_import.py`'s shape),
`editor/panels/master_sheet_dialog.py` (Qt),
`tools/tests/test_master_sheet_import.py`. Modified:
`tools/tests/test_editor_viewport.py` (**both new modules go into
`TestPurity`'s import list** — the layering guard; every new editor module does),
`conftest.py` (`TIERS` entry), `editor/CLAUDE.md`, `editor/panels/CLAUDE.md`.

**`editor/master_sheet_import.py`**
- `load_registry_doc(data_dir)` / `write_registry_doc(data_dir, doc)` — the ONE
  write path for this file, through `engine.data_io.write_validated`; the load
  degrades to an empty doc on a missing/corrupt file (E-37, mirroring
  `asset_import.load_manifest_doc` exactly).
- `master_ref(sheet_id)` → `"master/<sheet_id>.png"` — with the same docstring
  warning `asset_import.sheet_ref` carries: read the entry's `sheet`, never
  re-derive it.
- `import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h)` —
  slugify the display name / filename stem into an id, copy to
  `master/<id>.png` (**skip the copy when byte-identical or same path**, so a
  re-import produces no diff), write the registry entry. Returns the id.
- `master_sheets(data_dir)` — the list the picker renders: an
  `ImportedSheet`-shaped frozen dataclass per entry with its real pixel size,
  its grid at its declared frame size, and its **users**. Reuse
  `asset_import.sheet_users` for the refcount rather than writing a second one.
- Deliberately NOT here: `pad_to_frame`. A master sheet is a grid the designer
  authored; centring it on a padded canvas would silently shift every row.

**`editor/panels/master_sheet_dialog.py`**
- The small popup: **Import new master spritesheet…** vs **Use existing…**; the
  existing branch lists every registry entry with an embedded read-only
  `SheetPreview` (`sheet_preview.py`), a filter box, and each row described with
  its size, grid and user count.
- **Copy `editor/panels/sheet_picker.py`'s structure** — it is the same dialog
  one concept over (construction split from display so tests never `exec()` a
  modal; `QAction.trigger()`/direct-method as the test path).
- The import branch collects `display_name`, `frame_w`, `frame_h` before writing
  — the frame size is D3's whole point and cannot be deferred.

**Tests**: import into a temp data dir writes the PNG and a schema-valid registry
entry; re-importing the same bytes leaves the file untouched; slugification cases
(spaces, punctuation, leading digit, collision with an existing id);
`master_sheets()` reports users correctly for a sheet two slots point at; the
dialog constructs, lists what the registry holds, and returns the selected id
without opening a modal. Bare-minimum coverage — no exhaustive Qt matrix.

**Exit gate**: `py -m pytest tools/tests/test_master_sheet_import.py -x -q` plus
`py -m pytest -m editor` for the Qt tier.

### Phase M4 — DetailsPanel: button, row window, narrowed views

**Goal**: the designer flow from §1, end to end, in the main importer. This is
the phase with the most existing code to respect.

**Files** — modified: `editor/panels/details.py`,
`editor/panels/sheet_preview.py`, `editor/panels/CLAUDE.md`,
`tools/tests/test_details_panel.py`, `tools/tests/test_editor_panels.py`.

**The button.** A third button, `"Use Master Spritesheet…"`, in the buttons row
beside Import / Use / Save / Clear. **Connect it wrapped in a lambda.** A bare
`clicked.connect(self._method)` puts Qt's `checked` bool into the first kwarg —
the exact footgun that made Clear skip its confirm dialog for months and that
map_details' Delete hit before it.

**On selection**: write the entry's `sheet` to `master/<id>.png`, adopt the
master sheet's `frame_w`/`frame_h` into the entry, and **disable the Frame W/H
spinboxes with a tooltip** saying the master sheet owns the grid. This bypasses
`_on_frame_size_changed`'s two-file write on purpose (D3) — `slots.json` must
not be touched here, and a reviewer who does not know that will read the bypass
as a bug, so comment it.

**The `using rows [ ] til [ ]` row.** Built exactly like the Frame W/H row: a
`QHBoxLayout` of `QLabel` + two `_NoWheelSpinBox` **imported from
`editor.panels.balancing`** (their one home — never a bare `QSpinBox`; the
mousewheel is navigation-only everywhere in this editor), committing on
`editingFinished`, not `valueChanged`. Placed directly under the selection,
visible only while the slot's sheet is a master sheet — the same
`_slice_applies()` / `_tint_applies()` gating idiom, which is the established
precedent for a category- or context-scoped control in this panel. Bounds come
from the sheet's real row count, and **`a > b` must be unrepresentable** (ED-30 —
clamp the second spin's minimum to the first's value), not an error caught at
save time.

**Narrow the preview.** `SheetPreview.set_sheet(png, fw, fh)` computes
`_cols`/`_rows` by integer division; add an optional row window so only the
selected rows are drawn. **The cell captions and the `frame_clicked(row, col)`
signal must speak ENTRY-RELATIVE row indices**, so the preview and the
`RowEditor`s below cannot disagree about what "row 1" means — the same
one-vocabulary argument that keeps the column captions, the hide checkboxes, the
static radios and the manifest's `hidden`/`loop_start`/`loop_end` all speaking
one number today.

**Narrow the rows.** `_load_sheet` builds one `RowEditor` per detected sheet row;
it now builds one per row **in the window**. Row 0 of the window stays
idle-locked — the E-35 rule remains unrepresentable in the UI rather than
becoming a save-time error.

**Save.** `save()` writes `row_start`; **omit the key when it is 0** so a
non-master entry stays byte-identical — the convention `slice` and
`tint_overlay` already follow. `draft_entry()` must preserve it the same way it
preserves `anchors` (that panel does not author anchors and must not erase them;
the same now applies in reverse for any panel that does not author the window).

**Tests**: selecting a master sheet writes the master ref and the inherited frame
size and disables the Frame W/H spins; the row appears only for a master sheet;
setting the window rebuilds exactly that many RowEditors and narrows the preview;
`frame_clicked` on the first visible row routes to RowEditor 0; save writes
`row_start` and omits it at 0; Clear refcounts correctly against a master sheet
that other slots still use (reuse `asset_import.unreferenced_sheets` — a master
sheet with remaining users must never be unlinked).

**Exit gate**: `py -m pytest -m editor`; then a **live `py editor/main.py`**:
import a real multi-character master sheet, point two different slots at two
different row windows, confirm the preview and the row strip both narrow, save,
and confirm both slots render correctly from the one file. State that it was a
live run.

### Phase M5 — VFX preview panel

**Goal**: parity for the one other import surface in scope (D5).

**Files** — modified: `editor/panels/vfx_preview.py`,
`editor/CLAUDE.md`, `tools/tests/test_vfx_preview.py` (or the panel's existing
test module).

**Design note**: vfx slots are single-`idle`-row, so the window here selects
exactly ONE row — either the same two spins with the second clamped to the first,
or a single "row" spin. Implementer's call; state which and why in the phase
report. Everything else (button wrapped in a lambda, frame size inherited and
locked, `row_start` omitted at 0) is M4's behaviour unchanged.

**⚠ File collision with the `/add-vfx` skill** (added to `Development` after this
plan was first written). `.claude/commands/add-vfx.md` edits this same file: it
reads and may append to `_EMIT_FAMILIES`, `_LEVERS`, `_RAMP_KEY`
(`vfx_preview.py:85-128`) and the per-family fixed `vfx_*` slot mapping that the
existing "Import Spritesheet…" button at `:198` resolves through. M5 touches the
button row and the frame-size/row-window controls, not those tables — but **do
not run M5 concurrently with an `/add-vfx` dispatch on the same checkout.** If
both are in flight, worktree-isolate them and merge M5 second, since its diff is
the smaller one. Whoever executes M5 should check `git log --oneline -- editor/panels/vfx_preview.py`
first.

**Exit gate**: `py -m pytest -m editor`; a live editor run selecting a vfx slot
and importing from a master sheet.

---

## 8. Verify (whole plan)

Iteration policy is the root `CLAUDE.md` Test Suite Policy, not this doc. It is
**role-scoped**, and `.claude/hooks/test_guard.py` enforces the mechanical parts
— a run that breaks the table is *denied*, not merely discouraged:

| Role | Gate for this plan |
|---|---|
| Dispatched coder / reviewer (any phase) | `py tools/smoke.py` + `py -m pytest tools/tests/test_<file>.py -q` over **the files it touched** — nothing wider. **Not** the full suite, **not** a tier sweep, **not** `--affected` (its safety pass is the whole core tier, so the hook denies it for subagents). |
| Main session, mid-plan | targeted files, or `py tools/testgate.py check --affected` after a merge |
| Main session, at handoff | exactly ONE `py tools/testgate.py check` |

**A denied test run is a REPORT, never a retry.** `test_guard.py` denies with
exit 2 and a reason. Do not re-issue, do not vary the flags (it normalises
`-q/-v/-x/-n/--tb`, so a reworded command fingerprints identically), do not reach
for the escape hatch. Two denies are expected and must not be fought: *"already
ran this exact target and nothing has changed"* (the guard fingerprints the main
checkout's diff, and worktrees are gitignored, so a coder's own edits can be
invisible to it) and *"another test run is already in flight"* (never wait-loop,
never delete the lock — only the orchestrator clears one, and only after
confirming nothing is live).

`--affected` **aborts rather than silently widening**: a `GATE ABORT` is not a
test failure and not something to retry — name the affected test files yourself
and run those once.

- Every phase's own exit gate above.
- Data phases: every touched file validates; `py tools/smoke.py`.
- Render phases: `py tools/smoke.py` plus a **live** `py game/main.py` look —
  visuals changed, so a headless pass is not sufficient evidence.
- Editor phases: `py -m pytest -m editor` plus a **live** `py editor/main.py`
  exercise of the changed panel.
- At handoff: `py tools/testgate.py check`. **The gate is ZERO.** There is no
  baseline and no tolerated failure; a red test outside this diff's blast radius
  gets surfaced to the user, not investigated silently.
- Tests must never write into `data/` (`TempDataCase`) and must never assert
  against live `data/` content — pin the fixture. `master_sheets.json` and
  `data/sprites/master/` must be copied by the editor-test temp-data helper;
  extend it in M1 if it does not already copy the whole tree. Note the committed
  fixture manifest (`tools/tests/fixtures/data/sprites/asset_manifest.json`)
  currently holds **278 entries** and grew again in the tile-condition rework —
  assert on entries the test itself writes, never on a count or on "this slot has
  no art".
- Docs: `engine/CLAUDE.md` + `engine/render/CLAUDE.md` + `engine/assets/CLAUDE.md`
  for Part A/M2, `data/CLAUDE.md` for M1, `editor/CLAUDE.md` +
  `editor/panels/CLAUDE.md` for M3–M5. Architectural changes update **the package
  doc**, not the root router.

## 9. Risks / open items

- **G0 may invalidate Part A's shape** (D9). The plan explicitly permits a
  re-scope; taking it is the success case, not a failure.
- ~~**SDL2 Renderer under the dummy video driver is unverified**~~ — **RETIRED
  by G1's probe** (§4, measured 2026-08-12). The `dummy` driver hosts
  `Window`/`Renderer`/`Texture` upload/draw/`to_surface()` readback correctly,
  so G2/G3's parity coverage runs in normal CI and the feared reduction in
  safety does not apply.
- **Pixel parity between SDL's scaler and `pygame.transform.scale` is not
  guaranteed.** The plan accepts a pinned tolerance rather than pretending to
  bit-identity. If the difference is visible on pixel art at zoom, that is a
  finding to surface — pixel art is the whole aesthetic here, and a blurrier GPU
  path would be a regression no fps number redeems.
- **Two backends is two implementations to keep in parity**, forever. Mitigated
  by the parity test and by keeping HUD / nine-slice / fonts / crop
  single-implementation on the Surface path (D7).
- **The overlay-pass regression is MEASURED and SCHEDULED as phase G5** — it is
  no longer an open risk awaiting a decision. G4 broke the pass out and found
  **6.0× worse on GPU at 40 diamonds** (4.31 vs 0.72 ms) and **1.65× worse plus
  4.9 MB of per-frame churn** on the far-off-screen polyline. The decision is
  taken: clip the scratch to the target and reuse the buffer, in
  `backend_gpu.py` alone (§6/G5). Until G5 lands, the GPU path carries a real
  live-gameplay regression on every tile highlight and wall segment PR #122
  routes through `WorldFill`, and **no phase outside G5 may touch
  `backend_gpu.py`** — a second editor of that file while G5 is scoped is how
  the two fixes collide.
- **G0's HUD-cost claim is still INFERRED and unretired, and is SCHEDULED as
  phase G6.** D7 kept the HUD single-implementation on the Surface path partly
  on the strength of "the HUD cannot plausibly be the dominant cost", which has
  never been measured — `tools/profile_render.py` submits no HUD items, so
  `hud` reads 0.00 in every row of G4's table. The instrument shipped in G4;
  retiring the claim needs §4.3 Step 6's live frame timings at a display, which
  **no headless agent can produce** — G6 is an `/execute-phase` with the user,
  not an agent dispatch (§6/G6). If the HUD turns out to be significant, D7 is
  the decision that gets re-opened.
- **G4 MUST profile the overlay path, not just the sprite path** (raised in G2's
  review, deferred there deliberately; **discharged — G4 did it, see the G5
  bullet above**). `backend_gpu.py` rasterizes both
  `OverlayLines` and `OverlayPolys` into a bounding-box `SRCALPHA` scratch
  Surface and uploads it **per call, per frame, uncached** — the only route that
  is parity-exact, since SDL's `draw_line` has no width and no native primitive
  covers an arbitrary-length alpha polygon. Two consequences the Surface backend
  does not have: (a) the scratch is sized from the raw point bounding box with
  **no clip to the target**, while `backend.py:190` draws straight onto the
  target and clips — a polyline with one point far off-screen (the renderer
  converts world→screen without clipping) asks for a surface that wide every
  frame; (b) per-frame alloc → CPU rasterize → upload → destroy churn, on a path
  the game feeds tile fills, splatters, glows and drummer-aura rings through.
  G0 profiled `flush` as one bucket and never separated overlays, so this is
  **unmeasured**: G4's re-measure must break the overlay pass out, or the port
  can move frame time the wrong way at exactly the boss load this plan exists to
  fix.
- **`backend_gpu` snapshots a source Surface at first upload and never
  refreshes it**, where `backend.py` returns the live surface at 1:1. A
  consumer that mutates a surface in place and keeps handing it to the same
  `DrawCall` renders correctly on the Surface path and freezes at its
  first-frame contents on the GPU path, with no error. No shipped consumer does
  this today; it is a new precondition G3/G4 must not violate (the ground cache
  in particular composites into a surface it reuses — G3 must upload a target
  Texture, never hand a mutated cache Surface to `backend_gpu`).
- **A non-zero `slice` on a 1:1-sized draw diverges between the backends.**
  `backend.py:216` takes the nine-patch branch only when the dest size differs
  from the source, so such a call is a legal plain scale there; `backend_gpu`
  raises `NotImplementedError` on any non-zero slice. That guard is exactly what
  G2 was specified to write (slice is HUD-only and must be asserted, not
  implemented twice), so it is not a defect — but it is a latent crash if G4's
  HUD-composite split ever lets a sliced `DrawCall` reach the world path.
- **G4 now inherits THREE live checks, none of which has ever been run**: G2's
  pixel-art look (a real non-dummy window, a real sheet from
  `data/sprites/imported/`, a CPU/GPU PNG pair at 1:1 and magnified), G3's
  large-map pan for seams and stutter, and G4's own fallback-vs-GPU comparison.
  All three are blocked on the same thing — nothing selects the GPU path until
  G4 wires it — so G4 is the first phase where any of them is even *possible*,
  and it should be run with a human at a display (§5.1 already flags G4 as
  `/execute-phase` for exactly this).
- **The GPU parity tolerances are pinned per phase and must not be nudged.**
  `backend_gpu` is 1, `GroundCacheGpu` is 2 (tint path only, §6/G3 RESULTS). A
  later phase that finds a pin failing has found a regression; widening the
  constant to make a phase pass is the one move this plan forbids outright, and
  both constants carry the measured histogram in a comment so the next reader
  can tell drift from noise. G3's tolerance was negative-controlled (a 1px
  injected shift fails at delta 140), so it is known to still catch the
  misalignment class it exists for — repeat that control if either number moves.
- **`row_start` interacts with sheet sharing.** Two slots on one master sheet
  with overlapping windows is legal and probably intentional. Two slots on one
  sheet with different frame sizes is not — which is exactly why the master sheet
  owns the grid (D3). Note that a plain (non-master) shared sheet is still free
  to be cut two ways; M2's `_sheets` re-key is safe for that because only the
  raw Surface is shared, and `_frames` stays slot-keyed (D10).
- **Widening the manifest `sheet` pattern is a one-way door for old readers.**
  Nothing outside this repo reads it, but a `master/` path in an entry will not
  validate against an older checkout's schema. Worth one line in the PR.
- **Orphan policy for master sheets is unspecified.** `imported/` orphans are
  legal and deliberate (that is how you get art back). M3 should follow the same
  rule — a master sheet no entry references stays on disk and stays in the
  picker — but nothing in this plan deletes master sheets at all, so
  "unreferenced master sheet cleanup" is genuinely deferred, not decided.
- **Not in scope, named so it is not mistaken for an oversight**: the palette
  importer (D5), deduping `_frames`/`_hit_masks` (D10), migrating the HUD to
  textures (D7), and moving the editor viewport onto the GPU path (D6).
