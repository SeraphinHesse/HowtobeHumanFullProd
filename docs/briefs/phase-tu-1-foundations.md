# Phase TU-1 — Foundations (engine + data, no UI)

Source plan: `planning/TutorialPLAN.md` — Vision (§1), D1/D3/D4/D5 (§2),
build-order row TU-1 (§3, lines 129–153). This phase is pure data + the pure
`engine/tilemap.py` model. **Nothing player-visible yet** — no editor, no
game-loop wiring. That is the exit bar, not an aspiration: if you find
yourself touching `game/**` or `editor/**`, you have left this phase's scope.

## 1. Behavioral spec

**Goal (verbatim from the plan, `planning/TutorialPLAN.md:131-132`)**: "every
data shape exists and validates; the map format carries the tutorial markers.
Nothing player-visible yet."

**D1 (map markers)** — `planning/TutorialPLAN.md:53-60`: `engine/tilemap.py`
gains two nullable single-tile markers `tutorial_flute` / `tutorial_stone`,
"the exact `camera_start` pattern": schema-pinned, bounds cross-checked in
`validate_doc`, **never rendered by the emitters**.

- **verified** `engine/tilemap.py:48-53` — `TileMapDoc.camera_start` /
  `start_area` are the two existing nullable `{col,row,slot}` markers to
  mirror.
- **verified** `engine/tilemap.py:58-72` (`from_dict`) and `:75-89` (`to_dict`)
  — both markers round-trip through a dict OR `None`.
- **verified** `engine/tilemap.py:105-121` (`validate_doc`) — both existing
  markers get an `if doc.X is not None and not (0 <= col < cols and 0 <= row
  < rows): raise ValueError(...)` block; deco/base follow the same shape.
- **verified** `engine/tilemap.py:299-306` — `camera_start_slot_from_schema` /
  `start_area_slot_from_schema` dig the const-pinned slot out of the schema
  via the shared `_object_slot_from_schema` helper (`:283-291`).
- **verified** `engine/tilemap.py:332-346` (`new_doc`) — both existing
  markers default to `None` on a freshly created map.
