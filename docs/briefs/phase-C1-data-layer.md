# Phase C1 — Data layer (MasterSheetColumnsPLAN, Section S1)

Source plan: `planning/MasterSheetColumnsPLAN.md` §2 (D1, D2, D4, D12, "The one
thing forced by layering"), §3 → Section S1 → `#### Phase C1 — Data layer`.
Package doc to read FIRST: `data/CLAUDE.md`, "Asset data (Phase 5, D-30/31/32
specifics)" — specifically `data/CLAUDE.md:557-662`, the `row_start` / master-sheet
paragraphs. It is normative and wins over anything in this brief.

---

## 1. Goal + file scope

**Goal.** The two asset schemas learn about master-sheet *columns*, and the one
committed registry entry is migrated to carry its column width. No engine code,
no editor code, no behaviour change: after this phase every existing manifest
entry and every existing sheet still resolves to the exact same pixels, because
nothing reads the new keys yet (C2 does that).

**Files you may touch — this list is exhaustive.**

Modified:
- `data/schemas/master_sheets.schema.json`
- `data/schemas/asset_manifest.schema.json`
- `data/sprites/master_sheets.json`
- `data/CLAUDE.md`
- `tools/tests/test_assets_manifest.py`
- `tools/tests/fixtures/data/schemas/master_sheets.schema.json`
- `tools/tests/fixtures/data/schemas/asset_manifest.schema.json`
- `tools/tests/fixtures/data/sprites/master_sheets.json`

New: none.

**Out of scope — do not open, do not "fix in passing":** anything under
`engine/`, `editor/`, `game/`, `tools/smoke.py`, `tools/testgate.py`,
`tools/tests/test_master_sheet_import.py`, `tools/tests/test_asset_store.py`.
See §3 for the one known consequence outside this scope and what to do about it
(report it — do not patch it).

---

## 2. Design

House style, no exceptions (`data/schemas/*.schema.json` all follow it; check
`data/schemas/master_sheets.schema.json` as the model):

