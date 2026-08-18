# Phase E1 — Import path

Source plan: `planning/MasterSheetColumnsPLAN.md` §3 → Section S2 → `#### Phase E1`
(plan lines 398-447). Branch base: `section-S2`. Goal (plan): "A master sheet
can be imported with a column width and column names."

**E1 lands FIRST in S2, before E2-E5.** It supersedes S1's C3 stopgap
(`import_master_sheet` deriving `column_width` from sheet width) with the real
designer-supplied field. All citations below are verified against the current
`section-S2` tree, not the plan doc's (drifted) line numbers — see the "Anchor
drift" note at the end of this brief.

---

## 1. Behavioral spec

### What changes, observably

Today, "Import new master spritesheet…" in the Master Spritesheets dialog
(`editor/panels/master_sheet_dialog.py`) collects a PNG, a display name and a
frame size, then writes a `column_width` that is *silently derived* from the
PNG's width (`editor/master_sheet_import.py:346-367`, the S1/C3 stopgap: "one
column spanning the whole sheet"). After E1, the import form has two more
rows — **Column width** and **Colours** — and the designer's own values are
written verbatim. `columns` (names) is optional and omitted from the registry
entry when the designer leaves it blank.

### The facts to pin, each verified against the current tree

1. **Current signature** —
   `import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h)`
   (`editor/master_sheet_import.py:285`). **New signature:**
   `import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h,
   column_width, columns=())`. `column_width` gets **no default** — same
   shape as `frame_w`/`frame_h`, which also have none — because it is now a
   real designer input, not a derived stopgap.
2. **The stopgap derivation to delete** — `editor/master_sheet_import.py:346-367`:
   ```python
   cw_min, cw_max = column_width_bounds(data_dir)
   with Image.open(destination) as image:
       sheet_w, _ = image.size
   doc["entries"][sheet_id] = {
       "file": master_ref(sheet_id), "display_name": name,
       "frame_w": frame_w, "frame_h": frame_h,
       "column_width": max(cw_min, min(cw_max, sheet_w // frame_w)),
   }
   write_registry_doc(data_dir, doc)
   return sheet_id
   ```
   Replace wholesale (§2). **verified**
3. **`GridInUseError`'s guard compares only `(frame_w, frame_h)` today** —
   `editor/master_sheet_import.py:313-339`: `stored_grid` is built at
   `:314-315` from `existing.get("frame_w")`/`existing.get("frame_h")` and
   compared at `:316`. It must extend to
   `(frame_w, frame_h, column_width)` (D10) — a re-import that changes ONLY
   `column_width` on a sheet with users must raise exactly like a frame-size
   change does today, same ordering (raised **before** the PNG copy at
   `:341-344` and **before** the registry write at `:368`), and
   `GridInUseError` keeps subclassing `ValueError` so
   `master_sheet_dialog._on_import_clicked`'s `except (OSError, ValueError)`
   (`editor/panels/master_sheet_dialog.py:215-219`) still catches it with no
   dialog edit. **verified**
4. **`column_width_bounds()` already exists** — `editor/master_sheet_import.py:164-175`,
   sibling of `frame_bounds()` (`:149-161`), reads `(minimum, maximum)` off
   `master_sheets.schema.json`'s `column_width` property (schema: 1..256,
   `data/schemas/master_sheets.schema.json:15-20`). **Reuse it verbatim for
   the dialog's new spinbox** — never retype `1, 256` (ED-30). **verified**
