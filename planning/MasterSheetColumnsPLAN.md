<!-- plan-scale: large -->
<!-- status: 1/4 sections, 3/13 phases — S1 landed, wave 2 (S2+S3+S4) next -->

# MasterSheetColumnsPLAN.md — master spritesheet COLUMNS, and the two systems that spend them

## 1. Context

`planning/completed plans/`-bound `GpuAndMasterSheetsPLAN.md` (COMPLETE
2026-08-13) gave master spritesheets a **vertical** window. `row_start` on a
manifest entry lets many characters share one PNG, each claiming its own band of
rows; the sheet owns the frame grid and a linking slot inherits it (that plan's
D3); the window is applied in exactly ONE place, `AssetStore._frame_surface`
(`engine/assets/store.py:208-213`).

There is no **horizontal** twin, anywhere:

- `MasterSheet.grid()` derives columns from the whole PNG width
  (`editor/master_sheet_import.py:304-309`) — there is no per-slot column window
  to intersect it with.
- `SheetPreview` has a row window but its source rect always starts at x=0
  (`editor/panels/sheet_preview.py:113`, `:214-216`).
- Nothing in the world-sprite path lets a caller pick a frame COLUMN. `RenderItem`
  carries slot / animation / time (`engine/render/item.py:26-35`); the column
  comes solely from the animation timeline. The only per-caller column narrowing
  that exists is `HudSprite.hidden_frames`, and it is HUD-only.

This plan adds the twin and then spends it twice.

A master sheet gains a **column width** (in frames). A slot claims a **column**.
Two systems then drive that column live instead of the designer:

1. **Building colour.** Every column of a building's master sheet is the same
   art in a different colour. A placed building rolls one at random and the
   player can change it in the construct-confirm screen or later in the upgrade
   panel — the building switches colour purely by switching master column.
2. **Seasons.** Every N rounds the season turns, and the map's gameplay tiles,
   background tiles, deco props and tile-condition art all step one column
   further along their sheets.

Every other slot keeps a **manually** set column, chosen by the designer in the
editor's Details panel.

