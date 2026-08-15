# Phase E2 — `SheetPreview` column window

Part of `planning/MasterSheetColumnsPLAN.md`, Section S2 (`section-S2`).
Goal (plan): "The raw-sheet inspector can show one column instead of the whole
sheet." Give `editor/panels/sheet_preview.py`'s `SheetPreview` a **column**
window that is the exact structural twin of its existing **row** window, so a
future caller (E4/E5) can narrow the raw-PNG inspector to one master-sheet
column block without a second application point ever existing.

## 1. Behavioral spec

All citations verified against the current tree (`section-S2`,
`editor/panels/sheet_preview.py`, 319 lines).

- **The row window today** — `set_sheet(self, png_path, frame_w, frame_h,
  row_start=0, row_count=None)` (`sheet_preview.py:82-83`), documented
  opt-in/reset/window-relative at `:84-100`. Body: `self._cols =
  pixmap.width() // self._frame_w` (`:113`, computed ONCE, from the FULL
  sheet width — there is no column narrowing yet); then the row window is
  carved out of the sheet's row count (`:114-118`):
  ```
  sheet_rows = pixmap.height() // self._frame_h
  self._row_start = min(max(0, int(row_start)), max(0, sheet_rows))
  available = sheet_rows - self._row_start
  self._rows = (available if row_count is None
                else max(0, min(int(row_count), available)))
  ```
  The `pixmap is None` branch resets `self._cols = self._rows = 0` and
  `self._row_start = 0` (`:109-111`).
- **`row_window()`** — `(self._row_start, self._rows)` (`:123-125`), sitting
  directly after `set_sheet`.
- **The row window is applied in exactly ONE place** — the `paintEvent`
  source rect (`:211-217`):
  ```python
  # THE ONE PLACE THE ROW WINDOW IS APPLIED. Every other coordinate in
  # this widget — cells, captions, hit-tests, frame_clicked — is
  # window-relative, so nothing below needs an offset (M4 §2.3).
  source = QRect(0, self._row_start * self._frame_h,
                 self._cols * self._frame_w,
                 self._rows * self._frame_h)
  painter.drawPixmap(rect, self._pixmap, source)
  ```
  The x-origin is a hardcoded `0` — this is the ONE line E2 must change.
- **Everything downstream already reads `self._cols` generically** and needs
  NO further edits once `self._cols` becomes the windowed count (exactly the
  trick the row window already plays with `self._rows`): `_scale_for`
  (`:143-151`, `sheet_w = self._cols * self._frame_w` at `:146`), `_grid_rect`
  (`:156-163`, `:161`), `cell_at` (`:174-184`, the bounds check `0 <= col <
  self._cols` at `:182` — this is what makes `frame_clicked` WINDOW-RELATIVE:
  `mousePressEvent` at `:310-315` calls `cell_at` and emits its result
  verbatim), `_cell_rect` (`:186-193`), `_paint_cells` (`:234-246`, `for col
  in range(self._cols)` at `:238`), `_paint_grid` (`:248-256`, `:251`),
  `_paint_labels` (`:281-293`, `:288` — captions are `str(col)`, i.e. already
  window-relative once `self._cols` is windowed).
- **`__init__`** (`:60-78`) already declares `self._cols = 0` (`:66`) and
  `self._row_start = 0` (`:68`); there is no `self._col_start` yet.
- **Test precedent**: `tools/tests/test_details_panel.py:622-655`,
  `TestSheetPreviewRowWindow(QtCase)` — `preview(tmp)` helper builds a 3×5
  frame sheet (`:627-633`); `test_default_arguments_show_the_whole_sheet`
  (`:635-648`) proves the 3-arg call is byte-identical and a later 3-arg call
  RESETS a window; `test_a_window_past_the_bottom_is_clamped_not_raised`
  (`:650-654`) proves the clamp. The class sits between `TestMasterSheet...`
  content above it and `class TestSheetPicker(DetailsCase)` at `:657`.
- **`cell_at` is the payload `frame_clicked` emits** — `TestSheetPreviewClicks
  .test_preview_cell_hit_test_round_trips`
  (`test_details_panel.py:307-313`) already pins this pattern:
  `preview.cell_at(rect.center())` is asserted directly, with no synthetic
  `QTest` mouse event needed, because `mousePressEvent` (`sheet_preview.py
  :310-315`) does nothing but call `cell_at` and re-emit its tuple. Reuse this
  pattern for the "first visible column reports column 0" test — do not reach
  for `QTest.mouseClick`.

## 2. Architecture plan

Mirror the row window function-for-function. Six edits, all inside
`editor/panels/sheet_preview.py`:

1. **`__init__` (`:60-78`)** — add `self._col_start = 0` immediately after
   `self._row_start = 0` (`:68`).

