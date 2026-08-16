# Phase E5 — Master Sheets panel

Source plan: `planning/MasterSheetColumnsPLAN.md` §3 → Section S2 → `#### Phase E5`
(plan lines 540-597). Branch base: this brief is written against `section-S2` at
the commit where **E1 (import path), E2 (`SheetPreview` column window) and E4
(viewport column switcher) are already merged in** (E3's brief exists but E3
itself has not landed). Re-verify every line number below against your actual
checkout before editing — if E3 has landed since this brief was written, only
`editor/panels/details.py` is affected and this phase does not touch that file,
so nothing here should have moved; if it has, stop and diff before proceeding.

Goal (plan): "One place that lists every registered master sheet, shows its
slicing values and its users, and can re-import it."

**Open with the `/add-editor-feature` skill** — this is a new panel + a new
selector top-level item, exactly what that skill encodes.

## 1. Behavioral spec

**What a master sheet is** (`editor/master_sheet_import.py:1-30`): one PNG
holding many characters' rows in a single grid, registered in
`data/sprites/master_sheets.json`. It is not a `slots.json` slot.

**D9 — Master Sheets is a NEW TOP-LEVEL selector item**, not nested under any
registry category — unlike Timeline (`buildings`) or Theme/Cutscenes/Tutorial/
Strings (`ui`), which are leaves hung off an existing category root.

**D10 — an in-use sheet is fully locked.** `GridInUseError`
(`editor/master_sheet_import.py:73-98`) already compares
`(frame_w, frame_h, column_width)` — E1 landed this extension (verified at
`editor/master_sheet_import.py:396-425`, the guard in `import_master_sheet`).
To change a locked sheet's grid the designer clears every linking slot first.

**The registry-driven listing API E5 consumes, unmodified** —
`editor/master_sheet_import.py`:
- `master_sheets(data_dir=None) -> list[MasterSheet]` (`:489-535`) — sorted by
  display name, reads the REGISTRY (not a folder glob), skips an entry whose
  PNG vanished (E-37), and already carries `users` via `asset_import.sheet_users`
  read once (`:503-504`, `:532`).
- `class MasterSheet` (`:448-486`) — `sheet_id`, `ref`, `path`, `display_name`,
  `frame_w`, `frame_h`, `column_width`, `columns` (tuple, `()` unnamed),
  `width`/`height` (real pixel size), `users` (tuple of slot keys).
  `.grid()` → `(cols, rows)` at the sheet's own frame size; `.column_count()` →
  master-column count.
- `load_registry_doc(data_dir=None)` / `write_registry_doc(data_dir, doc)`
  (`:126-154`) — the ONE write path (ED-31); E5 calls these, never
  `data_io.write_validated` directly.
- `frame_bounds`, `column_width_bounds`, `columns_bounds` (`:157-197`) — ranges
  read from the schema, never retyped (ED-30).
- `parse_columns(text, data_dir=None)` (`:200-236`) — slugify + validate the
  Colours field before any write.
- `GridInUseError` (`:73-98`) — a `ValueError` subclass. **E5 raises this class
  itself** for the panel's own Re-import guard (§2 below) — it does not call
  `import_master_sheet` for that path (see the correctness note in §2.4).

**Refcount ownership**: `asset_import.sheet_users(doc, ref)`
(`editor/asset_import.py:55-61`) is the ONE refcount in this editor.
`MasterSheet.users` already carries it — E5 must never compute a second one.

**The selector's Timeline-leaf pattern** (`editor/panels/selector.py`) — the
newest, cleanest instance, copied for the marker/signal/branch shape (not the
nesting — Timeline nests, Master Sheets does not, D9):
- Marker-role constants `:105-114` (`_TIMELINE_ROLE = Qt.ItemDataRole.UserRole + 9`
  is the last one).
- Label constants `:116-122` (`_TIMELINE_LABEL = "Timeline"` is the last one).
- Signal declarations `:134-144` (`timeline_selected = Signal()` at `:143`,
  `add_requested = Signal(str)` at `:144`).
