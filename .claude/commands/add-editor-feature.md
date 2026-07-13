---
description: Use when the task is to add an editor feature or panel. Hangs it off the single-selection model, one render path (ED-22), all writes via write_validated, adds the module to TestPurity.
argument-hint: <feature, e.g. "per-level balancing focus in the details panel">
allowed-tools: Read, Edit, Write, Grep, Glob, Bash(py -m unittest*), Bash(py tools/smoke.py*)
---

Add an editor feature: **$ARGUMENTS**. This is an `editor/` task; never import or
edit `game/**` (the editor talks only to `engine/` + `data/`).

## Read first (token-light)
1. `editor/CLAUDE.md` — architecture + the hard rules (selection model, one render
   path, no lock writes).
2. `editor/panels/CLAUDE.md` — the panel conventions for the area you're touching
   (selector / balancing / details / palette / map-details / viewport).

## Steps
1. **Hang it off selection** — the single selected node (map / building level /
   enemy / UI / VFX slot) drives every panel. Add your feature as a reaction to the
   existing selection signals (`node_selected`/`domain_selected`/`map_selected`), NOT
   as a new parallel state store (ED-3).
2. **One render path (ED-22)** — any preview draws through the engine pipeline into
   the viewport surface. QPainter never draws tiles/sprites; a static icon uses the
   injected `viewport.slot_qimage` provider. No second renderer.
3. **All `data/` writes go through `engine.data_io.write_validated`** — invalid input
   must be unrepresentable in the form (bounds from the schema, ED-30/31). Never
   hand-write JSON.
4. **Locks** — read-only display via `editor.locks`; the editor NEVER sets/clears a
   `_lock` (a test asserts no such symbol exists). A locked domain → disabled fields
   + owner banner.
5. **Keep pure helpers Qt-free/pygame-free** — logic that can live outside Qt goes in
   an `editor/*.py` helper (like `selection.py`/`registry_ops.py`/`tilemap_ops.py`) so
   it's headlessly testable.
6. **`data_dir` injection** — new modules take `data_dir=None` (defaults to
   `<repo>/data`) so tests run against a temp copy.
7. **Register purity** — add any new editor module to
   `test_editor_viewport.TestPurity`'s import list (or `test_editor_panels` where
   appropriate).

## Verify
- `py -m unittest discover -s tools/tests -t .` — TestPurity + the panel's test
  (drive it with synthetic `QTest` events, one `QApplication` per process).
- Live: `py editor/main.py` (or headless under `QT_QPA_PLATFORM=offscreen`) — exercise
  the feature; for data-writing features confirm the JSON validates and a Play
  subprocess loads it.

## Final report
- Changed files; how it hangs off selection; verification performed (live editor vs
  static read); whether `editor/panels/CLAUDE.md` needed a durable-rule update.
