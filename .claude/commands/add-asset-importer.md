---
description: Use when the task is to wire a new renderable game-element category into the editor's asset pipeline so a designer can import its spritesheet (registry category + slots + selector + import path).
argument-hint: <element category, e.g. "projectiles" or "boss cutscene frames">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py tools/testgate.py*), Bash(py -m pytest*), Bash(py tools/smoke.py*)
---

Wire a new game-element category into the editor's asset importer: **$ARGUMENTS**.
Use this when a new kind of renderable thing (a new VFX family, projectile art, a new
enemy/building CATEGORY not just a variant) needs a home in `data/slots.json` and a
way for a designer to import its sheet. For adding a variant to an EXISTING slot,
use the editor's `+ Variant` button; for swapping one slot's art, use
`/replace-visual`.

## Read first (token-light)
1. `editor/panels/CLAUDE.md` — the merged selector tree (categories from
   `data/slots.json` order), DetailsPanel import, `asset_import.import_idle_sheet`,
   the ● marker + one-render-path rules.
2. `engine/assets/CLAUDE.md` — the slot registry + manifest v2 (frame size,
   `animations` vocabulary, grey-X placeholder).

## Steps
1. **Registry category/group** — add the category (and its leaf groups) to
   `data/slots.json`: each slot needs a key, frame size, and an `animations`
   vocabulary. Map/deco-style slots use `["idle"]` only; animated entities list their
   real animations (idle/walk/attack/death/…). `load_registry` fails LOUD, so keep it
   schema-valid.
2. **Selector surfaces it** — the tree builds top-level nodes from registry
   categories in `slots.json` order and stops at the deepest all-leaf group, so a
   well-formed category appears automatically. If it should ALSO be a balancing
   domain, it needs a `data/balancing/<domain>.json`; asset-only categories (like
   vfx) don't.
3. **Import path** — a multi-row animated slot uses `DetailsPanel` (row 0 idle
   locked, per-row fps/hidden/loop). A single-`idle` slot (tiles/deco/simple FX) uses
   `editor.asset_import.import_idle_sheet(data_dir, registry, slot_key, png_path)`
   (Qt-free, pygame-free, in `TestPurity`). Confirm whichever importer targets your
   slot key and emits `manifest_changed`/`entry_saved` so
   `MainWindow._on_manifest_changed` refreshes markers + palette icons.
4. **One render path (ED-22)** — the animated preview is the viewport only; edits
   emit `draft_changed` → in-memory manifest override, save → `reload_assets()`.
   Grey-X until art is imported (E-37).
5. **Purity** — any new editor module goes in `test_editor_viewport.TestPurity`.
6. **Game consumption** — if game code renders the new element, it resolves the slot
   through the registry/`SpriteAnimator` like everything else; a new slot joins the
   pool the moment it's saved (no code change for variants).

## Verify
- `py tools/smoke.py` — registry + manifest validate.
- `py tools/testgate.py check` — TestPurity + any registry/import
  test.
- Live: `py editor/main.py` — the category's node appears in the tree; import a sheet
  onto a slot; it previews in the viewport; grey-X before import; and (if game-facing)
  `py game/main.py` shows it.

## Final report
- Changed files (slots.json + any editor wiring); the new category + its slots;
  verification performed; whether `editor/panels/CLAUDE.md` needed a durable update.
- Tag every claim **measured** / **verified** / **inferred** (see `/report`).
