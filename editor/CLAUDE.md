# CLAUDE.md — EDITOR package

Self-contained guide for `editor/` — the PySide6 editor, the designer's single
interface to all game data. You reached here from the root router.
Requirements: SPEC.md §7 (`ED-*`). **When you change editor
architecture/conventions, update THIS doc.**

## File scope you may edit
`editor/**`. Never import or edit `game/**`. The editor talks to `engine/`
(rendering, assets, coords) and `data/` (through the validating writer) —
nothing else.

## Architecture
- `main.py` — Qt shell: docked panels, layout persisted to
  `.editor_prefs.json` (gitignored).
- `panels/` — selector (tree), viewport, balancing form, asset import.
- `run_controls.py` — Play (subprocess `py game/main.py`) / Build
  (PyInstaller) / Playbuild (launch `dist/` exe). Always subprocesses; the
  editor never runs game logic in-process.
- `spawnclaude.py` — dispatch a `claude` session with a domain lock or in
  small-tweak (no-lock) mode.
- `locks.py` — read/enforce `_lock` on `data/balancing/*`; the editor obeys
  the same lock rules as agents (ED-62) and NEVER force-unlocks.

## The selection model (the editor's core invariant)
Exactly one selected node (map / building level / enemy / UI / VFX slot)
drives everything: viewport mode (tilemap editor for maps, entity preview for
entities), balancing panel content, and asset-import context (ED-3). New
editor features should hang off selection, not add parallel state.

## Hard rules
- **One render path:** the viewport draws through `engine/render` into an
  embedded surface — never a second Qt-side renderer (ED-22). What the editor
  shows is what the game draws.
- All `data/` writes go through the schema-validating writer; invalid input
  must be unrepresentable in the forms (ED-30/31).
- Locked domain → read-only UI with owner shown (ED-32); greyed out in
  spawnclaude (ED-61).
- Asset import keeps full parity with the prototype importer's semantics
  (ED-40): rows = animations, row 0 idle, per-row fps/hidden/loop, offset,
  animated preview via `playback_order`.

## Verify before finishing
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it.
State exactly what you exercised (live editor run vs static read).
