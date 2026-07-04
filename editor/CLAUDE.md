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
- **Viewport selection-independence was Phase 4 only** — superseded by the
  Phase 5 entity-preview mode (below); tilemap-editor mode is still Phase 6.
- **Live verification convention**: windowed runs are driven by synthetic
  `QTest` events (real mouse click on the selector, real key events on form
  widgets), same as Phase 3.

## Phase 5 conventions (merged tree / details panel / entity preview)
- **Merged tree** (`panels/selector.py`): top-level nodes = registry
  categories in `data/slots.json` order (the first five double as balancing
  domains; vfx is asset-only. `deco` is ALSO asset-only but nested as a
  CHILD of the "map" node as of the Phase 6 follow-up — see the Phase 6
  section below — rather than its own top-level node). Children come from
  registry groups; the
  tree STOPS at the deepest group whose children are all leaf groups (a
  building TYPE like "Defender") — tiers/levels never appear in the tree.
  Signals: `node_selected(category, group_path)` on every selection, plus
  the Phase 4 `domain_selected(str)` at ANY depth of a domain category, so
  balancing follows while browsing types. ● markers (ED-11) come from
  `refresh_markers()` (pure `load_manifest`; the clean label sits in
  UserRole+1). A domain category with no balancing file is omitted whole
  (Phase 4 behavior).
- **Composite selection** (user-confirmed layout): tree node × Details
  subcategory dropdown (tier — or the concrete slot for flat groups) ×
  LevelBar index resolve to ONE slot key via the PURE `editor/selection.py`
  (`subcategories` / `level_slots` / `resolve_slot`; no Qt — test it
  headlessly). `MainWindow` owns the composite state and drives
  `viewport.set_preview_slot` + `details.set_slot`. Balancing keeps its
  last domain while vfx/deco nodes are selected. The level bar only
  resolves the ASSET slot — per-level balancing values stay Phase 9.
- **DetailsPanel** (`panels/details.py`, right pane): prototype-importer
  parity (ED-40/41). The sheet PNG is copied to
  `data/sprites/imported/<slot>.png` AT IMPORT TIME (prototype parity);
  Save writes the manifest entry through `write_validated`; Clear (confirm
  dialog in the UI path; `clear_entry(confirm=False)` for tests) removes
  entry + PNG. Row 0's animation combo is locked to `["idle"]` — the E-35
  rule is UNREPRESENTABLE in the UI, not a save-time error. Frame sizes and
  animation vocabularies come from the registry per slot. No pygame here;
  Pillow reads sheet dimensions.
- **One render path (ED-22)**: the ONLY animated preview is the viewport.
  Every Details edit emits `draft_changed(slot, entry_dict)` →
  `viewport.set_preview_draft` overrides that slot in an in-memory manifest
  (never disk) and rebuilds AssetStore + Renderer. `entry_saved` /
  `entry_cleared` → `viewport.reload_assets()` (re-read manifest from disk,
  drop draft — ED-42, no restart) + `selector.refresh_markers()`. Camera
  state lives in `_coords` and survives reloads (Phase 3 feel).
- **Entity preview (ED-21)**: the slot renders at the map centre on the
  `entities` layer over the grid, and the camera is parked on that same
  centre tile via `CoordinateSystem.center_on` (in `_resize_surface` and on
  entering entity mode) — `clamp` alone would anchor (not centre) the sprite
  to an edge whenever the grid overflows the viewport (at zoom 1 the 20x20
  grid is 1280px wide, wider than the center pane); the animation dropdown is a floating
  QComboBox child pinned top-left of the viewport, visible only when the
  effective entry has animations; the anim clock is wall-clock and resets
  on slot/animation/draft change. No asset → grey X (E-37).
- New editor modules MUST be added to `test_editor_viewport.TestPurity`'s
  import list (`details`, `level_bar`, `selection` are in).
- Measured live (this machine, windowed 1280x720, preview + import active):
  ~57 fps.

