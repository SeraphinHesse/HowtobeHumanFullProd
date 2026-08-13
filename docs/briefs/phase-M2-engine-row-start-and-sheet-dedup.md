# Phase M2 — Engine: `row_start` + dedup by source file

Plan: `planning/GpuAndMasterSheetsPLAN.md` §6/M2 (lines 989–1027), decisions D2
(:111–119), D3 (:120–128), D10 (:161–166), risks §9 (:1311–1319).
Package doc: `engine/CLAUDE.md` → subsystem doc `engine/assets/CLAUDE.md`
(read that one; it owns the manifest-v2 optional-key conventions, the store
cache contract and the E-37 tolerance split).

M1 has landed. `data/schemas/asset_manifest.schema.json` already carries
`row_start` as an optional integer property (`:175-180`, `minimum: 0`,
`maximum: 255`) and the widened sheet pattern
`"^(imported|master)/[a-z][a-z0-9_]*\\.png$"` (`:205-208`), plus the seeded
registry `data/sprites/master_sheets.json` and the folder `data/sprites/master/`.
**Do not re-do any of that.** M2 is the engine reading what M1 stores.

---

## 1. Behavioral spec (every claim carries `file:line`)

### 1.1 Why this phase exists (measured)

**Measured** (plan §6/G0 "Asset store, warm", `planning/GpuAndMasterSheetsPLAN.md:326-337`,
`:352-356`): with every one of the 278 manifest slots resolved, the store holds
**274 sheet Surfaces for only 194 distinct source PNGs — 80 duplicate decodes
costing 58.3 MB, 62% of all sheet pixel memory**, before a single master sheet
exists. That is the justification for re-keying the sheet cache, and it grows
once ten slots share one master PNG.

### 1.2 `row_start` parsing — `engine/assets/manifest.py`

`ManifestEntry` is a frozen dataclass whose optional keys all default to a value
that makes an omitting entry byte-identical to a pre-feature one: `slice=None`
(`manifest.py:92`), `anchors=None` (`:93`), `tint_overlay=False` (`:98`).
**Add `row_start: int = 0` as the fourth**, with a comment mirroring
`tint_overlay`'s (`:94-97`): omitted ⇒ 0 ⇒ byte-identical entry (D2,
plan `:111-119`).

`entry_from_dict` is documented as the layer that **raises** on anything unusable
(`manifest.py:111-114`). Parse `row_start` in the same defensive shape as `slice`
(`:157-170`) and `tint_overlay` (`:199-201`), placed after the `tint_overlay`
block and before the `ManifestEntry(...)` construction at `:203-214`:

- absent ⇒ `0`.
- a `bool` is **not** an acceptable int here — `isinstance(True, int)` is True in
  Python, and `slice`/`anchors` guard the analogous "looks valid but isn't" case
  explicitly (`:159-161`, `:174-177`). Reject non-`int` (including `bool`,
  `float`, and a bare string — `"3"` must not silently `int()` into a window).
- negative ⇒ raise `ValueError(f"{slot_key}: row_start must be >= 0")`.
- the raise message shape matches the file's existing messages
  (`:124`, `:126`, `:169`, `:201`).

`load_manifest` is the E-37 tolerance layer and stays untouched in behaviour: it
already wraps `entry_from_dict` in `try/except ValueError` → `log.warning(...)` →
skip that entry (`manifest.py:306-311`), and it NEVER raises (`:289-292`). A
corrupt `row_start` therefore warns and drops that one slot; every other slot in
the file still loads. `load_registry` (`engine/assets/registry.py`) is a different
tolerance class and is **out of scope** — the split is described in
`engine/assets/CLAUDE.md` §"Tolerance split (E-37)" and is unchanged by this
phase.

### 1.3 The window is applied in exactly ONE place — `engine/assets/store.py`

`AssetStore._frame_surface` cuts the frame rect today at `store.py:187-188`:

```python
rect = pygame.Rect(col * entry.frame_w, row * entry.frame_h,
                   entry.frame_w, entry.frame_h)
```

The row must become `(row + entry.row_start) * entry.frame_h`. **This is the only
site in the codebase where `row_start` may be read for geometry** (plan
`:1004-1009`). Nothing else changes: `col` is untouched, `frame_w`/`frame_h` are
untouched.

`playback_order` (`manifest.py:34-55`), `Track.row` (`:76-80`, set from
`enumerate(rows)` at `:131`/`:152-153`), and `Manifest.current_frame`
(`:250-286`, which returns `(track.row, col)`) all keep meaning **"row *i* of
this entry's `rows[]`"**. Do not offset any of them, and do not add `row_start`
to `Manifest`. Those are prototype-exact animation semantics
(`manifest.py:3-8`); the window is a *slicing* concern.