- `$schema` is draft 2020-12; `additionalProperties: false` at every object level.
- **Every** property carries a `description` that documents units and intent.
- **Every** numeric carries `minimum` and `maximum` — the editor derives its
  spinbox ranges from the schema rather than retyping them (ED-30). See
  `editor/master_sheet_import.py:115-123` for the read-from-the-schema precedent
  (`frame_w`'s bounds are read out of the schema, not hardcoded).
- Keys sorted, 2-space indent — the whole `data/` tree is written that way; match
  the file you are editing byte-for-byte in style.

### 2a. `data/schemas/master_sheets.schema.json` (D1, D2, D4)

The registry entry today has exactly four properties — `file`, `display_name`,
`frame_w`, `frame_h` — and **all four are `required`**
(`data/schemas/master_sheets.schema.json:39-44`, *verified*). That is why
`column_width` is required too, rather than optional: the entry object has no
optional-key convention to join, and the file holds exactly one entry to migrate.

Add into `properties` of the `^[a-z][a-z0-9_]*$` entry object (alphabetical
position: `column_width` and `columns` sort before `display_name`):

```json
"column_width": {
  "description": "How many frame-COLUMNS one master column spans (D1) — measured in FRAMES, never pixels, so a column boundary can never land mid-frame the way a raw pixel width can. A slot claiming master column c cuts x = (c * column_width + frame_col) * frame_w. A sheet whose art is one single column sets this to its full column count. Columns are MASTER-SHEET-ONLY (D2): a plain imported/<slot>.png has no column concept. Inherited onto a linking manifest entry, the same way frame_w/frame_h already are (D3); it cannot drift, because D10 refuses every slicing edit to a sheet that slots link.",
  "maximum": 256,
  "minimum": 1,
  "type": "integer"
},
"columns": {
  "description": "Optional per-column NAMES, in sheet order (D4): the colour swatch labels a building colour picker reads, or the season labels a season stepper reads. A sheet may author its columns in any order and offer any set; index i names master column i. Omitted => this sheet's columns are unnamed and are referred to by index. A building stores the column INDEX, not the name (D5), so two sheets in one upgrade chain must author their colours in the same order — nothing enforces that.",
  "items": {
    "maxLength": 32,
    "pattern": "^[a-z][a-z0-9_]*$",
    "type": "string"
  },
  "maxItems": 16,
  "minItems": 1,
  "type": "array",
  "uniqueItems": true
}
```

Then add `"column_width"` to the entry's `required` array. `columns` stays out
of `required`.

Also extend the top-level `description` (line 5) so it mentions that the registry
owns the column width as well as the frame grid — one clause, same D-citation
style the existing text uses.

### 2b. `data/schemas/asset_manifest.schema.json` (D3, D12, layering)

Three new **optional** per-entry keys — the fifth through seventh optional keys,
joining `slice`, `anchors`, `tint_overlay`, `row_start`. None of them goes into
`required` (`data/schemas/asset_manifest.schema.json:226-233`); omission is what
keeps every committed entry byte-identical, exactly the trick `row_start` used
(`data/CLAUDE.md:596-604`). Insert alphabetically (before `frame_h`).

```json
"column": {
  "description": "Optional master-column window origin: the 0-based master COLUMN this entry cuts from, the horizontal twin of row_start. Entry frame j of row i cuts sheet x = (column * column_width + j) * frame_w. Omitted => 0 => the entry is byte-identical to a pre-column entry, the same 'optional by omission from required' convention slice, tint_overlay and row_start follow. Master sheets only (D2): meaningless on an imported/<slot>.png entry, which has no columns. 0-based like row_start, hence a ceiling of 255.",
  "maximum": 255,
  "minimum": 0,
  "type": "integer"
},
"column_mode": {
  "description": "Optional declaration of WHO picks this entry's column (D3). 'manual' (or the key absent) => the stored 'column' above wins. Any other value => a live column supplied by the render path wins, falling back to the stored 'column' when the caller supplies none. The engine only ever distinguishes manual from not-manual (D12); it never learns what a season or a colour is — those meanings live in game/ and editor/, and this enum is the only place their names are written down. 'season' => the map's season stepper drives it; 'building_color' => the placed building's chosen colour index drives it.",
  "enum": ["manual", "season", "building_color"],
  "type": "string"
},
"column_width": {
  "description": "How many frame-columns one master column spans, INHERITED from the linked master sheet's registry entry (sprites/master_sheets.json). It is a second copy of a registry value and exists only because engine/ never reads the registry from the cut path — the store sees entry.sheet as an opaque relative path. It cannot drift: no slicing value on a sheet may change while any slot links it. Omitted => 0 => column * 0 + frame_col == frame_col => byte-identical resolution for every pre-column entry.",
  "maximum": 256,
  "minimum": 1,
  "type": "integer"
}
```

Note the deliberate asymmetry to state in the description and NOT to "fix":
`column_width`'s schema `minimum` is 1, while the *engine's* omitted-default is
0 (`column * 0 + col == col`). 0 is not a legal authored value; it is only the
in-memory default for an absent key. C2 owns that default — you write schema only.

`column_mode` is a bare `enum` with no default keyword: JSON Schema `default` is
annotation-only here and the loader owns the fallback. Do not add `"default"`.

### 2c. `data/sprites/master_sheets.json` — migration

One entry, `slinger_t2_lvl3`: `data/sprites/master/slinger_t2_lvl3.png` is
960×576 at `frame_w` 64 / `frame_h` 96 = **15 cols × 6 rows** (*measured*,
handed down — do not re-derive). It gets:

```json
"column_width": 15
```

and **no `columns` key** — the sheet is one single column spanning the whole
image, and its column is unnamed. Result (sorted keys):

```json
"slinger_t2_lvl3": {
  "column_width": 15,
  "display_name": "slinger_t2_lvl3",
  "file": "master/slinger_t2_lvl3.png",
  "frame_h": 96,
  "frame_w": 64
}
```

`data/sprites/asset_manifest.json` is **not** edited: no entry gains a column
key, which is the point of making all three optional.

### 2d. `data/CLAUDE.md`

Extend the Asset data section in place, matching the surrounding voice:

- In the `sprites/master_sheets.json ↔ schemas/master_sheets.schema.json`
  bullet (`data/CLAUDE.md:605-629`): update the inline shape to include
  `column_width` (+ optional `columns`), and add a sub-bullet stating D1
  (frames not pixels), D2 (master-sheet-only) and D4 (names optional, index is
  the identity). Say plainly that **nothing reads either key yet** — C1 ships
  schema + migration only, C2 applies the column in exactly one place in
  `engine/assets` — mirroring how the `row_start` paragraph ends
  (`data/CLAUDE.md:603-604`).
- In the manifest optional-keys area (`data/CLAUDE.md:564-604`): add a
  `column` / `column_mode` / `column_width` paragraph next to the `row_start`
  one, stating that they are a SLICING concern and never a playback one, that
  omission is byte-identical, that `column_width` is an inherited copy of the
  registry value and why layering forces that, and D12's line about what the
  engine is allowed to know.
- Note (do not fix): lines 564-579 contain a near-duplicated "the four OPTIONAL
  per-entry keys" bullet. Do not attempt to dedupe it in this phase — just keep
  the count honest in whichever bullet you extend, or add your paragraph as a
  new sibling bullet and leave the old text alone.

### 2e. Tests — `tools/tests/test_assets_manifest.py`

Everything goes in the existing `TestMasterSheetSchemas` class
(`tools/tests/test_assets_manifest.py:389-447`), which already validates
hand-built documents against the **pinned fixture** schemas
(`MASTER` / `MANIFEST`, lines 398-399) — never live `data/`. Keep that.

**First, and load-bearing:** the `sheet_entry()` helper
(`tools/tests/test_assets_manifest.py:405-410`) builds an entry with only
`file` / `display_name` / `frame_w` / `frame_h`. Once `column_width` is
required, every existing negative test in that class would start passing for the
*wrong reason* (rejected for the missing key, not for the thing it names). Add
`"column_width": 4` to the helper's default dict.

Then the **bare minimum** that pins the behaviour — this list is a CEILING, not
a floor. Write these and nothing more; do not invent extra coverage, do not
parametrise beyond what is written here:

Registry:
1. A registry entry carrying `column_width` (and no `columns`) validates.
2. An entry with `column_width` deleted is rejected.
3. `column_width` of `0` and of `257` are each rejected (one `subTest` loop).
4. A `columns` array with a duplicate (`["red", "red"]`) is rejected, and one
   with a bad name (`"Red"`) is rejected (one `subTest` loop is fine).

Manifest:
5. An entry with none of the three new keys still validates (extend or sit
   beside `test_entry_without_row_start_and_master_sheet_both_validate`).
6. `column: -1`, `column_mode: "seasonal"`, and `column_width: 0` are each
   rejected (one `subTest` loop).

Match the existing style exactly: `unittest`, `assertRaises(ValidationError)`,
`with self.subTest(...)` inside loops, no new imports, no new helpers beyond the
`sheet_entry` default above.

---

## 3. Shared files / coordination

**`tools/tests/test_assets_manifest.py` is yours for this phase.** Phase C2
edits the same file, but LATER and SEQUENTIALLY — C1, C2 and C3 run one after
another inside Section S1, never concurrently. So there is **no shared-file
contract to honour and nothing to defend**: append where it reads naturally,
don't carve out reserved regions, don't leave "C2 goes here" markers.

**The pinned fixture schemas must move with the real ones.** Both files you are
editing have fixture twins, and they are byte-identical today (*measured*:
`diff -q` clean on both):

- `tools/tests/fixtures/data/schemas/master_sheets.schema.json`
- `tools/tests/fixtures/data/schemas/asset_manifest.schema.json`

`TestMasterSheetSchemas` validates against the **fixture** copies
(`tools/tests/test_assets_manifest.py:398-399`), so a schema edit that does not
reach the fixture makes your new tests fail against the old schema — and a
fixture that drifts from live `data/` is exactly the drift the pin exists to
make visible. Sync them with the snapshot's own tool, which is the sanctioned
door:

```
py tools/tests/fixture_data.py --refresh
```

It re-mirrors live `data/*.json` into `tools/tests/fixtures/data/` and prints
every path it changed (`tools/tests/fixture_data.py:56-83`). Expect **exactly
three** changed paths: the two schemas plus `sprites/master_sheets.json`.

- It writes only under `tools/tests/fixtures/` — it never writes into `data/`.
- It prints `Now run the full suite: py tools/testgate.py check` when it
  finishes. **Ignore that line** — see §4; it is not your gate.
- If it reports any path beyond those three, live `data/` had already drifted
  from the pin before you arrived. **Report that upward and stop** — do not
  revert it, do not `git restore` anything (destructive git is forbidden), and
  do not investigate.

**Known consequence outside your scope — report, do NOT patch.** Making
`column_width` required means a registry entry written by the editor's existing
import path is no longer schema-valid: `import_master_sheet` builds its entry
dict with only `file` / `display_name` / `frame_w` / `frame_h`
(`editor/master_sheet_import.py:276-281`) and writes it through
`write_registry_doc` → `write_validated`
(`editor/master_sheet_import.py:107`), so importing a master sheet in the editor
will raise until Section S2 adds the column-width field to that form. The tests
that cover it (`tools/tests/test_master_sheet_import.py`) will go red for the
same reason. **This is a section-level sequencing question, not yours to
resolve.** Do not touch `editor/**` and do not touch that test file. Name it in
your report to the orchestrator, in one line, and move on.

---

## 4. Verification

### Test budget (verbatim, binding)

> Your gate is `py tools/smoke.py` plus `py -m pytest <the specific test files
> you edited> -x -q`. Nothing wider. You may NOT run the full suite, a tier
> sweep (`-m core` / `-m editor` / `-m meta`), `py tools/testgate.py check`, or
> `--affected` — a `PreToolUse` hook denies all four for subagents.
>
> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to your orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.
>
> Two denies are expected and must not be fought: *"already ran this exact
> target and NOTHING has changed"* (the guard fingerprints the MAIN checkout's
> diff; worktrees are gitignored, so your own edits can be invisible to it —
> accept the quoted earlier result, and if it was a FAIL you believe you have
> since fixed, say exactly that in your report) and *"another test run is
> already in flight"* (do not wait-loop, do not delete the lock — report and
> stop).

