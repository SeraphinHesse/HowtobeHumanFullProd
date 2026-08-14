# Phase M1 — Master-sheet data layer (`planning/GpuAndMasterSheetsPLAN.md` §7/M1)

**Package: `data` only.** The storage concept exists and validates. **No engine
code (that is M2), no editor code (M3/M4/M5).** Nothing in this phase reads
`row_start` or the registry at runtime — M1 ships a schema, a seeded empty
registry, a committed folder, and the tests that pin them.

---

## 1. Behavioral spec (what exists today, with citations)

All line numbers verified by reading the files at branch `phase-G1-umbrella`.

### 1.1 The manifest `sheet` field is a real path, and its pattern is `imported/`-only

`data/schemas/asset_manifest.schema.json:199-203` — the per-entry `sheet`
property:

```json
"sheet": {
  "description": "Sheet path relative to data/sprites, resolved as a real path (D-31) — NOT derived from the slot key. Normally imported/<slot>.png, …",
  "pattern": "^imported/[a-z][a-z0-9_]*\\.png$",
  "type": "string"
}
```

The pattern literal is at **`asset_manifest.schema.json:201`**. This one line is
what currently makes `master/<id>.png` unrepresentable. `data/CLAUDE.md`'s
"A sheet may be SHARED — `sheet` is a path, not a slot-derived name" bullet
already states that one PNG may back many slots; only the *folder* is
constrained.

### 1.2 The existing optional per-entry keys, and how "optional" is spelled

The entry object's `required` array is at
**`asset_manifest.schema.json:220-227`** and lists exactly six keys —
`sheet`, `frame_w`, `frame_h`, `offset_x`, `offset_y`, `rows`. Everything not in
that array is optional by omission from `required` (never by a `oneOf`, never by
a nullable type):

| Optional key | Declared at | Shape |
|---|---|---|
| `anchors` | `asset_manifest.schema.json:79-150` | object, six optional `[x, y]` int pairs, `additionalProperties: false` |
| `slice` | `asset_manifest.schema.json:204-214` | 4-item int array, `minimum: 0`, `maximum: 1024` |
| `tint_overlay` | `asset_manifest.schema.json:215-218` | bool; omitted ⇒ `False` ⇒ byte-identical entry |

`row_start` is the **fourth** optional key and must follow this exact
convention: present in `properties`, absent from `required`, `description`
stating that omitted ⇒ 0.

### 1.3 Existing frame-count bounds (what `row_start`'s `maximum` must match)

- `$defs.row.frames`: `minimum: 1`, `maximum: 256` —
  `asset_manifest.schema.json:18-23`.
- `$defs.row.hidden` items (0-based frame **columns**): `minimum: 0`,
  `maximum: 255` — `asset_manifest.schema.json:24-33`.
- `loop_start` / `loop_end` (0-based columns): `maximum: 255` —
  `asset_manifest.schema.json:40-51`.

`row_start` is a **0-based row index**, so its ceiling is the 0-based twin of
the 256-count bound: `minimum: 0`, `maximum: 255`. State that reasoning in the
`description`.

### 1.4 Smoke schema pairing — FINDING: no fourth directory exception is needed

`tools/smoke.py::validate_data` is at **`tools/smoke.py:25-68`**. It walks
`sorted(data_root.rglob("*.json"))` (`:49`), skips anything under
`data/schemas/` (`:50-51`), then applies four directory exceptions
(`:52-59`: `maps/`, `balancing_history/`, `agent_forms/`, `ui/screens/`) and
otherwise falls through to plain stem pairing:

```python
else:
    schema = schema_dir / f"{path.stem}.schema.json"   # tools/smoke.py:60-61
```

`data/sprites/` is **not** special-cased anywhere — `data/sprites/asset_manifest
.json` already pairs by stem through that `else`. Therefore
`data/sprites/master_sheets.json` pairs to
`data/schemas/master_sheets.schema.json` by the same branch, with **zero change
to `tools/smoke.py`**. (**verified** by reading `:49-66`.) The PNGs under
`data/sprites/master/` are invisible to this walk — `rglob("*.json")` only.

**`tools/smoke.py` is therefore OUT of scope for this phase.** If, while
implementing, you find any reason the pairing does not resolve, that is a
**finding to report to the orchestrator**, not a silent `if/elif` edit: adding a
fifth exception means editing the chain, its docstring (`:26-39`) and pinning it
in `tools/tests/test_smoke_pairing.py`, which is a different phase's scope.

