# CLAUDE.md — editor/panels

The PySide6 panels: viewport, selector (tree), balancing form, details/import,
palette, map-details. You reached here from `editor/CLAUDE.md`. Requirements:
SPEC.md §7 (`ED-*`). When you change a panel's conventions, update THIS doc.

**Two invariants govern every panel** (also in the router): everything is
**selection-driven** (hang new features off the single selected node, not parallel
state), and there is **one render path** — the viewport draws through
`engine/render` into an embedded surface; QPainter never draws tiles (ED-22).
**Every new editor module MUST be added to `test_editor_viewport.TestPurity`'s
import list.**

## Phase 3 — Qt viewport spike (`panels/viewport.py`, ED-2/22/23)
- **Embed = QImage-copy fallback, ACCEPTED.** The viewport renders the full engine
  pipeline (`RenderItem` → `Renderer` → offscreen `pygame.Surface` sized to the
  widget) then converts to a `QImage` (`surface_to_qimage`, pure/testable —
  `pygame.image.tobytes` + `QImage(..., Format_RGB888).copy()`) and paints it in
  `paintEvent` via `QPainter.drawImage`. No second render path, no QPainter-drawn
  tiles (ED-22) — QPainter only blits the converted frame.
- Measured live (1280x720, 20x20 grid): ~62.5 fps, ~8.5–11 ms/frame combined —
  clears the 60fps bar (ED-2); no lower-level embed needed at this scope.
  Re-measure if the grid grows much larger or many animated sprites are added.
- **SDL dummy-driver rule**: `viewport.py` sets `SDL_VIDEODRIVER=dummy` /
  `SDL_AUDIODRIVER=dummy` at **module level, before `import pygame`** — the
  editor's pygame surface is always an offscreen target; the editor never opens a
  real SDL window. Must stay first in the module. **NOTE this is a real
  `os.environ` mutation that every editor subprocess inherits** — the reason
  `run_controls` strips those vars before launching Play/Playbuild (see router).
- **Headless-drive**: `editor/main.py` exposes `main(max_frames=None)`; run under
  `QT_QPA_PLATFORM=offscreen` for CI/agent verification. Frames driven by a
  `QTimer` (`FRAME_INTERVAL_MS = 16`), never a busy loop. FPS measured over real
  wall-clock, logged to stdout + title ~1×/sec.
- **Input**: drag pan + wheel zoom call only `engine.coords` methods (no iso math).
  Pan accepts **either right-click-drag (ED-23 game "same feel") or
  left-click-drag** — left is an editor-only addition for input devices without a
  right button; `game/main.py` stays right-click-only. Zoom anchors on viewport
  centre. Panning is a no-op whenever the map's pixel extent fits inside the
  viewport on that axis (`CoordinateSystem.clamp` centers — expected, not a bug).
- One `QApplication` per test process (`QApplication.instance() or
  QApplication(sys.argv)`); Qt allows only one.

## Phase 4 — selector / balancing / locks (ED-3/30/31/32)
- **Shell layout** (`main.py`): plain `QSplitter`s — selector (left) | viewport
  (center) over balancing (bottom). Full docking + `.editor_prefs.json`
  persistence (ED-1) deferred. `MainWindow(max_frames=None, data_dir=None)`; first
  listed domain selected on startup.
- **`data_dir` injection**: every editor module takes `data_dir=None` (defaults to
  `<repo>/data`) — lets tests run against a tempfile copy and never mutate the repo.
- **`panels/selector.py`**: flat/merged `QTreeWidget` (Phase 5 extends it). Emits
  `domain_selected(str)` — the coupling to the shell.
