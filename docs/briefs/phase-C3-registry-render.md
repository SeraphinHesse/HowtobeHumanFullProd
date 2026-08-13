# Phase C3 — Master-sheet registry loader + render threading

Source plan: `planning/MasterSheetColumnsPLAN.md` §3 → Section S1 → `#### Phase C3`
(plan lines 282-333). Branch base: `section-S1`.

**C3 lands AFTER C1.** C1 makes `column_width` a REQUIRED key on
`data/schemas/master_sheets.schema.json` and migrates the one committed registry
entry. Every registry fixture you write must carry `column_width`, or
`data_io.load_validated` rejects it. C2 runs CONCURRENTLY with you in a separate
worktree — read §3 before you touch `engine/assets/CLAUDE.md`.

---

## 1. Behavioral spec

### What changes, observably

Nothing in the game or the editor looks different. C3 is plumbing: it adds a pure
reader for `data/sprites/master_sheets.json` that both `game/` and `editor/` may
import, and threads a per-item `column` from a component down to the asset store.
With every `column` at its default `0`, every `DrawCall` is identical to today's.

### The four behaviours to pin

1. **`engine/assets/master_registry.load_registry(data_dir)` fails LOUD.** Same
   rule as `engine/assets/registry.py:156-160`'s `load_registry` for
   `slots.json` — "the registry is infrastructure, like geometry.json"
   (`engine/assets/CLAUDE.md:44-48`, the E-37 tolerance split). Read via
   `engine.data_io.load_validated` (`engine/data_io.py:69-73`), which validates
   and raises. Absent file → `OSError`; schema-invalid → `jsonschema`
   `ValidationError`. It does NOT degrade.
2. **`columns_for(doc, sheet_ref)` / `column_width_for(doc, sheet_ref)` never
   raise.** Given `master/<sheet_id>.png` they resolve the entry and return its
   `columns` as a tuple / its `column_width` as an int. Given anything else — an
   `imported/foo.png` ref, `None`, a non-string, a `master/` ref no entry claims,
   an entry that is not a dict, a missing key — they return `()` / `0`.
   Resolution is by matching the ref against each entry's STORED `file` value,
   never by re-deriving `master/<id>.png` from the entry key: that never-re-derive
   rule is `editor/master_sheet_import.py:83-91`'s (`master_ref`) explicit
   contract, and a hand-edited registry can point elsewhere.
3. **`editor/master_sheet_import.load_registry_doc` still degrades to
   `{"version": 1, "entries": {}}`** on a missing or corrupt registry
   (`editor/master_sheet_import.py:94-104`, E-37). It now gets its bytes from the
   engine module instead of its own `data_io.load_json` call. One deliberate
   behaviour delta, called out because it is a real one: a registry that parses
   as JSON but FAILS the schema now reads as *absent* (empty doc) where it used
   to be returned raw. That is the same "corrupt file → empty" branch the
   docstring already promises, and nothing but a hand-edit can produce such a
   file — `write_registry_doc` (`editor/master_sheet_import.py:107-111`) is the
   ONE write path and it validates. `write_registry_doc` is UNTOUCHED.
4. **A `RenderItem`'s column reaches the asset store.**
   `SpriteAnimator.render_items` (`engine/core/sprite_animator.py:31-42`) passes
   its `column` into the emitted `RenderItem`; `Renderer.flush` passes
   `item.column` into `self._assets.frame(...)` at
   `engine/render/renderer.py:203`. The HUD pass
   (`engine/render/renderer.py:241-254`) gets NO column: `HudSprite` gains no
   such field, the same scope line `slice`, `crop_rect` and `hidden_frames`
   already hold (`engine/assets/CLAUDE.md:36-38`).

### Facts already measured — do not re-derive

- `engine/render/item.py:25-35`: `RenderItem` is a FROZEN dataclass whose every
  field after `slot_key`/`world_pos` is defaulted, so appending `column: int = 0`
  is safe for existing positional call sites. **verified**
- `engine/render/renderer.py:203` is the world-sprite
  `self._assets.frame(item.slot_key, item.animation, item.anim_time_ms)` call to
  thread through. **verified**