## Phase 6 conventions (tilemap mode, ED-10/ED-20/ED-23/ED-24)
- **Selection**: the Maps branch is the FIRST child of the "map" category
  node; one leaf per `data/maps/*.json` (pointer excluded), ● prefix =
  ACTIVE map (refresh_maps owns those markers; refresh_markers skips map
  nodes). A map leaf emits `map_selected(map_id)` + `domain_selected("map")`
  and NEVER `node_selected` — entity-preview machinery doesn't react.
  MainWindow: map node → tilemap mode (palette shown, right stack →
  MapDetailsPanel); any other node → `_leave_map_mode()` (entity preview
  exactly as Phase 5).
- **`editor/map_session.py`** owns the open doc (ONE map at a time, D-22)
  and THE global `QUndoStack` (ED-24). Phase 6 undo scope: paint strokes
  (ONE command per stroke — press→release coalesced, incl. line/rect/bucket),
  base move, deco place/remove, display-name edit. Balancing/import undo
  DEFERRED until those panels are next touched. Ctrl+Z / Ctrl+Y are
  window-level QActions on MainWindow. Dirty = `not undo_stack.isClean()`;
  save → `setClean()`. Opening a DIFFERENT map while dirty goes through
  `MainWindow._resolve_dirty()` (`dirty_policy`: "ask" | "save" | "discard";
  tests set the policy, the dialog is UI-only) — also injected into
  MapDetailsPanel.dirty_resolver for New/Duplicate. Browsing away to an
  entity node keeps the dirty doc in memory (reselecting the same map
  returns to it un-prompted).
- **Painting is pure-model first**: `editor/tilemap_ops.py` (no Qt) mutates
  the doc in place and returns `[(col,row,old,new), ...]` change lists;
  `line_cells`/`rect_cells` are exported separately for ghosts. The
  viewport only translates mouse events: ALL cell picking is
  `screen_to_world` → floor (E-3). Strokes Bresenham-interpolate between
  move events so fast drags don't gap.
- **Viewport map mode** (`set_map_mode(session)`): coords rebuilt with the
  map's dims; LEFT button = armed tool, RIGHT = pan (entity preview keeps
  either-button pan). Under the "none" tool a LEFT-drag that didn't grab the
  base pans too (inspect mode — `_drag_pos` is set after `_tool_press` when
  `_tool == "none" and not _base_drag`), so the camera moves without a brush
  armed. `_drag_pos` set ⇒ pan; a live brush stroke leaves it None. Ghosts are tinted engine sprites on the `overlay`
  layer; zone tints are per-code multipliers (ZONE_TINTS, editor chrome
  constants); grid lines go through `Renderer.submit_overlay_lines`
  (E-24) — QPainter still never draws tiles (ED-22). A press on the base's
  cell starts a base drag regardless of tool; hide the base eye to paint
  under it. `cursor_world` feeds the MainWindow status-bar readout (ED-23,
  both modes).
