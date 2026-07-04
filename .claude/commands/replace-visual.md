---
description: Replace a slot's grey-X placeholder with a real spritesheet via the manifest-v2 asset pipeline.
argument-hint: <slot-key> <path-to-sheet.png>
allowed-tools: Bash(py tools/smoke.py*), Bash(py -c *), Bash(git status*), Bash(git add*), Bash(git commit*), Bash(git push*), Read, Edit, Write, Glob, Grep
---

Give slot **$1** a real spritesheet from **$2**, wiring it into the manifest-v2
asset system. Unlike the prototype, this repo has **no `sprite_gen` / procedural
fallback** — the grey-X placeholder is the only "no asset" state (SPEC non-goal).
So "replacing a visual" here means adding a manifest entry, not editing code.

## Facts

- Slots and their frame sizes / animation vocabularies are declared in
  `data/slots.json` (D-32). A slot key belongs to exactly one category — that
  fixes its frame size (buildings/enemies/deco/core 64×96; map tiles 64×32;
  ui/vfx 64×64).
- Imported sheets live at `data/sprites/imported/<slot>.png` (committed content,
  D-31) and the manifest is `data/sprites/asset_manifest.json` (manifest v2,
  D-30). Both are written ONLY through `engine.data_io.write_validated`.
- Row 0 of any entry is always `idle` (schema-forced).

## Steps

1. Confirm `$1` is a real slot in `data/slots.json` and note its frame size.
2. **Single-animation (idle-only) slots** — tiles, deco, base, most UI — use the
   Qt-free helper:
   ```
   py -c "from editor import asset_import; from engine.assets.registry import load_registry; reg=load_registry('data'); asset_import.import_idle_sheet('data', reg, '$1', r'$2'); print('imported $1')"
   ```
   It copies the sheet to `data/sprites/imported/$1.png` and writes exactly one
   `idle` row through the validating writer.
3. **Multi-animation slots** (buildings/enemies with attack/death/… rows) are a
   designer task best done in the editor's Details import panel (per-row
   animation / fps / hidden / loop). From an agent, replicate that by writing the
   manifest v2 entry directly through `write_validated` — one row per animation,
   row 0 = idle — matching the slot's animation vocabulary from `slots.json`.
4. Verify: `py tools/smoke.py` (validates the manifest against its schema and
   runs the game headlessly). If the slot is a building/enemy, a live
   `py game/main.py` or the editor's entity preview confirms it animates.
5. `git status`, summarize, wait for confirmation, then
   `git add data/sprites/imported/$1.png data/sprites/asset_manifest.json` →
   `git commit -m "art: real sheet for $1"` → push per whatever branch you're on
   (respect any active domain scope — a tile/deco slot belongs to the `map`
   domain, a building slot to `buildings`, etc.).

Never hand-format the manifest JSON. Never gitignore the imported PNGs — they are
content, not build artifacts.
