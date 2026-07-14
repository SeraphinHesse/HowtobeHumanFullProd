# Phase A2 — nine-slice (slice 10L-A)

Branch: `phase-A1-A2-engine` (A1 lands first; see §3). Packages: engine + data.
Plan: `planning/UI_EDITOR_PLAN.md` lines 97-110 (A2 scope), 241-253 (risks).

---

## 1. Behavioral spec

### What a `slice` is
A manifest entry may carry optional nine-slice margins
`"slice": [left, top, right, bottom]` — ints ≥ 0, **authored in FRAME pixels**
(same convention as `offset_x`/`offset_y`, `data/CLAUDE.md` "Asset data").
Omitted ⇒ plain uniform scale, exactly as today. Applies to **HUD sprites only**
(plan line 27-28: "world sprites keep uniform zoom scaling").

The field rides `ManifestEntry` → `Frame` → `DrawCall` → the backend. Nothing
between the manifest and `engine/render/backend.py` interprets it — the renderer
copies it, the store copies it, the backend is the only place geometry happens.

### 9-patch geometry (the contract)
Given source surface size `(sw, sh)` (== the frame size), authored margins
`(left, top, right, bottom)`, destination size `(dw, dh)` (already
`max(1, round(...))` per `backend.py:125`):

1. **Clamp the margins to the SOURCE** (an authored margin larger than the frame
   is meaningless): `sl, sr = clamp_pair(left, right, sw)`,
   `st, sb = clamp_pair(top, bottom, sh)`.
2. **Clamp them again to the DESTINATION** (the degenerate case):
   `dl, dr = clamp_pair(sl, sr, dw)`, `dt, db = clamp_pair(st, sb, dh)`.
3. Column/row bands:

   | band | source `(x, w)` | dest `(x, w)` |
   |---|---|---|
   | left   | `(0, sl)`            | `(0, dl)` |
   | middle | `(sl, sw-sl-sr)`     | `(dl, dw-dl-dr)` |
   | right  | `(sw-sr, sr)`        | `(dw-dr, dr)` |

   Rows are the same with `st/sb`, `dt/db`, `sh/dh`.
4. The 9 regions are the cross-product. Each is `subsurface(src_rect)` →
   `pygame.transform.scale` to the dest size **only if it differs** → blit at the
   dest position on a fresh `pygame.Surface(size, pygame.SRCALPHA)`.
   - corners: dest size == source size in the non-degenerate case ⇒ **blitted 1:1,
     never resampled** (this is the whole point of a 9-patch).
   - top/bottom edges: stretched on **x only**. left/right edges: **y only**.
   - centre: stretched on **both**.
   - A region with source **or** dest width/height ≤ 0 is **skipped**. (Source
     centre width 0 with a positive dest centre width leaves that band
     transparent — there are no source pixels to stretch. Correct by
     construction; authoring error, not a crash.)

### `clamp_pair(a, b, limit)` — the degenerate clamp (exact)
```
total = a + b
if total <= limit:  return a, b        # normal case, untouched
if total <= 0:      return 0, 0        # no margins on this axis
a2 = a * limit // total                # integer, ratio-preserving
return a2, limit - a2                  # a2 + b2 == limit EXACTLY
```
Consequences, all deliberate:
- Overflow ⇒ the two margins exactly fill the axis, so the **centre band is 0
  wide/tall and vanishes**; the corners are still drawn, now **squeezed** (source
  corner scaled down into the clamped dest corner) rather than clipped.
- `limit == 1` with equal margins ⇒ `a2 = 0`, `b2 = 1`: one margin collapses to
  nothing and the other takes the single pixel. No crash, no negative rect.
- `total == 0` on an axis (e.g. `slice = [0, 3, 0, 3]`) is **not degenerate** — it
  is a legitimate 1×3 patch: the horizontal middle band takes the full `dw` and
  the sprite stretches freely on x while the top/bottom 3px bands stay fixed.