- `engine/render/renderer.py:243-245` is the HUD `frame(...)` call — leave it
  alone. **verified**
- `engine/assets/master_registry.py` does not exist yet. **verified**
- C2 is concurrently adding `column=None` as the LAST keyword arg of
  `AssetStore.frame()` and `.hit_opaque()`. **Pass it as a KEYWORD —
  `column=item.column` — so your line composes with C2's signature regardless of
  merge order.** This is the interface contract between C2 and C3. **verified**

---

## 2. Architecture plan

### `engine/assets/master_registry.py` (NEW, pure)

The sibling of `engine/assets/registry.py`: **no pygame, no Qt, no game
vocabulary** (`engine/assets/CLAUDE.md:8-11`, the import boundary). Its only
import is `from engine import data_io` (plus `pathlib` if you want it).

Why `engine/` and not a copy per package: `game/` and `editor/` may not import
each other and both need this — the same argument `engine/era_math.py` carries
(`engine/CLAUDE.md:99`).

```
REGISTRY_SUBPATH = ("sprites", "master_sheets.json")
SCHEMA_SUBPATH   = ("schemas", "master_sheets.schema.json")
MASTER_PREFIX    = "master/"

registry_path(data_dir)        -> Path   # no I/O
schema_path(data_dir)          -> Path   # no I/O
load_registry(data_dir)        -> dict   # data_io.load_validated; FAILS LOUD
columns_for(doc, sheet_ref)    -> tuple  # () when unresolvable
column_width_for(doc, sheet_ref) -> int  # 0 when unresolvable
```

- `load_registry(data_dir)` takes a required `data_dir` (a `Path`), exactly like
  `registry.load_registry(data_dir)` — no `None`-means-repo-default here; that
  convenience belongs to the editor module and stays there.
- The two accessors take the already-loaded `doc`, so a caller reads the file
  once. Share ONE private `_entry_for(doc, sheet_ref)` between them; both are
  total functions — wrap the lookup so a non-dict `doc`, a non-dict `entries`, a
  non-str `sheet_ref` and a non-dict entry all fall out as "unresolved".
- `columns_for` returns a `tuple` of the stored names in stored order (D4 — a
  sheet may author its columns in any order); a missing/non-list `columns`
  returns `()`.
- `column_width_for` returns `int(entry["column_width"])` only when it is already
  an `int` (no coercion of strings/bools — the same defensive shape `row_start`
  parsing uses, `engine/assets/CLAUDE.md:119-127`); anything else → `0`.

### `editor/master_sheet_import.py` (delegation only)

`load_registry_doc` keeps its signature, its docstring intent and its E-37
wrapper; only the read line moves:

```python
from engine.assets import master_registry
...
def load_registry_doc(data_dir=None):
    try:
        doc = master_registry.load_registry(_data_dir(data_dir))
    except (OSError, ValueError, ValidationError):
        return {"version": 1, "entries": {}}
    ...keep the existing isinstance shape guard and the return...
```

`jsonschema.exceptions.ValidationError` does NOT subclass `ValueError`, so it
must be named explicitly (`from jsonschema import ValidationError` — `jsonschema`
is already a hard dependency via `engine/data_io.py`; it is neither Qt nor
pygame, so the module stays inside its documented purity envelope,
`editor/master_sheet_import.py:8-9`). Keep the existing isinstance guard on
`doc`/`doc["entries"]`: validation makes it redundant, but it is the empty-doc
contract in code and costs nothing.

`registry_path`/`schema_path`/`frame_bounds`/`write_registry_doc` in the editor
module are UNCHANGED — do not re-point them at the engine constants in this
phase. `write_registry_doc` remains the ONE write path (ED-31).

### Render threading

- `engine/render/item.py`: `RenderItem` gains `column: int = 0`, **appended LAST**
  after `scale`. One short comment: the master-sheet column block this item wants;
  `0` = the entry's own stored column.
- `engine/core/sprite_animator.py`: `SpriteAnimator` gains `column: int = 0` — a
  declared, JSON-safe `Component` field, so it serializes for free — and passes
  `column=self.column` in `render_items`.
