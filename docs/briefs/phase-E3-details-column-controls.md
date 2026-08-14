# Phase E3 — DetailsPanel column controls

Part of `planning/MasterSheetColumnsPLAN.md`, Section S2 (`section-S2`), Wave 2.
Builds on Phase E2 (`SheetPreview` column window), landed on
`phase-E2-sheet-preview-columns` @ `ee418a7`. **All `file:line` citations below
are against that commit** — verify they still match on the branch you actually
start from (E3's own worktree should be cut from E2's landed state, not from
`Development` and not from bare `section-S2`, which as of this writing is one
commit behind E2).

**Goal (plan).** A slot linked to a master sheet gets its column and its mode:
a `column` spin, a `column_mode` combo (Manual / Season / Building colour),
and a read-only display of the inherited `column_width` — the horizontal twin
of the row window E2 just gave the preview.

## 1. Behavioral spec

- **The row-window row it sits under** — `QHBoxLayout` of `QLabel` +
  `_NoWheelSpinBox` pairs, built in `DetailsPanel.__init__`
  (`editor/panels/details.py:404-422`), added to the panel's layout at
  `details.py:443` (`layout.addWidget(self._master_row)`) and hidden by
  default at `details.py:449` (`self._master_row.setVisible(False)`). Your new
  row is the same shape, placed immediately after it.
- **`_NoWheelSpinBox`/`_NoWheelComboBox` come from `editor.panels.balancing`**
  — already imported at `details.py:55`. Never construct a bare `QSpinBox` or
  `QComboBox`; the mousewheel is navigation-only across this editor.
- **The Frame W/H "read-only while a master sheet is linked" treatment** —
  `_refresh_master_state` (`details.py:792-816`) disables the spins and sets a
  tooltip while `_master_applies()`:
  ```python
  for spin in (self._frame_w, self._frame_h):
      spin.setEnabled(not master)
      spin.setToolTip(MASTER_GRID_TOOLTIP if master else "")
  ```
  (`details.py:798-800`). Your `column_width` display gets the identical
  treatment — a disabled `_NoWheelSpinBox` (not a plain `QLabel`), so keyboard
  focus/tab order and styling stay consistent with every other panel field.
- **`_master_applies()`** (`details.py:770-775`) tests the `_sheet_ref`
  prefix (`MASTER_PREFIX = "master/"`, `details.py:69`), not the category —
  D2 in one line. This is your visibility gate, reused verbatim.
- **`_on_row_window_changed`** (`details.py:818-838`) is the "writes nothing"
  pattern to copy: guarded by `self._loading`/`self.slot_key is
  None`/`not self._master_applies()`, it updates in-memory state, re-derives
  the preview, and calls `self._emit_draft()` — never `self._write_doc(...)`.
  **`_on_frame_size_changed` is the opposite pattern (writes `slots.json`) and
  must NOT be copied for columns** — the column is entry state, saved by Save
  like every other row edit.
- **`draft_entry()`** (`details.py:712-748`) is where every optional,
  omit-at-default key gets added to the saved entry. The row-window block is
  the template (`details.py:736-742`):
  ```python
  if self._master_applies():
      if self._row_start:
          entry["row_start"] = self._row_start
  elif existing and existing.get("row_start"):
      entry["row_start"] = existing["row_start"]
  ```
  `column` (omit at 0), `column_mode` (omit at `"manual"`) and `column_width`
  (omit at 0) each need this exact two-branch shape: author it while
  `_master_applies()`, else **preserve** whatever `existing` already had. Get
  this wrong and a path that doesn't even show the row (a plain
  `imported/<slot>.png` entry, or a master entry loaded before this phase
  shipped) will silently erase a previously-saved column on next Save.
- **Schema bounds** (`data/schemas/asset_manifest.schema.json`): `column` is
  an integer 0..255 (mirrors `row_start`'s range exactly — reuse `(0, 255)`,
  do not retype the bound elsewhere, ED-30); `column_mode` is the enum
  `manual`/`season`/`building_color`; `column_width` is 1..256 when authored
  (0 is legal only as the absent-key in-memory default, never a value you
  write).
