# Phase M3 — Editor: pure master-sheet import module + picker dialog

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6/M3 (lines 1029–1079),
decisions D1 (line 102), D3 (line 120), D5 (line 134), orphan policy §9
(`data/CLAUDE.md`, "Orphans are legal and deliberate").

**Goal (verbatim from the plan, line 1031): master sheets can be imported and
listed. No DetailsPanel changes yet.**

**Open with the `/add-editor-feature` skill.** Do not hand-roll the dialog. The
skill carries the conventions this phase would otherwise rediscover badly:
panel/dialog registration, the `_NoWheel*` widget rule, the `TestPurity` import
list, the `conftest.TIERS` entry. Read it first, then this brief.

---

## 1. Behavioral spec (every claim cited)

### 1.1 What already exists (M1 landed — do not re-do it)

- `data/schemas/master_sheets.schema.json` exists.
  `data/schemas/master_sheets.schema.json:55-58` requires `version` + `entries`;
  `:50-53` pins `version` to `const: 1`; `:11` keys entries by
  `^[a-z][a-z0-9_]*$`; `:39-44` makes `file`, `display_name`, `frame_w`,
  `frame_h` all required; `:23` pins `file` to
  `^master/[a-z][a-z0-9_]*\.png$`; `:26-37` bounds both frame dimensions
  `1..1024`; `:15-20` bounds `display_name` to `minLength 1` / `maxLength 80`.
- `data/sprites/master_sheets.json` is seeded `{"entries": {}, "version": 1}`
  (`data/sprites/master_sheets.json:1-4`) — **verified**: the registry is
  EMPTY on disk today, so every test must write its own entries and must never
  assert a count against live `data/`.
- `data/sprites/master/` exists and is tracked by a `.gitkeep`
  (**measured**: `ls data/sprites/master/ -a` → `.gitkeep` only).