- **Palette** (`panels/palette.py`): brush icons are STATIC engine-resolved
  frames via the injected `viewport.slot_qimage` provider (user-confirmed
  ED-22 reading — not a second render path). Tile buttons rebuild from the
  open map's legend (`set_legend`), zone kinds first; deco slots come from
  the registry. Picker → `viewport.code_picked` → `palette.arm_code` loop.
  Follow-up: a "Base" section (registry `core` category, always just
  `base_hole`) sits in the SAME exclusive brush group as tile codes and
  deco — arming it (`arm_base`) is import-target-only (`_armed_slot()`'s
  priority: deco, then base, then the armed code's slot) since the base is
  never painted, only dragged; `viewport.arm_base` clears any stale armed
  code/deco so a leftover "paint" click can't use the wrong brush.
- **Lifecycle** (`panels/map_details.py`): New/Duplicate (schema-bounded
  dialog, id re-checked) / Save / Set Active — Set Active is the ONLY
  writer of `data/maps/active_map.json` (D-21). Create/duplicate write to
  disk immediately (all-forest fill for new maps) so the tree and the game
  see them; MainWindow follows `session.map_opened`/`active_changed` to
  refresh the Maps branch. Map deletion is deferred (destructive).
- **"None" tool (follow-up)**: `PalettePanel.TOOLS` starts with `"none"`,
  the default-armed tool on both the palette and a fresh `ViewportPanel`.
  It structurally cannot paint/erase/place deco (`_tool_press`'s dispatch
  matches none of its `if self._tool == ...` branches) but the base-cell
  check runs BEFORE tool dispatch, so dragging the base still works with
  "none" armed — this is the intended way to inspect/pan a map or grab the
  base without risking a stray brush stroke on a miss-click. A LEFT-drag
  under "none" (off the base) PANS the camera — the map-editor pan when no
  brush is armed. `viewport._ghost_items` returns nothing for `"none"` (no
  misleading preview of a placement that wouldn't happen).
- **Palette import (follow-up, `editor/asset_import.py`)**: the map
  palette replaces `DetailsPanel` in the right stack while a map is open,
  so the normal importer is unreachable from there. `PalettePanel`'s
  "Import Spritesheet…" button targets whichever brush is currently armed
  (deco first, then the Base/hole slot, else the armed code's slot) and
  calls the new
  `editor.asset_import.import_idle_sheet(data_dir, registry, slot_key,
  png_path)` — a Qt-free, pygame-free helper (added to
  `test_editor_viewport.TestPurity`) that always writes exactly ONE `idle`
  row (map/deco slots' `animations` vocabulary in `slots.json` is
  `["idle"]` only, so `DetailsPanel`'s multi-row `RowEditor` machinery is
  unnecessary here). Emits `manifest_changed(slot)`, wired to the same
  `MainWindow._on_manifest_changed` handler as `DetailsPanel.entry_saved`/
  `entry_cleared` — which now ALSO calls `palette.refresh_icons()` (a
  standing bug: importing art for a tile/deco slot through the normal
  Details panel while a different tree node was selected never refreshed
  the palette's brush icons before this fix).

## Phase 7 conventions (run controls, ED-1/ED-50/51/52, T-4)
- **`editor/run_controls.py`**: pure, Qt-optional builders (`play_command`,
  `build_command`, `playbuild_path`, `build_exists`) plus `RunControls
  (QObject)`.
- **Play and Playbuild are DETACHED, not tracked** — this is a deliberate
  deviation from ED-50's literal "subprocess output captured to an editor
  console pane" wording for Play, confirmed live and user-directed: both
  spawn a long-running GUI process (a pygame window / the frozen exe) that
  the user closes on their own schedule, and a QProcess parented to
  `RunControls` for that whole lifetime crashed live with `RuntimeError:
  Signal source has been deleted` when its `finished` signal fired. Only a
  one-line `launched(which, started_ok)` signal fires (console gets a
  "launched ... (detached)" or "FAILED to launch ..." note) — no output
  streaming. Three live-verification catches on the way to a working
  detached launch, in the order found:
  1. The static `QProcess.startDetached(program, args, workingDirectory)`
     returns `(ok, pid)` in this PySide6 version, NOT a bare bool —
     emitting the raw tuple into a `Signal(str, bool)` threw a Shiboken
     conversion error at the `.emit()` call site.
  2. **The real bug, found only by testing in an actual terminal (not my
     own automation)**: `editor/panels/viewport.py` sets
     `SDL_VIDEODRIVER`/`SDL_AUDIODRIVER` to `"dummy"` in `os.environ` at
     import time, for its OWN offscreen render surface (Phase 3
     convention). Since that's a real process-environment mutation, EVERY
     subprocess the editor spawns inherits it — so Play/Playbuild launched
     a real `game/main.py` / `HowToBeHuman.exe` that ran its full loop and
     printed "fps: N" every second (spamming whatever console it shared),
     but rendered into an invisible dummy surface: no window ever
     appeared. `editor/run_controls.py`'s `_real_window_environment()`
     strips both vars from a copy of `QProcessEnvironment.
     systemEnvironment()` before handing it to the detached child — a
     regression test (`test_real_window_environment_strips_sdl_dummy_vars`)
     reproduces the exact scenario by setting the same dummy vars the test
     file already sets for its own headless conventions.
  3. Handing that environment to a detached child requires the INSTANCE
     form `QProcess().startDetached()` (no args) — the static overload
     only takes program/arguments/workingDirectory, no environment.
     `run_controls.start_detached(program, arguments, working_dir)` is a
     plain module function wrapping this; `RunControls._detach` holds it
     as an **instance attribute** (not a bound method lookup) specifically
     so tests can substitute a fake launcher — mocking `QProcess.
     startDetached` directly (even with `unittest.mock.patch.object(...,
     autospec=True)`) silently failed to intercept the Shiboken-bound
     call, and the real method ran unmocked during a test.
- **Build stays tracked** (short-lived, progress matters): `RunControls`
  owns exactly one `QProcess` at a time for it — a second `build()` while
  one is in flight is refused, not queued. Signals: `output(str)` (merged
  stdout+stderr), `started("build")`, `finished("build", code)`,
  `build_state_changed(can_playbuild)`. `_on_ready_read`/`_on_finished`
  guard with `shiboken6.isValid(self)` before emitting, in case the editor
  is torn down mid-build. `RunControls` does NOT save dirty data or
  validate schemas — `MainWindow` does that before calling `.play()` —
  keeping this module a dumb subprocess launcher ("editor never runs game
  logic in-process"). Must stay in `test_editor_viewport.TestPurity`'s
  import list.
- **Unbuffered subprocess output is required for Build, not optional**:
  its `QProcess` gets `PYTHONUNBUFFERED=1` injected into its environment
  (`QProcessEnvironment.systemEnvironment()` + `insert`, never a bare
  environment — that would drop `PATH` etc.). Python fully block-buffers
  stdout once it isn't a tty (the QProcess pipe case), so without this the
  console pane shows nothing until the subprocess exits — verified live:
  omitting it left `console_len=0` seconds into a run; with it, output
  streamed within 10s of a PyInstaller build.
- **Console pane scope (resolves SPEC.md open question 3)**: Build's
  streamed progress + Play/Playbuild's one-line launch notes, in a
  `QDockWidget` docked bottom wrapping a read-only `QPlainTextEdit`.
  Spawnclaude's agent session (Phase 8) gets its own terminal, not this
  pane.
- **`MainWindow` wiring**: `addToolBar("Run")` holds three `QAction`s
  (Play/Build/Playbuild) — the first chrome beyond the undo/redo
  window-actions and the status bar. `_on_play()`: if `map_session.dirty`,
  `save()` it (balancing/import panels already write on every edit, so
  nothing else needs flushing); then `tools.smoke.validate_data(data_dir)`
  (reused, not duplicated) — on failure, `QMessageBox.critical` and abort,
  no launch. Only `build_action` disables on `started`/re-enables on
  `finished` (Play/Playbuild aren't tracked, so nothing to disable while
  they run). Playbuild gates on `RunControls.can_playbuild()`, re-checked
  via `build_state_changed` after every Build; disabled state carries a
  tooltip hint ("Run Build first…").
- **`tools/build.py`** (T-4): PyInstaller one-folder build, same
  pure-builder-plus-thin-`main()` shape as `tools/smoke.py`; calls
  `tools.smoke.validate_data()` first (fail loud before a slow build).
  Invoked as `[sys.executable, "-m", "PyInstaller", ...]` (not a bare
  `pyinstaller` console-script, which may not be on PATH), `--onedir`,
  `--add-data` separator via `os.pathsep`. Output: `dist/HowToBeHuman/
  HowToBeHuman.exe`. `*.spec` (PyInstaller drops one at repo root every
  build) is gitignored alongside `build/`/`dist/`/`*.exe`.
- **Frozen-exe data path (`game/main.py`)**: PyInstaller 6.x's `--onedir`
  nests `--add-data` targets under `_internal/`, NOT next to the exe —
  confirmed live (a `Path(sys.executable).parent`-based fix built cleanly
  but the frozen exe exited within ~4s; `data/` wasn't found). Fixed via
  `sys._MEIPASS` (PyInstaller's own pointer to wherever bundled resources
  live, correct for both onedir and onefile) instead of deriving from
  `sys.executable`. Re-verified live: the rebuilt exe stayed running past
  6s under the same trigger, and stayed running (detached) under the
  final Play/Playbuild design too.

## Phase 8 conventions (spawnclaude / locks / .claude commands, ED-60/61/62, T-1)
- **`editor/spawnclaude.py`**: pure Qt-free builders (`domain_choices`,
  `start_domain_prompt`, `small_tweak_prompt`, `spawn_command`) + `dispatch()`
  + `SpawnClaudeDialog`. Added to `test_editor_viewport.TestPurity`. Reads locks
  via `editor.locks` (ED-61 greying) and NEVER writes one.
- **Three dispatch modes.** The session's first input is the LITERAL slash
  command (passed as claude's initial-prompt arg), so Claude loads that skill
  directly — no natural-language wrapper:
  - **Domain** → `/start-domain <domain>`. **Delegation lock model
    (user-confirmed, reconciles ED-60 vs. locks.py's "editor never writes
    locks")**: the editor GUI does NOT flip any `_lock` JSON — the spawned
    `/start-domain` skill does, so the branch+lock protocol stays the single
    lock-writer and `/merge-domain` the only unlock (ED-62 "one enforcement
    point"). A test asserts spawnclaude exposes no set/clear/unlock symbol.
  - **Small tweak** → `/smalltweak <task>`. No lock, no domain scope — the
    scope guard fail-opens when no domain is active (does NOT pop a second
    guarded prompt).
  - **Admin** → a blank `claude` (no initial input, no lock, no scope) for
    unguarded work. `spawn_command(None)` omits the trailing prompt arg;
    `dispatch(admin=True)` selects it (precedence: admin > domain > tweak).
- **Terminal launch = Windows Terminal (`wt`) only** (user-confirmed).
  `spawn_command` → `["wt", "-d", <repo>, "cmd", "/k", "claude", <prompt>]`;
  `cmd /k` keeps the tab open so a launch error stays visible. The launch
  REUSES `run_controls.start_detached` (instance-form `QProcess().startDetached()`
  with `_real_window_environment()`) so the `SDL_VIDEODRIVER`/`AUDIODRIVER=dummy`
  vars the viewport sets at import time are stripped from the spawned terminal —
  same Phase 7 lesson, one tested strip point. `dispatch(detach=…)` is injectable
  so tests capture the argv instead of spawning a real terminal.
- **Its own terminal, not the Console dock** (resolves SPEC open-question 3,
  already noted Phase 7). `MainWindow` gets an `addToolBar("Agents")` with a
  single `Spawn Claude…` `QAction` → `_on_spawnclaude` (opens the dialog; locks
  re-read on every open, no watcher).
- **`.claude/` layout (T-1)**: `commands/` holds `start/resume/finish/merge-domain`,
  `smalltweak`, plus the ported `processtodo`/`replace-visual`. `hooks/scope_guard.py`
  is the PreToolUse file-scope guard (reads `.claude/active_domain`, fail-open when
  absent; deny via the `permissionDecision:"deny"` JSON; `_norm` strips a leading
  `./` only — NOT a leading dotdir, so `.claude/**` matches). Wired in
  `.claude/settings.json` on `Edit|Write|MultiEdit`. Lock writes go through
  `engine.data_io.write_validated` (the lock is a D-11 object now, not a string —
  commands use an inline `py -c`, never hand-edit).
- **Integration branch = `main`** (user-confirmed): `/start-domain` branches
  `feature<Domain>` off `main` and commits the lock to `main`; `/merge-domain`
  merges back into `main`. (The prototype's `claudeprototype` has no equivalent;
  `phase1-engine-core` is `origin/HEAD` but stale.) Per-domain docs
  (`game/<domain>/CLAUDE.md`) don't exist until Phase 9, so the commands fall
  back to `game/CLAUDE.md`.

## Verify before finishing
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it.
State exactly what you exercised (live editor run vs static read).
