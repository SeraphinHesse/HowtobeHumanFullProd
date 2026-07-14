---
description: Use when the task is to add or change a balancing tunable/value in a domain (buildings/enemies/map/ui/core). Keys into data/balancing/<domain>.json + schema mirror; the recursive editor form renders it for free.
argument-hint: <domain + value, e.g. "core: xp reward per boss kill">
allowed-tools: Read, Edit, Grep, Glob, Bash(py tools/smoke.py*), Bash(py tools/testgate.py*), Bash(py -m pytest*)
---

Add a balancing value: **$ARGUMENTS**. Every gameplay tunable comes from
`data/balancing/` at startup (G-7) — never hardcode a constant. The five domains
are `buildings` / `enemies` / `map` / `ui` / `core`.

## Read first (token-light)
1. `data/CLAUDE.md` — the writer + schema discipline (single value store, no py+json
   dual system).
2. The target `data/balancing/<domain>.json` + `data/schemas/<domain>.schema.json`
   — see how a sibling key is shaped, and place the new key in the right nested
   subtree.

## Steps
1. **Add the key** to `data/balancing/<domain>.json` in its nested group. Use a real
   JSON array where the value is a list (not a stringified list). ×10 combat scale
   applies to HP/DMG values; `base_hp` stays 10 (the documented exception).
2. **Mirror it in the schema** `data/schemas/<domain>.schema.json` (draft 2020-12,
   `additionalProperties:false`, the key added to `required`): give it a `type`, a
   per-key `description`, and `minimum`/`maximum` where meaningful — the editor's
   spinboxes read those bounds so **invalid input is unrepresentable** (ED-30). For a
   repeated tier shape, reuse/extend the local `#/$defs/...` ref.
3. **No editor code needed** — `editor/panels/balancing.py` recurses the schema and
   renders the new leaf automatically (integer→spinbox, number→double-spinbox,
   bool→checkbox, enum→combo, string→line-edit). If you added a NEW `$ref` kind or a
   variable-length array, check that the recursive form handles it (it only supports
   local `#/$defs/` refs and fixed-length scalar arrays).
4. **Wire the read** in game code through `game/core/balance.py` (`load_balance`) —
   never re-read the JSON directly.
5. Writes to `data/` MUST go through `engine.data_io.write_validated` (deterministic:
   sorted keys, 2-space indent). If you're editing the JSON by hand here, keep it
   schema-valid; the smoke test will catch drift.

## Verify
- `py tools/smoke.py` — schema validation over all data files.
- `py tools/testgate.py check` — if a balancing-parity or editor-form
  test covers the domain.
- Optional live: `py editor/main.py`, select the domain, confirm the new field renders
  with its bounds; `py game/main.py` confirms the value takes effect.

## Final report
- Changed files (json + schema); the key's path + bounds; verification performed.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
