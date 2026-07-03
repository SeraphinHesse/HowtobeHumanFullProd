# CLAUDE.md — DATA package

Self-contained guide for `data/` — the single source of truth every other
package reads. Requirements: SPEC.md §5 (`D-*`). **When you change a format or
schema, update THIS doc.**

## What lives here
- `schemas/` — one JSON Schema per file type, plus the slot registry
  declarations (which asset slots exist per category, frame sizes, animation
  vocabularies) (D-32, E-34).
- `balancing/` — one file per domain (`buildings.json`, `enemies.json`,
  `map.json`, `ui.json`, `core.json`), each carrying a `_lock` field (D-10/11).
- `maps/` — map files (terrain/zone grid with spawning as a painted zone,
  deco layer, base position) + `active_map.json` pointer (D-20/21).
- `sprites/` — `asset_manifest.json` (manifest v2, D-30) + `imported/` sheet
  PNGs (committed — they are content, not build artifacts).

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