### 1.5 Test-harness facts that constrain how M1's tests may be written

- **`TempDataCase` already copies the WHOLE live `data/` tree.**
  `tools/tests/temp_data.py:85` (`shutil.copytree(LIVE_DATA, dest)` into the
  session template) and `:101` (the `FULL_ASSETS` path) copy everything;
  `_prune` (`:61-71`) only truncates the media suffixes in
  `STUB_SUFFIXES = {".wav", ".mp3", ".ogg", ".mp4"}` (`:51`). PNG is
  deliberately not stubbed (`:22-24`). **So `data/sprites/master/` and
  `data/sprites/master_sheets.json` are copied automatically and the helper
  needs NO extension — this is the one thing §8 of the plan told M1 to check,
  and the answer is "already covered".** (**verified**.) Do not add a
  master-sheet special case to `temp_data.py`.
- **`tools/tests/test_fixture_guard.py:116-158`** pins that the pruned template
  has *exactly* live `data/`'s file set. A new tracked file under
  `data/sprites/master/` is copied by `copytree` like any other, so this test
  stays green — but it is the test that fails loudly if the folder is ever
  gitignored or otherwise made invisible.
- **`test_assets_manifest.py` is NOT on the live-data allowlist**
  (`test_fixture_guard.py:22-71`), and `test_live_data_reads_are_allowlisted`
  (`:91-107`) hard-fails any scanned test file matching
  `REPO / "data"` / `parents[2] / "data"` / `LIVE_DATA` (`:74-79`). See §3.3 —
  this decides where the new tests load their schemas from.
- The committed fixture snapshot is JSON-only and lives at
  `tools/tests/fixtures/data/` (`tools/tests/fixture_data.py:29`), refreshed
  only by the explicit `py tools/tests/fixture_data.py --refresh`
  (`fixture_data.py:56-73`). It contains its own stale copy of
  `fixtures/data/schemas/asset_manifest.schema.json`.
- `tools/tests/test_assets_manifest.py` today is a pure-core module (no
  pygame, no Qt, no `data/` reads): row/entry builders at `:23-44`, seven test
  classes at `:47`, `:84`, `:103`, `:198`, `:249`, `:297`, `:312`.

### 1.6 Committed-folder precedent

`data/sprites/imported/.gitkeep` is a tracked file in this repo (**measured**:
`git ls-files | grep gitkeep` lists it alongside `data/maps/.gitkeep`). Git
cannot track an empty directory, so `data/sprites/master/` gets the identical
treatment: a tracked, empty `data/sprites/master/.gitkeep`. `.gitignore`
contains no `data/` rule at all (**measured**), so nothing needs un-ignoring —
and nothing may be added to ignore this folder (D-31: these PNGs are content).

---

## 2. Architecture plan

### 2.1 New — `data/schemas/master_sheets.schema.json`

House style, no exceptions (`data/CLAUDE.md` "Rules" + D-12/ED-30): draft
2020-12, `$id`, `title`, `additionalProperties: false` at **every** object
level, every key in `required`, every property carrying a `description` that
documents units, every numeric carrying `minimum` **and** `maximum` so the
editor derives spinbox ranges and out-of-range input is unrepresentable.
`data/schemas/font_manifest.schema.json:1-47` is the closest existing twin
(same `{version, entries:{<id>: {file, display_name}}}` shape) — copy its
structure, not its wording.

Proposed content (author it through `engine.data_io.dumps_deterministic`, never
hand-formatted — sorted keys, 2-space indent, D-3):

