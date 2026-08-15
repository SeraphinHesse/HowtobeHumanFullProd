# Phase E4 — Viewport preview column switcher

Part of Section S2 of `planning/MasterSheetColumnsPLAN.md` ("Options to switch
column in the preview just like which animation").

## 1. Behavioral spec

The entity-preview viewport already gives a designer a floating dropdown to
scrub through a slot's authored ANIMATIONS. E4 adds a second, independent
lever beside it: a dropdown to scrub through a master-sheet-linked slot's
COLUMNS (colour/season blocks, D3/D4 of the plan doc), for preview only —
exactly the same "pick a value, see it live" UX the animation combo already
gives, on the orthogonal axis.

**Existing pattern to twin (verified against the CURRENT tree, no drift from
the plan doc's line numbers):**
- The floating animation combo is built and pinned in `__init__`:
  `editor/panels/viewport.py:272-277` (`self._anim_combo = _NoWheelComboBox(self)`,
  `.move(8, 8)`, `.hide()`, `currentTextChanged.connect(self.set_preview_animation)`).
  `_NoWheelComboBox` is imported from `editor.panels.balancing`
  (`viewport.py:48`) — already imported, do not add a second import or a bare
  `QComboBox`.
- `_refresh_anim_combo` (`viewport.py:1636-1648`): `blockSignals(True)` →
  `clear()` → `addItems(list(animations))` → if the current value fell out of
  the new list, fall back to the first entry (or the `"idle"` sentinel when
  empty) → `setCurrentText` when non-empty → `blockSignals(False)` →
  `setVisible(bool(animations))`.
- `preview_animations()` (`viewport.py:428-434`) is draft-aware: it reads
  `self._manifest.entry(self.preview_slot)`, and `self._manifest` is already
  the draft-applied manifest (`_build_store`, `viewport.py:351-357`, applies
  `self._draft` via `Manifest.override` before assigning `self._manifest`).
  Nothing new is needed here for draft-awareness — reading through
  `self._manifest.entry(...)` is what makes it automatic.
- `_refresh_anim_combo()` is called from exactly four sites:
  `reload_assets` (`:368`), `set_preview_slot` (`:404`), `set_preview_draft`
  (`:448`), and the else-branch of `set_map_mode` when leaving map mode back
  to entity preview (`:480`).
- The combo is explicitly hidden in map mode (`set_map_mode`, `:477`,
  `self._anim_combo.hide()`) and in screen mode (`set_screen_mode`, `:523`,
  `self._anim_combo.hide()`).
- The preview `RenderItem` is built once, in `render_frame`'s entity-preview
  branch: `viewport.py:1885-1893`.

**S1's landed interface this phase consumes (verified against
`docs/handoffs/section-S1.md` AND the plan doc's "Post-integration fixes"
block, which SUPERSEDES the handoff on the sentinel — the handoff still says
`int = 0`, that is stale, do not use it):**
- `RenderItem.column: int | None = None` (`engine/render/item.py:42`,
  verified in the current tree) — `None` means "no live driver, use the
  entry's own stored `column`"; **0 is a legitimate live value** (season 0,
  colour 0), never a sentinel.
- `ManifestEntry` (returned by `self._manifest.entry(slot_key)`) carries
  `.sheet` (str), `.column` (int), `.column_mode` (str), `.column_width`
  (int) directly as dataclass fields (`engine/assets/manifest.py:90,119-121`).
- `engine.assets.master_registry.columns_for(doc, sheet_ref)` — the sheet's
  declared column NAMES in stored order, or `()` when unresolvable/unnamed
  (`engine/assets/master_registry.py:72-79`, verified).
- `engine.assets.master_registry.column_width_for(doc, sheet_ref)` — how many
  frame-columns one master column spans, or `0` when unresolvable
  (`engine/assets/master_registry.py:82-95`, verified).
- `engine.assets.master_registry.MASTER_PREFIX = "master/"`
  (`engine/assets/master_registry.py:31`) — a sheet ref belongs to a master
  sheet iff it starts with this (D2: columns are master-sheet-only).
- `editor.master_sheet_import.load_registry_doc(data_dir)` — the editor's
  E-37-tolerant wrapper around `master_registry.load_registry`, degrading a
  missing/corrupt registry to `{"version": 1, "entries": {}}`
  (`editor/master_sheet_import.py:118-139`, verified).