### No-op cases (must take the existing `_scaled` path, unchanged)
- `call.slice is None` — every world sprite (`renderer.py:111-122` never sets it)
  and every un-sliced HUD sprite.
- `all(m == 0 for m in call.slice)` — an all-zero slice is arithmetically
  identical to a plain scale; route it to `_scaled` so it shares the plain-scale
  cache entry.
- `size == surface.get_size()` — `_scaled` already returns the source surface
  itself. Nine-slicing at 1:1 is the identity, so short-circuit.

Placeholder frames (`store.py:73`, the grey X) **never carry a slice** — a
"no asset yet" square has no authored margins, and keeping it on the plain path
preserves `test_placeholder_surfaces_do_not_leak`.

### Purity (hard rule, `engine/CLAUDE.md` "Hard rules")
`ManifestEntry.slice` / `Frame.slice` / `DrawCall.slice` are plain
`tuple[int,int,int,int] | None`. `engine/assets/manifest.py`, `engine/assets/
types.py`, `engine/render/item.py`, `engine/render/renderer.py` stay pygame-free
(`test_render.TestPurity`, line 424-438). Only `backend.py` touches pygame.

---

## 2. Architecture plan (exact edits, in order)

### 2.1 `data/schemas/asset_manifest.schema.json`
Add `slice` to the per-entry `properties` (object at lines 74-141), **between
`rows` and `sheet`** (D-3 sorted keys). Do **not** add it to `required`
(lines 132-139) — omitted means plain scale.

```json
            "slice": {
              "description": "Optional nine-slice margins in FRAME pixels [left, top, right, bottom]. When a HUD sprite is drawn at a size other than its frame size, corners blit 1:1, edges stretch on one axis and the centre on both. Omit for plain uniform scaling (world sprites ignore it).",
              "items": {
                "maximum": 1024,
                "minimum": 0,
                "type": "integer"
              },
              "maxItems": 4,
              "minItems": 4,
              "type": "array"
            },
```
(`maximum: 1024` mirrors `frame_w`/`frame_h`'s cap; `additionalProperties: false`
at line 76 is why the key must be declared at all.) The committed
`data/sprites/asset_manifest.json` is **not** touched — no entry uses `slice` yet.

### 2.2 `engine/assets/manifest.py`
`ManifestEntry` (lines 75-83) gains one field:
```python
@dataclass(frozen=True)
class ManifestEntry:
    slot_key: str
    sheet: str
    frame_w: int
    frame_h: int
    offset_x: int
    offset_y: int
    animations: dict  # {name: Track}, insertion order = row order
    slice: tuple = None   # (left, top, right, bottom) frame-px, or None
```
`entry_from_dict` — add the parse just before the `return ManifestEntry(...)` at
line 132, and pass it through:
```python
    margins = raw.get("slice")
    if margins is not None:
        try:
            margins = tuple(int(v) for v in margins)
        except (TypeError, ValueError):
            raise ValueError(f"{slot_key}: slice must be 4 integers")
        if len(margins) != 4 or any(v < 0 for v in margins):
            raise ValueError(
                f"{slot_key}: slice must be [left, top, right, bottom], all >= 0")

    return ManifestEntry(
        slot_key=slot_key,
        sheet=sheet,
        frame_w=frame_w,
        frame_h=frame_h,
        offset_x=int(raw.get("offset_x", 0)),
        offset_y=int(raw.get("offset_y", 0)),
        animations=animations,
        slice=margins,
    )
```
Raising (rather than warning + dropping to `None`) is the module's stated
contract — "Raises ValueError on anything unusable" (docstring, line 87-88) — and
`load_manifest` is the E-37 tolerance layer that turns it into a warn+skip
(→ grey X). Schema validation + `tools/smoke.py` catch it at authoring time.

### 2.3 `engine/assets/types.py`
```python
@dataclass(frozen=True)
class Frame:
    surface: object
    frame_w: int
    frame_h: int
    offset_x: int = 0
    offset_y: int = 0
    slice: tuple = None   # nine-slice margins from the manifest entry, or None
```
Appended last, defaulted ⇒ every existing positional/kw construction (incl. the
test fakes in `test_render.py:41`, `test_components.py:24`, `test_shell.py:23`,
`test_hud_items.py:34`) keeps working untouched.