- **`use_master_sheet()`** (`details.py:654-700`) is where a fresh link
  adopts the sheet's grid — `self._master_grid = (sheet.frame_w,
  sheet.frame_h)` at `details.py:683`. Add the `column_width` adoption right
  beside it.
- **`_reset_row_window()`** (`details.py:785-790`) is called from every
  non-master path (`import_sheet`, `use_sheet`, `clear_entry`) to snap the
  row window back to "whole sheet, row 0". Extend it to also reset
  `self._column`/`self._column_mode`/`self._column_width`/`self._sheet_cols`
  — the same "column only ever means something on a master sheet" rule D2
  already states for the row window.
- **`_load_sheet`** (`details.py:983-1027`) computes `cols, sheet_rows = w //
  fw, h // fh` at `details.py:989` and only stores `self._sheet_rows`. Store
  `self._sheet_cols = cols` alongside it — you need the sheet's real
  frame-column count to compute the column spin's ceiling
  (`sheet_cols // column_width`, per the plan's "core mechanism" pseudocode,
  §2 of the plan doc around line 130).
- **`_refresh_preview()`** (`details.py:1047-1063`) is the one place
  `SheetPreview.set_sheet` is called, already passing the row window:
  ```python
  self._preview.set_sheet(self._sheet_file(self._sheet_ref), fw, fh,
                          row_start=self._row_start,
                          row_count=len(self._row_editors))
  ```
  (`details.py:1053-1055`). Extend this call with `col_start=` /
  `col_count=` when `_master_applies()` and `self._column_width > 0`:
  `col_start = self._effective_column() * self._column_width`, `col_count =
  self._column_width` — this is the ONE place the column window reaches the
  preview, mirroring how it is the one place the row window does.
  `SheetPreview.set_sheet(png, fw, fh, row_start=0, row_count=None,
  col_start=0, col_count=None)` is E2's landed signature
  (`editor/panels/sheet_preview.py:82-83`); `column_window()` sits beside
  `row_window()` at `sheet_preview.py:141-143` if a test needs to read it back.
- **Changing the column does NOT rebuild `RowEditor`s.** Unlike
  `_on_row_window_changed`, which calls `_load_sheet` because the row window
  changes *which rows exist*, the column window only changes *which
  horizontal slice of those same rows* is shown — so `_on_column_changed`
  should call `self._refresh_preview()` directly, not `_load_sheet`.
- **`engine.assets.master_registry.column_width_for(doc, sheet_ref)`**
  (`engine/assets/master_registry.py:82`, published by S1, already landed and
  independent of any other S2 phase) is how to read a linked sheet's
  `column_width` off the registry. **Do not read `MasterSheet.column_width`
  as an attribute** — Phase E1 is what adds that field to the `MasterSheet`
  dataclass, and E1 and E3 run concurrently with no ordering guarantee
  between them. Going through `master_registry.column_width_for` instead
  means E3's production code has *no* dependency on E1's landing order.
  `editor.master_sheet_import.load_registry_doc(self._data_dir)` gets you the
  `doc` argument; `master_sheet_import` is already imported at
  `details.py:52`. Add `from engine.assets import master_registry` as a new
  import.

## 2. Architecture plan

1. **New imports** (`details.py`, near line 52): `from engine.assets import
   master_registry`.
2. **New instance state** in `__init__`, beside `self._master_grid = None`
   (`details.py:302`):
   ```python
   self._column = 0
   self._column_mode = "manual"
   self._column_width = 0
   self._sheet_cols = 0     # frame-columns the CURRENT sheet really has
   ```
