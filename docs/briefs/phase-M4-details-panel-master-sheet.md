# Phase M4 — DetailsPanel: button, row window, narrowed views

Source plan: `planning/GpuAndMasterSheetsPLAN.md` §6/M4 (lines 1081–1147),
decisions D3 (line 120), ED-30, E-35, E-37. Depends on **M2** (engine
`row_start` slicing + sheet-path-keyed store) and **M3** (`editor/
master_sheet_import.py` + `editor/panels/master_sheet_dialog.py`) — both landed.

**Goal (verbatim from the plan, line 1083): the designer flow from §1, end to
end, in the main importer. This is the phase with the most existing code to
respect.**

**Open with the `/add-editor-feature` skill.** It carries the conventions this
phase would otherwise rediscover badly: the `_NoWheel*` widget rule, the
`TestPurity` import list, the panels-doc update. Read it, then this brief.

---

## 0. FIRST STEP — confirm your checkout (non-negotiable)

Phase M2 lost its brief last run because a worktree-isolated agent branched from
`Development` and never noticed. Before reading a single source file:

```bash
git rev-parse HEAD
git merge-base --is-ancestor 367ff9c HEAD && echo "OK: 367ff9c is in history" \
  || git merge --ff-only 367ff9c
```

If the fast-forward fails (`Development` has moved past the merge base), **stop
and report** — do not `git merge` your way out of it, and never run `git reset
--hard` / `git restore` / `git stash` (root `CLAUDE.md` §Branching). A wrong
base here silently deletes M2's and M3's work from your diff.

Everything below assumes `editor/master_sheet_import.py` and
`editor/panels/master_sheet_dialog.py` exist. If they do not, your base is
wrong — stop.

---

## 1. Exit gate — READ THIS BEFORE THE PLAN'S OWN GATE LINE

The plan text at line 1143 says the gate is `py -m pytest -m editor`. **That
line does not apply to you.** `-m editor` is a TIER SWEEP, and
`.claude/hooks/test_guard.py` **denies tier sweeps to subagents** (root
`CLAUDE.md` §Test Suite Policy). A denied run is a report, never a retry, and
never a reworded retry — the guard normalises flags and fingerprints
identically.

Your gate, in full:

```bash
py tools/smoke.py
py -m pytest tools/tests/test_details_panel.py tools/tests/test_editor_panels.py tools/tests/test_master_sheet_import.py -x -q
```

Nothing wider. No `--affected` (its safety pass is the whole core tier — also
denied). No `py tools/testgate.py check` — the single full gate belongs to the
main session at handoff.

**The plan's live-editor gate (line 1143: "then a live `py editor/main.py` …")
is a HUMAN step, not yours.** Do not attempt it, do not launch the editor, do
not claim it. Your report says the two commands above and what they printed;
the main session runs the live pass with the user. Write your report's live
section as "NOT RUN — human step (M4 §1)".

Tests: **bare minimum**. Cover the behaviours §3 names and stop. No exhaustive
Qt matrix, no coverage sweep.

---

## 2. Rulings on M3's three carry-forwards

M3 left three things open. All three are decided here — implement them as
written; do not re-litigate, do not defer them again.

### 2.1 Re-import REFUSES a frame_w/frame_h change once the sheet has users — **YES**

`import_master_sheet`'s docstring (`editor/master_sheet_import.py:179-183`)
says: *"M3 deliberately has no refusal path for a changed grid: nothing links a
slot to a master sheet until M4."* **M4 is the phase that makes slots link.**
The moment a manifest entry points at `master/<id>.png` with a `row_start`, a
re-import that changes the grid re-cuts every linked window into different
pixels — wrong art, no error. That is the exact failure `resolve_sheet_id`'s
uniquify rule already exists to prevent (`:151-154`); this is the same rule,
one axis over.

Implement in `editor/master_sheet_import.py`:

- A module-level `class GridInUseError(ValueError)` with a docstring saying why
  it subclasses `ValueError` (see the wiring note below).
- In `import_master_sheet`, **after** `resolve_sheet_id` returns and **before**
  any file write: if `sheet_id` already exists in the registry, and its stored
  `frame_w`/`frame_h` differ from the arguments, and
  `sheet_users(load_manifest_doc(data_dir), master_ref(sheet_id))` is non-empty
  → raise `GridInUseError`. The message must NAME the users (they are what the
  designer has to fix) and say what to do: clear or re-point those slots first.
  Reuse `asset_import.sheet_users` — there is exactly one refcount in the
  editor (`:247-248`), do not write a second.
