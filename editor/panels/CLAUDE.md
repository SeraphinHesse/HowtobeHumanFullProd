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

## Phase 4 — selector / balancing / domains (ED-3/30/31)
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
  rows; `random_names` grows via the game's 9H add-name menu).
  - **Arrays of OBJECTS get `+ Row` / `− Row` (ER-5), gated ENTIRELY by the
    schema**: `can_add = "maxItems" not in node or len(items) < maxItems`,
    `can_remove = len(items) > minItems`. Every array that predates ER-5
    (`tiers`, `scale_tiers`, `round_counts`) has `minItems == maxItems`, so it
    shows **no buttons and is byte-identical** — that gate is the whole
    compatibility argument. `death_spawn.spawns` (`minItems: 1`, no `maxItems`)
    is the first genuinely resizable array: a per-era spawn table for a type that
    ships with one row. **Add COPIES THE LAST ROW** (the doc validated on load, so
    a copy is schema-valid by construction — no default-instance synthesis, no
    guessing at `pattern`/`minLength`); **remove pops the LAST row**, never a
    middle one, because these arrays are era-INDEXED and removing `[1]` would
    silently renumber every era after it. Both stage into `self._doc` like any
    other edit and re-dirty on the ARRAY path — `_refresh_dirty` compares whole
    subtrees, so add-then-remove cleans itself back up, and `_dots.get()` is
    None-safe for a path with no dot widget. Then the form REBUILDS, which is why
    `_rebuild_form` re-shows the dots of everything still in `self._dirty`: fresh
    widgets start with the dot hidden, and a rebuild that is not a domain switch
    would otherwise drop the pending marks of every other staged edit. The buttons
    carry `objectName` `rowadd:<path>` / `rowremove:<path>` so a test can assert
    WHICH arrays are resizable. Scalar arrays keep their fixed length.
  Scalar leaves:
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
  array — one file per domain because domains edit independently, unlike
  the old prototype's single combined snapshot). **"Version History"** opens
  `_HistoryDialog`, listing that domain's sessions newest-first; "Load into
  Editor" replays a past snapshot into the live widgets via
  `_apply_snapshot`/`_set_widget_value` (staged only — dirty dots reappear for
  whatever differs from the current baseline, nothing is written until the user
  clicks Save again); "Delete" removes an entry via
  `balancing_history.delete_session`. Undo (ED-24) deferred for balancing.
- **`domains.py`** (in `editor/`, not `panels/`, but governs the form):
  `domains(data_dir)`, `category_keys`/`is_domain_category`,
  `balancing_path`/`schema_path` — read-only derivation helpers.
  - **The domain list is DERIVED, never hardcoded** (AD-6; the `DOMAINS` constant
    is GONE): `domains(data_dir)` = slots.json's category order ∩ the categories
    carrying a `data/balancing/<key>.json` (D-10 order preserved). A new balancing
    domain therefore appears in selector + balancing form with **zero editor
    edits** — that is the whole point; do not re-introduce a list. It is a
    **function, not a module constant**, because every editor module is
    `data_dir`-injectable (tests run against a temp copy of `data/`) and a
    constant derived at import from the repo's `data/` would be silently wrong for
    any other tree.
  - **`is_domain_category(key)` (schema exists) is a DIFFERENT question from
    "is in `domains()`" (balancing file exists)** — keep them apart. A category
    *intended* as a domain (it has a `data/schemas/<key>.schema.json`) whose
    balancing file is missing is omitted from the tree **whole**, not degraded to
    an asset-only node: every leaf under a domain emits `domain_selected`, which
    would drive `BalancingPanel.set_domain` into a missing file. That rule is what
    keeps "no balancing file, no domain node" expressible now that the domain list
    is derived from those very files.