- Instance-var init `:155-161` (`self._timeline_item = None` at `:161`).
- The category-loop insertion for Timeline, nested under `"buildings"`, at
  `:237-247` — **this is the wrong template for placement** (D9 says Master
  Sheets is OUTSIDE the `for category in self.registry.categories():` loop
  that spans `:163-247`); copy its MARKER/signal shape only.
- `_emit_selection`'s Timeline branch `:578-584`, immediately before the
  `_SCREEN_ROLE` check at `:585`, itself before the unconditional
  `_PAYLOAD_ROLE` fallback at `:607-610` which unpacks and always fires
  `node_selected`.

**Shell wiring's Timeline-leaf pattern** (`editor/main.py`):
- Panel construction block `:169-185` (`self.timeline = TimelinePanel(...)` at
  `:185`, right after `self._strings_panel = StringsPanel(...)` — actually
  `:184`; see §3 for the exact line).
- `from editor.panels.timeline import TimelinePanel` in the alphabetical
  `editor.panels.*` import block, `:66-81`.
- Signal connection `:308-332` (`self.selector.timeline_selected.connect(
  self._on_timeline_selected)` at `:332`).
- `right_stack` page registration `:509-516` (`self.right_stack.addWidget(
  self.timeline)  # index 7: Timeline (TimelinePLAN T5)` at `:516`).
- Handler `_on_timeline_selected` (`:1383-1390`) — reload fresh from disk, then
  `self.right_stack.setCurrentWidget(self.timeline)`.

**`tools/tests/test_editor_viewport.py:1343` hard-asserts
`window.right_stack.count() == 8`** (measured live, current branch) — it
becomes **9**. E5 owns this exact line.

**`TestPurity`'s import list** (`tools/tests/test_editor_viewport.py:1488-1533`,
the assert-string built at `:1492-1530`) — every new editor module goes in.
Current neighbours: `"editor.panels.sheet_picker, editor.panels.
master_sheet_dialog, "` at `:1510`.

**Hard invariant** (the Theme/Cutscenes/Tutorial/Timeline precedent,
`selector.py` module docstring `:36-60`): a single-document/single-concept leaf
emits its OWN signal and **never** `node_selected`, or the entity-preview
machinery reacts to a selection that names no slot.

## 2. Architecture plan

### 2.1 `editor/panels/selector.py`

1. After `_TIMELINE_ROLE` at `:114`, add:
   ```python
   _MASTER_SHEETS_ROLE = Qt.ItemDataRole.UserRole + 10  # True on the single Master Sheets top-level item (E5, D9)
   ```
2. After `_TIMELINE_LABEL = "Timeline"` at `:122`, add:
   ```python
   _MASTER_SHEETS_LABEL = "Master Sheets"
   ```
3. After `timeline_selected = Signal()` at `:143`, before `add_requested` at
   `:144`, add:
   ```python
   master_sheets_selected = Signal()  # E5: the Master Sheets top-level item
   ```
4. After `self._timeline_item = None` at `:161`, add:
   ```python
   self._master_sheets_item = None
   ```
5. **After the `for category in self.registry.categories():` loop ends**
   (its body is `:163-247`; the loop's last statement is
   `self._timeline_item = timeline_item` at `:247`) and **before**
   `self.refresh_maps()` at `:248`, add — OUTSIDE the loop, per D9:
   ```python
   # MasterSheetColumnsPLAN D9: a NEW TOP-LEVEL item, not hung off any
   # registry category (a master sheet is not a slots.json category) — the
   # SECOND top-level insertion after the category-root loop above.
   master_sheets_item = self._make_item(
       _MASTER_SHEETS_LABEL, "master_sheets", (_MASTER_SHEETS_LABEL,))
   master_sheets_item.setData(0, _MASTER_SHEETS_ROLE, True)
   self.addTopLevelItem(master_sheets_item)
   self._master_sheets_item = master_sheets_item
   ```
   `"master_sheets"` as the payload's `category_key` is a placeholder that
   matches no real registry category and is never in `self._domains` — this is
   what keeps `domains()` (`:274-281`, filters `topLevelItem` by
   `key in self._domains`) and `refresh_markers()` (`:507-523`, which already
   tolerates a `KeyError` from `self.registry.group_slots(...)` for the Maps
   branch, per its own comment at `:520`) from needing any special-casing for
   this new item — both already degrade correctly. **Placement**: this makes
   Master Sheets the LAST top-level item, after every registry category root.
   The plan does not specify an order; this is the least-disruptive default —
   flag if the reviewer wants it first instead.