A window that runs past the sheet's real row count must **degrade to the grey-X
placeholder, never raise** (E-37). This already falls out of the existing guard:
`sheet.subsurface(rect)` raises `ValueError` on an out-of-sheet rect, which is
caught, warned and cached as `_LOAD_FAILED` (`store.py:189-196`), and `frame()`
turns `_LOAD_FAILED` into `self._placeholder(slot_key)` (`:96-97`, `:155-157`).
**Verify** that path still fires with a `row_start` past the sheet height rather
than assuming it; if the warning text at `:192-194` no longer reads sensibly with
a window (it prints the entry-relative row), extend the message to name
`row_start` too — do not change the control flow.

`hit_opaque` needs **no change**: it goes through the same `_frame_surface`
(`store.py:133`) and keys its masks on `(entry.slot_key, row, col)` (`:137-142`),
which stays the entry-relative row and therefore stays correct and per-slot.

### 1.4 `_sheet` re-keys onto the source path — `engine/assets/store.py`

Today `_sheet` caches the decoded Surface under the SLOT key
(`store.py:159-176`: `slot_key = entry.slot_key` at `:160`, membership test at
`:161`, store at `:175`). Re-key both the lookup and the store onto
**`entry.sheet`** — one PNG, one `pygame.image.load`, one Surface (plan
`:1010-1014`). Keep `entry.slot_key` in the two warning messages (`:164-165`,
`:172-173`) so a failure still names a slot a designer recognises; note in a
comment that with a shared sheet only the first requesting slot is named in the
log, which is acceptable (the message already prints the resolved `path`).

Update the cache comment at `store.py:42` (`# slot_key -> Surface | _LOAD_FAILED`)
to say `sheet path -> Surface | _LOAD_FAILED`.

The `_LOAD_FAILED` marker (`store.py:26`) keeps its "already logged" role — now
per source file rather than per slot, which is strictly better: a missing PNG
shared by six slots logs once, not six times.

Two contracts survive unchanged and must be restated in the code comment:
- Frames are **subsurfaces** of the parent sheet, so the parent must stay cached
  for the store's life (`store.py:10-12`, `engine/assets/CLAUDE.md` §Store).
  Sharing the parent does not weaken that — it strengthens it.
- There is no cache invalidation; a manifest change means a new `AssetStore`
  (`store.py:12-13`).

### 1.5 What must NOT change

- `_frames` (`store.py:43`) and `_hit_masks` (`:44`) stay keyed
  `(slot_key, row, col)` — D10 (plan `:161-166`). Two slots may legitimately cut
  one plain shared PNG at different frame sizes, and a wrong key in the frame
  cache is a **silent wrong-pixels bug, not a crash** (plan §9 `:1311-1316`).
- `frame_size` precedence (`store.py:52-62`), `anchor` (`:64-72`), `offset`
  (`:74-82`), `animation_total_ms` (`:46-50`) — all untouched.
- `Manifest.override` (`manifest.py:229-237`) — untouched; it copies whole
  entries, so it carries `row_start` for free.

---

## 2. Architecture plan

1. **`manifest.py`** — add the field to `ManifestEntry`, add the parse block to
   `entry_from_dict`, pass `row_start=row_start` in the constructor call
   (`:203-214`). No new imports, no new module. The file stays pure (no pygame) —
   `engine/CLAUDE.md` §"Hard rules" lists it as a pure module and
   `test_editor_viewport.py::TestPurity` enforces the class of rule.
2. **`store.py`** — two small edits: the rect row in `_frame_surface`
   (`:187-188`) and the cache key in `_sheet` (`:160-176`). Nothing else in the
   file moves.