- **verified** `data/schemas/map_file.schema.json:40-72` — `camera_start`'s
  `oneOf [null, object{col,row,slot:const}]` shape, `:202-234` — `start_area`'s
  identical shape (2×2-min-corner semantics don't apply to the new single-tile
  markers; only `camera_start`'s shape is the template). Root `required` array
  at `:245-256` lists every property including both existing markers —
  **`additionalProperties: false` + full `required` means every committed map
  file must carry the new keys** (verified precedent:
  `data/CLAUDE.md:334` — "existing maps were migrated to `"start_area":
  null`" when that marker was added). **measured**: `data/maps/` holds 7 real
  map files besides `active_map.json` (`first_light`, `holex`, `summertest2`,
  `summertest3`, `test`, `test2`, `testo`) — all 7 need the two new keys added
  (`null`) or `validate_data`/`load_active_map` fails loud on every one of
  them.
- **Correction (orchestrator, post-reconciliation with TU-2's brief):** the
  slot const is never a real *sprite* — `data/schemas/map_file.schema.json:
  222-223` confirms `start_area`'s const is "not this sprite," the editor
  draws an outline instead — but `start_area`/`camera_start` each still carry
  a real `core` registry **group** in `data/slots.json`
  (**verified** `editor/panels/palette.py:226-244`:
  `_camera_slots`/`_start_area_slots` call
  `self._registry.group_slots("core", ("Camera Start",))` /
  `(("Start Area",))`). That group is what lets the palette's brush button
  resolve a slot key/icon at all (`refresh_icons()`,
  `editor/panels/palette.py:457-464`) — an outline-only marker still needs
  ONE slot key to arm. **TU-1 must add two matching `core` groups**,
  `"Tutorial Flute"` → slot `tutorial_flute` and `"Tutorial Stone"` → slot
  `tutorial_stone`, each const-pinned to match the map schema's `slot` const
  (same shape as the existing `"Start Area"` group). This closes TU-2's
  flagged gap (`docs/briefs/phase-tu-2-paint-mode.md` §0) so TU-2 does not
  need to touch `data/slots.json` itself.

**D3 (tutorial script is data)** — `planning/TutorialPLAN.md:70-76`:
`data/tutorial/tutorial.json` + `data/schemas/tutorial.schema.json`, holding
the step list, both message texts verbatim, `skippable: true`,
`first_loss_costs_life: true`, and "the highlight/gate wiring" — a step's
`message` (string id), `highlight` (opaque string ids), `advance_on` (event
id), input `allow` list, and free-form `flags` (D2, `:61-69`). TU-1 does
**not** implement the sequencer (that is `engine/tutorial.py` in TU-6,
`planning/TutorialPLAN.md:240`) — only the data shape, designed so **TU-6/TU-7
extend the step list without a schema change** (explicit in TU-7's file list,
`planning/TutorialPLAN.md:274`: "script gains the round-2 steps — schema from
TU-1 already covers them").

Both message texts, verbatim (must appear character-for-character in
`tutorial.json`, `planning/TutorialPLAN.md:45-49`):
1. `You need love to create. In order for you to gain Love, you need economy buildings`
2. `Once the humans reach our hole the round is lost. You have only 3 lives. If economy buildings get destroyed during the human attack they don't yield resources. To defend your base you need to build defense buildings`

**D4 (cutscene registry)** — `planning/TutorialPLAN.md:77-88`:
`data/video/cutscenes.json` + `data/schemas/cutscenes.schema.json`, entries
`id → {video, audio (nullable), length, trigger}`, `trigger` enum
`intro`/`first_end_turn`. TU-1 only creates the registry file — migrating
`game/main.py`'s hardcoded path (**verified** `game/main.py:233-234`: `video =
VideoSource(data_dir / "video" / "cutscene.mp4",
ui_balance["Menu"]["cutscene_length"], ...)`, length **verified**
`data/balancing/ui.json:24` — `"cutscene_length": 44.2`) is explicitly TU-5's
job (`planning/TutorialPLAN.md:210-227`). TU-1 leaves `main.py` untouched.

**D5 (one balancing tunable)** — `planning/TutorialPLAN.md:89-94`:
`Tutorial.economy_buildings_required` (default 1, min 1) as a new group in
`data/balancing/core.json` + `data/schemas/core.schema.json`, the
`/add-balancing-value` pattern. **verified** existing domain-group shape at
`data/balancing/core.json:1-50` and `data/schemas/core.schema.json:1-254`
(five groups: `General`, `LightningStrike`, `PhaseLoop`, `TheHole`, `XP`, each
`additionalProperties:false` + full `required`, alphabetically ordered,
D-3/D-12 conventions — **verified** `data/CLAUDE.md:104-109`: every numeric
leaf needs a `description` + `minimum`/`maximum`, and `test_balancing_data.py`
(**verified** `tools/tests/test_balancing_data.py:20-51`) walks every domain
generically checking exactly that — no edit to that test file is needed if
the new leaf follows the convention).

**Smoke's directory-exception rule** — **verified**
`tools/smoke.py:25-68` (`validate_data`): four existing exceptions (maps,
`balancing_history`, `agent_forms`, `ui/screens`), each because the file's
*stem* is arbitrary and can't stem-pair to its own schema. **Both new files
(`data/tutorial/tutorial.json`, `data/video/cutscenes.json`) have a stem that
already equals their schema's stem** (`tutorial` ↔ `tutorial.schema.json`,
`cutscenes` ↔ `cutscenes.schema.json`) — the existing `else: schema =
schema_dir / f"{path.stem}.schema.json"` branch (`tools/smoke.py:61`)
already resolves both correctly with **zero code change**. This is the
"whichever keeps `validate_data` simplest" option the plan itself sanctions
(`planning/TutorialPLAN.md:80`). See §3 for the (still required) doc/test
consequences of choosing this — the phase does not silently skip touching
`tools/smoke.py`.

## 2. Architecture plan

1. **`engine/tilemap.py`**: add `tutorial_flute`/`tutorial_stone` to
   `TileMapDoc` as two more nullable `{col,row,slot}` markers, following
   `camera_start` byte-for-byte through `from_dict`/`to_dict`/`validate_doc`/
   `new_doc`, plus two new schema-const helpers
   (`tutorial_flute_slot_from_schema`/`tutorial_stone_slot_from_schema`) reusing
   the existing `_object_slot_from_schema`. They are **never** added to any
   `render_items`/`visible_render_items`/`band_render_items` emitter — that is
   the whole point of D1 ("never rendered by the emitters").

2. **`data/schemas/map_file.schema.json`**: add `tutorial_flute` and
   `tutorial_stone` properties, each an exact structural copy of
   `camera_start`'s `oneOf` block with a new `const` slot string
   (`"tutorial_flute"` / `"tutorial_stone"` respectively — plain marker ids,
   not real asset-registry slots, exactly like `start_area`'s const). Add both
   names to the root `required` array.

3. **Migrate every committed map file.** Because the schema's `required`
   array is now longer, all 7 real maps under `data/maps/` (everything except
   `active_map.json`) need `"tutorial_flute": null, "tutorial_stone": null`
   added, written back through `data_io.write_validated` (or
   `tilemap.save_map`) so they land in canonical D-3 form. This is the exact
   precedent `data/CLAUDE.md:334` already documents for `start_area`. Without
   this step `py tools/smoke.py` fails on every existing map, and
   `load_active_map` fails loud at boot.

4. **`data/tutorial/tutorial.json` + `data/schemas/tutorial.schema.json`**
   (new). Schema: root keys `skippable` (bool), `first_loss_costs_life`
   (bool), `messages` (a **closed** 2-key object —
   `economy_intro`/`lives_intro`, both required strings — matching TU-4's
   "step *structure* is fixed... only texts/flags are editable"), `steps`
   (array, `minItems:1`, items `$ref` a `$defs/step` with `additionalProperties:
   false`: `id`, `message` (nullable string id into `messages`), `highlight`
   (array of opaque strings — engine-agnostic per D2), `advance_on` (string
   event id), `allow` (array of strings), `flags` (object,
   `additionalProperties: true` — the ONE deliberately-open leaf in this
   schema, mirroring the precedent of `map_file.schema.json`'s open background
   legend codes at `data/schemas/map_file.schema.json:119-138`, so TU-6/TU-7
   attach whatever per-step data they need with no schema bump).
   Content: both message texts verbatim under `economy_intro`/`lives_intro`;
   `skippable: true`; `first_loss_costs_life: true`; a **round-1-only** step
   list (message box #1 → highlight `tile:tutorial_flute` → highlight
   `card:musician` → highlight `button:confirm` → highlight
   `button:end_turn`) — round-2 steps are explicitly TU-7's addition
   (`planning/TutorialPLAN.md:274`), not TU-1's.

5. **`data/video/cutscenes.json` + `data/schemas/cutscenes.schema.json`**
   (new). Schema: root object, `additionalProperties: {$ref: #/$defs/entry}`
   (an open registry — D4's "room to grow"), `required: ["intro",
   "first_end_turn"]` (the two entries this phase must seed). Entry:
   `video` (string, bare filename under `data/video/` — the caller supplies
   the directory prefix, matching `game/main.py:233`'s existing
   `data_dir / "video" / "cutscene.mp4"` composition), `audio` (nullable
   string), `length` (number, seconds — **not** a balancing file so the D-12
   "seconds 0-60" balancing convention doesn't bind it; use a generous
   0–3600 cap), `trigger` (enum `["intro", "first_end_turn"]` today; a new
   trigger point is a schema bump later, per D4). Content: `intro` →
   `{"video": "cutscene.mp4", "audio": null, "length": 44.2, "trigger":
   "intro"}` (the file **verified** already exists at `data/video/cutscene.mp4`);
   `first_end_turn` → a placeholder video filename (need not exist on disk —
   `engine/video.py`'s `VideoSource` gracefully skips a missing file,
   **verified** `engine/CLAUDE.md:73-81`), `audio: null`, a placeholder
   `length`.

6. **`data/balancing/core.json` + `data/schemas/core.schema.json`**: add a
   `Tutorial` group (alphabetically between `TheHole` and `XP`) with one leaf,
   `economy_buildings_required` (integer, `minimum: 1`, `maximum: 10000`
   matching the existing "counts" bucket, `default`-free since `data/` is the
   only value store — the JSON *is* the default). Content: `{"Tutorial":
   {"economy_buildings_required": 1}}`.

7. **Refresh the pinned test fixture.** **verified**
   `tools/tests/fixture_data.py:1-23` — every value-asserting test reads
   `FIXTURE_DATA` (`tools/tests/fixtures/data/`), a deliberately-frozen JSON
   mirror of `data/`, refreshed only by `py tools/tests/fixture_data.py
   --refresh`. This phase changes `map_file.schema.json`, `core.schema.json`/
   `core.json`, all 7 map files, and adds two new schema+content pairs — **run
   the refresh command after landing the data changes, before running the
   suite**, or `test_tilemap_model.py` (which reads `FIXTURE_DATA / "schemas"
   / "map_file.schema.json"`, **verified** `tools/tests/test_tilemap_model.py:
   14-20`) keeps validating against the STALE pre-TU-1 schema and the new
   tilemap round-trip tests (§ Tests below) will fail confusingly.

8. **New test file reads live data, but through the fixture, not
   `REPO/"data"`.** **verified** `tools/tests/test_fixture_guard.py:22-47,
   58-82` — any `test_*.py` that contains the literal pattern `REPO / "data"`
   (among other spellings) must be on the `ALLOWED` allowlist or the guard
   fails. `test_tutorial_data.py` must import `FIXTURE_DATA`/`fixture_copy`
   from `tools.tests.fixture_data` (same pattern as
   `tools/tests/test_tilemap_model.py:15,19-20`) instead of touching
   `REPO / "data"` directly — this avoids needing to touch
   `test_fixture_guard.py` at all. Pass `FIXTURE_DATA` (or a `fixture_copy`
   tempdir) as `smoke.validate_data(data_root)`'s argument for the "both new
   JSON files validate via smoke" test, never the bare live root.

## 3. File scope + shared-file contract

**New:**
- `data/tutorial/tutorial.json`
- `data/schemas/tutorial.schema.json`
- `data/video/cutscenes.json`
- `data/schemas/cutscenes.schema.json`
- `tools/tests/test_tutorial_data.py`

**Modified:**
- `engine/tilemap.py` — five insertion points, all inside the existing
  `camera_start`/`start_area` neighborhoods:
  1. `TileMapDoc` dataclass (`:38-54`): two new fields immediately after
     `start_area: dict = None` (`:53`).
  2. `from_dict` (`:58-72`): two new kwargs immediately after the
     `start_area=` kwarg (`:70-71`), before the closing `)`.
  3. `to_dict` (`:75-89`): two new keys immediately after the `"terrain":`
     line (`:88`) — alphabetically last (`t-e` < `t-u`), before the closing
     `}`.
  4. `validate_doc` (`:92-125`): two new bounds-check blocks immediately
     after the `start_area` block (`:115-121`), before the `deco` loop
     (`:122`).
  5. Two new helper functions (`tutorial_flute_slot_from_schema`,
     `tutorial_stone_slot_from_schema`) immediately after
     `start_area_slot_from_schema` (`:304-306`), before `defaults_from_schema`
     (`:309`).
  6. `new_doc` (`:332-346`): add `tutorial_flute=None, tutorial_stone=None` to
     the `TileMapDoc(...)` call, after `start_area=None` (`:345`).
- `data/schemas/map_file.schema.json` — two new properties
  (`tutorial_flute`/`tutorial_stone`), each an exact copy of the
  `camera_start` block (`:40-72`) with the const slot renamed, inserted
  alphabetically right after `"terrain"` (`:235-243`), before the closing
  `}` of `"properties"`; add both names to the root `"required"` array
  (`:245-256`), alphabetically last.
- **All 7 real map files** under `data/maps/` (`first_light.json`,
  `holex.json`, `summertest2.json`, `summertest3.json`, `test.json`,
  `test2.json`, `testo.json`) — add `"tutorial_flute": null, "tutorial_stone":
  null`, rewritten in canonical D-3 form. (`active_map.json` is the pointer
  file and is untouched — it pairs to `active_map.schema.json`, not
  `map_file.schema.json`.)
- `tools/smoke.py` — **no functional change** (see §1/§2 point 8): the
  existing stem-pairing `else` branch already resolves both new files
  correctly. If you disagree and want an explicit directory exception for
  symmetry with the other four, it is a legal alternative — but then you
  must also bump the docstring's exception count (`tools/smoke.py:26-39`,
  currently "FOUR") and add the two new `elif` branches right after the
  `screens_dir` branch (`tools/smoke.py:58-59`), using two new `tutorial_dir =
  data_root / "tutorial"` / `video_dir = data_root / "video"` locals declared
  next to `screens_dir` (`:47`). **Do not do both** — pick one, and keep
  `test_tutorial_data.py`'s smoke assertion consistent with whichever you
  picked.
- `data/balancing/core.json` + `data/schemas/core.schema.json` — new
  `Tutorial` group, alphabetically between `TheHole` (`core.json:30-36`,
  `core.schema.json:122-161`) and `XP` (`core.json:37-49`,
  `core.schema.json:162-243`); add `"Tutorial"` to the schema's root
  `required` array (`core.schema.json:245-251`), same alphabetical slot.
- `data/slots.json` — **added per the correction above**: two new `core`
  registry groups, `"Tutorial Flute"` (one slot, `tutorial_flute`) and
  `"Tutorial Stone"` (one slot, `tutorial_stone`), same shape as the existing
  `"Start Area"` group (`data/slots.json`, `core` category) — write via
  `write_validated` against `data/schemas/slots.schema.json`. This is a data-
  only addition (no sprite, no manifest entry needed — the marker is drawn as
  an outline, never a sprite); it exists solely so TU-2's palette brush
  buttons have a slot key to arm.
- `tools/tests/test_tilemap_model.py` — add a `TestTutorialMarkers` class
  mirroring `TestCameraStart` (`:239-299`) 1:1: defaults-to-None + round-trip,
  disk round-trip, slot-const-from-schema, out-of-bounds fails loud, and (per
  `TestStartArea`'s `test_never_emitted_by_render_emitters`, `:348-354`) a
  test that neither marker appears in any emitter's output even with
  `camera=True`. Add near the end of the file, after `TestStartArea`
  (`:301-354`), before `TestBandRenderItems` (`:357`).
- `engine/CLAUDE.md` — **shared with TU-6** (which adds a brand-new
  `engine/tutorial.py` top-level-module bullet). To keep the two edits
  textually non-overlapping regardless of merge order:
  - **TU-1's edit**: append one sentence to the END of the `tilemap.py`
    bullet's first paragraph — immediately after "...the game doesn't draw
    it and the editor draws a pure 2×2 outline via `submit_overlay_lines`."
    (`engine/CLAUDE.md:44`), and BEFORE the "Checkerboard parity is
    PROTOTYPE-EXACT" sub-bullet (`:45`) — introducing `tutorial_flute`/
    `tutorial_stone` as two more never-rendered markers.
  - **TU-6's edit** (informational only — do not do this in TU-1): a whole
    new top-level-module bullet for `engine/tutorial.py`, appended AFTER the
    existing `video_playback.py` bullet (`engine/CLAUDE.md:82-87`, the last
    bullet in the "Top-level modules" section), BEFORE "## Hard rules (whole
    package)" (`:89`). Flag this boundary to whoever plans/executes TU-6.
- `data/CLAUDE.md` — **added beyond the task's given file list**, because
  `data/CLAUDE.md:4` ("When you change a format or schema, update THIS doc")
  and the root router's exit checklist (`CLAUDE.md` "Step 2... If anything
  architectural changed: update the package CLAUDE.md") both bind here: this
  phase adds two schema/content pairs and changes two existing schemas.
  Two insertion points:
  1. Append one sentence to the end of the "Map data" section's `maps/<id>.json`
     bullet (`data/CLAUDE.md:319-336`, right after the `start_area` sentence
     ending "...existing maps were migrated to `"start_area": null`."),
     introducing `tutorial_flute`/`tutorial_stone` and repeating the same
     migration note for them.
  2. A new subsection, e.g. "## Tutorial + cutscenes data (Phase TU-1, D3/D4)",
     inserted after the "Map data" section ends (after `data/CLAUDE.md:355`,
     the `maps/first_light.json` sentence) and before "## Rules"
     (`data/CLAUDE.md:357`), documenting the two new schema-pairing choices
     and the new `Tutorial` balancing group. **Flag this file back to the
     orchestrator** — confirm before landing since it wasn't in the original
     scope list.

**Not in scope for TU-1** (do not touch): `game/**`, `editor/**`, `data/ui/**`.
(`data/slots.json` IS in scope now — see the correction above and the new
bullet in this section.)

## 4. Exit gate

```bash
py tools/tests/fixture_data.py --refresh   # re-mirror the changed schemas/content
py tools/smoke.py                          # data validation + 5-frame headless boot
py tools/testgate.py check --affected      # while iterating
py tools/testgate.py check                 # full suite once, before handoff — GATE PASS or not done
```

Also confirm:
- `jsonschema.validate` against the new schemas rejects: a step with an
  unknown key (`additionalProperties:false`), a `messages` object missing
  either required text, and `Tutorial.economy_buildings_required: 0`
  (`minimum: 1`).
- All 7 real maps still `load_active_map`/`load_map` cleanly with the new
  required keys present as `null`.
- `smoke.validate_data()` (against the fixture, not live `data/`, per §2
  point 8) reports both new files checked without a `FileNotFoundError`.

**Quick Test** (this phase is explicitly "nothing player-visible yet" — the
Quick Test is a regression check that it stayed that way):
1. `py editor/main.py` — open the Maps tree, open any existing map (e.g.
   `first_light`). It must look and behave EXACTLY as before (no new paint
   mode, no new markers drawn) — TU-2 hasn't landed yet.
2. `py game/main.py` — the game must boot to the same intro cutscene /
   main menu it did before this phase, with identical timing. If it hangs,
   crashes, or looks different, the map migration or the `cutscenes.json`
   addition broke something it shouldn't have (this phase must not touch
   `game/main.py`).