6. After `select_tutorial()` (`:497-503`), before the `# -- ● markers` comment
   at `:505`, add:
   ```python
   # -- Master Sheets item (E5, D9) -----------------------------------------

   def select_master_sheets(self):
       """Programmatic selection of the Master Sheets item (tests, initial
       selection) — mirrors select_theme/select_tutorial. No parent to
       expand: it is top-level (D9)."""
       if self._master_sheets_item is None:
           raise KeyError("no Master Sheets item")
       self.setCurrentItem(self._master_sheets_item)
   ```
7. In `_emit_selection`, after the `_TIMELINE_ROLE` block's `return` at
   `:584`, before the `_SCREEN_ROLE` check at `:585`, add:
   ```python
   if items[0].data(0, _MASTER_SHEETS_ROLE):
       # Master Sheets item (D9): a NEW TOP-LEVEL item, not hung off any
       # category — there is no "master_sheets" balancing domain to gate a
       # domain_selected emission on (unlike Theme/Timeline, nested under
       # "ui"/"buildings"). Own signal only, never node_selected.
       self.master_sheets_selected.emit()
       return
   ```
   **This never emits `domain_selected`.** (The plan's Tests bullet for E5
   says "the selector emits the new signal plus `domain_selected` and never
   `node_selected`" — that phrasing is the Theme/Timeline boilerplate reused
   without adjusting for D9's top-level placement; those two ARE nested under
   a real category and gate `domain_selected` on it, Master Sheets has no such
   category. Test `domains_seen == []` on this selection, not `assertIn`.)

### 2.2 `editor/main.py`

1. Import, alphabetical block `:66-81`: insert between `map_details` (`:72`)
   and `palette` (`:73`):
   ```python
   from editor.panels.master_sheets import MasterSheetsPanel
   ```
2. Panel construction: after `self.timeline = TimelinePanel(data_dir=data_dir)
   # TimelinePLAN T5: Timeline leaf` at `:185`, before `self._screen_defaults
   = {}` at `:186`, add:
   ```python
   self.master_sheets = MasterSheetsPanel(data_dir=data_dir)  # MasterSheetColumnsPLAN E5: Master Sheets item
   ```
3. Signal connection: after `self.selector.timeline_selected.connect(
   self._on_timeline_selected)` at `:332`, add:
   ```python
   # Master Sheets wiring (MasterSheetColumnsPLAN E5): the top-level
   # "Master Sheets" item -> right_stack; reload on entry, the same
   # convention as every other selection-driven panel.
   self.selector.master_sheets_selected.connect(self._on_master_sheets_selected)
   ```
4. `right_stack` page: after `self.right_stack.addWidget(self.timeline)  #
   index 7: Timeline (TimelinePLAN T5)` at `:516`, add:
   ```python
   self.right_stack.addWidget(self.master_sheets)   # index 8: Master Sheets (MasterSheetColumnsPLAN E5)
   ```
5. Handler: after `_on_timeline_selected` (`:1383-1390`), before the
   `# -- frame drive` comment at `:1392`, add:
   ```python
   # -- Master Sheets panel (MasterSheetColumnsPLAN E5) ----------------------

   def _on_master_sheets_selected(self):
       """The selector's Master Sheets item: reload the registry fresh from
       disk (mirrors every other selection-driven panel's reload-on-entry
       convention) and show the panel."""
       self.master_sheets.reload_sheets()
       self.right_stack.setCurrentWidget(self.master_sheets)
   ```

### 2.3 `tools/tests/test_editor_viewport.py`

- `:1343`: `self.assertEqual(window.right_stack.count(), 8)` →
  `self.assertEqual(window.right_stack.count(), 9)`.
- `:1510`: `"editor.panels.sheet_picker, editor.panels.master_sheet_dialog, "`
  → append `"editor.panels.master_sheets, "` on the same or a new
  continuation line inside the string, anywhere in that block.