5. **The schema's `columns` array** (`data/schemas/master_sheets.schema.json:21-32`):
   optional, 1-16 items, each a unique string matching `^[a-z][a-z0-9_]*$`,
   max 32 chars. **The exact same pattern `_slugify()` already guarantees**
   (`editor/master_sheet_import.py:196-204`, its docstring says so outright:
   "matching master_sheets.schema.json's `^[a-z][a-z0-9_]*$` entry-key
   pattern"). **verified**
6. **`MasterSheet` dataclass** — `editor/master_sheet_import.py:372-395`.
   Fields today: `sheet_id, ref, path, display_name, frame_w, frame_h, width,
   height, users`. Gains `column_width: int` and `columns: tuple`, inserted
   after `frame_h` (grouping the grid-ownership fields together, D3/D4), read
   off the registry entry the same defensive way `frame_w`/`frame_h` already
   are (`:435-436`, `entry.get(..., 1)`) inside `master_sheets()`
   (`:398-442`, construction at `:430-439`). **verified**
7. **`grid()` must NOT change return arity.** `MasterSheet.grid()`
   (`editor/master_sheet_import.py:390-395`) returns a 2-tuple
   `(width // frame_w, height // frame_h)` and is unpacked as exactly that in
   TWO places **outside E1's file scope**:
   `editor/panels/vfx_preview.py:439` (`_cols, rows = sheet.grid() if sheet
   is not None else (0, 0)`) and `editor/panels/vfx_preview.py:474` (`cols,
   sheet_rows = sheet.grid()`). Changing `grid()` to a 3-tuple would raise
   `ValueError: too many values to unpack` in a file E1 may not touch — a real
   regression in the live VFX preview panel, not just a stale test. **This is
   a deliberate deviation from the plan doc's literal wording** ("`grid()`
   gains a `columns` count") — see §2 for the resolution (a new, separate
   method). **measured** (grep-verified, both call sites read above).
8. **`_build_import_box`** — `editor/panels/master_sheet_dialog.py:104-139`.
   Builds Choose-PNG / Display-name / Frame-width / Frame-height rows, then
   the Import button. Two new rows go between Frame height and Import.
9. **`perform_import()`** — `editor/panels/master_sheet_dialog.py:188-202` —
   calls `import_master_sheet(self._data_dir, self._png_path,
   self._name.text(), self._frame_w.value(), self._frame_h.value())`. Must
   thread the two new fields.
10. **`RegistryUnreadableError`** (`editor/master_sheet_import.py:51-70`,
    raised by `_assert_registry_readable` at `:178-193`, called as the FIRST
    line inside `import_master_sheet` at `:304`) is untouched by this phase —
    its ordering (before name resolution, before the PNG copy) is preserved
    automatically as long as the new code is added at/after the existing call
    site, not before it. Do not regress it.
11. **Known, deliberate collateral breakage, OUT OF E1's SCOPE.**
    `import_master_sheet`'s new `column_width` positional has no default, so
    every 5-positional-arg call site outside `tools/tests/test_master_sheet_import.py`
    breaks with `TypeError: missing 1 required positional argument`. Two exist:
    `tools/tests/test_vfx_preview.py:235-236` and
    `tools/tests/test_details_panel.py:528-529`. **Both files are on E1's
    explicit "may NOT touch" list.** This is expected — a later phase in this
    same section (whichever one touches `details.py`/`vfx_preview.py`) fixes
    its own call site as part of its own work; sections/phases in `section-S2`
    run sequentially in one tree, so a transient red in an unrelated test file
    is not this phase's exit gate's concern. **Say this explicitly in your
    report; do not attempt to fix it — that means editing files outside your
    scope.** **measured** (grep-verified: `import_master_sheet\(` has exactly
    9 matching files repo-wide; the two named are real, current call sites).

---

## 2. Architecture plan

### `editor/master_sheet_import.py`

**(a) New signature + body for `import_master_sheet`** (replaces
`:285-369` wholesale):

