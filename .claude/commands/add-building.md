---
description: Use when the task is to add or create a new building type (defence/economy/boost/structure). Produces leaf class + research row + registry + balancing subtree + slots, following the 10B-10E pattern.
argument-hint: <building name + type, e.g. "Sun Scorcher (beam defence)">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py tools/smoke.py*), Bash(py -m unittest*)
---

Add a new building: **$ARGUMENTS**. This follows the migration plan's 10B–10E
pattern (each of those phases adds "a leaf class + one row and never reopens the
roll").

## Read first (token-light)
1. `game/buildings/CLAUDE.md` — the hierarchy rules (all-state-in-components,
   parents compute derived values, leaves ≤ ~10 lines).
2. The closest existing leaf to what you're adding (Defender for defence, Musician
   for economy) — copy its shape, don't invent one.
3. `game/buildings/research.py` — the `RESEARCH` table + `ResearchSpec` fields.

## Steps
1. **Leaf class** in the right module (`defence.py` / `economy.py` /
   `boost.py`-style / `structure.py`): declare only `SUBTREE` (path into
   `buildings.json`), `BUILDING_TYPE`, `TIER_SPRITES` prefixes, tags, and component
   wiring. **Never store derived values** (max_hp/upgrade_cost/damage/yield/…) — the
   parent computes them from `TierState` + balancing. Keep it ≤ ~30 lines.
2. **Balancing subtree** — add the building's block to `data/balancing/buildings.json`
   under its group, and mirror it in `data/schemas/buildings.schema.json` (draft
   2020-12, `additionalProperties:false`, per-key `description` + min/max). ×10
   combat scale for HP/DMG. (See `/add-balancing-value` for the schema-mirror
   discipline.)
3. **Research row** — add ONE `ResearchSpec` row to `game/buildings/research.py`
   (`starts_unlocked`, `starts_with_tier`, `gate_kind`/`gate_path`, `unlock_group`,
   UI copy). A spec stores WHERE in `buildings.json` to read a gate, never a gate
   VALUE. **Do NOT reopen or restructure the level-up roll** — adding a row is the
   whole integration.
4. **Registry** — confirm `game/buildings/registry.py`'s `create(...)` factory
   covers the new `BUILDING_TYPE` (it re-exports `LEAF_CLASSES`); add it if the
   factory dispatches explicitly.
5. **Slots** — add the sprite group to `data/slots.json` (frame size + tier sprite
   prefixes) so art can be imported; grey-X until then. If the editor needs a new
   category, see `/add-asset-importer`.
6. Combat buildings advertise via the `Attacker` component + `"combat"` tag, never
   an `IS_COMBAT`-style flag — the combat sweep must stay type-agnostic.

## Avoid
- Storing any derived stat on the leaf (breaks the "parents compute" rule).
- Duplicating placement validation (it lives in `registry.place_building`).
- Hardcoding cost/effect in UI and gameplay separately — one value in
  `buildings.json`.

## Verify
- Headless: a tier-max test upgrades the line asserting hp/dmg/yield per the
  balancing tables at each step: `py -m unittest discover -s tools/tests -t .`.
- Data: `py tools/smoke.py` (schema validation).
- Live: `py game/main.py` — build it, upgrade it, confirm cost/effect + it appears
  in the construct list once its gate opens.

## Final report
- Changed files; the building's type + gate; verification performed (headless test
  / smoke / live); whether `game/buildings/CLAUDE.md` needed a durable-rule update.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