- `editor.master_sheet_import.master_sheets(data_dir)` — every registered
  sheet annotated with its REAL pixel `width`/`height` (Pillow header read,
  lazy) plus its declared `frame_w`/`frame_h`
  (`editor/master_sheet_import.py:398-443`, verified — this is the CURRENT
  2-tuple-`grid()` shape; see the Architecture note below on why E4 does not
  depend on E1's promised extension to it).
- The engine's own column-block formula, for reference/consistency
  (`engine/assets/store.py:219-236`, verified): `block = entry.column` when
  `column_mode == "manual"` or the caller passed `column=None`, else
  `column`; `sheet_cols = sheet.get_width() // (entry.column_width *
  entry.frame_w)`; then `max(0, min(block, sheet_cols - 1))` (D7's two-sided
  clamp). **Consequence you must state to the coder plainly: for a `manual`-
  mode entry, the block ALWAYS resolves to the entry's own stored `column`
  no matter what the viewport submits.** The combo is still visible and still
  changes what `RenderItem.column` carries (that is what E4's own test pins),
  it just has no visible pixel effect for `manual` mode — that is D3, not a
  bug for this phase to work around. It has a real effect for `season`/
  `building_color` mode entries (a live driver overriding the stored value),
  which is the whole point of a PREVIEW switcher: see any column without
  touching the entry's saved `column_mode`/`column`.

**Not yet landed on this branch (E1/E2/E3 — this phase's coder runs AFTER
they land, since the section runs its phases in order):** the plan doc's
S2 "Publishes" line names `MasterSheet.columns` and says `grid()` "gains a
`columns` count" (E1's design notes). **E4 deliberately does not depend on
either** — see Architecture §2. Confirm nothing in your diff assumes an E1
API surface beyond what's cited above as already-landed; if in doubt, grep
`editor/master_sheet_import.py` for the current shape before writing code
that calls it.

## 2. Architecture plan

**New instance state (in `__init__`, immediately after the `_anim_combo`
block, `viewport.py:272-277` — insert before the `# -- screen mode state`
comment that currently follows at `:279`):**
```python
# MasterSheetColumnsPLAN E4: a third floating combo, pinned beside the
# animation combo, previewing a master-sheet-linked slot's COLUMN (D3/D4).
# Visible only when the previewed slot links a master sheet (D2).
self._column_combo = _NoWheelComboBox(self)
self._column_combo.move(8, 40)   # stacked clear of the animation combo
self._column_combo.hide()
self._column_combo.currentIndexChanged.connect(self._on_column_index_changed)
self.preview_column = None   # int|None — rides straight onto RenderItem.column
```
`currentIndexChanged` (not `currentTextChanged`) because the value that
matters is the INDEX (what `RenderItem.column` wants), and column labels are
not guaranteed unique text the way `"idle"`/`"attack"` animation names are
expected to be — driving off index avoids ever mapping a label back to a
position. The exact pixel offset (`move(8, 40)`) is cosmetic and not
pixel-gated by any test; keep it visually clear of the animation combo,
nothing more is required.

**New imports** (both already-landed, pure, Qt/pygame-free modules — no
layering risk):
- `viewport.py:46` currently reads
  `from editor import anchor_ops, tilemap_ops, vfx_params, widget_tree` — add
  `master_sheet_import` in alphabetical position:
  `from editor import anchor_ops, master_sheet_import, tilemap_ops, vfx_params, widget_tree`.
- `viewport.py:51` currently reads
  `from engine.assets import entry_from_dict, load_manifest, load_registry` —
  append `master_registry`:
  `from engine.assets import entry_from_dict, load_manifest, load_registry, master_registry`.

**`_on_column_index_changed` handler** — place near `set_preview_animation`
(`viewport.py:406-410`):
```python
def _on_column_index_changed(self, index):
    self.preview_column = index if index >= 0 else None
```

**`_preview_column_labels()` helper** — place immediately after
`preview_animations()` (`viewport.py:428-434`), as its direct sibling:
```python
def _preview_column_labels(self):
    """Column-switcher combo labels for the previewed slot's EFFECTIVE
    (draft-aware) entry: the linked master sheet's declared `columns` names
    (D4), in sheet order, when it has any — else "Column N" for N in
    range(the sheet's real master-column count). () when the slot has no
    entry or its sheet is not a master sheet (D2)."""
    if self.preview_slot is None:
        return ()
    entry = self._manifest.entry(self.preview_slot)
    if entry is None or not entry.sheet.startswith(master_registry.MASTER_PREFIX):
        return ()
    doc = master_sheet_import.load_registry_doc(self._data_dir)
    names = master_registry.columns_for(doc, entry.sheet)
    if names:
        return names
    column_width = master_registry.column_width_for(doc, entry.sheet)
    if column_width <= 0:
        return ()
    for sheet in master_sheet_import.master_sheets(self._data_dir):
        if sheet.ref == entry.sheet:
            count = sheet.width // (column_width * sheet.frame_w)
            return tuple(f"Column {i}" for i in range(count))
    return ()
```
This is **deliberately self-sufficient against S1's already-landed interface
only** — it does not call `MasterSheet.grid()` or read a `MasterSheet.columns`
attribute, so it does not care what shape E1 eventually lands those in. The
count formula (`sheet.width // (column_width * sheet.frame_w)`) is the exact
one `engine/assets/store.py:232` already uses for the render-time clamp
ceiling, kept in lockstep on purpose.

**`_refresh_column_combo()`** — place immediately after `_refresh_anim_combo`
(`viewport.py:1636-1648`), as its direct twin:
```python
def _refresh_column_combo(self):
    labels = self._preview_column_labels()
    combo = self._column_combo
    combo.blockSignals(True)
    combo.clear()
    combo.addItems(list(labels))
    if self.preview_column is None or self.preview_column >= len(labels):
        self.preview_column = 0 if labels else None
    if labels:
        combo.setCurrentIndex(self.preview_column)
    combo.blockSignals(False)
    combo.setVisible(bool(labels))
```

**Four call sites — add `self._refresh_column_combo()` directly after the
existing `self._refresh_anim_combo()` call, same line-for-line pattern, at:**
`reload_assets` (`:368`), `set_preview_slot` (`:404`), `set_preview_draft`
(`:448`), and `set_map_mode`'s else-branch (`:480`).

**Two hide sites — add `self._column_combo.hide()` directly after the
existing `self._anim_combo.hide()` call, at:** `set_map_mode`'s map-mode
branch (`:477`) and `set_screen_mode`'s screen-mode branch (`:523`). Do not
add anything at `:527` (`_state_combo.hide()` on screen-mode exit) —
`_anim_combo` is not re-shown there either; whatever re-enters entity-preview
mode calls `set_preview_slot`/`reload_assets` downstream, which already
re-runs `_refresh_column_combo` once you've added it to those two methods.
This mirrors `_anim_combo`'s existing behavior exactly — do not diverge.

**`set_preview_slot`** (`viewport.py:390-404`): inside the
`if slot_key != self.preview_slot:` branch, alongside the existing
`self.preview_animation = "idle"` reset, add `self.preview_column = None` —
so a fresh slot never inherits a stale numeric index from whatever was
previously previewed (parity with the animation reset; `_refresh_column_combo`
still re-derives the real value right after).

**`render_frame`** (`viewport.py:1885-1893`): add `column=self.preview_column`
as a new keyword argument to the preview `RenderItem(...)` construction,
alongside the existing `fit_tiles=`/`scale=` keywords.

## 3. File scope + shared-file contract

E4 may modify **only**:
- `editor/panels/viewport.py` — the whole diff above.
- `editor/CLAUDE.md` — **shared with Phase E5. APPEND ONLY, at the END of the
  viewport/master-sheet-adjacent content, never touch surrounding text.**
  The last section in the file that discusses `ViewportPanel`/master-sheet
  integration is `## VFX preview (...)`, whose final paragraph (the ESV-6
  note) ends at `editor/CLAUDE.md:345`, immediately followed by a blank line
  and the unrelated `## Running the tests FROM the editor` heading at `:347`
  (verified — these line numbers are current). Insert a new, short, top-level
  section **between `:346` and `:347`**:
  ```
  ## Master-sheet column switcher (`panels/viewport.py`, MasterSheetColumnsPLAN E4)

  A third floating `_NoWheelComboBox` (`_column_combo`), twinned with the
  entity-preview animation combo (`_anim_combo`) — same construction/refresh/
  hide idiom, one call site each. Visible only when the previewed slot's
  EFFECTIVE (draft-aware) entry links a master sheet (`entry.sheet` starts
  with `master/`, D2); labels are the sheet's declared `columns` names (D4)
  or generated `Column N` labels sized off `store.py`'s own clamp-ceiling
  formula. Selecting an entry rides `self.preview_column` onto the preview
  `RenderItem.column` (`int | None`) — `None` means "no live driver, use the
  entry's stored column". **For a `manual`-mode entry this combo changes
  nothing on screen** (`store.py:_column_block` always uses the entry's own
  stored `column` when `column_mode == "manual"`, D3) — it only visibly
  drives `season`/`building_color` entries. That is intended, not a bug.
  ```
  (You may tighten the wording; do not shorten the D3 caveat — the next
  person to touch this combo needs to know why "I picked a colour and
  nothing moved" is expected for a manual-mode slot.)
- `tools/tests/test_editor_viewport.py` — **shared with Phase E5. E4 owns the
  END of this file.** Append exactly ONE new test class between the current
  final blank line at `:1538` and the `if __name__ == "__main__":` block at
  `:1540-1541` (verified current EOF). Whichever of E4/E5 lands second in
  this section inserts its own class in the same spot, above the still-last
  `if __name__` block — do not reorder or touch any class above your
  insertion point.
  - **Forbidden line 1 — do NOT touch:** `self.assertEqual(window.right_stack.count(), 8)`
    at `:1343` (`TestMainWindowVfxMode`). That count becomes 9 under Phase
    E5's Master Sheets panel; E5 owns that edit, not E4.
  - **Forbidden line 2 — do NOT touch:** the `TestPurity.test_editor_does_not_import_game`
    import-list string, `:1494-1530`. `editor.panels.viewport` and
    `editor.master_sheet_import` are ALREADY both present in that list
    (`:1507`, `:1496`) — E4's new imports need no addition there at all.
  - You WILL need two new top-of-file imports this file does not currently
    have: `from editor import master_sheet_import` and
    `from engine.assets import master_registry`. Add them near the existing
    `from editor...`/`from engine...` import lines (top of file, well above
    line 1343) — this is NOT the forbidden zone; only the two lines named
    above are off-limits.

E4 may **not** touch `editor/panels/details.py`, `editor/panels/sheet_preview.py`,
`editor/master_sheet_import.py`, `editor/panels/master_sheet_dialog.py`,
`editor/panels/selector.py`, or `editor/main.py`.

## 4. Exit gate + Quick Test

**Tests — bare minimum, no exhaustive Qt matrix.** Write one new test class
(e.g. `TestColumnSwitcher(TempDataCase)`) with small helper methods to write a
real, schema-valid `data/sprites/master_sheets.json` entry + a matching PNG
(Pillow, mirroring `pin_slot_rows`'s pattern already in this file) and to
point an existing slot's manifest entry (e.g. `painter_t1_lvl1`) at it with
`column`/`column_mode`/`column_width` set. Pin exactly these behaviors, one
assertion group each, and nothing more:
1. The combo lists a master sheet's declared `columns` names, in order.
2. A master sheet with no declared `columns` falls back to `Column 0`,
   `Column 1`, … sized to the real master-column count.
3. The combo is hidden for a slot whose entry is not master-linked (a plain
   `imported/<slot>.png` ref).
4. The combo is hidden in screen mode (`panel.set_screen_mode(session,
   FIXTURE_DEFAULTS)` — this file already has that fixture and pattern
   nearby). Map mode hides through the exact same code path
   (`_column_combo.hide()` added at the same two call sites as
   `_anim_combo.hide()`) — do not also write a map-mode variant, it would be
   pinning the same line twice.
5. Selecting a column changes the `column` submitted on the preview
   `RenderItem` — monkeypatch `panel._renderer.submit` the same way this file
   already monkeypatches `panel._renderer.submit_hud` (see
   `record_hud`/`test_viewport_set_screen_mode_renders_without_defaults`,
   `:621-639`), call `panel.render_frame()`, and read back the captured
   item's `.column`.
6. An unsaved draft's column is reflected: `panel.set_preview_draft(slot_key,
   draft_entry_with_a_different_column_mode_or_columns)` changes what the
   combo/`_preview_column_labels()` report, without touching disk.

Every widget you construct (`ViewportPanel`, any `MapSession`/`UIScreenSession`
you build for the mode tests) goes through `self.track(...)`
(`tools/tests/qt_harness.py`) — never a bare `.close()`.

**Exit gate — exactly this, nothing wider:**
```
py tools/smoke.py
py -m pytest tools/tests/test_editor_viewport.py -q
```
Never the full suite, never `testgate check`, never `--affected`, never a
tier sweep (`-m core`/`-m editor`/`-m meta`).

> **Test-guard rule.** If `test_guard` denies a test command, do NOT re-issue
> it, do not vary the flags (the guard normalises `-q/-v/-x/-n/--tb`, so a
> reworded command fingerprints identically), and do not reach for the
> guard's escape hatch. Report the deny text and the result it quotes back to
> the orchestrator and stop testing. Retrying is the loop the guard exists to
> stop.

**Quick Test (live editor, run by the orchestrator/user — not the coder).**
Launch `py editor/main.py`. In the selector, find a building/enemy slot whose
manifest entry links a master sheet with declared `columns` (or link one via
the Details panel's master-sheet button if none exists yet — Phase E3 lands
that control earlier in this section). Confirm a THIRD floating dropdown
appears beside the existing animation dropdown, listing the sheet's colour/
season names (or `Column N` if the sheet declared none). Pick a different
entry: if the entry's column mode is `season` or `building_color`, the
preview sprite visibly changes to that column's art; if it is `manual`, the
preview does not change (expected — see the D3 note above) but the dropdown
selection itself still holds. Switch to a map or a UI screen: the column
dropdown disappears along with the animation dropdown.

---

## Report format for the executing agent

State exactly what you verified (live editor run vs. the two exit-gate
commands), tag claims measured/verified/inferred, and list every file you
touched with line ranges. If any anchor in §1/§2 has drifted further since
this brief was written (E1/E2/E3 landing on this branch may have shifted line
numbers in `viewport.py` itself — unlikely, since they don't touch that file,
but confirm), say so explicitly rather than silently adapting.