### Exit gate

```
py tools/smoke.py
py -m pytest tools/tests/test_assets_manifest.py -x -q
```

Both green, zero failures, zero unexpected skips. Nothing wider.

`py tools/smoke.py` is load-bearing here, not ceremony: it validates the
committed `data/sprites/master_sheets.json` against the live
`data/schemas/master_sheets.schema.json` via ordinary stem pairing
(`data/CLAUDE.md:611-617`). So the schema edit and the migration **must land
together** — the moment `column_width` becomes required, an unmigrated registry
fails smoke loud. If you land only one half, smoke tells you immediately.

### Quick Test (in-game / by hand — the ORCHESTRATOR or the user runs this, not you)

Not a game-visible phase; the by-hand check is a data check:

1. `py tools/smoke.py` → passes, i.e. the migrated registry is valid.
2. `git diff --stat data/sprites/asset_manifest.json` → **empty**. Not one byte
   of the manifest may change in C1; if it did, an optional key was made
   required by mistake.
3. Open `data/sprites/master_sheets.json` and confirm the single
   `slinger_t2_lvl3` entry reads `"column_width": 15` and has no `columns` key.
4. Launch the game (`py game/main.py`), reach a wave with the slinger, and
   confirm its sprite looks **exactly as before** — C1 must be visually inert.

### Report

Tag every claim **measured** (command + number) / **verified** (you read or ran
it) / **inferred**. Include: the three files `fixture_data.py --refresh`
changed, the one-line editor consequence from §3, and the two gate results
collapsed to one line each. Do not paste raw pytest output. Do not commit, do
not push, do not open a PR.
