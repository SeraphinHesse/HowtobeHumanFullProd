> **SUPERSEDED — historical record.** This brief predates the ZERO-failure
> gate. Any "baseline", "N pre-existing failures", "no NEW failures vs
> Development" or `unittest discover` instruction below is DEAD: the suite is
> green, the gate is ZERO, and a red test is yours. Which tests you may run is
> role-scoped — §"Test Suite Policy" in the root `CLAUDE.md` is the only
> authority. Do not follow this file's verification section.

# Phase A8 — pixel hit-mask (slice 10L-A)

Branch: `phase-10L-finish-umbrella` (umbrella run, dependency: A1–A3 landed).
Packages: engine only (no game, no editor, no data schema changes).
Plan: `planning/UI_EDITOR_PLAN.md` lines 258-266 (A8 scope), lines 67-80 (R2 design).

---

## 1. Behavioral spec

### What a hit-mask does
Skinned buttons hover AND click only over **drawn pixels** (alpha > 0), not the
whole rect. The engine resolves a destination screen-space click via the inverse
of the nine-patch band layout (mapping destination coords back to source) and
reads a cached per-pixel alpha mask.

**Canonical silhouette:** widgets always query `("idle", 0)` — hit-testing reads
the drawn state row at anim_time_ms=0, so clicking on transparent corners falls
through to the world (including `over_ui` pan-arming) even when the widget
animates through opaque frames.

### The API: `AssetStore.hit_opaque`
```python
def hit_opaque(self, slot_key, animation="idle", anim_time_ms=0,
               dest_size=None, rel_xy=(0, 0)) -> bool
```
- **`slot_key`** — the asset slot (e.g. a button skin).
- **`animation`** — animation row (default "idle"). Falls back to idle if missing,
  same as `frame()`.
- **`anim_time_ms`** — frame resolution time (default 0). Combined with animation
  to look up `(sheet_row, sheet_col)`.
- **`dest_size`** — the blit destination size in screen pixels. Defaults to the
  frame size; used by the nine-patch inverse to map screen coords to source.
- **`rel_xy`** — screen-space click coords `(x, y)` relative to the dest
  top-left (default `(0, 0)`). Must be clamped to `[0, dest_size[0])` ×
  `[0, dest_size[1])` by the caller (the button).
- **Returns** `bool` — `True` if the pixel at `rel_xy` is opaque (alpha > 0) in
  the resolved frame. Never raises.

### Tolerance (E-37 — degrade, never crash)
- **Placeholder** (`current_frame` returns `PLACEHOLDER`) → return `True`
  (opaque everywhere, full-rect clickable). Clients can test while art is
  missing.
- **Corrupt/missing sheet** (`_frame_surface` is `_LOAD_FAILED`) → return `True`.
  Degradation: if the sheet is gone, we assume the widget is opaque (safe for
  menu buttons in a partially-imported build).
- **Out-of-bounds `rel_xy`** — the caller must clamp; the mask will safely return
  `False` if asked to read outside the frame (a pygame mask's `get_at` raises
  on OOB, so the store must check first, or a misaligned button would crash the
  hit test). Alternatively, clamping is the button's responsibility; if it passes
  OOB coords, it is a bug upstream, not a store bug. **Document this contract in
  a docstring.**

### The mask cache
- **Key space**: `(slot_key, row, col)` — identical to `_frames` (the subsurface
  cache, `store.py:42`/`store.py:96`). Same sheet → same row/col → same surface
  subsurface; a mask can be keyed the same way.
- **Cache dict**: `self._hit_masks` beside `self._frames` (both instance dicts).
- **On miss**: `pygame.mask.from_surface(surface, threshold=0)` — **alpha > 0
  counts as opaque**. A surface with no alpha channel (a flat RGB sheet) degrades
  to all-set (every pixel is opaque) — mask.set_at will raise if you try to set
  pixels on an all-set mask, but reading always returns True, which is correct
  semantics.
- **No invalidation** — masks die with the store like everything else; when the
  manifest changes, a new AssetStore is constructed.

### The inverse transform: `dest_to_source`
Pure function in `engine/assets/nine_slice.py`:
```python
def dest_to_source(rel_xy, dest_size, src_size, margins) -> (sx, sy)
```
Maps a destination screen-space coordinate back through the nine-patch geometry
to the source frame pixel it came from.