```python
def import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h,
                         column_width, columns=()):
    """... (keep the existing docstring's re-import/GridInUseError
    paragraphs; update to say column_width is now the real designer value,
    not a derived stopgap, and that `columns` is written only when non-empty
    — omit-at-default, the `slice`/`tint_overlay`/`row_start` convention)."""
    data_dir = _data_dir(data_dir)
    _assert_registry_readable(data_dir)          # UNCHANGED — keep first
    png_path = Path(png_path)
    name = (str(display_name or "").strip() or png_path.stem)
    sheet_id = resolve_sheet_id(data_dir, png_path, name)
    frame_w, frame_h, column_width = int(frame_w), int(frame_h), int(column_width)
    columns = tuple(columns)

    doc = load_registry_doc(data_dir)
    doc.setdefault("version", 1)
    doc.setdefault("entries", {})
    existing = doc["entries"].get(sheet_id)
    stored_grid = ((existing.get("frame_w"), existing.get("frame_h"),
                     existing.get("column_width"))
                   if isinstance(existing, dict) else None)
    if stored_grid is not None and stored_grid != (frame_w, frame_h, column_width):
        ref = existing.get("file")
        if not isinstance(ref, str):
            ref = master_ref(sheet_id)
        users = sheet_users(load_manifest_doc(data_dir), ref)
        if users:
            raise GridInUseError(
                f"'{sheet_id}' is cut at {stored_grid[0]}×{stored_grid[1]} "
                f"(column width {stored_grid[2]}) by {len(users)} slot(s): "
                f"{', '.join(users)}. Re-importing it at {frame_w}×{frame_h} "
                f"(column width {column_width}) would re-cut every row/column "
                f"window into different pixels. Clear or re-point those slots "
                f"first, then import again.")

    destination = data_dir.joinpath(*MASTER_SUBDIR) / f"{sheet_id}.png"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not _same_bytes(png_path, destination):
        destination.write_bytes(png_path.read_bytes())

    entry = {
        "file": master_ref(sheet_id),
        "display_name": name,
        "frame_w": frame_w,
        "frame_h": frame_h,
        "column_width": column_width,
    }
    if columns:
        entry["columns"] = list(columns)
    doc["entries"][sheet_id] = entry
    write_registry_doc(data_dir, doc)
    return sheet_id
```

Notes:
- The `Image.open`/`cw_min, cw_max` block is gone entirely — `column_width` is
  no longer derived, so nothing needs the PNG's pixel width at write time.
  `Image` stays imported (still used by `master_sheets()`).
- No clamping of `column_width` inside this function — exactly like
  `frame_w`/`frame_h`, which are never clamped here either; out-of-range
  values are caught by the schema at `write_registry_doc`'s `write_validated`
  call. The dialog is what makes out-of-range unrepresentable (ED-30), via
  `column_width_bounds()` feeding the spinbox range — see (c).
- **`columns=()` is NOT "preserve the existing entry's names."** It means
  "this call names no colours," so the key is omitted — same as calling with
  a fresh `columns` each time. There is no re-import-seeds-the-form flow in
  today's dialog for `frame_w`/`frame_h` either (the designer re-types them
  from scratch to correct a wrong grid); `columns` follows the same,
  pre-existing pattern. Do not build seeding — out of scope.

**(b) `GridInUseError`'s docstring** (`:73-90`) — extend the "WHY REFUSE"
paragraph one sentence: the guard now also covers `column_width`, per D10.

**(c) New pure helpers, added after `column_width_bounds()` (`:164-175`):**

```python
def columns_bounds(data_dir=None):
    """``(max_items, max_length)`` for the registry's optional ``columns``
    array, READ FROM THE SCHEMA — sibling of `frame_bounds`/
    `column_width_bounds` for the same ED-30 reason: the numbers have exactly
    one home. Falls back to the schema's own (16, 32) if unreadable (E-37)."""
    try:
        schema = data_io.load_json(schema_path(data_dir))
        prop = (schema["properties"]["entries"]["patternProperties"]
                ["^[a-z][a-z0-9_]*$"]["properties"]["columns"])
        return int(prop["maxItems"]), int(prop["items"]["maxLength"])
    except (OSError, ValueError, KeyError, TypeError):
        return 16, 32


def parse_columns(text, data_dir=None):
    """Comma-separated colour/season names (the dialog's Colours field) into a
    tuple ready for ``import_master_sheet``'s ``columns=`` argument.

    Each non-blank entry is slugified with the SAME `_slugify` sheet ids use
    — guaranteeing the schema's `^[a-z][a-z0-9_]*$` item pattern is met by
    construction, never re-checked against a retyped regex (ED-30). A blank
    entry (stray/trailing comma, whitespace) is dropped silently, never
    padded into a fake colour. What DOES raise `ValueError`, before any
    write: a duplicate slug (schema `uniqueItems`), a slug over the schema's
    max length, or more entries than the schema's max item count — all three
    would otherwise surface as an opaque `jsonschema.ValidationError` out of
    `write_registry_doc`, which the dialog's `except (OSError, ValueError)`
    cannot catch."""
    max_items, max_length = columns_bounds(data_dir)
    slugs = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        slug = _slugify(part)
        if len(slug) > max_length:
            raise ValueError(
                f"Colour/season name '{part}' is too long after slugifying "
                f"(max {max_length} characters).")
        if slug in slugs:
            raise ValueError(
                f"Colour/season name '{part}' repeats (as '{slug}') — "
                f"each entry must be unique.")
        slugs.append(slug)
    if len(slugs) > max_items:
        raise ValueError(
            f"{len(slugs)} colour/season names given; the schema allows at "
            f"most {max_items}.")
    return tuple(slugs)
```