Read `engine/assets/CLAUDE.md` (the `row_start` / Store sections),
`editor/panels/CLAUDE.md` ("Master-sheet dialog", "DetailsPanel ▸ master
sheets") and `data/CLAUDE.md` (Asset data) before touching any of this — they are
the normative spec and they win over the code graph.

## 2. Decisions (settled with the user — do not re-litigate)

- **D1 — `column_width` is measured in FRAMES, not pixels.** A master column
  spans `column_width` frame-columns, so the cut is
  `x = (column × column_width + frame_col) × frame_w`. Frames tie the value to
  the grid the sheet already owns; a raw pixel width can disagree with `frame_w`
  and produce a column boundary mid-frame.
- **D2 — Columns are MASTER-SHEET-ONLY.** `column_width` lives on the master-sheet
  registry entry; a plain `imported/<slot>.png` has no column concept. This is
  exactly the scope rule `row_start` already follows (old plan's D4) and it keeps
  a spinbox pair off every slot in the editor that would never use it.
- **D3 — A slot carries `column` (int) plus `column_mode`** (`manual` |
  `season` | `building_color`). `manual` — or the key absent — means the stored
  `column` wins. Any other mode means the live column the render path supplies
  wins, falling back to the stored `column` when the caller supplies none. The
  mode name is the designer's declaration of intent and the editor's label
  source; see D12 for what the engine is allowed to know about it.
- **D4 — Colour/season names are declared PER MASTER SHEET**, as an optional
  `columns: ["pink", "red", "purple", "yellow"]` on the registry entry. A sheet
  may author its columns in any order and offer any set. Omitted ⇒ the sheet's
  columns are unnamed and are referred to by index.
- **D5 — A building stores the column INDEX, not the colour name.**
  `BuildingSprite.column` is an int. Consequence, accepted: every sheet in one
  upgrade chain must author its colours in the same order or a building changes
  colour on upgrade. Nothing enforces it; the Master Sheets panel showing each
  sheet's `columns` side by side is the mitigation.
- **D6 — The swatches appear only on colour-capable art.** They are drawn only
  when the building's current slot links a master sheet that declares `columns`.
  A building still on a grey-X placeholder or single-column art shows nothing —
  the same degrade-quietly rule the VFX master-sheet button already follows
  (`editor/panels/vfx_preview.py:390-394`).
- **D7 — Seasons CLAMP to the last column**, they do not wrap.
  `season = era_of_round(round_num, rounds_per_season)`; the clamp happens
  per-sheet at cut time, so a 2-column sheet holds at column 1 while a 4-column
  neighbour is at 3.
- **D8 — The season-driven categories are:** the `map` category's gameplay tiles
  (`tile_buildable` / `tile_combat` / `tile_spawning` and their `_b` checker
  twins) and its **Background** group (`tile_forest`, `tile_ocean`, `tile_cliff`,
  `tile_background_1..9`); the `deco` category; the `conditions` category.
  **Not** the `backgrounds` category (`main_menu_bg`), not enemies, not
  buildings.
- **D9 — Master Sheets is a NEW TOP-LEVEL item in the selector tree**, not a leaf
  under an existing category. A master sheet is not a `slots.json` category (old
  plan's D1), so hanging it under one would misfile a cross-cutting concept the
  way `progression` would be misfiled under `buildings`.
- **D10 — An in-use sheet is FULLY LOCKED.** `GridInUseError`
  (`editor/master_sheet_import.py:49-66`) extends to `column_width`: while
  `asset_import.sheet_users` is non-empty, no slicing value may change. To change
  one, the designer Clears every linking slot first. Re-import re-opens the
  import form seeded with the sheet's current values and is refused on the same
  rule. Rejected alternative: allow it behind a confirm — changing `frame_h`
  silently invalidates every linking slot's `row_start` (a row index means
  different pixels at a new frame height), and it would need a cascade write into
  every linking manifest entry, because `AssetStore` resolves the entry's frame
  size before the registry's. The confirm can warn about that; it cannot fix it.
- **D11 — Plan scale: LARGE.** Four sections, thirteen phases (3/5/3/2), two
  waves. Wave 1 is S1 alone; S2, S3 and S4 all depend only on S1 and touch
  disjoint files, so they run concurrently in isolated worktrees.
- **D12 — The engine never learns what a season or a colour is.** It
  distinguishes `manual` from not-manual and nothing more; the enum's values live
  in `data/schemas/asset_manifest.schema.json` and their meaning lives in `game/`
  and `editor/`. This is the same line `engine/vfx/` holds against balancing key
  names.

### The one thing forced by layering, not chosen

`engine/` never reads `data/sprites/master_sheets.json` from the cut path — the
store only ever sees `entry.sheet` as an opaque relative path. So **`column_width`
is inherited onto the manifest entry**, exactly as `frame_w`/`frame_h` already
are under the old plan's D3. It is a second copy of a registry value and it
cannot drift, because D10 refuses every edit to a sheet that slots link.

### The core mechanism

`AssetStore._frame_surface` gains the column block beside the row window. This
stays the ONE place either is applied:

```python
if entry.column_mode == "manual" or column is None:
    block = entry.column
else:
    block = column                        # season index / building colour
block = min(block, max(0, sheet_cols - 1))            # D7 clamp, per sheet
sheet_row = row + entry.row_start
rect = pygame.Rect((block * entry.column_width + col) * entry.frame_w,
                   sheet_row * entry.frame_h,
                   entry.frame_w, entry.frame_h)
```

`column_width` omitted ⇒ 0 ⇒ `block * 0 + col == col` ⇒ **every existing manifest
entry resolves byte-identically**, the omit-at-default convention `slice`,
`tint_overlay` and `row_start` already follow.

Like `row_start`, this is a **slicing** concern and never a playback one.
`Track.row`, `playback_order` and `current_frame` keep meaning "row *i* / frame
*j* of THIS entry's own `rows[]`". Leaking the block upward would touch the
prototype-exact animation semantics for nothing.

## 3. Section map

| Section | Title | Phases | Depends on | Status |
|---|---|---|---|---|
| S1 | Column core — data + engine | C1, C2, C3 | — | **LANDED** (`section-S1`) |
| S2 | Editor surfaces | E1, E2, E3, E4, E5 | S1 | not started |
| S3 | Building colour | B1, B2, B3 | S1 | **PARTIAL** (`section-S3`) — B1 landed; B2+B3 unstarted, briefs ready |
| S4 | Seasons | N1, N2 | S1 | not started |

**Waves:** wave 1 = S1. Wave 2 = S2 + S3 + S4, concurrently — they share no
files, and each concurrent implementation agent gets `isolation: "worktree"` per
the root `CLAUDE.md` hard rule.

---

### Section S1 — Column core (data + engine)

**Purpose.** Put the horizontal window into the data model and into the one
function that cuts a frame, then thread a per-item column through the render
path so a caller can drive it. Nothing designer-facing and nothing game-facing
changes yet; at the end of S1 every existing entry still resolves to the exact
same pixels.

**Publishes.**
- Manifest entry keys: optional `column` (int ≥ 0), `column_mode`
  (`manual` | `season` | `building_color`), `column_width` (int ≥ 1, inherited).
- Master-sheet registry keys: required `column_width` (frames), optional
  `columns` (names).
- `ManifestEntry.column` / `.column_mode` / `.column_width`.
- `AssetStore.frame(slot_key, animation, anim_time_ms, extra_hidden=None,
  column=None)` and `AssetStore.hit_opaque(..., column=None)`.
- `RenderItem.column` and `SpriteAnimator.column`.
- `engine/assets/master_registry.py`: `load_registry(data_dir)`,
  `columns_for(doc, sheet_ref)`, `column_width_for(doc, sheet_ref)`.

**Depends on.** —

| Phase | Scope (package) | Status |
|---|---|---|
| C1 | data | *(LANDED)* `phase-C1-data-layer` @ `be45213` |
| C2 | engine | *(LANDED)* `phase-C2-manifest-store` @ `60f0954` |
| C3 | engine + editor | *(LANDED)* `phase-C3-registry-render` @ `f9c2732` |

**Section gate (measured, on the merged `section-S1`):** `py tools/smoke.py` → OK;
`py -m pytest` over the 7 touched test files → **204 passed, 49 subtests, 0
failed, 0 skipped**. Handoff: `docs/handoffs/section-S1.md`.

**Post-integration fixes (main session, on the umbrella — READ THIS BEFORE S2/S3/S4).**
The umbrella reviewer confirmed two defects in what S1 shipped; both are fixed
on the umbrella, so the surface below is what wave 2 actually codes against:

- **`RenderItem.column` is `int | None = None`, and `SpriteAnimator.column` is
  `int = -1`** — not `0`/`0` as C3 first shipped. With both defaulting to `0`
  the renderer always passed a real int, so `_column_block`'s `column is None`
  branch was unreachable on the world path and a `season`/`building_color`
  entry resolved block 0 instead of its stored `column` — a direct D3
  violation. `-1` is a sentinel (a Component field must be JSON-safe, so
  `int | None` is rejected outright) and `render_items` maps it to `None`; it
  cannot be `0`, because season 0 and colour 0 are real. **N2 consequence:**
  `band_render_items`/`visible_render_items` must take `column=None`, not
  `column=0`.
- **`import_master_sheet` now refuses an existing-but-unreadable registry**
  (`RegistryUnreadableError`, raised before the PNG copy). `load_registry_doc`
  degrades a schema-invalid registry to an EMPTY doc, which is right for
  reading and catastrophic for writing: the import merged its one entry into
  that empty doc and wrote it, deleting every other sheet. C1 making
  `column_width` required means every pre-C1 registry is schema-invalid by
  construction, so this was reachable, not theoretical.
- Minor, same commit: the D7 clamp is two-sided (`max(0, min(...))`); the
  stopgap `column_width` is clamped to the schema's own bounds via a new
  `column_width_bounds()` sibling of `frame_bounds()` (**E1 should reuse it**),
  so a >256-frame sheet can no longer fail the write *after* the PNG copy and
  strand an orphan PNG.

Gate after the fixes (measured): `py tools/smoke.py` OK; the same 7 test files →
**208 passed, 49 subtests, 0 failed, 0 skipped**.

**Still open, owned by wave 2:** `GridInUseError` compares only
`(frame_w, frame_h)` while `column_width` is written outside that tuple — once
E1 gives the designer a real field, a re-import can silently re-cut an in-use
sheet's column windows. E1 must extend the guard tuple (it is already D10's
stated intent).

#### Phase C1 — Data layer *(LANDED)*

**Goal.** The two schemas describe columns, and the one committed registry entry
is migrated. No engine or editor code.

**Files** — modified: `data/schemas/master_sheets.schema.json`,
`data/schemas/asset_manifest.schema.json`, `data/sprites/master_sheets.json`,
`data/CLAUDE.md`, `tools/tests/test_assets_manifest.py`, and the pinned fixture
copies under `tools/tests/fixtures/data/schemas/`.

**`master_sheets.schema.json`**
- `column_width` — **required** integer, `minimum: 1`, `maximum: 256`, described
  in FRAMES ("how many frame-columns one master column spans"; D1). Required, not
  optional, because the registry's existing four keys are all required and the
  file has exactly one entry to migrate.
- `columns` — **optional** array of 1..16 strings, pattern `^[a-z][a-z0-9_]*$`,
  `uniqueItems: true`; the per-column names a colour swatch or a season label
  reads (D4). Omitted ⇒ unnamed columns.
- House style, no exceptions: draft 2020-12, `additionalProperties: false`, every
  property carrying a `description` documenting units, every numeric carrying
  `minimum`/`maximum` so the editor derives its spinbox ranges rather than
  retyping them (ED-30).

**`asset_manifest.schema.json`** — three new OPTIONAL per-entry keys, the fifth
through seventh after `slice`, `anchors`, `tint_overlay`, `row_start`:
- `column` — integer, `minimum: 0`, `maximum: 255`. The 0-based master column
  this entry cuts from. Omitted ⇒ 0.
- `column_mode` — string `enum: ["manual", "season", "building_color"]`. Omitted
  ⇒ `"manual"`. The description must say what D12 says: the engine only
  distinguishes `manual` from not-manual; the named drivers are for the designer
  and the editor.
- `column_width` — integer, `minimum: 1`, `maximum: 256`. The value inherited
  from the linked master sheet (see §2 "forced by layering"). Omitted ⇒ 0 ⇒ no
  columns ⇒ byte-identical resolution.

**Migration.** `data/sprites/master_sheets.json`'s single entry
`slinger_t2_lvl3` is a 960×576 PNG at 64×96 — **measured**: 15 cols × 6 rows. It
gets `column_width: 15` (one column spanning the whole sheet) and no `columns`.

**Tests.** The migrated registry validates; a registry entry missing
`column_width` is rejected; `column_width: 0` and `column_width: 257` are
rejected; a `columns` array with a duplicate or a bad name is rejected; a manifest
entry with none of the three new keys still validates; `column: -1`,
`column_mode: "seasonal"` and `column_width: 0` are each rejected.

**Exit gate.** `py tools/smoke.py` (it fails loud on an invalid committed
registry, so the schema edit and the data edit must land together) plus
`py -m pytest tools/tests/test_assets_manifest.py -x -q`.

#### Phase C2 — Manifest parse + the frame cut *(LANDED)*

**Goal.** The engine can cut a column block out of a sheet, and caches it
correctly.

**Files** — modified: `engine/assets/manifest.py`, `engine/assets/store.py`,
`engine/assets/CLAUDE.md`, `tools/tests/test_assets_manifest.py`,
`tools/tests/test_asset_store.py`.

**Design notes**
- `entry_from_dict` parses the three keys onto `ManifestEntry` with the **exact
  defensive shape `row_start` uses** (`engine/assets/manifest.py:209-217`): no
  `int()` coercion, so a bool, a float, a numeric string or a negative all RAISE;
  `column_mode` raises on anything outside the enum. `load_manifest` stays the
  E-37 layer that turns a raise into warn-and-skip-this-entry, and
  `load_registry` stays fail-loud.
- `AssetStore._frame_surface` applies the block per §3. **This is the only place
  the column window is applied**, exactly as the row window is.
- **`_frames` and `_hit_masks` keys must gain the resolved block.** They are
  keyed `(entry.slot_key, row, col)` today (`store.py:201`, `:154`); two columns
  of one slot would collide and return silently wrong pixels — the same failure
  class the D10 comment in `store.py:48-58` warns about for sheet-keyed frames.
  The key becomes `(entry.slot_key, row, col, block)`. Leave a comment saying
  why, or the next reader will "simplify" it back.
- `sheet_cols` for the clamp is `sheet.get_width() // (entry.column_width *
  entry.frame_w)` when `column_width > 0`, else 1. A block past the real column
  count clamps (D7); a rect that still lands off the sheet degrades to the grey-X
  placeholder with a warning naming the resolved block, never raises (E-37) —
  the same path the off-sheet row already takes.
- `frame()` and `hit_opaque()` gain `column=None` as their LAST keyword argument.
  Every existing call site passes nothing and is unaffected.

**Tests.** An entry with `column_width: 4`, `column: 2` resolves frames from
frame-column `2*4 + col`; an entry with no `column_width` resolves
**byte-identically to before** (pin this explicitly — it is the compatibility
argument for the whole feature); a caller-supplied `column` overrides the stored
one when `column_mode != "manual"` and is IGNORED when it is `manual`; a block
past the sheet's column count clamps to the last column; two different columns of
one slot return two different surfaces (the cache-key pin); a corrupt `column`,
`column_mode` or `column_width` warns and skips the entry rather than raising.

**Exit gate.** `py -m pytest tools/tests/test_assets_manifest.py
tools/tests/test_asset_store.py -x -q` plus `py tools/smoke.py`.

#### Phase C3 — Master-sheet registry loader + render threading *(LANDED)*

**Goal.** Both consumer packages can read the registry, and a render item can
carry a column.

**Files** — new: `engine/assets/master_registry.py`,
`tools/tests/test_master_registry.py`. Modified: `engine/render/item.py`,
`engine/core/sprite_animator.py`, `engine/render/renderer.py`,
`editor/master_sheet_import.py`, `engine/CLAUDE.md`,
`engine/assets/CLAUDE.md`, `conftest.py` (`TIERS` entry for the new test
module), `tools/tests/test_render.py`.

**`engine/assets/master_registry.py`** — pure (no pygame, no Qt, no game
vocabulary), the sibling of `registry.py`:
- `load_registry(data_dir)` — `engine.data_io.load_validated` against
  `master_sheets.schema.json`. Fail-loud, like `load_registry` for `slots.json`:
  the registry is infrastructure.
- `columns_for(doc, sheet_ref)` / `column_width_for(doc, sheet_ref)` — resolve
  `master/<sheet_id>.png` back to its entry and return its `columns` tuple / its
  `column_width`. A ref that is not a `master/` path, or names no entry, returns
  `()` / `0` rather than raising.
- **Why `engine/` and not a copy in each package:** `game/` and `editor/` may not
  import each other and both need this. It is the same argument
  `engine/era_math.py` carries for hosting the era clock, and the same one that
  keeps the editor's previous-era preview from drifting off the runtime.
- `editor/master_sheet_import.load_registry_doc` **delegates** to it, keeping its
  own E-37 degrade-to-empty-doc wrapper. `write_registry_doc` is untouched and
  remains the ONE write path.
- Add both the new module and nothing else to `TestPurity`'s import list only if
  a new *editor* module is created — this one is engine, so it does not apply.

**Render threading**
- `RenderItem` gains `column: int = 0`, appended last (it is a frozen dataclass
  and every field has a default, so appending is safe; existing positional call
  sites are unaffected).
- `SpriteAnimator` gains `column: int = 0` — a declared, JSON-safe Component
  field, so it serializes for free — and passes it in `render_items`.
- `Renderer.flush` passes `item.column` into
  `self._assets.frame(...)` at `engine/render/renderer.py:203`. The HUD pass is
  **not** given a column: `HudSprite` gains no such field, the same scope
  decision `slice`, `crop_rect` and `hidden_frames` already carry.

**Tests.** `load_registry` round-trips a fixture registry and fails loud on an
invalid one; `columns_for`/`column_width_for` return the empty values for an
`imported/` ref and for an unknown sheet; the editor's `load_registry_doc` still
degrades to an empty doc on a missing/corrupt file; a `RenderItem` with a
non-zero `column` reaches `AssetStore.frame` with it (spy on the store);
`column=0` produces a byte-identical `DrawCall` to before.

**Exit gate.** `py -m pytest tools/tests/test_master_registry.py
tools/tests/test_render.py tools/tests/test_master_sheet_import.py -x -q` plus
`py tools/smoke.py`.

---

### Section S2 — Editor surfaces

**Purpose.** Give the designer everything the data model now allows: import a
column-sliced master sheet, set a slot's column and mode, preview any column, and
manage every registered sheet from one place.

**Publishes.** The master-sheet import form's `column_width` + `columns` fields;
`MasterSheet.columns`; `SheetPreview`'s column window; the Details panel's Column
/ Column-mode controls; the viewport's column switcher; a **Master Sheets**
top-level selector item backed by `editor/panels/master_sheets.py`.

**Depends on.** S1.

| Phase | Scope (package) | Status |
|---|---|---|
| E1 | editor | not started |
| E2 | editor | not started |
| E3 | editor | not started |
| E4 | editor | not started |
| E5 | editor | not started |

#### Phase E1 — Import path

**Goal.** A master sheet can be imported with a column width and column names.

**Files** — modified: `editor/master_sheet_import.py`,
`editor/panels/master_sheet_dialog.py`, `editor/panels/CLAUDE.md`,
`tools/tests/test_master_sheet_import.py`.

**Design notes**
- `import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h,
  column_width, columns=())` — the two new arguments are written into the
  registry entry; `columns` is omitted from the entry when empty (the
  omit-at-default convention).
- `MasterSheet` gains `column_width` and `columns`, and `grid()` gains a
  `columns` count derived as `width // (column_width * frame_w)`. The docstring's
  existing warning stands: no caller may supply a frame size, and now no caller
  may supply a column width either — the sheet owns both.
- **`GridInUseError` extends to `column_width`** (D10). The guard at
  `master_sheet_import.py:246-269` compares `(frame_w, frame_h)` today; it
  compares `(frame_w, frame_h, column_width)` after this phase, and still raises
  BEFORE the PNG copy and the registry write. It keeps subclassing `ValueError`
  on purpose so the dialog's existing `except (OSError, ValueError)` catches it.
- Two new rows in `_build_import_box` (`master_sheet_dialog.py:104-139`): a
  **Column width** `_NoWheelSpinBox` whose range comes from the schema via the
  existing `frame_bounds` idiom (extend it, or add a sibling — never retype the
  bounds, ED-30), and a **Colours** `QLineEdit` taking a comma-separated list,
  slugified and validated against the schema's pattern before the write. Both
  thread through `perform_import()`.
- `pad_to_frame` remains deliberately absent. Centring would mis-cut every column
  window exactly as it would mis-cut every row window.
- **E1 MUST SUPERSEDE S1's STOPGAP.** Making `column_width` required on the
  registry broke every editor import, and no S1 phase owned the fix, so C3
  shipped `import_master_sheet` writing `column_width: max(1, sheet_w //
  frame_w)` (`editor/master_sheet_import.py:303`) — one column spanning the
  whole sheet, behaviour-preserving, no art moves. Replace that derivation with
  the real designer-supplied argument above; do not leave both. Its 256-frame
  schema cap also means a sheet wider than 256 frames is currently refused —
  the designer field inherits the same bound, which is correct, but say so in
  the spinbox tooltip.

**Tests.** Import writes `column_width` and `columns` into a schema-valid entry;
an empty colour list omits the key; slugification and rejection cases for colour
names; `GridInUseError` fires on a `column_width` change with users and does not
fire with none; `MasterSheet.grid()` reports the right column count; the dialog
constructs, collects the two new fields and imports without opening a modal.
Bare-minimum coverage — no exhaustive Qt matrix.

**Exit gate.** `py -m pytest tools/tests/test_master_sheet_import.py -x -q` plus
`py tools/smoke.py`.

#### Phase E2 — `SheetPreview` column window

**Goal.** The raw-sheet inspector can show one column instead of the whole sheet.

**Files** — modified: `editor/panels/sheet_preview.py`,
`editor/panels/CLAUDE.md`, `tools/tests/test_details_panel.py` (its
`TestSheetPreviewRowWindow` neighbours).

**Design notes.** The exact mirror of the row window
(`sheet_preview.py:82-121`): `set_sheet(png, fw, fh, row_start=0, row_count=None,
col_start=0, col_count=None)`, opt-in, defaulting to the whole sheet, **applied in
exactly one place — the `paintEvent` source rect** (`:211-217`). Cell captions and
the `frame_clicked(row, col)` signal keep speaking WINDOW-RELATIVE indices on
both axes, for the same one-vocabulary reason the row window already does: the
preview and the `RowEditor`s below it must not be able to disagree about what
"frame 1" means. Add a `column_window()` accessor beside `row_window()`.

**Tests.** A column window narrows the drawn source rect and the cell grid;
`frame_clicked` on the first visible column reports column 0; a `col_count` past
the sheet's real columns clamps; the default arguments render byte-identically to
before.

**Exit gate.** `py -m pytest tools/tests/test_details_panel.py -x -q` plus
`py tools/smoke.py`.

#### Phase E3 — DetailsPanel column controls

**Goal.** A slot linked to a master sheet gets its column and its mode.

**Files** — modified: `editor/panels/details.py`, `editor/panels/CLAUDE.md`,
`tools/tests/test_details_panel.py`.

**Design notes**
- A new row under the existing `using rows [ ] til [ ]` row
  (`details.py:404-422`), built the same way: a `QHBoxLayout` of `QLabel` + a
  `_NoWheelSpinBox` **imported from `editor.panels.balancing`** (their one home —
  never a bare `QSpinBox`; the mousewheel is navigation-only across this editor)
  committing on `editingFinished`, plus a `_NoWheelComboBox` for the mode
  (Manual / Season / Building colour).
- A read-only display of the **inherited `column_width`** with a tooltip saying
  the master sheet owns it — the same treatment the Frame W/H spins get
  (`details.py:796-800`).
- Visibility is gated by the existing `_master_applies()`
  (`details.py:770-775`), which tests the `sheet` ref's `master/` prefix, not the
  category. D2 in one line.
- The column spin's ceiling is the sheet's real column count, so an off-sheet
  column is unrepresentable (ED-30) rather than an error found at save time.
- **`_on_column_changed` writes NOTHING** — copy `_on_row_window_changed`
  (`details.py:818-838`), not `_on_frame_size_changed`. The column is entry
  state, saved by Save like every other row edit; `slots.json` must not be
  touched.
- `draft_entry()` omits `column` at 0, `column_mode` at `"manual"`, and
  `column_width` at 0, and **preserves all three on any path that does not author
  them** — the convention `row_start` and `anchors` already follow
  (`details.py:734-748`).
- `use_master_sheet()` adopts the sheet's `column_width` into the entry alongside
  `frame_w`/`frame_h`.

**Tests.** The row appears only for a master sheet; setting the column re-cuts the
preview and writes nothing until Save; save writes the three keys and omits each
at its default; a panel path that does not author them preserves an existing
value; selecting a master sheet adopts its `column_width`; the spin's ceiling is
the sheet's last column.

**Exit gate.** `py -m pytest tools/tests/test_details_panel.py -x -q` plus
`py tools/smoke.py`.

#### Phase E4 — Viewport preview column switcher

**Goal.** "Options to switch column in the preview just like which animation."

**Files** — modified: `editor/panels/viewport.py`, `editor/CLAUDE.md`,
`tools/tests/test_editor_viewport.py`.

**Design notes.** A third floating `_NoWheelComboBox` child pinned beside the
animation combo (`viewport.py:272-277`), with a `_refresh_column_combo()` twin of
`_refresh_anim_combo()` (`viewport.py:1636-1648`) — `blockSignals` → clear →
`addItems` → fall back to the first entry if the current one is gone →
`setVisible(bool(columns))`. Labels come from the linked sheet's `columns` when
declared, else `Column N` (D4). It is draft-aware like `preview_animations()`
(`viewport.py:428-434`), hidden in map and screen mode alongside the other two
combos (`:477`, `:523`), and its value rides onto the preview `RenderItem`'s new
`column` field (`viewport.py:1885-1893`).

**Tests.** The combo lists a master sheet's columns by name and falls back to
`Column N` without names; it is hidden for a non-master slot and in map/screen
mode; selecting a column changes the submitted `RenderItem.column`; an unsaved
draft's column is reflected.

**Exit gate.** `py -m pytest tools/tests/test_editor_viewport.py -x -q` plus
`py tools/smoke.py`.

#### Phase E5 — Master Sheets panel

**Goal.** One place that lists every registered master sheet, shows its slicing
values and its users, and can re-import it.

**Files** — new: `editor/panels/master_sheets.py`,
`tools/tests/test_master_sheets_panel.py`. Modified:
`editor/panels/selector.py`, `editor/main.py`, `editor/CLAUDE.md`,
`editor/panels/CLAUDE.md`, `conftest.py` (`TIERS`),
`tools/tests/test_editor_panels.py`, `tools/tests/test_editor_viewport.py`.

**Design notes**
- **Selector registration** copies the Timeline leaf, the newest and cleanest
  instance of the pattern (`selector.py:114`, `:122`, `:143`, `:237-247`,
  `:578-584`): a new marker role, a label constant, a `master_sheets_selected`
  `Signal`, an item, and a branch in `_emit_selection` — placed **before** the
  `_PAYLOAD_ROLE` fall-through (`:607-610`), which unpacks unconditionally. It is
  a NEW TOP-LEVEL item (D9), added outside the `for category in
  self.registry.categories()` loop; `addTopLevelItem` at `:187` is the only
  top-level insertion today and nothing forbids a second. The hard invariant
  holds: a single-document leaf emits its own signal and **never**
  `node_selected`, or the entity-preview machinery reacts.
- **Shell wiring** copies `_on_timeline_selected` (`editor/main.py:1383-1390`):
  construct the panel beside the others (`:169-185`), connect the signal
  (`:308-332`), add the `right_stack` page (`:509-516`), and reload on entry.
  **`tools/tests/test_editor_viewport.py:1343` hard-asserts
  `right_stack.count() == 8`** — it becomes 9.
- **The panel.** A list of every registry entry (reuse
  `master_sheet_import.master_sheets(data_dir)`, which is registry-driven, not a
  folder glob) with, per selection: display name, real pixel size, grid,
  `column_width`, `columns`, and its users — the refcount comes from
  `asset_import.sheet_users` (there is exactly ONE refcount in this editor, not
  two), and an embedded read-only `SheetPreview`.
- **Editing.** Slicing values are editable only while the sheet has no users; with
  users, the controls are disabled and a label names the linking slots and says to
  Clear them first (D10). **Re-import** re-opens the import form seeded with the
  sheet's current values; it overwrites the PNG bytes in place and keeps the id
  and every link, and is refused by the same `GridInUseError` rule if the seeded
  values are changed while slots link.
- **Construction is split from display** so no test `exec()`s a modal — the rule
  `sheet_picker.py` and `master_sheet_dialog.py` both follow.
- **The new module goes into `TestPurity`'s import list**
  (`tools/tests/test_editor_viewport.py:1494-1530`) — every new editor module
  does.

**Tests.** The panel constructs and lists exactly what the registry holds; the
detail text reports grid, `column_width`, `columns` and user count; slicing
controls are disabled for an in-use sheet and enabled for an unused one; an edit
to an unused sheet writes a schema-valid registry through `write_registry_doc`;
re-import replaces the PNG and preserves the id and the links; the selector emits
the new signal plus `domain_selected` and never `node_selected`; `right_stack`
count and page routing.

**Exit gate.** `py -m pytest tools/tests/test_master_sheets_panel.py
tools/tests/test_editor_panels.py -x -q` plus `py tools/smoke.py`; then a **live
`py editor/main.py`**: open Master Sheets, confirm the list, re-import a sheet,
confirm an in-use sheet refuses a slicing edit and names its slots. State that it
was a live run.

---

### Section S3 — Building colour

**Purpose.** A placed building rolls a random colour column, keeps it across
upgrades, and the player can change it from the construct-confirm screen and the
upgrade panel.

**Publishes.** `BuildingSprite.column` as the building's colour; the host's
`{slot_key: colour_names}` capability map; colour swatches in both screens; a
`BuildingColors` name→RGB map in `data/balancing/ui.json`.

**Depends on.** S1.

| Phase | Scope (package) | Status |
|---|---|---|
| B1 | game | *(LANDED)* `phase-B1-colour-state` @ `bf53459` |
| B2 | game | *(NOT LANDED)* brief `docs/briefs/phase-B2-construct-swatches.md`; branch `phase-B2-construct-swatches` cut, coder never committed |
| B3 | game + data | *(NOT DISPATCHED)* brief `docs/briefs/phase-B3-upgrade-swatches.md`; reuses B2's helper |

**Section S3 note.** The reconciled cross-phase interface — `place_building`'s
final signature (`state=None, colour_columns=None, rng=None, column=None`), the
host-derived `colour_columns` capability map, B2's `ColorSwatchRow` helper and
B3's `BuildingColors` schema shape — is recorded in `docs/handoffs/section-S3.md`.

#### Phase B1 — Colour state, the roll, and the render

**Goal.** A building has a colour column and renders at it.

**Files** — modified: `game/buildings/registry.py`, `game/main.py`,
`game/buildings/CLAUDE.md`, `tools/tests/test_buildings.py`.

**Design notes**
- **The colour IS `BuildingSprite.column`** (inherited from S1's
  `SpriteAnimator.column`). One source of truth, no second component to keep in
  sync, and it is a declared JSON-safe Component field so it serializes for free.
  It **survives an upgrade automatically**, because `Building.apply_tier_stats`
  (`game/buildings/building.py:182-192`) rewrites only `anim.slot_key`.
- The roll happens in `registry.place_building` (`:145-161`), right where
  `_tile_condition` is already stamped, from an **injected rng** so a seeded test
  is possible — never the stdlib `random` module directly, the rule
  `engine/vfx/emitters.py` already holds.
- **The capability map.** `game/main.py` builds `{slot_key: (colour names,)}`
  once at boot from `engine.assets.master_registry` + the manifest, and passes it
  down. This is the `condition_art` precedent
  (`game/map/conditions.py`) exactly: the HOST does the art-derived lookup so
  `game/ui` never touches the asset layer, and a slot absent from the map simply
  has no colours (D6, E-37).
- A building whose slot offers no colours keeps `column = 0` and is untouched.

**Tests.** Placement rolls a column inside the slot's colour count with a seeded
rng; a slot with no colours stays at 0; the column survives `apply_tier_stats`
across a tier and a level change; the submitted `RenderItem` carries it.

**Exit gate.** `py -m pytest tools/tests/test_buildings.py -x -q` plus
`py tools/smoke.py`. Quick Test: place a colour-capable building twice and see
two different colours.

#### Phase B2 — ConstructPreview swatches

**Goal.** The four colour buttons in the build-confirm modal, changing the
preview live.

**Files** — modified: `game/ui/building_ui.py`, `game/ui/CLAUDE.md`,
`tools/tests/test_building_ui.py`, `tools/tests/test_ui_min_targets.py`.

**Design notes**
- N square `widgets.Button(rect, label="")` swatches built in
  `ConstructPreview.__init__` after the dice button (`building_ui.py:356`),
  registered in the `ids` dict at `:362` so `skinning.apply` sees them,
  hit-tested in `handle_click` **before** the `name_rect` branch (`:424`), and
  drawn in `submit`'s BUTTON block (`:458-469`), never the text block — the
  panel → buttons → text order at `:445-447` is deliberate.
- **≥12 logical px on the smaller dimension** — `tools/tests/
  test_ui_min_targets.py` asserts it for every `kind == "button"` (UR-5). An
  unlabelled swatch satisfies the static-label check trivially.
- The modal is height-constrained (the 5-row defence case bottoms at `y+124`
  against a button row top of `y+126`, `:485-496`) — the swatch row must fit
  without pushing the stat list.
- The swatches appear only when the host's capability map has colours for this
  building's slot (D6). Clicking one sets the pending colour and the preview
  redraws in it immediately.
- Colours are read as `widgets.<NAME>` attribute access, never
  `from .widgets import <NAME>` — `configure_palette` rebinds module attrs at
  boot.

**Tests.** The swatches exist only for a colour-capable slot; a click returns the
right colour index; the placed building carries the picked column; the min-target
floor holds.

**Exit gate.** `py -m pytest tools/tests/test_building_ui.py
tools/tests/test_ui_min_targets.py -x -q` plus `py tools/smoke.py`. Quick Test:
open the confirm modal on a colour-capable building, click each swatch, watch the
preview change, confirm, and see the placed building in that colour.

#### Phase B3 — Upgrade-panel swatches + the colour palette

**Goal.** The same row in the upgrade panel, and the swatch colours come from
data.

**Files** — modified: `game/ui/building_ui.py`, `data/balancing/ui.json`,
`data/schemas/ui.schema.json`, `data/ui/screen_defaults.json` (regenerated),
`game/ui/CLAUDE.md`, `tools/tests/test_building_ui.py`,
`tools/tests/test_ui_skinning.py`.

**Design notes**
- The same swatch row in `BuildingUI` upgrade mode, in the free band between the
  stat column's worst case (y≈268) and the action button top (`view_h - 60`), or
  below `move_btn` (`:1394-1413`). Laid out in `_build_upgrade`/
  `_layout_upgrade_rows`, which run **before** `skinning.apply`.
- **`BuildingColors`** — a new group in `data/balancing/ui.json` mapping a colour
  name to `[r, g, b]`, added per `/add-balancing-value` (JSON + schema with
  description and bounds; the editor's balancing panel picks it up by recursing
  the schema, no editor code). It exists because the shared palette has no pink —
  `game/ui/overlays.py:76-89` records reusing `C_PURPLE` as "the closest existing
  colour to pink". A `columns` name with no entry here degrades to a neutral
  swatch rather than raising.
- **Adding widget ids means regenerating** `data/ui/screen_defaults.json` via
  `py tools/export_ui_layouts.py` and updating the golden baseline in
  `tools/tests/test_ui_skinning.py`. Note `building_panel`'s baseline is `[]`
  because the export harness never selects a building — add a mock builder in
  `tools/screen_mocks.py` if the swatches must be covered.

**Tests.** The upgrade panel shows the swatches only for a colour-capable
building; clicking one changes the live building's column; the RGB comes from
`ui.json` and an unknown name degrades; the regenerated defaults match the
golden baseline.

**Exit gate.** `py -m pytest tools/tests/test_building_ui.py
tools/tests/test_ui_skinning.py -x -q` plus `py tools/smoke.py`. Quick Test:
build, upgrade a tier, open the upgrade panel, change the colour, and confirm it
holds across the next upgrade.

---

### Section S4 — Seasons

**Purpose.** Every N rounds the season turns and four tile render paths step one
column further along their sheets.

**Publishes.** `Seasons.rounds_per_season` in `data/balancing/core.json`;
`RunState.season`; a `column=` argument on the tilemap emitters and the game's
deco / condition submit paths.

**Depends on.** S1.

| Phase | Scope (package) | Status |
|---|---|---|
| N1 | game + data | not started |
| N2 | game + engine | not started |

#### Phase N1 — The season clock

**Goal.** The run knows which season it is in, and says so exactly once per
round.

**Files** — modified: `data/balancing/core.json`, `data/schemas/core.schema.json`,
`game/core/game_state.py`, `game/main.py`, `game/core/CLAUDE.md`,
`tools/tests/test_game_state.py`, `tools/tests/test_balance_data.py`.

**Design notes**
- New `Seasons` group in `core.json` with `rounds_per_season` (integer, default
  **10**, `minimum: 1`), added per `/add-balancing-value` — JSON + schema with a
  description and bounds, read by direct indexing
  (`core_balance["Seasons"]["rounds_per_season"]`), **never `.get()`** (D-2: it
  must fail loud when the schema requires the key).
- `RunState.season: int = 0`, recomputed from
  **`engine.era_math.era_of_round(round_num, rounds_per_season)`**. That function
  already is `(round − 1) // N` with a round ≤ 0 guard
  (`engine/era_math.py:46-52`) — it is exactly the season formula, so **no new
  math is written**. Reuse it; do not add a `season_of_round` twin.
- Recompute on the round edge. `state.round_num += 1` happens in exactly one
  place, `game/core/payday.py:277`; the host's phase-edge watcher chain
  (`game/main.py:1710-1750`, `gp["prev_phase"]`) is the idiomatic place to notice
  it. Pick one and say which in the phase report.
- **A season change invalidates the ground cache** (`ground_cache.invalidate`, the
  hook already wired to `tile_map.on_zone_change` at `game/main.py:774`). Once per
  N rounds, on the edge — it must not fire per frame.

**Tests.** `era_of_round` gives 0 for rounds 1..10 and 1 for 11..20 at
`rounds_per_season = 10` (a pin, not a new function); `RunState.season` advances
exactly once per N rounds and never mid-round; the ground cache is invalidated on
change and not otherwise; the new balancing key validates and is read by
indexing.

**Exit gate.** `py -m pytest tools/tests/test_game_state.py
tools/tests/test_balance_data.py -x -q` plus `py tools/smoke.py`.

#### Phase N2 — The four render paths

**Goal.** Seasonal slots follow the season; everything else is untouched.

**Files** — modified: `engine/tilemap.py`, `engine/CLAUDE.md`, `game/main.py`,
`game/map/spawn_deco.py`, `game/map/conditions.py`, `game/map/CLAUDE.md`,
`tools/tests/test_tilemap_model.py`, `tools/tests/test_map_conditions.py`.

**Design notes**
- `band_render_items` and `visible_render_items` gain a `column=0` keyword that
  rides onto every emitted `RenderItem`. `engine/tilemap.py` learns nothing about
  seasons — it takes an int, the same way it already takes `tint_for_code`.
- The four submit sites all pass `column=state.season`:
  gameplay + background tiles through the ground cache's `band_render_items`
  callback (`game/main.py:1877-1886`); map-authored deco through
  `visible_render_items` (`:1889-1892`); runtime spawn-band trees
  (`game/map/spawn_deco.py:56-96`); tile conditions
  (`game/map/conditions.py:24-64`).
- **Passing it everywhere is safe**: a slot left on `column_mode: "manual"`
  ignores it entirely (D3/§3), and a slot with no `column_width` resolves
  byte-identically. So no per-slot opt-in list is needed in code — the designer's
  mode flag IS the opt-in.
- The `backgrounds` category (`main_menu_bg`) and every enemy and building path
  are deliberately untouched (D8).

**Tests.** A seasonal slot at season 2 resolves frames from column 2; a manual
slot at the same season resolves from its stored column; a slot with no
`column_width` is byte-identical; the season clamps per-sheet on a 2-column sheet
(D7); each of the four submit paths carries the column.

**Exit gate.** `py -m pytest tools/tests/test_tilemap_model.py
tools/tests/test_map_conditions.py -x -q` plus `py tools/smoke.py`; then a **live
`py game/main.py`**: import a multi-column tile sheet, mark it `season`, cheat to
round 11 and 21, and watch the tiles step. State that it was a live run.

---

## 4. Verify (whole plan)

**Test policy is role-scoped and lives in ONE place**: §"Test Suite Policy" in the
root `CLAUDE.md`, enforced by `.claude/hooks/test_guard.py`. Every phase gate
above is `py tools/smoke.py` plus the targeted test files that phase touched —
which is what a subagent may run. **The single full `py tools/testgate.py check`
happens once, in the MAIN SESSION, at `/commitpushpr` stage 5** — after the PR is
up and after `Development` has been merged down. Never in a phase, never twice.

End-to-end Quick Test once all four sections land:

1. `py editor/main.py` → **Master Sheets** → import a 4-column sheet with a
   column width and colour names. Confirm the list shows its grid, its columns
   and its users, and that an in-use sheet refuses a slicing edit.
2. Point a building slot at it and set **Column mode = Building colour**; point a
   `deco` and a `conditions` slot at a seasonal sheet with mode **Season**; leave
   a third slot on **Manual** at column 2. Switch columns in the viewport
   preview and confirm the art changes.
3. `py game/main.py` → place that building: it comes up in a random colour; the
   swatches in the confirm modal change it live; confirm; reopen the upgrade
   panel and change it again; upgrade a tier and confirm the colour holds.
4. Cheat to round 11 and 21: the seasonal tiles, deco and conditions each step
   one column, and hold at the last column past the end.
5. A slot whose sheet has fewer columns than the current season shows its last
   column, never a grey X. A slot on Manual never moves.

## 5. Risks / open items

- **A locked in-use sheet has exactly one recovery path: Clear every linking
  slot.** That is D10's price — a wrong `column_width` discovered after linking
  twelve background slots means twelve unlinks. Recorded deliberately; revisit if
  it actually bites.
- **The `_frames` / `_hit_masks` cache key is the sharpest edge in this plan.**
  Forgetting the block is a silent wrong-pixels bug, not a crash. C2's tests must
  pin two columns of one slot resolving to two different surfaces.
- **Per-sheet clamping means tiles can disagree about the season** — a 2-column
  sheet sits at column 1 while a 4-column neighbour is at 3. That is what
  clamp-to-last buys (D7); it is a content problem, not a code one.
- **D5 (index, not name) means an upgrade chain must author its colours in the
  same order.** Nothing enforces it. The Master Sheets panel showing each sheet's
  `columns` is the mitigation.
- **`column_width` is duplicated onto every linking manifest entry.** Forced by
  layering, not chosen (§2). It cannot drift only because D10 refuses in-use
  edits — if D10 is ever relaxed, this becomes a real cascade-write problem.
- **No art exists yet.** Every new path degrades to column 0 or the grey-X
  placeholder, so all thirteen phases can land and be verified before a single
  multi-column sheet is drawn. The live gates on E5, B2/B3 and N2 need one
  throwaway test sheet each.
- **`right_stack.count() == 8`** at `tools/tests/test_editor_viewport.py:1343` is
  a hard pin that E5 must update.
- **`data/sprites/master_sheets.json` migration** — one entry, but `tools/smoke.py`
  fails loud on an invalid committed registry, so C1's schema edit and data edit
  must land in the same commit.
