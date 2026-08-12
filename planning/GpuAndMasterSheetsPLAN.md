<!-- status: NOT STARTED — phases G0–G4 then M1–M5 -->

# GpuAndMasterSheetsPLAN.md — GPU render backend, then master spritesheets

Phased, agent-executable plan (same family as `AgentDispatchPLAN.md` /
`TimelinePLAN.md`). Base branch: `Development`. Runnable via
`/execute-plan-phases planning/GpuAndMasterSheetsPLAN.md G0-M5` or phase by
phase.

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
- **Unverified and load-bearing:** whether an SDL2 `Renderer` can be created at
  all under `SDL_VIDEODRIVER=dummy`. Phase G1 must answer this experimentally
  before G2 is written; the answer only affects whether the GPU path can be
  *tested* headlessly, not the dual-backend decision itself (D6 stands either
  way).

---

## 5. Build order

| Phase | Scope | Status |
|-------|-------|--------|
| G0 | Measure the real render cost (no engine changes) | not started |
| G1 | Backend seam + headless-renderer feasibility probe | not started |
| G2 | `backend_gpu.py` — world sprites, overlays, texture cache | not started |
| G3 | Ground cache on the GPU path | not started |
| G4 | Host wiring, HUD composite, fallback, re-measure | not started |
| M1 | Data layer: master-sheet registry + schema + `row_start` | not started |
| M2 | Engine: `row_start` slicing + sheet-path-keyed store | not started |
| M3 | Editor: pure master-sheet import module + picker dialog | not started |
| M4 | DetailsPanel: button, row window, narrowed preview + rows | not started |
| M5 | VFX preview panel button | not started |

Phases are sequential. G0→G4 must land before M2 re-keys the store (M2's dedup
is what G2's texture cache keys off), and M1 must land before M2 (schema before
parser). M3/M4/M5 are editor-only and could be split across worktrees if run
concurrently — **two or more implementation agents running at the same time must
each get `isolation: "worktree"`** (root `CLAUDE.md`, Hard rules).

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

### Phase G3 — Ground cache on the GPU path

**Goal**: the ground layer's scroll-and-fill technique, on textures, behind the
same public signature.

**Files** — new: `engine/render/ground_cache_gpu.py` (or a variant class inside
`ground_cache.py` — implementer's call, stated in the report). Modified:
`engine/render/ground_cache.py` (only if the variant lands there),
`engine/render/CLAUDE.md`, `tools/tests/test_ground_cache.py`.

**Design notes**
- Same `ensure(view_w, view_h, ground_items_fn)` signature, so both callers
  (game and editor) are untouched and the content-agnostic callback contract
  holds.
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

**Exit gate**: `py -m pytest -m editor`; a live editor run selecting a vfx slot
and importing from a master sheet.

---

## 8. Verify (whole plan)

Iteration policy is the root `CLAUDE.md` Test Suite Policy, not this doc:
targeted `py -m pytest tools/tests/test_<area>.py -x -q` while working, **one**
full `py tools/testgate.py check` at handoff, never mid-task, never twice, never
two runs in flight. `--affected` does not reliably narrow — read its `GATE INFO`
line before believing it did.

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
  extend it in M1 if it does not already copy the whole tree.
- Docs: `engine/CLAUDE.md` + `engine/render/CLAUDE.md` + `engine/assets/CLAUDE.md`
  for Part A/M2, `data/CLAUDE.md` for M1, `editor/CLAUDE.md` +
  `editor/panels/CLAUDE.md` for M3–M5. Architectural changes update **the package
  doc**, not the root router.

## 9. Risks / open items

- **G0 may invalidate Part A's shape** (D9). The plan explicitly permits a
  re-scope; taking it is the success case, not a failure.
- **SDL2 Renderer under the dummy video driver is unverified** (§4). If it
  cannot run headless, G2/G3's parity coverage becomes a live-only check and CI
  covers the Surface path only — a real reduction in safety that must be stated
  on the PR, not glossed.
- **Pixel parity between SDL's scaler and `pygame.transform.scale` is not
  guaranteed.** The plan accepts a pinned tolerance rather than pretending to
  bit-identity. If the difference is visible on pixel art at zoom, that is a
  finding to surface — pixel art is the whole aesthetic here, and a blurrier GPU
  path would be a regression no fps number redeems.
- **Two backends is two implementations to keep in parity**, forever. Mitigated
  by the parity test and by keeping HUD / nine-slice / fonts / crop
  single-implementation on the Surface path (D7).
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