```json
{
  "$id": "master_sheets.schema.json",
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "additionalProperties": false,
  "description": "data/sprites/master_sheets.json (GpuAndMasterSheetsPLAN D1): the registry of MASTER spritesheets - one committed PNG under data/sprites/master/ holding many characters' rows stacked in one grid, keyed by a generated sheet id. A master sheet is a FILE with metadata, not a data/slots.json category: it is never previewed, animated or rendered on its own, so it carries no animation vocabulary and no slot key. A manifest entry links to one by setting its 'sheet' to master/<sheet_id>.png and its 'row_start' to the first row of its window (asset_manifest.schema.json). The registry OWNS the frame grid (D3): a linking slot inherits frame_w/frame_h from here and may not override them, so every slot cutting one master sheet agrees on what row N means. Written ONLY by the editor's master-sheet import, through the validating writer.",
  "properties": {
    "entries": {
      "additionalProperties": false,
      "description": "One entry per imported master spritesheet, keyed by sheet id.",
      "patternProperties": {
        "^[a-z][a-z0-9_]*$": {
          "additionalProperties": false,
          "description": "One master spritesheet: where its PNG lives, its designer-facing name, and the frame grid it is cut at.",
          "properties": {
            "display_name": {
              "description": "Human-readable name shown in the editor's master-sheet picker.",
              "maxLength": 80,
              "minLength": 1,
              "type": "string"
            },
            "file": {
              "description": "PNG path relative to data/sprites, resolved as a real path (D-31) - always master/<sheet_id>.png. Committed content like sprites/imported/*.png, never a build artifact.",
              "pattern": "^master/[a-z][a-z0-9_]*\\.png$",
              "type": "string"
            },
            "frame_h": {
              "description": "Frame height in pixels this master sheet's grid is cut at; every linking slot inherits it (D3).",
              "maximum": 1024,
              "minimum": 1,
              "type": "integer"
            },
            "frame_w": {
              "description": "Frame width in pixels this master sheet's grid is cut at; every linking slot inherits it (D3).",
              "maximum": 1024,
              "minimum": 1,
              "type": "integer"
            }
          },
          "required": [
            "file",
            "display_name",
            "frame_w",
            "frame_h"
          ],
          "type": "object"
        }
      },
      "type": "object"
    },
    "version": {
      "const": 1,
      "description": "Master-sheet registry format version; this schema is v1."
    }
  },
  "required": [
    "version",
    "entries"
  ],
  "title": "master_sheets",
  "type": "object"
}
```

Notes the implementer must respect:
- `frame_w`/`frame_h` bounds are **1..1024**, matching
  `asset_manifest.schema.json:151-162` exactly — the two grids describe the same
  pixels and must not disagree.
- The id pattern `^[a-z][a-z0-9_]*$` is the slot-key convention, identical to
  the manifest's `patternProperties` key (`asset_manifest.schema.json:74`) and
  `font_manifest.schema.json:11`.
- The `file` pattern deliberately does **not** cross-check that the id in the
  path equals the key — JSON Schema cannot express it. If a later phase wants
  that pin it belongs in a loader cross-check (the `engine.tilemap` precedent
  named in `data/CLAUDE.md`), not here.

### 2.2 New — `data/sprites/master_sheets.json`

Seeded exactly:

```json
{
  "entries": {},
  "version": 1
}
```

Keys sorted (D-3), 2-space indent, trailing newline — i.e. write it with
`engine.data_io.write_validated(doc, path, schema)` (or `dumps_deterministic`)
rather than by hand, and confirm it is byte-identical to
`dumps_deterministic(json.loads(text))`.

### 2.3 New — `data/sprites/master/.gitkeep`

Empty tracked file, mirroring `data/sprites/imported/.gitkeep` (§1.6). It exists
solely so git tracks the folder before any PNG lands. **Never add
`data/sprites/master/` to `.gitignore`** — these are D-31 committed content, the
same status as `sprites/imported/*.png`. `.gitkeep` is inert for every consumer:
`smoke.validate_data` globs `*.json`, and `fixture_data.refresh` mirrors `*.json`
only, so it cannot leak into the JSON-only fixture snapshot
(`test_fixture_guard.py:160-167`).

### 2.4 Modified — `data/schemas/asset_manifest.schema.json` (two changes, no others)

