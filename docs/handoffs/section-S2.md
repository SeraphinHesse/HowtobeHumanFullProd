# Section S2 handoff

**Landed** — `section-S2` @ `1dfacf0`; five phases green, **zero fix rounds**, all
reviewed clean. E1 `phase-E1-import-path` @ `327fd8b` · E2 `phase-E2-sheet-preview-columns`
@ `ee418a7` · E3 `phase-E3-details-column-controls` @ `4b97db7` · E4
`phase-E4-viewport-column-switcher` @ `2b15282` · E5 `phase-E5-master-sheets-panel` @
`fa856c8`.

**Interface deltas**
- **S1's derived-`column_width` stopgap is GONE** (**measured**: zero hits for `STOPGAP` /
  `sheet_w // frame_w`). `import_master_sheet(data_dir, png_path, display_name, frame_w,
  frame_h, column_width, columns=(), sheet_id=None)` (`editor/master_sheet_import.py:346`)
  — `column_width` REQUIRED 6th positional, `columns` omitted at empty.
- **`GridInUseError`'s tuple is now `(frame_w, frame_h, column_width)`** (`:418-421`),
  still raised before the PNG copy and registry write, still a `ValueError` subclass.
- **`sheet_id=` is NEW and mine, not the plan's** (`:347`): `resolve_sheet_id` (`:304-343`)
  mints `<slug>_2` when bytes differ, stranding every link. `None` ⇒ today's behaviour.
- `MasterSheet.grid()` **stays a 2-tuple** (4 live unpack sites); count is a new
  `column_count()`. New schema-read `columns_bounds()` / `parse_columns()`.
- `SheetPreview.set_sheet(..., col_start=0, col_count=None)` + `column_window()` — applied
  in ONE place, the `paintEvent` source rect; indices WINDOW-relative on both axes.
- New `editor/panels/master_sheets.py`; selector `master_sheets_selected`, a NEW TOP-LEVEL
  item, **last**, emitting no `domain_selected` (D9: no host category) and never
  `node_selected`. `right_stack.count()` is **9** (`test_editor_viewport.py:1344`).

**Open findings**
1. **No shipped master sheet declares `columns`** — `data/sprites/master_sheets.json` has
   one entry (`slinger_t2_lvl3`, `column_width: 15`, no `columns`). **S2 did NOT change
   this**; S3's in-game Quick Test stays unrunnable until a designer authors a
   multi-column sheet. *Owner: user / top orchestrator.* **measured**
2. **`docs/handoffs/section-S1.md:36-39` is STALE** — says `RenderItem.column: int = 0`;
   umbrella superseded it with `int | None = None` (+ `SpriteAnimator.column = -1`).
   S3/S4 read it. *Owner: top orchestrator.* **verified**
3. Viewport combo is a **visible no-op for `manual`-mode slots** (`store._column_block`
   resolves manual to the stored `column`). Correct per D3, but most slots are manual.
   *Owner: user (UX call).* **verified**
4. Live `py editor/main.py` Quick Test never run (no display); section check was targeted
   hand-verification of the E1+E5 / E4+E5 auto-merges, not a full section-diff reviewer
   pass. *Owner: user / top orchestrator.* **verified**

**Gate** (merged `section-S2`) — `py tools/smoke.py` **PASS** (62 data files valid, 5
headless frames, shell boot OK); `py -m pytest` over the 6 touched test files `-n 4` →
**312 passed, 17 subtests, 0 failed, 0 skipped**. Both **measured**.