**(d) `MasterSheet` dataclass** (`:372-395`) — insert two fields after
`frame_h`:

```python
    frame_w: int
    frame_h: int
    column_width: int
    columns: tuple      # declared colour/season names, () if unnamed (D4)
    width: int
    height: int
    users: tuple
```

Add a NEW method after `grid()` — **not a third `grid()` return value** (see
§1.7 for why):

```python
    def column_count(self):
        """How many MASTER columns (colour/season blocks) fit across this
        sheet's width, at its own `column_width` (frames) and `frame_w`
        (D1): `width // (column_width * frame_w)`. Distinct from `grid()`'s
        frame-column count on purpose — `grid()` stays a 2-tuple because
        `editor/panels/vfx_preview.py:439`/`:474` already unpack it as one
        and are out of this phase's scope."""
        return self.width // (self.column_width * self.frame_w)
```

**(e) `master_sheets()`** (`:398-442`) — in the `MasterSheet(...)`
construction at `:430-439`, add:

```python
            column_width=int(entry.get("column_width", 1)),
            columns=tuple(entry.get("columns") or ()),
```

(inserted after `frame_h=int(entry.get("frame_h", 1)),`, before `width=width,`
— matches the dataclass field order in (d)).

### `editor/panels/master_sheet_dialog.py`

**(f) `_build_import_box`** (`:104-139`) — add `cw_low, cw_high =
master_sheet_import.column_width_bounds(self._data_dir)` beside the existing
`low, high = master_sheet_import.frame_bounds(self._data_dir)` line, then two
new widgets + form rows between the Frame-height row and the Import button:

```python
        self._column_width = _NoWheelSpinBox(box)
        self._column_width.setRange(cw_low, cw_high)
        self._column_width.setValue(cw_low)
        self._column_width.setToolTip(
            "How many frame-columns one colour/season column spans. The "
            f"schema caps a master sheet at {cw_high} frames wide, so a "
            "sheet with more frames than that cannot be imported.")

        self._colours = QLineEdit(box)
        self._colours.setPlaceholderText(
            "Comma-separated colour/season names (optional)")
        self._colours.setToolTip(
            "Each name is slugified to lowercase_with_underscores. Leave "
            "blank for an unnamed sheet, referred to by column index.")
```

and in the `QFormLayout` block, add two `form.addRow(...)` calls between
`form.addRow("Frame height", self._frame_h)` and `form.addRow(self._import)`:
`form.addRow("Column width", self._column_width)` and
`form.addRow("Colours", self._colours)`.

**(g) `perform_import()`** (`:188-202`) — validate colours BEFORE the write
(so a rejection never touches disk), then thread both new values:

```python
    def perform_import(self):
        if self._png_path is None:
            return None
        columns = master_sheet_import.parse_columns(
            self._colours.text(), self._data_dir)
        sheet_id = master_sheet_import.import_master_sheet(
            self._data_dir, self._png_path, self._name.text(),
            self._frame_w.value(), self._frame_h.value(),
            self._column_width.value(), columns=columns)
        self._sheets = master_sheet_import.master_sheets(self._data_dir)
        self._filter.clear()
        self._refill()
        self.select_sheet(sheet_id)
        return sheet_id
