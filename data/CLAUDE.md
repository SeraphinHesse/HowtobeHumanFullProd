# CLAUDE.md — DATA package

Self-contained guide for `data/` — the single source of truth every other
package reads. Requirements: SPEC.md §5 (`D-*`). **When you change a format or
schema, update THIS doc.**

## What lives here
- `schemas/` — one JSON Schema per file type.
- `slots.json` — the slot registry (which asset slots exist per category,
  frame sizes, animation vocabularies, editor grouping) (D-32, E-34; see
  the Phase 5 section for why it is NOT under `schemas/`).
- `balancing/` — one file per domain (`buildings.json`, `enemies.json`,
  `map.json`, `ui.json`, `core.json`), each carrying a `_lock` field (D-10/11).
- `balancing_history/` — one file per domain (`buildings.json`, …, matching
  `balancing/`'s stems), each a flat newest-first JSON array of full-document
  snapshots appended only by the editor's explicit "Save Balancing Changes"
  action (`editor/balancing_history.py`, `editor/panels/balancing.py`). A
  **second schema-pairing exception** (see the map files entry below): every
  `data/balancing_history/*.json` validates against
  `schemas/balancing_history.schema.json`, not `schemas/<domain>.schema.json`
  — its filename stem intentionally collides with the real domain file's stem,
  so `tools/smoke.py` special-cases the directory the same way it already does
  for `maps/`.
- `maps/` — map files (terrain/zone grid with spawning as a painted zone,
  deco layer, base position) + `active_map.json` pointer (D-20/21).
- `sprites/` — `asset_manifest.json` (manifest v2, D-30) + `imported/` sheet
  PNGs (committed — they are content, not build artifacts).

## Balancing files (Phase 4 D-10/11/12, restructured Phase 9A)
- All five domains exist: `balancing/{buildings,enemies,map,ui,core}.json`,
  each with `schemas/<domain>.schema.json`. Since **Phase 9A** they hold the
  prototype's live tuning verbatim, restructured into the REPLAN nested
  feature tree (see planning/MIGRATION_PLAN.md): PascalCase group objects
  (`EconomyBuildings`, `TheHole`, `EnemyScaling`, …), snake_case leaves,
  tier struct-lists under a `tiers` key with the prototype's field names
  verbatim. `_lock` stays top-level. The prototype's 4 stringified
  LIGHTNING lists became real JSON arrays; the Features file dissolved into
  one canonical wired flag per concept (`ui:FX/gore_enabled`,
  `ui:FX/bg_art/enabled`, `ui:FX/income_floaters_enabled`,
  `ui:FX/boss_announce/enabled`, `core:TheHole/building_revive`,
  `core:XP/xp_from_buildings`).
- **Enemy sizing leaves (ER-1)**: each `enemies.json` `EnemyTypes/*` block carries
  a required `footprint` (int tiles, 1–8: the unit occupies footprint² tiles and
  its sprite is downscaled to `footprint*tile_w` wide, never upscaled) and
  `sprite_scale` (number 0.1–8, applied AFTER that fit — the knob for low-res
  art). The dead `Boss/era_sizes` and the `sprite_w`/`sprite_h` on every
  `Boss/stats` row were deleted from content AND schema in the same change:
  nothing read them, and render size now derives from the footprint.
- **`death_spawn` (ER-3)**: each `enemies.json` `EnemyTypes/*` block carries a
  **required** `death_spawn` block — `at_hp_fraction` (number 0–1: the unit dies
  once `hp <= max_hp *` this; `0.0` = the normal die-at-zero rule), `enabled`
  (bool: false = dies normally, spawns nothing), `spawn_hp_fraction` (number
  0–1: children spawn at this fraction of their OWN max HP; `1.0` = full) and
  `spawns` — **always an ARRAY of `$defs/spawn_counts` rows, one per era**,
  resolved `spawns[clamp(era)]`. The Boss carries 5 rows (index-aligned with its
  `stats`); a type with no eras carries a single row and always clamps to row 0,
  which IS the "flat per-type table" case. There is deliberately **no `oneOf`
  union** — a type-less schema node crashes the editor's balancing panel for the
  whole domain. Required-not-optional because `data/` is the only value store (a
  code-side default is banned) and the editor panel skips schema keys absent from
  the doc. `Boss/death_spawns` was REPLACED by `Boss/death_spawn` (the 5 rows
  moved verbatim under `spawns`).
- **Parity gate**: `tools/tests/balancing_parity_map.json` (committed,
  deliberately NOT under `data/` — smoke stem-pairs everything here) maps
  EVERY prototype live-JSON key to its new path, `MERGED:<target>`, or
  `DROPPED:<reason>`; `tools/tests/test_balancing_parity.py` asserts
  coverage both ways + value equality (skips whole if the prototype
  checkout is absent). The py-only live `BOSS_ERAS` list is committed as
  literal `_py_only` expectations (reshaped into `Boss/stats` +
  `Boss/death_spawn/spawns`; its dead `swarm_*` fields not migrated). When you
  move/rename a balancing key, update the mapping in the same change.
  - **The two tables have DIFFERENT semantics — do not confuse them.** The
    **main** table's consumer skips values that are `"DROPPED:<reason>"`
    strings. **`_py_only` is a literal-expectation table** (`{path, expect}`)
    whose consumer (`test_py_only_boss_eras_expectations`) has **NO `DROPPED:`
    branch** — a bare string there raises `TypeError: string indices must be
    integers`. So when a `_py_only` key MOVES you **re-path it**; never retag it
    `DROPPED:`, never delete it (it is the parity proof the value is unchanged).
    ER-3 re-pathed all 15 `Boss/death_*` entries that way — a pure prefix swap —
    leaving `_py_only` at 45 entries.
  - **The parity test SKIPS SILENTLY inside a git worktree**: it derives the
    prototype path from `REPO.parent`, which `.claude/worktrees/agent-XXX/`
    lacks, so the whole class skips — it looks green and proves nothing. Run it
    from a worktree that is a **SIBLING of the repo** and confirm the 4 tests
    actually RAN.
- **Schema shape (9A)**: tier/struct subschemas live in each schema's
  `$defs`, referenced via **local `#/$defs/` refs only** (plain
  `jsonschema.validate` resolves in-document refs fine; cross-file still
  forbidden). Every object level keeps `additionalProperties:false` + full
  `required` — except `era_unlock_round`, optional in the meditator/beam/
  wall-builder tier defs (only tier 0 carries it, prototype-verbatim). No
  `allOf` composition (it breaks `additionalProperties:false`).
  `random_names` has `minItems:1` and NO `maxItems` (the 9H add-name menu
  appends). Bounds policy, documented per-domain in the schema description:
  fractions/chances 0–1, HP/DMG (×10) 0–100000, costs/counts 0–10000,
  rounds/levels 0–1000, seconds 0–60, pixels ±4096.
- **`_lock` shape (D-11)**: `"UNLOCKED"` or
  `{"locked_by": <str>, "since": "YYYY-MM-DD"}` — enforced via `oneOf`
  (`const` / closed object, `since` checked by regex pattern, not
  `format:` which jsonschema doesn't assert). The subschema is **inlined in
  every domain schema** (no cross-file `$ref`: `engine.data_io` validates
  with a plain `jsonschema.validate`, which can't resolve external refs).
- **D-12 convention**: every property carries a `description` documenting
  units/scale (a test enforces presence), and every numeric property
  declares `minimum`/`maximum` — the editor derives spinbox ranges from
  them, making out-of-range input unrepresentable (ED-30). ×10 combat
  scale is noted in descriptions where it will apply; `core.json`'s
  `base_hp` stays 10, absolute HP — the deliberate NOT-×10 exception.
- Schemas follow the house style: `$id`, draft 2020-12,
  `additionalProperties: false`, all keys `required`, canonical D-3
  formatting (author schemas via `dumps_deterministic`, content via
  `write_validated` — never hand-format).

## Asset data (Phase 5, D-30/31/32 specifics)
- **`slots.json` location is a deliberate D-32 deviation**: SPEC says
  `data/schemas/slots.*`, but `tools/smoke.py` skips `data/schemas/` when
  validating, and the registry must be validated content — so it lives at
  `data/slots.json` with `schemas/slots.schema.json`.
- **`slots.json` shape**: ordered `categories[]` (array — order survives
  D-3 sorted-keys dumps and IS the editor tree order; the first five keys
  mirror the D-10 domains, then asset-only `vfx`/`deco`/`backgrounds`), each with
  `key/display_name/frame_w/frame_h/animations/groups`. `animations[0]` is
  always `idle` (schema-enforced). `groups` is a recursive tree of
  `{label, slots[] XOR children[]}`; a slot key may repeat across groups of
  ONE category (meditators reuse musician art) but never across categories
  (frame size would be ambiguous — loader rejects it).
- **`slots[]` entries: bare key OR frame-size override (ER-1, D1)**. An entry is
  either a bare key string (inherits the category's `frame_w`/`frame_h`) or
  `{key, frame_w, frame_h}` overriding it for that ONE slot. Bare is the norm —
  no committed entry uses the object form yet; it exists for art whose sheet is
  cut at a different size than its category (a 128×128 formation sheet in the
  64×96 `enemies` category). It describes **slicing, not drawing** — on-screen
  size comes from the render fit (`engine/render/CLAUDE.md`).
  - **`uniqueItems` no longer implies key uniqueness**: it compares whole values,
    so `"foo"` and `{"key": "foo", …}` are two distinct items. It is kept (it
    still catches literal duplicates, and it is the D-3 house style), and
    `SlotRegistry.__init__` picks up the slack — a key repeated within a category
    must AGREE on its frame size or the loader raises `ValueError`. Schemas for
    what schemas can express; loader cross-checks for what they cannot (the
    `engine/tilemap.py` precedent).
- **Variant families**: a leaf group whose slots are INTERCHANGEABLE art for
  one thing. `enemies` eras (`Walker → Era 2 → [enemy_stage_2,
  enemy_stage_2_v2]`) and `deco` prop TYPES (`Props → Rock → [deco_rock,
  deco_rock_v2]`) are both shaped this way, and the editor's "+ Variant"
  button appends `<stem>_v<k>` to either. `map → Tiles → Background` is NOT a
  variant family: every background slot needs its own map-file legend code, so
  "another background variant" is just another numbered `tile_background_<n>`
  type. Deco types are added as whole leaf subgroups (`Prop <n>` holding
  `deco_prop_<n>`), never appended to a flat list.
- **Frame sizes (SPEC §9.1 resolved)**: buildings / enemies / deco / core
  64×96; map tiles 64×32; ui / vfx 64×64; backgrounds 480×270 (10K full-frame
  menu art, drawn as a screen-space `HudSprite` — not a world sprite). All
  data — edit `slots.json`.
- **`sprites/asset_manifest.json` (manifest v2, D-30)**:
  `{version: 2, entries: {slot: {sheet: "imported/<slot>.png", frame_w,
  frame_h, offset_x, offset_y, rows[]}}}` with row =
  `{animation, frames, fps, hidden[], loop_start, loop_end, loop_count}`;
  `rows[0].animation` is schema-forced to `idle` (`prefixItems`). Written
  ONLY by the editor's import panel and `tools/migrate_prototype_assets.py`
  — both through `write_validated`.
- **`sprites/imported/*.png` are committed content (D-31)**, copied there at
  import time (editor) or by the migration tool. Never gitignore them.

## Map data (Phase 6, D-20/21/22 specifics)
- **`maps/<id>.json` (map files)**: `id` (== filename stem, loader-enforced),
  `display_name`, `cols`/`rows` (each map owns its dims, 4..1024; geometry.json
  keeps only tile pitch + zoom levels as global truth — large maps stay
  performant via windowed tile culling, see engine `visible_render_items`),
  `terrain` (rows strings of
  cols single-char codes — one line per row keeps diffs cheap), `legend`
  (schema-pinned char→{slot, checker} table: b/c/s = buildable/combat/
  spawning with checkerboard `_b` alternation, f/l/o = forest/cliff/ocean
  background, no alternation — the file is self-describing, no package
  hardcodes tile vocabulary), `base` ({col,row,slot} — slot const-pinned to
  `base_hole`), `camera_start` (nullable {col,row,slot}), `start_area`
  (nullable {col,row,slot} — slot const-pinned to `start_area`; {col,row} is
  the 2×2 starting area's MIN corner, spans col..col+1 × row..row+1, loader
  cross-checks col+1 < cols / row+1 < rows; anchors the game's tile-unlock
  section grid, never forces tile states, drawn by the editor as an outline
  only; existing maps were migrated to `"start_area": null`), `deco` (world
  positions; renders ABOVE entities, E-26). Spawning is a painted zone — the
  format has NO spawn-point objects.
- **SCHEMA-PAIRING EXCEPTION (the one directory rule)**: every
  `data/maps/*.json` EXCEPT `active_map.json` validates against
  `schemas/map_file.schema.json` (tools/smoke.py implements + tests this);
  `active_map.json` keeps normal stem pairing via `active_map.schema.json`.
  The stem `map` still belongs to the BALANCING domain (`balancing/map.json`).
- Dimension consistency (terrain row count/lengths, base/deco in bounds)
  is beyond JSON Schema → `engine.tilemap.load_map` cross-checks and fails
  LOUD (D-2). Read/write map files ONLY through `engine.tilemap`.
- **`maps/active_map.json` (D-21)**: `{"active": "<map_id>"}` — written
  ONLY by the editor's Set Active action (and tests). The game follows it
  at boot and fails loud if missing/invalid (art tolerance E-37 does not
  apply to map data).
- `maps/first_light.json` is the committed starter map (prototype-exact
  initial layout) so the game always boots on real data.

## Rules
- **JSON here is the ONLY value store** (D-1). Never move a value into Python;
  never reintroduce the prototype's py+json dual system.
- **Schema first:** adding a key = update the schema in the same change, then
  the content file. All writes validate (D-2); the game fails loud in dev on
  invalid data.
- Deterministic formatting: sorted keys, 2-space indent (D-3) — keeps diffs
  minimal for git and agents.
- Designers never hand-edit these files (the editor is their interface); you
  (an agent) may edit directly, but only schema-valid writes, and only in a
  domain whose `_lock` you hold (or with explicit user say-so for small
  tweaks).
- Balance semantics: ×10 combat HP/DMG scale; `BASE_HP` stays 10; units and
  scale are documented per key in the schema (D-12).
- `active_map.json` changes only via the editor's selector (D-21) unless the
  user explicitly asks.

## Verify before finishing
Validate every touched file against its schema and run the headless smoke test
(`tools/smoke.py` once it exists). Report agreement explicitly.