### 2.4 `engine/assets/store.py`
Real-art path only (lines 65-67):
```python
        return Frame(surface=surface, frame_w=entry.frame_w,
                     frame_h=entry.frame_h, offset_x=entry.offset_x,
                     offset_y=entry.offset_y, slice=entry.slice)
```
`_placeholder` (line 71-73) is **left as-is** — the grey X stays `slice=None`.

### 2.5 `engine/render/item.py`
```python
@dataclass(frozen=True)
class DrawCall:
    surface: object  # opaque to everything except the backend
    dest: tuple  # screen-space topleft (floats; backend rounds)
    size: tuple  # final blit size in px (backend scales if != surface size)
    tint: tuple = None
    flip: bool = False
    slice: tuple = None  # nine-slice margins (frame px) — HUD sprites only
```

### 2.6 `engine/render/renderer.py` — ONE line
In the HUD folding block (lines 137-148; **A1 has already rewritten the
`assets.frame(...)` call there — see §3**), add `slice=frame.slice` to the
`DrawCall`:
```python
        for hud in self._hud:
            if isinstance(hud, HudSprite):
                frame = self._assets.frame(hud.slot_key, hud.animation, hud.anim_time_ms)  # A1
                draw_calls.append(DrawCall(
                    surface=frame.surface,
                    dest=hud.dest,
                    size=hud.size,
                    tint=hud.tint,
                    flip=hud.flip,
                    slice=frame.slice,        # <-- A2, the only A2 line here
                ))
```
The **world-sprite `DrawCall` (lines 111-122) is NOT touched** — it never sets
`slice`, so it defaults to `None` and world rendering is provably byte-identical.

### 2.7 `engine/render/backend.py` — the 9-patch
Two new module functions next to `_scaled` (lines 38-47), and a 4-line hook in
`draw`.

```python
def _clamp_pair(a, b, limit):
    """Opposite margins clamped PROPORTIONALLY into `limit`. On overflow
    a+b == limit exactly (the centre band vanishes, the corners squeeze)."""
    total = a + b
    if total <= limit:
        return a, b
    if total <= 0:
        return 0, 0
    a2 = a * limit // total
    return a2, limit - a2


def _nine_patch(surface, size, margins):
    """Composite `surface` into `size` as a 9-patch: corners 1:1, edges
    stretched on one axis, centre on both. Memoized per (surface, size,
    margins) in the same weak scale cache."""
    key = ("9p", size, margins)
    by_key = _scale_cache.get(surface)
    if by_key is None:
        by_key = _scale_cache[surface] = {}
    patched = by_key.get(key)
    if patched is not None:
        return patched

    sw, sh = surface.get_size()
    dw, dh = size
    sl, sr = _clamp_pair(margins[0], margins[2], sw)   # margins <= the frame
    st, sb = _clamp_pair(margins[1], margins[3], sh)
    dl, dr = _clamp_pair(sl, sr, dw)                   # ...and <= the dest
    dt, db = _clamp_pair(st, sb, dh)

    src_cols = ((0, sl), (sl, sw - sl - sr), (sw - sr, sr))
    dst_cols = ((0, dl), (dl, dw - dl - dr), (dw - dr, dr))
    src_rows = ((0, st), (st, sh - st - sb), (sh - sb, sb))
    dst_rows = ((0, dt), (dt, dh - dt - db), (dh - db, db))

    patched = pygame.Surface(size, pygame.SRCALPHA)
    for (sx, sw_i), (dx, dw_i) in zip(src_cols, dst_cols):
        for (sy, sh_i), (dy, dh_i) in zip(src_rows, dst_rows):
            if min(sw_i, sh_i, dw_i, dh_i) <= 0:
                continue          # empty band (degenerate clamp / zero margin)
            region = surface.subsurface(pygame.Rect(sx, sy, sw_i, sh_i))
            if (dw_i, dh_i) != (sw_i, sh_i):
                region = pygame.transform.scale(region, (dw_i, dh_i))
            patched.blit(region, (dx, dy))
    by_key[key] = patched
    return patched
```
In `draw()`, replace line 126 (`surface = _scaled(call.surface, size)`) with:
```python
        margins = call.slice
        if margins and any(margins) and size != call.surface.get_size():
            surface = _nine_patch(call.surface, size, tuple(margins))
        else:
            surface = _scaled(call.surface, size)
```
Everything after it (flip, tint, batch append, lines 127-132) is unchanged — a
9-patch composite is just "the surface at the final size", exactly like a scaled
one, so flip/tint/batching keep working for free.

