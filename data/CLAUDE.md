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
- `maps/` — map files (terrain/zone grid with spawning as a painted zone,
  deco layer, base position) + `active_map.json` pointer (D-20/21).
- `sprites/` — `asset_manifest.json` (manifest v2, D-30) + `imported/` sheet
  PNGs (committed — they are content, not build artifacts).

## Balancing files (Phase 4, D-10/11/12 specifics)
- All five domains exist: `balancing/{buildings,enemies,map,ui,core}.json`,
  each with `schemas/<domain>.schema.json`. Values are **Phase 4
  placeholders** — real balance lands with the Phase 9 port; `map.json`
  holds only a placeholder multiplier until Phase 6 gives it the map format.
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
  mirror the D-10 domains, then asset-only `vfx`/`deco`), each with
  `key/display_name/frame_w/frame_h/animations/groups`. `animations[0]` is
  always `idle` (schema-enforced). `groups` is a recursive tree of
  `{label, slots[] XOR children[]}`; a slot key may repeat across groups of
  ONE category (meditators reuse musician art) but never across categories
  (frame size would be ambiguous — loader rejects it).
- **Frame sizes (SPEC §9.1 resolved)**: buildings / enemies / deco / core
  64×96; map tiles 64×32; ui / vfx 64×64. All data — edit `slots.json`.
- **`sprites/asset_manifest.json` (manifest v2, D-30)**:
  `{version: 2, entries: {slot: {sheet: "imported/<slot>.png", frame_w,
  frame_h, offset_x, offset_y, rows[]}}}` with row =
  `{animation, frames, fps, hidden[], loop_start, loop_end, loop_count}`;
  `rows[0].animation` is schema-forced to `idle` (`prefixItems`). Written
  ONLY by the editor's import panel and `tools/migrate_prototype_assets.py`
  — both through `write_validated`.
- **`sprites/imported/*.png` are committed content (D-31)**, copied there at
  import time (editor) or by the migration tool. Never gitignore them.

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