3. **New widget row**, built right after the `self._master_row` block
   (`details.py:404-422`), same shape:
   - `self._column_row = QWidget()`, `QHBoxLayout`, no margins.
   - `QLabel("Column")` + `self._column_spin` (`_NoWheelSpinBox`, range set
     dynamically per sheet — see step 5 — committed on `editingFinished` →
     `self._on_column_changed`).
   - `QLabel("mode")` + `self._column_mode_combo` (`_NoWheelComboBox`,
     `addItems(["Manual", "Season", "Building colour"])`; map
     display↔stored value with a small dict, e.g. `{"Manual": "manual",
     "Season": "season", "Building colour": "building_color"}` and its
     reverse — do NOT store the friendly label in the manifest). Commit on
     `currentIndexChanged` → `self._on_column_changed` (a combo has no
     `editingFinished`).
   - `QLabel("width:")` + `self._column_width_display` (`_NoWheelSpinBox`,
     always `setEnabled(False)`, tooltip e.g. "The master sheet owns this
     value (D1) — it is inherited, not editable here.").
   - `addStretch(1)`.
   - Add to the panel layout right after `layout.addWidget(self._master_row)`
     (`details.py:443`): `layout.addWidget(self._column_row)`.
   - Hide by default right after `self._master_row.setVisible(False)`
     (`details.py:449`): `self._column_row.setVisible(False)`.
4. **`_reset_row_window`** (`details.py:785-790`): add the four column-state
   resets listed in §1.
5. **`_refresh_master_state`** (`details.py:792-816`): where it currently
   does `self._master_row.setVisible(master)` (`details.py:797`), add
   `self._column_row.setVisible(master)`. Where it fills the row spins
   (`details.py:801-812`), add the column-spin fill, guarded by `master and
   self._sheet_cols >= 1 and self._column_width >= 1`:
   ```python
   width = max(1, self._column_width)
   ceiling = max(0, (self._sheet_cols // width) - 1)
   self._column_spin.blockSignals(True)
   self._column_spin.setRange(0, ceiling)
   self._column_spin.setValue(min(self._column, ceiling))
   self._column_spin.blockSignals(False)
   self._column_mode_combo.blockSignals(True)
   self._column_mode_combo.setCurrentText(<display label for self._column_mode>)
   self._column_mode_combo.blockSignals(False)
   self._column_width_display.setRange(1, 256)   # schema bound, ED-30
   self._column_width_display.setValue(width)
   ```
   This is the "an off-sheet column is unrepresentable rather than a
   save-time error" requirement (ED-30) — the spin's ceiling always tracks
   the real sheet, the same way `_row_to`'s minimum tracks `_row_from`.
6. **`use_master_sheet()`** (`details.py:654-700`): beside
   `self._master_grid = (sheet.frame_w, sheet.frame_h)` (`details.py:683`),
   adopt the width:
   ```python
   doc = master_sheet_import.load_registry_doc(self._data_dir)
   self._column_width = master_registry.column_width_for(doc, sheet.ref)
   self._column = int((seed or {}).get("column", 0))
   self._column_mode = (seed or {}).get("column_mode", "manual")
   ```
   (`seed` is already computed a few lines above at `details.py:679-680`; the
   `row_start`/`row_count` lines right after it, `details.py:684-687`, are
   the exact pattern to mirror for `column`/`column_mode`.)
7. **`set_slot()`'s reload branch** (`details.py:548-556`, inside `if entry
   and self._master_applies():`): mirror the `row_start`/`row_count` lines
   (`details.py:554-555`) for column state, with the same registry fallback
   as step 6 for `column_width` — an entry saved *before* this phase shipped
   has no `column_width` key (S1's in-memory default is 0), so falling back
   to `master_registry.column_width_for` is what gives that entry a working
   ceiling on first load rather than a `0..0` spin:
   ```python
   self._column = int(entry.get("column", 0))
   self._column_mode = entry.get("column_mode", "manual")
   self._column_width = (int(entry.get("column_width", 0)) or
       master_registry.column_width_for(
           master_sheet_import.load_registry_doc(self._data_dir),
           self._sheet_ref))
   ```
8. **`_load_sheet`** (`details.py:983-1027`): store `self._sheet_cols = cols`
   next to the existing `self._sheet_rows = sheet_rows` (`details.py:990`).
9. **`_refresh_preview()`** (`details.py:1047-1063`): extend the
   `self._preview.set_sheet(...)` call per §1, only when
   `_master_applies()` and `self._column_width > 0`. When those conditions
   are false, call it exactly as today (E2's row-only shape) — a
   three-argument-equivalent call must still reset any stale column window
   the widget remembers from a previous slot.
10. **New method `_on_column_changed`** (place it right after
    `_on_row_window_changed`, `details.py:818-838`), following that method's
    guard/writes-nothing shape exactly, but calling `self._refresh_preview()`
    instead of `_load_sheet` (see §1's "does NOT rebuild RowEditors" point),
    then `self._emit_draft()`.
11. **`draft_entry()`** (`details.py:712-748`): add the three two-branch
    author-or-preserve blocks from §1, placed beside the existing
    `row_start` block (`details.py:736-742`).
12. **`editor/panels/CLAUDE.md`** — append ONE new subsection. See §3 for the
    exact insertion point.

## 3. File scope + shared-file contract

**E3 may modify ONLY:**
- `editor/panels/details.py`
- `editor/panels/CLAUDE.md`
- `tools/tests/test_details_panel.py`

**E3 may NOT touch:** `editor/panels/sheet_preview.py`,
`editor/master_sheet_import.py`, `editor/panels/master_sheet_dialog.py`,
`editor/panels/viewport.py`, `editor/panels/selector.py`, `editor/main.py`, or
any `engine/` file. `SheetPreview.set_sheet`'s `col_start`/`col_count`
keywords and `column_window()` are E2's already-landed, read-only-to-you
interface — call them, don't extend them.

**`editor/panels/CLAUDE.md` — append only, one new subsection at the END of
the DetailsPanel/master-sheet content.** E1, E2 and E5 also append to this
file (E1 near "Master-sheet dialog", E2 already added a bullet right before
this insertion point). Your insertion point: immediately after E2's already-
landed bullet block that ends `...` `DetailsPanel._on_frame_clicked` needs no
offset.` and immediately before the `## TestRunnerPLAN TR-5` heading. Do not
rewrite anything above it — pure append.

**`tools/tests/test_details_panel.py` — append only, at the END of the
file.** As of the E2 landing this file is 1152 lines, ending with
`TestConditionTintCheckbox`. Add your new test class(es) after it.
- **Line 528 is OFF LIMITS** — it is
  `TestMasterSheetWindow.setUp`'s `master_sheet_import.import_master_sheet(
  self.data_dir, src, "Village Folk", *self.FRAME)` call. Phase E1 is
  concurrently making `column_width` a **required 6th positional argument**
  of `import_master_sheet`; E1 owns updating that call site. **If your new
  tests call `import_master_sheet` themselves, pass a `column_width` value**
  (e.g. `*self.FRAME, self.FRAME[0]` for "one column spans the whole sheet",
  matching the pre-E1 stopgap's own derivation) so your tests don't silently
  depend on E1's landing order either. Do not edit line 528 itself; it is not
  yours to fix.
- **The `TestSheetPreviewColumnWindow` class is OFF LIMITS** (E2 inserted it
  after `TestSheetPreviewRowWindow`, around lines 657-725 on the E2 landing).
  Do not touch it, do not insert your class between it and its neighbours —
  append after the LAST class in the file instead.

## 4. Tests — bare minimum, no exhaustive Qt matrix

Write the **minimum** tests that pin the behaviour above, mirroring
`TestMasterSheetWindow`'s existing style (`details.py`'s sibling tests at
`tools/tests/test_details_panel.py:508-621` on the E2 landing — same
`DetailsCase`/`link()` helper pattern is worth reusing or extending):

1. The column row is hidden for a plain (non-master) slot and visible once
   `use_master_sheet` links one.
2. Setting the column re-cuts the preview (`self.panel._preview.column_window()`
   changes) and **writes nothing** — no `Save()` call, assert the manifest doc
   on disk is unchanged.
3. `Save()` writes `column`, `column_mode`, `column_width` when non-default,
   and **omits each key individually** when it's at its default (0 /
   `"manual"` / 0) — three separate assertions, not one combined check.
4. A panel path that does not author them (e.g. `clear_entry` then re-`Save`,
   or loading a slot whose sheet is not a master sheet) **preserves** an
   existing entry's column values rather than erasing them — mirror
   `test_save_writes_row_start_and_omits_it_at_zero`'s round-trip shape
   (`test_details_panel.py:590-604` on the E2 landing).
5. Linking a master sheet via `use_master_sheet` adopts that sheet's
   `column_width` (assert `self.panel._column_width` equals the registry's
   value via `master_registry.column_width_for`, not a hardcoded number).
6. The column spin's `maximum()` tracks the sheet's real column count
   (`sheet_cols // column_width - 1`), same idiom as
   `test_the_window_rebuilds_the_rows_and_narrows_the_preview`'s
   `_row_to.minimum()` assertion (`test_details_panel.py:568`).