- The manifest schema already admits `master/<id>.png` in `sheet` and the
  optional `row_start` key (`data/CLAUDE.md`, "Since M1 the pattern admits two
  folders"). **M3 writes neither** — M4 does.
- `master_sheets.json` pairs with its schema by NORMAL stem
  (`data/CLAUDE.md`, "Normal stem pairing — no fifth smoke directory
  exception"). Nothing in `tools/smoke.py` needs touching.

### 1.2 `editor/master_sheet_import.py` (NEW, Qt-free, pygame-free, Pillow-only)

Mirror `editor/asset_import.py` function-for-function. That module's imports are
`shutil`, `dataclasses`, `pathlib`, `PIL.Image`, `engine.data_io`
(`editor/asset_import.py:16-22`) — the new module's import list is the same
(minus `shutil` if you use `read_bytes`/`write_bytes`, as
`editor/font_import.py:65` does).

**`load_registry_doc(data_dir)`** — an exact structural copy of
`asset_import.load_manifest_doc` (`editor/asset_import.py:32-43`): read
`Path(data_dir) / "sprites" / "master_sheets.json"` via `data_io.load_json`;
on `OSError`/`ValueError`, or on a doc that is not a dict, or whose `entries`
is not a dict, return `{"version": 1, "entries": {}}`. This is the E-37
"pre-import state is normal" degrade — the file is seeded empty today but a
corrupt one must not crash the editor.

**`write_registry_doc(data_dir, doc)`** — the ONE write path for this file, the
twin of `asset_import.write_manifest_doc` (`editor/asset_import.py:46-52`):
`data_io.write_validated(doc, data_dir/"sprites"/"master_sheets.json",
data_dir/"schemas"/"master_sheets.schema.json")`. No other module in this phase
may call `write_validated` on this file (ED-31).

**`master_ref(sheet_id)` → `f"master/{sheet_id}.png"`** — the twin of
`asset_import.sheet_ref` (`editor/asset_import.py:25-29`), and it MUST carry
the same docstring warning that module carries: *a consumer always reads the
entry's stored `file` / the manifest entry's `sheet`, never re-derives the path
from a key.* The reason is stated at `editor/asset_import.py:9-14`: the engine
resolves `sprites_dir / entry.sheet` verbatim (`engine/assets/store.py`), so a
re-derived path is a silently wrong file.

**`import_master_sheet(data_dir, png_path, display_name, frame_w, frame_h)` →
`sheet_id`.** Ordered algorithm:

1. Slugify. Copy `editor/font_import.py:20-26`'s `_slugify` exactly
   (`re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")`, prefixed when
   empty or leading-digit) with the prefix changed from `font` to `sheet`. The
   result must satisfy the schema's `^[a-z][a-z0-9_]*$`
   (`data/schemas/master_sheets.schema.json:11`) — that is what the prefix rule
   buys. Source of the name: `display_name`, falling back to
   `Path(png_path).stem` (`editor/font_import.py:59` precedent).
2. Resolve the id against existing entries.
   - If the base slug is unused → that is the id.
   - If it IS used and the existing entry's PNG on disk is **byte-identical** to
     `png_path` (or is literally the same file, `Path.resolve()` equality) →
     **reuse that id**. This is the re-import case: the sheet is already in the
     library.
   - Otherwise → uniquify with `editor/font_import.py:29-35`'s `_unique_id`
     (`<slug>_2`, `<slug>_3`, …). **Never overwrite a different sheet's entry
     under a colliding name**: a master sheet is linked by path from manifest
     entries (`data/CLAUDE.md`, "A sheet may be SHARED — `sheet` is a path"), so
     overwriting `master/characters.png` with different art would silently
     re-point every slot already cutting it. *(This resolution is **inferred**
     from the font-import precedent; the plan states the collision case only as
     a test, not as a rule. Flagged in §"Open questions".)*
3. Copy the bytes to `data_dir/"sprites"/"master"/f"{sheet_id}.png"`, creating
   the parent with `mkdir(parents=True, exist_ok=True)`. **Skip the copy when
   the source and destination resolve to the same path, or when the destination
   already exists with identical bytes** — the same "re-importing the same PNG
   leaves the file (and the diff) untouched" rule
   `editor/asset_import.py:160-163` implements for `imported/`.
4. Write the entry through `write_registry_doc`:
   `{"file": master_ref(sheet_id), "display_name": <name>, "frame_w": fw,
   "frame_h": fh}` — exactly the four required keys
   (`data/schemas/master_sheets.schema.json:39-44`), no extras
   (`additionalProperties: false`, `:12`).
5. Return `sheet_id`.

A re-import that reuses an id therefore leaves the PNG untouched but rewrites
the entry, so a designer can correct a `display_name` or a wrong `frame_w`
without producing a duplicate file. *(Also **inferred** — see §"Open
questions".)*

**`master_sheets(data_dir)` → a list of frozen dataclasses.** Shape it on
`asset_import.ImportedSheet` (`editor/asset_import.py:72-99`) and
`asset_import.imported_sheets` (`:102-118`):

- One item per **registry entry** (not per file on disk — the registry is the
  authority here, unlike `imported/` which is globbed at
  `editor/asset_import.py:109`). Sort by sheet id, or by `display_name`; pick
  one and say which in the docstring.
- Fields: `sheet_id`, `ref` (`master/<id>.png`, from the entry's stored `file`,
  never re-derived), `path`, `display_name`, `frame_w`, `frame_h` (the DECLARED
  grid), `width`/`height` (the REAL pixel size, read with `Image.open` — lazy
  header parse only, `editor/asset_import.py:105`), and `users`.
- `grid()` returns `(width // frame_w, height // frame_h)` at the entry's OWN
  declared frame size — no caller-supplied frame size, because D3
  (`planning/GpuAndMasterSheetsPLAN.md:120-128`) says the master sheet owns the
  grid and a linking slot inherits it. This is the one real divergence from
  `ImportedSheet.grid(frame_w, frame_h)` (`editor/asset_import.py:88-91`), and
  the reason `fits()` (`:93-99`) has no analogue here: there is no target frame
  size to filter against.
- An unreadable or missing PNG is SKIPPED from the list, never fatal (E-37) —
  same `except (OSError, ValueError): continue` shape as
  `editor/asset_import.py:113-114`. A registry entry whose file has vanished is
  a real state (someone deleted a PNG by hand).
- **`users` reuses `asset_import.sheet_users(doc, ref)`
  (`editor/asset_import.py:55-61`) against the MANIFEST doc loaded once via
  `asset_import.load_manifest_doc`.** Do not write a second refcount. `ref` is
  the entry's `master/<id>.png` string, which is exactly what a linking
  manifest entry stores in `sheet`, so the existing equality test works
  unchanged.

**Deliberately NOT in this module: `pad_to_frame`**
(`editor/asset_import.py:121-136`). That helper CENTRES undersized art on a
transparent canvas. A master sheet is a grid the designer authored; centring it
would shift every row by `(pad - size) // 2` and silently break every
`row_start` window M2/M4 cut from it. Say this in the module docstring so the
next reader does not "restore parity" with `asset_import`.

**Orphan policy (§9 / `data/CLAUDE.md`): nothing in this phase deletes a master
sheet or a registry entry.** A master sheet with zero users stays on disk, stays
in the registry, and stays listed in the picker — that is how you get it back.
There is no Clear/Delete affordance in M3, and `unreferenced_sheets`
(`editor/asset_import.py:64-69`) has no analogue here because nothing collects.

### 1.3 `editor/panels/master_sheet_dialog.py` (NEW, Qt)

Two branches, in one dialog:

- **Import new master spritesheet…** — a file chooser plus three inputs
  collected **before anything is written**: `display_name` (QLineEdit),
  `frame_w`, `frame_h`. The frame size cannot be deferred: D3
  (`planning/GpuAndMasterSheetsPLAN.md:120-128`) makes the registry the owner of
  the grid, and there is no later screen that could supply it. Spin ranges come
  from the schema's own `minimum`/`maximum` (1..1024,
  `data/schemas/master_sheets.schema.json:26-37`) so out-of-range input is
  unrepresentable (ED-30) — read them from the schema file, do not retype the
  numbers.
- **Use existing…** — a list of everything `master_sheets(data_dir)` returns,
  each row described with its **real size, its grid at its declared frame size,
  and its user count**, plus a filter box and an embedded read-only
  `SheetPreview`.

`chosen()` returns the selected sheet id (or the id just imported); `None` when
cancelled. That id is what M4's DetailsPanel will consume — M3 stops at
returning it.

---

## 2. Architecture plan

**Open with `/add-editor-feature`.** (Second statement, per the dispatch: the
skill is the canonical pattern for a new editor panel/dialog and it is what
keeps registration, the `_NoWheel*` rule, the purity guard and the TIERS entry
consistent.)

**Layering.** `editor/master_sheet_import.py` is Qt-free, pygame-free,
Pillow-only — the same class as `editor/asset_import.py`
(`editor/CLAUDE.md`: "Pure helpers used by panels: … `asset_import.py` … all
Qt-free/pygame-free, in `TestPurity`"). It imports `engine.data_io` and nothing
from `game/` (root layering rule).

**Dialog shape — copy `editor/panels/sheet_picker.py` structurally.** The parts
that matter and why:

- **Construction is split from display; nothing in a test calls `exec()`.**
  `SheetPickerDialog.__init__` builds every widget and ends with `self._refill()`
  (`editor/panels/sheet_picker.py:37-82`); the model is exposed through pure
  methods — `visible_sheets()` (`:86-94`), `chosen()` (`:96-100`),
  `select_sheet(ref)` (`:102-110`). Tests construct the dialog, call those, and
  never open a modal. `editor/panels/CLAUDE.md` states the rule generally for
  the selector's context menu: "construction … is split from display so tests
  never `exec()` a modal popup (`QAction.trigger()` is the test path)".
- **Filter + list + preview + detail label + `QDialogButtonBox`**, laid out as
  `editor/panels/sheet_picker.py:61-81`. Ok is enabled only when something is
  selected (`:134-137`); double-click accepts (`:55`); `_try_accept` refuses an
  empty selection (`:162-164`).
- **Per-row label carries size + grid + users**, the shape at
  `editor/panels/sheet_picker.py:118-128` (`name  W×H  (cols×rows frames)` plus
  a used-by suffix). Adapt: always show the grid, since the frame size is the
  sheet's own; show `— unused` for a zero-user sheet (an orphan is normal, not
  an error).
- **`SheetPreview(interactive=False, parent=self)`**
  (`editor/panels/sheet_picker.py:57`; the widget is
  `editor/panels/sheet_preview.py:55-60`, `set_sheet(png_path, frame_w,
  frame_h)` at `:81`). Read-only: no cell clicking, no row state. Feed it the
  sheet's own declared `frame_w`/`frame_h`.
- **Every value widget is a `_NoWheel*`** imported from
  `editor.panels.balancing` — never a bare `QSpinBox`/`QComboBox`. This is an
  editor-wide convention, stated in `editor/panels/CLAUDE.md`: "EVERY value
  widget anywhere in the editor … imports
  `_NoWheelSpinBox`/`_NoWheelDoubleSpinBox`/`_NoWheelComboBox` FROM
  `balancing.py` (their one home)".
- **`data_dir=None` injection** on both the module functions and the dialog, so
  tests run against a temp copy (`editor/panels/CLAUDE.md` Phase 4: "every
  editor module takes `data_dir=None`").
- **The dialog never calls `write_validated` itself** — it calls
  `master_sheet_import.import_master_sheet`, which owns the one write path.

**What this phase deliberately does NOT wire.** Nothing opens this dialog yet.
`DetailsPanel` grows the button in M4 and `VfxPreviewPanel` in M5 (D5,
`planning/GpuAndMasterSheetsPLAN.md:134-138`). A dialog nothing constructs is
the correct M3 end state — the tests are what construct it.

---

## 3. File scope + shared-file contract

**NEW**
- `editor/master_sheet_import.py`
- `editor/panels/master_sheet_dialog.py`
- `tools/tests/test_master_sheet_import.py`

**MODIFIED**
- `tools/tests/test_editor_viewport.py` — add **both** new modules to the
  `TestPurity` import string. The list is at
  `tools/tests/test_editor_viewport.py:1492-1525`; append
  `editor.master_sheet_import` beside `editor.asset_import` (`:1495`) and
  `editor.panels.master_sheet_dialog` beside `editor.panels.sheet_picker`
  (`:1509`). This is the layering guard — `editor/` must never import `game/`
  (`editor/CLAUDE.md`: "Every new editor module MUST be added to
  `test_editor_viewport.TestPurity`'s import list").
- `conftest.py` — ONE `TIERS` entry: `"test_master_sheet_import": "editor"`.
  **A module missing from `TIERS` is a hard error, not a silent skip**
  (`conftest.py:19-23`); an unmarked module would simply never run. Tier is
  `editor` because the file builds Qt widgets — and `test_widget_tree` is
  already filed `editor` even though it is Qt-free, purely for tracking with the
  editor suites (`conftest.py:170-173`). **No `tools/ci_shards.py` edit is
  needed** (**inferred** from `tools/tests/test_ci_shards.py:99-103`: the
  `editor-rest` shard selects the tier and ignores only the explicitly-listed
  heavy files) — if `test_ci_shards` goes red, report it rather than widening
  scope.
- `editor/CLAUDE.md` — one bullet in the "Pure helpers used by panels" list for
  `master_sheet_import.py` (say Pillow-only, in `TestPurity`, and that
  `pad_to_frame` is deliberately absent).
- `editor/panels/CLAUDE.md` — a short section for the dialog, in the house style
  of the existing per-panel sections.

**Nothing else.**

**FORBIDDEN, explicitly:**
- `editor/panels/details.py` and `editor/panels/vfx_preview.py` — those are
  phases M4 and M5. M3 stops before any DetailsPanel change (the plan's own goal
  line, `planning/GpuAndMasterSheetsPLAN.md:1031`).
- `engine/**` — phase **M2 is running concurrently in a separate worktree** and
  owns `engine/assets/manifest.py` + `engine/assets/store.py`
  (`planning/GpuAndMasterSheetsPLAN.md:994-996`).
- `data/**` — M1 already landed the schema, the seed and the folder. Do not
  re-seed, do not add a sample master sheet to the repo.
- `tools/smoke.py` — normal stem pairing already covers `master_sheets.json`
  (`data/CLAUDE.md`). If it does not, that is a finding to REPORT, not to patch.

**Shared-file contract with M2: there is none.** M2's file set
(`engine/assets/manifest.py`, `engine/assets/store.py`,
`engine/assets/CLAUDE.md`, `tools/tests/test_assets_manifest.py`,
`tools/tests/test_asset_store.py` — plan lines 994–996) and M3's file set above
are **disjoint**. The two phases touch no file in common, so there is no
insertion-point negotiation to do. If you find yourself wanting to edit an
`engine/` file, stop and report instead — that is M2's diff, in another
worktree, and editing it here produces a merge conflict, not a feature.

**Insertion points inside the two shared TEST files** (shared with future
phases, not with M2):
- `tools/tests/test_editor_viewport.py` — the `code = (...)` string literal at
  `:1492`. Add two names to the existing string; change nothing else in that
  file.
- `conftest.py` — the `TIERS` dict at `:36-175`. Add exactly one key, in the
  alphabetical-ish neighbourhood of the other editor entries. Do not reorder,
  do not touch `TIER_TIMEOUTS`.

---

## 4. Exit gate + Quick Test

**Open with the `/add-editor-feature` skill** (third and final statement — this
is the phase's opening move, not an afterthought).

### The exit gate you (the coder) run — exactly this, nothing wider

```bash
py tools/smoke.py
py -m pytest tools/tests/test_master_sheet_import.py tools/tests/test_editor_viewport.py -q
```

**This is a DELIBERATE DOWNGRADE from the plan's wording.**
`planning/GpuAndMasterSheetsPLAN.md:1078-1079` writes the exit gate as
`py -m pytest -m editor` for the Qt tier. That is a **tier sweep**, and
`.claude/hooks/test_guard.py` DENIES a tier sweep from a subagent — running it
produces a denied command and a stalled agent, not a check. The root
`CLAUDE.md` §"Test Suite Policy" role table wins over the plan doc, and the plan
itself says so at §8 (`:1187`): a dispatched coder runs `py tools/smoke.py` +
`py -m pytest tools/tests/test_<file>.py -q` over the files it touched,
"nothing wider". So: the two commands above, and **not** `py -m pytest -m
editor`, **not** `py tools/testgate.py check`, **not** `--affected`, **not** the
full suite. The single full `check` is the main session's step at handoff.

**A denied test run is a REPORT, never a retry** (`:1191-1199`). Do not reword
the command; the guard normalises flags and fingerprints it identically.

The gate is ZERO failures.

### Tests to write — bare minimum, no exhaustive Qt matrix

In `tools/tests/test_master_sheet_import.py`, over a temp data dir. **Tests must
never write into `data/`**: subclass `TempDataCase` (`tools/tests/temp_data.py`
line 127) for the Qt half and `DataDirCase` (line 111) for the pure half, and
**never assert against live `data/` content** — the registry ships EMPTY
(`data/sprites/master_sheets.json:1-4`) and a test that assumes so is asserting
what a designer has not yet done. Write your own entries.

**The temp-data helper already copies what you need — no extension required.**
**Verified**: `fresh_data_dir` does a whole-tree `shutil.copytree` of `data/`
(`tools/tests/temp_data.py:100-107` via `template_data()` at `:85`), pruning
only `.wav/.mp3/.ogg/.mp4` bytes (`:51`) and dropping `balancing_history/`
(`:56`). PNGs are explicitly NOT stubbed (`:22-24`). So `sprites/master_sheets
.json` and `sprites/master/.gitkeep` arrive in every temp copy already. The
plan's §8 flag (`:1215-1217`) is therefore **discharged with no code change** —
say so in your report; do not add a special case to `temp_data.py`.

1. **Import writes the PNG and a schema-valid entry.** Build a small sheet with
   Pillow (the `pin_slot_rows` precedent, `tools/tests/temp_data.py:179-189`),
   `import_master_sheet(...)`, then assert
   `data_dir/"sprites"/"master"/f"{id}.png"` exists and that the registry
   validates — validation comes free from `write_registry_doc` going through
   `write_validated`, so asserting the entry's four keys plus a re-load is
   enough.
2. **Re-importing the same bytes leaves the file untouched.** Import, record the
   destination's bytes and `st_mtime_ns`, import the identical source again,
   assert the id is the same and the file was not rewritten.
3. **Slugification**: spaces → `_`; punctuation → `_`; a leading digit gets the
   prefix; a collision with an existing DIFFERENT sheet yields a new unique id
   and does not clobber the first entry.
4. **`master_sheets()` reports users correctly for a sheet two slots point at.**
   Write two manifest entries whose `sheet` is `master/<id>.png` (the manifest
   schema admits it since M1) and assert `users` is both slot keys, sorted —
   the `asset_import.sheet_users` contract (`editor/asset_import.py:55-61`).
   Also cover the zero-user orphan case: it is still listed.
5. **The dialog constructs, lists what the registry holds, and returns the
   selected id — without opening a modal.** One Qt test. Seed two registry
   entries, construct the dialog inside `self.track(...)` (the `QtCase`
   contract — `close()` only hides; `TempDataCase`'s docstring,
   `tools/tests/temp_data.py:128-135`), assert its model method returns both,
   select one, assert `chosen()`. No `exec()`.

### Quick Test (in-game / in-editor — the orchestrator or the user runs this, not you)

1. `py editor/main.py`.
2. There is no button yet (by design — M4 wires it), so drive the dialog the way
   the phase is meant to be checked: from a Python shell in the repo root,
   `from editor.panels.master_sheet_dialog import MasterSheetDialog` under a
   running `QApplication`, or add a throwaway local call you do NOT commit.
   Alternatively state plainly in the report that the dialog is unreachable from
   the running editor in M3 and defer the live look to M4's Quick Test.
3. In the dialog: choose **Import new master spritesheet…**, pick a PNG with
   several character rows stacked in it, type a display name and the real frame
   size, confirm.
4. Confirm on disk: `data/sprites/master/<slug>.png` exists, and
   `data/sprites/master_sheets.json` has gained one entry with that
   `display_name` and frame size, still sorted-keys / 2-space formatted.
5. Re-open the dialog, choose **Use existing…**: the new sheet is listed with
   its real pixel size, its grid, and "unused" (no manifest entry points at it
   yet); the embedded preview shows the sheet gridded at the declared frame
   size.
6. Re-import the SAME PNG with the same name: no duplicate file appears, and
   `git status` shows no change to the PNG.
7. `py tools/smoke.py` still passes with the new registry content
   (it schema-validates every data file, including this one).

---

## Open questions (need an orchestrator/user decision, or an explicit "coder's
call")

1. **Collision policy** — the plan lists "collision with an existing id" only as
   a test case, never as a rule. This brief specifies *uniquify, never
   overwrite* (`<slug>_2`), by the `editor/font_import.py:29-35` precedent.
   **Inferred.** If the intended behaviour is "replace the existing sheet", say
   so before the coder starts, because the two produce different files on disk.
2. **Re-import with a CHANGED frame size or display name** — this brief
   specifies: reuse the id, leave the PNG untouched, rewrite the entry (so a
   designer can correct a wrong grid without a duplicate file). **Inferred.**
   The alternative — refuse, because slots may already be cutting that grid at
   that size (D3) — is defensible and is arguably safer once M4 lands. Worth a
   ruling.
3. **Sort order of `master_sheets()`** — by id or by `display_name`. Cosmetic;
   the coder's call, but pin it in a docstring so the dialog's list order is not
   accidental.
4. **The dialog is unreachable from the running editor in M3** (nothing
   constructs it until M4). That makes the live Quick Test partly artificial.
   This is inherent to the plan's phasing, not a defect in it — but the
   orchestrator should decide whether to accept the shell-driven check above or
   to defer the live look to M4.

---

## 5. Orchestrator rulings (binding — these close the planner's open questions)

1. **Id collision: UNIQUIFY, never overwrite. CONFIRMED.** `<slug>_2` per the
   `editor/font_import.py:29-35` precedent. Overwriting `master/characters.png`
   would silently re-point every manifest entry already cutting that file — a
   wrong-pixels bug with no error, which is exactly the class D10 and the E-37
   split exist to avoid. The plan listed collision only as a test case; this is
   the rule it implies.
2. **Re-import with a changed frame size or display name: reuse the id, leave
   the PNG untouched, rewrite the entry. CONFIRMED for M3.** The "refuse it"
   alternative is the safer one only once slots actually inherit the grid, and
   in M3 nothing does — no panel links a slot to a master sheet until M4. Do NOT
   build a refusal path here. Whether M4 must guard re-import against sheets
   that already have users is M4's question; note it in your report so it is not
   lost.
3. **`master_sheets()` sorts by `display_name`**, case-insensitively, with the
   id as the tie-break — it is what the picker shows, so it is what a designer
   scans. Pin the order in the docstring and in one test.
4. **The shell-driven Quick Test is ACCEPTED; the live look defers to M4.** The
   dialog is genuinely unreachable from the running editor in M3 because nothing
   constructs it until M4 — that is the phasing working as designed, not a gap
   to paper over. Do not wire it into a panel to make it demonstrable; that is
   M4's file scope and is forbidden here.
5. **`tools/temp_data.py` needs NO edit — the planner verified this.** Its
   whole-tree `copytree` (`:85`, `:100-107`) already carries
   `data/sprites/master_sheets.json` and `data/sprites/master/` into every temp
   copy. The plan's §8 flag is discharged. Report it; do not extend the helper.
6. **If `test_ci_shards` goes red, REPORT it — do not widen scope into
   `tools/ci_shards.py`.** The `editor-rest` shard selects by tier and ignores
   only explicitly-listed heavy files (`tools/tests/test_ci_shards.py:99-103`),
   so it should stay green on its own.