**Inputs** (all safe, never raises):
- `rel_xy` — `(x, y)` in destination space, 0-indexed. Caller must clamp to
  bounds; reading OOB is the caller's bug, not this function's — the function
  itself never checks bounds (it is pure, with no knowledge of the destination
  size).
- `dest_size` — `(dw, dh)` final blit size in pixels.
- `src_size` — `(sw, sh)` source frame size.
- `margins` — `(left, top, right, bottom)` in SOURCE frame pixels, or `None` (→
  treated as all-zero, plain scale).

**Output**: `(sx, sy)` — source frame coords. **Both are integer** (nearest-pixel
lookup; no interpolation). If a source margin is 0, the logic below still works.

**The piecewise mapping** (exact inverse of `_nine_patch`'s band layout):
1. Clamp margins to source, then to destination — same as `_nine_patch` (lines
   `engine/render/backend.py:96-98`):
   ```
   sl, sr = _clamp_pair(margins[0], margins[2], sw)
   st, sb = _clamp_pair(margins[1], margins[3], sh)
   dl, dr = _clamp_pair(sl, sr, dw)
   dt, db = _clamp_pair(st, sb, dh)
   ```
2. Define band boundaries:
   ```
   src_cols = ((0, sl), (sl, sw - sl - sr), (sw - sr, sr))
   dst_cols = ((0, dl), (dl, dw - dl - dr), (dw - dr, dr))
   src_rows = ((0, st), (st, sh - st - sb), (sh - sb, sb))
   dst_rows = ((0, dt), (dt, dh - dt - db), (dh - db, db))
   ```
3. **Corners map 1:1**: leading corners (left/top) start at 0 in both source and
   dest; trailing corners (right/bottom) end at their respective sizes.
   ```
   # left col
   if rel_x < dl:
       sx = rel_x
   # right col (corners never resampled, so this is exact)
   elif rel_x >= dw - dr:
       sx = sw - (dw - rel_x)
   # centre col: scale by the width ratio
   else:
       mid_s = sw - sl - sr  # source centre band width
       mid_d = dw - dl - dr  # dest centre band width
       sx = sl + (rel_x - dl) * mid_s // max(1, mid_d)
   ```
   Same logic for rows with `rel_y`, `st`, `sb`, `dt`, `db`, `sh`, `dh`.

4. **All inputs clamp; never raises** (E-37):
   - Negative `rel_xy` → clamp to 0 (→ leading corner).
   - `rel_xy >= dest_size` → clamp to `dest_size - 1`.
   - `margins` larger than source → already clamped by `_clamp_pair`.
   - Integer division rounds down (nearest-pixel, consistent with pygame's
     discrete screen coords).

5. **None / all-zero margins** → plain scale:
   ```
   if margins is None or all(m == 0 for m in margins):
       sx = rel_x * sw // max(1, dw)
       sy = rel_y * sh // max(1, dh)
   ```
   This is faster and gives the same answer (all bands are "centre").

### File locations and purity
- **`engine/assets/nine_slice.py`** (NEW, pure — no pygame).
  - `clamp_pair(a, b, limit)` — moved from backend, no change.
  - `dest_to_source(rel_xy, dest_size, src_size, margins)` — the inverse.
  - No imports except stdlib (no engine, no pygame).
  
- **`engine/assets/store.py`** (pygame allowed here).
  - `AssetStore.hit_opaque(...)` method.
  - `self._hit_masks` dict beside `self._frames`.
  
- **`engine/render/backend.py`** (pygame).
  - Delete `_clamp_pair` (lines 50-68).
  - Add import: `from engine.assets.nine_slice import clamp_pair as _clamp_pair`.
  - Two calls `_clamp_pair(...)` in `_nine_patch` (lines 96-98) now use the
    imported version; otherwise no change to the function logic.
  - `render/backend.py` flow (lines 71-116) stays bit-for-bit identical after the
    import swap.

---

## 2. Architecture plan (exact edits, in order)

### 2.1 `engine/assets/nine_slice.py` (NEW FILE)

```python
"""Piecewise band mapping for nine-slice geometry.

Pure module (no pygame, no engine) — defines the coordinate transform that
inverts _nine_patch. Moved from render/backend.py in A8 so it can be used by
hit-mask code (no pygame there either).
"""


def clamp_pair(a, b, limit):
    """Opposite margins clamped PROPORTIONALLY into `limit`. On overflow
    a+b == limit exactly (the centre band vanishes, the corners squeeze)."""
    a = max(0, a)
    b = max(0, b)
    total = a + b
    if total <= limit:
        return a, b
    if total <= 0:
        return 0, 0
    a2 = a * limit // total
    return a2, limit - a2


def dest_to_source(rel_xy, dest_size, src_size, margins):
    """Map destination screen coords back to source frame coords, inverting
    the nine-patch band layout.
    
    Args:
        rel_xy: (x, y) in destination space, 0-indexed.
        dest_size: (dw, dh) final blit size in pixels.
        src_size: (sw, sh) source frame size in pixels.
        margins: (left, top, right, bottom) in source frame pixels, or None
            (treated as all-zero, plain scale).
    
    Returns:
        (sx, sy) — source frame coords, integers. Never raises; out-of-bounds
        rel_xy will resolve to an edge pixel (the caller must clamp first if
        they want to validate the hit). All inputs are safe: negative margins
        floor to 0; margins larger than source are clamped by the piecewise
        logic.
    
    Corners map 1:1 (never resampled). Edges stretch on one axis, the centre
    on both. This is the exact inverse of _nine_patch in engine/render/backend.py.
    """
    rel_x, rel_y = rel_xy
    dw, dh = dest_size
    sw, sh = src_size
    
    if margins is None or all(m == 0 for m in margins):
        # Plain scale — all bands are the centre band.
        return (rel_x * sw // max(1, dw), rel_y * sh // max(1, dh))
    
    # Clamp margins to source, then to destination (same as _nine_patch).
    sl, sr = clamp_pair(margins[0], margins[2], sw)
    st, sb = clamp_pair(margins[1], margins[3], sh)
    dl, dr = clamp_pair(sl, sr, dw)
    dt, db = clamp_pair(st, sb, dh)
    
    # Piecewise column mapping.
    if rel_x < dl:
        # Left corner: map 1:1.
        sx = rel_x
    elif rel_x >= dw - dr:
        # Right corner: map from the trailing edge.
        sx = sw - (dw - rel_x)
    else:
        # Centre column: scale by the band width ratio.
        mid_s = sw - sl - sr
        mid_d = dw - dl - dr
        sx = sl + (rel_x - dl) * mid_s // max(1, mid_d)
    
    # Piecewise row mapping (same pattern).
    if rel_y < dt:
        # Top corner: map 1:1.
        sy = rel_y
    elif rel_y >= dh - db:
        # Bottom corner: map from the trailing edge.
        sy = sh - (dh - rel_y)
    else:
        # Centre row: scale by the band height ratio.
        mid_s = sh - st - sb
        mid_d = dh - dt - db
        sy = st + (rel_y - dt) * mid_s // max(1, mid_d)
    
    return (sx, sy)
```

### 2.2 `engine/render/backend.py`

**Line 1–50**: add import at the top (after existing imports):
```python
from engine.assets.nine_slice import clamp_pair as _clamp_pair
```

**Lines 50–68**: **DELETE** the local `_clamp_pair` function (it is now
`from engine.assets.nine_slice import clamp_pair as _clamp_pair`). The two
calls in `_nine_patch` (lines 96-98 in the current code) automatically use the
imported version — no change needed there.

Everything else in the file (the `_nine_patch` function, the `_has_alpha`
function, the `draw` function) stays unchanged. The geometry logic is identical;
only the source location of `_clamp_pair` has moved.

### 2.3 `engine/assets/store.py`

**Line 42** (the `__init__` method): add a new instance dict after `self._frames`:
```python
        self._frames = {}   # (slot_key, row, col) -> Surface | _LOAD_FAILED
        self._hit_masks = {}  # (slot_key, row, col) -> pygame.mask.Mask | _LOAD_FAILED
```

**After line 67** (after the `frame` method, before the internals section):
```python
    def hit_opaque(self, slot_key, animation="idle", anim_time_ms=0,
                   dest_size=None, rel_xy=(0, 0)):
        """Opaque-pixel test for a slot's frame at a destination coord.
        
        Args:
            slot_key: asset slot key.
            animation: animation row (default "idle"); falls back to idle if
                missing, same as frame().
            anim_time_ms: frame resolution time (default 0).
            dest_size: (dw, dh) blit destination size in pixels; defaults to
                the frame size. Used by the nine-patch inverse to map screen
                coords to source.
            rel_xy: (x, y) screen-space click coords relative to dest top-left
                (default (0, 0)). Caller must clamp to bounds; reading OOB is
                the caller's bug, not this function's.
        
        Returns:
            True if the pixel at rel_xy is opaque (alpha > 0). Never raises:
            placeholder → True (opaque everywhere); corrupt/missing sheet → True
            (E-37 degradation).
        """
        from engine.assets.nine_slice import dest_to_source
        
        # Resolve the frame exactly like frame().
        ref = self._manifest.current_frame(slot_key, animation, int(anim_time_ms))
        if ref is PLACEHOLDER:
            return True  # placeholder: opaque everywhere
        
        entry = self._manifest.entry(slot_key)
        surface = self._frame_surface(entry, ref)
        if surface is _LOAD_FAILED:
            return True  # corrupt/missing sheet: degrade to opaque
        
        # Get or create the mask for this frame.
        row, col = ref
        key = (entry.slot_key, row, col)
        if key not in self._hit_masks:
            self._hit_masks[key] = pygame.mask.from_surface(surface, threshold=0)
        mask = self._hit_masks[key]
        
        # Map the destination coord back to source via the nine-patch inverse.
        if dest_size is None:
            dest_size = (entry.frame_w, entry.frame_h)
        sx, sy = dest_to_source(rel_xy, dest_size, (entry.frame_w, entry.frame_h),
                                entry.slice)
        
        # Clamp to frame bounds (safe read, OOB → False).
        if not (0 <= sx < entry.frame_w and 0 <= sy < entry.frame_h):
            return False
        
        return mask.get_at((sx, sy))
```

---

## 3. File scope + shared-file contract

**A8 edits exactly these 3 source files + 2 docs:**

| File | Change |
|---|---|
| `engine/assets/nine_slice.py` | NEW FILE: `clamp_pair`, `dest_to_source` |
| `engine/assets/store.py` | add `self._hit_masks` dict, add `hit_opaque` method |
| `engine/render/backend.py` | import `clamp_pair` from nine_slice; **delete local `_clamp_pair`** |

Plus docs: `engine/assets/CLAUDE.md`, `engine/render/CLAUDE.md`.

**Do NOT touch:** `data/schemas/` (no schema changes), `engine/assets/types.py`,
`engine/assets/manifest.py`, `engine/render/item.py`, `engine/render/renderer.py`,
`engine/render/hud.py`, any `editor/**` or `game/**` file.

**Test files A8 owns:**
- `tools/tests/test_nine_slice.py` — the `dest_to_source` inverse mapping +
  composite cross-check (synthetic 3-colour sheet through backend._nine_patch,
  assert dest_to_source-driven alpha agrees with patched.get_at on band-interior
  grid points).
- `tools/tests/test_asset_store.py` — extend `TestSlicing` with hit-mask tests
  (hole→False, opaque→True, placeholder→True, cache build).

**A1–A7 are NOT touched by A8.** This is a pure engine refactor: move one
function, add one method, add tests. No renderer changes, no HUD changes, no
game/editor integration.

---

## 4. Exit gate + Quick Test

### Commands
```
py -m unittest discover -s tools/tests -t .
py tools/testgate.py check --affected
py tools/smoke.py
```

**Gate = ZERO failures** (`GATE PASS`). No baseline, no tolerated failures —
the old "no NEW failures vs 16" policy is dead.

### New tests

**`tools/tests/test_nine_slice.py` — extend with `dest_to_source` inverse tests**
(existing tests for `_nine_patch` geometry stay; add these):
- `test_dest_to_source_corners_map_1_to_1_leading_end` — source 6×6, dest 20×20,
  margins (2,2,2,2); `(0,0)` → `(0,0)`, `(1,1)` → `(1,1)`, `(2,2)` → `(2,2)`.
- `test_dest_to_source_corners_map_1_to_1_trailing_end` — same; `(19,19)` →
  `(5,5)`, `(18,18)` → `(4,4)`, `(17,17)` → `(3,3)` (the trailing corner's
  leading pixel).
- `test_dest_to_source_centre_scales_by_band_width_ratio` — same dest 20×20 at
  source 6×6; centre band occupies `[2,4)` in source, `[2,18)` in dest; a dest
  point `(10, 10)` (centre middle) maps to source `(3, 3)` (centre middle) —
  `2 + (10 - 2) * 2 // 16 = 2 + 8*2//16 = 2 + 1 = 3`.
- `test_dest_to_source_degenerate_margins_clamp_without_raising` — margins
  (5,5,5,5) into a 6px source and 2px dest; must not raise; boundary points are
  safely clamped.
- `test_dest_to_source_none_margins_are_plain_scale` — `margins=None` and a
  non-1:1 dest; `(10, 10)` on a 20×20 dest, 6×6 source → `10*6//20 = 3` for both
  x and y.
- `test_dest_to_source_zero_margins_are_plain_scale` — `margins=(0,0,0,0)` →
  same as None (all bands are centre).
- `test_dest_to_source_out_of_bounds_clamps` — `rel_xy = (-1, 5)` → `(-1, 5)` is
  OOB in source too (negative), so clamped; `rel_xy = (25, 25)` on a 20×20 dest →
  clamped to trailing edge. Function never raises; it clamps all outputs.

**Composite cross-check (new class `TestDestToSourceGeometry`)**:
- Render a synthetic sheet (6×6, corners RED, edges GREEN, centre BLUE) through
  `backend._nine_patch` at dest 20×20, margins (2,2,2,2).
- For a grid of interior points on each band (e.g. (5,5) in the centre, (1,10)
  on the left edge, (10,1) on the top edge), map to source via `dest_to_source`,
  read the source alpha from the original sheet's `get_at()`, and assert it
  matches the patched surface's `get_at()` at the dest point (within ±1px
  tolerance for band seams — the edges are resampled and may differ slightly).

