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

## Phase 3 conventions (Qt viewport spike, ED-2/ED-22/ED-23)
- **Embed approach: QImage-copy fallback, ACCEPTED.** `editor/panels/viewport.py`
  renders the full engine pipeline (`RenderItem` → `Renderer` → offscreen
  `pygame.Surface` sized to the widget) then converts the surface to a
  `QImage` (`surface_to_qimage`, pure/testable — `pygame.image.tobytes` +
  `QImage(..., Format_RGB888).copy()`) and paints it in `paintEvent` via
  `QPainter.drawImage`. No second render path, no QPainter-drawn tiles
  (ED-22) — QPainter only blits the converted frame.
- **Measured (this machine, live windowed run, 1280x720, 20x20 grid,
  release-ish build):** steady-state ~62.5 fps, ~8.5–11 ms per frame for
  render + submit + `flush` + `surface_to_qimage` + `update()`/paint
  combined. Comfortably clears the 60fps bar (ED-2) — no need for a
  lower-level embed (native window handle reparenting, etc.) at this scope.
  Re-measure if the grid grows much larger or Phase 5+ adds many animated
  sprites.
- **SDL dummy-driver rule**: `editor/panels/viewport.py` sets
  `SDL_VIDEODRIVER=dummy` / `SDL_AUDIODRIVER=dummy` at module level, before
  `import pygame` — the editor's pygame surface is always an offscreen
  target sized to the widget; the editor never opens a real SDL window.
  This mirrors `tools/render_demo.py`'s convention and must stay first in
  the module (before any other pygame-touching import).
- **Headless-drive convention**: `editor/main.py` exposes
  `main(max_frames=None)`, same shape as `game/main.py`. Run under
  `QT_QPA_PLATFORM=offscreen` for CI/agent verification (Qt's env-var
  analogue to `SDL_VIDEODRIVER=dummy`); frames are driven by a `QTimer`
  (`FRAME_INTERVAL_MS = 16`), never a busy loop. FPS is measured over
  real wall-clock time (not assumed from the timer interval) and logged to
  stdout + the window title about once a second.
- **Input**: drag pan and wheel zoom live on `ViewportPanel`
  (`mousePressEvent`/`mouseMoveEvent`/`mouseReleaseEvent`/`wheelEvent`),
  calling only `engine.coords` methods (`pan`, `clamp`, `set_zoom`,
  `world_to_screen`/`screen_to_world`) — no iso math in the editor. Pan
  accepts **either right-click-drag (ED-23/game "same feel") or left-click-
  drag** — left is an editor-only addition for input devices without a
  right button; `game/main.py` stays right-click-only per spec. Zoom
  anchors on the viewport centre, matching `game/main.py`'s `step_zoom` (ED-23
  "same feel"). Verified live via synthetic `QTest` mouse/wheel events against
  the real windowed app (not just headless unit tests) — panning is a no-op
  whenever the map's pixel extent fits inside the viewport on that axis
  (`CoordinateSystem.clamp` centers instead of panning in that case; this is
  expected `clamp()` behavior, not a bug — e.g. at zoom 1 the 20x20 map is
  exactly as wide as a 1280px viewport).
- Panel/tests keep one `QApplication` instance per test process
  (`QApplication.instance() or QApplication(sys.argv)`); Qt only allows one
  per process.

## Phase 4 conventions (selector / balancing / locks, ED-3/ED-30..32)
- **Shell layout** (`main.py`): plain `QSplitter`s — selector (left) |
  viewport (center) over balancing (bottom). Full docking +
  `.editor_prefs.json` persistence (ED-1) is deliberately deferred.
  `MainWindow(max_frames=None, data_dir=None)`; the first listed domain is
  selected on startup.
- **`data_dir` injection**: every editor module takes `data_dir=None`
  (defaults to `<repo>/data`), mirroring `ViewportPanel` — this is what lets
  tests run against a tempfile copy of `data/` and never mutate the repo.
- **`locks.py` is read-only**: `DOMAINS` (canonical D-10 order),
  `balancing_path`/`schema_path` (the domain→file convention),
  `lock_info`/`is_locked`/`owner`/`since`. No set/clear/force-unlock exists
  anywhere in the editor (a test asserts this); /start-domain and
  /merge-domain (Phase 8, T-1) are the only lock writers.
- **`panels/selector.py`**: flat `QTreeWidget` of the domains whose
  `data/balancing/<domain>.json` exists, D-10 order, SingleSelection (ED-3).
  Emits `domain_selected(str)` — the only coupling to the shell. Deferred to
  Phase 5/6 data: Maps node, Buildings type→tier→level subtree, ● asset
  markers (ED-10/11).
- **`panels/balancing.py`**: `set_domain(d)` re-reads data + schema fresh
  from disk and rebuilds a `QFormLayout`: integer → `QSpinBox`, number →
  `QDoubleSpinBox` (ranges from schema `minimum`/`maximum` — invalid input
  is unrepresentable, ED-30), `enum` → `QComboBox` (typed `itemData`),
  boolean → `QCheckBox`; tooltips carry the schema `description` (D-12
  units/scale). Underscore keys (`_lock`) never become fields. Every widget
  change writes the whole doc via `engine.data_io.write_validated` (ED-31) —
  signals are connected *after* initial values are set, so form population
  never writes. Locked domain → all fields disabled + banner
  "Locked by <owner> since <date>" (ED-32); lock state is read at selection
  time (re-select to refresh; no file watcher). Undo via the global
  QUndoStack (ED-24) lands with the tilemap editor.
- **Viewport is selection-independent in Phase 4**: it keeps rendering the
  grey-X grid whatever is selected — mode switching (tilemap editor / entity
  preview) needs the Phase 5 slot registry and Phase 6 map format.
- **Live verification convention**: windowed runs are driven by synthetic
  `QTest` events (real mouse click on the selector, real key events on form
  widgets), same as Phase 3.

## Verify before finishing
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it.
State exactly what you exercised (live editor run vs static read).