### Design decision — cache: REUSE `_scale_cache`, distinguishing key
The composite goes in the **existing** `WeakKeyDictionary` (`backend.py:35`),
keyed by the SOURCE surface, in the same inner dict, under
`("9p", size, margins)`. Plain scales keep their bare `size` 2-tuple key, so a
3-tuple can never collide.

- **Weak eviction still holds** (the pin that matters): the inner dict hangs off
  the source surface, so when a transient surface — the grey-X placeholder, a
  fresh surface each call — is GC'd, its whole inner dict (plain scales *and*
  9-patch composites) dies with it. `test_placeholder_surfaces_do_not_leak`
  counts SOURCE keys (`len(backend._scale_cache) <= 1`) and is unaffected. In
  practice the placeholder never even reaches this path (§1: placeholder frames
  carry no slice).
- **Margins are in the key, not just the size**, because the editor's A4 slice
  spinboxes re-draw the *same* cached frame subsurface with *different* margins;
  a size-only key would serve a stale composite.
- A parallel `WeakKeyDictionary` was rejected: same lifetime, same key surface,
  double the bookkeeping and a second thing every cache test must clear.

### Design decision — `pygame.transform.scale`, NOT `smoothscale`
The plan (lines 246-248) defers this to "by eye on real art". **No real UI art
exists yet**, so pick the choice that is correct for what this codebase actually
ships and revisit later:

- Our sheets are **pixel art with per-pixel alpha**, loaded with no
  `convert_alpha()` (`engine/assets/CLAUDE.md`, "Store"). `smoothscale` filters
  RGB across alpha boundaries — it bleeds the transparent-pixel colour into the
  edges (halos/fringing) and blurs pixel art on any non-integer stretch.
- `pygame.transform.scale` is nearest-neighbour and alpha-safe, and it is
  **already** what every world sprite goes through at zoom ≠ 1 (`_scaled`,
  line 46). Using the same resampler keeps HUD skins visually consistent with the
  world at the same zoom.
- **Revisitable**: corners are never resampled, so the only resample sites are
  the 4 edges + centre inside `_nine_patch`. If real art turns out to be
  high-res/photographic, swapping those to `smoothscale` is a one-line change
  behind a module constant. Note it in `engine/render/CLAUDE.md`.

### Docs
Update `engine/render/CLAUDE.md` ("Backend throughput" — the cache now also holds
9-patch composites; the scale-vs-smoothscale rationale) and
`engine/assets/CLAUDE.md` (the optional `slice` field, HUD-only) and
`data/CLAUDE.md` ("Asset data" — the manifest `slice` key). Per the root router,
each package doc gets only its own change.

---

## 3. File scope + shared-file contract

**A2 edits exactly these 6 source files + 1 schema:**

| File | Change |
|---|---|
| `data/schemas/asset_manifest.schema.json` | optional `slice` property |
| `engine/assets/manifest.py` | `ManifestEntry.slice`, `entry_from_dict` parse |
| `engine/assets/types.py` | `Frame.slice` |
| `engine/assets/store.py` | pass `slice=entry.slice` (real-art path only) |
| `engine/render/item.py` | `DrawCall.slice` |
| `engine/render/renderer.py` | **one line**: `slice=frame.slice` in the HUD DrawCall |
| `engine/render/backend.py` | `_clamp_pair`, `_nine_patch`, 4-line hook in `draw()` |