- **`panels/balancing.py`** (recursive since Phase 9A): `set_domain(d)` re-reads
  data + schema fresh from disk and rebuilds the form inside a `QScrollArea`,
  recursing the 9A nested tree: object → `CollapsibleSection` (QToolButton arrow
  header; depth-1 groups start expanded, deeper collapsed), array of objects → one
  collapsed sub-section per index titled `[i] — <name>` when the item has a `name`
  field, array of scalars → one row per index (**fixed length** — no add/remove
  rows; `random_names` grows via the game's 9H add-name menu). Scalar leaves:
  integer → `QSpinBox`, number → `QDoubleSpinBox` (4 decimals; ranges from schema
  `minimum`/`maximum` — invalid input unrepresentable, ED-30), `enum` → `QComboBox`
  (typed `itemData`), boolean → `QCheckBox`, string → `QLineEdit` (commit on
  `editingFinished`; text shorter than `minLength` restored, not written). Local
  `#/$defs/` refs resolved by `_deref` (the only `$ref` kind allowed);
  schema-optional leaves absent from the doc (tier `era_unlock_round`) skipped.
  Widgets register in `self._widgets` keyed by `/`-joined paths
  (`"DefenceBuildings/BasicDefence/tiers/0/base_dmg"`); numeric/enum widgets are
  `_NoWheelSpinBox`/`_NoWheelDoubleSpinBox`/`_NoWheelComboBox` (ignore
  `wheelEvent` so scrolling the panel can never nudge a value by accident — the
  event propagates to the enclosing `QScrollArea` instead).
  **Edits are staged, not written immediately**: `_commit(path, value)` walks the
  doc (numeric segment → list index) and mutates `self._doc` in memory only,
  then toggles a small pending-change dot (`self._dots`) next to that field by
  comparing against `self._baseline` (a deep copy taken at `set_domain`/last-save
  time) — signals connected *after* initial values are set, so form population
  never dirties anything. The toolbar's **"Save Balancing Changes"** button
  (enabled only while `self._dirty` is non-empty) is the ONE place that calls
  `engine.data_io.write_validated` (ED-31) — it prompts for a required session
  name + optional description (`_SaveMetaDialog`), then also appends a full-doc
  snapshot to that domain's history via `editor.balancing_history.save_session`
  (`data/balancing_history/<domain>.json`, a per-domain flat newest-first JSON
  array — one file per domain because domains lock/edit independently, unlike
  the old prototype's single combined snapshot). **"Version History"** opens
  `_HistoryDialog`, listing that domain's sessions newest-first; "Load into
  Editor" replays a past snapshot into the live widgets via
  `_apply_snapshot`/`_set_widget_value` (staged only — dirty dots reappear for
  whatever differs from the current baseline, nothing is written until the user
  clicks Save again); "Delete" removes an entry via
  `balancing_history.delete_session`. Locked domain → all fields disabled +
  banner "Locked by <owner> since <date>" (ED-32); lock state read at selection
  time (re-select to refresh; no file watcher). Undo (ED-24) deferred for
  balancing. Test note: `test_editor_panels.TempDataCase` normalizes every domain
  to UNLOCKED in its temp copy (repo files are legitimately locked while a feature
  branch exists).
- **`locks.py` is read-only** (in `editor/`, not `panels/`, but governs the form):
  `DOMAINS` (D-10 order), `balancing_path`/`schema_path`,
  `lock_info`/`is_locked`/`owner`/`since`. **No set/clear/force-unlock anywhere in
  the editor** (a test asserts this); `/start-domain` + `/merge-domain` are the
  only lock writers.

## Phase 5 — merged tree / details / entity preview
- **Merged tree** (`panels/selector.py`): top-level nodes = registry categories in
  `data/slots.json` order (first five double as balancing domains; vfx is
  asset-only; `deco` is asset-only, nested as a CHILD of the "map" node — Phase 6
  follow-up). Children come from registry groups; the tree STOPS at the deepest
  group whose children are all leaf groups (a building TYPE like "Defender") —
  tiers/levels never appear in the tree. Signals: `node_selected(category,
  group_path)` on every selection, plus `domain_selected(str)` at ANY depth of a
  domain category, so balancing follows while browsing types. ● markers (ED-11)
  from `refresh_markers()` (pure `load_manifest`; clean label in UserRole+1). A
  domain category with no balancing file is omitted whole.
- **Composite selection** (user-confirmed): tree node × Details subcategory
  dropdown (tier — or the concrete slot for flat groups) × LevelBar index resolve
  to ONE slot key via the PURE `editor/selection.py` (`subcategories` /
  `level_slots` / `resolve_slot`; no Qt — test headlessly). `MainWindow` owns the
  composite state and drives `viewport.set_preview_slot` + `details.set_slot`.
  Balancing keeps its last domain while vfx/deco nodes are selected. The level bar
  only resolves the ASSET slot — per-level balancing values stay Phase 9.
- **"+ Variant" / "+ Type" buttons** (sprite variants): the LevelBar carries a
  trailing `+ Variant` + `+ Type` button. WHICH selections offer them is a product
  call in the shell — `MainWindow._VARIANT_TARGETS` (`{"enemies": None, "deco":
  None, "map": {"Background"}}`; `None` = any leaf subcategory) filtered through
  `_variant_target()`; `selection.variant_target` is the game-name-free structural
  half. The `map` entry is a real constraint: `Buildable`/`Combat`/`Spawning` are
  leaf subgroups too, and a `tile_buildable_v2` would silently break the
  checkerboard `_b` pairing. `set_levels(..., can_add=…, can_add_type=…)` forces
  the bar visible even for one level.
  - **enemies / deco** → `registry_ops.add_variant` appends an interchangeable
    `<stem>_v<k>` slot (`next_variant_key`; a bare slot counts as v1 so the first
    add is `_v2`).
  - **map → Background** → `registry_ops.add_background_slot`: a background needs
    its OWN legend code, so "another variant" IS another numbered
    `tile_background_<n>` type. `_bind_background_code` claims that code in the open
    map (undoable). No map open → registry-only (paintable once some map's `+ Level`
    claims a code).
  - **`+ Type` (deco only)** → `registry_ops.add_deco_prop` appends a whole leaf
    CHILD group (`Prop <n>` holding `deco_prop_<n>`) under `Props`. Same handler as
    the palette's `+ Add Prop`.
  - All are pure `write_validated` calls in `editor/registry_ops.py` (`TestPurity`).
    After the write MainWindow reloads every cached registry
    (`selector`/`details`/`viewport`/`palette` `.reload_registry()`) and
    `select_last()`s the new slot. No game change needed: `enemy.py:variant_slot`
    already rolls a random variant per spawn across an era's slots, and a deco
    placement stores its CONCRETE slot in the map file.
- **DetailsPanel** (`panels/details.py`, right pane): prototype-importer parity
  (ED-40/41). The sheet PNG is copied to `data/sprites/imported/<slot>.png` AT
  IMPORT TIME; Save writes the manifest entry through `write_validated`; Clear
  (confirm dialog in UI; `clear_entry(confirm=False)` for tests) removes entry +
  PNG. Row 0's animation combo is locked to `["idle"]` — the E-35 rule is
  UNREPRESENTABLE in the UI, not a save-time error. Frame sizes + animation
  vocabularies come from the registry per slot. No pygame here; Pillow reads sheet
  dimensions.
- **One render path (ED-22)**: the ONLY animated preview is the viewport. Every
  Details edit emits `draft_changed(slot, entry_dict)` → `viewport.set_preview_draft`
  overrides that slot in an in-memory manifest (never disk) + rebuilds
  AssetStore/Renderer. `entry_saved`/`entry_cleared` → `viewport.reload_assets()`
  (re-read manifest, drop draft — ED-42, no restart) + `selector.refresh_markers()`.
  Camera state lives in `_coords` and survives reloads.
- **Entity preview (ED-21)**: the slot renders at the map centre on the `entities`
  layer over the grid; the camera is parked on that centre tile via
  `CoordinateSystem.center_on` (`clamp` alone would anchor, not centre, when the
  grid overflows the viewport); the animation dropdown is a floating QComboBox
  pinned top-left, visible only when the effective entry has animations; the anim
  clock is wall-clock and resets on slot/animation/draft change. No asset → grey X
  (E-37). New modules go in `test_editor_viewport.TestPurity`'s import list
  (`details`, `level_bar`, `selection` are in). Measured ~57 fps.

## Phase 6 — tilemap mode (`panels/palette.py`, `panels/map_details.py`; ED-10/20/23/24)
- **Selection**: the Maps branch is the FIRST child of the "map" category node; one
  leaf per `data/maps/*.json` (pointer excluded), ● prefix = ACTIVE map. A map leaf
  emits `map_selected(map_id)` + `domain_selected("map")` and NEVER `node_selected`.
  MainWindow: map node → tilemap mode (palette shown, right stack →
  MapDetailsPanel); any other node → `_leave_map_mode()` (entity preview as Phase 5).
- **`editor/map_session.py`** owns the open doc (ONE map at a time, D-22) and THE
  global `QUndoStack` (ED-24). Phase-6 undo scope: paint strokes (ONE command per
  stroke — press→release coalesced, incl. line/rect/bucket), base move, deco
  place/remove, display-name edit. Ctrl+Z / Ctrl+Y are window-level QActions. Dirty
  = `not undo_stack.isClean()`; save → `setClean()`. Opening a DIFFERENT map while
  dirty goes through `MainWindow._resolve_dirty()` (`dirty_policy`:
  "ask"|"save"|"discard"). Browsing away to an entity node keeps the dirty doc in
  memory.
- **Painting is pure-model first**: `editor/tilemap_ops.py` (no Qt) mutates the doc
  in place and returns `[(col,row,old,new), ...]` change lists; `line_cells`/
  `rect_cells` exported separately for ghosts. The viewport only translates mouse
  events: ALL cell picking is `screen_to_world` → floor (E-3). Strokes
  Bresenham-interpolate between move events so fast drags don't gap.
- **Viewport map mode** (`set_map_mode(session)`): coords rebuilt with the map's
  dims; camera opens (and re-frames on window resize, `_resize_surface`) centred
  on the map's own `camera_start` via `_center_on_camera_start` — the same view
  `game/main.py:frame_camera()` opens on at boot — falling back to `clamp` (which
  centres if the map fits the viewport, else anchors) when no startpoint has been
  painted yet. LEFT = armed tool, RIGHT = pan (entity preview keeps either-button pan).
  Under the "none" tool a LEFT-drag that didn't grab the base pans too (inspect
  mode — `_drag_pos` set after `_tool_press` when `_tool == "none" and not
  _base_drag`). `_drag_pos` set ⇒ pan; a live brush stroke leaves it None. Ghosts
  are tinted engine sprites on the `overlay` layer; zone tints are per-code
  multipliers (ZONE_TINTS); grid lines go through `Renderer.submit_overlay_lines`
  (E-24) — QPainter never draws tiles. A press on the base's cell starts a base
  drag regardless of tool; hide the base eye to paint under it. `cursor_world` feeds
  the status-bar readout.
- **Palette** (`panels/palette.py`): brush icons are STATIC engine-resolved frames
  via the injected `viewport.slot_qimage` provider (not a second render path). Tile
  buttons rebuild from the open map's legend (`set_legend`), zone kinds first; deco
  slots from the registry. Picker → `viewport.code_picked` → `palette.arm_code`.
  **Decoration mode is two-level**: a `Type:` `QComboBox` lists the `Props` group's
  child labels; the brushes below are ONLY that type's variants (`Var 1`, `Var 2`,
  … — one brush per variant, so a specific variant lands in the map file). `+
  Variant` extends the shown type, `+ Add Prop` adds a new type. Because only the
  shown type has buttons, **`arm_deco(slot)` switches the combo to that slot's own
  type first**. Follow-up: a "Base" section (registry `core` category, always
  `base_hole`) sits in the SAME exclusive brush group — arming it (`arm_base`) is
  import-target-only (`_armed_slot()` priority: deco, then base, then armed code's
  slot) since the base is never painted, only dragged.