- **Do not touch `TestColumnSwitcher` at `:1540` onward** (E4's class, end of
  file).

### 2.4 `editor/panels/master_sheets.py` (new)

`class MasterSheetsPanel(QWidget)`, structured like `TimelinePanel`/
`GameThemePanel` (a docked `right_stack` page, not a `QDialog`) but with the
list+preview+detail layout of `MasterSheetDialog`
(`editor/panels/master_sheet_dialog.py:61-107`) — construction split from
display, same rule `sheet_picker.py` and `master_sheet_dialog.py` both follow
(no test `exec()`s a modal; there is no modal here at all except the file
browse, confined to one `_on_*_browse_clicked` each).

**Widgets**: `QListWidget` of every `MasterSheet` (label via a `_label(sheet)`
helper mirroring `MasterSheetDialog._label` at `:267-273` — display name, real
pixel size, grid, user count/"unused"); an embedded read-only
`SheetPreview(interactive=False)` (`editor/panels/sheet_preview.py`, off
limits to edit — call its existing `set_sheet(sheet.path, sheet.frame_w,
sheet.frame_h)` three-argument form, the whole-sheet default `:83-84`, no row
or column window — this panel shows the raw registry entry, not one slot's
window); a detail `QLabel` (word-wrap) reporting grid, `column_width`,
`columns`, user count/names; a **slicing edit row** — `_NoWheelSpinBox` ×3
(frame_w/frame_h/column_width, ranges from `frame_bounds`/
`column_width_bounds`) + a Colours `QLineEdit`, all **disabled with a tooltip
naming the linking slots** when `sheet.users` is non-empty (D10), enabled with
a Save button when empty; a separate **Re-import** groupbox — "Choose PNG…"
button (confines `QFileDialog` to `_on_reimport_browse_clicked`, mirrors
`master_sheet_dialog._on_browse_clicked`/`set_import_source`) plus its OWN
frame_w/frame_h/column_width/colours fields, seeded from the selected sheet on
every selection change, and a "Re-import" button.

**`reload_sheets()`** — the reload-on-entry method (`TimelinePanel.
set_timeline`'s naming precedent, adapted since this panel lists many sheets,
not one document): re-reads `master_sheet_import.master_sheets(self._data_dir)`,
refills the list, reselects the previously-selected sheet id if it still
exists (else selects the first row), and reseeds the detail/edit/re-import
fields for the current selection. `__init__` calls it once at the end
(`TimelinePanel.__init__` calling `self.set_timeline()` at `:526` is the
precedent).

**`save_selected()`** — the direct-edit write path (no PNG touched). Guard:
returns/no-ops if the selected sheet has users (defense in depth; the UI
already disables the controls). Otherwise: `parse_columns` the Colours field,
`load_registry_doc`, mutate `doc["entries"][sheet_id]`'s `frame_w`/`frame_h`/
`column_width`/`columns` (omit `columns` at empty, the `slice`/`tint_overlay`/
`row_start` convention — delete the key if now empty, add/overwrite it if
not), `write_registry_doc`, `reload_sheets()`.

**`reimport_selected(png_path, frame_w=None, frame_h=None, column_width=None,
columns=None)`** — the model half of Re-import; omitted numeric/columns
arguments default to the selected sheet's CURRENT stored values (what "seeded"
means). **This is a bespoke write path, not a call into
`master_sheet_import.import_master_sheet`** — see the correctness note below
for why. It:
1. Resolves the selected `MasterSheet`; returns `None` if none selected.
2. Computes `new_grid = (frame_w, frame_h, column_width)` (defaults applied)
   vs `old_grid = (sheet.frame_w, sheet.frame_h, sheet.column_width)`.
3. **If `sheet.users` and `new_grid != old_grid`**: raise
   `master_sheet_import.GridInUseError` (imported class, message built
   locally in the same shape as `import_master_sheet`'s own at
   `master_sheet_import.py:419-425` — reuse the message text pattern, not the
   function).