- `engine/render/renderer.py:203` becomes
  `frame = self._assets.frame(item.slot_key, item.animation, item.anim_time_ms, column=item.column)`.
  Keyword, per the C2 contract. Nothing else in `flush` changes; the HUD call at
  `:243-245` is untouched.

### Docs

- `engine/CLAUDE.md:30` — the `assets/` row of the subsystem table. Extend its
  *Owns* cell to name the master-sheet registry loader. One line, nothing else in
  that file.
- `engine/assets/CLAUDE.md` — EXACTLY TWO edits. See §3; that file is shared with
  C2 and the boundaries are a contract.

### Not in this phase

`TestPurity`'s import list gets nothing new — that rule applies only to new
**editor** modules, and `master_registry.py` is engine. `HudSprite` gains no
`column`. `engine/assets/store.py` is C2's file: do not open it.

---

## 3. File scope + shared-file contract

### Files you may create

| File | Why |
|---|---|
| `engine/assets/master_registry.py` | the new pure loader |
| `tools/tests/test_master_registry.py` | its tests |

### Files you may modify

| File | Edit |
|---|---|
| `engine/render/item.py` | `RenderItem.column: int = 0`, appended last |
| `engine/core/sprite_animator.py` | `column: int = 0` field + pass it in `render_items` |
| `engine/render/renderer.py` | line 203 only: `column=item.column` |
| `editor/master_sheet_import.py` | `load_registry_doc` delegates; nothing else |
| `engine/CLAUDE.md` | line 30 table row only |
| `engine/assets/CLAUDE.md` | the two blocks below — nothing else |
| `conftest.py` | one `TIERS` entry |
| `tools/tests/test_render.py` | fake-store signatures + the column-through test |
| `tools/tests/test_master_sheet_import.py` | the degrade test (+ the C1 stopgap, below, if it triggers) |

### `engine/assets/CLAUDE.md` — SHARED WITH C2, RUNNING CONCURRENTLY

C2 and C3 both edit this file, in separate worktrees. It is split into disjoint
insertion blocks. Editing outside yours produces a merge conflict in a doc, which
is the cheapest possible bug and still a waste — stay inside.

**C2 owns** (do NOT touch): a new bullet documenting the optional `column` /
`column_mode` / `column_width` manifest keys, inserted as the sibling
immediately AFTER the existing bullet beginning

> ``- **Optional `row_start` (M2, GpuAndMasterSheetsPLAN)**:``

and its two sub-bullets (currently lines 119-135), inside the "Phase 5
conventions" list.

**C3 (you) own EXACTLY TWO things:**

**(a)** Inside the `- **Store**:` bullet (currently starting line 136), the ONE
sentence that begins

> ``` `_frames`/`_hit_masks` stay SLOT-keyed on purpose (**D10**): ``` …

— today it says a shared sheet's slots resolve different pixels for the same
`(row, col)` "because each applies its own `row_start` **and** may declare its
own `frame_w`/`frame_h`", and that "deduping frames too would mean folding the
grid and the window into the key, which is a noted follow-up and deliberately
not done". Update that sentence so it says the cache key now also carries the
**resolved column block** (a live column can make ONE slot resolve different
pixels for the same `(row, col)`, which is why the block joins the key). Do not
rewrite the `_sheets`-is-path-keyed half of the bullet, and do not touch the
`Sliced frames are SUBSURFACES` sentence.

`engine/assets/store.py` is **C2's file, not yours** — you document what C2 is
landing; C2 lands the code. Do not open, edit or test it.

Deliberately out of your two: the `(slot_key, row, col)` key mentioned inside the
separate `- **Pixel hit-mask (A8, R2 design)**` bullet (currently line 179) —
leave it exactly as it is and report it as stale-after-C2 (see §"Report").

**(b)** A new SHORT paragraph (one bullet, 3-5 lines) documenting
`engine/assets/master_registry.py`, **APPENDED AT THE END of the "Phase 5
conventions" list** — i.e. inserted immediately AFTER the bullet beginning

> ``- **E-38 is RETIRED — the migration tool is deleted.**``