**`tools/tests/test_asset_store.py` — extend `TestSlicing` with hit-mask tests**:
- `test_hit_opaque_returns_false_for_transparent_pixel` — a frame with a hole
  (all opaque except one transparent corner pixel at (0,0)); `hit_opaque(slot,
  rel_xy=(0,0), dest_size=frame_size)` → `False`.
- `test_hit_opaque_returns_true_for_opaque_pixel` — same frame, any interior
  opaque pixel → `True`.
- `test_hit_opaque_placeholder_returns_true` — missing slot (or no sheet) →
  `True` (E-37 degradation).
- `test_hit_opaque_mask_is_cached_per_frame` — hit the same (row,col) twice;
  the second call reuses the mask (assert `len(self._hit_masks) == 1` after two
  calls, same frame).
- `test_hit_opaque_different_frames_have_different_masks` — two animations in
  one sheet; each (row,col) pair gets its own mask entry.
- `test_hit_opaque_at_stretched_dest` — a 20×20 dest of a 6×6 frame with
  margins; a corner pixel at (0,0) maps to (0,0); a centre pixel at (10,10) maps
  to the source centre and reads correctly. Verifies the `dest_to_source` call
  works end-to-end.
- `test_hit_opaque_out_of_bounds_returns_false` — `rel_xy = (100, 100)` on a
  20×20 dest → clamped, reads OOB in source, returns `False`.

**Regression pins:** existing `test_nine_slice.py` tests stay green (geometry,
cache, schema round-trip). `test_render.TestBackendThroughput` and
`test_placeholder_surfaces_do_not_leak` stay green (import swap is
transparent).

### Quick Test (headless, no live game step)
```
py tools/testgate.py check
```
Run the full test suite. All new tests must pass; no regressions. The `dest_to_source`
and `hit_opaque` implementations are pure-logic (no visual/gameplay impact until
A5′ wires the game side in). A5′ will add the live Quick Test that actually clicks
a skinned button and sees it fall through transparent corners.

**What to state in the PR:**
- Ran `py tools/testgate.py check` — ZERO failures.
- Ran `py tools/smoke.py` — manifest validation passes (the schema is unchanged).
- Confirmed no files touched outside the spec: `engine/assets/nine_slice.py` (NEW),
  `engine/assets/store.py`, `engine/render/backend.py` (import swap only), two test
  files, two docs. Zero game/editor changes.

---

## Risks / open items

None specific to A8. The design is settled and the code is pure logic. A5′ will
wire the game side (`widgets.set_skin_hit_test(assets.hit_opaque)`) and surface
any edge cases in real button behaviour.