Plus docs: `engine/render/CLAUDE.md`, `engine/assets/CLAUDE.md`,
`data/CLAUDE.md`.

**Do NOT touch:** `data/sprites/asset_manifest.json` (no entry gets a slice in
A2), `engine/render/hud.py` (A1), any `editor/**` or `game/**` file.

### Shared-file contract with A1 (binding)
A1 and A2 are the SAME coder on branch `phase-A1-A2-engine`, **A1 first**. Both
touch the HUD folding block in `engine/render/renderer.py` (lines 137-148):
- **A1 owns**: `HudSprite.animation` / `HudSprite.anim_time_ms` (in `hud.py`) and
  the `assets.frame(hud.slot_key, hud.animation, hud.anim_time_ms)` call.
- **A2 owns**: adding `slice=frame.slice` to the `DrawCall` constructed in that
  same block. Nothing else in that block.

Write A2 assuming A1 has landed; do not re-plan or re-touch A1's changes.

### Test-file ownership
- **A2 owns**: `tools/tests/test_render.py`, `tools/tests/test_asset_store.py`,
  `tools/tests/test_assets_manifest.py`, and the new
  `tools/tests/test_nine_slice.py`.
- **A1 owns** `tools/tests/test_hud_items.py` — do not touch it.

### Known follow-up, explicitly OUT of A2 scope
`editor/asset_import.import_idle_sheet` rewrites a manifest entry from scratch
(`editor/asset_import.py:69-84`), so re-importing a sheet would drop an existing
`slice`. Phase **A4** adds the slice-margin editor and owns preserving it.

---

## 4. Exit gate + Quick Test

### Commands
```
py -m unittest discover -s tools/tests -t .
py tools/smoke.py
```

**Baseline (do not "fix"):** 1086 tests, **16 pre-existing failures**, 1 skipped
on `Development` (test_run_controls, test_details_panel `TestSubcategoryDropdown`,
test_editor_viewport `TestEntityPreview` ×3, test_editor_panels ×2,
test_editor_map_mode ×2, test_balancing_parity ×6). **Exit gate = no NEW
failures.**

### New tests

**`tools/tests/test_nine_slice.py` (new file)** — synthetic 6×6 three-colour
sheet: whole surface GREEN `(0,255,0)`, centre 2×2 rect BLUE `(0,0,255)`, the
four 2×2 corners RED `(255,0,0)`; `slice = (2,2,2,2)`.
- `test_corners_are_not_scaled` — draw at 20×20. Assert all four dest corner
  pixels `(0,0) (19,0) (0,19) (19,19)` are RED, and that the corner is still
  exactly 2px: `(2,0)` and `(0,2)` are GREEN (edge, not corner).
- `test_edges_and_centre_fill` — same call: `(10,0)` and `(10,19)` GREEN (top/
  bottom edges stretched on x), `(0,10)` and `(19,10)` GREEN (left/right edges,
  y), `(10,10)` and `(2,2)` and `(17,17)` BLUE (centre stretched both ways).
- `test_composite_is_cached_per_surface_size_and_margins` — clear
  `backend._scale_cache`; draw the same 9-patch `DrawCall` once with a counting
  `pygame.transform.scale` (5 resamples: 4 edges + centre, corners 1:1), then
  draw it twice more and assert the counter did **not** advance; assert the inner
  dict holds exactly one `("9p", size, margins)` entry. Then draw the same source
  at a *different* size and at *different* margins and assert each adds one more
  entry (proves the key discriminates).
- `test_degenerate_size_clamps_proportionally` — same source/margins at dest
  `(2,2)`: must not raise; the 2×2 result is all RED (corners survive squeezed,
  centre vanishes). Also dest `(1,1)`: must not raise, single pixel is RED.