(which currently ends at line 197) and immediately BEFORE the `## Verify`
heading. Say: the pure reader of `data/sprites/master_sheets.json`, sibling of
`registry.py`, fail-loud via `data_io.load_validated`; `columns_for` /
`column_width_for` resolve a `master/<id>.png` ref to `()` / `0` rather than
raising; it lives in `engine/` because `game/` and `editor/` both need it and may
not import each other; the editor's `load_registry_doc` delegates to it and keeps
its own E-37 empty-doc wrapper.

Your two blocks sit ~60 lines apart from C2's. Git merges them cleanly as long as
neither side reflows the other's text.

### `conftest.py`

Add ONE line to `TIERS`, in the `core` block, alphabetically between
`"test_map_overlays"` (line 125) and `"test_master_sheet_import"` (line 128):

```python
    "test_master_registry": "core",   # MasterSheetColumnsPLAN C3
```

The `core` CI shard selects by `-m core` (`tools/ci_shards.py:78`), so no shard
table needs editing. **verified**

### Scope addenda — three mechanical consequences, flagged upward

These are outside the phase's nominal file list. Each is forced by this phase's
own change, each is one line, and each leaves a RED test module that your gate
cannot see if you skip it. Apply them and name them in your report.

1. **`tools/test_domains.py`** — a new test module with no domain entry makes
   `tools/tests/test_test_domains.py:26-40` (meta tier) fail hard. Add
   `"test_master_registry.py",` to the `"data"` tuple (line 191-198), after
   `"test_balancing_data.py"` — that is where its sibling
   `test_assets_registry.py` already lives (`tools/test_domains.py:192`).
   **verified**
2. **`tools/tests/test_components.py:23`** — its `FakeAssets.frame(self,
   slot_key, animation="idle", anim_time_ms=0, extra_hidden=None)` receives a
   WORLD item through `renderer.submit(item)` at line 87, so your new
   `column=item.column` keyword raises `TypeError` there. Add `, column=0` to
   that one signature. Nothing else in the file. **verified**
3. **`tools/tests/test_hud_items.py:33` and `:45`** — same collision; line 98
   submits a world `RenderItem` through those fakes. Add `, column=0` to both
   `frame` signatures (`FakeAssets` and `RecordingAssets`). `RecordingAssets`
   forwards to `super().frame(...)` — leave the forwarding as is. Nothing else.
   **verified**

`tools/tests/test_shell.py:23` has the same fake shape but appears to submit only
HUD primitives (**inferred**, not measured). Do NOT edit it pre-emptively; if it
turns red, report it rather than widening further.

### The C1 stopgap — conditional, trigger is observable

`editor/master_sheet_import.import_master_sheet` writes an entry with exactly
four keys (`editor/master_sheet_import.py:276-281`) and the entry schema is
`additionalProperties: false` with a `required` list
(`data/schemas/master_sheets.schema.json:39-45`). Once C1 makes `column_width`
required, that write fails validation — breaking master-sheet import and
`tools/tests/test_master_sheet_import.py:59-70`, which asserts the entry equals
exactly those four keys. C1's file list names no editor file (**verified**, plan
lines 194-197), and the import form's `column_width` field belongs to Section S2.

**Run your gate FIRST.** If `test_master_sheet_import.py` passes, do nothing —
someone else handled it.

If it fails with a `ValidationError` naming `column_width` out of
`write_registry_doc`, apply this stopgap and say so loudly in your report:

- In `import_master_sheet`, record `"column_width": <the sheet's full width in
  frames>` on the entry it writes — read the PNG size with `Image.open`
  (Pillow is already imported at `editor/master_sheet_import.py:36`; `open` is
  lazy, header-only, exactly as `master_sheets()` uses it at line 340) and use
  `max(1, width // frame_w)`. **One column spanning the whole sheet** is the
  behaviour-preserving value: it makes every existing sheet a 1-column sheet, so
  D7's per-sheet clamp holds every slot at column 0 and no art moves. `1` would
  claim a 6-frame-wide sheet has six colour columns and send a season-driven slot
  into garbage — do not use it.
- Update the four-key assertion at `tools/tests/test_master_sheet_import.py:67-70`
  to expect the fifth key.
- Add a one-line comment saying S2's import form supersedes this default.

---

## 4. Exit gate + Quick Test

### Tests to write — MINIMUM, not maximum