4. Otherwise: overwrite `destination = self._data_dir / "sprites" /
   sheet.ref` with `Path(png_path).read_bytes()` — **this is what "overwrites
   the PNG bytes in place" means**; `load_registry_doc`, mutate
   `doc["entries"][sheet.sheet_id]`'s `frame_w`/`frame_h`/`column_width`/
   `columns` in place (same omit-at-empty rule as `save_selected`) — **the id
   and the `file`/`display_name` keys are untouched**, so every manifest
   entry's `sheet` ref keeps resolving to the same file — `write_registry_doc`,
   `reload_sheets()`, return `sheet.sheet_id`.
5. `_on_reimport_clicked` wraps the call in `except (OSError, ValueError)` →
   `QMessageBox.warning`, the `master_sheet_dialog._on_import_clicked`
   precedent (`GridInUseError` subclasses `ValueError` on purpose, for exactly
   this catch).

**Correctness note — why Re-import cannot be `MasterSheetDialog.
perform_import()` / `import_master_sheet`, read before implementing.**
`import_master_sheet` derives its target id via `resolve_sheet_id`
(`master_sheet_import.py:304-343`), which — when the display name's slug
matches an EXISTING entry — walks that slug's numbered family
(`characters`, `characters_2`, …) looking for one whose STORED PNG is
byte-identical to the newly chosen file, and **mints a brand-new id
(`_unique_id`, the `characters_2` case) the moment the bytes differ and no
family member matches**. That is the exactly-right behavior for the picker's
"import a new sheet" flow (never silently overwrite unrelated art), but it is
the exactly-wrong behavior for THIS panel's promise ("keeps the id and every
link") whenever a designer swaps in genuinely different art — which is the
normal case "overwrites the PNG bytes in place" describes. Going through
`resolve_sheet_id` here would silently fork a second sheet id and leave every
existing manifest entry pointed at the stale one. `reimport_selected` sidesteps
this entirely by writing to the KNOWN `sheet.sheet_id` directly — it never
calls `resolve_sheet_id` or `import_master_sheet`. `master_sheet_import.py`
stays unedited (off limits, §3); E5 only imports its exported names
(`GridInUseError`, `load_registry_doc`, `write_registry_doc`, `master_sheets`,
`MasterSheet`, `frame_bounds`, `column_width_bounds`, `parse_columns`).

## 3. File scope + shared-file contract

**New**: `editor/panels/master_sheets.py`, `tools/tests/test_master_sheets_panel.py`.

**Modified, and ONLY these regions**:
- `editor/panels/selector.py` — the six insertion points in §2.1 above.
- `editor/main.py` — the five insertion points in §2.2 above.
- `tools/tests/test_editor_viewport.py` — **exactly two regions**: the
  `right_stack.count()` literal at `:1343` (8→9) and the `TestPurity` import
  string at `:1510` (append `editor.panels.master_sheets`). **Do not touch
  `class TestColumnSwitcher` at `:1540` onward (E4's, appended at the end of
  the file) or any test above line 1343.**
- `conftest.py` (`TIERS`) — after `"test_master_sheet_import": "editor",` at
  `:129`, add `"test_master_sheets_panel": "editor",` (same tier — Qt-heavy).
- `tools/tests/test_editor_panels.py` — add selector-tree tests for the new
  item (pattern: `test_theme_leaf_is_second_child_and_emits_theme_selected`
  and `test_tutorial_leaf_exists_under_ui_and_emits_tutorial_selected`,
  `:375-406`) — append near `TestSelectorTree` (`:277` onward), anywhere
  in that class.
- `editor/CLAUDE.md` — **APPEND ONLY.** Insert a new top-level section
  between the blank line at `:372` and `## Running the tests FROM the editor`
  at `:373` (E4's `## Master-sheet column switcher` section ends at `:371`,
  verified live on this branch):
  ```
  ## Master Sheets panel (`panels/master_sheets.py`, MasterSheetColumnsPLAN E5)

  <2-4 short paragraphs: the top-level selector item (D9, no domain_selected);
  reload_sheets/save_selected/reimport_selected; the ONE refcount is
  asset_import.sheet_users via MasterSheet.users, never a second; the
  reimport_selected correctness note from §2.4 above, condensed.>
  ```
  **If E3 has landed by the time you execute this and shifted these line
  numbers, re-grep for `## Master-sheet column switcher` and
  `## Running the tests FROM the editor` and insert between them regardless of
  the literal numbers above** — E3 only touches `details.py` and
  `panels/CLAUDE.md`, not `editor/CLAUDE.md`, so this section should be stable,
  but verify before writing.