3. **Why `_frames`/`_hit_masks` stay slot-keyed, and why that is a CODE COMMENT,
   not just a brief line.** Deduping frames too would require folding
   `frame_w`/`frame_h`/`row_start` into the key. A reader who sees `_sheets`
   keyed by path next to `_frames` keyed by slot will read the latter as an
   oversight and "fix" it; the plan says so in as many words (`:1013-1014`).
   Leave a comment at `store.py:43-44` naming D10 and the reason: only the raw
   Surface is safe to share, because two slots may cut one PNG with different
   grids; frame-cache dedup is a **noted follow-up, deliberately not done here**
   (plan §9 `:1325-1327` lists it under "not in scope, named so it is not
   mistaken for an oversight").
4. **Why `playback_order` / `current_frame` keep their meaning.** The window is
   an entry-level slicing origin. If it leaked up into `Track.row`, every
   consumer of `(sheet_row, sheet_col)` — `SpriteAnimator`, the editor's preview,
   `hit_opaque`'s mask key — would need to know about it, and the prototype-exact
   loop/hidden semantics documented at `manifest.py:3-8` would be re-expressed
   against sheet rows instead of entry rows for no gain. Row *i* of `rows[]` is
   the animation index; `row_start` is where that array lands on the PNG.
5. **Doc update.** Add a `row_start` bullet to `engine/assets/CLAUDE.md` beside
   the existing `slice` / `anchors` / `tint_overlay` optional-key bullets (it is
   the FOURTH optional per-entry key), and amend the §Store bullet's
   "Sliced frames are SUBSURFACES" sentence to state that the sheet cache is now
   keyed by **source path**, not slot key, with `_frames`/`_hit_masks` still
   slot-keyed and why. That doc — not `engine/CLAUDE.md`, not the root router —
   is the one to edit.

---

## 3. File scope + shared-file contract

**You may edit exactly these five files. Nothing else.**

| File | Change |
|---|---|
| `engine/assets/manifest.py` | `ManifestEntry.row_start`; `entry_from_dict` parse + raise |
| `engine/assets/store.py` | `_frame_surface` row offset; `_sheet` re-key; cache comments |
| `engine/assets/CLAUDE.md` | `row_start` optional-key bullet; sheet-cache-key note |
| `tools/tests/test_assets_manifest.py` | parse + tolerance tests (§4) |
| `tools/tests/test_asset_store.py` | slicing + dedup + placeholder tests (§4) |

**Forbidden, explicitly:**
- `engine/render/backend_gpu.py` — phase **G5** owns it, and plan §9 (`:1249-1253`)
  states outright that *no phase outside G5 may touch it*.
- Every `editor/**` file. Phase **M3** is running **concurrently in a separate
  worktree** and owns `editor/master_sheet_import.py` and
  `editor/panels/master_sheet_dialog.py`.
- `data/**` (M1 landed it), `data/schemas/**`, `tools/smoke.py`, `game/**`,
  `conftest.py` (both test modules already exist and already have `TIERS`
  entries — you are adding cases to them, not new modules).

**Shared-file contract: there is none. M2 and M3 have ZERO file overlap.** M3's
files are all new files under `editor/`; M2's are all under `engine/assets/` plus
two existing test modules M3 does not touch (M3's tests land in the new
`tools/tests/test_master_sheet_import.py`). Do not go looking for a merge seam,
do not coordinate an insertion point, and do not read the M3 brief.

Nothing downstream needs a caller change: `row_start` defaults to 0 and the
sheet re-key is internal to `AssetStore`.

---

## 4. Tests — bare minimum, five cases

**Never write into `data/`**; use temp dirs (`test_asset_store.py`'s `SheetCase`
already does — `:81-90`) or `TempDataCase`, and never assert against live `data/`
content. `test_assets_manifest.py` reads schemas from the pinned snapshot
`FIXTURE_DATA` (`:24`, `:357-368`) — follow that if you touch schema validation
at all (you should not need to; M1's `TestMasterSheetSchemas` at `:357-411`
already covers the schema side).

In `tools/tests/test_assets_manifest.py` (helpers `row()` / `entry_dict()` at
`:27-48`; copy the shape of `test_bad_slice_raises` `:179-187` and
`test_bad_slice_is_warn_and_skip_through_load_manifest` `:189-199`):

1. **Corrupt `row_start` warns and skips, never raises.** `entry_from_dict`
   raises `ValueError` for each of `-1`, `"3"`, `3.5`, `True`; and one of those
   written into a manifest file goes through `load_manifest` as
   `assertLogs("engine.assets.manifest", WARNING)` + that slot absent from
   `m.slots()`, with a second good entry still present.
   *(Absent `row_start` ⇒ `entry.row_start == 0` belongs here as a one-line
   assertion in the same test class — it is the parse half of test 3.)*

In `tools/tests/test_asset_store.py` (`make_sheet` `:31-38`, `entry()` `:63-78`,
`SheetCase.store`/`frame_colour` `:87-93`; extend the local `entry()` helper with
a `row_start=None` kwarg rather than writing a second builder):

2. **`row_start: 3` resolves frames from sheet row 3.** Build a sheet with enough
   rows that row 3 is uniquely coloured, give the entry `row_start: 3`, and
   assert `frame(slot, "idle", 0)` returns row 3's colour — and that the entry's
   SECOND row (`"attack"`) resolves to sheet row 4. Extend `COLOURS` rather than
   reusing an ambiguous colour.
3. **No `row_start` resolves byte-identically to before.** Pin this explicitly —
   it is the compatibility argument for the whole re-key (plan `:1019-1020`). The
   two existing tests `test_time_resolves_to_the_right_subframe` (`:97-104`) and
   `test_second_row_uses_its_sheet_band` (`:106-113`) already assert the pre-M2
   pixels; keep them green **unchanged** and add one test that a windowless entry
   and a `row_start: 0` entry produce the same pixels.
4. **Two slots on one sheet path produce ONE Surface.** Two manifest entries with
   different `slot_key`s and the same `sheet`; assert the two resolved frames'
   `.surface.get_parent()` is the **same object** (identity, `assertIs`) AND
   assert the load count is 1 via a spy on `pygame.image.load`
   (monkeypatch it around a real call and count, `addCleanup` to restore).
   Both halves are required: identity without the count would pass on a cache
   that decodes twice and throws one away.
5. **`row_start` past the sheet height yields the placeholder.** Mirror
   `test_frame_outside_sheet_bounds_yields_placeholder` (`:344-353`): a 2-row
   sheet with `row_start: 5`, `assertLogs("engine.assets.store", WARNING)`, and
   the returned frame is placeholder-sized — no raise.

Do not build an exhaustive matrix beyond these five.

---

## 5. Exit gate + Quick Test

**Exit gate — run exactly this, nothing wider:**

```bash
py tools/smoke.py
py -m pytest tools/tests/test_assets_manifest.py tools/tests/test_asset_store.py -q
```

Both green, zero failures, zero unexpected skips. The full suite, a
`testgate check`, `--affected` and tier sweeps are **not yours** — the role table
in §"Test Suite Policy" of the root `CLAUDE.md` is the only authority and a
`PreToolUse` hook denies all four from a subagent. The single full gate run is
the main session's step at handoff.

**Quick Test (human, in the editor — not part of the coder's gate):**

1. `py editor/main.py`, open any slot in the asset tree that already has imported
   art, and confirm its preview and animation look **exactly as before** — the
   whole no-`row_start` compatibility claim, seen with eyes.
2. Point two different slots at the SAME sheet via *Use Spritesheet…* (the
   existing linking flow — no master sheet needed), reload assets, and confirm
   both still render their own frames correctly. That is the re-key under the
   condition it changes.
3. `py game/main.py`, play into a wave, and confirm every sprite still draws the
   right art and animates — a wrongly-shared parent Surface shows up as *wrong
   pixels*, not a crash, so this look is the real check.

Expected: nothing visibly changes anywhere. M2 is a memory/plumbing phase; the
row window has no designer-facing UI until M4.

---

## Notes for the reporter

- Tag the dedup claim **measured** only if you re-measure; the 58.3 MB / 80
  duplicates number is G0's measurement, cite it as such.
- If the out-of-sheet warning text at `store.py:192-194` had to grow a
  `row_start` mention, say so — it is a deliberate deviation from "control flow
  unchanged", not a silent extra.
- Widening the manifest `sheet` pattern is a one-way door for older checkouts
  (plan §9 `:1317-1319`); M1 already landed it, but it is worth one line in the
  PR body.

---

## 5. Orchestrator rulings (binding — these close the planner's open questions)

1. **Shared-sheet warning names only the first requesting slot: ACCEPTED as-is.**
   With `_sheets` keyed by path, `store.py:164-165`/`:172-173` can no longer name
   every slot that wanted a failed sheet. That is fine — the resolved path is
   already printed and it is the actionable half. Leave the required comment
   saying so. Enumerating slots is a scope change and is NOT in this phase.
2. **Extending the out-of-sheet warning's TEXT at `store.py:192-194` is
   permitted; extending its CONTROL FLOW is not.** The entry-relative row will
   read misleadingly once a window exists, so making the message say both the
   entry row and the resolved sheet row is welcome. If you change it, say so in
   your report.
3. **The Quick Test correctly stops at compatibility + plain shared-sheet
   linking.** `data/sprites/master_sheets.json` is seeded empty, so no real
   master sheet exists to window until M3/M4 land. Do NOT hand-author a master
   entry to get a live check — that crosses into `data/` and out of this phase.
   The end-to-end window look is M4's live gate.
4. **Rejecting `bool` in the `row_start` parse is CONFIRMED**, not optional.
   `isinstance(True, int)` is True in Python, so the plain int guard would admit
   `"row_start": true` as row 1. The plan did not name this case; it is a correct
   addition in the same defensive shape `slice`/`anchors` already use. Keep it
   and pin it with a test.