```

`_on_import_clicked` (`:215-219`) needs no change — its existing
`except (OSError, ValueError)` around `self.perform_import()` already catches
`parse_columns`'s `ValueError` the same way it catches `GridInUseError`.

### `tools/tests/test_master_sheet_import.py` — mechanical updates forced by
the signature change

**Every** existing call to `import_master_sheet(...)` in this file (currently
19 call sites — grep it yourself, do not trust a stale count) needs a
`column_width` argument appended, since it no longer has a default. Pick any
schema-valid int (1-256); it does not need to relate to `frame_w`. Two classes
need real thought, not just an appended digit:

- `MasterSheetImportTest.test_import_writes_png_and_schema_valid_entry`
  (`:60-73`) — this is the "writes a schema-valid entry" pin from the Tests
  list. Rewrite it to pass an explicit `column_width` and a non-empty
  `columns=(...)`, and assert the FULL entry dict including `columns`. Add a
  SEPARATE small test asserting an empty/default `columns` omits the key
  entirely (`self.assertNotIn("columns", ...)`).
- `GridInUseTest` (`:198-264`) — `setUp` (`:201-206`) picks the sheet's
  starting `column_width`; add TWO new tests: (1) a re-import that changes
  **only** `column_width` (frame size unchanged) with a linked slot raises
  `GridInUseError`; (2) the same re-import with **zero** linked slots
  succeeds and rewrites the entry's `column_width`. These are the "fires /
  does not fire" pair the plan's Tests list asks for.

Also add, for `MasterSheet.column_count()`: extend
`test_master_sheets_lists_users_orphans_and_sorts_by_display_name`
(`:110-137`) — give the "zebra crowd" import an explicit `column_width` and
assert `by_id[shared].column_count()` equals the expected int (its existing
`by_id[shared].grid(), (4, 4)` assertion is untouched, since `grid()`'s arity
does not change).

Add a small, Qt-free class for `parse_columns` (it touches no filesystem):

```python
class ParseColumnsTest(unittest.TestCase):
    def test_slugifies_and_drops_blanks(self):
        self.assertEqual(
            master_sheet_import.parse_columns(" Deep Red, , ANCIENT-blue "),
            ("deep_red", "ancient_blue"))

    def test_duplicate_slug_is_rejected(self):
        with self.assertRaises(ValueError):
            master_sheet_import.parse_columns("Red, red")
```

And extend `MasterSheetDialogTest.test_dialog_lists_registry_and_returns_the_selected_id`
(`:273-299`) — its two direct `import_master_sheet(...)` calls (`:277`,
`:279`) need a `column_width` argument each; and in the dialog-driven import
block (`:290-296`), set `dialog._column_width.setValue(...)` and
`dialog._colours.setText("Pink, Blue")` before calling `perform_import()`,
then assert the written entry's `column_width`/`columns` (read
`data_io.load_json(self.data_dir / "sprites" / "master_sheets.json")
["entries"]["gamma_crowd"]` — `data_io` is already imported in this file).
This is the "dialog constructs, collects the two new fields and imports
without opening a modal" pin.

**This is a ceiling, not a floor — bare minimum, no exhaustive matrix. See
Tests policy below.**

---

## 3. File scope + shared-file contract

### Files you may modify — ONLY these four

| File | Edit |
|---|---|
| `editor/master_sheet_import.py` | new signature + body of `import_master_sheet`; extend `GridInUseError`'s guard tuple + docstring; new `columns_bounds()`/`parse_columns()`; `MasterSheet` gains `column_width`/`columns` + `column_count()`; `master_sheets()` populates the two new fields |
| `editor/panels/master_sheet_dialog.py` | `_build_import_box` gains the Column width spin + Colours line edit; `perform_import()` threads both |
| `editor/panels/CLAUDE.md` | ONE new subsection, APPENDED — see below |
| `tools/tests/test_master_sheet_import.py` | signature-forced updates to every existing `import_master_sheet(...)` call + the new/extended tests in §2 |

**You may NOT touch:** `editor/panels/details.py`, `editor/panels/sheet_preview.py`,
`editor/panels/viewport.py`, `editor/panels/selector.py`, `editor/panels/vfx_preview.py`,
`editor/main.py`, or any test file other than `tools/tests/test_master_sheet_import.py`
— including `tools/tests/test_vfx_preview.py` and `tools/tests/test_details_panel.py`,
which WILL go red from this phase's signature change (§1.11). That is expected
and owned by whichever later S2 phase touches those two files' subjects; name
it in your report, do not fix it.

### `editor/panels/CLAUDE.md` — shared with E2/E3/E4/E5, APPEND ONLY

The master-sheet section runs from the `## Master-sheet dialog (...)` heading
at line 1751 through the `SheetPreview`'s row-window paragraph, which ends
`"...That is why \`DetailsPanel._on_frame_clicked\` needs no offset."` at
**line 1849**. Line 1850 is blank; line 1851 is the NEXT `##` heading
(`## TestRunnerPLAN TR-5 — ...`). **Insert your new subsection at line 1850**
— i.e. immediately after line 1849 and before the blank-line-then-heading —
as a new `###` block, mirroring the existing `### DetailsPanel ▸ master
sheets (...)` subsection's style (`:1801`). Suggested content (adapt to
whatever you actually built):