- `test_zero_margin_axis_stretches_freely` — `slice = (0,3,0,3)` at dest 30×12:
  no crash, a horizontal midpoint row pixel matches the source's middle band
  (pure 1×3 patch, x unconstrained).
- `test_all_zero_slice_is_a_plain_scale` — `slice = (0,0,0,0)` produces a surface
  pixel-identical to `pygame.transform.scale(src, size)` and lands in the plain
  `size`-keyed cache entry (not a `("9p", …)` one).
- `test_slice_survives_a_schema_validated_round_trip` — build a minimal v2
  manifest doc with `"slice": [4, 4, 4, 4]`, `engine.data_io.write_validated` it
  to a temp path against the **real** `data/schemas/asset_manifest.schema.json`,
  `load_manifest` it back, assert `entry.slice == (4, 4, 4, 4)`; assert a
  3-element slice and a negative value each raise `jsonschema.ValidationError`;
  assert an entry with no `slice` still validates (optionality).

**`tools/tests/test_assets_manifest.py`** (extend `TestEntryFromDict`)
- `test_slice_parsed_as_int_tuple` — `"slice": [1, 2, 3, 4]` → `(1, 2, 3, 4)`.
- `test_slice_absent_is_none` — `entry.slice is None`.
- `test_bad_slice_raises` — wrong length / negative / non-numeric each raise
  `ValueError` (and therefore warn+skip through `load_manifest`).

**`tools/tests/test_asset_store.py`** (extend `TestSlicing`)
- `test_frame_carries_slice` — an entry with `slice` → `store.frame(...).slice ==
  (…)`.
- `test_placeholder_frame_has_no_slice` — the grey-X `Frame.slice is None`.

**`tools/tests/test_render.py`** (new class `TestNineSliceThrough`; extend
`FakeAssets` with an optional `slices={slot: (l,t,r,b)}` dict)
- `test_hud_sprite_drawcall_carries_slice` — a `HudSprite` whose slot has a slice
  → the emitted `DrawCall.slice` equals it.
- `test_world_sprite_drawcall_never_sets_slice` — the same slot submitted as a
  `RenderItem` → `DrawCall.slice is None`.

**Regression pins that must stay green:** `test_render.TestBackendThroughput`
(`test_scaled_cache_reuses_scale`, `test_batch_equals_per_blit`,
`test_placeholder_surfaces_do_not_leak`) and `test_render.TestPurity`.

### Quick Test (human-runnable)
1. **See the 9-patch.** From the repo root, paste:
   ```
   py -c "import os;os.environ.setdefault('SDL_VIDEODRIVER','dummy');import pygame;pygame.init();from engine.render import backend;from engine.render.item import DrawCall;s=pygame.Surface((6,6),pygame.SRCALPHA);s.fill((0,255,0));s.fill((0,0,255),(2,2,2,2));[s.fill((255,0,0),r) for r in ((0,0,2,2),(4,0,2,2),(0,4,2,2),(4,4,2,2))];t=pygame.Surface((320,52),pygame.SRCALPHA);backend.draw(t,[DrawCall(surface=s,dest=(0,0),size=(320,52),slice=(2,2,2,2))]);os.makedirs('build',exist_ok=True);pygame.image.save(t,'build/nine_slice_demo.png');print('wrote build/nine_slice_demo.png')"
   ```
   Open `build/nine_slice_demo.png` (gitignored). **Expect**: four crisp 2×2 red
   corners at their original size, green borders stretched along each edge, a
   blue centre filling the middle — no blur, no colour fringing at the region
   seams (the `scale`-not-`smoothscale` decision, by eye). 320×52 is the button
   size the A6 Quick Test will use.
2. **Nothing regressed.** `py tools/smoke.py` (the committed manifest still
   validates with the new optional property) and `py game/main.py` — no manifest
   entry carries a `slice`, so the game must look **exactly** as before; the HUD
   and every world sprite take the unchanged `_scaled` path.
3. State in the PR exactly what you ran: the suite, the smoke test, the PNG
   look, and the live game boot.