**Change 1 — widen the `sheet` pattern.** Replace the pattern at `:201` with a
single two-branch alternation and update the `description`. **Not `oneOf`** (the
editor's form walker handles it badly), not an `enum`, not `anyOf`:

```json
"sheet": {
  "description": "Sheet path relative to data/sprites, resolved as a real path (D-31) — NOT derived from the slot key. Normally imported/<slot>.png, the file this slot's own import owns; but a slot may LINK to another slot's sheet (the editor's 'Use Spritesheet...'), so one PNG can back many slots. It may equally live in master/<sheet_id>.png — a MASTER spritesheet registered in sprites/master_sheets.json, shared by many slots, each claiming its own row window via row_start. Anything deleting art must refcount this field first.",
  "pattern": "^(imported|master)/[a-z][a-z0-9_]*\\.png$",
  "type": "string"
}
```

The exact proposed pattern string, as it appears in the JSON file:
`"^(imported|master)/[a-z][a-z0-9_]*\\.png$"` (regex:
`^(imported|master)/[a-z][a-z0-9_]*\.png$`). Every existing entry still matches
byte-for-byte; the change is purely permissive.

**Change 2 — add the optional `row_start` property.** Insert alphabetically
between `rows` (`:175-198`) and `sheet` (`:199-203`) — sorted keys are the D-3
house format, so alphabetical placement is not cosmetic. Do **not** add it to
`required` (`:220-227`):

```json
"row_start": {
  "description": "Optional row window origin: the 0-based SHEET row that this entry's rows[0] (idle) cuts from; entry row i cuts sheet row row_start + i. Exists so many characters stacked in one master spritesheet can each claim their own contiguous rows. Omit for a sheet this entry starts at the top of — omitted ⇒ 0 ⇒ the entry is byte-identical to a pre-window entry, the same convention slice and tint_overlay follow. The window END is NOT stored: it is len(rows), so there is one source of truth. 0-based like hidden/loop_start, hence a ceiling of 255 against rows' 256-count bound.",
  "maximum": 255,
  "minimum": 0,
  "type": "integer"
}
```

### 2.5 Modified — `data/CLAUDE.md`

Extend the **Asset data** section (the `sprites/asset_manifest.json` bullet
block and the "A sheet may be SHARED" bullet), in that doc's existing voice:

- A new bullet for `sprites/master_sheets.json` ↔
  `schemas/master_sheets.schema.json`, stating: **normal stem pairing, no fifth
  smoke directory exception** (with the `tools/smoke.py:60-61` reasoning); the
  registry shape; D1 (why this is a registry file and *not* a `slots.json`
  category — no animation vocabulary, no selector node, no cross-category
  `sprite_slot` enum entry); D3 (the registry OWNS the grid, a linking slot
  inherits `frame_w`/`frame_h`).
- A new bullet: `sprites/master/*.png` are committed content (D-31), exactly
  like `sprites/imported/*.png`; the folder is tracked via `.gitkeep`; never
  gitignore it.
- Amend the optional-keys sentence so the manifest's optional set reads
  `slice` / `anchors` / `tint_overlay` / **`row_start`** — note that the doc
  currently says this twice, in two adjacent bullets that disagree about which
  two keys are "the" optional pair; fix both occurrences to the same list of
  four rather than adding a third variant.
- Amend the `sheet`-is-a-path bullet: the pattern now admits both folders, and
  record the one-way-door caveat from the plan's §9 (a `master/` path will not
  validate against an older checkout's schema).
- Note explicitly that `row_start` is a **slicing** concern only — nothing in
  M1 reads it; M2 applies it in exactly one place.

### 2.6 Modified — `tools/tests/test_assets_manifest.py`

Add ONE new class (bare-minimum coverage, no exhaustive matrix) covering the six
cases the plan names — see §4.2. Keep the existing pure-core classes untouched.

---

## 3. File scope + shared-file contract

### 3.1 In scope (this phase writes exactly these)

| File | New/Modified | Note |
|---|---|---|
| `data/schemas/master_sheets.schema.json` | new | §2.1 verbatim |
| `data/sprites/master_sheets.json` | new | §2.2, deterministic bytes |
| `data/sprites/master/.gitkeep` | new | empty; `git add` it explicitly |
| `data/schemas/asset_manifest.schema.json` | modified | **exactly two edits**: the pattern+description at `:199-203`, and the new `row_start` property between `:198` and `:199`. Nothing else in this 244-line file moves. |
| `data/CLAUDE.md` | modified | §2.5 |
| `tools/tests/test_assets_manifest.py` | modified | one new class appended; existing classes untouched |

### 3.2 Explicitly OUT of scope

- **`engine/**` — that is M2.** `engine/assets/manifest.py` does not learn
  `row_start`, `engine/assets/store.py` does not re-key `_sheets`, in this
  phase. A schema that permits a key the parser ignores is the intended M1 end
  state.
- **`editor/**` — that is M3/M4/M5.** No import module, no dialog, no
  DetailsPanel row.
- **`tools/smoke.py`** — §1.4: pairing already resolves. If you believe it does
  not, **stop and report**; do not edit the `if/elif` chain.
- **`tools/tests/temp_data.py`** — §1.5: `copytree` already covers the new
  files. Do not add a master-sheet branch.
- **`data/slots.json`** — D1: a master sheet is deliberately not a slot
  category.
- **Existing manifest CONTENT** (`data/sprites/asset_manifest.json`): not one
  byte changes. No entry gains `row_start`, no entry's `sheet` is repointed.
  This is the compatibility claim the whole design rests on — verify it with
  `git diff --stat data/sprites/asset_manifest.json` showing nothing.

### 3.3 Shared-file contract — the two collisions you must not walk into

**(a) Concurrent agents.** Another planner/coder pair is on
`docs/briefs/phase-G1-backend-seam.md` and `engine/render/**`; the main session
is in `game/main.py` and `tools/`. Neither overlaps §3.1. If you find yourself
about to edit `game/main.py`, `tools/smoke.py`, `tools/testgate.py` or anything
under `engine/render/`, you are out of scope — stop and report.

**(b) The fixture-pinning guard — this is the one real decision M1 must make.**
`tools/tests/test_assets_manifest.py` is **not** in
`test_fixture_guard.py`'s `ALLOWED` map (`:22-71`), and
`test_live_data_reads_are_allowlisted` (`:91-107`) fails on any of
`REPO / "data"`, `parents[2] / "data"`, or `LIVE_DATA` appearing in that file
(`:74-79`). The new schema-validation tests therefore may **not** spell a live
`data/` path.

**Recommended route (Option A — no allowlist edit):** load the schemas from the
pinned snapshot, i.e. `from tools.tests.fixture_data import FIXTURE_DATA` (or
`fixture_copy(tmpdir)` if the test writes), then
`FIXTURE_DATA / "schemas" / "master_sheets.schema.json"`. That requires the
snapshot to carry the new/updated schemas, so this phase also runs:

```bash
py tools/tests/fixture_data.py --refresh
```

which mirrors live JSON into `tools/tests/fixtures/data/` and prints every file
it changed (`fixture_data.py:56-73`). **Expect it to report exactly the two
schema files plus the new `sprites/master_sheets.json`.** If it reports anything
else — unrelated designer drift on this branch — **stop and report the list to
the orchestrator before committing it**; a refresh that sweeps in an unrelated
content change is how a pin stops being a pin. The generated diff under
`tools/tests/fixtures/data/**` is an accepted extension of §3.1's scope, and only
for the paths the refresh prints.

**Alternative (Option B — only if the orchestrator prefers it):** add
`"test_assets_manifest.py"` to `ALLOWED` in `test_fixture_guard.py` with a
one-line justification and read the live schema, following the exact
`test_asset_anchors.py` precedent already in that map (`:24-26`: "validates the
live asset_manifest schema this same phase adds the `anchors` block to"). This
edits a file outside §3.1. **Do not take Option B silently** — pick A, or ask.

**Open question for the orchestrator/human:** A vs B. A keeps the guard's
doctrine ("pin the fixture") and costs a mechanical refresh; B matches the
closest precedent for a schema-changing phase and costs one allowlist line.
Neither is chosen for you here.

---

## 4. Exit gate + Quick Test

### 4.1 Commands the coder runs — and NOTHING wider

Verbatim test budget, inherited from `planning/GpuAndMasterSheetsPLAN.md` §8:

> The coder's gate is `py tools/smoke.py` + `py -m pytest
> tools/tests/test_assets_manifest.py -q` — nothing wider. NOT the full suite,
> NOT a tier sweep, NOT `--affected` (the `test_guard.py` hook denies all three
> for subagents).

And verbatim:

> If `test_guard` denies a test command, do NOT re-issue it, do not vary the
> flags (the guard normalises `-q/-v/-x/-n/--tb`, so a reworded command
> fingerprints identically), and do not reach for the guard's escape hatch.
> Report the deny text and the result it quotes back to the orchestrator and
> stop testing. Retrying is the loop the guard exists to stop.

```bash
py tools/smoke.py
py -m pytest tools/tests/test_assets_manifest.py -x -q
```

`py tools/smoke.py` must print a data-file count **one higher than before**
(`tools/smoke.py:67` prints `smoke: N data file(s) schema-valid`) — that single
number is the evidence `master_sheets.json` paired to its schema through the
plain stem branch with no code change. Record the before/after numbers in the
phase report as a **measured** claim.

Not this phase's gate, but flag it in the report if the orchestrator's later
full run trips it: `tools/tests/test_smoke_pairing.py:94-96`
(`test_repo_data_still_validates`) validates the live tree and will now include
the new file.

### 4.2 Tests required (bare minimum — six cases, one class)

In `tools/tests/test_assets_manifest.py`, schemas loaded per §3.3:

**Registry (`master_sheets.schema.json`):**
1. The seeded document `{"version": 1, "entries": {}}` validates.
2. A registry whose entry has a **bad `file` path** (e.g.
   `"imported/x.png"`, or `"master/X.png"`) is rejected.
3. A registry with a **bad sheet id** key (e.g. `"1bad"` or `"Bad-Id"`) is
   rejected.
4. A registry entry **missing `frame_w`** is rejected.

**Manifest (`asset_manifest.schema.json`):**
5. An existing-shaped entry with **no `row_start`** still validates, and an
   entry with `sheet: "master/x.png"` validates. (Reuse the module's existing
   `entry_dict()` / `row()` builders at `test_assets_manifest.py:23-44` — pass
   `sheet="master/x.png"`; note `entry_dict` already takes a `sheet` kwarg.)
6. An entry with a **negative `row_start`** (`-1`) is rejected.

Assertion style: `jsonschema.ValidationError` via `assertRaises`, or
`engine.data_io.load_validated` on a tempfile — the module already imports only
pure-core helpers, so keep it pygame-free and Qt-free.

**Two hard constraints on these tests:**
- **Tests must never write into `data/`.** Use a tempdir /
  `fixture_copy(tmpdir)` / `TempDataCase` for anything that writes. A session
  fixture hashes `data/` before and after the suite and fails the run if one
  byte changed.
- **Never assert against live `data/` content.** The committed fixture manifest
  `tools/tests/fixtures/data/sprites/asset_manifest.json` holds **278 entries**
  and keeps growing (it grew again in the tile-condition rework) — assert only
  on entries the test itself writes, never on a count, never on "this slot has
  no art".

### 4.3 Exit gate (all must hold)

1. `py tools/smoke.py` → green, count +1 vs the pre-change run.
2. `py -m pytest tools/tests/test_assets_manifest.py -x -q` → green, six new
   cases.
3. `git diff --stat data/sprites/asset_manifest.json` → **empty**. Every
   existing entry is byte-identical; `row_start` appears nowhere in committed
   content.
4. `data/sprites/master/.gitkeep` and `data/sprites/master_sheets.json` are
   **tracked** (`git status` shows them staged/committed, not untracked, not
   ignored).
5. Both new/edited JSON files are canonical on disk: text ==
   `data_io.dumps_deterministic(json.loads(text))` (D-3).
6. `data/CLAUDE.md` updated per §2.5 (architectural change → **package** doc,
   never the root router).
7. No file outside §3.1 (+ the §3.3 refresh output, if Option A) is modified.

### 4.4 Quick Test (concrete, in-repo — there is no in-game surface yet)

M1 ships no runtime behaviour, so the honest Quick Test is a data-layer one; say
so on the PR rather than inventing a gameplay scenario.

1. `py tools/smoke.py` — note the printed file count; it is one higher than on
   `Development`.
2. Drop any PNG at `data/sprites/master/characters.png`, then hand-add to
   `data/sprites/master_sheets.json`:
   `{"characters": {"file": "master/characters.png", "display_name":
   "Characters", "frame_w": 64, "frame_h": 96}}` and re-run
   `py tools/smoke.py` → still green. **Revert both** afterwards (`git status`
   clean) — this is a validation probe, not seed content.
3. Repeat with a deliberately broken entry (`"file": "imported/characters.png"`,
   or key `"Characters"`) → `py tools/smoke.py` fails loud naming
   `sprites/master_sheets.json`. Revert.
4. `py editor/main.py` boots and the asset panel behaves exactly as before —
   **nothing in the editor should look different**; M1 is invisible by design.
   A visible change means something out of scope was touched.

---

## Report expectations for the executing coder

State, tagged **measured** / **verified** / **inferred**:
- the smoke file count before and after (measured);
- that `tools/smoke.py` needed no edit (verified) — or, if it did, the exact
  reason, as a finding, with the chain left unedited;
- which of §3.3's Option A / Option B was taken, and — if A — the full list of
  paths `fixture_data.py --refresh` printed;
- that `data/sprites/asset_manifest.json` is byte-unchanged (measured, via
  `git diff --stat`).