2. **`set_sheet` signature (`:82-83`)** — add `col_start=0, col_count=None`
   after `row_count=None`:
   ```python
   def set_sheet(self, png_path, frame_w, frame_h, row_start=0,
                 row_count=None, col_start=0, col_count=None):
   ```

3. **`set_sheet` docstring (`:84-100`)** — extend the existing paragraph to
   say the column window follows the identical rule (opt-in, defaults to the
   whole sheet, a call omitting `col_start`/`col_count` resets any previously
   set column window, WINDOW-RELATIVE on BOTH axes now, not just rows). Do
   not rewrite the row-window prose — append the column half next to it in
   the same voice.

4. **`set_sheet` body (`:101-121`)**:
   - In the `pixmap is None` branch (`:109-111`), also reset
     `self._col_start = 0` alongside the existing `self._cols = self._rows =
     0` / `self._row_start = 0`.
   - Replace the single-line `self._cols = pixmap.width() //
     self._frame_w` (`:113`) with the full-sheet computation plus the SAME
     clamp-and-window shape the rows already use, computed BEFORE the
     existing row-window block so both windows are carved from the same
     `pixmap` read:
     ```python
     sheet_cols = pixmap.width() // self._frame_w
     sheet_rows = pixmap.height() // self._frame_h
     self._col_start = min(max(0, int(col_start)), max(0, sheet_cols))
     col_available = sheet_cols - self._col_start
     self._cols = (col_available if col_count is None
                   else max(0, min(int(col_count), col_available)))
     self._row_start = min(max(0, int(row_start)), max(0, sheet_rows))
     available = sheet_rows - self._row_start
     self._rows = (available if row_count is None
                   else max(0, min(int(row_count), available)))
     ```
     (The existing `sheet_rows = pixmap.height() // self._frame_h` line
     moves up into this block rather than being duplicated — one read of
     each dimension.)

5. **`column_window()` accessor** — add directly after `row_window()`
   (`:123-125`), same one-line docstring shape:
   ```python
   def column_window(self):
       """``(col_start, col_count)`` — the sheet columns currently drawn."""
       return (self._col_start, self._cols)
   ```

6. **`paintEvent` source rect (`:211-217`)** — the ONE application point.
   Change the x-origin from the hardcoded `0` to `self._col_start *
   self._frame_w`, and extend the comment to say BOTH windows are applied
   here:
   ```python
   # THE ONE PLACE EITHER WINDOW IS APPLIED. Every other coordinate in
   # this widget — cells, captions, hit-tests, frame_clicked — is
   # window-relative, so nothing below needs an offset.
   source = QRect(self._col_start * self._frame_w,
                  self._row_start * self._frame_h,
                  self._cols * self._frame_w,
                  self._rows * self._frame_h)
   painter.drawPixmap(rect, self._pixmap, source)
   ```

**Nothing else in the file changes.** `_scale_for`, `_grid_rect`,
`heightForWidth`, `sizeHint`, `cell_at`, `_cell_rect`, `_paint_cells`,
`_paint_grid`, `_paint_labels`, `mouseMoveEvent`, `mousePressEvent` all read
`self._cols` generically already (per §1) — once it holds the windowed count
instead of the full-sheet count, they are correct with zero edits, exactly
how the row window already made `self._rows` windowed without touching those
same methods.

**Byte-identical default check.** `col_start=0`, `col_count=None` →
`col_available = sheet_cols - 0 = sheet_cols` → `self._cols = sheet_cols`,
identical to today's `self._cols = pixmap.width() // self._frame_w`. Combined
with `self._col_start = 0`, the new source-rect x-origin is `0 *
self._frame_w == 0` — the exact value it hardcodes today. A 3-argument (or
5-argument, row-window-only) `set_sheet` call therefore paints byte-identically
to before.

## 3. File scope + shared-file contract

E2 may modify ONLY:
- `editor/panels/sheet_preview.py` — the six edits above. No other file in
  `editor/panels/` may be touched (not `details.py`,
  `master_sheet_import.py`, `master_sheet_dialog.py`, `viewport.py`,
  `selector.py`) and not `editor/main.py`.
- `editor/panels/CLAUDE.md` — **APPEND ONLY, one new bullet, at the END of
  the existing `SheetPreview` row-window paragraph**: the section headed
  `### DetailsPanel ▸ master sheets (M4: the button, the row window, the
  narrowing)` currently ends with the row-window bullet at lines 1841-1849,
  and the NEXT heading is `## TestRunnerPLAN TR-5 — ...panels/test_run_panel.py`
  at line 1851. Insert the new bullet as a new list item directly after line
  1849 and before line 1851 — do not touch a single character of the
  surrounding text (that section is shared with E1/E3/E4/E5; a rewrite
  collides). Suggested bullet, matching the existing voice:
  ```
  - **The column window is the row window's twin (E2)**: `set_sheet(png, fw,
    fh, row_start=0, row_count=None, col_start=0, col_count=None)` — same
    opt-in/reset/clamp rules, applied in the SAME source-rectangle line in
    `paintEvent`, and `column_window()` sits beside `row_window()`. Cell
    captions and `frame_clicked(row, col)` stay WINDOW-RELATIVE on BOTH
    axes now, not just rows — the preview and the RowEditors below it must
    not be able to disagree about what "frame 1" means on either axis.
  ```