The plan's list is a CEILING, not a floor. Write the bare minimum that pins the
behaviour; invent nothing beyond this list. Terse asserts, no parametrised
matrices, no coverage sweeps.

`tools/tests/test_master_registry.py` (new, `core` tier — pure, no pygame, no Qt;
use `tools/tests/temp_data.py`'s `DataDirCase`/`TempDataCase` for a writable data
dir, the pattern `tools/tests/test_master_sheet_import.py:47-57` follows, and
**pin your own registry fixture** — never assert against live `data/`):

1. `load_registry` round-trips a fixture registry it wrote itself (entries with
   `column_width` and `columns` present).
2. `load_registry` raises on an invalid registry (e.g. `column_width` missing or
   out of range) and on an absent file — fail loud, not empty.
3. `columns_for` / `column_width_for` return the stored values for a known
   `master/<id>.png` ref.
4. `columns_for` / `column_width_for` return `()` / `0` for an `imported/x.png`
   ref and for an unknown `master/` ref.

`tools/tests/test_render.py`:

5. A `RenderItem` with a non-zero `column` reaches `assets.frame` with it — spy
   with a recording fake in the shape of `RecordingAssetsWithHidden`
   (`tools/tests/test_render.py:548-557`). Add `column=0` to the `frame`
   signatures of `FakeAssets` (line 46) and `RecordingAssetsWithHidden`
   (line 555) so the existing tests keep passing.
6. `column=0` (the default) produces a `DrawCall` identical to the pre-change one
   — assert the drawn `DrawCall` for a plain `RenderItem` still has the same
   surface/dest/size/tint/flip.

`tools/tests/test_master_sheet_import.py`:

7. `load_registry_doc` still returns `{"version": 1, "entries": {}}` for a
   missing file and for a corrupt one (write garbage bytes at
   `registry_path(self.data_dir)`).

### Exit gate — run this, nothing wider

```
py -m pytest tools/tests/test_master_registry.py tools/tests/test_render.py tools/tests/test_master_sheet_import.py -x -q
py tools/smoke.py
```

If you applied the §3 scope addenda, add `tools/tests/test_components.py` and
`tools/tests/test_hud_items.py` to that SAME single pytest invocation — they are
files you edited, which is exactly what the policy allows. Do not run anything
else.

The gate is ZERO: `GATE PASS` / all green, or you are not done.

### Test budget — binding

> Your gate is `py tools/smoke.py` plus `py -m pytest <the specific test files you edited> -x -q`. Nothing wider. You may NOT run the full suite, a tier sweep (`-m core` / `-m editor` / `-m meta`), `py tools/testgate.py check`, or `--affected` — a `PreToolUse` hook denies all four for subagents.
>
> If `test_guard` denies a test command, do NOT re-issue it, do not vary the flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command fingerprints identically), and do not reach for the guard's escape hatch. Report the deny text and the result it quotes back to your orchestrator and stop testing. Retrying is the loop the guard exists to stop.
>
> Two denies are expected and must not be fought: *"already ran this exact target and NOTHING has changed"* (the guard fingerprints the MAIN checkout's diff; worktrees are gitignored, so your own edits can be invisible to it — accept the quoted earlier result, and if it was a FAIL you believe you have since fixed, say exactly that in your report) and *"another test run is already in flight"* (do not wait-loop, do not delete the lock — report and stop).

### Quick Test (in-game — the ORCHESTRATOR or the user runs this, not you)

1. `py editor/main.py` → open the master-sheet picker (Master Sheets / the
   master-sheet dialog). The committed sheet still appears with its name and
   grid. *This is the delegation check: if `load_registry_doc` degraded wrongly,
   the picker is empty.*
2. `py game/main.py` → start a run, place a building, let a wave spawn. Every
   sprite draws exactly as before — buildings, enemies, tiles, HUD. C3 is
   invisible by design; any visual change is a bug.

### Report

Tag every claim **measured** / **verified** / **inferred**. Name explicitly:
whether the C1 stopgap triggered; which scope addenda you applied; and that the
`(slot_key, row, col)` key sentence in `engine/assets/CLAUDE.md`'s Pixel-hit-mask
bullet (line 179) is left stale on purpose for C2 to reconcile.