## Phase 5 — merged tree / details / entity preview
- **Merged tree** (`panels/selector.py`): top-level nodes = registry categories in
  `data/slots.json` order (the ones with a balancing file double as balancing
  domains — DERIVED, see `domains.py` above; vfx and `backgrounds` (10K menu art)
  are asset-only; `deco` is asset-only, nested as a CHILD of the "map" node —
  Phase 6
  follow-up). Children come from registry groups; the tree STOPS at the deepest
  group whose children are all leaf groups (a building TYPE like "Defender") —
  tiers/levels never appear in the tree. Signals: `node_selected(category,
  group_path)` on every selection, plus `domain_selected(str)` at ANY depth of a
  domain category, so balancing follows while browsing types. ● markers (ED-11)
  from `refresh_markers()` (pure `load_manifest`; clean label in UserRole+1). A
  domain category with no balancing file is omitted whole. The derived domain list
  is cached as `self._domains` (`_emit_selection` consults it on every click) and
  re-derived in `reload_registry()`.
- **"Add new X…" context menu** (AD-6, `add_requested = Signal(str)` → the form
  spec's `id`): right-clicking a **category ROOT** (payload `path == ()`) pops one
  entry per form spec whose `selector_context` is that category key; right-clicking
  **empty space** offers the single **Add New Category…** entry (`add-category` —
  that spec deliberately carries NO `selector_context`, since it *creates* a
  category and so belongs to no node). Group nodes, the Maps branch and map leaves
  offer **no menu**, and a category with no matching spec shows nothing rather than
  an empty popup. `editor/main.py::_on_add_requested` opens the `AgentFormDialog`
  for that spec — so **adding a form is still just adding a JSON file**; the
  selector hardcodes no form list.
  - Conventions worth keeping: the DEFAULT context-menu policy +
    `contextMenuEvent` (not `CustomContextMenu`); construction (`_context_menu`,
    returns `QMenu | None`) is split from display so tests never `exec()` a modal
    popup (`QAction.trigger()` is the test path); specs load FRESH per menu open
    (same rule as the launcher — a spec an agent just wrote needs no restart); and
    a spec-load failure degrades to **no menu** plus one stderr line, because an
    unhandled exception raised inside a Qt event handler can abort the process — a
    right-click must never be able to kill the editor.
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
  (ED-40/41). A *file* import copies the PNG to `data/sprites/imported/<slot>.png`
  AT IMPORT TIME; Save writes the manifest entry through `write_validated`; Clear
  (confirm dialog in UI; `clear_entry(confirm=False)` for tests) removes the entry
  + any PNG it leaves unreferenced. Row 0's animation combo is locked to `["idle"]`
  — the E-35 rule is UNREPRESENTABLE in the UI, not a save-time error. Frame sizes +
  animation vocabularies come from the registry per slot. No pygame here; Pillow
  reads sheet dimensions.
  - **Nine-slice margins (10L-A)**: 4 spinboxes (L/T/R/B), **ui category only**
    (gated on `self._context[0]`, `_slice_applies`), bounded by the slot's frame
    size (`registry.frame_size`, L/R capped at `frame_w`, T/B at `frame_h`),
    writing the optional manifest `slice` field. **All-zero ⇒ the key is
    omitted** — a slot with no nine-slice keeps a byte-identical entry, and
    zeroing the four spins and re-saving un-slices a previously-sliced slot
    (`save()` replaces the whole entry). Nine-slice is drawn on the HUD path
    only — the entity preview (`RenderItem`) deliberately ignores it; a
    `slice`-carrying draft still parses and previews as a plain scaled sprite.
  - **`ui` variants = skins**: the `ui` category's leaves offer "+ Variant"
    (`MainWindow._VARIANT_TARGETS`, added in A3) → `ui_button_v2`, …, i.e. one
    slot per button skin; its 4-row vocab is `idle/hover/pressed/disabled` (row
    0 locked to idle as everywhere).
  - **A slot's sheet is NOT `imported/<slot>.png`.** "Use Spritesheet…"
    (`panels/sheet_picker.py`) LINKS a slot to art already imported: the entry's
    `sheet` points at another slot's PNG and no bytes are copied, so one file backs
    many slots. The engine already resolved `sprites_dir / entry.sheet` verbatim
    (`engine/assets/store.py`) and the schema pattern always allowed it — the only
    thing that ever assumed otherwise was this panel. Read `self._sheet_ref` (from
    the entry); `imported/<slot>.png` is only the fresh-import destination and the
    no-entry fallback. **Clear refcounts before unlinking**
    (`asset_import.sheet_users` / `unreferenced_sheets`) — deleting a shared PNG
    blanks every other slot using it. Sheet-sharing rules live in `data/CLAUDE.md`.
  - **Static rows are DERIVED, never stored.** A row's "Static — don't animate"
    checkbox is a view of the manifest's existing `hidden` array (hide every column
    but one): `playback_order` drops hidden frames AFTER loop expansion, so a
    one-visible-frame row is already a still sprite. No schema key, no editor-only
    state, and a static row built by hand with the old checkboxes re-opens as
    static. `RowEditor.effective_hidden()` is the ONE place the array is computed —
    `to_dict` and the preview both call it, so they cannot disagree. A 1-frame row
    is deliberately not auto-static (nothing to disable). The loop spins grey out
    when static but keep their values: a loop over one visible frame is meaningless,
    not harmful, and rewriting a designer's numbers behind their back is worse.
  - **`panels/sheet_preview.py` draws a raw PNG, and that does NOT break ED-22.**
    The one-render-path rule bans a second Qt-side renderer of GAME CONTENT — the
    animated preview stays in the viewport, through `engine/render`. SheetPreview
    inspects the importer's own input file (no slot, no animation, no time
    resolved), like a thumbnail in a file dialog. `viewport.slot_qimage` can't serve
    here: it only ever yields the resolved idle frame, not an arbitrary frame or the
    sheet. Clicking a cell routes through that row's own `RowEditor`
    (`set_static_frame` / `toggle_hidden`), never a parallel state store, which is
    what keeps the checkboxes and the picture in sync. Each cell is captioned with
    its COLUMN index (white on a dark plate — it lands on arbitrary art, so a plain
    colour would be invisible against some sheet), the same number the hide
    checkboxes, the static radios and the manifest's `hidden`/`loop_start`/
    `loop_end` speak. `labels_visible()` drops them below `LABEL_MIN_CELL` px,
    where the plate would cover the frame it labels.
  - **Per-slot frame size (ER-5) is a TWO-FILE write, and that is not optional.**
    Frame size is a CATEGORY property; ER-1 added an optional per-slot override in
    `data/slots.json` (`{key, frame_w, frame_h}` beside the bare-string form), and
    the `Frame W/H` spinboxes are the only way to author it — `registry_ops
    .set_slot_frame_size` (pure, `write_validated`, `TestPurity`). Writing the
    CATEGORY's own size back removes the override (bare string again): that is how
    "reset to default" is expressed, and it keeps slots.json free of overrides that
    override nothing. **But `AssetStore.frame_size` resolves manifest entry >
    registry**, so a slot that already has an entry carries its own
    `frame_w`/`frame_h` and would keep rendering at the OLD size no matter what
    slots.json says. So the handler writes the override, reloads every cached
    registry (`registry_changed` → `MainWindow._reload_registries`, same path the
    `+ Variant` writes use), **re-cuts the sheet at the new size and re-saves the
    entry**. Leaving the two files disagreeing on disk is the failure mode the
    method exists to prevent. It commits on `editingFinished` (not `valueChanged`
    — typing "128" would otherwise write three times) and works with **no sheet
    imported**, which is the point: declaring the frame size BEFORE the import is
    what the importer slices and pads against.
  - **Clear's confirm dialog only fires because the connect is wrapped**
    (`clicked.connect(lambda: self.clear_entry())`). It was connected directly for
    months, so `clicked(bool checked=False)` landed in the `confirm=True` kwarg and
    Clear deleted the entry + PNG with NO dialog — the exact footgun recorded below
    for map_details' Delete, live in a second panel. Pinned by
    `TestClearAsksFirst`.
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