- **Lifecycle** (`panels/map_details.py`): New/Duplicate (schema-bounded dialog, id
  re-checked) / Save / Set Active / Delete — Set Active is the ONLY writer of
  `data/maps/active_map.json` (D-21). Create/duplicate write to disk immediately
  (all-forest fill for new maps). **Delete map** (`MapSession.delete`,
  `engine.tilemap.delete_map`) is confirm-dialog gated (mirrors
  `details.py:clear_entry` / `balancing.py:_HistoryDialog._delete_selected`) and
  refuses the ACTIVE map (button disabled + tooltip; would leave the D-21
  pointer dangling) — deleting always targets the currently-open doc, which
  `_on_delete` releases from the session (`doc = None`, undo stack cleared)
  before the file unlink, then emits `map_deleted` so MainWindow leaves map
  mode and the selector's Maps branch refreshes. **Do not connect a
  `clicked`-driven confirm method directly** — `QPushButton.clicked` emits
  `clicked(bool checked)`, which silently overrides a `confirm=True` kwarg
  default to `False` on connect; wrap in a lambda (`clicked.connect(lambda:
  self._on_delete())`) so a real click always shows the dialog.
- **Starting Area (2×2 marker)**: a third single-object brush in gametiles mode
  (registry `core`/`Start Area`, slot `start_area`) mirroring the Hole/Camera
  Start pattern end-to-end — `palette.arm_start_area`/`start_area_armed` →
  `viewport.arm_start_area`; paint = place/move (the clicked cell is the 2×2's
  MIN corner, `MapSession.push_start_area_place` clamps it to
  `[0, cols−2]×[0, rows−2]`), erase = remove; a press on ANY of its 4 covered
  cells (eye on, no single-object brush armed) starts a drag whose release cell
  becomes the new min corner. **It renders as a closed 2×2 OUTLINE through
  `submit_overlay_lines` (E-24), never a sprite** — the engine emitters
  deliberately don't emit it, and the ghost is the same outline at the clamped
  hover cell (`_submit_start_area_outline`); ED-22-clean, same primitive as
  grid lines. Own `start_area` layer eye. `map_requirement_warnings` adds two
  warnings: `"starting area"` when the marker is missing and `"buildable tiles
  under starting area"` when any covered cell isn't a `tile_buildable`-slot
  code (the marker anchors the game's unlock grid but never forces tile
  states — painted terrain wins).
- **"None" tool**: `PalettePanel.TOOLS` starts with `"none"`, default-armed. It
  structurally cannot paint/erase/place deco but the base-cell check runs BEFORE
  tool dispatch, so dragging the base still works; a LEFT-drag under "none" (off the
  base) PANS. `viewport._ghost_items` returns nothing for `"none"`.
- **Palette import** (`editor/asset_import.py`): while a map is open the palette
  replaces `DetailsPanel`, so the normal importer is unreachable. The palette's
  "Import Spritesheet…" targets whichever brush is armed (deco → base → armed
  code's slot) and calls `editor.asset_import.import_idle_sheet(data_dir, registry,
  slot_key, png_path)` — a Qt-free, pygame-free helper (in `TestPurity`) that writes
  exactly ONE `idle` row (map/deco slots' `animations` vocab is `["idle"]` only).
  Emits `manifest_changed(slot)`, wired to `MainWindow._on_manifest_changed` (same
  handler as `DetailsPanel.entry_saved`/`entry_cleared`, which now ALSO calls
  `palette.refresh_icons()`).

## Verify
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it. State
exactly what you exercised (live editor run vs static read). Live runs are driven
by synthetic `QTest` events.