- `tools/tests/test_details_panel.py` — **E2 owns the region immediately
  after `TestSheetPreviewRowWindow`, which spans lines 622-655.** Add a new
  `class TestSheetPreviewColumnWindow(QtCase):` directly after line 655 and
  before line 657 (`class TestSheetPicker(DetailsCase):`), with one blank
  line of separation on each side matching the file's existing spacing.
  **Change nothing else in this file** — no other class, no import line, no
  helper. (`make_png` and `QtCase` are already imported at module level,
  `:14`/`:32` — reuse them, do not re-import.) Phase E3 appends its own
  classes at the END of the file; E2's insertion point is fixed and must not
  drift toward the end to avoid a merge collision with E3.

E2 may NOT touch `editor/panels/details.py`, `master_sheet_import.py`,
`master_sheet_dialog.py`, `viewport.py`, `selector.py`, or `editor/main.py`.

## 4. Exit gate + Quick Test

**Tests — bare minimum, pinning behaviour only.** Add
`TestSheetPreviewColumnWindow(QtCase)` mirroring
`TestSheetPreviewRowWindow`'s shape and FRAME/`preview()` helper (reuse the
same `FRAME = (16, 24)` and a 3×5-frame synthetic PNG, or narrow/widen it as
needed for a column test — coder's call, keep it small). Cover exactly:
1. A column window narrows both the drawn source rect (assert via
   `column_window()` after `set_sheet(..., col_start=1, col_count=1)`) and
   the cell grid (`heightForWidth`/`_grid_rect` width shrinks, or simply
   assert `column_window()` reports the narrowed tuple — do not duplicate
   the row window's own coverage).
2. `frame_clicked`'s window-relative first-column guarantee: after
   `set_sheet(..., col_start=1, col_count=2)`, `widget.cell_at(widget
   ._cell_rect(0, 0).center())` is `(0, 0)` — the pattern already pinned by
   `TestSheetPreviewClicks.test_preview_cell_hit_test_round_trips`
   (`test_details_panel.py:307-313`); do not synthesize a real Qt mouse
   event.
3. `col_count` past the sheet's real column count clamps (mirror
   `test_a_window_past_the_bottom_is_clamped_not_raised`, `:650-654`, on the
   column axis via `column_window()`).
4. The default (3- or 5-argument) call renders byte-identically: `set_sheet`
   with no column args, then with explicit column args, then a call omitting
   them again RESETS to the whole sheet — mirror
   `test_default_arguments_show_the_whole_sheet` (`:635-648`) on the column
   axis, asserting `column_window()` and `heightForWidth`/width-based sizing
   as appropriate.

No exhaustive Qt matrix, no test of `_scale_for`/`_paint_*` internals beyond
what the four cases above already exercise — those methods are unmodified
per §2 and already covered by the row-window tests' existing painting
assertions.

**Exit gate — exactly this, nothing wider:**
```
py tools/smoke.py
py -m pytest tools/tests/test_details_panel.py -q
```
Never the full suite, never `testgate check`, never `--affected`, never a
tier sweep (`-m core`/`-m editor`/`-m meta`).

> **Test-guard rule.** If `test_guard` denies a test command, do NOT re-issue
> it, do not vary the flags (the guard normalises `-q/-v/-x/-n/--tb`, so a
> reworded command fingerprints identically), and do not reach for the
> guard's escape hatch. Report the deny text and the result it quotes back to
> the orchestrator and stop testing. Retrying is the loop the guard exists to
> stop.

**Quick Test (live editor, run by the orchestrator/user, not the coder).**
Launch `py editor/main.py`, select any building or enemy slot that already
links a spritesheet (e.g. any Slinger level under Buildings), open the
Details panel, and click **"Use Spritesheet…"** to attach a wide multi-column
sheet (or import a fresh one) — the raw preview above the row editors should
still show the FULL sheet exactly as before (nothing in this phase is wired
into any UI control yet: `set_sheet`'s new `col_start`/`col_count` are
opt-in, no caller in `details.py` passes them, so the panel's own behaviour
must look completely unchanged). This is a regression check on the
byte-identical default, not a demo of new UI — E4/E5 are what add a control
that actually calls the new arguments.