## Phase B4 — screen mode (`ui_screen_session.py`, `panels/screen_details.py`, `panels/_screen_primitives.py`; R3)
- **Selection** (`panels/selector.py`): the "Screens" branch is the FIRST
  child of the "ui" category node (mirrors the Maps branch under "map"), one
  leaf per `data/ui/screens/*.json`, labelled by the filename stem (screen
  docs carry no display-name field, unlike maps). A screen leaf emits
  `screen_selected(screen_id)` + `domain_selected("ui")` and NEVER
  `node_selected` — the `_MAP_ROLE`/`_SCREEN_ROLE` branches in `_emit_selection`
  are structurally identical. `screen_ids()`/`select_screen()`/
  `refresh_screens()` mirror `map_ids()`/`select_map()`/`refresh_maps()`
  exactly (selection-preserving rebuild).
- **`ViewportPanel.set_screen_mode(session, defaults)`** (mirrors
  `set_map_mode`): a FIXED 1280×720 logical canvas (`data/display.json`'s
  canonical resolution) scaled-to-fit the widget (`_screen_scale_offset`) —
  no viewport-driven zoom, the whole canvas is always visible, like the
  entity preview's parked camera. `defaults` is the FULL loaded
  `data/ui/screen_defaults.json` mapping (`{screen_id: {widgets, mock_note}}`),
  not a single screen's sub-dict — `_current_screen_defaults()` is the ONE
  place that indexes it by the open session's `screen_id`.
  - **Graceful degrade (E-37) is the LIVE state until B3 lands**: an empty/
    missing `defaults` (or a screen id absent from it) renders a red
    "no layout defaults yet — click Refresh Layouts" `HudText` and every
    widget interaction (`_screen_press`/`_screen_move`/`_nudge_selected`) is a
    no-op by construction — each checks `_current_screen_defaults()` first, so
    there is nothing to iterate over a missing key.
  - **ALL submission goes through `Renderer.submit_hud`** (ED-22 one render
    path): background (`{slot}` → whole-screen `HudSprite`, `{color}` →
    `HudRect`) first, then each widget. A widget with a `skin` override, or a
    kind-matched default (`doc["defaults"]["button_skin"]`/`"panel_skin"` for
    `kind in ("button", "panel")`), renders as `HudSprite(skin, dest, size,
    tint, animation=state, anim_time_ms=screen_anim_clock)`; the label rides
    alongside as a centred `HudText`. An UNSKINNED widget renders through
    `editor.panels._screen_primitives.fallback_hud_items` — flat rect(s) +
    centred label, keyed off the `kind` enum (`button|panel|label|backdrop|
    bar|field`, pinned by `screen_defaults.schema.json`); `label` draws text
    only, no box. `_screen_primitives` is pure (HUD dataclasses +
    `engine.render.fonts.TextMetrics` for vertical centring only — `HudText`'s
    own `align="center"` only shifts x) and NEVER imports `game/ui` — an
    accepted drift (layering rule), kept aligned to the real skinned look by
    eye + the B2 parity pin, not by shared code.
  - **Interaction**: click hit-tests widgets in REVERSE submission order
    (topmost = last-drawn); a selected widget gets a `HudLines` outline +
    4 `HudRect` corner handles. Drag-move/resize LIVE-mutates
    `session.doc["widgets"][id]["rect"]` directly (exactly like a tilemap
    paint stroke) and commits ONE `push_move`/`push_resize` on release —
    idempotent by the same argument as `map_session`'s stroke commands
    (pushing after the doc is already mutated just re-applies the same
    value). Arrow keys nudge 1 logical px per undoable `push_move` (no
    live-drag needed — `QUndoStack.push()` calls `redo()` itself).
    `ViewportPanel.setFocusPolicy(StrongFocus)` + `setFocus()` on select is
    what lets arrow keys reach it in the real app.
  - **State dropdown** (idle/hover/pressed/disabled): a floating `QComboBox`
    like the entity-preview animation combo, populated from
    `registry.category("ui").animations` (data-driven, not a literal list) —
    drives every skinned widget's `HudSprite.animation` for the frame.
  - **`refresh_screen_defaults(defaults)`** / **`set_selected_widget(id)`**:
    the "Refresh Layouts" re-render path and the screen_details↔viewport
    selection sync, respectively — neither touches mode/session state.