- **Zero users still allows the rewrite.** That is the flow M3's docstring
  documents — correcting a wrong `display_name` or `frame_w` without breeding a
  duplicate file — and nothing can be mis-cut when nothing is linked. Keep that
  sentence in the docstring and extend it with the new refusal.
- **The raise happens before the PNG copy and before `write_registry_doc`.** A
  refused import must leave disk byte-identical.

**Wiring cost: zero.** `master_sheet_dialog._on_import_clicked` already catches
`(OSError, ValueError)` and shows a `QMessageBox.warning`
(`editor/panels/master_sheet_dialog.py:215-219`), so a `ValueError` subclass
surfaces to the designer with no dialog edit. Say so in the class docstring, or
someone will later "clean up" the base class and silently turn the refusal into
a crash.

### 2.2 `resolve_sheet_id` matches only the base slug — **FIX**

Today `resolve_sheet_id` (`:141-169`) checks byte-identity against `entries[slug]`
only. So once `characters_2` exists, re-importing `characters_2`'s exact bytes
compares them against `characters`, finds a mismatch, and mints
`characters_3` — a third identical copy of the same PNG. That defeats the
one-PNG-one-entry invariant M2 built the sheet-path-keyed store on.

Fix: check the **slug family** for byte-identity, in id order — `slug`, then
`slug_2`, `slug_3`, … — and return the first byte-identical match; only
uniquify when none matches. Skip non-dict entries the same way the existing code
does (`:160-165`); that E-37 tolerance stays.

Scope the scan to the slug family, **not to every entry in the registry**. A
family scan fixes exactly the stated defect. Scanning all ids would also collapse
the same PNG imported deliberately under an unrelated display name into one
entry — a different behaviour change, not this phase's call. Put that reasoning
in the docstring next to the existing three-case list, which becomes four cases.

### 2.3 `sheet_preview.py` becomes row_start-aware — **YES, in this phase**

The plan already requires it ("Narrow the preview", line 1115). The carry-forward
question was only *where*, and the answer is here. Two binding constraints:

- **The window is OPT-IN and defaults to the whole sheet.** `set_sheet(png, fw,
  fh)` keeps its current three-argument signature working unchanged, so
  `sheet_picker.py` and `master_sheet_dialog.py`'s embedded read-only previews
  and every non-master DetailsPanel slot behave **byte-identically to before**.
  Add the window as optional parameters (`row_start=0, row_count=None`) or a
  separate `set_row_window(...)` — implementer's call; state which and why in
  your report.
- **Everything the widget emits or paints speaks ENTRY-RELATIVE rows.**
  `frame_clicked(row, col)` emits window-relative `row` (first visible row is
  `0`), and `set_rows(...)` is indexed window-relative. The window is applied
  ONCE, where the source rectangle is cut — the exact same discipline M2 imposed
  on the engine, where `AssetStore._frame_surface` is "the only place the window
  is applied" (plan lines 1004-1009). One vocabulary, one number, one place.

---

## 3. The work

**Files — modified:** `editor/panels/details.py`,
`editor/panels/sheet_preview.py`, `editor/master_sheet_import.py` (§2.1 + §2.2),
`editor/panels/CLAUDE.md`, `tools/tests/test_details_panel.py`,
`tools/tests/test_editor_panels.py`, `tools/tests/test_master_sheet_import.py`.
No new modules, so no `TestPurity` addition and no `conftest.TIERS` entry.
**Do not touch `engine/render/backend_gpu.py`** — fenced to phase G5.

### 3.1 The button

A third button, `"Use Master Spritesheet…"`, in the buttons row beside Import /
Use / Save / Clear (`details.py:293-304`). **Connect it wrapped in a lambda**, as
`_use_btn` and `_clear_btn` already are (`:300`, `:304`). A bare
`clicked.connect(self._method)` puts Qt's `checked` bool into the first kwarg —
the footgun that made Clear skip its confirm dialog for months.

It opens `master_sheet_dialog`, built the way `_on_use_clicked` opens the sheet
picker (`details.py:864`): construction split from display, so tests never
`exec()` a modal.

### 3.2 On selection

- Write the entry's `sheet` to the registry entry's **stored `file`, verbatim**
  — never re-derive `master/<id>.png` (`master_sheet_import.master_ref`'s
  docstring, `:63-71`).
- Adopt the master sheet's `frame_w`/`frame_h` into the entry and into
  `_row_frame_size`.
- **Disable the Frame W/H spinboxes** (`details.py:365-366`) with a tooltip
  saying the master sheet owns the grid (D3).