```markdown
### E1 — import path: column width + column names (MasterSheetColumnsPLAN)
- **Import collects the real designer-supplied `column_width`** and an
  optional comma-separated **Colours** field, replacing S1's C3 stopgap
  derivation. `import_master_sheet(data_dir, png_path, display_name, frame_w,
  frame_h, column_width, columns=())` — `columns` is omitted from the entry
  when empty (the `slice`/`tint_overlay`/`row_start` convention); it is NOT
  preserved across a re-import that omits it, the same way `frame_w`/
  `frame_h` are never seeded from the existing entry either.
- **`GridInUseError`'s comparison tuple is `(frame_w, frame_h, column_width)`**
  (D10) — a re-import that changes only `column_width` on a sheet with users
  is refused exactly like a frame-size change, same ordering (before the PNG
  copy, before the write).
- **`master_sheet_import.parse_columns(text)`** is the pure slugify+validate
  step the Colours field runs through before any write (ED-30): each
  comma-separated entry is slugified with the same `_slugify` sheet ids use;
  a duplicate slug, an over-length slug, or more than the schema's item cap
  raises `ValueError` there, never as an opaque `ValidationError` from the
  write.
- **`MasterSheet.column_count()`** is a NEW method, not a third `grid()`
  return — `grid()` stays a 2-tuple on purpose because
  `editor/panels/vfx_preview.py:439`/`:474` already unpack it as one and are
  out of this phase's file scope.
```

**Never rewrite the surrounding text** — not the M3/M4 prose above your
insertion point, not the TR-5 heading below it. If your content needs more
than ~15 lines, trim it; this file is shared with three other phases landing
in the same section and a big diff here is a merge hazard for all of them.

### Tests — bare minimum, not maximum

Write the minimum that pins the behaviour in §2's test list. No exhaustive Qt
matrix, no parametrised sweep over every colour-name edge case beyond the one
slugify case and the one rejection case named above.

---

## 4. Exit gate + Quick Test

### Exit gate — run this, nothing wider

```
py tools/smoke.py
py -m pytest tools/tests/test_master_sheet_import.py -q
```

The gate is ZERO: all green, or you are not done. **Do not** run the full
suite, a tier sweep (`-m core`/`-m editor`/`-m meta`), `py
tools/testgate.py check`, or `--affected` — a `PreToolUse` hook denies all
four for subagents.

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

### Quick Test (in-game — the orchestrator or the user runs this, not you)

`py editor/main.py` → open the Master Spritesheets dialog (via DetailsPanel's
"Use Master Spritesheet…" button, or the VFX preview panel's equivalent) →
"Import new master spritesheet…" → choose any PNG, give it a display name and
a frame size, set **Column width** to something other than 1, type
`Red, Blue, Red` into **Colours** and click Import. Expect a warning dialog
naming the duplicate colour, with nothing written to disk. Fix it to
`Red, Blue`, click Import again: the sheet appears in the list, and
`data/sprites/master_sheets.json` (on disk) shows the new entry with
`"column_width"` at your chosen value and `"columns": ["red", "blue"]`.

---

## Anchor drift from the plan doc — reported, not corrected in place

The plan doc's phase block cites `GridInUseError`'s guard at
`master_sheet_import.py:246-269`; the current tree has it at `:313-339` (the
module grew between C1/C2/C3 landing and now — `resolve_sheet_id`,
`_slug_family`, `RegistryUnreadableError` and its plumbing were all added
after the plan doc's phase block was written). This brief's citations are all
verified against the current `section-S2` tree, not the plan doc.