- **`ScreenDetailsPanel`** (`panels/screen_details.py`, right pane,
  `right_stack` index 2): widget list (from the current screen's defaults) →
  per-widget form (rect spinboxes + skin/font combos + Color/Text Color
  `QColorDialog` buttons + label edit + visible checkbox — the `_NoWheel*`
  widgets are IMPORTED from `editor.panels.balancing`, never copied).
  **Reset is per-FIELD, not per-widget**: every override-capable control
  carries its OWN compact "↺" `QToolButton` (`_field_row`/`_make_reset_button`)
  firing `push_field(widget_id, <key>, old, None)` for THAT key only — reset
  the rect while keeping an assigned skin, or vice versa. Rect is ONE button
  for the whole X/Y/W/H group (`_field_row` wraps all four spinboxes + one
  reset — it's stored as a single `rect` key, not four). Each reset button's
  enabled state (`_refresh_reset_buttons`) is "does THIS key currently have
  an override" — computed every `_populate_widget_form`, which also runs
  after every undo/redo (`indexChanged`), so a button never invites a no-op
  click. A separate **"Reset ALL to default"** button below the form still
  clears every override on the widget at once (one `push_field(..., None)`
  per key — `_DocFieldCommand`'s pruning drops the widget entry once it's
  empty either way) → screen-level Background picker (slot combo + color
  button + its OWN reset via `push_background(None)`, since background is a
  single key regardless of whether it's currently `{slot}` or `{color}`) → a
  `Defaults` `CollapsibleSection` (button_skin/panel_skin/font/text_color,
  each its own combo/button + `push_default_field(..., None)` reset) → Save
  (greyed out `not session.dirty`). Every edit AND every reset is an
  IMMEDIATE undoable push_* — NOT staged like `balancing.py`. Skin/background
  combos list `registry.
  group_slots("ui")`/`group_slots("ui", ("Backgrounds",))` (registry-driven,
  never hardcoded); font combo keys mirror `engine/render/fonts.py`'s private
  `_FONT_SPECS` (duplicated as a local tuple rather than importing a
  leading-underscore cross-module name). `session.undo_stack.indexChanged`
  refreshes the visible form/background/defaults section after Ctrl+Z/Y so
  nothing goes stale.
  - **Widget list is display-named, selection is UserRole-keyed (UH-4, D4)**:
    each `QListWidgetItem`'s TEXT is `widget_display_name(widget_id, spec)` —
    `spec.get("display_name") or widget_id` (`editor.panels._screen_primitives.
    widget_display_name`, the ONE resolution rule shared with the viewport
    caption below) — and its TOOLTIP is always the raw code id (the id's
    secondary surface). The selection contract itself never reads item text:
    `item.setData(Qt.ItemDataRole.UserRole, widget_id)` at construction, the
    list's `currentItemChanged` connect (not `currentTextChanged` — display
    names aren't guaranteed unique, the id is) reads `item.data(UserRole)` in
    `_on_widget_list_selected` and still emits the CODE id on
    `widget_selected`; `select_widget(widget_id)` scans rows for
    `item.data(UserRole) == widget_id` instead of `findItems(text, …)`.
    `display_name` is a cosmetic, editor-only field (`screen_defaults.json`,
    OPTIONAL per widget, authored by `tools/export_ui_layouts.py`'s
    `_DISPLAY_NAMES` mapping) — it never appears in an override doc, and
    `_populate_widget_form`/every `push_*` call is unchanged, still keyed by
    the code id via `self._current_widget`. The viewport's selection outline
    (`viewport._submit_screen_selection`) gains a matching `HudText` caption
    above the outline using the SAME `widget_display_name` helper, so the
    list and the canvas can never show two different names for one widget.
- **`MainWindow`**: `_on_screen_selected` → `_resolve_dirty(session=None)`
  (generalized to take ANY session — every pre-B4 call site passes none and
  gets `map_session`; screen mode passes `self.screen_session`) →
  `session.open` → `_enter_screen_mode()` (loads
  `data/ui/screen_defaults.json`, wires viewport + screen_details, switches
  `right_stack`) / `_leave_screen_mode()`. Ctrl+Z/Y route through
  `_active_undo_stack()` (screen session while `viewport.in_screen_mode()`,
  else map session). **"Refresh Layouts"** toolbar action →
  `RunControls.export_layouts()` (same tracked-`QProcess` + console-streaming
  path as Build, distinguished by the `which` string on the shared
  `started`/`finished` signals) → on exit 0, reloads defaults into viewport +
  screen_details + `selector.refresh_screens()`.
- **`_enter_screen_mode()` reloads the asset manifest on EVERY entry**
  (`viewport.reload_assets()`, ED-42, called first thing — before
  `_load_screen_defaults()`/`set_screen_mode`): the viewport's `AssetStore`
  is built once at `ViewportPanel.__init__` and otherwise only rebuilt by an
  explicit `reload_assets()`/`reload_registry()` call (`engine/assets/
  CLAUDE.md` "no cache invalidation") — without this, an editor left running
  while `data/sprites/asset_manifest.json` changed on disk (a fresh import,
  a branch switch, another process's write) kept showing grey-X/flat-rect
  skins in screen mode until restart, even though the doc's `skin`
  override/`defaults.button_skin` resolved fine (a `HudSprite` is emitted
  either way — `skin` comes from the screen doc, not the manifest; only the
  RESOLVED FRAME was stale). `_on_export_layouts_finished` (the "Refresh
  Layouts" completion handler) reloads too, for the same reason. Both calls
  are cheap: `AssetStore` loads sheet PNGs lazily, so a reload is a fresh
  manifest-JSON read plus a fresh (empty-cache) `AssetStore`/`Renderer`, not
  a bulk re-decode. Regression coverage:
  `test_editor_viewport.TestScreenModeReloadOnEntry` (fails red without the
  `reload_assets()` call — proven by reverting it) and
  `TestScreenModeRealSkinRenderPath` (the real on-disk-doc + real-manifest
  render path — every earlier skin test only exercised
  `push_skin_assign` on an in-memory session, never a populated screen
  JSON, so a manifest-resolution regression here had no test that could
  have caught it).

## Phase UH-2 — per-mode screen views + auto Refresh Layouts on entry
- **`building_panel` gets five views, exported by UH-1's per-mode snapshot
  exporter** (`unlock`/`construct`/`upgrade`/`base_info`/`preview`) instead of
  one superimposed pile of every mode's widgets. `data/ui/screen_defaults.json`
  per-screen shape is unchanged for every OTHER screen; `building_panel` gains
  an optional `views` key: `{view_id: {widgets, mock_note}}` — the SAME shape
  as a per-screen entry, so the resolver below returns either interchangeably.
  Top-level `widgets` stays the required first-wins union (back-compat: the
  game's known-id check and any pre-UH-2 reader still work); the editor
  ignores it whenever `views` is present.
- **`VIEW_ORDER`/`ordered_views()`** (`editor/ui_screen_session.py`, module
  level, one authority) pin the game-mode display order
  (`unlock, construct, upgrade, base_info, preview`) — needed because D-3's
  sorted-keys JSON alphabetizes the `views` object (`base_info` first).
  Selector and `MainWindow` both import it from here.
- **`UIScreenSession.view`** (non-doc, non-undoable) is the active view, or
  `None` for a screen's single implicit view (every screen but
  building_panel). `open()` resets it to `None`; `set_view(view_id)` sets it
  and emits `view_changed` — the session does NOT validate view names (it
  holds only the override doc, not defaults); validity is the caller's job.
- **One resolution point per consumer, no per-call-site changes.**
  `ViewportPanel._current_screen_defaults()` and
  `ScreenDetailsPanel._current_screen_defaults()` both: get the screen's
  entry, and if it carries `views` and the session's `view` names one, return
  `entry["views"][view]` instead of `entry`. Because every render/hit-test/
  nudge path and the widget list already funnel through these two functions,
  this single change IS the per-view filtering — `_refresh_widget_list` needs
  no code change, it just iterates whichever dict comes back.
  `ViewportPanel._effective_rect` layers the session doc's override on top of
  whichever `defaults` came back, so an id present in several views (`panel`,
  `close_btn`) carries ONE override applying in every view (D2) with zero
  extra plumbing.
- **Selector**: the "Screens" branch (B4) gains a child leaf per view under
  any screen whose `screen_defaults.json` entry carries `views` — a NEW
  `_screen_views_from_disk()` helper (a fresh degrade-to-`{}` read mirroring
  `MainWindow._load_screen_defaults`, approved over adding a MainWindow
  injection path) reads the file itself. View leaves carry `_VIEW_ROLE`
  (`(screen_id, view_id)`) and emit `screen_view_selected(screen_id,
  view_id)` + `domain_selected("ui")` — never `screen_selected`/
  `node_selected` (the exact `_SCREEN_ROLE` pattern, one level deeper).
  `select_screen_view()` mirrors `select_screen()`; `refresh_screens()`'s
  selection-preserving rebuild also preserves a selected VIEW leaf, falling
  back to the screen leaf if the view vanished.
- **`MainWindow` wiring**: `_on_screen_selected` (a bare screen-leaf pick)
  sets the DEFAULT view — `ordered_views(views)[0]` if the screen has views
  (`"unlock"` for building_panel), else `None` — then calls
  `_enter_screen_mode()`. New `_on_screen_view_selected(screen_id, view_id)`
  is the identical flow (same-doc fast path; `_resolve_dirty` only when
  opening a DIFFERENT screen) but sets the CHOSEN view. **View switching
  re-runs `_enter_screen_mode()` in full** — `viewport.set_screen_mode`
  already resets widget selection/drag state and `screen_details.set_defaults`
  → `_on_screen_opened` rebuilds the list/form, so no stale-selection handling
  is needed; the repeated `reload_assets()` is cheap by design (above).
  Switching views on the SAME open doc never triggers the dirty prompt and
  never clears the undo stack (only `_resolve_dirty` does that, and it's
  skipped on the same-doc path).
- **Auto Refresh Layouts on screen-mode entry**: `MainWindow(...,
  auto_refresh_layouts=True)` (injectable, the `prefs_path=` precedent) plus
  `self._screen_mode_entered` gate `_enter_screen_mode()`: immediately after
  `reload_assets()`, if `auto_refresh_layouts` and not yet entered this
  session, call `self.run_controls.export_layouts()` (the SAME tracked-
  QProcess path "Refresh Layouts" the toolbar button uses — its own
  completion handler already refreshes defaults/status bar; a run already in
  flight silently refuses the auto-call, run_controls' one-tracked-process
  rule). Set the flag true; `_leave_screen_mode()` resets it, so re-entering
  screen mode later fires again exactly once. Switching views or screens
  WHILE already in screen mode does NOT re-fire it. Every test-suite
  `MainWindow(...)` construction passes `auto_refresh_layouts=False` except
  the dedicated auto-refresh tests (which stub `run_controls.export_layouts`
  with a recorder — never a real subprocess in tests).

## Verify
Launch `py editor/main.py` and exercise the changed panel; for data-writing
features, confirm the JSON on disk validates and a Play subprocess loads it. State
exactly what you exercised (live editor run vs static read). Live runs are driven
by synthetic `QTest` events.