- `editor/panels/CLAUDE.md` — **APPEND ONLY.** Insert a new top-level section
  between the blank line at `:1885` and `## TestRunnerPLAN TR-5` at `:1886`
  (the `### E1 — import path` subsection under `## Master-sheet dialog` ends
  at `:1884`, verified live on this branch):
  ```
  ## Master Sheets panel (`panels/master_sheets.py`, MasterSheetColumnsPLAN E5)

  <the panel's shape: list + embedded read-only SheetPreview + detail label;
  D10 lock (disabled controls + tooltip naming the linking slots) vs. the
  always-attemptable Re-import (GridInUseError decides, not a UI lock); why
  reimport_selected bypasses import_master_sheet/resolve_sheet_id (the
  correctness note, condensed); right_stack index 8.>
  ```
  If E3 has landed and shifted this, re-grep for `### E1 — import path` and
  `## TestRunnerPLAN TR-5` and insert between them.

**Off limits** (do not touch): `editor/panels/details.py`,
`editor/panels/sheet_preview.py`, `editor/panels/viewport.py`,
`editor/master_sheet_import.py`. E5 only **imports** exported names from
`master_sheet_import.py` — it must never edit that file. Phase E3 may be live
in a parallel worktree on `details.py`.

## 4. Exit gate + Quick Test

**Coder's gate (run these, nothing wider):**

```
py tools/smoke.py
py -m pytest tools/tests/test_master_sheets_panel.py tools/tests/test_editor_panels.py tools/tests/test_editor_viewport.py -q
```

Never the full suite, `testgate check`, `--affected`, or a tier sweep
(`-m core`/`-m editor`/`-m meta`).

**Tests — bare minimum, no exhaustive Qt matrix.** Write only what pins:
- The panel constructs and lists exactly what the registry holds (seed a temp
  registry via `master_sheet_import.import_master_sheet` in `setUp`, then
  `pin_empty_registry`-style clearing first — **never assert against live
  `data/` content**, follow `tools/tests/test_master_sheet_import.py`'s
  `make_png`/`pin_empty_registry` pattern).
- The detail text reports grid, `column_width`, `columns` and user count.
- Slicing controls are disabled for an in-use sheet (link a slot to it in the
  temp manifest first) and enabled for an unused one.
- `save_selected()` on an unused sheet writes a schema-valid registry through
  `write_registry_doc` (read it back with `data_io.load_json` + validate, or
  trust the writer and assert the new values round-trip via `master_sheets()`).
- `reimport_selected()` with **genuinely different PNG bytes** (not the same
  file — a test using identical bytes would pass by accident even through the
  broken `resolve_sheet_id` path and prove nothing) replaces the PNG and
  preserves the id and the links; `reimport_selected()` on an in-use sheet
  with an unchanged grid succeeds; with a changed grid raises
  `GridInUseError` and leaves the file/registry untouched.
- The selector emits `master_sheets_selected` on the new item, and asserts
  `domains_seen == []` (never `domain_selected`) and `nodes == []` (never
  `node_selected`) — see the §2.1 resolution of the plan's boilerplate Tests
  phrasing.
- `right_stack.count() == 9` and selecting the item routes to the panel.

Every widget constructed in a test destroyed via `qt_harness`
(`self.track(...)`), never a bare `close()`.

### Test-guard rule (verbatim)

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

**Quick Test (orchestrator/user, live `py editor/main.py`, not a coder gate):**
Open Master Sheets (the new top-level selector item). Confirm the list shows
every registered sheet with its grid/column_width/users. Select an unused
sheet, edit `column_width`, Save, confirm it round-trips. Select a sheet with
at least one linking slot, confirm the slicing controls are disabled and the
label names the linking slots. Re-import a sheet with a new PNG at the same
grid while it has users — confirm it succeeds and the linking slots still
resolve art. Re-import the same sheet at a different frame size while it still
has users — confirm it is refused with a message naming the slots.