- This **bypasses `_on_frame_size_changed` on purpose** (`details.py:653-687`).
  That method writes the per-slot registry override into `slots.json` and
  re-saves; here the grid comes from the master sheet and **`slots.json` must not
  be touched**. Comment the bypass at the call site with that reason — a reviewer
  who does not know D3 will read it as a bug.

### 3.3 The `using rows [ ] til [ ]` row

Built exactly like the Frame W/H row: a `QHBoxLayout` of `QLabel` + two
`_NoWheelSpinBox` **imported from `editor.panels.balancing`**
(`details.py:55` already imports them) — never a bare `QSpinBox`; the mousewheel
is navigation-only across this editor. Commit on `editingFinished`, not
`valueChanged`.

Placed directly under the selection, visible only while the slot's sheet is a
master sheet — the same gating idiom as `_slice_row.setVisible(self._slice_applies())`
/ `_tint_row.setVisible(self._tint_applies())` (`details.py:407-408`,
`:630-637`). Add a `_master_applies()`-shaped predicate alongside them; it tests
the current `_sheet_ref`, not the category.

Bounds come from the sheet's real row count. **`a > b` must be
unrepresentable** (ED-30): clamp the second spin's minimum to the first's value
as the first changes — not an error caught at save time.

### 3.4 Narrow the rows

`_load_sheet` (`details.py:771-803`) builds one `RowEditor` per detected sheet
row; it now builds one per row **in the window**. Row 0 of the window stays
idle-locked — E-35 stays unrepresentable in the UI rather than becoming a
save-time error. `_on_frame_clicked` (`:839-849`) already indexes
`self._row_editors` directly, so §2.3's entry-relative signal makes it correct
with no arithmetic — do not add an offset there.

### 3.5 Save

`save()` (`:689-699`) writes `row_start` via `draft_entry()`; **omit the key when
it is 0** so a non-master entry stays byte-identical — the convention `slice`
(`:603-605`) and `tint_overlay` (`:613-617`) already follow.

`draft_entry()` must PRESERVE an existing `row_start` the same way it preserves
`anchors` (`:606-612`) for any path that does not author the window. Read that
comment before writing this one; it is the same argument in reverse.

### 3.6 Clear

`clear_entry` (`:701-751`) must refcount correctly against a master sheet other
slots still use. It already reads the entry's own `ref` and routes both
candidates through `asset_import.unreferenced_sheets` (`:734-736`) — check that
a `master/` ref survives that path unchanged, and **a master sheet with
remaining users must never be unlinked**. If the existing code already gets this
right, say so in your report rather than changing it.

---

## 4. Tests (bare minimum — these behaviours, nothing more)

`tools/tests/test_details_panel.py` / `test_editor_panels.py`:
- selecting a master sheet writes the master ref + inherited frame size and
  disables the Frame W/H spins;
- the `using rows` row appears only for a master sheet;
- setting the window rebuilds exactly that many `RowEditor`s and narrows the
  preview;
- `frame_clicked` on the first VISIBLE row routes to `RowEditor` 0;
- `save()` writes `row_start` and omits it at 0;
- Clear against a master sheet with remaining users does not unlink the PNG.

`tools/tests/test_master_sheet_import.py`:
- §2.1: a re-import with a changed grid and non-empty users raises
  `GridInUseError`, names the users, and leaves the PNG **and** the registry
  byte-identical; the same re-import with ZERO users succeeds and rewrites the
  entry;
- §2.2: re-importing `<slug>_2`'s exact bytes returns `<slug>_2`, not
  `<slug>_3`.

A `sheet_preview` window test (default arguments paint identically to
pre-change) goes wherever that widget is already covered.

**Test-harness rules, both learned the hard way** (`editor/CLAUDE.md`
§"Testing the editor"): subclass `QtCase` and `self.track(...)` every widget —
`close()` is not cleanup. And **never assert against live `data/`** — the master
registry is seeded EMPTY on disk, so write your own entries into a `TempDataCase`
dir. A session fixture fails the run if `data/` changes.

---

## 5. Report back

`/report` taxonomy: tag every claim **measured** (command + number) /
**verified** (read or ran it) / **inferred**. Include:

1. The two gate commands from §1 and their one-line results.
2. "Live editor pass: NOT RUN — human step (M4 §1)."
3. Which shape you chose for §2.3's window parameter and why.
4. §3.6: whether `clear_entry` needed a change or was already correct.
5. Anything in §2's rulings that turned out to be wrong when it met the code —
   report it, do not silently re-decide it.