No exhaustive Qt matrix, no combo-box round-trip of every label. **Every
widget constructed in a test must be destroyed via `qt_harness`
(`self.track(...)`)** — the existing `DetailsCase.setUp` already does this
for `self.panel`; never a bare `.close()`. **Never assert against live
`data/` content** — `DetailsCase`/`TempDataCase` already copies `data/` to a
tempdir; author your own fixture sheets with `make_png` the way
`TestMasterSheetWindow.setUp` does.

### Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_details_panel.py -q
```

Nothing wider. Never the full suite, never `testgate check`, never
`--affected`, never a tier sweep (`-m core`/`-m editor`/`-m meta`).

### Quick Test (live editor, run by the orchestrator/user — not the coder)

Launch `py editor/main.py`. Import a master spritesheet with several
character columns (or use one already registered). In the selector, pick a
slot and click **Use Master Spritesheet…**, choosing that sheet. Confirm a
new **Column** row appears under the row-window controls, with a spin, a
mode combo (Manual/Season/Building colour) and a disabled width field. Change
the column value and confirm the embedded sheet preview re-cuts to show only
that column's frames, without the manifest file on disk changing (no Save
yet). Click **Save**, then re-select a different slot and re-select this one
— confirm the column value you set survived the round trip.

## Test-guard rule

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.
